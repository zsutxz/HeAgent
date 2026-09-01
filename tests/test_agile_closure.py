from __future__ import annotations

import pytest
from pydantic import ValidationError

from heagent.engine.agile import (
    AgileClosureError,
    CompletedStoryEvidence,
    CorrectCourse,
    Retrospective,
    ReviewFinding,
    ReviewVerdict,
    apply_correct_course,
    apply_review_verdict,
)
from heagent.engine.artifacts import ArtifactStatus
from heagent.engine.workflow import GoalWorkflowState, WorkflowPhase, WorkflowStatus


def test_blocking_review_returns_to_implementation_and_preserves_verdict() -> None:
    state = GoalWorkflowState(phase=WorkflowPhase.REVIEW, status=WorkflowStatus.RUNNING)
    verdict = ReviewVerdict(
        evidence=["tests/test_feature.py::test_failure"],
        findings=[ReviewFinding(finding_id="review-1", summary="missing boundary check", evidence=["line 42"])],
    )

    result = apply_review_verdict(state, verdict)

    assert result.state.phase is WorkflowPhase.IMPLEMENTATION
    assert result.state.status is WorkflowStatus.RUNNING
    assert result.verdict.findings == verdict.findings
    assert result.completion_eligible is False
    assert state.phase is WorkflowPhase.REVIEW
    assert state.status is WorkflowStatus.RUNNING


def test_passing_review_requires_evidence_and_does_not_roll_back() -> None:
    state = GoalWorkflowState(phase=WorkflowPhase.REVIEW, status=WorkflowStatus.RUNNING)
    verdict = ReviewVerdict(evidence=["pytest passed"])

    result = apply_review_verdict(state, verdict)

    assert result.state.phase is WorkflowPhase.REVIEW
    assert result.completion_eligible is True
    with pytest.raises(ValidationError):
        ReviewVerdict(evidence=[])


def test_retrospective_requires_done_stories_and_acceptance_evidence() -> None:
    complete = CompletedStoryEvidence(
        story_id="47-5", status=ArtifactStatus.DONE, acceptance_evidence=["acceptance test passed"]
    )
    retrospective = Retrospective(
        epic_id="epic-47",
        stories=[complete],
        outcomes=["shipped"],
        lessons=["test contracts"],
        actions=["add coverage"],
    )

    assert retrospective.stories == [complete]
    with pytest.raises(ValidationError, match="done status"):
        CompletedStoryEvidence(story_id="47-4", status=ArtifactStatus.REVIEW, acceptance_evidence=["review link"])
    with pytest.raises(ValidationError):
        CompletedStoryEvidence(story_id="47-4", status=ArtifactStatus.DONE, acceptance_evidence=[])


def test_correct_course_rejects_illegal_transition_without_mutating_source() -> None:
    state = GoalWorkflowState(phase=WorkflowPhase.REVIEW, status=WorkflowStatus.RUNNING)
    legal = CorrectCourse(
        source_phase=WorkflowPhase.REVIEW,
        target_phase=WorkflowPhase.IMPLEMENTATION,
        reason="scope correction",
        impact="add missing validation",
    )

    corrected = apply_correct_course(state, legal)

    assert corrected.phase is WorkflowPhase.IMPLEMENTATION
    assert state.phase is WorkflowPhase.REVIEW
    illegal = legal.model_copy(update={"target_phase": WorkflowPhase.SPRINT})
    with pytest.raises(AgileClosureError, match="illegal workflow transition"):
        apply_correct_course(state, illegal)
    assert state.phase is WorkflowPhase.REVIEW
