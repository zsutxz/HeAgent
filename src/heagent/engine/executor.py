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

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from heagent.engine.policy import PolicyEngine, PolicyVerdict, ToolExecutionMode
from heagent.exceptions import PolicyViolation, SafetyViolation
from heagent.tools.sandbox import CommandRunner, bind_command_runner, bind_sandbox_profile
from heagent.types import ToolCall, ToolResult

if TYPE_CHECKING:
    from heagent.engine.context import RunContext
    from heagent.tools.safety import SafetyGuard

logger = logging.getLogger(__name__)

# 工具处理器签名：接收 ToolCall，返回任意结果（executor 会 str() 化为 ToolResult.content）。
Handler = Callable[[ToolCall], Awaitable[object]]


class ToolExecutor:
    """按当前 policy verdict 分发工具调用。"""

    def __init__(self, *, sandbox_runner: CommandRunner | None = None) -> None:
        """记 ``SANDBOX_REQUIRED`` 路径用的后端（None 时 :meth:`execute_in_sandbox` 透传）。"""
        self.sandbox_runner = sandbox_runner

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
        try:
            guard.check(call)
        except SafetyViolation as exc:
            if emit:
                emit(
                    "tool_call_blocked",
                    run_context=run_context,
                    tool_name=call.name,
                    details={
                        "reason": str(exc),
                        "mode": "safety_blocked",  # P1-6 修复：标识触发层为 SafetyGuard 而非 Policy
                    },
                )
            return ToolResult(tool_call_id=call.id, content=str(exc), is_error=True)

        try:
            if emit:
                emit(
                    "tool_call_started",
                    run_context=run_context,
                    tool_name=call.name,
                    details={"mode": ToolExecutionMode.DIRECT.value},
                )
            result = await handler(call)
            content = str(result) if result is not None else ""
            if emit:
                emit(
                    "tool_call_completed",
                    run_context=run_context,
                    tool_name=call.name,
                    details={"mode": ToolExecutionMode.DIRECT.value, "content_length": len(content)},
                )
            return ToolResult(tool_call_id=call.id, content=content)
        except Exception as exc:  # noqa: BLE001 - 任意工具异常都转成错误结果，避免中断循环
            if emit:
                emit(
                    "tool_call_failed",
                    run_context=run_context,
                    tool_name=call.name,
                    details={"mode": ToolExecutionMode.DIRECT.value, "error": str(exc)},
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

        try:
            guard.check(call)
        except SafetyViolation as exc:
            if emit:
                emit(
                    "tool_call_blocked",
                    run_context=run_context,
                    tool_name=call.name,
                    details={
                        "reason": str(exc),
                        "mode": "safety_blocked",  # P1-6 修复
                    },
                )
            return ToolResult(tool_call_id=call.id, content=str(exc), is_error=True)

        sandbox_mode = ToolExecutionMode.SANDBOX_REQUIRED.value
        try:
            if emit:
                emit(
                    "tool_call_started",
                    run_context=run_context,
                    tool_name=call.name,
                    details={
                        "mode": sandbox_mode,
                        "sandbox_profile": verdict.sandbox_profile or "",
                    },
                )
            result = await self.execute_in_sandbox(call=call, profile=verdict.sandbox_profile, handler=handler)
            content = str(result) if result is not None else ""
            if emit:
                emit(
                    "tool_call_completed",
                    run_context=run_context,
                    tool_name=call.name,
                    details={
                        "mode": sandbox_mode,
                        "sandbox_profile": verdict.sandbox_profile or "",
                        "content_length": len(content),
                    },
                )
            return ToolResult(tool_call_id=call.id, content=content)
        except Exception as exc:  # noqa: BLE001 - 任意工具异常都转成错误结果，避免中断循环
            if emit:
                emit(
                    "tool_call_failed",
                    run_context=run_context,
                    tool_name=call.name,
                    details={
                        "mode": sandbox_mode,
                        "sandbox_profile": verdict.sandbox_profile or "",
                        "error": str(exc),
                    },
                )
            return ToolResult(tool_call_id=call.id, content=f"Tool error: {exc}", is_error=True)

    async def execute_in_sandbox(
        self,
        *,
        call: ToolCall,
        profile: str | None,
        handler: Handler,
    ) -> object:
        """经配置的沙箱后端执行工具。

        默认实现：配置了 ``sandbox_runner`` 则经 :func:`bind_command_runner` + :func:`bind_sandbox_profile`
        注入到 handler（shell 等 handler 内 ``get_command_runner()`` / ``get_sandbox_profile()``
        取到对应值），否则透传直接调 handler。
        子类可覆写本方法替换整套沙箱语义（见 ``tests/test_engine_p0.py`` 的 ``RecordingExecutor``）。
        ⚠ 默认 Passthrough 不产生 OS 级隔离；FirejailBackend 仅隔离 shell 子进程、Linux-only、
        非完美边界——须 OS 级沙箱兜底（见 CLAUDE.md）。
        """
        if self.sandbox_runner is None:
            logger.warning(
                "SANDBOX_REQUIRED verdict but sandbox_runner is None; "
                "executing tool '%s' in passthrough (no OS-level isolation)",
                call.name,
            )
            return await handler(call)
        with bind_command_runner(self.sandbox_runner), bind_sandbox_profile(profile):
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
        if emit:
            emit(
                "tool_call_blocked",
                run_context=run_context,
                tool_name=call.name,
                details={
                    "reason": verdict.reason,
                    "mode": verdict.mode.value,
                    "sandbox_profile": verdict.sandbox_profile or "",
                },
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
