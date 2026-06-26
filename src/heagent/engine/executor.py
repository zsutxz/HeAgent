"""Tool execution dispatch for direct, approval, and sandboxed flows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from heagent.engine.policy import PolicyEngine, PolicyVerdict, ToolExecutionMode
from heagent.exceptions import PolicyViolation, SafetyViolation
from heagent.types import ToolCall, ToolResult

if TYPE_CHECKING:
    from heagent.engine.context import RunContext
    from heagent.tools.safety import SafetyGuard

Handler = Callable[[ToolCall], Awaitable[object]]


class ToolExecutor:
    """Dispatch tool calls according to the active policy verdict."""

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
        """Execute one tool call using the policy-selected mode."""
        if verdict.mode is ToolExecutionMode.BLOCKED:
            return self._policy_error(call, verdict, run_context=run_context, emit=emit)
        if verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED:
            return self._policy_error(call, verdict, run_context=run_context, emit=emit)
        if verdict.mode is ToolExecutionMode.SANDBOX_REQUIRED:
            return await self._execute_in_sandbox(
                call=call,
                verdict=verdict,
                guard=guard,
                handler=handler,
                run_context=run_context,
                emit=emit,
            )
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
        try:
            guard.check(call)
        except SafetyViolation as exc:
            if emit:
                emit(
                    "tool_call_blocked",
                    run_context=run_context,
                    tool_name=call.name,
                    details={"reason": str(exc), "mode": ToolExecutionMode.BLOCKED.value},
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
        except Exception as exc:  # noqa: BLE001
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
                    details={"reason": str(exc), "mode": ToolExecutionMode.BLOCKED.value},
                )
            return ToolResult(tool_call_id=call.id, content=str(exc), is_error=True)

        try:
            if emit:
                emit(
                    "tool_call_started",
                    run_context=run_context,
                    tool_name=call.name,
                    details={
                        "mode": ToolExecutionMode.SANDBOX_REQUIRED.value,
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
                        "mode": ToolExecutionMode.SANDBOX_REQUIRED.value,
                        "sandbox_profile": verdict.sandbox_profile or "",
                        "content_length": len(content),
                    },
                )
            return ToolResult(tool_call_id=call.id, content=content)
        except Exception as exc:  # noqa: BLE001
            if emit:
                emit(
                    "tool_call_failed",
                    run_context=run_context,
                    tool_name=call.name,
                    details={
                        "mode": ToolExecutionMode.SANDBOX_REQUIRED.value,
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
        """Execute a tool through the configured sandbox backend.

        The default implementation is a passthrough. A future backend can
        override this method or replace the executor in EngineContainer.
        """
        return await handler(call)

    def _policy_error(
        self,
        call: ToolCall,
        verdict: PolicyVerdict,
        *,
        run_context: RunContext | None,
        emit: Callable[..., None] | None,
    ) -> ToolResult:
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
        return PolicyEngine.context_grants_sandbox(
            call,
            context=run_context,
            sandbox_profile=verdict.sandbox_profile,
        )
