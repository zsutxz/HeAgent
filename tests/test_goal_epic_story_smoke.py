"""No-network smoke coverage for a declarative Goal -> Epic -> Story delivery."""

from __future__ import annotations

import pytest

from heagent.engine.artifacts import parse_artifact, validate_hierarchy
from heagent.engine.checkpoint import WorkflowCheckpointStore, WorkflowStatus
from heagent.engine.workflow_runner import WorkflowRunner, WorkflowStepResult
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource


GOAL = """---
id: goal-sample
type: goal
status: planning
title: Sample goal
---
# Sample goal

## Epics
- epic-sample: Sample Epic
"""

EPIC = """---
id: epic-sample
type: epic
goal_id: goal-sample
status: planning
title: Sample Epic
---
# Sample Epic

## Goal
Deliver two independently verifiable stories.
## Value
Users receive a tested increment.
## Scope
Only the sample workflow.
## Dependencies
None.
## Acceptance Criteria
- Both stories have evidence.
## Stories
- story-one: Plan
- story-two: Build
## Definition of Done
- Both stories are accepted.
"""

STORY_ONE = """---
id: story-one
type: story
goal_id: goal-sample
epic_id: epic-sample
status: done
title: Plan
---
# Plan

## User Story
As a user, I want a plan, so that work is scoped.
## Acceptance Criteria
- Given a goal, when planning completes, then a plan exists.
## Tasks
- [x] Produce plan.
## Definition of Done
- Plan evidence recorded.
"""

STORY_TWO = (
    STORY_ONE.replace("story-one", "story-two")
    .replace("# Plan", "# Build")
    .replace("a plan, so that work is scoped", "a build, so that value is delivered")
)


@pytest.mark.asyncio
async def test_two_story_epic_smoke_preserves_evidence_across_recovery(tmp_path) -> None:
    validate_hierarchy(
        [parse_artifact(GOAL), parse_artifact(EPIC), parse_artifact(STORY_ONE), parse_artifact(STORY_TWO)]
    )
    workflow = WorkflowResource(
        name="sample-epic",
        instructions="",
        steps=[
            WorkflowStepResource(index=1, name="story-one.md", instructions="", output="story-one"),
            WorkflowStepResource(index=2, name="story-two.md", instructions="", input="story-one", output="story-two"),
        ],
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal-sample", run_id="sample-run", checkpoint_store=store)
    executed: list[str] = []

    async def execute(step: WorkflowStepResource) -> WorkflowStepResult:
        executed.append(step.name)
        return WorkflowStepResult(output=f"{step.name} accepted", evidence=[f"{step.name} acceptance passed"])

    assert (await runner.run_step(execute)).status is WorkflowStatus.PENDING
    restored = WorkflowRunner.from_checkpoint(
        workflow,
        (await store.list_checkpoints(goal_id="goal-sample"))[-1],
        checkpoint_store=store,
    )
    assert (await restored.run_step(execute, inputs=restored.state.outputs)).status is WorkflowStatus.COMPLETED
    assert executed == ["story-one.md", "story-two.md"]
    assert (await restored.run_step(execute)).status is WorkflowStatus.COMPLETED
    assert executed == ["story-one.md", "story-two.md"]

    workflow_state = await store.load_state()
    assert workflow_state is not None
    # Non-DONE workflow phases persist completed runner state as RUNNING.
    assert workflow_state.status is WorkflowStatus.RUNNING
    assert workflow_state.artifact_refs == ["story-one.md", "story-one", "story-two.md", "story-two"]
    assert len(restored.state.acceptance_evidence) == 2
