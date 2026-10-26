"""S-1：``transition_reason`` 字段与「状态 ↔ checkpoint ↔ 磁盘」双向往返。

本文件只锁 S-1 的契约：
- 新字段与 ``last_event`` 正交（一个答「经哪个事件」，一个答「为什么发它」）；
- 长度只由 :func:`_bounded_reason` 收敛，写入路径永不抛；
- 旧 checkpoint（缺该键）照常加载；新 checkpoint 对旧代码是 ``extra="ignore"`` 兼容。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from heagent.engine.checkpoint import (
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)
from heagent.engine.workflow_events import WorkflowEvent
from heagent.engine.workflow_resource import StepApproval, WorkflowResource, WorkflowStepResource
from heagent.engine.workflow_runner import (
    WorkflowRunner,
    WorkflowStepResult,
    _MAX_REASON_CHARS,
    _bounded_reason,
)


def _workflow() -> WorkflowResource:
    return WorkflowResource(
        name="demo",
        instructions="",
        steps=[WorkflowStepResource(index=1, name="step-01.md", instructions="")],
    )


def _checkpoint(**overrides: object) -> WorkflowCheckpoint:
    payload: dict[str, object] = {
        "checkpoint_id": "cp-1",
        "goal_id": "goal-1",
        "phase": WorkflowPhase.IMPLEMENTATION,
        "status": WorkflowStatus.PENDING,
        "run_id": "run-1",
    }
    payload.update(overrides)
    return WorkflowCheckpoint(**payload)


def _runner(store: WorkflowCheckpointStore | None = None) -> WorkflowRunner:
    return WorkflowRunner(_workflow(), goal_id="goal-1", run_id="run-1", checkpoint_store=store)


async def _latest(store: WorkflowCheckpointStore) -> WorkflowCheckpoint | None:
    """取该 goal 最后一个 checkpoint（含已完成状态；``load_latest_unfinished`` 会跳过 COMPLETED）。"""
    checkpoints = await store.list_checkpoints(goal_id="goal-1")
    return checkpoints[-1] if checkpoints else None


# --------------------------------------------------------------------------- 字段与默认值


def test_state_and_checkpoint_default_to_empty_reason() -> None:
    runner = _runner()
    assert runner.state.transition_reason == ""
    assert _checkpoint().transition_reason == ""
    assert _checkpoint().last_event == ""


def test_checkpoint_tolerates_read_of_newer_file() -> None:
    """前向兼容（R-1）：模型未声明 ``model_config`` ⇒ pydantic 默认 extra="ignore"，旧代码读新文件不炸。"""
    assert WorkflowCheckpoint.model_config.get("extra", "ignore") != "forbid"
    cp = _checkpoint(transition_reason="why", unknown_future_field="ignored")
    assert cp.transition_reason == "why"


# --------------------------------------------------------------------------- 写点与正交


@pytest.mark.asyncio
async def test_failed_step_records_reason_and_event(tmp_path) -> None:
    """失败路径：状态面三键同源落盘，理由含原始异常摘要。"""
    store = WorkflowCheckpointStore(str(tmp_path))
    runner = _runner(store)

    async def callback(_step):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await runner.run_step(callback)

    assert runner.state.status is WorkflowStatus.FAILED
    assert runner.state.last_event == WorkflowEvent.EXECUTOR_FAILED.value
    assert "boom" in runner.state.transition_reason

    persisted = await _latest(store)
    assert persisted is not None
    assert persisted.last_event == WorkflowEvent.EXECUTOR_FAILED.value
    assert "boom" in persisted.transition_reason
    assert persisted.next_action == runner.state.reason


@pytest.mark.asyncio
async def test_successful_step_records_reason_from_result(tmp_path) -> None:
    """正常完成路径也带理由（``WorkflowStepResult.reason`` 透传到 ``transition_reason``）。"""
    store = WorkflowCheckpointStore(str(tmp_path))
    runner = _runner(store)

    async def callback(_step):
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output="ok", reason="all checks passed")

    await runner.run_step(callback)

    assert runner.state.transition_reason == "all checks passed"
    assert runner.state.last_event == WorkflowEvent.FINAL_STEP_COMPLETED.value
    persisted = await _latest(store)
    assert persisted is not None
    assert persisted.transition_reason == "all checks passed"


def test_transition_fields_are_orthogonal_and_reset() -> None:
    """正交性：同一事件换理由不影响 ``last_event``；未声明理由的转换把 ``transition_reason`` 置空。"""
    runner = _runner()

    with_reason = runner._transition_fields(WorkflowEvent.START, reason="started by user")
    without_reason = runner._transition_fields(WorkflowEvent.START)
    assert with_reason["last_event"] == without_reason["last_event"] == WorkflowEvent.START.value
    assert with_reason["transition_reason"] == "started by user"
    assert without_reason["transition_reason"] == ""

    runner.state = runner.state.model_copy(update=with_reason)
    assert runner.state.transition_reason == "started by user"

    runner.state = runner.state.model_copy(update=runner._transition_fields(WorkflowEvent.STEP_COMPLETED))
    assert runner.state.transition_reason == ""
    assert runner.state.last_event == WorkflowEvent.STEP_COMPLETED.value


# --------------------------------------------------------------------------- 有界与回读


def test_bounded_reason_caps_without_raising() -> None:
    long_text = "x" * (_MAX_REASON_CHARS + 3000)
    bounded = _bounded_reason(long_text)
    assert len(bounded) == _MAX_REASON_CHARS
    assert bounded.endswith("...")


@pytest.mark.asyncio
async def test_oversized_reason_is_truncated_on_write() -> None:
    runner = _runner()

    async def callback(_step):
        raise RuntimeError("y" * (_MAX_REASON_CHARS + 500))

    with pytest.raises(RuntimeError):
        await runner.run_step(callback)
    assert len(runner.state.transition_reason) <= _MAX_REASON_CHARS
    assert runner.state.transition_reason.endswith("...")


def test_legacy_checkpoint_without_field_loads_as_empty() -> None:
    """后向兼容：磁盘上缺 ``transition_reason`` 的旧文件照常加载，读作空串。"""
    legacy = {
        "checkpoint_id": "cp-legacy",
        "goal_id": "goal-1",
        "phase": "implementation",
        "status": "pending",
        "run_id": "run-1",
        "last_event": "start",
        "next_action": "legacy reason",
        "outputs": {},
        "completed_steps": [],
    }
    loaded = WorkflowCheckpoint.model_validate_json(json.dumps(legacy))
    assert loaded.transition_reason == ""
    assert loaded.last_event == "start"
    assert loaded.next_action == "legacy reason"


@pytest.mark.asyncio
async def test_roundtrip_via_store_keeps_reason(tmp_path) -> None:
    """两次往返：写 → 落盘 → 回读（from_checkpoint）→ 再落盘，理由不丢。"""
    store = WorkflowCheckpointStore(str(tmp_path))
    runner = _runner(store)

    async def callback(_step):
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output="ok", reason="roundtrip")

    await runner.run_step(callback)
    first = await _latest(store)
    assert first is not None and first.transition_reason == "roundtrip"

    restored = WorkflowRunner.from_checkpoint(_workflow(), first, checkpoint_store=store)
    assert restored.state.transition_reason == "roundtrip"
    assert restored.state.last_event == first.last_event

    # 再存一次：回读点若漏字段，第二次落盘会把它写成空串。
    await store.save(first.model_copy(update={"transition_reason": restored.state.transition_reason}))
    second = await _latest(store)
    assert second is not None and second.transition_reason == "roundtrip"


# --------------------------------------------------------------------------- S-2：不变量守卫


def test_illegal_last_event_fails_loud_and_names_the_value() -> None:
    """I-3 封闭词汇表：非法 ``last_event`` 必须 fail-loud，且错误信息点名该值。"""
    with pytest.raises(ValueError, match="bogus_event"):
        _checkpoint(last_event="bogus_event")
    # 空串（旧档案未记录）仍然合法。
    assert _checkpoint(last_event="").last_event == ""


@pytest.mark.asyncio
async def test_store_rejects_corrupted_vocabulary_file(tmp_path) -> None:
    """落盘路径同样 fail-loud：非法事件的文件不会被静默当作「无 checkpoint」。"""
    from heagent.engine.checkpoint import WorkflowCheckpointError

    store = WorkflowCheckpointStore(str(tmp_path))
    raw = tmp_path / "cp-bad.json"
    raw.write_text(
        json.dumps(
            {
                "checkpoint_id": "cp-bad",
                "goal_id": "goal-1",
                "phase": "implementation",
                "status": "pending",
                "run_id": "run-1",
                "last_event": "not_an_event",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(WorkflowCheckpointError, match="corrupted"):
        await store.load("cp-bad")


def test_transition_failure_preserves_cause_chain() -> None:
    """I-5：非法迁移抛 ``WorkflowTransitionError`` 且 ``__cause__`` 非空（``raise … from exc``）。"""
    from heagent.engine.workflow_transition import WorkflowTransitionError, transition

    with pytest.raises(WorkflowTransitionError) as excinfo:
        transition(WorkflowStatus.COMPLETED, WorkflowEvent.START)
    assert excinfo.value.__cause__ is not None
    assert isinstance(excinfo.value.__cause__, KeyError)


def test_error_kind_comes_from_closed_mapping() -> None:
    """I-6：失败分类只能来自 ``error_kind_for`` 的封闭映射（未知异常归 `exception`）。"""
    from heagent.events.protocol import ERROR_KIND_EXCEPTION, error_kind_for

    # 未登记类型回落兜底分类；已登记类型走自己的分类（证明映射真的在生效，而非恒返兜底）。
    assert error_kind_for(TypeError("boom")) == ERROR_KIND_EXCEPTION
    assert error_kind_for(TimeoutError("slow")) == "timeout"
    # ``explicit`` 覆盖语义分类（如 unknown_tool），不得绕过词表检查之外的分支。
    assert error_kind_for(RuntimeError("x"), explicit="unknown_tool") == "unknown_tool"


# --------------------------------------------------------------------------- S-3：中断语义矩阵


_MATRIX_START = "<!-- S-3:transition-matrix:start -->"
_MATRIX_END = "<!-- S-3:transition-matrix:end -->"


def _matrix_block() -> str:
    frame = (Path(__file__).resolve().parents[1] / "docs" / "frame.md").read_text(encoding="utf-8")
    assert _MATRIX_START in frame and _MATRIX_END in frame, "docs/frame.md 缺少 S-3 矩阵标记"
    return frame.split(_MATRIX_START, 1)[1].split(_MATRIX_END, 1)[0]


def _table_rows(block: str, header_first_cell: str) -> list[list[str]]:
    """取出以 ``header_first_cell`` 开头的表格的数据行（跳过分隔行）。"""
    lines = block.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("|") and header_first_cell in line:
            rows: list[list[str]] = []
            for candidate in lines[index + 2 :]:
                if not candidate.startswith("|"):
                    break
                rows.append([cell.strip() for cell in candidate.strip().strip("|").split("|")])
            return rows
    raise AssertionError(f"矩阵缺少表头（首列含 {header_first_cell}）")


def test_interrupt_matrix_covers_vocabulary() -> None:
    """S-3：矩阵的事件列必须与 ``WorkflowEvent`` 完全一致，且每行带可解析的代码锚点。

    能力边界（写进代码不写进心里）：本判据只证明**矩阵不滞后于词表**，不证明语义正确——
    「某个事件的落状态是否合理」由 A39 的裁定与评审负责，判据抓不到。反过来说：新增事件却
    不更新矩阵、或手改矩阵漏掉一个事件，都会在这里变红。
    """
    block = _matrix_block()
    rows = _table_rows(block, "状态")
    assert len(rows) >= len(WorkflowEvent), f"矩阵行数少于事件数：{len(rows)}"

    for row in rows:
        assert len(row) == 5, f"矩阵应为 5 列（状态/事件/原因/下一步/代码锚点），实际 {len(row)}：{row}"
        assert all(cell for cell in row), f"矩阵存在空单元格：{row}"

    listed = {match for row in rows for match in re.findall(r"`([a-z_]+)`", row[1])}
    expected = {event.value for event in WorkflowEvent}
    assert listed == expected, f"矩阵事件列与词表不一致：多出 {listed - expected}，缺少 {expected - listed}"

    for row in rows:
        anchors = re.findall(r"`(src/[\w/.\-]+\.py):(\d+)`", row[4])
        assert anchors, f"该行没有可解析的代码锚点：{row[0]} / {row[1]}"
        for relative, line_text in anchors:
            path = Path(__file__).resolve().parents[1] / relative
            assert path.is_file(), f"锚点文件不存在：{relative}"
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            assert int(line_text) <= line_count, f"锚点越界：{relative}:{line_text}（文件仅 {line_count} 行）"

    assert "TBD" not in block and "待定" not in block, "矩阵不得留 TBD/待定"


def test_interrupt_matrix_matches_absorb_semantics() -> None:
    """S-3：中断语义表必须与 ``_absorb_step_exception`` 的**现行**二分口径一致（A39）。"""
    import asyncio as _asyncio

    from heagent.engine.workflow_runner import WorkflowRunner, _CANCEL_EXCEPTIONS

    assert _asyncio.CancelledError in _CANCEL_EXCEPTIONS
    assert KeyboardInterrupt in _CANCEL_EXCEPTIONS
    assert SystemExit in _CANCEL_EXCEPTIONS

    runner = WorkflowRunner(_workflow())
    runner.state = runner.state.model_copy(update=runner._transition_fields(WorkflowEvent.START))
    assert runner._absorb_step_exception(KeyboardInterrupt()) is WorkflowEvent.CANCELLED
    assert runner.state.status is WorkflowStatus.PENDING

    runner = WorkflowRunner(_workflow())
    runner.state = runner.state.model_copy(update=runner._transition_fields(WorkflowEvent.START))
    assert runner._absorb_step_exception(RuntimeError("boom")) is WorkflowEvent.EXECUTOR_FAILED
    assert runner.state.status is WorkflowStatus.FAILED


@pytest.mark.asyncio
async def test_decision_paths_carry_their_reason() -> None:
    """Epic E1 评审 F1：人工决策路径也必须带理由（原先只有「结果/异常」两条路径透传）。

    ``pause`` / ``reject`` / ``amend`` / 审批门这几处正是「为什么要停、为什么被否」最需要审计的
    地方；若它们的 ``transition_reason`` 恒为空，S-1 的价值在这些路径上就等于零。
    """
    runner = _runner()
    paused = runner.pause()
    assert paused.last_event == WorkflowEvent.USER_PAUSE.value
    assert "pause" in paused.transition_reason

    gate_workflow = WorkflowResource(
        name="demo",
        instructions="",
        steps=[WorkflowStepResource(index=1, name="step-01.md", instructions="", approval=StepApproval(required=True))],
    )
    gate_runner = WorkflowRunner(gate_workflow, goal_id="goal-1", run_id="run-1")

    async def work(_step):
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output="done")

    await gate_runner.run_step(work)
    assert gate_runner.state.awaiting_approval
    assert gate_runner.state.transition_reason, "审批门挂起必须带理由（F1）"

    rejected = gate_runner.reject("scope mismatch")
    assert rejected.last_event == WorkflowEvent.USER_REJECT.value
    assert "scope mismatch" in rejected.transition_reason
