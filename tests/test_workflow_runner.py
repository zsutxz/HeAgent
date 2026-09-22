from __future__ import annotations

import pytest

from heagent.engine.checkpoint import WorkflowCheckpoint, WorkflowCheckpointStore, WorkflowPhase, WorkflowStatus
from heagent.engine.workflow_runner import (
    WorkflowGateError,
    WorkflowRunResult,
    WorkflowRunner,
    WorkflowStepResult,
    parse_story_list,
    required_sections,
)
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource


def _workflow(*steps: WorkflowStepResource) -> WorkflowResource:
    return WorkflowResource(name="demo", instructions="", steps=list(steps))


@pytest.mark.asyncio
async def test_runner_executes_one_declared_step_in_order() -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01-first.md", instructions="first"),
        WorkflowStepResource(index=2, name="step-02-second.md", instructions="second"),
    )
    runner = WorkflowRunner(workflow)
    seen: list[str] = []

    async def callback(step):
        seen.append(step.name)
        return WorkflowStepResult(output=step.name)

    first = await runner.run_step(callback)
    assert first.status is WorkflowStatus.PENDING
    assert first.step_index == 1
    assert seen == ["step-01-first.md"]
    second = await runner.run_step(callback)
    assert second.status is WorkflowStatus.COMPLETED
    assert runner.done
    assert seen == ["step-01-first.md", "step-02-second.md"]


@pytest.mark.asyncio
async def test_missing_input_and_invalid_output_block_without_advancing() -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", input="brief", output="plan"),
    )
    runner = WorkflowRunner(workflow)
    result = await runner.run_step(lambda _: WorkflowStepResult(output=None))
    assert result.status is WorkflowStatus.BLOCKED
    assert result.missing == ["brief"]
    assert runner.state.active_step == 0
    runner.resume()
    result = await runner.run_step(lambda _: WorkflowStepResult(output={"other": "x"}), inputs={"brief": "x"})
    assert result.status is WorkflowStatus.BLOCKED
    assert "missing" in result.reason


@pytest.mark.asyncio
async def test_checkpoint_waits_then_resume_advances_and_persists_state(tmp_path) -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", checkpoint="user"),
        WorkflowStepResource(index=2, name="step-02.md", instructions=""),
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)
    result = await runner.run_step(lambda _: WorkflowStepResult(output="ok"))
    assert result.status is WorkflowStatus.WAITING_USER
    assert runner.state.active_step == 1
    state = await store.load_state()
    assert state is not None
    assert state.active_step == 1
    assert state.status is WorkflowStatus.WAITING_USER
    runner.resume()
    result = await runner.run_step(lambda _: WorkflowStepResult(output="done"))
    assert result.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_final_checkpoint_completes_instead_of_waiting(tmp_path) -> None:
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions="", checkpoint="true"))
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    result = await runner.run_step(lambda _: WorkflowStepResult(output="done"))

    assert result.status is WorkflowStatus.COMPLETED
    assert runner.done
    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert checkpoints[-1].status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_failed_step_is_retryable_without_fake_completion() -> None:
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)
    result = await runner.run_step(lambda _: WorkflowStepResult(status=WorkflowStatus.FAILED, reason="provider"))
    assert isinstance(result, WorkflowRunResult)
    assert result.status is WorkflowStatus.FAILED
    assert not runner.done
    runner.resume()
    result = await runner.run_step(lambda _: WorkflowStepResult(output="ok"))
    assert result.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_checkpoint_restore_keeps_zero_based_completed_steps(tmp_path) -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions=""),
        WorkflowStepResource(index=2, name="step-02.md", instructions=""),
    )
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="goal-run-step-2",
        goal_id="goal",
        phase=WorkflowPhase.IMPLEMENTATION,
        status=WorkflowStatus.PENDING,
        run_id="run",
        active_step=1,
        completed_steps=[0],
    )
    store = WorkflowCheckpointStore(str(tmp_path))
    runner = WorkflowRunner.from_checkpoint(workflow, checkpoint, checkpoint_store=store)
    assert runner.state.completed_steps == [0]
    result = await runner.run_step(lambda _: WorkflowStepResult(output="ok"))
    assert result.status is WorkflowStatus.COMPLETED
    assert runner.state.completed_steps == [0, 1]


