"""Deterministic, no-network smoke coverage for goal workflow closure."""

from __future__ import annotations

import pytest
from heagent.engine.ledger import ExecutionLedger, ExecutionStatus
from heagent.engine.observability import EventBus
from heagent.engine.checkpoint import (
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)


@pytest.mark.asyncio
async def test_two_story_stub_smoke_leaves_checkpoint_and_audit_evidence(tmp_path) -> None:
    goal_id = "smoke-goal"
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    ledger = ExecutionLedger(str(tmp_path / "ledger"))
    events = EventBus()
    state = GoalWorkflowState(
        goal_id=goal_id,
        phase=WorkflowPhase.PLANNING,
        status=WorkflowStatus.RUNNING,
        artifact_refs=["prd.md", "architecture.md"],
    )

    for index, story in enumerate(("story-1", "story-2"), start=1):
        run_id = f"run-{index}"
        key = f"{goal_id}:{story}"
        claim = await ledger.acquire(
            key,
            scope="goal",
            run_id=run_id,
            metadata={"goal_id": goal_id, "story": story, "phase": "implementation"},
        )
        assert claim.acquired
        record = await ledger.complete(key, metadata={"goal_id": goal_id, "story": story, "tokens": 15})
        assert record.status is ExecutionStatus.COMPLETED
        events.publish(
            "goal.story.completed",
            run_id=run_id,
            details={"goal_id": goal_id, "story": story, "segment": index - 1, "tokens": 15},
        )
        phase = WorkflowPhase.IMPLEMENTATION if index == 1 else WorkflowPhase.REVIEW
        state = state.model_copy(
            update={
                "phase": phase,
                "active_story": story,
                "active_skill": "he-build",
                "active_step": index,
            }
        )
        await store.save(
            WorkflowCheckpoint(
                checkpoint_id=f"cp-{index}",
                goal_id=goal_id,
                phase=phase,
                status=WorkflowStatus.COMPLETED,
                run_id=run_id,
                active_skill="he-build",
                active_step=index,
                active_story=story,
                artifact_refs=list(state.artifact_refs),
                acceptance_evidence=[f"{story} completed by stub"],
                next_action="continue with next story",
            ),
            state,
        )

    done = GoalWorkflowState.model_validate(
        state.model_copy(
            update={
                "phase": WorkflowPhase.DONE,
                "status": WorkflowStatus.COMPLETED,
                "transition_reason": "smoke acceptance complete",
            }
        )
    )
    await store.save(
        WorkflowCheckpoint(
            checkpoint_id="cp-done",
            goal_id=goal_id,
            phase=WorkflowPhase.DONE,
            status=WorkflowStatus.COMPLETED,
            run_id="run-final",
            active_story="story-2",
            acceptance_evidence=["smoke complete"],
            next_action="none",
        ),
        done,
    )

    assert done.status is WorkflowStatus.COMPLETED
    assert len(await store.list_checkpoints(goal_id=goal_id)) == 3
    assert await store.load_latest_unfinished(goal_id) is None
    assert len([r for r in await ledger.list_records() if r.metadata["goal_id"] == goal_id]) == 2
    assert len([e for e in events.recent_events if e.details.get("goal_id") == goal_id]) == 2


@pytest.mark.asyncio
async def test_corrupt_workflow_evidence_fails_loudly(tmp_path) -> None:
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text("{not-json", encoding="utf-8")
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(workflow_path))

    with pytest.raises(ValueError, match="workflow state is corrupted"):
        await store.load_state()
