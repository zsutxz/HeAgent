"""核心 Agent 循环 —— Provider 调用、工具执行与迭代控制的编排中枢。

``AgentLoop`` 是 HeAgent 的顶层编排器：它反复执行「调 LLM → 解析工具调用 → 执行
工具 → 把结果喂回 LLM」的循环，直到 LLM 给出不含工具调用的最终回答（或触发迭代
上限 / 预算上限）。每一轮还穿插**运行时治理**（``engine``：准入/审批/沙箱裁决、
运行记录持久化、事件发布）与**上下文管理**（就地压缩 ``compressor`` 或窗口重置
``window_reset``，二者互斥）。

本模块对外的主入口：
  - :meth:`AgentLoop.run`          —— 非流式执行，返回最终回答字符串；
  - :meth:`AgentLoop.run_stream`   —— 流式执行，逐个 yield ``StreamEvent``；
  - :meth:`AgentLoop.resume` / ``resume_stream`` —— 按 run_id 恢复未完成的运行；
  - :meth:`AgentLoop.pause` / ``unpause`` / ``is_paused`` —— 协作式暂停/恢复当前循环。

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
from heagent.agent.system_prompt import build_system_prompt
from heagent.agent.tool_execution import execute_tool_call, execute_tools, invoke_handler
from heagent.config import get_settings
from heagent.context.window_reset import WindowReset, WindowResetConfig
from heagent.engine import EngineContainer, RunContext, RunStatus
from heagent.engine.hooks import SESSION_END, SESSION_START
from heagent.exceptions import BudgetExceeded
from heagent.tools.call_summary import summarize_tool_call
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard
from heagent.types import (
    Message,
    ProviderResponse,
    Role,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolSchema,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from heagent.context.compressor import ContextCompressor
    from heagent.context.session import SessionStore
    from heagent.cron.jobs import JobStore
    from heagent.engine.store import RunSnapshot
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


_DELEGATION_DETAIL_KEYS = ("kind", "role", "workflow_step", "workflow_story", "goal_id", "goal_kind")


def _delegation_details(run_context: RunContext) -> dict[str, Any]:
    """Return a delegated run's identity for the ``run_started`` log line.

    Progress banners (``cli_display._announce_*``) are stderr-only, so the log file could
    not answer "which agent/step ran when" after the fact.  These keys make a delegated run
    reconstructible from ``logs/heagent-*.log``; a root run carries no such metadata and
    therefore logs exactly as before.
    """
    metadata = run_context.metadata or {}
    return {key: metadata[key] for key in _DELEGATION_DETAIL_KEYS if metadata.get(key) not in (None, "")}


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
        delegation_depth: int = 0,
        steering_callback: Callable[[], Awaitable[list[Message]]] | None = None,
        follow_up_callback: Callable[[], Awaitable[list[Message]]] | None = None,
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
            delegation_depth: 当前 loop 所处的委派深度（根 loop=0，SubAgent 创建的子 loop=父深度+1）；
                作为子 Agent 委派工具的递归深度闸门输入（上限取 `Settings.subagent_max_depth`）。
            steering_callback: steering 回调（参考 Pi）：每轮 LLM 调用前被 poll，返回的消息
                以 USER 角色注入到下一轮上下文。用于在 Agent 运行中插入/重定向指令。
            follow_up_callback: follow-up 回调（参考 Pi）：内层循环自然退出（无 tool_calls）后被 poll，
                返回消息则自动接续新轮次。用于任务完成后的自动追加。
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
        # 委派深度：根 loop 为 0，SubAgent 创建的子 loop 为父深度+1（递归闸门用）。
        self.delegation_depth = delegation_depth
        # steering / follow-up 回调（参考 Pi 双层循环设计）
        self.steering_callback = steering_callback
        self.follow_up_callback = follow_up_callback
        # 最近一次 run 的「事后产物」，供外部（如 SubAgent.run）读取，不参与循环逻辑。
        self.last_run_context: RunContext | None = None
        self.last_usage: TokenUsage | None = None
        self.last_iteration: int | None = None
        # 从程序启动开始的累计总 token 数（跨 run 累加）
        self.cumulative_tokens: int = 0
        # 当前在途的工具批次摘要（形如 ``file_read → src/a.py``；多调用带 ``(+N)``）。
        # 批次执行期间非空、结束（含取消）即清空——状态栏据此显示「卡在哪个工具」。
        self.active_tool: str = ""
        # 本次 run 的「调用尝试」活动标签（每次调用一条，run 开始即清空）。事件环缓冲仅
        # 200 条、长 run 会丢早期调用，故活动回顾独立记录于此（单次模式跑完回显）；
        # 被 policy/hook 阻止、命中 ledger 缓存的调用**同样留痕**——台账记的是
        # 「这次 run 试过动什么」，展示文案（show_tool_activity）据此刻画。
        self.tool_activity: list[str] = []
        # 最近一次 run 结束时的「当前上下文占用」估算（下一轮将发送的消息 token 数），供状态栏展示。
        self.last_context_tokens: int = 0
        # 协作式暂停控制：Event 初始已设置（运行态）。pause() 清空 → 循环在下一轮边界挂起；
        # unpause() 重新设置 → 继续。仅在同一事件循环内调用（跨线程需 call_soon_threadsafe 包装）。
        self._pause_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()

        settings = get_settings()
        self.max_iterations = max_iterations or settings.max_iterations

    # ------------------------------------------------------------------
    # steering / follow-up 消息队列（参考 Pi 双层循环设计）
    # ------------------------------------------------------------------

    async def _poll_steering(self) -> list[Message]:
        """Poll steering 回调，返回待注入的消息（失败静默，不阻断主循环）。"""
        if self.steering_callback is None:
            return []
        try:
            return await self.steering_callback()
        except Exception:
            logger.warning("steering_callback failed", exc_info=True)
            return []

    async def _poll_follow_up(self) -> list[Message]:
        """Poll follow-up 回调，返回待注入的消息（失败静默，不阻断主循环）。"""
        if self.follow_up_callback is None:
            return []
        try:
            return await self.follow_up_callback()
        except Exception:
            logger.warning("follow_up_callback failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # 暂停 / 恢复（协作式：在下一轮 LLM 调用前的边界生效）
    # ------------------------------------------------------------------

    def pause(self) -> None:
        """请求暂停循环：当前进行中的 LLM 调用会跑完，随后在下一轮边界挂起。

        协作式暂停——不打断进行中的 provider 调用、不取消任务；``unpause()`` 后从
        挂起点原地继续（消息、迭代计数、run 上下文均保留）。幂等，可多次调用。
        须在同一事件循环内调用（跨线程请用 ``loop.call_soon_threadsafe`` 包装）。
        """
        self._pause_event.clear()
        logger.info("AgentLoop pause requested")

    def unpause(self) -> None:
        """恢复被 ``pause()`` 挂起的循环。幂等，可多次调用。"""
        self._pause_event.set()
        logger.info("AgentLoop unpaused")

    @property
    def is_paused(self) -> bool:
        """当前是否处于暂停请求态（循环可能尚未到达挂起点）。"""
        return not self._pause_event.is_set()

    async def _wait_if_paused(self, run_context: RunContext) -> None:
        """暂停检查点：处于暂停态则挂起，直到 ``unpause()``。

        由 ``run`` / ``run_stream`` 内层循环在每轮边界调用；挂起前后各发一条
        ``run_paused`` / ``run_resumed`` 事件供观测。
        """
        if self._pause_event.is_set():
            return
        self._emit("run_paused", run_context=run_context)
        try:
            await self._pause_event.wait()
        finally:
            self._emit("run_resumed", run_context=run_context)

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
          ① ``_init_or_resume`` → ② 双层主循环（外层 follow-up + 内层 steering/tool 执行）
        """
        init = await self._init_or_resume(prompt, system, session_id, _resume, stream=False)
        state = init.state
        run_context = init.run_context
        system_content = init.system_content
        accumulated = init.accumulated

        response: ProviderResponse | None = None
        try:
            with self._runtime_scope(run_context):
                # ---- 外层循环：follow-up 接续 ----
                while True:
                    # ---- 内层循环：steering + 工具执行 ----
                    while True:
                        # 暂停检查点（协作式）：pause() 后挂在此处，unpause() 继续。
                        await self._wait_if_paused(run_context)

                        # Poll steering 回调（每轮 LLM 调用前），注入的消息作为用户指令进入下一轮上下文
                        for msg in await self._poll_steering():
                            state.messages.append(msg)

                        self._begin_iteration(state, run_context)
                        response = await self._call_provider(state, run_context=run_context)
                        if response.usage:
                            accumulated = self._add_usage(accumulated, response.usage)

                        await self._maybe_compress(state, run_context, response.usage)
                        state.messages.append(
                            Message(
                                role=Role.ASSISTANT,
                                content=response.content,
                                tool_calls=response.tool_calls or None,
                                reasoning_content=response.reasoning_content,
                            )
                        )
                        await self._checkpoint(run_context, prompt=init.prompt, system=system_content, state=state)

                        if not response.tool_calls:
                            break  # 退出内层，进入 follow-up 检查

                        tool_results = await self._execute_tools(response.tool_calls, state, run_context=run_context)
                        for tool_result in tool_results:
                            state.messages.append(
                                Message(
                                    role=Role.TOOL,
                                    content=tool_result.content,
                                    tool_call_id=tool_result.tool_call_id,
                                )
                            )
                        await self._checkpoint(run_context, prompt=init.prompt, system=system_content, state=state)
                        await self._maybe_window_reset(
                            state, run_context, init.prompt, system_content, usage=response.usage
                        )

                    # ---- follow-up 检查 ----
                    follow_up = await self._poll_follow_up()
                    if not follow_up:
                        break  # 无 follow-up，外层退出
                    for msg in follow_up:
                        state.messages.append(msg)
                    # 有 follow-up → 继续外层循环，启动新一轮 LLM 调用

                final_answer = response.content if response is not None else ""
                run_context.touch(status=RunStatus.COMPLETED, iteration=state.iteration)
                await self._checkpoint(
                    run_context,
                    prompt=init.prompt,
                    system=system_content,
                    state=state,
                    final_answer=final_answer,
                )
                self._emit("run_completed", run_context=run_context, details={"answer_length": len(final_answer)})
                self.last_usage = accumulated
                self.cumulative_tokens += accumulated.total_tokens
                self.last_iteration = state.iteration
                return final_answer
        except Exception as exc:
            await self._on_run_failed(run_context, init.prompt, system_content, state, exc)
            raise
        finally:
            await self._persist_and_cache(session_id, state, accumulated, run_context)

    async def run_stream(  # noqa: C901
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
        同样支持 steering/follow-up 双层循环。
        """
        init = await self._init_or_resume(prompt, system, session_id, _resume, stream=True)
        state = init.state
        run_context = init.run_context
        system_content = init.system_content
        accumulated = init.accumulated

        response: ProviderResponse | None = None
        try:
            with self._runtime_scope(run_context):
                # ---- 外层循环：follow-up 接续 ----
                while True:
                    # ---- 内层循环：steering + 工具执行 ----
                    while True:
                        # 暂停检查点（协作式）：pause() 后挂在此处，unpause() 继续。
                        await self._wait_if_paused(run_context)

                        # Poll steering 回调（每轮 LLM 调用前）
                        for msg in await self._poll_steering():
                            state.messages.append(msg)

                        self._begin_iteration(state, run_context)

                        tools = self._get_tools()
                        full_content = ""
                        tool_calls: list[ToolCall] = []
                        chunk_usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
                        model = ""
                        finish_reason = ""
                        reasoning_content = ""

                        async for chunk in self.provider.stream(state.messages, tools=tools or None):
                            if chunk.content:
                                full_content += chunk.content
                                yield StreamEvent(type="text", text=chunk.content)
                            if chunk.tool_calls:
                                tool_calls.extend(chunk.tool_calls)
                            if chunk.usage and chunk.usage.total_tokens > 0:
                                # P1-2 修复：跨 chunk 的 usage 用累加而非覆盖
                                # （非 OpenAI 提供者可能分多个 chunk 分发 usage）
                                chunk_usage = self._add_usage(chunk_usage, chunk.usage)
                            if chunk.model:
                                model = chunk.model
                            if chunk.finish_reason:
                                finish_reason = chunk.finish_reason
                            if chunk.reasoning_content:
                                reasoning_content += chunk.reasoning_content

                        # 部分 Provider（DeepSeek 等）流式 API 不支持 usage-bearing chunk，
                        # chunk_usage 始终为零 → 用量显示、压缩、窗口重置全部失效。
                        # 此时用本地 token 估算兜底（与 _call_provider / _maybe_window_reset 一致）。
                        if chunk_usage.total_tokens == 0:
                            from heagent.context.tokens import count_tokens, estimate_completion_tokens

                            estimated_prompt = count_tokens(state.messages)
                            estimated_completion = estimate_completion_tokens(full_content, tool_calls)
                            chunk_usage = TokenUsage(
                                prompt_tokens=estimated_prompt,
                                completion_tokens=estimated_completion,
                                total_tokens=estimated_prompt + estimated_completion,
                            )

                        accumulated = self._add_usage(accumulated, chunk_usage)
                        response = ProviderResponse(
                            content=full_content,
                            tool_calls=tool_calls,
                            usage=chunk_usage,
                            model=model,
                            finish_reason=finish_reason or "stop",
                            reasoning_content=reasoning_content or None,
                        )

                        await self._maybe_compress(state, run_context, response.usage)
                        state.messages.append(
                            Message(
                                role=Role.ASSISTANT,
                                content=response.content,
                                tool_calls=response.tool_calls or None,
                                reasoning_content=response.reasoning_content,
                            )
                        )

                        # P1-1 修复：流式 delta 累积未能捕获 tool_calls、
                        # 但 finish_reason 指示 tool_calls 时，回退到非流式调用。
                        # 此前不完整消息已追加入 messages，LLM 回退调用看到残缺历史
                        # 并在覆盖后仍不一致；现先 pop 残缺消息、回退成功后再 append。
                        if not response.tool_calls and finish_reason == "tool_calls":
                            state.messages.pop()  # 移除残缺的流式 assistant 消息
                            response = await self._call_provider(state, run_context=run_context)
                            state.messages.append(
                                Message(
                                    role=Role.ASSISTANT,
                                    content=response.content,
                                    tool_calls=response.tool_calls or None,
                                    reasoning_content=response.reasoning_content,
                                )
                            )
                            accumulated = self._add_usage(accumulated, response.usage)

                        await self._checkpoint(run_context, prompt=init.prompt, system=system_content, state=state)

                        if not response.tool_calls:
                            break  # 退出内层，进入 follow-up 检查

                        # 先逐个公告「调用什么、作用在哪个对象上」，再执行：
                        # 工具可能耗时数十秒（shell / 联网 / 子 Agent），展示层需要在
                        # 它真正跑起来之前就看到目标；结果事件在执行后补发。
                        for tool_call in response.tool_calls:
                            yield StreamEvent(
                                type="tool_call",
                                tool_name=tool_call.name,
                                tool_target=summarize_tool_call(tool_call.name, tool_call.arguments),
                            )
                        tool_results = await self._execute_tools(response.tool_calls, state, run_context=run_context)
                        for tool_call, tool_result in zip(response.tool_calls, tool_results, strict=True):
                            # 批次内并发执行，结果按调用顺序返回——带上工具名与成败标志，
                            # 展示层才能把「失败」归因到具体调用（成功不必逐条提示）。
                            yield StreamEvent(
                                type="tool_result",
                                tool_name=tool_call.name,
                                tool_result_content=tool_result.content,
                                tool_error=tool_result.is_error,
                            )
                            state.messages.append(
                                Message(
                                    role=Role.TOOL,
                                    content=tool_result.content,
                                    tool_call_id=tool_result.tool_call_id,
                                )
                            )
                        await self._checkpoint(run_context, prompt=init.prompt, system=system_content, state=state)
                        await self._maybe_window_reset(
                            state, run_context, init.prompt, system_content, usage=response.usage
                        )

                    # ---- follow-up 检查 ----
                    follow_up = await self._poll_follow_up()
                    if not follow_up:
                        break  # 无 follow-up，外层退出
                    for msg in follow_up:
                        state.messages.append(msg)
                    # 有 follow-up → 继续外层循环

                # 真正完成：外层退出后统一收尾
                run_context.touch(status=RunStatus.COMPLETED, iteration=state.iteration)
                await self._checkpoint(
                    run_context,
                    prompt=init.prompt,
                    system=system_content,
                    state=state,
                    final_answer=response.content if response is not None else "",
                )
                self._emit(
                    "run_completed",
                    run_context=run_context,
                    details={"answer_length": len(response.content) if response and response.content else 0},
                )
                self.last_usage = accumulated
                self.cumulative_tokens += accumulated.total_tokens
                self.last_iteration = state.iteration
                yield StreamEvent(type="done", final_answer=response.content if response is not None else "")
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

    async def _build_resume_state(self, run_id: str) -> tuple[RunSnapshot, _ResumeState | None]:
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
        # 展示态按 run 重置（恢复也是新的一次 run）：交互模式复用同一 loop 跑多轮，
        # 不清会跨轮串味。放在本函数顶部而非 _init_new_run——后者在恢复分支被提前
        # 跳过，会导致 resume 后的状态栏/台账残留上一段 run 的值。
        self.active_tool = ""
        self.tool_activity = []
        if _resume is not None:
            resume_details: dict[str, Any] = {"resume": True, "stream": stream}
            resume_details.update(_delegation_details(_resume.run_context))
            self._emit("run_started", run_context=_resume.run_context, details=resume_details)
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
        await self.engine.prune_ledger_once()  # 全新 run 启动清理一次；resume 不触发（那次 run 启动已清过）
        state = AgentState(max_iterations=self.max_iterations)
        accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        run_context = self._ensure_run_context(session_id=session_id)

        # 拼装系统提示词（注入 soul/context/skills/facts/profile），先落 SYSTEM——
        # 严格模板（如 Ollama）要求 SYSTEM 必须是消息数组的第一条。
        system_content = await asyncio.to_thread(self._build_system, system, prompt=prompt)
        if system_content:
            state.messages.append(Message(role=Role.SYSTEM, content=system_content))

        # 若指定会话，恢复历史消息（剔除旧 SYSTEM，避免与新系统提示词重复），
        # 置于 SYSTEM 之后、新 USER 提示词之前。
        if self.session and session_id:
            prior = await asyncio.to_thread(self.session.load, session_id)
            if prior:
                state.messages.extend(m for m in prior if m.role != Role.SYSTEM)
                logger.debug("Restored %d messages from session '%s'", len(prior), session_id)

        state.messages.append(Message(role=Role.USER, content=prompt))

        await self._start_run_record(run_context, prompt=prompt, system=system_content)
        details: dict[str, Any] = {"stream": True} if stream else {"session_id": session_id or ""}
        details.update(_delegation_details(run_context))
        # 展示态已由 _init_or_resume 统一重置（新 run 与恢复路径共用）。
        self._emit("run_started", run_context=run_context, details=details)
        if self.engine.hooks is not None:
            await self.engine.hooks.run_session(SESSION_START, run_context)
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
        # 复位暂停态：无论完成/失败/取消（finally 块），均解除协作式暂停，
        # 防止「暂停后被打断」的暂停态泄漏到下一次 run（P1 修复）。
        self._pause_event.set()
        if self.session and session_id:
            await asyncio.to_thread(self.session.save, session_id, state.messages)
            logger.debug("Saved %d messages to session '%s'", len(state.messages), session_id)
        self.last_usage = accumulated
        self.last_iteration = state.iteration
        self.last_run_context = run_context
        # 当前上下文占用：以「下一轮将发送的消息」估算 token 数（区别于 last_usage 的累计值）。
        from heagent.context.tokens import count_tokens

        self.last_context_tokens = count_tokens(state.messages)
        if self.engine.hooks is not None:
            await self.engine.hooks.run_session(SESSION_END, run_context)
        await self.engine.close_run(run_context)

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
        *,
        usage: TokenUsage | None = None,
    ) -> None:
        """窗口重置（window_reset 启用时）。

        达到 token 阈值时把长对话折叠成「原始 prompt + 进度摘要」的新窗口
        （segment 计数 +1），换段继续，避免上下文溢出。

        P1-3 修复：取 LLM 上报的 ``usage.total_tokens``（调用**前**的输入 token 数）
        与 ``count_tokens(state.messages)``（调用**后**、含工具结果的 token 估算）
        的**最大值**作为触发判断依据——纠正此前仅用 usage（滞后一轮）的偏差。
        """
        if not self.window_reset:
            return
        from heagent.context.tokens import count_tokens

        settings = get_settings()
        # P1-3: usage reflects pre-call input tokens; count_tokens reflects current msg list
        # (including just-appended tool results); take max to avoid one-round lag.
        llm_tokens = usage.total_tokens if usage else 0
        current_tokens = max(llm_tokens, count_tokens(state.messages))
        if not self.window_reset.should_trigger(
            token_count=current_tokens,
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

    def _get_tools(self) -> list[ToolSchema]:
        """取发送给 LLM 的工具 Schema 列表，按 policy 白名单过滤（P5-1）。

        若 engine.policy.allowed_tools 非 None，仅返回白名单内工具；
        否则返回全部已启用工具。减少 token 浪费与模型误调。
        """
        schemas = self.registry.enabled_schemas()
        allowed = self.engine.policy.allowed_tools
        if allowed is not None:
            schemas = [s for s in schemas if s.name in allowed]
        return schemas

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
        tools = self._get_tools()

        from heagent.context.tokens import count_tokens

        estimated = count_tokens(state.messages)
        logger.info("Calling provider: %d messages, ~%d tokens estimated", len(state.messages), estimated)
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
            logger.info(
                "Provider response: %d actual tokens (estimated: %d, delta: %+d)",
                response.usage.total_tokens,
                estimated,
                response.usage.total_tokens - estimated,
            )
            # P0-3：把「实际 vs 估算」的偏差回收成校准系数（输入侧同量纲才可比）。
            # 这是全局唯一的校准入口——非流式调用必经此处，流式 usage 缺失时无样本可学。
            from heagent.context.tokens import note_actual_usage

            note_actual_usage(
                response.model,
                estimated=estimated,
                actual=response.usage.prompt_tokens,
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
        技能/记忆/cron 工具各自拿到本次 run 的 store 与上下文；subagent 工具拿到的是
        **由本层组装**的委派回调（``build_subagent_delegates``，见 ``agent/delegation.py``），
        工具层因此无需认识 ``SubAgent``。这样工具 handler 内部无需显式传参即可访问
        「当前 run 的」依赖，且 run 之间互不串扰。

        任一 ``bind_*`` 抛异常时 ExitStack 自动弹出已进入的上下文，异常逸出到
        ``run()``/``run_stream()`` 的 ``try/except Exception`` 被 ``_on_run_failed`` 收口
        （不会裸抛到 run 之外、丢失 session 落盘与 last_* 缓存）。
        """
        from heagent.agent.delegation import build_subagent_delegates
        from heagent.tools.builtins.cron import bind_cron_tools
        from heagent.tools.builtins.memory import bind_memory_tools
        from heagent.tools.builtins.skills import bind_skill_tools
        from heagent.tools.builtins.subagent import bind_subagent_tools
        from heagent.tools.edits import bind_edit_snapshot_run
        from heagent.tools.path_safety import bind_workspace_root

        with ExitStack() as stack:
            stack.enter_context(bind_workspace_root(Path(run_context.workspace_root)))
            stack.enter_context(bind_edit_snapshot_run(run_context.run_id))
            stack.enter_context(bind_skill_tools(self.skills))
            stack.enter_context(bind_memory_tools(facts=self.facts, profile=self.profile))
            stack.enter_context(bind_cron_tools(self.cron_store))
            delegate_one, delegate_many = build_subagent_delegates(
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
                depth=self.delegation_depth,
            )
            stack.enter_context(
                bind_subagent_tools(
                    delegate_one,
                    delegate_many,
                    run_context=run_context,
                    depth=self.delegation_depth,
                    max_depth=get_settings().subagent_max_depth,
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
        target: str = "",
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
                target=target,
                details=details or {},
            )
        except Exception:
            logger.exception("Failed to emit engine event '%s'", event_type)
