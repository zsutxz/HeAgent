"""工具执行链 —— 并发执行一批工具调用，端到端含幂等 / 策略裁决 / 执行。

从 ``AgentLoop`` 抽出（原 ``_execute_tools`` / ``_execute_one`` / ``_invoke_handler``
/ ``_invoke``），使 ``loop.py`` 聚焦于「LLM ↔ 工具循环」编排。``AgentLoop`` 保留
``_execute_tools`` / ``_execute_one`` / ``_invoke_handler`` 为薄包装（签名不变——
``_execute_one`` 被 ``test_window_reset`` 直接调用），内部委托本模块。

执行链固定为：``ledger 幂等 → PolicyEngine 裁决 → ToolExecutor 执行（内含 SafetyGuard）→
ledger 回写``。单个工具异常被转成 error ToolResult，不阻塞同批其它调用。

**ledger 只是幂等缓存，不拥有工具结果**，因此这里有两条硬性约定：

1. **在途期间续租**（``_renew_ledger_lease``）：工具可以跑很久（``shell`` 的 ``timeout``
   可达数分钟），而 ledger 记录带 120s 租约——租约过期后任何进程的 ``prune`` 都会把它
   视为「孤儿 RUNNING」删掉（见 ``engine/ledger.py`` 的 prune 语义）。长时调用结束再
   ``complete()`` 就会撞 ``Cannot complete non-existent key``，把跑完的成果换成一条记账
   报错（实测踩坑：一次 6 分半的 pytest 输出被整段丢弃，模型只好重跑一遍）。故在途期间
   后台周期续租，让「租约过期 = 真孤儿」这一 prune 前提成立。
2. **回写失败不改结果**（``_record_ledger_outcome``）：即便记录仍被清掉（如另一进程在续租
   窗口内 prune、I/O 故障），也只记 warning 并（成功路径）**把记录重建为 COMPLETED**，
   绝不把成功的工具结果替换成 error ToolResult——缓存丢了最多是重发时重复执行一次，
   结果丢了是整轮白干。重建只开在工具调用这一个调用点（``recreate_if_missing=True``），
   ledger 的默认严格语义（防误键凭空建记录）不变。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from heagent.engine import ApprovalDecision, ApprovalRequest, ToolExecutionMode
from heagent.pub.safe_logging import safe_log
from heagent.pub.types import ToolCall, ToolResult
from heagent.tools.call_summary import activity_label, summarize_tool_call

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.agent.loop import AgentLoop, AgentState
    from heagent.engine import PolicyVerdict, RunContext
    from heagent.engine.ledger import ExecutionLedger

logger = logging.getLogger(__name__)

# ── ledger 租约续期（长时工具调用）─────────────────────────────────
# 租约长度与续期间隔：间隔取租约的 1/3，保证单个心跳周期内的时钟抖动/事件循环排队
# 不会让租约在两次续期之间过期。两者都可在测试中替换（见 tests/test_window_reset.py）。
_LEDGER_LEASE_SECONDS = 120
_LEDGER_LEASE_RENEW_INTERVAL = 40


async def _renew_ledger_lease(ledger: ExecutionLedger, key: str) -> None:
    """工具在途期间周期续租，直到被调用方取消（或记录已消失）。

    这是尽力而为的保活：记录被清掉（``heartbeat`` 返回 ``None``）或续租本身 I/O 失败都
    只记 warning，**不抛错**——工具结果由 :func:`_record_ledger_outcome` 与调用方兜底，
    绝不能因为「保不住缓存键」而打断正在跑的工具。

    实现上刻意用 ``asyncio.sleep`` 循环而非 ``asyncio.TimerHandle``：间隔远大于单次
    ``to_thread`` 落盘耗时，无需担心漂移累积。
    """
    while True:
        await asyncio.sleep(_LEDGER_LEASE_RENEW_INTERVAL)
        try:
            record = await ledger.heartbeat(key, lease_seconds=_LEDGER_LEASE_SECONDS)
        except Exception:
            # 注意 CancelledError 是 BaseException，不会被这里吞掉——取消续租任务
            # （execute_tool_call 的 finally）仍按取消语义退出。
            safe_log(logger, logging.WARNING, "Ledger lease renewal failed for %s; will retry", key, exc_info=True)
            continue
        if record is None:
            # 记录已被清理（或已终态）：续租已无意义，退出让回写路径去报告。
            safe_log(logger, logging.WARNING, "Ledger record %s vanished while the tool was in flight", key)
            return


async def _record_ledger_outcome(loop: AgentLoop, cache_key: str, result: ToolResult) -> None:
    """把工具结果写回 ledger（成功 ``complete`` / 失败 ``fail``），**失败只告警**。

    幂等记账是旁路：记账失败（记录被 prune 清掉、跨进程锁冲突、磁盘故障……）不得改写
    工具结果，否则「跑成功的工具」会被降级成一条 ``Tool error: Cannot complete ...``。

    成功路径带 ``recreate_if_missing=True``（唯一开这档的调用点）：记录若在工具在途期间被
    别的进程清掉，就按「本次确实完成了」重建为 COMPLETED——保住幂等缓存，避免模型重发同一
    ``tool_call.id`` 时把有副作用的工具再跑一遍。失败路径不开：FAILED 语义本就允许重试，
    没有值得保住的结果。
    """
    try:
        if result.is_error:
            await loop.engine.ledger.fail(cache_key, result.content)
        else:
            await loop.engine.ledger.complete(cache_key, metadata={"result": result.content}, recreate_if_missing=True)
    except Exception:
        safe_log(
            logger,
            logging.WARNING,
            "Failed to record ledger outcome for %s (tool result kept; idempotency cache lost)",
            cache_key,
            exc_info=True,
        )


def _activity_labels(calls: list[ToolCall]) -> list[str]:
    """把一批调用渲染成活动标签 ``<tool> → <target>``（无作用对象时只留工具名）。

    同一份标签同时喂给状态栏（``loop.active_tool``）与 run 级活动台账
    （``loop.tool_activity``），保证「正在跑什么」与「跑完回看什么」不会两套口径；
    拼接统一经 :func:`heagent.tools.call_summary.activity_label`——GUI 侧（bridge /
    聊天日志）走同一函数，避免两端各拼箭头而漂移。
    """
    return [activity_label(call.name, summarize_tool_call(call.name, call.arguments)) for call in calls]


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

    顺带维护 run 作用域的展示态：在途期间 ``loop.active_tool`` 非空（状态栏可见），
    并把每个调用的活动标签追加进 ``loop.tool_activity``（单次模式跑完回显）。
    """
    loop._emit("tool_batch_started", run_context=run_context, details={"count": len(calls)})
    # 状态栏要看到「卡在哪个工具」，活动台账要留「这次 run 试过动什么」——两者同源。
    # 台账在执行**前**登记：被阻止 / 命中缓存的调用也留痕（回看时同等重要），
    # 故其语义是「调用尝试」而非「执行成功」，展示文案据此刻画。
    labels = _activity_labels(calls)
    loop.tool_activity.extend(labels)
    if labels:
        loop.active_tool = labels[0] if len(labels) == 1 else f"{labels[0]} (+{len(labels) - 1})"
    safe_results: list[ToolResult] = []
    try:
        tasks = [execute_tool_call(loop, call, run_context=run_context) for call in calls]
        results = list(await asyncio.gather(*tasks, return_exceptions=True))
        # 防 asyncio.gather 内部异常向上传播取消整批调用（P1-2 修复）：
        # 若 execute_tool_call 自身抛异常（如 ledger I/O 故障），把异常转成 error ToolResult，
        # 不中断同批其它工具调用。
        for i, raw in enumerate(results):
            if isinstance(raw, BaseException):
                tool_call_id = calls[i].id if i < len(calls) else "unknown"
                logger.exception("Unexpected exception in execute_tool_call for %s", tool_call_id)
                safe_results.append(ToolResult(tool_call_id=tool_call_id, content=f"Tool error: {raw}", is_error=True))
            else:
                safe_results.append(raw)
        state.results.extend(safe_results)
    finally:
        # 走到这里即「本批已不在途」；取消（CancelledError）同样经此清空，
        # 否则被中断的 run 会把陈旧工具留在状态栏上。
        loop.active_tool = ""
    loop._emit(
        "tool_batch_completed",
        run_context=run_context,
        details={"count": len(safe_results), "errors": sum(1 for result in safe_results if result.is_error)},
    )
    return safe_results


