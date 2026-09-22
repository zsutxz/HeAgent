"""按策略裁决结果分发工具调用（executor）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。工具执行链固定为
``PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler``。本模块负责其中
「ToolExecutor」一环：接收 :class:`~heagent.engine.policy.PolicyVerdict`，按其 ``mode``
选择执行路径，并在内部串行调用 :class:`~heagent.tools.safety.SafetyGuard`。

分发规则（:meth:`ToolExecutor.execute`）：

- ``BLOCKED`` / ``APPROVAL_REQUIRED`` —— 不执行，返回 :class:`ToolResult` 错误结果
  （``is_error=True``）；V1 未接审批交互，故 ``APPROVAL_REQUIRED`` 当前等同阻断。
- ``SANDBOX_REQUIRED`` —— 先复核沙箱授权（:meth:`_sandbox_granted`），未授权则同上返回
  错误；已授权则过 guard 后走 :meth:`execute_in_sandbox`。
- ``DIRECT`` —— 过 guard 后直接调 handler。

异常处理约定：handler 抛出的任何异常都被捕获并转成 ``is_error=True`` 的 :class:`ToolResult`
返回（不向上抛）——让错误以工具结果形式进入 LLM 上下文，而非中断循环。经 ``emit`` 发布
started / completed / failed / blocked 事件供可观测。

⚠ 安全边界声明：:meth:`execute_in_sandbox` 默认为**透传**（直接调 handler），未接真实沙箱
后端，``SANDBOX_REQUIRED`` 不产生 OS 级隔离效果——须 OS 级沙箱兜底（见 CLAUDE.md）。
"""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heagent.engine.policy import PolicyEngine, PolicyVerdict, ToolExecutionMode
from heagent.events.protocol import error_kind_for
from heagent.exceptions import PolicyViolation, SafetyViolation
from heagent.tools.call_summary import summarize_tool_call
from heagent.tools.sandbox import (
    CommandRunner,
    SandboxTier,
    bind_command_runner,
    bind_sandbox_profile,
    bind_sandbox_session,
    bind_sandbox_workspace,
    get_or_create_session,
)
from heagent.types import ToolCall, ToolResult

if TYPE_CHECKING:
    from heagent.engine.context import RunContext
    from heagent.tools.safety import SafetyGuard

logger = logging.getLogger(__name__)

# 工具处理器签名：接收 ToolCall，返回任意结果（executor 会 str() 化为 ToolResult.content）。
Handler = Callable[[ToolCall], Awaitable[object]]


def _session_workspace(run_context: RunContext | None) -> Path | None:
    """从 ``run_context.metadata`` 提取并校验沙箱会话目录（FR-1）。

    无键 / 非 str / 空串 → None（不 bind，行为与现状一致）；路径不存在 → 抛
    ``RuntimeError("sandbox workspace missing: <path>")`` 显性失败（bind 前拦下，
    不让不存在的目录直入 ``--private=`` / ``cwd=``）。
    """
    if run_context is None:
        return None
    raw = run_context.metadata.get("sandbox_workspace")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if not path.exists():
        raise RuntimeError(f"sandbox workspace missing: {path}")
    return path


