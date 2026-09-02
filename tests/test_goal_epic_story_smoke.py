"""No-network smoke coverage for a declarative Goal -> Epic -> Story delivery."""

from __future__ import annotations

import pytest

from heagent.engine.agile import (
    CompletedStoryEvidence,
    Retrospective,
    ReviewFinding,
    ReviewVerdict,
    apply_review_verdict,
)
from heagent.engine.artifacts import ArtifactStatus, parse_artifact, validate_hierarchy
from heagent.engine.workflow import WorkflowCheckpointStore, WorkflowPhase, WorkflowStatus
from heagent.engine.workflow_runner import WorkflowRunner, WorkflowStepResult
from heagent.memory.skill_packages import WorkflowResource, WorkflowStepResource


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

    workflow_state = await store.load_workflow()
    assert workflow_state is not None
    review_state = workflow_state.model_copy(update={"phase": WorkflowPhase.REVIEW, "status": WorkflowStatus.RUNNING})
    rollback = apply_review_verdict(
        review_state,
        ReviewVerdict(
            evidence=["review output"],
            findings=[ReviewFinding(finding_id="f-1", summary="missing edge assertion", evidence=["test gap"])],
        ),
    )
    assert rollback.state.phase is WorkflowPhase.IMPLEMENTATION
    assert rollback.verdict.findings[0].summary == "missing edge assertion"

    retrospective = Retrospective(
        epic_id="epic-sample",
        stories=[
            CompletedStoryEvidence(
                story_id="story-one",
                status=ArtifactStatus.DONE,
                acceptance_evidence=["story-one acceptance passed"],
            ),
            CompletedStoryEvidence(
                story_id="story-two",
                status=ArtifactStatus.DONE,
                acceptance_evidence=["story-two acceptance passed"],
            ),
        ],
        outcomes=["two stories delivered"],
        lessons=["checkpoint recovery preserves WIP"],
        actions=["keep artifact gates"],
    )
    assert [story.story_id for story in retrospective.stories] == ["story-one", "story-two"]
