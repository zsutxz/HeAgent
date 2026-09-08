"""Tests for sub-agent builtin tools — task_delegate / task_parallel.

工具层契约测试：只注入 fake executor（不启动 Agent 栈），验证 JSON 返回契约与
所有预检分支。真实编排路径（SubAgent 构造、角色解析、并行保序）见
``tests/test_agent_delegation.py`` / ``tests/test_subagent_role.py``。
"""

from __future__ import annotations

import json
from typing import Literal

import pytest

from heagent.engine.context import RunContext
from heagent.engine.roles import RoleSpec
from heagent.tools.builtins.subagent import (
    SubTaskOutcome,
    configure_subagent_tools,
    reset_subagent_tools,
    task_delegate,
    task_parallel,
)
from heagent.tools.registry import ToolRegistry


class _FakeExecutor:
    """Records delegation requests and returns canned outcomes (no Agent stack)."""

    def __init__(self, *, statuses: list[Literal["ok", "failed"]] | None = None) -> None:
        self.calls: list[tuple[str, object, RoleSpec | None, str | None]] = []
        self._statuses = statuses

    def _outcome(self, task: str, spec: RoleSpec | None, index: int) -> SubTaskOutcome:
        statuses = self._statuses or []
        status: Literal["ok", "failed"] = statuses[index] if index < len(statuses) else "ok"
        return SubTaskOutcome(
            status=status,
            role=spec.name if spec is not None else "",
            task=task,
            iterations=3,
            run_id=f"run-{index}",
            output=f"out:{task}",
        )

    async def delegate_one(self, task: str, spec: RoleSpec | None, system: str | None) -> SubTaskOutcome:
        self.calls.append(("one", task, spec, system))
        return self._outcome(task, spec, 0)

    async def delegate_many(self, tasks: list[str], spec: RoleSpec | None, system: str | None) -> list[SubTaskOutcome]:
        self.calls.append(("many", list(tasks), spec, system))
        return [self._outcome(task, spec, index) for index, task in enumerate(tasks)]


@pytest.fixture()
def _reset_subagent():
    """Teardown only: 测试后复位 subagent 模块状态，防止回调泄漏到后续测试。"""
    yield
    reset_subagent_tools()


def _configure(executor: _FakeExecutor, **kwargs: object) -> _FakeExecutor:
    configure_subagent_tools(executor.delegate_one, executor.delegate_many, **kwargs)  # type: ignore[arg-type]
    return executor


@pytest.mark.usefixtures("_reset_subagent")
class TestTaskDelegate:
    async def test_unconfigured_returns_error(self) -> None:
        result = await task_delegate("do something")
        assert "not configured" in result

    async def test_delegates_through_callback(self) -> None:
        executor = _configure(_FakeExecutor())
        payload = json.loads(await task_delegate("compute 2+2"))

        assert payload["status"] == "ok"
        assert payload["output"] == "out:compute 2+2"
        assert payload["iterations"] == 3
        assert payload["run_id"] == "run-0"
        assert executor.calls == [("one", "compute 2+2", None, None)]

    async def test_failed_outcome_is_passed_through(self) -> None:
        _configure(_FakeExecutor(statuses=["failed"]))
        payload = json.loads(await task_delegate("will fail"))
        assert payload["status"] == "failed"

    async def test_role_is_resolved_before_callback(self) -> None:
        executor = _configure(_FakeExecutor())
        payload = json.loads(await task_delegate("plan it", role="planner"))

        assert payload["role"] == "planner"
        spec = executor.calls[0][2]
        assert isinstance(spec, RoleSpec)
        assert spec.name == "planner"

    async def test_unknown_role_never_calls_callback(self) -> None:
        executor = _configure(_FakeExecutor())
        payload = json.loads(await task_delegate("x", role="no_such_role"))

        assert payload["status"] == "error"
        assert "Unknown role" in payload["message"]
        assert executor.calls == []

    async def test_system_override_is_forwarded(self) -> None:
        executor = _configure(_FakeExecutor())
        await task_delegate("x", system="be terse")
        await task_delegate("y")
        assert [call[3] for call in executor.calls] == ["be terse", None]