class ToolExecutor:
    """按当前 policy verdict 分发工具调用。"""

    def __init__(self, *, sandbox_runner: CommandRunner | None = None) -> None:
        """记 ``SANDBOX_REQUIRED`` 路径用的后端（None 时 :meth:`execute_in_sandbox` 透传）。"""
        self.sandbox_runner = sandbox_runner

    @staticmethod
    def _target(call: ToolCall) -> str:
        """该调用的「作用对象」摘要（读写的文件 / 命令 / URL / 子 Agent 角色）。

        唯一产自 :func:`heagent.tools.call_summary.summarize_tool_call`——日志、流式事件与
        各展示层共用同一份格式化，避免多处映射漂移；永不抛异常（退化为空串）。
        """
        return summarize_tool_call(call.name, call.arguments)

    def _runner_tier(self) -> SandboxTier:
        """当前沙箱后端的强度档位；无后端（透传快速路径）时为 ``PASSTHROUGH``。

        库消费者的自定义 runner 可能未声明 ``tier``（旧 ``CommandRunner`` 契约无此
        属性）——按最弱档 ``PASSTHROUGH`` 处理（fail-safe：未知强度不误判为强隔离）。
        """
        if self.sandbox_runner is None:
            return SandboxTier.PASSTHROUGH
        return getattr(self.sandbox_runner, "tier", SandboxTier.PASSTHROUGH)

    async def execute(
        self,
        *,
        call: ToolCall,
        verdict: PolicyVerdict,
        guard: SafetyGuard,
        handler: Handler,
        run_context: RunContext | None = None,
        emit: Callable[..., None] | None = None,
    ) -> ToolResult:
        """按 verdict.mode 选择路径执行一次工具调用。

        ``guard`` / ``handler`` 由调用方（AgentLoop._execute_one）注入；``emit`` 为可选的
        事件发布回调（通常绑定到 EngineContainer.events.publish）。
        """
        # BLOCKED：策略硬阻断 → 返回错误结果。
        if verdict.mode is ToolExecutionMode.BLOCKED:
            return self._policy_error(call, verdict, run_context=run_context, emit=emit)
        # APPROVAL_REQUIRED：V1 未接审批交互，当前等同阻断 → 返回错误结果。
        if verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED:
            return self._policy_error(call, verdict, run_context=run_context, emit=emit)
        # SANDBOX_REQUIRED：走沙箱路径（内部会复核授权）。
        if verdict.mode is ToolExecutionMode.SANDBOX_REQUIRED:
            return await self._execute_in_sandbox(
                call=call,
                verdict=verdict,
                guard=guard,
                handler=handler,
                run_context=run_context,
                emit=emit,
            )
        # DIRECT：直接执行。
        return await self._execute_direct(
            call=call,
            guard=guard,
            handler=handler,
            run_context=run_context,
            emit=emit,
        )

    def _emit_tool_event(
        self,
        emit: Callable[..., None] | None,
        event: str,
        call: ToolCall,
        run_context: RunContext | None,
        details: dict[str, Any],
    ) -> None:
        """工具生命周期事件的**唯一**发出点。

        ``event`` 与 ``details`` 由调用方给出（各路径附加的键不同：``sandbox_profile`` /
        ``sandbox_tier`` / ``content_length`` / ``error``），但 ``run_context`` / ``tool_name``
        / ``target`` 的取值与字段约定在此单点固定——此前 8 处 emit 各自复制这段样板，
        字段一改就得全改。``emit`` 为 None（未订阅可观测）时静默跳过。
        """
        if emit is None:
            return
        emit(
            event,
            run_context=run_context,
            tool_name=call.name,
            target=self._target(call),
            details=details,
        )

    def _guard_or_blocked(
        self,
        call: ToolCall,
        guard: SafetyGuard,
        *,
        run_context: RunContext | None,
        emit: Callable[..., None] | None,
    ) -> ToolResult | None:
        """跑 ``SafetyGuard.check(call)``：拦下则发事件并返回错误结果，通过则返回 ``None``。

        把「拦下 / 通过」固定为单一形状，避免 DIRECT 与 SANDBOX 两条路径各写一遍 try/except。
        """
        try:
            guard.check(call)
        except SafetyViolation as exc:
            # P1-6：mode 标成 safety_blocked，以区分触发层（SafetyGuard）与策略层阻断。
            self._emit_tool_event(
                emit,
                "tool_call_blocked",
                call,
                run_context,
                {"reason": str(exc), "mode": "safety_blocked"},
            )
            return ToolResult(tool_call_id=call.id, content=str(exc), is_error=True)
        return None

    async def _execute_direct(
        self,
        *,
        call: ToolCall,
        guard: SafetyGuard,
        handler: Handler,
        run_context: RunContext | None,
        emit: Callable[..., None] | None,
    ) -> ToolResult:
        """DIRECT 模式：guard.check → handler。

        guard 抛 :class:`SafetyViolation` → 返回错误结果（不向上抛）；
        handler 抛任何异常 → 转成 ``is_error=True`` 的 ToolResult。
        """
        blocked = self._guard_or_blocked(call, guard, run_context=run_context, emit=emit)
        if blocked is not None:
            return blocked

        mode = ToolExecutionMode.DIRECT.value
        try:
            self._emit_tool_event(emit, "tool_call_started", call, run_context, {"mode": mode})
            _started = time.perf_counter()
            result = await handler(call)
            content = str(result) if result is not None else ""
            self._emit_tool_event(
                emit,
                "tool_call_completed",
                call,
                run_context,
                {
                    "mode": mode,
                    "content_length": len(content),
                    "duration_ms": max(int((time.perf_counter() - _started) * 1000), 0),
                },
            )
            return ToolResult(tool_call_id=call.id, content=content)
        except Exception as exc:  # noqa: BLE001 - 任意工具异常都转成错误结果，避免中断循环
            self._emit_tool_event(
                emit,
                "tool_call_failed",
                call,
                run_context,
                {
                    "mode": mode,
                    "error": str(exc),
                    "error_kind": error_kind_for(exc),
                    "duration_ms": max(int((time.perf_counter() - _started) * 1000), 0),
                },
            )
            return ToolResult(tool_call_id=call.id, content=f"Tool error: {exc}", is_error=True)

    async def _execute_in_sandbox(
        self,
        *,
        call: ToolCall,
        verdict: PolicyVerdict,
        guard: SafetyGuard,
        handler: Handler,
        run_context: RunContext | None,
        emit: Callable[..., None] | None,
    ) -> ToolResult:
        """SANDBOX_REQUIRED 模式：复核授权 → guard.check → execute_in_sandbox。

        双重授权复核（policy 已判 mode，此处再验）：未授权则返回策略错误，防越权执行。
        """
        if not self._sandbox_granted(call, run_context, verdict):
            return self._policy_error(call, verdict, run_context=run_context, emit=emit)

        blocked = self._guard_or_blocked(call, guard, run_context=run_context, emit=emit)
        if blocked is not None:
            return blocked

        sandbox_mode = ToolExecutionMode.SANDBOX_REQUIRED.value
        sandbox_tier = self._runner_tier().value
        # 沙箱路径的事件额外带上 profile / tier：「这条命令到底在哪层隔离下跑的」得能查。
        sandbox_facts = {"sandbox_profile": verdict.sandbox_profile or "", "sandbox_tier": sandbox_tier}
        try:
            self._emit_tool_event(emit, "tool_call_started", call, run_context, {"mode": sandbox_mode, **sandbox_facts})
            _started = time.perf_counter()
            # 子类 override 兼容：库消费者旧签名 execute_in_sandbox(*, call, profile, handler)
            # 不含 run_context——签名探测后按需传参，防 TypeError（FR-1 review patch 5）。
            if "run_context" in inspect.signature(self.execute_in_sandbox).parameters:
                result = await self.execute_in_sandbox(
                    call=call,
                    profile=verdict.sandbox_profile,
                    handler=handler,
                    run_context=run_context,
                )
            else:
                result = await self.execute_in_sandbox(
                    call=call,
                    profile=verdict.sandbox_profile,
                    handler=handler,
                )
            content = str(result) if result is not None else ""
            self._emit_tool_event(
                emit,
                "tool_call_completed",
                call,
                run_context,
                {
                    "mode": sandbox_mode,
                    **sandbox_facts,
                    "content_length": len(content),
                    "duration_ms": max(int((time.perf_counter() - _started) * 1000), 0),
                },
            )
            return ToolResult(tool_call_id=call.id, content=content)
        except Exception as exc:  # noqa: BLE001 - 任意工具异常都转成错误结果，避免中断循环
            self._emit_tool_event(
                emit,
                "tool_call_failed",
                call,
                run_context,
                {
                    "mode": sandbox_mode,
                    **sandbox_facts,
                    "error": str(exc),
                    "error_kind": error_kind_for(exc),
                    "duration_ms": max(int((time.perf_counter() - _started) * 1000), 0),
                },
            )
            return ToolResult(tool_call_id=call.id, content=f"Tool error: {exc}", is_error=True)

    async def execute_in_sandbox(
        self,
        *,
        call: ToolCall,
        profile: str | None,
        handler: Handler,
        run_context: RunContext | None = None,
    ) -> object:
        """经配置的沙箱后端执行工具。

        默认实现：配置了 ``sandbox_runner`` 则经 :func:`bind_command_runner` + :func:`bind_sandbox_profile`
        注入到 handler（shell 等 handler 内 ``get_command_runner()`` / ``get_sandbox_profile()``
        取到对应值），否则透传直接调 handler。
        FR-1（沙箱会话目录）：``run_context.metadata["sandbox_workspace"]`` 存在（开关开启时
        由 :meth:`EngineContainer.create_run_context <heagent.engine.container.EngineContainer.create_run_context>`
        写入）时再经 :func:`bind_sandbox_workspace` 把 per-run 目录送达后端（Firejail ``--private``
        根 / WinJob 子进程 cwd）；无该键时不 bind，行为与现状一致。
        子类可覆写本方法替换整套沙箱语义（见 ``tests/test_engine_p0.py`` 的 ``RecordingExecutor``）。
        ⚠ 默认 Passthrough 不产生 OS 级隔离；FirejailBackend 仅隔离 shell 子进程、Linux-only、
        非完美边界；WinJob 会话目录仅 cwd 约定、无文件系统隔离——须 OS 级沙箱兜底（见 CLAUDE.md）。
        """
        if self.sandbox_runner is None:
            if run_context is not None and isinstance(run_context.metadata.get("sandbox_workspace"), str):
                logger.warning(
                    "sandbox_workspace ignored: no sandbox backend (sandbox_runner is None); "
                    "tool '%s' runs passthrough without per-run session directory",
                    call.name,
                )
            logger.warning(
                "SANDBOX_REQUIRED verdict but sandbox_runner is None; "
                "executing tool '%s' in passthrough (no OS-level isolation)",
                call.name,
            )
            return await handler(call)
        workspace = _session_workspace(run_context)
        with bind_command_runner(self.sandbox_runner), bind_sandbox_profile(profile):
            # workspace 非 None 蕴含 run_context 非 None（_session_workspace(None) → None）；
            # 用 or 收窄类型（避免 bandit S101 assert）。
            if workspace is None or run_context is None:
                return await handler(call)
            session = get_or_create_session(run_context.run_id, workspace)
            with bind_sandbox_workspace(workspace), bind_sandbox_session(session):
                return await handler(call)

    def _policy_error(
        self,
        call: ToolCall,
        verdict: PolicyVerdict,
        *,
        run_context: RunContext | None,
        emit: Callable[..., None] | None,
    ) -> ToolResult:
        """把 BLOCKED / APPROVAL_REQUIRED 裁决转成错误 ToolResult（不抛异常）。"""
        message = str(PolicyViolation(verdict.reason))
        # 键序（reason → mode → sandbox_profile）与 SafetyGuard 拦截的事件形状不同，保持既有契约。
        self._emit_tool_event(
            emit,
            "tool_call_blocked",
            call,
            run_context,
            {"reason": verdict.reason, "mode": verdict.mode.value, "sandbox_profile": verdict.sandbox_profile or ""},
        )
        return ToolResult(tool_call_id=call.id, content=message, is_error=True)

    @staticmethod
    def _sandbox_granted(call: ToolCall, run_context: RunContext | None, verdict: PolicyVerdict) -> bool:
        """复核当前 run 是否授予该调用的沙箱执行权（委托 PolicyEngine.context_grants_sandbox）。"""
        return PolicyEngine.context_grants_sandbox(
            call,
            context=run_context,
            sandbox_profile=verdict.sandbox_profile,
        )
