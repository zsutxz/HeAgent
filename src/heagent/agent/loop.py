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

import logging
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from heagent.agent.middleware import MiddlewareFn, Request, compose
from heagent.agent.system_prompt import build_system_prompt
from heagent.agent.tool_execution import execute_tool_call, execute_tools, invoke_handler
from heagent.config import get_settings
from heagent.context.window_reset import WindowReset, WindowResetConfig
from heagent.engine import EngineContainer, RunContext, RunStatus
from heagent.exceptions import BudgetExceeded
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard
from heagent.types import Message, ProviderResponse, Role, StreamEvent, TokenUsage, ToolCall, ToolResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

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


@dataclass(slots=True)
class _RunInit:
    """``run()`` / ``run_stream()`` 共享的初始化产物。

    与 ``_ResumeState`` 互为双生：``_init_or_resume`` 输出统一结构，
    循环体据此进入主循环，不再重复分支逻辑。
    """

    state: AgentState
    run_context: RunContext
    system_content: str | None
    accumulated: TokenUsage
    prompt: str  # 原始 prompt（恢复时可能已替换为 _resume.prompt）


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
        """初始化 AgentLoop 主循环。

        参数：
            provider: LLM provider，循环的驱动后端（必填）。
            registry: 工具注册表；缺省取全局单例 ``ToolRegistry.get()``。
            guard: 安全护栏（shell 命令黑名单）；缺省 ``SafetyGuard()``。非真正安全边界，须 OS 级沙箱兜底。
            middlewares: 包裹 provider 调用的中间件链（如重试/日志）；缺省空。
            max_iterations: 主循环最大轮数上限；缺省取 ``settings.max_iterations``。
            skills: 技能记忆库（自学习闭环），可选。
            facts: 事实记忆库，可选。
            profile: 用户画像记忆库，可选。
            session: 会话持久化；提供 ``session_id`` 时据此恢复历史消息并在结束时落盘。
            compressor: 就地上下文压缩策略（D3：与 ``window_reset`` 互斥，每个 loop 仅取其一）。
            window_reset: 窗口重置策略配置（D3：与 ``compressor`` 互斥）；达阈值折叠为「prompt + 进度摘要」。
            context_dir: 工作区根目录（文件工具围栏基址 + engine 落盘根），可选。
            soul: 灵魂/人格记忆库，可选。
            cron_store: 后台定时任务的存储后端，可选。
            engine: 运行时治理容器（policy/executor/store/ledger/observability）；
                缺省 ``EngineContainer.default``，非安全边界（须 OS 级沙箱兜底）。
            run_context: 外部预置的运行上下文（SubAgent 委派时用）；run() 取用后即清空，一次性。
        """
        self.provider = provider
        self.registry = registry or ToolRegistry.get()
        self.guard = guard or SafetyGuard(blocked_tools=get_settings().safety_blocked_tools)
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
        self.window_reset = WindowReset(provider, config=window_reset) if window_reset is not None else None
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

    # ------------------------------------------------------------------
    # 公共入口：run（非流式）/ run_stream（流式）
    # ------------------------------------------------------------------

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
          ① ``_init_or_resume`` → ② 主循环（non-streaming）
        """
        init = await self._init_or_resume(prompt, system, session_id, _resume, stream=False)
        state = init.state
        run_context = init.run_context
        system_content = init.system_content
        accumulated = init.accumulated

        response: ProviderResponse | None = None
        try:
            with self._runtime_scope(run_context):
                while True:
                    self._begin_iteration(state, run_context)
                    response = await self._call_provider(state, run_context=run_context)
                    if response.usage:
                        accumulated = self._add_usage(accumulated, response.usage)

                    await self._maybe_compress(state, run_context, response.usage)
                    state.messages.append(
                        Message(role=Role.ASSISTANT, content=response.content, tool_calls=response.tool_calls or None)
                    )
                    await self._checkpoint(run_context, prompt=init.prompt, system=system_content, state=state)

                    if not response.tool_calls:
                        break

                    tool_results = await self._execute_tools(response.tool_calls, state, run_context=run_context)
                    for tool_result in tool_results:
                        state.messages.append(
                            Message(role=Role.TOOL, content=tool_result.content, tool_call_id=tool_result.tool_call_id)
                        )
                    await self._checkpoint(
                        run_context, prompt=init.prompt, system=system_content, state=state
                    )
                    await self._maybe_window_reset(state, run_context, init.prompt, system_content, response.usage)

                final_answer = response.content if response is not None else ""
                run_context.touch(status=RunStatus.COMPLETED, iteration=state.iteration)
                await self._checkpoint(
                    run_context, prompt=init.prompt, system=system_content, state=state, final_answer=final_answer,
                )
                self._emit("run_completed", run_context=run_context, details={"answer_length": len(final_answer)})
                return final_answer
        except Exception as exc:
            await self._on_run_failed(run_context, init.prompt, system_content, state, exc)
            raise
        finally:
            await self._persist_and_cache(session_id, state, accumulated, run_context)

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
        文本片段实时下推；工具调用与最终完成同样以事件形式产出。
        """
        init = await self._init_or_resume(prompt, system, session_id, _resume, stream=True)
        state = init.state
        run_context = init.run_context
        system_content = init.system_content
        accumulated = init.accumulated

        try:
            with self._runtime_scope(run_context):
                while True:
                    self._begin_iteration(state, run_context)

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

                    await self._maybe_compress(state, run_context, response.usage)
                    state.messages.append(
                        Message(
                            role=Role.ASSISTANT, content=response.content, tool_calls=response.tool_calls or None
                        )
                    )

                    if not response.tool_calls and finish_reason == "tool_calls":
                        response = await self._call_provider(state, run_context=run_context)
                        state.messages[-1] = Message(
                            role=Role.ASSISTANT,
                            content=response.content,
                            tool_calls=response.tool_calls or None,
                        )
                        accumulated = self._add_usage(accumulated, response.usage)

                    await self._checkpoint(
                        run_context, prompt=init.prompt, system=system_content, state=state
                    )

                    if not response.tool_calls:
                        run_context.touch(status=RunStatus.COMPLETED, iteration=state.iteration)
                        await self._checkpoint(
                            run_context,
                            prompt=init.prompt,
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

                    tool_results = await self._execute_tools(
                        response.tool_calls, state, run_context=run_context
                    )
                    for tool_call, tool_result in zip(response.tool_calls, tool_results, strict=True):
                        yield StreamEvent(type="tool_call", tool_name=tool_call.name)
                        yield StreamEvent(type="tool_result", tool_result_content=tool_result.content)
                        state.messages.append(
                            Message(
                                role=Role.TOOL,
                                content=tool_result.content,
                                tool_call_id=tool_result.tool_call_id,
                            )
                        )
                    await self._checkpoint(
                        run_context, prompt=init.prompt, system=system_content, state=state
                    )
                    await self._maybe_window_reset(
                        state, run_context, init.prompt, system_content, response.usage
                    )
        except Exception as exc:
            await self._on_run_failed(run_context, init.prompt, system_content, state, exc)
            raise
        finally:
            await self._persist_and_cache(session_id, state, accumulated, run_context)

    # ------------------------------------------------------------------
    # 恢复入口：resume / resume_stream
    # ------------------------------------------------------------------

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
        snapshot, _resume = await self._build_resume_state(run_id)
        if _resume is None:
            return snapshot.final_answer or ""
        return await self.run(snapshot.prompt, system=snapshot.system, _resume=_resume)

    async def resume_stream(self, run_id: str) -> AsyncIterator[StreamEvent]:
        """:meth:`resume` 的流式版。

        已 COMPLETED 的 run 直接 yield 单个 ``done`` 事件（带缓存答案）；未完成的
        run 同样按 progress_summary 重建窗口后，用原 run_id 流式续跑。
        """
        snapshot, _resume = await self._build_resume_state(run_id)
        if _resume is None:
            yield StreamEvent(type="done", final_answer=snapshot.final_answer or "")
            return
        async for event in self.run_stream(snapshot.prompt, system=snapshot.system, _resume=_resume):
            yield event

    async def _build_resume_state(self, run_id: str) -> tuple[object, _ResumeState | None]:
        """从快照重建恢复状态；已完成的 run 返回 ``(snapshot, None)``。"""
        snapshot = await self.engine.run_store.load(run_id)
        if snapshot is None:
            raise ValueError(f"No run snapshot found for run_id={run_id!r}")
        if snapshot.context.status == RunStatus.COMPLETED:
            return snapshot, None

        progress = snapshot.context.metadata.get("progress_summary")
        if progress:
            messages = WindowReset.build_resume_messages(original_prompt=snapshot.prompt, summary=progress)
        else:
            messages = [m.model_copy(deep=True) for m in snapshot.messages]

        state = AgentState(
            messages=messages,
            max_iterations=self.max_iterations,
            iteration=snapshot.context.iteration,
        )
        return snapshot, _ResumeState(
            state=state,
            run_context=snapshot.context,
            prompt=snapshot.prompt,
            system=snapshot.system,
        )

    # ------------------------------------------------------------------
    # 初始化（run / run_stream 共享）
    # ------------------------------------------------------------------

    async def _init_or_resume(
        self,
        prompt: str,
        system: str | None,
        session_id: str | None,
        _resume: _ResumeState | None,
        *,
        stream: bool,
    ) -> _RunInit:
        """统一初始化：恢复模式（_resume → 跳过）或全新运行。

        返回 ``_RunInit`` 供 ``run()`` / ``run_stream()`` 直接消费，
        循环体不再重复分支逻辑。
        """
        if _resume is not None:
            self._emit("run_started", run_context=_resume.run_context, details={"resume": True, "stream": stream})
            return _RunInit(
                state=_resume.state,
                run_context=_resume.run_context,
                system_content=_resume.system,
                accumulated=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                prompt=_resume.prompt,
            )
        fresh = await self._init_new_run(prompt, system, session_id, stream=stream)
        return _RunInit(
            state=fresh[0],
            run_context=fresh[1],
            system_content=fresh[2],
            accumulated=fresh[3],
            prompt=prompt,
        )

    async def _init_new_run(
        self,
        prompt: str,
        system: str | None,
        session_id: str | None,
        *,
        stream: bool,
    ) -> tuple[AgentState, RunContext, str | None, TokenUsage]:
        """全新运行的初始化（``run``/``run_stream`` 的「分支①-B」共用）。

        建空白状态与运行上下文 → 恢复会话历史（剔除旧 SYSTEM）→ 拼系统提示词 →
        落 SYSTEM+USER 首条消息 → 写初始运行快照 → 发 run_started 事件。
        返回 ``(state, run_context, system_content, accumulated)``。

        ``stream`` 仅决定 run_started 事件 details 的载荷（流式带 ``stream`` 标记，
        非流式带 ``session_id``），与两个入口重构前的行为逐字段一致。
        """
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

        await self._start_run_record(run_context, prompt=prompt, system=system_content)
        details: dict[str, Any] = {"stream": True} if stream else {"session_id": session_id or ""}
        self._emit("run_started", run_context=run_context, details=details)
        return state, run_context, system_content, accumulated

    # ------------------------------------------------------------------
    # 终结（run / run_stream 共享）
    # ------------------------------------------------------------------

    async def _persist_and_cache(
        self,
        session_id: str | None,
        state: AgentState,
        accumulated: TokenUsage,
        run_context: RunContext,
    ) -> None:
        """持久化会话 + 缓存事后产物（finally 块共用）。

        无论成功/失败均调用：落盘会话消息、缓存 ``last_*`` 属性。
        """
        if self.session and session_id:
            self.session.save(session_id, state.messages)
            logger.debug("Saved %d messages to session '%s'", len(state.messages), session_id)
        self.last_usage = accumulated
        self.last_iteration = state.iteration
        self.last_run_context = run_context

    # ------------------------------------------------------------------
    # 迭代控制
    # ------------------------------------------------------------------

    def _begin_iteration(self, state: AgentState, run_context: RunContext) -> None:
        """推进迭代计数、发布 iteration_started 事件，并强制迭代硬上限。

        每轮循环入口调用：iteration+1 → touch 上下文 → 发事件 → 超过 max_iterations
        即抛 ``BudgetExceeded``（显性失败，防止失控循环）。``run``/``run_stream`` 共用。
        """
        state.iteration += 1
        run_context.touch(iteration=state.iteration)
        self._emit("iteration_started", run_context=run_context)
        if state.iteration > state.max_iterations:
            raise BudgetExceeded(f"Exceeded {state.max_iterations} iterations without final answer")

    # ------------------------------------------------------------------
    # 上下文管理（压缩 / 窗口重置）
    # ------------------------------------------------------------------

    async def _maybe_compress(
        self,
        state: AgentState,
        run_context: RunContext,
        usage: TokenUsage | None,
    ) -> None:
        """就地压缩上下文（compressor 启用时）。

        compressor 仅在返回新列表时才替换（用 ``is`` 判同避免无谓替换），
        同时发布 context_compressed 事件。``usage`` 为空则跳过。
        """
        if not self.compressor or not usage:
            return
        settings = get_settings()
        compressed = await self.compressor.compress(
            state.messages,
            token_count=usage.total_tokens,
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

    async def _maybe_window_reset(
        self,
        state: AgentState,
        run_context: RunContext,
        prompt: str,
        system_content: str | None,
        usage: TokenUsage | None,
    ) -> None:
        """窗口重置（window_reset 启用时）。

        达到 token 阈值时把长对话折叠成「原始 prompt + 进度摘要」的新窗口
        （segment 计数 +1），换段继续，避免上下文溢出；``usage`` 为空则跳过。
        """
        if not self.window_reset or not usage:
            return
        settings = get_settings()
        if not self.window_reset.should_trigger(
            token_count=usage.total_tokens,
            max_tokens=settings.max_context_tokens,
        ):
            return
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
        await self._checkpoint(run_context, prompt=prompt, system=system_content, state=state)

    # ------------------------------------------------------------------
    # 异常 / 完成
    # ------------------------------------------------------------------

    async def _on_run_failed(
        self,
        run_context: RunContext,
        prompt: str,
        system_content: str | None,
        state: AgentState,
        exc: Exception,
    ) -> None:
        """异常收尾：置 FAILED、记错误快照、发布 run_failed 事件（不含 re-raise）。

        ``run``/``run_stream`` 的 except 块共用；``raise`` 留在各自 except 末尾
        （显性失败，异常原样向上抛）。
        """
        run_context.touch(status=RunStatus.FAILED, iteration=state.iteration)
        await self._checkpoint(
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

    @staticmethod
    def _add_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
        """把两份 token 用量计数逐字段相加，返回新的 ``TokenUsage``（不可变叠加）。"""
        return TokenUsage(
            prompt_tokens=a.prompt_tokens + b.prompt_tokens,
            completion_tokens=a.completion_tokens + b.completion_tokens,
            total_tokens=a.total_tokens + b.total_tokens,
        )

    # ------------------------------------------------------------------
    # 系统提示词 / Provider 调用 / 工具执行
    # ------------------------------------------------------------------

    def _build_system(self, user_system: str | None, prompt: str = "") -> str | None:
        """合并生成系统提示词（委托 :func:`build_system_prompt`，保留 skills.record_usage 副作用）。"""
        return build_system_prompt(
            user_system,
            prompt,
            soul=self.soul,
            context_dir=self.context_dir,
            skills=self.skills,
            facts=self.facts,
            profile=self.profile,
        )

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
        """并发执行一批工具调用（委托 :func:`execute_tools`）。"""
        return await execute_tools(self, calls, state, run_context=run_context)

    async def _execute_one(
        self,
        call: ToolCall,
        *,
        run_context: RunContext | None = None,
    ) -> ToolResult:
        """端到端执行一次工具调用并保证幂等（委托 :func:`execute_tool_call`；被测试直接调用）。"""
        return await execute_tool_call(self, call, run_context=run_context)

    async def _invoke_handler(self, call: ToolCall) -> object:
        """解析并调用工具 handler（委托 :func:`invoke_handler`）。"""
        return await invoke_handler(self, call)

    # ------------------------------------------------------------------
    # 运行时上下文 / 注册 / 持久化 / 事件
    # ------------------------------------------------------------------

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

        任一 ``bind_*`` 抛异常时 ExitStack 自动弹出已进入的上下文，异常逸出到
        ``run()``/``run_stream()`` 的 ``try/except Exception`` 被 ``_on_run_failed`` 收口
        （不会裸抛到 run 之外、丢失 session 落盘与 last_* 缓存）。
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

    async def _start_run_record(self, run_context: RunContext, *, prompt: str, system: str | None) -> None:
        """写入初始运行快照（best-effort：失败仅记日志，不阻断主循环）。"""
        try:
            await self.engine.run_store.start(run_context, prompt=prompt, system=system)
        except Exception:
            logger.exception("Failed to start run record for '%s'", run_context.run_id)

    async def _checkpoint(
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
            await self.engine.run_store.checkpoint(
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
