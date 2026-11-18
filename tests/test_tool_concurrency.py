"""并发工具调用极限测试 —— 12+ 并发批次的并发性、隔离性、资源竞争与无死锁。

覆盖面（``agent/tool_execution.execute_tools`` 批次语义）：

  1. 并发性证明：12 个 handler 经 ``asyncio.Barrier`` 相互等待——若批次实际串行，
     barrier 永不满、超时显性失败（不静默不挂死）；
  2. 结果顺序契约：完成顺序被打乱（倒序延迟），返回仍按调用顺序；
  3. 隔离性：批内个别调用失败（handler 异常 / 闸门异常）不取消同批其余调用；
  4. 资源竞争：同 key 重复调用经 ledger 互斥只执行一次 handler；12 个不同 key
     并发抢占共享 ledger 存储后全部落账 COMPLETED；
  5. 取消路径：批次被外部取消时在途展示态被清理（finally 语义），无任务泄漏。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from heagent.agent.run_lifecycle import AgentState
from heagent.agent.tool_execution import execute_tools
from heagent.engine import PolicyVerdict, ToolExecutionMode
from heagent.engine.executor import ToolExecutor
from heagent.engine.ledger import ExecutionLedger
from heagent.pub.types import ToolCall
from heagent.tools.safety import SafetyGuard

_BATCH = 12
# barrier 等待超时：并发成立时毫秒级到达；串行退化时首个调用超时显性红（不挂死）
_BARRIER_TIMEOUT = 2.0
_CANCEL_DELAY = 0.1


class _EmitRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))

    def names(self) -> list[str]:
        return [e for e, _ in self.events]

    def completed(self) -> list[dict[str, Any]]:
        return [kw.get("details") for e, kw in self.events if e == "tool_batch_completed"]


def _barrier_behavior(barrier: asyncio.Barrier, i: int) -> Callable[[], Any]:
    """第 i 号行为：全员 barrier 会师 → 倒序延迟（打乱完成顺序）→ 返回 done-i。"""

    async def go() -> str:
        await asyncio.wait_for(barrier.wait(), timeout=_BARRIER_TIMEOUT)
        await asyncio.sleep((_BATCH - 1 - i) * 0.01)
        return f"done-{i}"

    return go


def _make_loop(tmp_path: Any, behaviors: dict[str, Callable[[], Any]]) -> Any:
    """构造 ``execute_tools`` 所需的最小假 loop：策略全放行、真 executor、真 ledger。

    handler 解析走真 ``invoke_handler``（经 loop.registry），行为按工具名注入。
    """
    emit = _EmitRecorder()

    async def _invoke_handler(call: ToolCall) -> object:
        action = behaviors[call.name]
        result = action()
        return await result if asyncio.iscoroutine(result) else result

    return SimpleNamespace(
        _emit=emit,
        tool_activity=[],
        active_tool="",
        engine=SimpleNamespace(
            ledger=ExecutionLedger(str(tmp_path / "ledger")),
            policy=SimpleNamespace(
                evaluate_tool_call=lambda call, context=None, schema=None: PolicyVerdict(mode=ToolExecutionMode.DIRECT)
            ),
            executor=ToolExecutor(),
            approval_handler=None,
            hooks=None,
        ),
        registry=SimpleNamespace(
            get_schema=lambda name: None,
            get_handler=lambda name: behaviors.get(name),
        ),
        guard=SafetyGuard(),
        _invoke_handler=_invoke_handler,
    )


def _calls(n: int, name: str = "fast", prefix: str = "c") -> list[ToolCall]:
    return [ToolCall(id=f"{prefix}{i}", name=name, arguments={}) for i in range(n)]


def _named_calls(n: int) -> list[ToolCall]:
    return [ToolCall(id=f"c{i}", name=f"t{i}", arguments={}) for i in range(n)]


class TestBatchConcurrency:
    """12 并发批次的并发性证明、结果顺序契约与在途展示态。"""

    async def test_batch_of_12_runs_concurrently_in_call_order(self, tmp_path: Any) -> None:
        """12 个 handler 经 barrier 相互等待同时到达；完成顺序与返回顺序解耦。"""
        barrier = asyncio.Barrier(_BATCH)
        behaviors = {f"t{i}": _barrier_behavior(barrier, i) for i in range(_BATCH)}
        loop = _make_loop(tmp_path, behaviors)
        state = AgentState()
        calls = _named_calls(_BATCH)

        results = await asyncio.wait_for(execute_tools(loop, calls, state), timeout=10)

        assert [r.tool_call_id for r in results] == [c.id for c in calls]
        assert [r.content for r in results] == [f"done-{i}" for i in range(_BATCH)]
        assert not any(r.is_error for r in results)
        assert len(state.results) == _BATCH
        # barrier 全员到齐才放行 = 12 个调用确实同时在飞
        assert loop._emit.names().count("tool_batch_started") == 1
        assert loop._emit.completed() == [{"count": _BATCH, "errors": 0}]

    async def test_inflight_label_and_activity_ledger_at_scale(self, tmp_path: Any) -> None:
        """在途展示态：批次飞行中 active_tool 聚合标签，结束后清空；台账留全部 12 条。"""
        release = asyncio.Event()

        async def hold_until_released() -> str:
            await asyncio.wait_for(release.wait(), timeout=5)
            return "ok"

        loop = _make_loop(tmp_path, {"fast": hold_until_released})
        state = AgentState()
        calls = _calls(_BATCH)

        task = asyncio.create_task(execute_tools(loop, calls, state))
        await asyncio.sleep(0.05)  # 让 12 个 handler 全部停在 release 等待（批次在途）
        assert loop.active_tool.startswith("fast")
        assert loop.active_tool.endswith("(+11)")
        assert len(loop.tool_activity) == _BATCH
        release.set()
        await asyncio.wait_for(task, timeout=10)
        assert loop.active_tool == ""


class TestBatchIsolation:
    """批内个别调用失败不取消同批其余调用。"""

    async def test_handler_failures_do_not_cancel_batch(self, tmp_path: Any) -> None:
        """12 调用中 2 个 handler 抛异常：全部返回 ToolResult，错误精确落在抛异常的调用上。"""
        fail_indexes = {3, 7}

        def boom() -> str:
            raise RuntimeError("handler boom")

        behaviors: dict[str, Callable[[], Any]] = {}
        for i in range(_BATCH):
            behaviors[f"t{i}"] = boom if i in fail_indexes else (lambda: "ok")

        loop = _make_loop(tmp_path, behaviors)
        calls = _named_calls(_BATCH)
        state = AgentState()

        results = await asyncio.wait_for(execute_tools(loop, calls, state), timeout=10)

        assert len(results) == _BATCH
        for i, r in enumerate(results):
            assert r.tool_call_id == f"c{i}"
            assert r.is_error is (i in fail_indexes)
            if i not in fail_indexes:
                assert r.content == "ok"
        assert loop._emit.completed() == [{"count": _BATCH, "errors": len(fail_indexes)}]

    async def test_gate_failures_do_not_cancel_batch(self, tmp_path: Any) -> None:
        """闸门层（policy 裁决）抛异常同样转 error 结果，不取消同批。"""
        gate_fail_names = {"t2", "t9"}

        def policy_evaluate(call: ToolCall, context: object = None, schema: object = None) -> PolicyVerdict:
            if call.name in gate_fail_names:
                raise RuntimeError("policy boom")
            return PolicyVerdict(mode=ToolExecutionMode.DIRECT)

        loop = _make_loop(tmp_path, {f"t{i}": (lambda: "ok") for i in range(_BATCH)})
        loop.engine.policy = SimpleNamespace(evaluate_tool_call=policy_evaluate)
        calls = _named_calls(_BATCH)
        state = AgentState()

        results = await asyncio.wait_for(execute_tools(loop, calls, state), timeout=10)

        assert len(results) == _BATCH
        assert all(r.is_error == (calls[i].name in gate_fail_names) for i, r in enumerate(results))
        assert all(r.tool_call_id == f"c{i}" for i, r in enumerate(results))


class TestResourceContention:
    """共享资源的并发竞争：ledger 互斥与同 key 去重。"""

    async def test_duplicate_call_id_executes_once(self, tmp_path: Any) -> None:
        """同批重复 tool_call.id 经 ledger 互斥只执行一次 handler（防重入）。"""
        run_counts = {"dup": 0}

        async def slow_dup() -> str:
            run_counts["dup"] += 1
            await asyncio.sleep(0.05)  # 给重复调用留出撞上 RUNNING 租约的窗口
            return "dup-ok"

        loop = _make_loop(tmp_path, {"dup": slow_dup, "fast": (lambda: "ok")})
        run_context = SimpleNamespace(run_id="run-dedupe")
        calls = [
            ToolCall(id="dup", name="dup", arguments={}),
            *[ToolCall(id=f"c{i}", name="fast", arguments={}) for i in range(10)],
            ToolCall(id="dup", name="dup", arguments={}),
        ]
        state = AgentState()

        results = await asyncio.wait_for(execute_tools(loop, calls, state, run_context=run_context), timeout=10)

        assert len(results) == _BATCH
        assert run_counts["dup"] == 1  # handler 恰执行一次，重复调用绝不二次执行
        dup_results = [r for r in results if r.tool_call_id == "dup"]
        assert len(dup_results) == 2
        ok_results = [r for r in dup_results if not r.is_error]
        assert ok_results and all(r.content == "dup-ok" for r in ok_results)
        # 重复调用要么命中缓存（成功），要么被 RUNNING 租约拦下（in-flight 错误）
        for r in dup_results:
            assert (not r.is_error) or ("already in-flight" in r.content)

    async def test_concurrent_distinct_keys_all_recorded(self, tmp_path: Any) -> None:
        """12 个不同 key 并发抢占共享 ledger 存储：全部执行、全部落账 COMPLETED。"""
        loop = _make_loop(tmp_path, {"fast": (lambda: "ok")})
        run_context = SimpleNamespace(run_id="run-fanout")
        calls = _calls(_BATCH)
        state = AgentState()

        results = await asyncio.wait_for(execute_tools(loop, calls, state, run_context=run_context), timeout=10)

        assert all(not r.is_error for r in results)
        ledger = loop.engine.ledger
        for call in calls:
            record = await ledger.get(f"run-fanout:{call.id}")
            assert record is not None
            assert record.status.value == "completed"
            assert record.metadata.get("result") == "ok"


class TestCancellation:
    """批次取消路径：在途展示态清理与无任务泄漏。"""

    async def test_cancel_clears_inflight_state(self, tmp_path: Any) -> None:
        """批次被外部取消：active_tool 经 finally 清空，批次完成事件不再发出。"""
        never = asyncio.Barrier(_BATCH + 1)  # 12 个 handler 永远凑不满 → 全部卡在等待

        async def stuck() -> str:
            await asyncio.wait_for(never.wait(), timeout=30)
            return "unreachable"

        loop = _make_loop(tmp_path, {"fast": stuck})
        state = AgentState()
        calls = _calls(_BATCH)

        task = asyncio.create_task(execute_tools(loop, calls, state))
        await asyncio.sleep(_CANCEL_DELAY)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert loop.active_tool == ""
        assert "tool_batch_started" in loop._emit.names()
        assert "tool_batch_completed" not in loop._emit.names()
