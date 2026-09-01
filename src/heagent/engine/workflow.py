"""Goal-level workflow state and deterministic phase transitions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from heagent.engine.persist import atomic_write_text, load_json_model

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class SkillResolverProtocol(Protocol):
    """Minimal resolver contract keeping engine independent from memory."""

    def resolve(self, skill_id: str) -> object:
        ...


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class WorkflowPhase(StrEnum):
    """Phases owned by the goal workflow orchestrator."""

    DISCOVERY = "discovery"
    PLANNING = "planning"
    SPRINT = "sprint"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    RETROSPECTIVE = "retrospective"
    DONE = "done"


class WorkflowStatus(StrEnum):
    """Runtime status of the current goal work unit."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


class WorkflowTransitionError(ValueError):
    """Raised when a goal workflow transition is not safe to apply."""


class WorkflowRoute(BaseModel):
    """A deterministic next-skill decision or an explicit gate result."""

    skill_id: str | None = None
    target_phase: WorkflowPhase | None = None
    status: WorkflowStatus
    missing_artifacts: list[str] = Field(default_factory=list)
    reason: str = ""


class WorkflowCheckpoint(BaseModel):
    """Atomic, resumable snapshot for one completed workflow unit."""

    checkpoint_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    phase: WorkflowPhase
    status: WorkflowStatus
    run_id: str = Field(min_length=1)
    active_skill: str | None = None
    active_step: int | None = Field(default=None, ge=0)
    active_story: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    acceptance_evidence: list[str] = Field(default_factory=list)
    next_action: str = ""
    tool_in_flight: bool = False
    created_at: str = Field(default_factory=_iso_now)


class WorkflowCheckpointError(ValueError):
    """Raised when checkpoint persistence cannot safely proceed."""


