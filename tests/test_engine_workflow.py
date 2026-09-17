from __future__ import annotations

import pytest

from heagent.engine.workflow import (
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)


def test_initial_state_owns_runtime_metadata_only() -> None:
    state = GoalWorkflowState(goal_id="goal-1", active_story="43.1")

    assert state.phase is WorkflowPhase.DISCOVERY
    assert state.status is WorkflowStatus.PENDING
    assert state.artifact_refs == []
    assert "checkbox" not in state.model_dump()


@pytest.mark.asyncio
async def test_checkpoint_save_is_atomic_and_idempotent(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"))
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="goal1-run1-step0",
        goal_id="goal1",
        phase=WorkflowPhase.PLANNING,
        status=WorkflowStatus.COMPLETED,
        run_id="run1",
        next_action="await user",
    )

    first = await store.save(checkpoint)
    second = await store.save(checkpoint.model_copy(deep=True))
    assert first == second
    loaded = await store.load(checkpoint.checkpoint_id)
    assert loaded is not None
    assert loaded.next_action == "await user"
    workflow = await store.load_workflow()
    assert workflow is not None
    assert workflow.goal_id == "goal1"
    assert (tmp_path / "workflow.json").exists()


@pytest.mark.asyncio
async def test_checkpoint_store_loads_latest_unfinished_and_rejects_corruption(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"))
    await store.save(
        WorkflowCheckpoint(
            checkpoint_id="goal1-step1",
            goal_id="goal1",
            phase=WorkflowPhase.PLANNING,
            status=WorkflowStatus.COMPLETED,
            run_id="run1",
            created_at="2026-09-01T10:00:00",
        )
    )
    await store.save(
        WorkflowCheckpoint(
            checkpoint_id="goal1-step2",
            goal_id="goal1",
            phase=WorkflowPhase.SPRINT,
            status=WorkflowStatus.WAITING_USER,
            run_id="run2",
            active_step=2,
            created_at="2026-09-01T10:01:00",
        )
    )
    latest = await store.load_latest_unfinished("goal1")
    assert latest is not None
    assert latest.checkpoint_id == "goal1-step2"

    (tmp_path / "checkpoints" / "broken.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(WorkflowCheckpointError, match="corrupted"):
        await store.load("broken")


@pytest.mark.asyncio
async def test_checkpoint_rejects_goal_mismatch_and_corrupt_workflow_state(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"))
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="goal1-step1",
        goal_id="goal1",
        phase=WorkflowPhase.PLANNING,
        status=WorkflowStatus.WAITING_USER,
        run_id="run1",
    )
    with pytest.raises(WorkflowCheckpointError, match="different goals"):
        await store.save(checkpoint, GoalWorkflowState(goal_id="goal2"))

    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(WorkflowCheckpointError, match="workflow state is corrupted"):
        await store.save(checkpoint)


@pytest.mark.asyncio
async def test_checkpoint_rejects_in_flight_conflicts_and_unsafe_ids(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"))
    in_flight = WorkflowCheckpoint(
        checkpoint_id="goal1-run1-step0",
        goal_id="goal1",
        phase=WorkflowPhase.PLANNING,
        status=WorkflowStatus.RUNNING,
        run_id="run1",
        tool_in_flight=True,
    )
    with pytest.raises(WorkflowCheckpointError, match="in flight"):
        await store.save(in_flight)

    checkpoint = in_flight.model_copy(update={"tool_in_flight": False, "status": WorkflowStatus.COMPLETED})
    await store.save(checkpoint)
    with pytest.raises(WorkflowCheckpointError, match="conflict"):
        await store.save(checkpoint.model_copy(update={"next_action": "different"}))
    with pytest.raises(WorkflowCheckpointError, match="path-safe"):
        await store.load("../escape")
