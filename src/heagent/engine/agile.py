"""Typed, deterministic closure records for Goal workflow review cycles."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from heagent.engine.artifacts import ArtifactStatus
from heagent.engine.workflow import (
    GoalWorkflowState,
    WorkflowOrchestrator,
    WorkflowPhase,
    WorkflowTransitionError,
)


class AgileClosureError(ValueError):
    """Raised when a review or agile-closure record is incomplete or unsafe."""


class ReviewFinding(BaseModel):
    """One preserved review finding and the evidence that supports it."""

    model_config = ConfigDict(frozen=True)

    finding_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    blocking: bool = True


class ReviewVerdict(BaseModel):
    """A review outcome which retains evidence whether review passes or fails."""

    model_config = ConfigDict(frozen=True)

    evidence: list[str] = Field(min_length=1)
    findings: list[ReviewFinding] = Field(default_factory=list)

    @property
    def has_blocking_findings(self) -> bool:
        return any(finding.blocking for finding in self.findings)

    @property
    def completion_eligible(self) -> bool:
        return not self.has_blocking_findings


class ReviewApplication(BaseModel):
    """The immutable verdict plus the resulting workflow state."""

    model_config = ConfigDict(frozen=True)

    verdict: ReviewVerdict
    state: GoalWorkflowState
    completion_eligible: bool


def apply_review_verdict(state: GoalWorkflowState, verdict: ReviewVerdict) -> ReviewApplication:
    """Apply blocking review findings through the sole phase-transition owner."""
    if state.phase is not WorkflowPhase.REVIEW:
        raise AgileClosureError("review verdict requires a workflow in review phase")
    if verdict.has_blocking_findings:
        summaries = "; ".join(finding.summary for finding in verdict.findings if finding.blocking)
        try:
            next_state = WorkflowOrchestrator.transition(
                state,
                WorkflowPhase.IMPLEMENTATION,
                reason=f"review requires implementation: {summaries}",
            )
        except WorkflowTransitionError as exc:
            raise AgileClosureError(str(exc)) from exc
    else:
        next_state = state.model_copy(deep=True)
    return ReviewApplication(
        verdict=verdict,
        state=next_state,
        completion_eligible=verdict.completion_eligible,
    )


class CompletedStoryEvidence(BaseModel):
    """A completed Story and the acceptance evidence required for an Epic retro."""

    model_config = ConfigDict(frozen=True)

    story_id: str = Field(min_length=1)
    status: ArtifactStatus
    acceptance_evidence: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def require_done_status(self) -> CompletedStoryEvidence:
        if self.status is not ArtifactStatus.DONE:
            raise ValueError("retrospective stories must have done status")
        return self


class Retrospective(BaseModel):
    """Auditable Epic-level learning record grounded in completed Stories."""

    model_config = ConfigDict(frozen=True)

    epic_id: str = Field(min_length=1)
    stories: list[CompletedStoryEvidence] = Field(min_length=1)
    outcomes: list[str] = Field(min_length=1)
    lessons: list[str] = Field(min_length=1)
    actions: list[str] = Field(min_length=1)


class CorrectCourse(BaseModel):
    """A material scope or design correction with an explicit phase transition."""

    model_config = ConfigDict(frozen=True)

    source_phase: WorkflowPhase
    target_phase: WorkflowPhase
    reason: str = Field(min_length=1)
    impact: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_distinct_phases(self) -> CorrectCourse:
        if self.source_phase is self.target_phase:
            raise ValueError("correct course requires different source and target phases")
        return self


def apply_correct_course(state: GoalWorkflowState, record: CorrectCourse) -> GoalWorkflowState:
    """Apply a correction only when it matches the state and is a legal transition."""
    if state.phase is not record.source_phase:
        raise AgileClosureError(
            f"correct course source phase does not match workflow: {record.source_phase.value} != {state.phase.value}"
        )
    try:
        return WorkflowOrchestrator.transition(
            state,
            record.target_phase,
            reason=f"{record.reason}: {record.impact}",
        )
    except WorkflowTransitionError as exc:
        raise AgileClosureError(str(exc)) from exc
