"""Core agent loop: provider call, tool execution, and iteration control."""

from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from heagent.agent.middleware import MiddlewareFn, Request, compose
from heagent.config import get_settings
from heagent.context.window_reset import WindowReset, WindowResetConfig
from heagent.engine import EngineContainer, ExecutionStatus, RunContext, RunStatus
from heagent.exceptions import BudgetExceeded
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard
from heagent.types import Message, ProviderResponse, Role, StreamEvent, TokenUsage, ToolCall, ToolResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from heagent.context.compressor import ContextCompressor
    from heagent.context.session import SessionStore
    from heagent.cron.jobs import JobStore
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """Mutable state for one loop execution."""

    messages: list[Message] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 50
    results: list[ToolResult] = field(default_factory=list)


@dataclass
class _ResumeState:
    """Prebuilt loop state injected into ``run()`` by ``resume()``."""

    state: AgentState
    run_context: RunContext
    prompt: str
    system: str | None


class AgentLoop:
    """Iterative provider/tool loop with lightweight runtime governance."""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        registry: ToolRegistry | None = None,
        guard: SafetyGuard | None = None,
        middlewares: list[MiddlewareFn] | None = None,
        max_iterations: int | None = None,
        skills: SkillStore | None = None,
        facts: FactStore | None = None,
        profile: ProfileStore | None = None,
        session: SessionStore | None = None,
        compressor: ContextCompressor | None = None,
        window_reset: WindowResetConfig | None = None,
        context_dir: str | None = None,
        soul: SoulStore | None = None,
        cron_store: JobStore | None = None,
        engine: EngineContainer | None = None,
        run_context: RunContext | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry or ToolRegistry.get()
        self.guard = guard or SafetyGuard()
        self.middlewares = middlewares or []
        self.skills = skills
        self.facts = facts
        self.profile = profile
        self.session = session
        if compressor is not None and window_reset is not None:
            raise ValueError(
                "ContextCompressor and window_reset are mutually exclusive (D3); "
                "enable one context-management strategy per AgentLoop."
            )
        self.compressor = compressor
        self.window_reset = (
            WindowReset(provider, config=window_reset) if window_reset is not None else None
        )
        self.context_dir = context_dir
        self.soul = soul
        self.cron_store = cron_store
        self.engine = engine or EngineContainer.default(workspace_root=context_dir)
        self._run_context_template = run_context
        self.last_run_context: RunContext | None = None
        self.last_usage: TokenUsage | None = None
        self.last_iteration: int | None = None

        settings = get_settings()
        self.max_iterations = max_iterations or settings.max_iterations

    async def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        session_id: str | None = None,
        _resume: _ResumeState | None = None,
    ) -> str:
        """Run until the provider returns a final non-tool response."""
        if _resume is not None:
            state = _resume.state
            run_context = _resume.run_context
            system_content = _resume.system
            prompt = _resume.prompt
            accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            self._emit("run_started", run_context=run_context, details={"resume": True})
        else:
            state = AgentState(max_iterations=self.max_iterations)
            accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            run_context = self._ensure_run_context(session_id=session_id)

            if self.session and session_id:
                prior = self.session.load(session_id)
                if prior:
                    state.messages.extend(m for m in prior if m.role != Role.SYSTEM)
                    logger.debug("Restored %d messages from session '%s'", len(prior), session_id)

            system_content = self._build_system(system, prompt=prompt)
            if system_content:
                state.messages.append(Message(role=Role.SYSTEM, content=system_content))
            state.messages.append(Message(role=Role.USER, content=prompt))

            self._start_run_record(run_context, prompt=prompt, system=system_content)
            self._emit("run_started", run_context=run_context, details={"session_id": session_id or ""})

        response: ProviderResponse | None = None

        with self._runtime_scope(run_context):
            try:
                while True:
                    state.iteration += 1
                    run_context.touch(iteration=state.iteration)
                    self._emit("iteration_started", run_context=run_context)

                    if state.iteration > state.max_iterations:
                        raise BudgetExceeded(f"Exceeded {state.max_iterations} iterations without final answer")

                    response = await self._call_provider(state, run_context=run_context)
                    if response.usage:
                        accumulated = self._add_usage(accumulated, response.usage)

                    if self.compressor and response.usage:
                        settings = get_settings()
                        compressed = await self.compressor.compress(
                            state.messages,
                            token_count=response.usage.total_tokens,
                            max_tokens=settings.max_context_tokens,
                        )
                        if compressed is not state.messages:
                            before = len(state.messages)
                            state.messages = compressed
                            logger.info("Context compressed: %d -> %d messages", before, len(state.messages))
                            self._emit(
                                "context_compressed",
                                run_context=run_context,
                                details={"before": before, "after": len(state.messages)},
                            )

                    state.messages.append(
                        Message(role=Role.ASSISTANT, content=response.content, tool_calls=response.tool_calls or None)
                    )
                    self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

                    if not response.tool_calls:
                        break

                    tool_results = await self._execute_tools(response.tool_calls, state, run_context=run_context)
                    for tool_result in tool_results:
                        state.messages.append(
                            Message(role=Role.TOOL, content=tool_result.content, tool_call_id=tool_result.tool_call_id)
                        )
                    self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

                    if self.window_reset and response.usage:
                        settings = get_settings()
                        if self.window_reset.should_trigger(
                            token_count=response.usage.total_tokens,
                            max_tokens=settings.max_context_tokens,
                        ):
                            before = len(state.messages)
                            state.messages = await self.window_reset.reset(
                                run_context=run_context,
                                original_prompt=prompt,
                                messages=state.messages,
                            )
                            logger.info(
                                "Window reset: %d -> %d messages (segment=%s)",
                                before,
                                len(state.messages),
                                run_context.metadata.get("segment"),
                            )
                            self._emit(
                                "window_reset",
                                run_context=run_context,
                                details={"before": before, "after": len(state.messages)},
                            )
                            self._checkpoint(
                                run_context, prompt=prompt, system=system_content, state=state
                            )

                final_answer = response.content if response is not None else ""
                run_context.touch(status=RunStatus.COMPLETED, iteration=state.iteration)
                self._checkpoint(
                    run_context,
                    prompt=prompt,
                    system=system_content,
                    state=state,
                    final_answer=final_answer,
                )
                self._emit(
                    "run_completed",
                    run_context=run_context,
                    details={"answer_length": len(final_answer)},
                )
                return final_answer
            except Exception as exc:
                run_context.touch(status=RunStatus.FAILED, iteration=state.iteration)
                self._checkpoint(
                    run_context,
                    prompt=prompt,
                    system=system_content,
                    state=state,
                    error=str(exc),
                )
                self._emit(
                    "run_failed",
                    run_context=run_context,
                    details={"error": str(exc)},
                )
                raise
            finally:
                if self.session and session_id:
                    self.session.save(session_id, state.messages)
                    logger.debug("Saved %d messages to session '%s'", len(state.messages), session_id)
                self.last_usage = accumulated
                self.last_iteration = state.iteration
                self.last_run_context = run_context

    async def run_stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        session_id: str | None = None,
        _resume: _ResumeState | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Run the loop and yield streamed text/tool events.

        ``_resume`` (set by :meth:`resume_stream`) skips session/system
        initialization and continues from a prebuilt state, mirroring
        :meth:`run`'s resume branch.
        """
        if _resume is not None:
            state = _resume.state
            run_context = _resume.run_context
            system_content = _resume.system
            prompt = _resume.prompt
            accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            self._emit("run_started", run_context=run_context, details={"resume": True, "stream": True})
        else:
            state = AgentState(max_iterations=self.max_iterations)
            accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            run_context = self._ensure_run_context(session_id=session_id)

            if self.session and session_id:
                prior = self.session.load(session_id)
                if prior:
                    state.messages.extend(m for m in prior if m.role != Role.SYSTEM)

            system_content = self._build_system(system, prompt=prompt)
            if system_content:
                state.messages.append(Message(role=Role.SYSTEM, content=system_content))
            state.messages.append(Message(role=Role.USER, content=prompt))

            self._start_run_record(run_context, prompt=prompt, system=system_content)
            self._emit("run_started", run_context=run_context, details={"stream": True})

        with self._runtime_scope(run_context):
            try:
                while True:
                    state.iteration += 1
                    run_context.touch(iteration=state.iteration)
                    self._emit("iteration_started", run_context=run_context)

                    if state.iteration > state.max_iterations:
                        raise BudgetExceeded(f"Exceeded {state.max_iterations} iterations without final answer")

                    tools = self.registry.enabled_schemas()
                    full_content = ""
                    tool_calls: list[ToolCall] = []
                    chunk_usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
                    model = ""
                    finish_reason = ""

                    async for chunk in self.provider.stream(state.messages, tools=tools or None):
                        if chunk.content:
                            full_content += chunk.content
                            yield StreamEvent(type="text", text=chunk.content)
                        if chunk.tool_calls:
                            tool_calls.extend(chunk.tool_calls)
                        if chunk.usage and chunk.usage.total_tokens > 0:
                            chunk_usage = chunk.usage
                        if chunk.model:
                            model = chunk.model
                        if chunk.finish_reason:
                            finish_reason = chunk.finish_reason

                    accumulated = self._add_usage(accumulated, chunk_usage)
                    response = ProviderResponse(
                        content=full_content,
                        tool_calls=tool_calls,
                        usage=chunk_usage,
                        model=model,
                        finish_reason=finish_reason or "stop",
                    )

                    if self.compressor and response.usage:
                        settings = get_settings()
                        compressed = await self.compressor.compress(
                            state.messages,
                            token_count=response.usage.total_tokens,
                            max_tokens=settings.max_context_tokens,
                        )
                        if compressed is not state.messages:
                            before = len(state.messages)
                            state.messages = compressed
                            logger.info("Context compressed: %d -> %d messages", before, len(state.messages))
                            self._emit(
                                "context_compressed",
                                run_context=run_context,
                                details={"before": before, "after": len(state.messages)},
                            )

                    state.messages.append(
                        Message(role=Role.ASSISTANT, content=response.content, tool_calls=response.tool_calls or None)
                    )

                    if not response.tool_calls and finish_reason == "tool_calls":
                        response = await self._call_provider(state, run_context=run_context)
                        state.messages[-1] = Message(
                            role=Role.ASSISTANT,
                            content=response.content,
                            tool_calls=response.tool_calls or None,
                        )
                        accumulated = self._add_usage(accumulated, response.usage)

                    self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

                    if not response.tool_calls:
                        run_context.touch(status=RunStatus.COMPLETED, iteration=state.iteration)
                        self._checkpoint(
                            run_context,
                            prompt=prompt,
                            system=system_content,
                            state=state,
                            final_answer=response.content,
                        )
                        self._emit(
                            "run_completed",
                            run_context=run_context,
                            details={"answer_length": len(response.content)},
                        )
                        yield StreamEvent(type="done", final_answer=response.content)
                        break

                    tool_results = await self._execute_tools(response.tool_calls, state, run_context=run_context)
                    for tool_call, tool_result in zip(response.tool_calls, tool_results, strict=True):
                        yield StreamEvent(type="tool_call", tool_name=tool_call.name)
                        yield StreamEvent(type="tool_result", tool_result_content=tool_result.content)
                        state.messages.append(
                            Message(role=Role.TOOL, content=tool_result.content, tool_call_id=tool_result.tool_call_id)
                        )
                    self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

                    if self.window_reset and response.usage:
                        settings = get_settings()
                        if self.window_reset.should_trigger(
                            token_count=response.usage.total_tokens,
                            max_tokens=settings.max_context_tokens,
                        ):
                            before = len(state.messages)
                            state.messages = await self.window_reset.reset(
                                run_context=run_context,
                                original_prompt=prompt,
                                messages=state.messages,
                            )
                            logger.info(
                                "Window reset (stream): %d -> %d messages (segment=%s)",
                                before,
                                len(state.messages),
                                run_context.metadata.get("segment"),
                            )
                            self._emit(
                                "window_reset",
                                run_context=run_context,
                                details={"before": before, "after": len(state.messages)},
                            )
                            self._checkpoint(
                                run_context, prompt=prompt, system=system_content, state=state
                            )
            except Exception as exc:
                run_context.touch(status=RunStatus.FAILED, iteration=state.iteration)
                self._checkpoint(
                    run_context,
                    prompt=prompt,
                    system=system_content,
                    state=state,
                    error=str(exc),
                )
                self._emit(
                    "run_failed",
                    run_context=run_context,
                    details={"error": str(exc)},
                )
                raise
            finally:
                if self.session and session_id:
                    self.session.save(session_id, state.messages)
                self.last_usage = accumulated
                self.last_iteration = state.iteration
                self.last_run_context = run_context

    async def resume(self, run_id: str) -> str:
        """Resume an unfinished run by id, rebuilding context from its progress summary.

        Loads the persisted snapshot; if COMPLETED, returns the stored final answer.
        Otherwise rebuilds a fresh window from ``metadata['progress_summary']`` (or
        falls back to the snapshot's last messages) and continues under the same
        run_id. For streaming, use :meth:`resume_stream`.
        """
        snapshot = self.engine.run_store.load(run_id)
        if snapshot is None:
            raise ValueError(f"No run snapshot found for run_id={run_id!r}")
        if snapshot.context.status == RunStatus.COMPLETED:
            return snapshot.final_answer or ""

        progress = snapshot.context.metadata.get("progress_summary")
        if progress:
            messages = WindowReset.build_resume_messages(
                original_prompt=snapshot.prompt, summary=progress
            )
        else:
            messages = [m.model_copy(deep=True) for m in snapshot.messages]

        state = AgentState(
            messages=messages,
            max_iterations=self.max_iterations,
            iteration=snapshot.context.iteration,
        )
        return await self.run(
            snapshot.prompt,
            system=snapshot.system,
            _resume=_ResumeState(
                state=state,
                run_context=snapshot.context,
                prompt=snapshot.prompt,
                system=snapshot.system,
            ),
        )

    async def resume_stream(self, run_id: str) -> AsyncIterator[StreamEvent]:
        """Streaming variant of :meth:`resume`.

        A COMPLETED run yields a single ``done`` event carrying the cached final
        answer; an unfinished run rebuilds a fresh window from
        ``metadata['progress_summary']`` (or the snapshot's last messages) and
        streams the continuation under the same run_id.
        """
        snapshot = self.engine.run_store.load(run_id)
        if snapshot is None:
            raise ValueError(f"No run snapshot found for run_id={run_id!r}")
        if snapshot.context.status == RunStatus.COMPLETED:
            yield StreamEvent(type="done", final_answer=snapshot.final_answer or "")
            return

        progress = snapshot.context.metadata.get("progress_summary")
        if progress:
            messages = WindowReset.build_resume_messages(
                original_prompt=snapshot.prompt, summary=progress
            )
        else:
            messages = [m.model_copy(deep=True) for m in snapshot.messages]

        state = AgentState(
            messages=messages,
            max_iterations=self.max_iterations,
            iteration=snapshot.context.iteration,
        )
        async for event in self.run_stream(
            snapshot.prompt,
            system=snapshot.system,
            _resume=_ResumeState(
                state=state,
                run_context=snapshot.context,
                prompt=snapshot.prompt,
                system=snapshot.system,
            ),
        ):
            yield event

    @staticmethod
    def _add_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
        """Add two token usage counters together."""
        return TokenUsage(
            prompt_tokens=a.prompt_tokens + b.prompt_tokens,
            completion_tokens=a.completion_tokens + b.completion_tokens,
            total_tokens=a.total_tokens + b.total_tokens,
        )

    def _build_system(self, user_system: str | None, prompt: str = "") -> str | None:
        """Build one merged system prompt with context, skills, and memory."""
        parts: list[str] = []
        if user_system:
            parts.append(user_system)

        if self.soul:
            soul_content = self.soul.load()
            if soul_content:
                parts.insert(0, f"<identity>\n{soul_content}\n</identity>")
                logger.debug("Injected SOUL.md personality into system prompt")

        if self.context_dir:
            settings = get_settings()
            if settings.context_files_enabled:
                from heagent.context.loader import load_context_files

                context = load_context_files(self.context_dir)
                if context:
                    parts.append(f"<project-context>\n{context}\n</project-context>")
                    logger.debug("Injected project context files into system prompt")

        if self.skills:
            settings = get_settings()
            matched = self.skills.matching_skills(
                prompt,
                threshold=settings.skill_match_threshold,
            )[: settings.skill_max_auto_invoke]

            if matched:
                for skill_name in matched:
                    self.skills.record_usage(skill_name)
                contents: list[str] = []
                for name in matched:
                    raw = self.skills.load(name)
                    if raw:
                        contents.append(raw)
                if contents:
                    block = "\n\n---\n\n".join(contents)
                    parts.append(
                        "<skills>\n"
                        "The following skills are relevant to the user's request:\n\n"
                        f"{block}\n\n"
                        "You can use skill_list to see all skills, "
                        "skill_create to add new ones, or skill_update to modify.\n"
                        "</skills>"
                    )
                    logger.debug("Auto-invoked %d skill(s): %s", len(matched), matched)
            elif self.skills.list_skills():
                parts.append(
                    "<skills>\n"
                    "No skills matched the current request. "
                    "You can use skill_create to save reusable patterns, "
                    "skill_list to browse existing skills, or skill_update to refine them.\n"
                    "</skills>"
                )

        if self.facts:
            facts_list = self.facts.load()
            if facts_list:
                items = "\n".join(f"- {fact}" for fact in facts_list)
                parts.append(
                    "<memory>\n"
                    "The following facts are remembered from previous conversations:\n\n"
                    f"{items}\n"
                    "</memory>"
                )
                logger.debug("Injected %d fact(s) into system prompt", len(facts_list))

        if self.facts and get_settings().memory_nudge_enabled:
            parts.append(
                "<memory-nudge>\n"
                "After completing a complex task or learning something important, "
                "consider using fact_add to save key insights for future sessions.\n"
                "</memory-nudge>"
            )

        if self.profile:
            profile_text = self.profile.load()
            if profile_text:
                parts.append(
                    "<profile>\n"
                    "User profile (adapt your responses accordingly):\n\n"
                    f"{profile_text}\n"
                    "</profile>"
                )
                logger.debug("Injected user profile into system prompt")

        return "\n\n".join(parts) if parts else None

    async def _call_provider(
        self,
        state: AgentState,
        *,
        run_context: RunContext | None = None,
    ) -> ProviderResponse:
        """Call the provider, optionally through middleware."""
        tools = self.registry.enabled_schemas()

        from heagent.context.tokens import count_tokens

        estimated = count_tokens(state.messages)
        logger.debug("Calling provider: %d messages, ~%d tokens estimated", len(state.messages), estimated)
        self._emit(
            "provider_call_started",
            run_context=run_context,
            details={"message_count": len(state.messages), "estimated_tokens": estimated},
        )

        async def handler(req: Request) -> ProviderResponse:
            return await self.provider.send(req.messages, tools=req.tools or None)

        if self.middlewares:
            chain = compose(self.middlewares, handler)
            response = cast("ProviderResponse", await chain(Request(messages=state.messages, tools=tools)))
        else:
            response = await handler(Request(messages=state.messages, tools=tools))

        if response.usage and response.usage.total_tokens > 0:
            logger.debug(
                "Provider response: %d actual tokens (estimated: %d, delta: %+d)",
                response.usage.total_tokens,
                estimated,
                response.usage.total_tokens - estimated,
            )
        self._emit(
            "provider_call_completed",
            run_context=run_context,
            details={
                "model": response.model,
                "finish_reason": response.finish_reason,
                "actual_tokens": response.usage.total_tokens,
            },
        )
        return response

    async def _execute_tools(
        self,
        calls: list[ToolCall],
        state: AgentState,
        *,
        run_context: RunContext | None = None,
    ) -> list[ToolResult]:
        """Execute tool calls concurrently."""
        self._emit(
            "tool_batch_started",
            run_context=run_context,
            details={"count": len(calls)},
        )
        tasks = [self._execute_one(call, run_context=run_context) for call in calls]
        results = list(await asyncio.gather(*tasks))
        state.results.extend(results)
        self._emit(
            "tool_batch_completed",
            run_context=run_context,
            details={"count": len(results), "errors": sum(1 for result in results if result.is_error)},
        )
        return results

    async def _execute_one(
        self,
        call: ToolCall,
        *,
        run_context: RunContext | None = None,
    ) -> ToolResult:
        """Execute one tool call end to end.

        Idempotent via ExecutionLedger: a repeated ``tool_call.id`` (e.g. re-sent
        by the model after a window reset) hits the cached COMPLETED result
        instead of re-running the handler with side effects.
        """
        cache_key: str | None = None
        if run_context is not None:
            cache_key = f"{run_context.run_id}:{call.id}"
            claim = self.engine.ledger.acquire(cache_key, run_id=run_context.run_id)
            if not claim.acquired and claim.record.status == ExecutionStatus.COMPLETED:
                cached = claim.record.metadata.get("result")
                if cached is not None:
                    logger.debug("Ledger cache hit for tool_call %s", call.id)
                    self._emit(
                        "tool_call_cached",
                        run_context=run_context,
                        tool_name=call.name,
                        details={},
                    )
                    return ToolResult(tool_call_id=call.id, content=cached)

        verdict = self.engine.policy.evaluate_tool_call(call, context=run_context)
        handler = self.registry.get_handler(call.name)
        if handler is None:
            self._emit(
                "tool_call_failed",
                run_context=run_context,
                tool_name=call.name,
                details={"error": "unknown tool"},
            )
            result = ToolResult(tool_call_id=call.id, content=f"Unknown tool: {call.name}", is_error=True)
        else:
            result = await self.engine.executor.execute(
                call=call,
                verdict=verdict,
                guard=self.guard,
                handler=self._invoke_handler,
                run_context=run_context,
                emit=self._emit,
            )

        if cache_key is not None:
            if result.is_error:
                self.engine.ledger.fail(cache_key, result.content)
            else:
                self.engine.ledger.complete(cache_key, metadata={"result": result.content})
        return result

    async def _invoke_handler(self, call: ToolCall) -> object:
        """Resolve and invoke the registered handler for one tool call."""
        handler = self.registry.get_handler(call.name)
        if handler is None:
            raise RuntimeError(f"Unknown tool: {call.name}")
        return await self._invoke(handler, call)

    async def _invoke(self, handler: object, call: ToolCall) -> object:
        """Call a sync or async tool handler."""
        fn = cast("Callable[..., Any]", handler)
        if asyncio.iscoroutinefunction(fn):
            return await fn(**call.arguments)
        return fn(**call.arguments)

    def _ensure_run_context(self, *, session_id: str | None) -> RunContext:
        """Return a fresh run context for the current execution."""
        if self._run_context_template is not None:
            context = self._run_context_template
            self._run_context_template = None
            if session_id and context.session_id is None:
                context.session_id = session_id
            return context
        return self.engine.create_run_context(session_id=session_id, workspace_root=self.context_dir)

    @contextmanager
    def _runtime_scope(self, run_context: RunContext) -> Iterator[None]:
        """Bind tool runtimes for the duration of a single run."""
        from heagent.tools.builtins.cron import bind_cron_tools
        from heagent.tools.builtins.memory import bind_memory_tools
        from heagent.tools.builtins.skills import bind_skill_tools
        from heagent.tools.builtins.subagent import bind_subagent_tools
        from heagent.tools.path_safety import bind_workspace_root

        with ExitStack() as stack:
            stack.enter_context(bind_workspace_root(Path(run_context.workspace_root)))
            stack.enter_context(bind_skill_tools(self.skills))
            stack.enter_context(bind_memory_tools(facts=self.facts, profile=self.profile))
            stack.enter_context(bind_cron_tools(self.cron_store))
            stack.enter_context(
                bind_subagent_tools(
                    self.provider,
                    registry=self.registry,
                    guard=self.guard,
                    skills=self.skills,
                    facts=self.facts,
                    profile=self.profile,
                    compressor=self.compressor,
                    context_dir=self.context_dir,
                    soul=self.soul,
                    engine=self.engine,
                    parent_run_id=run_context.run_id,
                    run_context=run_context,
                )
            )
            yield

    def _start_run_record(self, run_context: RunContext, *, prompt: str, system: str | None) -> None:
        """Write the initial run snapshot on a best-effort basis."""
        try:
            self.engine.run_store.start(run_context, prompt=prompt, system=system)
        except Exception:
            logger.exception("Failed to start run record for '%s'", run_context.run_id)

    def _checkpoint(
        self,
        run_context: RunContext,
        *,
        prompt: str,
        system: str | None,
        state: AgentState,
        final_answer: str | None = None,
        error: str | None = None,
    ) -> None:
        """Persist run progress on a best-effort basis."""
        try:
            self.engine.run_store.checkpoint(
                run_context,
                prompt=prompt,
                system=system,
                messages=state.messages,
                results=state.results,
                final_answer=final_answer,
                error=error,
            )
        except Exception:
            logger.exception("Failed to checkpoint run '%s'", run_context.run_id)

    def _emit(
        self,
        event_type: str,
        *,
        run_context: RunContext | None = None,
        tool_name: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Publish one runtime event on a best-effort basis."""
        try:
            self.engine.events.publish(
                event_type,
                run_id=run_context.run_id if run_context is not None else "",
                iteration=run_context.iteration if run_context is not None else 0,
                tool_name=tool_name,
                details=details or {},
            )
        except Exception:
            logger.exception("Failed to emit engine event '%s'", event_type)
