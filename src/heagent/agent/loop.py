"""核心 Agent 循环 —— Provider 调用、工具执行与迭代控制的编排中枢。

``AgentLoop`` 是 HeAgent 的顶层编排器：它反复执行「调 LLM → 解析工具调用 → 执行
工具 → 把结果喂回 LLM」的循环，直到 LLM 给出不含工具调用的最终回答（或触发迭代
上限 / 预算上限）。每一轮还穿插**运行时治理**（``engine``：准入/审批/沙箱裁决、
运行记录持久化、事件发布）与**上下文管理**（就地压缩 ``compressor`` 或窗口重置
``window_reset``，二者互斥）。

本模块对外的主入口：
  - :meth:`AgentLoop.run`          —— 非流式执行，返回最终回答字符串；
  - :meth:`AgentLoop.run_stream`   —— 流式执行，逐个 yield ``StreamEvent``；
  - :meth:`AgentLoop.resume` / ``resume_stream`` —— 按 run_id 恢复未完成的运行。

完整数据流 / 调用链见 ``docs/frame.md``；本文件的注释聚焦于循环内部逐步流程。
"""

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
    """单次循环执行的可变内部状态（dataclass：轻量、可变、无需序列化）。"""

    messages: list[Message] = field(default_factory=list)  # 当前对话消息列表（SYSTEM/USER/ASSISTANT/TOOL）
    iteration: int = 0  # 当前已执行的迭代轮数（每轮 +1）
    max_iterations: int = 50  # 迭代硬上限，超过即抛 BudgetExceeded
    results: list[ToolResult] = field(default_factory=list)  # 本轮累计的工具执行结果


@dataclass
class _ResumeState:
    """``resume()`` 注入 ``run()`` 的预构建状态（私有，恢复专用）。

    ``resume()`` 从持久化快照重建出一份「上下文 + 进度」，绕过 ``run()`` 正常的
    会话/系统提示词初始化分支，直接带着旧 run_id 继续跑。
    """

    state: AgentState  # 重建后的循环状态（含历史消息与迭代计数）
    run_context: RunContext  # 沿用的原运行上下文（保留原 run_id）
    prompt: str  # 原 prompt（恢复时仍需作为系统提示词注入的依据）
    system: str | None  # 原系统提示词


