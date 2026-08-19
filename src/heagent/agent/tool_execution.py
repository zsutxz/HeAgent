"""工具执行链 —— 并发执行一批工具调用，端到端含幂等 / 策略裁决 / 执行。

从 ``AgentLoop`` 抽出（原 ``_execute_tools`` / ``_execute_one`` / ``_invoke_handler``
/ ``_invoke``），使 ``loop.py`` 聚焦于「LLM ↔ 工具循环」编排。``AgentLoop`` 保留
``_execute_tools`` / ``_execute_one`` / ``_invoke_handler`` 为薄包装（签名不变——
``_execute_one`` 被 ``test_window_reset`` 直接调用），内部委托本模块。

执行链固定为：``ledger 幂等 → PolicyEngine 裁决 → ToolExecutor 执行（内含 SafetyGuard）→
ledger 回写``。单个工具异常被转成 error ToolResult，不阻塞同批其它调用。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from heagent.engine import ApprovalDecision, ApprovalRequest, ToolExecutionMode
from heagent.types import ToolCall, ToolResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.agent.loop import AgentLoop, AgentState
    from heagent.engine import PolicyVerdict, RunContext

logger = logging.getLogger(__name__)


async def execute_tools(
    loop: AgentLoop,
    calls: list[ToolCall],
    state: AgentState,
    *,
    run_context: RunContext | None = None,
) -> list[ToolResult]:
    """并发执行一批工具调用（``asyncio.gather`` 同时跑），结果按调用顺序返回。

    每个调用经 :func:`execute_tool_call` 走完整的「ledger 幂等 → 策略裁决 → 执行」
    链路；批次前后发布 tool_batch_started/completed 事件，并累加进 state.results。
    """
    loop._emit("tool_batch_started", run_context=run_context, details={"count": len(calls)})
    tasks = [execute_tool_call(loop, call, run_context=run_context) for call in calls]
    results = list(await asyncio.gather(*tasks, return_exceptions=True))
    # 防 asyncio.gather 内部异常向上传播取消整批调用（P1-2 修复）：
    # 若 execute_tool_call 自身抛异常（如 ledger I/O 故障），把异常转成 error ToolResult，
    # 不中断同批其它工具调用。
    safe_results: list[ToolResult] = []
    for i, raw in enumerate(results):
        if isinstance(raw, BaseException):
            tool_call_id = calls[i].id if i < len(calls) else "unknown"
            logger.exception("Unexpected exception in execute_tool_call for %s", tool_call_id)
            safe_results.append(ToolResult(tool_call_id=tool_call_id, content=f"Tool error: {raw}", is_error=True))
        else:
            safe_results.append(raw)
    state.results.extend(safe_results)
    loop._emit(
        "tool_batch_completed",
        run_context=run_context,
        details={"count": len(safe_results), "errors": sum(1 for result in safe_results if result.is_error)},
    )
    return safe_results


async def execute_tool_call(
    loop: AgentLoop,
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
    try:
        if run_context is not None:
            # ① 抢占缓存键。抢不到时按记录状态分两路：
            #    - 已 COMPLETED（有 result）→ 幂等命中，返回缓存（Commit A 会在此复核 policy）。
            #    - lease-active（RUNNING 未过期，并发重入）→ 跳过重复执行，返回 skip 提示。
            cache_key = f"{run_context.run_id}:{call.id}"
            claim = await loop.engine.ledger.acquire(cache_key, run_id=run_context.run_id)
            if not claim.acquired:
                cached = claim.record.metadata.get("result")
                if cached is not None:
                    # A: 缓存命中也复核 policy——若当前 policy 已收紧到 BLOCKED，不返回缓存，
                    #    fall through 走正常链路（下方 evaluate 再算一次 BLOCKED，executor 拦截）。
                    schema = loop.registry.get_schema(call.name)
                    cached_verdict = loop.engine.policy.evaluate_tool_call(call, context=run_context, schema=schema)
                    if cached_verdict.mode is not ToolExecutionMode.BLOCKED:
                        logger.debug("Ledger cache hit for tool_call %s", call.id)
                        loop._emit("tool_call_cached", run_context=run_context, tool_name=call.name, details={})
                        return ToolResult(tool_call_id=call.id, content=cached)
                    logger.debug("Ledger cache bypass for blocked tool_call %s", call.id)
                logger.debug("Ledger lease-active skip for tool_call %s (%s)", call.id, claim.reason)
                loop._emit(
                    "tool_call_skipped_inflight",
                    run_context=run_context,
                    tool_name=call.name,
                    details={"reason": claim.reason},
                )
                return ToolResult(
                    tool_call_id=call.id,
                    content=f"tool '{call.name}' already in-flight (ledger: {claim.reason}); skipped",
                    is_error=True,
                )

        # ② 策略裁决；③ 查 handler。未知工具直接产出 error 结果，不走 executor。
        schema = loop.registry.get_schema(call.name)
        verdict = loop.engine.policy.evaluate_tool_call(call, context=run_context, schema=schema)
        # ②.5 审批交互（Epic 29）：需审批且配置了审批处理器时，先询问再（重新）裁决。
        # 未配置 handler 时 verdict 保持 APPROVAL_REQUIRED，走既有 executor 等同阻断路径（零回归）。
        if verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED and loop.engine.approval_handler is not None:
            verdict = await _resolve_approval(loop, call, verdict, run_context)
        handler = loop.registry.get_handler(call.name)
        # ②.6 PreToolUse hooks（Epic 32）：可阻断工具调用（block hook 退出码非 0 → 阻断）。
        hook_feedback: str | None = None
        if loop.engine.hooks is not None:
            hook_result = await loop.engine.hooks.run_pre_tool(call, run_context)
            if hook_result.blocked:
                hook_feedback = hook_result.feedback
        if hook_feedback is not None:
            loop._emit(
                "tool_call_blocked",
                run_context=run_context,
                tool_name=call.name,
                details={"reason": "hook", "feedback": hook_feedback},
            )
            result = ToolResult(
                tool_call_id=call.id,
                content=f"Tool '{call.name}' blocked by hook: {hook_feedback}",
                is_error=True,
            )
        elif handler is None:
            loop._emit(
                "tool_call_failed",
                run_context=run_context,
                tool_name=call.name,
                details={"error": "unknown tool"},
            )
            result = ToolResult(tool_call_id=call.id, content=f"Unknown tool: {call.name}", is_error=True)
        else:
            # ③ 真正执行：executor 在 verdict（准许/审批/沙箱）框架下调度 handler，
            #    内部还会经 loop.guard（SafetyGuard）做命令黑名单等检查。
            result = await loop.engine.executor.execute(
                call=call,
                verdict=verdict,
                guard=loop.guard,
                handler=loop._invoke_handler,
                run_context=run_context,
                emit=loop._emit,
            )
            # PostToolUse hooks（Epic 32）：通知，不阻断。
            if loop.engine.hooks is not None:
                await loop.engine.hooks.run_post_tool(call, run_context)

        # ④ 结果回写 ledger：成功记 complete（带结果供后续幂等），失败记 fail（允许重试）。
        if cache_key is not None:
            if result.is_error:
                await loop.engine.ledger.fail(cache_key, result.content)
            else:
                await loop.engine.ledger.complete(cache_key, metadata={"result": result.content})
        return result
    except Exception as exc:
        # P1-2 修复：ledger acquire / policy evaluate 等非 handler 异常也转为 error ToolResult，
        # 不向上抛导致 asyncio.gather 取消整批并发调用。
        logger.exception("Unhandled exception in execute_tool_call for %s", call.name)
        loop._emit(
            "tool_call_failed",
            run_context=run_context,
            tool_name=call.name,
            details={"error": str(exc)},
        )
        return ToolResult(tool_call_id=call.id, content=f"Tool error: {exc}", is_error=True)


async def _resolve_approval(
    loop: AgentLoop,
    call: ToolCall,
    verdict: PolicyVerdict,
    run_context: RunContext | None,
) -> PolicyVerdict:
    """审批交互：询问审批处理器；APPROVE 则写入 per-run 授权并重新裁决，DENY 保持原 verdict。

    handler 抛异常时 fail-safe 视为 DENY（不执行工具），保证可预测安全语义。
    授权写入 ``RunContext.metadata["approved_tools"]``，复用
    :meth:`PolicyEngine._approval_granted` 的既有读取逻辑（per-run 粒度）。
    """
    handler = loop.engine.approval_handler
    if handler is None:  # 防御性：调用方已确保非 None，此处兜底返回原 verdict。
        return verdict
    decision = ApprovalDecision.DENY
    try:
        decision = await handler.request(ApprovalRequest(tool_name=call.name, reason=verdict.reason, call=call))
    except Exception:
        logger.exception("approval handler failed for tool '%s'; denying", call.name)
        decision = ApprovalDecision.DENY

    loop._emit(
        "tool_call_approval",
        run_context=run_context,
        tool_name=call.name,
        details={"decision": decision.value, "reason": verdict.reason},
    )

    if decision is ApprovalDecision.APPROVE:
        # 写入 per-run 授权（列表追加，幂等）。
        if run_context is not None:
            approved = run_context.metadata.setdefault("approved_tools", [])
            if isinstance(approved, list) and call.name not in approved:
                approved.append(call.name)
        # 重新裁决：授权命中后审批步骤应被跳过，得到 DIRECT / SANDBOX_REQUIRED。
        schema = loop.registry.get_schema(call.name)
        return loop.engine.policy.evaluate_tool_call(call, context=run_context, schema=schema)
    # DENY：保持 APPROVAL_REQUIRED，交给 executor 转 error（与现状一致）。
    return verdict


async def invoke_handler(loop: AgentLoop, call: ToolCall) -> object:
    """解析并调用一次工具调用对应的注册 handler（executor 的执行回调）。

    未知工具直接抛 RuntimeError（executor 外层会捕获并转成 ToolResult.error）。
    """
    handler = loop.registry.get_handler(call.name)
    if handler is None:
        raise RuntimeError(f"Unknown tool: {call.name}")
    return await _invoke(handler, call)


async def _invoke(handler: object, call: ToolCall) -> object:
    """实际调用 handler：自动适配 sync / async / __call__ 异步对象。

    先调用再检测返回值类型（而非用 ``iscoroutinefunction`` 预判），避免
    ``functools.partial`` / ``__call__`` 异步对象等场景误入同步路径（P1-19 修复）。
    """
    fn = cast("Callable[..., Any]", handler)
    result = fn(**call.arguments)
    if asyncio.iscoroutine(result):
        return await result
    return result