@pytest.mark.asyncio
async def test_runner_persists_each_declared_output_reference_across_recovery(tmp_path) -> None:
    workflow = _workflow(
        WorkflowStepResource(
            index=1,
            name="step-01.md",
            instructions="",
            output="requirements brief, story breakdown",
        ),
        WorkflowStepResource(index=2, name="step-02.md", instructions="", input="requirements brief"),
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    assert (await runner.run_step(lambda _: WorkflowStepResult(output="analysis"))).status is WorkflowStatus.PENDING
    checkpoint = (await store.list_checkpoints(goal_id="goal"))[-1]
    restored = WorkflowRunner.from_checkpoint(workflow, checkpoint, checkpoint_store=store)

    assert restored.state.outputs["requirements brief"] == "analysis"
    assert restored.state.outputs["story breakdown"] == "analysis"
    result = await restored.run_step(lambda _: WorkflowStepResult(output="done"), inputs=restored.state.outputs)
    assert result.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_resume_reegress_same_pending_checkpoint_is_idempotent(tmp_path) -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", checkpoint="user"),
        WorkflowStepResource(index=2, name="step-02.md", instructions=""),
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    assert (await runner.run_step(lambda _: WorkflowStepResult(output="ok"))).status is WorkflowStatus.WAITING_USER
    runner.resume()
    await runner.persist_state()  # first write of step-2-active-1-pending

    runner.state = runner.state.model_copy(update={"status": WorkflowStatus.WAITING_USER, "reason": "interrupted"})
    await runner.persist_state()  # step-2-active-1-waiting_user

    runner.resume()
    await runner.persist_state()  # re-issues step-2-active-1-pending; must not conflict

    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert any(c.checkpoint_id == "goal-run-step-2-active-1-pending" for c in checkpoints)


def test_section_gate_requires_standalone_headings() -> None:
    """A ``section:`` rule only accepts ``## <title>`` on its own line, nothing else."""
    step = WorkflowStepResource(
        index=1,
        name="step-01.md",
        instructions="",
        validation_rules="section: 实现摘要; section: 测试证据; section: 验证结论",
    )
    WorkflowRunner.validate_output(step, "## 实现摘要\n\n## 测试证据\n\n## 验证结论\n")
    with pytest.raises(WorkflowGateError):
        WorkflowRunner.validate_output(step, "## 实现摘要（S-1）\n\n## 测试证据\n\n## 验证结论\n")
    with pytest.raises(WorkflowGateError):
        WorkflowRunner.validate_output(step, "## 实现摘要\n\n## 测试证据\n")


def test_required_sections_ignores_case_and_keeps_authored_names() -> None:
    """``Section:`` spelling keeps working, and the message keeps the authored casing."""
    assert required_sections("Section: Implementation Summary; section: Verification Verdict") == [
        "Implementation Summary",
        "Verification Verdict",
    ]
    assert required_sections("") == []
    assert required_sections(None) == []
    assert required_sections("given when then only") == []
    step = WorkflowStepResource(
        index=1,
        name="step-01.md",
        instructions="",
        validation_rules="Section: Implementation Summary",
    )
    WorkflowRunner.validate_output(step, "## implementation summary\n")


STORY_DOC = "\n".join(
    [
        "# 02-epics.md",
        "",
        "| 编号 | 父 Epic | 优先级 | 依赖 | 单一用户可见目标 |",
        "|------|---------|--------|------|------------------|",
        "| S-1 | E1 | P0 | none | 打开网页即可完整玩一局 |",
        "| S-2 | E2 | P1 | S-1 | 最高分跨会话记住 |",
        "",
        "## E1 — 经典玩法核心",
        "### S-1 经典玩法核心（可玩一局）",
        "",
        "- **父 Epic**：E1",
        "",
        "## E2 — 本地最高分与游戏控制",
        "### S-2 本地最高分",
        "",
        "- **父 Epic**：E2",
    ]
)


def test_story_headings_win_over_the_overview_table() -> None:
    """A doc with story sections plus an overview table must not read the table."""
    stories = parse_story_list(STORY_DOC)
    assert [story.id for story in stories] == ["S-1", "S-2"]
    assert [story.epic for story in stories] == ["E1", "E2"]
    assert stories[0].summary == "经典玩法核心（可玩一局）"


def test_story_table_alone_reads_the_epic_column_and_last_cell() -> None:
    """Tables without story sections keep working, with the Epic read from its column."""
    table = "\n".join(
        [
            "| 编号 | 父 Epic | 优先级 | 依赖 | 单一用户可见目标 |",
            "|------|---------|--------|------|------------------|",
            "| S-1 | E1 | P0 | none | 打开网页即可完整玩一局 |",
            "| S-2 | E2 | P1 | S-1 | 最高分跨会话记住 |",
            "",
            "## Sprint 计划",
            "",
            "### Sprint 1 — 可玩闭环",
            "",
            "### Sprint 2 — 体验收口",
        ]
    )
    stories = parse_story_list(table)
    assert [story.epic for story in stories] == ["E1", "E2"]
    assert stories[1].summary == "最高分跨会话记住"


def test_gate_error_names_the_headings_that_are_present() -> None:
    """A blocked step must show what its output actually contained."""
    step = WorkflowStepResource(index=1, name="step-07.md", instructions="", validation_rules="section: 实现摘要")
    with pytest.raises(WorkflowGateError, match="present H2 headings: 3. 本轮实现动作"):
        WorkflowRunner.validate_output(step, "## 3. 本轮实现动作\n\ntext\n")


# --- Phase 5 C1：步骤粒度观测事件（emit 注入端口）---


@pytest.mark.asyncio
async def test_run_step_emits_started_and_completed_with_duration() -> None:
    """emit 注入 → started/completed 各一条（step/story/result + duration_ms）。"""
    from typing import Any

    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(kind: str, *, details: dict[str, Any] | None = None) -> None:
        events.append((kind, details or {}))

    async def callback(step):
        return WorkflowStepResult(output={"plan": "x"})

    await runner.run_step(callback, inputs={"brief": "x"}, emit=emit)
    kinds = [kind for kind, _ in events]
    assert kinds == ["workflow_step_started", "workflow_step_completed"]
    started_details = events[0][1]
    assert started_details["step"] == "step-01.md"
    assert started_details["story"] == ""
    assert isinstance(started_details["duration_ms"], int)
    completed_details = events[1][1]
    assert completed_details["result"] == "completed"
    assert completed_details["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_run_step_emits_failed_and_reraises() -> None:
    """回调抛异常 → workflow_step_failed（error_kind=exception）且异常原样上抛。"""
    from typing import Any

    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(kind: str, *, details: dict[str, Any] | None = None) -> None:
        events.append((kind, details or {}))

    async def callback(step):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await runner.run_step(callback, emit=emit)
    kinds = [kind for kind, _ in events]
    assert kinds == ["workflow_step_started", "workflow_step_failed"]
    failed = events[1][1]
    assert failed["error_kind"] == "exception"
    assert "boom" in failed["error"]
    assert failed["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_run_step_without_emit_is_unchanged_and_emit_failure_isolated() -> None:
    """emit=None 零行为变化；emit 抛异常被隔离（warning）且步骤结果不受影响。"""
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)

    async def callback(step):
        return WorkflowStepResult(output={"plan": "x"})

    # emit=None：与既有行为一致（不发事件、不抛；单步工作流执行完即 COMPLETED）
    result = await runner.run_step(callback, inputs={"brief": "x"})
    assert result.status is WorkflowStatus.COMPLETED

    # emit 抛异常 → 隔离
    def bad_emit(kind: str, *, details=None) -> None:
        raise RuntimeError("observer down")

    runner2 = WorkflowRunner(workflow)
    result2 = await runner2.run_step(callback, inputs={"brief": "x"}, emit=bad_emit)
    assert result2.status is WorkflowStatus.COMPLETED
