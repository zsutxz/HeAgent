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

from heagent.engine import ExecutionStatus, RunContext
from heagent.types import ToolCall, ToolResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.agent.loop import AgentLoop, AgentState

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
    results = list(await asyncio.gather(*tasks))
    state.results.extend(results)
    loop._emit(
        "tool_batch_completed",
        run_context=run_context,
        details={"count": len(results), "errors": sum(1 for result in results if result.is_error)},
    )
    return results


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
    if run_context is not None:
        # ① 抢占缓存键：抢不到且已有 COMPLETED 记录 → 直接返回缓存结果（幂等命中）。
        cache_key = f"{run_context.run_id}:{call.id}"
        claim = loop.engine.ledger.acquire(cache_key, run_id=run_context.run_id)
        if not claim.acquired and claim.record.status == ExecutionStatus.COMPLETED:
            cached = claim.record.metadata.get("result")
            if cached is not None:
                logger.debug("Ledger cache hit for tool_call %s", call.id)
                loop._emit("tool_call_cached", run_context=run_context, tool_name=call.name, details={})
                return ToolResult(tool_call_id=call.id, content=cached)

    # ② 策略裁决；③ 查 handler。未知工具直接产出 error 结果，不走 executor。
    verdict = loop.engine.policy.evaluate_tool_call(call, context=run_context)
    handler = loop.registry.get_handler(call.name)
    if handler is None:
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

    # ④ 结果回写 ledger：成功记 complete（带结果供后续幂等），失败记 fail（允许重试）。
    if cache_key is not None:
        if result.is_error:
            loop.engine.ledger.fail(cache_key, result.content)
        else:
            loop.engine.ledger.complete(cache_key, metadata={"result": result.content})
    return result


async def invoke_handler(loop: AgentLoop, call: ToolCall) -> object:
    """解析并调用一次工具调用对应的注册 handler（executor 的执行回调）。

    未知工具直接抛 RuntimeError（executor 外层会捕获并转成 ToolResult.error）。
    """
    handler = loop.registry.get_handler(call.name)
    if handler is None:
        raise RuntimeError(f"Unknown tool: {call.name}")
    return await _invoke(handler, call)


async def _invoke(handler: object, call: ToolCall) -> object:
    """实际调用 handler：自动适配 sync / async 两种工具实现。

    参数以关键字展开 ``call.arguments`` 传入（工具用 ``**kwargs`` 接收）。
    """
    fn = cast("Callable[..., Any]", handler)
    if asyncio.iscoroutinefunction(fn):
        return await fn(**call.arguments)
    return fn(**call.arguments)