class AgentLoop:
    """迭代式 Provider/工具循环，附带轻量运行时治理。

    组件全部经构造函数注入（依赖注入），缺省时回退到全局默认：provider 必传；
    registry/guard/engine 等可选参数为 None 时各自取默认实现。组件分几类：

      - 执行核心：``provider``（LLM）、``registry``（工具）、``guard``（shell 黑名单）；
      - 记忆/人格：``skills``/``facts``/``profile``/``soul``（注入到系统提示词）；
      - 会话/上下文：``session``（跨轮持久化）、``compressor``/``window_reset``（二选一）；
      - 运行时治理：``engine``（PolicyEngine + ToolExecutor + store/ledger/events）；
      - 横切：``middlewares``（包裹 Provider 调用，如重试/限流）。

    注意 ``compressor`` 与 ``window_reset`` **互斥**（D3 决策），同传即报错。
    """

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
        # D3：compressor（就地压缩）与 window_reset（窗口重置）是两种互斥的上下文管理策略，
        # 每个 loop 只能启用其一；同时传入属于配置错误，直接报错而非默认其一。
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
        # 外部可预置一个 RunContext（SubAgent 委派时用）；run() 取用后即清空，保证一次性。
        self._run_context_template = run_context
        # 最近一次 run 的「事后产物」，供外部（如 SubAgent.run）读取，不参与循环逻辑。
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
        """执行循环，直到 Provider 返回不含工具调用的最终回答。

        参数：
            prompt: 用户输入。
            system: 可选的附加系统提示词（与自动注入的 soul/context/skills/facts 合并）。
            session_id: 会话 ID；提供时从 ``session`` 恢复历史消息并在结束时落盘。
            _resume: 恢复专用（由 ``resume()`` 注入），非 None 时跳过初始化、续跑旧 run。

        返回最终回答字符串。流程分两段：
          ① 初始化（除非恢复）：建状态/上下文 → 恢复会话历史 → 拼系统提示词 → 落首条 USER；
          ② 主循环：见下方 ``while True`` 块的逐步注释。
        """
        # —— 分支①-A：恢复模式。直接用注入的预构建状态，沿用旧 run_id，不重做初始化。
        if _resume is not None:
            state = _resume.state
            run_context = _resume.run_context
            system_content = _resume.system
            prompt = _resume.prompt
            accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            self._emit("run_started", run_context=run_context, details={"resume": True})
        else:
            # —— 分支①-B：全新运行。建空白状态、新建运行上下文。
            state = AgentState(max_iterations=self.max_iterations)
            accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            run_context = self._ensure_run_context(session_id=session_id)

            # 若指定会话，恢复历史消息（剔除旧 SYSTEM，避免与新系统提示词重复）。
            if self.session and session_id:
                prior = self.session.load(session_id)
                if prior:
                    state.messages.extend(m for m in prior if m.role != Role.SYSTEM)
                    logger.debug("Restored %d messages from session '%s'", len(prior), session_id)

            # 拼装系统提示词（注入 soul/context/skills/facts/profile），再落 SYSTEM + USER。
            system_content = self._build_system(system, prompt=prompt)
            if system_content:
                state.messages.append(Message(role=Role.SYSTEM, content=system_content))
            state.messages.append(Message(role=Role.USER, content=prompt))

            self._start_run_record(run_context, prompt=prompt, system=system_content)
            self._emit("run_started", run_context=run_context, details={"session_id": session_id or ""})

        response: ProviderResponse | None = None

        # 运行时作用域：在本轮 run 期间绑定工作区根/记忆/技能/cron/subagent 等工具运行时，
        # with 退出时自动解绑，保证不会泄漏到其它 run。
        with self._runtime_scope(run_context):
            try:
                while True:  # —— 主循环：每轮 = 一次 LLM 调用 +（若需要）一次工具执行
                    state.iteration += 1
                    run_context.touch(iteration=state.iteration)
                    self._emit("iteration_started", run_context=run_context)

                    # 迭代硬上限：超过仍未收敛即视为失控，抛 BudgetExceeded（显性失败）。
                    if state.iteration > state.max_iterations:
                        raise BudgetExceeded(f"Exceeded {state.max_iterations} iterations without final answer")

                    # 步骤1：调 LLM（可选经中间件链，如重试）。累加本轮 token 用量。
                    response = await self._call_provider(state, run_context=run_context)
                    if response.usage:
                        accumulated = self._add_usage(accumulated, response.usage)

                    # 步骤2（可选）：就地压缩上下文。compressor 仅在返回新列表时才替换，
                    # 用 ``is`` 判同避免无谓替换；同时发布压缩事件。
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

                    # 步骤3：把本轮 ASSISTANT 回复（含可能的 tool_calls）追加进对话历史。
                    state.messages.append(
                        Message(role=Role.ASSISTANT, content=response.content, tool_calls=response.tool_calls or None)
                    )
                    self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

                    # 步骤4：若 LLM 未请求任何工具调用 —— 已是最终回答，跳出循环。
                    if not response.tool_calls:
                        break

                    # 步骤5：并发执行 LLM 请求的工具调用，把每个结果作为 TOOL 消息追加进历史。
                    tool_results = await self._execute_tools(response.tool_calls, state, run_context=run_context)
                    for tool_result in tool_results:
                        state.messages.append(
                            Message(role=Role.TOOL, content=tool_result.content, tool_call_id=tool_result.tool_call_id)
                        )
                    self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

                    # 步骤6（可选）：窗口重置。达到 token 阈值时把长对话折叠成「原始 prompt +
                    # 进度摘要」的新窗口（segment 计数 +1），换段继续，避免上下文溢出。
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
                    # —— 循环回到顶部，带着工具结果再调一次 LLM，直到无工具调用为止。

                # 循环正常结束：记录最终答案、置 COMPLETED、发布完成事件，返回答案。
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
                # 任何异常：置 FAILED、记错误快照、发布失败事件后原样向上抛（显性失败）。
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
                # 无论成功失败：会话消息落盘，并把本次 run 的事后产物缓存到实例属性。
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
        """流式版循环：边跑边 yield ``StreamEvent``（text/tool_call/tool_result/done）。

        与 ``run()`` 的区别：每轮 LLM 调用走 ``provider.stream`` 逐 chunk 消费，
        文本片段实时下推；工具调用与最终完成同样以事件形式产出。``_resume`` 由
        :meth:`resume_stream` 注入，语义与 ``run()`` 的恢复分支一致（跳过初始化、
        续跑旧 run）。
        """
        # —— 分支①-A：恢复模式，沿用预构建状态与旧 run_id。
        if _resume is not None:
            state = _resume.state
            run_context = _resume.run_context
            system_content = _resume.system
            prompt = _resume.prompt
            accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            self._emit("run_started", run_context=run_context, details={"resume": True, "stream": True})
        else:
            # —— 分支①-B：全新运行，建状态/上下文、恢复会话、拼系统提示词、落首条 USER。
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

                    # 本轮流式累加用的临时变量：把多个 chunk 拼回一份完整响应。
                    tools = self.registry.enabled_schemas()
                    full_content = ""
                    tool_calls: list[ToolCall] = []
                    chunk_usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
                    model = ""
                    finish_reason = ""

                    # 消费流：文本片段实时 yield 给调用方，工具调用/usage/model/finish 逐 chunk 累积。
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

                    # 把累积结果重构成标准 ProviderResponse（与 run() 的非流式响应同构，便于复用后续逻辑）。
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

                    # 流式特有兜底：finish_reason 声称是 tool_calls 却没带 tool_calls（部分 provider 在
                    # 流式下会丢字段）。此时改走非流式 _call_provider 补取一次，确保工具调用不丢失。
                    if not response.tool_calls and finish_reason == "tool_calls":
                        response = await self._call_provider(state, run_context=run_context)
                        state.messages[-1] = Message(
                            role=Role.ASSISTANT,
                            content=response.content,
                            tool_calls=response.tool_calls or None,
                        )
                        accumulated = self._add_usage(accumulated, response.usage)

                    self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

                    # 无工具调用 = 最终回答：置 COMPLETED、落最终快照、发布完成事件，并 yield done 结束流。
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

                    # 有工具调用：并发执行，并把每个「调用名 + 结果」作为事件下推，同时追加 TOOL 消息进历史。
                    tool_results = await self._execute_tools(response.tool_calls, state, run_context=run_context)
                    for tool_call, tool_result in zip(response.tool_calls, tool_results, strict=True):
                        yield StreamEvent(type="tool_call", tool_name=tool_call.name)
                        yield StreamEvent(type="tool_result", tool_result_content=tool_result.content)
                        state.messages.append(
                            Message(role=Role.TOOL, content=tool_result.content, tool_call_id=tool_result.tool_call_id)
                        )
                    self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

                    # 窗口重置（逻辑同 run()，流式版仅日志多带一个 stream 标记），达到阈值则换段继续。
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
        """按 run_id 恢复一次未完成的运行，返回（续跑后的）最终回答。

        流程：
          1. 从 ``run_store`` 载入持久化快照；找不到即报错（显性失败）。
          2. 若该 run 已 COMPLETED，直接返回缓存的最终答案，无需重跑。
          3. 否则重建续跑窗口：优先用 ``metadata['progress_summary']`` 折叠成
             「原 prompt + 进度摘要」的新消息；无摘要则深拷贝快照里的历史消息。
          4. 用原 run_id、原 system、重建状态组装 ``_ResumeState`` 注入 ``run()`` 续跑。

        流式恢复见 :meth:`resume_stream`。
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
        """:meth:`resume` 的流式版。

        已 COMPLETED 的 run 直接 yield 单个 ``done`` 事件（带缓存答案）；未完成的
        run 同样按 progress_summary 重建窗口后，用原 run_id 流式续跑。
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
        """把两份 token 用量计数逐字段相加，返回新的 ``TokenUsage``（不可变叠加）。"""
        return TokenUsage(
            prompt_tokens=a.prompt_tokens + b.prompt_tokens,
            completion_tokens=a.completion_tokens + b.completion_tokens,
            total_tokens=a.total_tokens + b.total_tokens,
        )

    def _build_system(self, user_system: str | None, prompt: str = "") -> str | None:
        """合并生成一条系统提示词（含人格 / 项目上下文 / 技能 / 记忆 / 用户画像）。

        各块按以下**注入顺序**拼装（顺序即优先级呈现，影响 LLM 对提示的权重）：

          1. ``<identity>``    SOUL.md 人格（用 insert(0) 放到**最前**，作为基底身份）；
          2. user_system       调用方显式传入的附加系统提示词；
          3. ``<project-context>`` 项目上下文文件（受 settings.context_files_enabled 开关）；
          4. ``<skills>``      按 prompt 相似度自动匹配的技能（命中则注入内容；未命中但
                               存在技能时给一条引导提示）；
          5. ``<memory>``      facts 长期记忆；若开启 memory_nudge 再追加 ``<memory-nudge>`` 提醒；
          6. ``<profile>``     用户画像。

        无任何内容时返回 None（不插入空 SYSTEM 消息）。``prompt`` 仅用于技能相似度匹配。
        """
        parts: list[str] = []
        if user_system:
            parts.append(user_system)

        if self.soul:
            soul_content = self.soul.load()
            if soul_content:
                # insert(0)：把人格放到系统提示词最前，确立基底身份。
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
            # 按相似度匹配技能，截断到 skill_max_auto_invoke 上限，避免注入过多。
            matched = self.skills.matching_skills(
                prompt,
                threshold=settings.skill_match_threshold,
            )[: settings.skill_max_auto_invoke]

            if matched:
                # 命中：先记录用法（影响后续排序），再拼装技能正文。
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
                # 未命中但技能库非空：给一条引导，提示用户可手动创建/浏览技能。
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
        """调用 Provider（LLM），可选地经中间件链包裹。

        内层 handler 固定为 ``Provider.send``；若配置了 middlewares，则用
        ``compose`` 拼成洋葱链后再调用（重试/限流等横切逻辑在此生效），
        否则直接调 handler。调用前后发布 provider_call_started/completed 事件，
        并用本地 token 估算与实际 usage 对照记录偏差。
        """
        tools = self.registry.enabled_schemas()

        from heagent.context.tokens import count_tokens

        estimated = count_tokens(state.messages)
        logger.debug("Calling provider: %d messages, ~%d tokens estimated", len(state.messages), estimated)
        self._emit(
            "provider_call_started",
            run_context=run_context,
            details={"message_count": len(state.messages), "estimated_tokens": estimated},
        )

        # 链最内层：真正调用 Provider.send。中间件（如有）会层层包裹它。
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
        """并发执行一批工具调用（``asyncio.gather`` 同时跑），结果按调用顺序返回。

        每个调用经 :meth:`_execute_one` 走完整的「ledger 幂等 → 策略裁决 → 执行」
        链路；批次前后发布 tool_batch_started/completed 事件，并累加进 state.results。
        """
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
        """端到端执行一次工具调用，并保证幂等。

        幂等由 ``ExecutionLedger`` 提供：用 ``{run_id}:{tool_call.id}`` 作缓存键。
        当模型重发同一个 tool_call（例如窗口重置后）时，直接命中已 COMPLETED 的缓存
        结果，而不会重复执行有副作用的 handler。

        正常路径：① ledger 抢占/命中 → ② PolicyEngine 裁决（准许/审批/沙箱）→
        ③ ToolExecutor 在裁决框架内执行 handler（内部再经 SafetyGuard 黑名单）→
        ④ 把结果（成功/失败）写回 ledger。
        """
        cache_key: str | None = None
        if run_context is not None:
            # ① 抢占缓存键：抢不到且已有 COMPLETED 记录 → 直接返回缓存结果（幂等命中）。
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

        # ② 策略裁决；③ 查 handler。未知工具直接产出 error 结果，不走 executor。
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
            # ③ 真正执行：executor 在 verdict（准许/审批/沙箱）框架下调度 handler，
            #    内部还会经 self.guard（SafetyGuard）做命令黑名单等检查。
            result = await self.engine.executor.execute(
                call=call,
                verdict=verdict,
                guard=self.guard,
                handler=self._invoke_handler,
                run_context=run_context,
                emit=self._emit,
            )

        # ④ 结果回写 ledger：成功记 complete（带结果供后续幂等），失败记 fail（允许重试）。
        if cache_key is not None:
            if result.is_error:
                self.engine.ledger.fail(cache_key, result.content)
            else:
                self.engine.ledger.complete(cache_key, metadata={"result": result.content})
        return result

    async def _invoke_handler(self, call: ToolCall) -> object:
        """解析并调用一次工具调用对应的注册 handler（executor 的执行回调）。

        未知工具直接抛 RuntimeError（executor 外层会捕获并转成 ToolResult.error）。
        """
        handler = self.registry.get_handler(call.name)
        if handler is None:
            raise RuntimeError(f"Unknown tool: {call.name}")
        return await self._invoke(handler, call)

    async def _invoke(self, handler: object, call: ToolCall) -> object:
        """实际调用 handler：自动适配 sync / async 两种工具实现。

        参数以关键字展开 ``call.arguments`` 传入（工具用 ``**kwargs`` 接收）。
        """
        fn = cast("Callable[..., Any]", handler)
        if asyncio.iscoroutinefunction(fn):
            return await fn(**call.arguments)
        return fn(**call.arguments)

    def _ensure_run_context(self, *, session_id: str | None) -> RunContext:
        """为本次执行取得一个运行上下文。

        优先消费外部预置的 ``_run_context_template``（SubAgent 委派时注入，用后即
        清空，保证一次性）；否则由 engine 新建一个，绑定 session_id 与工作区根。
        """
        if self._run_context_template is not None:
            context = self._run_context_template
            self._run_context_template = None
            if session_id and context.session_id is None:
                context.session_id = session_id
            return context
        return self.engine.create_run_context(session_id=session_id, workspace_root=self.context_dir)

    @contextmanager
    def _runtime_scope(self, run_context: RunContext) -> Iterator[None]:
        """在单次 run 期间绑定各工具的运行时依赖，with 退出时统一解绑。

        用 ``ExitStack`` 把多个 ``bind_*`` 上下文管理器串起来：工作区根（路径安全）、
        技能/记忆/cron/subagent 工具各自拿到本次 run 的 store 与上下文。这样工具
        handler 内部无需显式传参即可访问「当前 run 的」依赖，且 run 之间互不串扰。
        """
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
        """写入初始运行快照（best-effort：失败仅记日志，不阻断主循环）。"""
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
        """持久化运行进度（best-effort：失败仅记日志，不阻断主循环）。

        在关键节点（每轮助手回复后、工具执行后、最终完成/失败时）落盘当前消息与
        结果，供 ``resume()`` 续跑或事后审计使用。
        """
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
        """发布一条运行时事件（best-effort：失败仅记日志，不阻断主循环）。

        事件（iteration_started / provider_call_* / tool_* / run_* 等）经
        ``engine.events`` 广播，供观测/调试/外部订阅消费。
        """
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
