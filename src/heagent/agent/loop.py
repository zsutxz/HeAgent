"""核心 Agent 循环——Provider 调用、工具执行与迭代控制的编排 façade。

``AgentLoop`` 是 HeAgent 的顶层编排器：它反复执行「调 LLM → 解析工具调用 → 执行
工具 → 把结果喂回 LLM」的循环，直到 LLM 给出不含工具调用的最终回答（或触发迭代
上限 / 预算上限）。每一轮还穿插**运行时治理**（``engine``：准入/审批/沙箱裁决、
运行记录持久化、事件发布）与**上下文管理**（就地压缩 ``compressor`` 或窗口重置
``window_reset``，二者互斥）。

Phase 2 起（façade 化）本模块只保留**依赖注入装配 + 公共入口委托**；循环策略拆为
可独立测试的 sibling 模块：

  - ``run_lifecycle``   —— run 生命周期：状态数据类、初始化分叉、非流式循环体、终结/检查点；
  - ``stream_runtime``  —— 流式循环体（``run_stream``）；
  - ``resume_runtime``  —— 从 run_store 快照重建续跑状态；
  - ``context_runtime`` —— 迭代控制、消息追加、压缩/窗口重置；
  - ``message_ports``   —— steering/follow-up 注入与协作式暂停；
  - ``tool_execution``  —— 工具批次执行（policy → executor → guard → handler）。

本模块对外的主入口：
  - :meth:`AgentLoop.run`          —— 非流式执行，返回最终回答字符串；
  - :meth:`AgentLoop.run_stream`   —— 流式执行，逐个 yield ``StreamEvent``；
  - :meth:`AgentLoop.resume` / ``resume_stream`` —— 按 run_id 恢复未完成的运行；
  - :meth:`AgentLoop.pause` / ``unpause`` / ``is_paused`` —— 协作式暂停/恢复当前循环。

完整数据流 / 调用链见 ``docs/frame.md``。
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import ExitStack, aclosing, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from heagent.agent.context_runtime import (
    add_usage,
    append_assistant_message,
    append_tool_result,
    begin_iteration,
    maybe_compress,
    maybe_window_reset,
)
from heagent.agent.message_ports import (
    inject_follow_up,
    inject_steering,
    is_paused,
    pause,
    poll_follow_up,
    poll_steering,
    unpause,
    wait_if_paused,
)
from heagent.agent.middleware import MiddlewareFn, Request, compose
from heagent.agent.resume_runtime import build_resume_state
from heagent.agent.run_lifecycle import (
    AgentState,
    _delegation_details,  # noqa: F401 ——兼容 re-export（测试从本模块导入）
    _ResumeState,
    _RunInit,
    checkpoint,
    execute_run,
    finish_run,
    init_new_run,
    init_or_resume,
    on_run_failed,
    persist_and_cache,
    start_run_record,
)
from heagent.agent.stream_runtime import stream_run
from heagent.agent.system_prompt import build_system_prompt
from heagent.agent.tool_execution import execute_tool_call, execute_tools, invoke_handler
from heagent.config import ResolvedRuntimeConfig, resolve_runtime_config
from heagent.context.window_reset import WindowReset, WindowResetConfig
from heagent.engine import EngineContainer, RunContext
from heagent.safe_logging import safe_log
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard
from heagent.types import (
    Message,
    ProviderResponse,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolSchema,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator

    from heagent.agent.sub import SubAgentAnnouncer  # 仅类型引用：sub 模块级导入本模块，此处不得模块级互导
    from heagent.context.compressor import ContextCompressor
    from heagent.context.session import SessionStore
    from heagent.cron.jobs import JobStore
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# façade 再导出面：状态数据类与委派详情原在 loop.py 定义，拆分后经 run_lifecycle
# 持有；此处显式再导出（mypy no_implicit_reexport 要求），外部/测试导入路径不变。
__all__ = ["AgentLoop", "AgentState", "_RunInit", "_ResumeState", "_delegation_details"]


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

    循环策略的实现分布在模块 docstring 所列的 sibling 模块中；本类方法保留同名
    委托（公共 API 兼容），新建代码可直接调用对应策略模块。
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
        subagent_announcer: SubAgentAnnouncer | None = None,
        runtime_config: ResolvedRuntimeConfig | None = None,
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
            subagent_announcer: 子 Agent 进度横幅注入口（``SubAgentAnnouncer``）；经
                ``_runtime_scope`` 转传给委派回调。缺省 None=静默；终端/GUI 入口传
                ``cli.display.SUBAGENT_ANNOUNCER`` 保持 stderr 横幅行为。
            runtime_config: 已解析的运行配置快照（Phase 1）；缺省构造期从当前 Settings 一次性解析，
                之后业务执行（压缩/窗口重置/委派/提示词/技能预算）只读快照，全局 Settings 漂移不影响已创建的 loop。
        """
        self.provider = provider
        # 运行配置快照（Phase 1）：构造期一次性解析；业务执行期只读快照。
        self._runtime = resolve_runtime_config(runtime_config)
        self.registry = registry or ToolRegistry.get()
        self.guard = guard or SafetyGuard(blocked_tools=list(self._runtime.safety_blocked_tools))
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
        # 本次 run 的起点（perf_counter）：``run_elapsed_ms`` 的唯一数据源，
        # 由 ``init_or_resume`` 写入；0.0 表示「尚未开始过 run」。
        self._run_started_perf = 0.0
        # 外部可预置一个 RunContext（SubAgent 委派时用）；run() 取用后即清空，保证一次性。
        self._run_context_template = run_context
        # 委派深度：根 loop 为 0，SubAgent 创建的子 loop 为父深度+1（递归闸门用）。
        self.delegation_depth = delegation_depth
        # steering / follow-up 回调（参考 Pi 双层循环设计）
        self.steering_callback = steering_callback
        self.follow_up_callback = follow_up_callback
        # 子 Agent 进度横幅注入口（None=静默；入口层经 cli.display.SUBAGENT_ANNOUNCER 注入）。
        self.subagent_announcer = subagent_announcer
        # 最近一次 run 的「事后产物」，供外部（如 SubAgent.run）读取，不参与循环逻辑。
        self.last_run_context: RunContext | None = None
        self.last_usage: TokenUsage | None = None
        self.last_iteration: int | None = None
        # 最近一次助手回复所用的**实际模型名**（由 provider 响应回填，跨包装解包后的真名）。
        # 与 ``last_usage`` 同属「本次运行的事后产物」：并发消费方（TCP 每请求一个 loop、
        # cron + 交互共享 loop）**必须读这里**，不要去读共享 provider 的路由状态
        # （``RoutingProvider.last_decision`` 是实例级最近一次决策，会被兄弟运行覆盖）。
        self.last_model: str | None = None
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

        self.max_iterations = max_iterations or self._runtime.max_iterations

    # ------------------------------------------------------------------
    # 公共入口：run（非流式）/ run_stream（流式）——委托 run_lifecycle / stream_runtime
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

        返回最终回答字符串。实现见 ``run_lifecycle.execute_run``。
        """
        return await execute_run(self, prompt, system=system, session_id=session_id, _resume=_resume)

    async def run_stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        session_id: str | None = None,
        _resume: _ResumeState | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """流式版循环：边跑边 yield ``StreamEvent``（text/tool_call/tool_result/done）。

        与 ``run()`` 的区别：每轮 LLM 调用走 ``provider.stream`` 逐 chunk 消费，
        文本片段实时下推；工具调用与最终完成同样以事件形式产出。
        同样支持 steering/follow-up 双层循环。实现见 ``stream_runtime.stream_run``。

        ``aclosing`` 是**必需**的：本方法是 ``stream_run`` 生成器的包装层，而 ``async for``
        在被提前关闭（消费者 ``break``、GUI 取消、外层任务取消）时**不会**关闭内层生成器。
        没有 ``aclosing``，内层只能等 event loop 的 asyncgen finalizer 在**另一个 Context**
        里收尾 → ``ContextVar.reset(token)`` 抛 ``ValueError(... created in a different Context)``
        → 被 ``stream_run`` 的 ``except Exception`` 当成运行失败（写 FAILED 终态 + 发
        run_failed 事件），且 session 落盘 / ``close_run`` 被推迟到调用方返回之后。
        ``aclosing`` 把内层的 aclose 拉回同一 Context，收尾因此是确定性的。
        """
        agen = stream_run(self, prompt, system=system, session_id=session_id, _resume=_resume)
        async with aclosing(agen):
            async for event in agen:
                yield event

    # ------------------------------------------------------------------
    # 恢复入口：resume / resume_stream（重建逻辑见 resume_runtime）
    # ------------------------------------------------------------------

    async def resume(self, run_id: str) -> str:
        """按 run_id 恢复一次未完成的运行，返回（续跑后的）最终回答。

        流程：
          1. 从 ``run_store`` 载入持久化快照；找不到即报错（显性失败）。
          2. 若该 run 已 COMPLETED，直接返回缓存的最终答案，无需重跑。
          3. 否则经 ``resume_runtime.build_resume_state`` 重建「原 prompt + 进度摘要」窗口。
          4. 用原 run_id、原 system、重建状态注入 ``run()`` 续跑。
        """
        snapshot, _resume = await build_resume_state(self, run_id)
        if _resume is None:
            return snapshot.final_answer or ""
        return await self.run(snapshot.prompt, system=snapshot.system, _resume=_resume)

    async def resume_stream(self, run_id: str) -> AsyncGenerator[StreamEvent, None]:
        """:meth:`resume` 的流式版。

        已 COMPLETED 的 run 直接 yield 单个 ``done`` 事件（带缓存答案）；未完成的
        run 同样按 progress_summary 重建窗口后，用原 run_id 流式续跑。
        """
        snapshot, _resume = await build_resume_state(self, run_id)
        if _resume is None:
            yield StreamEvent(type="done", final_answer=snapshot.final_answer or "")
            return
        agen = self.run_stream(snapshot.prompt, system=snapshot.system, _resume=_resume)
        async with aclosing(agen):
            async for event in agen:
                yield event

    # ------------------------------------------------------------------
    # steering / follow-up / 暂停——委托 message_ports
    # ------------------------------------------------------------------

    async def _poll_steering(self) -> list[Message]:
        """Poll steering 回调，返回待注入的消息（失败静默，不阻断主循环）。"""
        return await poll_steering(self)

    async def _poll_follow_up(self) -> list[Message]:
        """Poll follow-up 回调，返回待注入的消息（失败静默，不阻断主循环）。"""
        return await poll_follow_up(self)

    async def _inject_steering(self, state: AgentState) -> None:
        """把 steering 消息追加进上下文（每轮 LLM 调用前的边界）。实现见 ``message_ports``。"""
        await inject_steering(self, state)

    async def _inject_follow_up(self, state: AgentState) -> bool:
        """把 follow-up 消息追加进上下文；返回**是否还有下一轮**（外层循环判据）。"""
        return await inject_follow_up(self, state)

    def pause(self) -> None:
        """请求暂停循环：当前进行中的 LLM 调用会跑完，随后在下一轮边界挂起。

        协作式暂停——不打断进行中的 provider 调用、不取消任务；``unpause()`` 后从
        挂起点原地继续（消息、迭代计数、run 上下文均保留）。幂等，可多次调用。
        须在同一事件循环内调用（跨线程请用 ``loop.call_soon_threadsafe`` 包装）。
        """
        pause(self)

    def unpause(self) -> None:
        """恢复被 ``pause()`` 挂起的循环。幂等，可多次调用。"""
        unpause(self)

    @property
    def is_paused(self) -> bool:
        """当前是否处于暂停请求态（循环可能尚未到达挂起点）。"""
        return is_paused(self)

    async def _wait_if_paused(self, run_context: RunContext) -> None:
        """暂停检查点：处于暂停态则挂起，直到 ``unpause()``；前后发 run_paused/run_resumed 事件。"""
        await wait_if_paused(self, run_context)

    # ------------------------------------------------------------------
    # 初始化 / 终结 / 检查点——委托 run_lifecycle
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
        """统一初始化：恢复模式（_resume → 跳过）或全新运行。实现见 ``run_lifecycle``。"""
        return await init_or_resume(self, prompt, system, session_id, _resume, stream=stream)

    async def _init_new_run(
        self,
        prompt: str,
        system: str | None,
        session_id: str | None,
        *,
        stream: bool,
    ) -> tuple[AgentState, RunContext, str | None, TokenUsage]:
        """全新运行的初始化（``run``/``run_stream`` 的「分支①-B」共用）。实现见 ``run_lifecycle``。"""
        return await init_new_run(self, prompt, system, session_id, stream=stream)

    async def _finish_run(
        self,
        run_context: RunContext,
        init: _RunInit,
        state: AgentState,
        accumulated: TokenUsage,
        *,
        final_answer: str,
    ) -> None:
        """正常完成的统一收尾（置 COMPLETED → 落检查点 → 发事件 → 更新 last_* 缓存）。"""
        await finish_run(self, run_context, init, state, accumulated, final_answer=final_answer)

    async def _persist_and_cache(
        self,
        session_id: str | None,
        state: AgentState,
        accumulated: TokenUsage,
        run_context: RunContext,
    ) -> None:
        """持久化会话 + 缓存事后产物（finally 块共用，无论成功/失败均调用）。"""
        await persist_and_cache(self, session_id, state, accumulated, run_context)

    async def _on_run_failed(
        self,
        run_context: RunContext,
        prompt: str,
        system_content: str | None,
        state: AgentState,
        exc: Exception,
        duration_ms: int | None = None,
    ) -> None:
        """异常收尾：置 FAILED、记错误快照、发布 run_failed 事件（不含 re-raise）。

        ``duration_ms`` 缺省 ``None`` = 由 loop 记录的 run 起点现算（``run_elapsed_ms``）——
        此前这条 façade 路径不传耗时，``run_failed`` 事件恒报 ``duration_ms=0``。
        """
        await on_run_failed(self, run_context, prompt, system_content, state, exc, duration_ms=duration_ms)

    async def _start_run_record(self, run_context: RunContext, *, prompt: str, system: str | None) -> None:
        """写入初始运行快照（best-effort：失败仅记日志，不阻断主循环）。"""
        await start_run_record(self, run_context, prompt=prompt, system=system)

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
        """持久化运行进度（best-effort：失败仅记日志，不阻断主循环）。"""
        await checkpoint(
            self,
            run_context,
            prompt=prompt,
            system=system,
            state=state,
            final_answer=final_answer,
            error=error,
        )

    # ------------------------------------------------------------------
    # 迭代控制 / 上下文管理——委托 context_runtime
    # ------------------------------------------------------------------

    def _begin_iteration(self, state: AgentState, run_context: RunContext) -> None:
        """推进迭代计数、发布 iteration_started 事件，并强制迭代硬上限。"""
        begin_iteration(self, state, run_context)

    def _append_assistant_message(self, state: AgentState, response: ProviderResponse) -> None:
        """把助手回复追加进上下文（``run``/``run_stream`` 共用的循环步骤）。"""
        append_assistant_message(self, state, response)

    def _append_tool_result(self, state: AgentState, result: ToolResult) -> None:
        """把单条工具结果追加进上下文（``run``/``run_stream`` 共用）。"""
        append_tool_result(self, state, result)

    async def _maybe_compress(self, state: AgentState, run_context: RunContext, usage: TokenUsage | None) -> None:
        """就地压缩上下文（compressor 启用时）。实现见 ``context_runtime``。"""
        await maybe_compress(self, state, run_context, usage)

    async def _maybe_window_reset(
        self,
        state: AgentState,
        run_context: RunContext,
        prompt: str,
        system_content: str | None,
        *,
        usage: TokenUsage | None = None,
    ) -> None:
        """窗口重置（window_reset 启用时）；达阈值折叠为「原始 prompt + 进度摘要」。"""
        await maybe_window_reset(self, state, run_context, prompt, system_content, usage=usage)

    @staticmethod
    def _add_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
        """把两份 token 用量计数逐字段相加，返回新的 ``TokenUsage``（不可变叠加）。"""
        return add_usage(a, b)

    # ------------------------------------------------------------------
    # 系统提示词 / Provider 调用 / 工具执行（façade 核心留守）
    # ------------------------------------------------------------------

    def _build_system(
        self, user_system: str | None, prompt: str = "", sandbox_workspace: str | None = None
    ) -> str | None:
        """合并生成系统提示词（委托 :func:`build_system_prompt`，保留 skills.record_usage 副作用）。"""
        return build_system_prompt(
            user_system,
            prompt,
            soul=self.soul,
            context_dir=self.context_dir,
            skills=self.skills,
            facts=self.facts,
            profile=self.profile,
            sandbox_workspace=sandbox_workspace,
            settings=self._runtime,
        )

    def _bound_sandbox_workspace(self, run_context: RunContext) -> str | None:
        """本 run **真正生效**的 shell 沙箱工作目录（未生效返回 None）。

        与 executor 的 bind 条件同源：只有存在真实沙箱后端（``executor.sandbox_runner`` 非
        None）时，``metadata["sandbox_workspace"]`` 才会被 bind 给后端并成为 shell 的 cwd /
        ``--private`` 根。开关开启但后端缺席（passthrough）时该目录并不生效——此时**不**向模型
        报任何路径（提示词与真实 cwd 不一致比不提示更坏，见 E40-D2）。
        """
        if self.engine.executor.sandbox_runner is None:
            return None
        value = run_context.metadata.get("sandbox_workspace")
        return value if isinstance(value, str) and value else None

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

        # Phase 5 C1：provider 调用耗时（中间件链整体 wall time，perf_counter 单调钟）。
        _provider_started = time.perf_counter()
        if self.middlewares:
            chain = compose(self.middlewares, handler)
            response = cast("ProviderResponse", await chain(Request(messages=state.messages, tools=tools)))
        else:
            response = await handler(Request(messages=state.messages, tools=tools))
        _provider_duration_ms = max(int((time.perf_counter() - _provider_started) * 1000), 0)

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
                "duration_ms": _provider_duration_ms,
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
    # 运行时上下文 / 事件（façade 核心留守）
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
            stack.enter_context(
                bind_skill_tools(
                    self.skills,
                    manual_load_budget=self._runtime.skill_max_manual_load_tokens,
                    curator_stale_days=self._runtime.skill_curator_stale_days,
                )
            )
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
                announcer=self.subagent_announcer,
                runtime_config=self._runtime,
            )
            stack.enter_context(
                bind_subagent_tools(
                    delegate_one,
                    delegate_many,
                    run_context=run_context,
                    depth=self.delegation_depth,
                    max_depth=self._runtime.subagent_max_depth,
                )
            )
            yield

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
            # 观测插桩的兜底日志自身也必须免于日志故障（否则「发事件失败」会把 run 带走）。
            safe_log(logger, logging.ERROR, "Failed to emit engine event '%s'", event_type, exc_info=True)