@dataclass(slots=True)
class _LedgerClaim:
    """① 幂等闸门的产物（内部状态对象，与 ``AgentState`` / ``SubAgentResult`` 同为 dataclass 例外）。

    - ``cache_key`` 为 None：本次调用无 run 上下文，不走记账；
    - ``result`` 非 None：闸门已给出终局（幂等命中 / 并发在途跳过），调用方应直接返回；
    - ``lease_task``：抢占成功后的后台续租任务，**取消责任在调用方的 ``finally``**。

    三者皆空表示闸门放行（含「缓存因策略收紧被绕过」这一路：此时仍带 ``cache_key``，
    以便 ④ 把收紧前产生的陈旧 COMPLETED 记录改写为可重试的 FAILED）。
    """

    cache_key: str | None = None
    lease_task: asyncio.Task[None] | None = None
    result: ToolResult | None = None


async def _claim_ledger(loop: AgentLoop, call: ToolCall, run_context: RunContext | None) -> _LedgerClaim:
    """① 幂等闸门：抢占缓存键，并按记录状态处理两条短路。

    抢不到（``acquired=False``）时按记录分两路：
    - 已 COMPLETED（带 result）→ 幂等命中，返回缓存；但**先复核 policy**（Commit A）——
      若当前 policy 已收紧到 BLOCKED，不返回收紧前产生的陈旧成功结果，落到正常链路，
      由 executor 的 ``_policy_error`` 产出准确归因；
    - RUNNING 且租约未过期（并发重入）→ 跳过重复执行，返回 skip 提示。

    抢到即起后台续租任务（①.5）并把任务交给调用方：工具可能跑数分钟，远超租约长度。
    """
    if run_context is None:
        return _LedgerClaim()
    cache_key = f"{run_context.run_id}:{call.id}"
    claim = await loop.engine.ledger.acquire(cache_key, lease_seconds=_LEDGER_LEASE_SECONDS, run_id=run_context.run_id)
    if claim.acquired:
        # ①.5 占用成功 → 在途期间后台续租。失败/取消都不影响工具执行，故不 await 结果、
        #     不 attach 回调；取消由调用方 finally 负责（见 _LedgerClaim）。
        return _LedgerClaim(
            cache_key=cache_key,
            lease_task=asyncio.create_task(_renew_ledger_lease(loop.engine.ledger, cache_key)),
        )
    cached = claim.record.metadata.get("result")
    if cached is None:
        logger.debug("Ledger lease-active skip for tool_call %s (%s)", call.id, claim.reason)
        loop._emit(
            "tool_call_skipped_inflight",
            run_context=run_context,
            tool_name=call.name,
            details={"reason": claim.reason},
        )
        return _LedgerClaim(
            cache_key=cache_key,
            result=ToolResult(
                tool_call_id=call.id,
                content=f"tool '{call.name}' already in-flight (ledger: {claim.reason}); skipped",
                is_error=True,
            ),
        )
    # A: 缓存命中也复核 policy。此分支**不能**沿用上面的「在途跳过」返回——ledger 里此刻是
    #    已 COMPLETED 的旧记录，谎称 in-flight 会给出自相矛盾的文案
    #    （"already in-flight (ledger: already completed)"）并掩盖真因。
    schema = loop.registry.get_schema(call.name)
    cached_verdict = loop.engine.policy.evaluate_tool_call(call, context=run_context, schema=schema)
    if cached_verdict.mode is not ToolExecutionMode.BLOCKED:
        logger.debug("Ledger cache hit for tool_call %s", call.id)
        loop._emit("tool_call_cached", run_context=run_context, tool_name=call.name, details={})
        return _LedgerClaim(cache_key=cache_key, result=ToolResult(tool_call_id=call.id, content=cached))
    logger.debug("Ledger cache bypassed: tool_call %s is blocked by policy now", call.id)
    return _LedgerClaim(cache_key=cache_key)


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

    ① 与 ④ 都是**旁路记账**：① 失败仍转 error ToolResult（P1-2）；④ 失败只记 warning，
    不影响已拿到的工具结果。① 成功后在途期间后台续租（见模块 docstring 第 1 条），
    避免长时调用被别的进程 prune 掉自己的记录。

    ① 的闸门整体在 :func:`_claim_ledger`，其产物 :class:`_LedgerClaim` 把「在途续租任务」
    交回本函数的 ``finally`` 取消——跨函数的所有权必须显式传递，否则每个调用都会漏掉心跳回收。
    """
    gate = _LedgerClaim()
    try:
        gate = await _claim_ledger(loop, call, run_context)
        if gate.result is not None:
            return gate.result

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
        #    记账失败不得改写工具结果——见 _record_ledger_outcome 的 docstring。
        if gate.cache_key is not None:
            await _record_ledger_outcome(loop, gate.cache_key, result)
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
    finally:
        # 收尾取消续租任务：**必须在回写之后**（回写期间记录仍需保持有效租约），
        # 且无论正常返回、异常返回还是被取消都要执行，否则会留下一个常驻心跳任务。
        if gate.lease_task is not None:
            gate.lease_task.cancel()
            with suppress(asyncio.CancelledError):
                await gate.lease_task


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
