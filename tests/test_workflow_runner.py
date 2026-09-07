from __future__ import annotations

import pytest

from heagent.engine.workflow import WorkflowCheckpoint, WorkflowCheckpointStore, WorkflowPhase, WorkflowStatus
from heagent.engine.workflow_runner import WorkflowRunResult, WorkflowRunner, WorkflowStepResult
from heagent.memory.skill_packages import WorkflowResource, WorkflowStepResource


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
    state = await store.load_workflow()
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