class WorkflowCheckpointStore:
    """File-backed checkpoint store with deterministic idempotency."""

    def __init__(self, base_dir: str = ".heagent/checkpoints") -> None:
        self._base = Path(base_dir)
        self._lock = asyncio.Lock()

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        if checkpoint.tool_in_flight:
            raise WorkflowCheckpointError("cannot checkpoint a workflow with a tool in flight")
        path = self._path(checkpoint.checkpoint_id)
        async with self._lock:
            existing = await asyncio.to_thread(load_json_model, path, WorkflowCheckpoint)
            if path.exists() and existing is None:
                raise WorkflowCheckpointError(f"checkpoint is corrupted: {path}")
            if existing is not None:
                if existing.model_dump(mode="json") != checkpoint.model_dump(mode="json"):
                    raise WorkflowCheckpointError(f"checkpoint conflict: {checkpoint.checkpoint_id}")
                return str(path)
            payload = json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=False, indent=2)
            await asyncio.to_thread(atomic_write_text, path, payload)
        return str(path)

    async def load(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        return await asyncio.to_thread(load_json_model, self._path(checkpoint_id), WorkflowCheckpoint)

    def _path(self, checkpoint_id: str) -> Path:
        if not checkpoint_id or Path(checkpoint_id).name != checkpoint_id or checkpoint_id in {".", ".."}:
            raise WorkflowCheckpointError("checkpoint id must be a single path-safe name")
        return self._base / f"{checkpoint_id}.json"


class TokenBudgetError(ValueError):
    """Raised for invalid or inconsistent token accounting."""


class TokenBudgetState(BaseModel):
    """Separate counters for a segment, a goal, and the active context window."""

    segment_index: int = Field(default=0, ge=0)
    segment_tokens: int = Field(default=0, ge=0)
    cumulative_tokens: int = Field(default=0, ge=0)
    context_window_usage: int = Field(default=0, ge=0)


class TokenBudgetManager:
    """Deterministically decide whether a provider call must roll over."""

    def __init__(self, *, segment_limit: int, rollover_threshold: float = 0.8) -> None:
        if segment_limit <= 0 or not 0 < rollover_threshold <= 1:
            raise TokenBudgetError("segment limit and rollover threshold are invalid")
        self.segment_limit = segment_limit
        self.rollover_threshold = rollover_threshold
        self.state = TokenBudgetState()

    @property
    def threshold(self) -> int:
        return int(self.segment_limit * self.rollover_threshold)

    def should_rollover(self, estimated_tokens: int = 0) -> bool:
        self._validate_count(estimated_tokens, "estimated_tokens")
        return self.state.segment_tokens + estimated_tokens >= self.threshold

    def record(self, *, prompt_tokens: int, completion_tokens: int) -> TokenBudgetState:
        self._validate_count(prompt_tokens, "prompt_tokens")
        self._validate_count(completion_tokens, "completion_tokens")
        total = prompt_tokens + completion_tokens
        self.state = self.state.model_copy(
            update={
                "segment_tokens": self.state.segment_tokens + total,
                "cumulative_tokens": self.state.cumulative_tokens + total,
                "context_window_usage": self.state.context_window_usage + prompt_tokens,
            }
        )
        return self.state.model_copy(deep=True)

    def rollover(self) -> TokenBudgetState:
        self.state = self.state.model_copy(
            update={"segment_index": self.state.segment_index + 1, "segment_tokens": 0, "context_window_usage": 0}
        )
        return self.state.model_copy(deep=True)

    @staticmethod
    def _validate_count(value: int, name: str) -> None:
        if not isinstance(value, int) or value < 0:
            raise TokenBudgetError(f"{name} must be a non-negative integer")


class RolloverResult(BaseModel):
    """Evidence that a segment rollover completed in the required order."""

    previous_run_id: str = Field(min_length=1)
    new_run_id: str = Field(min_length=1)
    previous_segment: int = Field(ge=0)
    new_segment: int = Field(ge=0)


class RolloverCoordinator:
    """Coordinate checkpoint -> segment reset -> fresh run without importing agent."""

    def __init__(
        self,
        checkpoint: Callable[[str], Awaitable[None]],
        start_run: Callable[[str], Awaitable[str]],
    ) -> None:
        self._checkpoint = checkpoint
        self._start_run = start_run

    async def rollover(
        self,
        manager: TokenBudgetManager,
        *,
        run_id: str,
        tool_in_flight: bool = False,
    ) -> RolloverResult:
        if not run_id.strip():
            raise TokenBudgetError("run_id is required")
        if tool_in_flight:
            raise TokenBudgetError("cannot rollover while a tool is in flight")
        previous_segment = manager.state.segment_index
        await self._checkpoint(run_id)
        next_state = manager.rollover()
        new_run_id = await self._start_run(run_id)
        if not isinstance(new_run_id, str) or not new_run_id.strip():
            raise TokenBudgetError("fresh run callback returned an invalid run id")
        return RolloverResult(
            previous_run_id=run_id,
            new_run_id=new_run_id,
            previous_segment=previous_segment,
            new_segment=next_state.segment_index,
        )


class RecoveryEnvelope(BaseModel):
    """Minimal, versioned context passed to a fresh run."""

    version: int = 1
    goal_id: str = Field(min_length=1)
    phase: WorkflowPhase
    active_story: str | None = None
    active_step: int | None = Field(default=None, ge=0)
    artifact_refs: list[str] = Field(default_factory=list)
    acceptance_evidence: list[str] = Field(default_factory=list)
    checkpoint_summary: str = ""
    next_action: str = ""
    summary_error: str | None = None


def build_recovery_envelope(
    state: GoalWorkflowState,
    *,
    acceptance_evidence: list[str] | None = None,
    checkpoint_summary: str | None = None,
    summary_error: str | None = None,
    next_action: str = "",
) -> RecoveryEnvelope:
    """Build a bounded recovery context with deterministic summary fallback."""
    summary = checkpoint_summary
    if not summary:
        summary = f"goal={state.goal_id}; phase={state.phase.value}; status={state.status.value}"
        if state.active_story:
            summary += f"; story={state.active_story}"
    return RecoveryEnvelope(
        goal_id=state.goal_id,
        phase=state.phase,
        active_story=state.active_story,
        active_step=state.active_step,
        artifact_refs=list(state.artifact_refs),
        acceptance_evidence=list(acceptance_evidence or []),
        checkpoint_summary=summary,
        next_action=next_action,
        summary_error=summary_error,
    )


class GoalWorkflowState(BaseModel):
    """Serializable runtime metadata for one goal.

    ``GOAL.md`` remains the source of truth for story checkboxes. This model stores
    only orchestration metadata and therefore never mirrors or edits that board.
    """

    model_config = ConfigDict(frozen=True, validate_assignment=True)

    goal_id: str = Field(default_factory=lambda: uuid4().hex[:8], min_length=1)
    phase: WorkflowPhase = WorkflowPhase.DISCOVERY
    active_skill: str | None = None
    active_step: int | None = Field(default=None, ge=0)
    active_story: str | None = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    segment_index: int = Field(default=0, ge=0)
    segment_tokens: int = Field(default=0, ge=0)
    cumulative_tokens: int = Field(default=0, ge=0)
    artifact_refs: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    transition_reason: str = ""
    updated_at: str = Field(default_factory=_iso_now)

    @model_validator(mode="after")
    def validate_terminal_status(self) -> GoalWorkflowState:
        if self.phase is WorkflowPhase.DONE and self.status is not WorkflowStatus.COMPLETED:
            raise ValueError("done phase requires completed status")
        if self.status is WorkflowStatus.COMPLETED and self.phase is not WorkflowPhase.DONE:
            raise ValueError("completed status requires done phase")
        return self


class WorkflowOrchestrator:
    """Apply only declared phase transitions and explicit preconditions."""

    _TRANSITIONS: ClassVar[dict[WorkflowPhase, frozenset[WorkflowPhase]]] = {
        WorkflowPhase.DISCOVERY: frozenset({WorkflowPhase.PLANNING}),
        WorkflowPhase.PLANNING: frozenset({WorkflowPhase.SPRINT}),
        WorkflowPhase.SPRINT: frozenset({WorkflowPhase.IMPLEMENTATION}),
        WorkflowPhase.IMPLEMENTATION: frozenset({WorkflowPhase.REVIEW}),
        WorkflowPhase.REVIEW: frozenset({WorkflowPhase.IMPLEMENTATION, WorkflowPhase.RETROSPECTIVE, WorkflowPhase.DONE}),
        WorkflowPhase.RETROSPECTIVE: frozenset({WorkflowPhase.DONE}),
        WorkflowPhase.DONE: frozenset(),
    }

    _DEFAULT_SKILLS: ClassVar[dict[WorkflowPhase, str]] = {
        WorkflowPhase.DISCOVERY: "he-product-brief",
        WorkflowPhase.PLANNING: "he-architecture",
        WorkflowPhase.SPRINT: "he-sprint-planning",
        WorkflowPhase.IMPLEMENTATION: "he-build",
        WorkflowPhase.REVIEW: "he-code-review",
        WorkflowPhase.RETROSPECTIVE: "he-retrospective",
    }

    _NEXT_PHASE_PRIORITY: ClassVar[dict[WorkflowPhase, WorkflowPhase]] = {
        WorkflowPhase.DISCOVERY: WorkflowPhase.PLANNING,
        WorkflowPhase.PLANNING: WorkflowPhase.SPRINT,
        WorkflowPhase.SPRINT: WorkflowPhase.IMPLEMENTATION,
        WorkflowPhase.IMPLEMENTATION: WorkflowPhase.REVIEW,
        WorkflowPhase.REVIEW: WorkflowPhase.RETROSPECTIVE,
        WorkflowPhase.RETROSPECTIVE: WorkflowPhase.DONE,
    }

    @classmethod
    def route(
        cls,
        state: GoalWorkflowState,
        *,
        available_artifacts: list[str] | None = None,
        resolver: SkillResolverProtocol | None = None,
        requested_skill: str | None = None,
        waiting_for_user: bool = False,
    ) -> WorkflowRoute:
        """Choose one next skill, or return a loud gate result.

        Artifact checks are deliberately explicit and deterministic. The resolver
        remains responsible for canonical/alias resolution and ambiguity errors.
        """
        if state.status in {WorkflowStatus.BLOCKED, WorkflowStatus.FAILED, WorkflowStatus.COMPLETED}:
            return WorkflowRoute(status=state.status, reason=state.blocked_reason or "workflow is not runnable")
        if waiting_for_user or state.status is WorkflowStatus.WAITING_USER:
            return WorkflowRoute(status=WorkflowStatus.WAITING_USER, reason="user confirmation is required before continuing")
        target = cls._next_phase(state.phase)
        if target is None:
            return WorkflowRoute(status=WorkflowStatus.COMPLETED, target_phase=WorkflowPhase.DONE, reason="workflow has no remaining phase")
        artifacts = {item.replace("\\", "/").lower() for item in (available_artifacts or state.artifact_refs)}
        required = cls._required_artifacts(target)
        missing = [label for label, alternatives in required.items() if not any(option in artifacts for option in alternatives)]
        if missing:
            return WorkflowRoute(status=WorkflowStatus.BLOCKED, target_phase=target, missing_artifacts=missing, reason="missing required artifacts: " + ", ".join(missing))
        skill_id = requested_skill or cls._DEFAULT_SKILLS.get(target)
        if not skill_id:
            return WorkflowRoute(status=WorkflowStatus.BLOCKED, target_phase=target, reason=f"no skill is configured for phase {target.value}")
        if resolver is None:
            return WorkflowRoute(skill_id=skill_id, target_phase=target, status=WorkflowStatus.RUNNING, reason="skill selected")
        try:
            package = resolver.resolve(skill_id)
        except ValueError as exc:
            return WorkflowRoute(target_phase=target, status=WorkflowStatus.BLOCKED, reason=str(exc))
        metadata = getattr(package, "metadata", None)
        canonical_id = getattr(metadata, "canonical_id", "") or skill_id
        return WorkflowRoute(skill_id=canonical_id, target_phase=target, status=WorkflowStatus.RUNNING, reason="skill selected")

    @classmethod
    def _next_phase(cls, phase: WorkflowPhase) -> WorkflowPhase | None:
        if phase is WorkflowPhase.DONE:
            return None
        return cls._NEXT_PHASE_PRIORITY.get(phase)

    @staticmethod
    def _required_artifacts(target: WorkflowPhase) -> dict[str, tuple[str, ...]]:
        required_by_phase: dict[WorkflowPhase, dict[str, tuple[str, ...]]] = {
            WorkflowPhase.SPRINT: {"PRD or Spec": ("prd.md", "spec.md"), "architecture": ("architecture.md",)},
            WorkflowPhase.IMPLEMENTATION: {"ready Story": ("ready-for-dev",)},
            WorkflowPhase.REVIEW: {"implementation evidence": ("test-results", "implementation.md")},
        }
        return required_by_phase.get(target, {})

    @classmethod
    def can_transition(cls, state: GoalWorkflowState, target: WorkflowPhase) -> bool:
        """Return whether ``target`` is a legal next phase for ``state``."""
        if not isinstance(target, WorkflowPhase):
            return False
        if state.status not in {WorkflowStatus.PENDING, WorkflowStatus.RUNNING}:
            return False
        return target in cls._TRANSITIONS[state.phase]

    @classmethod
    def transition(
        cls,
        state: GoalWorkflowState,
        target: WorkflowPhase,
        *,
        reason: str,
        preconditions_met: bool = True,
    ) -> GoalWorkflowState:
        """Return a new state after validating the requested transition."""
        if not isinstance(target, WorkflowPhase):
            try:
                target = WorkflowPhase(target)
            except (TypeError, ValueError) as exc:
                raise WorkflowTransitionError(f"unknown target phase: {target!r}") from exc
        if not isinstance(reason, str) or not reason.strip():
            raise WorkflowTransitionError("transition reason is required")
        if state.status not in {WorkflowStatus.PENDING, WorkflowStatus.RUNNING}:
            raise WorkflowTransitionError(f"cannot transition a {state.status.value} workflow")
        if preconditions_met is not True:
            raise WorkflowTransitionError(
                f"preconditions are not met for {state.phase.value} -> {target.value}"
            )
        if not cls.can_transition(state, target):
            raise WorkflowTransitionError(f"illegal workflow transition: {state.phase.value} -> {target.value}")
        status = WorkflowStatus.COMPLETED if target is WorkflowPhase.DONE else WorkflowStatus.RUNNING
        return GoalWorkflowState.model_validate(
            state.model_copy(
                deep=True,
                update={
                "phase": target,
                "status": status,
                "blocked_reason": None,
                "transition_reason": reason,
                "updated_at": _iso_now(),
                }
            )
        )

    @staticmethod
    def block(state: GoalWorkflowState, reason: str) -> GoalWorkflowState:
        """Mark a workflow blocked without changing its phase or board state."""
        if not isinstance(reason, str) or not reason.strip():
            raise WorkflowTransitionError("blocked reason is required")
        if state.phase is WorkflowPhase.DONE or state.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.BLOCKED,
            WorkflowStatus.FAILED,
        }:
            raise WorkflowTransitionError("cannot block a terminal workflow")
        return GoalWorkflowState.model_validate(
            state.model_copy(
                deep=True,
                update={
                    "status": WorkflowStatus.BLOCKED,
                    "blocked_reason": reason,
                    "transition_reason": reason,
                    "updated_at": _iso_now(),
                },
            )
        )

    @staticmethod
    def fail(state: GoalWorkflowState, reason: str) -> GoalWorkflowState:
        """Mark a workflow failed without fabricating a completed phase."""
        if not isinstance(reason, str) or not reason.strip():
            raise WorkflowTransitionError("failure reason is required")
        if state.phase is WorkflowPhase.DONE or state.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.BLOCKED,
            WorkflowStatus.FAILED,
        }:
            raise WorkflowTransitionError("cannot fail a terminal workflow")
        return GoalWorkflowState.model_validate(
            state.model_copy(
                deep=True,
                update={
                    "status": WorkflowStatus.FAILED,
                    "blocked_reason": reason,
                    "transition_reason": reason,
                    "updated_at": _iso_now(),
                },
            )
        )