@pytest.mark.usefixtures("_reset_subagent")
class TestTaskParallel:
    async def test_unconfigured_returns_error(self) -> None:
        result = await task_parallel('["task1"]')
        assert "not configured" in result

    async def test_invalid_json(self) -> None:
        _configure(_FakeExecutor())
        result = await task_parallel("not json")
        assert "valid JSON array" in result

    async def test_empty_array(self) -> None:
        _configure(_FakeExecutor())
        result = await task_parallel("[]")
        assert "non-empty" in result

    async def test_not_array(self) -> None:
        _configure(_FakeExecutor())
        result = await task_parallel('"hello"')
        assert "non-empty" in result

    async def test_not_all_strings(self) -> None:
        """元素含非字符串时应拒绝，避免把 int 等传入委派回调。"""
        executor = _configure(_FakeExecutor())
        result = await task_parallel(json.dumps(["ok", 123]))
        assert "array of strings" in result
        assert executor.calls == []

    async def test_parallel_execution_keeps_order(self) -> None:
        executor = _configure(_FakeExecutor())
        payload = json.loads(await task_parallel(json.dumps(["task 1", "task 2"])))

        assert payload["status"] == "ok"
        outcomes = payload["outcomes"]
        assert [o["task"] for o in outcomes] == ["task 1", "task 2"]
        assert [o["run_id"] for o in outcomes] == ["run-0", "run-1"]
        assert executor.calls == [("many", ["task 1", "task 2"], None, None)]

    async def test_parallel_partial_when_one_fails(self) -> None:
        _configure(_FakeExecutor(statuses=["ok", "failed"]))
        payload = json.loads(await task_parallel(json.dumps(["a", "b"])))
        assert payload["status"] == "partial"
        assert {o["status"] for o in payload["outcomes"]} == {"ok", "failed"}

    async def test_mismatched_outcome_count_is_error(self) -> None:
        """回调契约要求与 tasks 等长保序，长度不符时显性失败而非错位记账。"""

        async def delegate_many(tasks, spec, system):  # noqa: ANN001, ANN202, ARG001
            return []

        configure_subagent_tools(delegate_many=delegate_many)
        payload = json.loads(await task_parallel(json.dumps(["a", "b"])))
        assert payload["status"] == "error"
        assert "mismatched" in payload["message"]

    async def test_unknown_role_never_calls_callback(self) -> None:
        executor = _configure(_FakeExecutor())
        payload = json.loads(await task_parallel(json.dumps(["a"]), role="no_such_role"))
        assert payload["status"] == "error"
        assert executor.calls == []


@pytest.mark.usefixtures("_reset_subagent")
@pytest.mark.usefixtures("_reset_subagent")
class TestDepthLimit:
    """委派深度闸门：depth >= max_depth 时拒绝，避免 LLM 自我委派无限递归。"""

    async def test_delegate_rejected_at_limit(self) -> None:
        executor = _configure(_FakeExecutor(), depth=3, max_depth=3)
        payload = json.loads(await task_delegate("x"))

        assert payload["status"] == "error"
        assert "depth limit" in payload["message"]
        assert executor.calls == []

    async def test_parallel_rejected_at_limit(self) -> None:
        executor = _configure(_FakeExecutor(), depth=3, max_depth=3)
        payload = json.loads(await task_parallel(json.dumps(["a", "b"])))

        assert payload["status"] == "error"
        assert "depth limit" in payload["message"]
        assert executor.calls == []

    async def test_delegates_below_limit(self) -> None:
        executor = _configure(_FakeExecutor(), depth=2, max_depth=3)
        payload = json.loads(await task_delegate("x"))

        assert payload["status"] == "ok"
        assert len(executor.calls) == 1

    async def test_zero_budget_blocks_root_delegation(self) -> None:
        """max_depth=0：连根 loop 的委派也拒绝（全局关闭委派）。"""
        executor = _configure(_FakeExecutor(), depth=0, max_depth=0)
        payload = json.loads(await task_delegate("x"))

        assert payload["status"] == "error"
        assert executor.calls == []

    async def test_depth_check_precedes_role_resolution(self) -> None:
        """深度超限优先于角色解析：未知角色 + 超限时报告深度错误。"""
        executor = _configure(_FakeExecutor(), depth=3, max_depth=3)
        payload = json.loads(await task_delegate("x", role="no_such_role"))

        assert "depth limit" in payload["message"]
        assert executor.calls == []


class TestCompletedSteps:
    """委派结果写入 run_context.metadata['completed_steps']（跨上下文重置存活）。"""

    async def test_records_single_and_parallel_steps(self) -> None:
        run_context = RunContext()
        _configure(_FakeExecutor(), run_context=run_context)

        await task_delegate("one", role="coder")
        await task_parallel(json.dumps(["a", "b"]), role="coder")

        steps = run_context.metadata["completed_steps"]
        assert [step["task"] for step in steps] == ["one", "a", "b"]
        assert all(step["role"] == "coder" and step["success"] is True for step in steps)
        assert steps[0]["iterations"] == 3
        assert steps[0]["run_id"] == "run-0"


class TestToolRegistration:
    def test_task_delegate_registered(self) -> None:
        """task_delegate 已注册且 schema 形态绑定本工具（task/role/system 参数）。"""

        registry = ToolRegistry.get()
        schema = registry.get_schema("task_delegate")
        assert schema is not None
        assert schema.name == "task_delegate"
        props = schema.parameters["properties"]
        assert "task" in props
        assert {"role", "system"} <= set(props)

    def test_task_parallel_registered(self) -> None:
        """task_parallel 已注册且 schema 形态绑定本工具（tasks_json 参数）。"""
        registry = ToolRegistry.get()
        schema = registry.get_schema("task_parallel")
        assert schema is not None
        assert schema.name == "task_parallel"
        props = schema.parameters["properties"]
        assert "tasks_json" in props
