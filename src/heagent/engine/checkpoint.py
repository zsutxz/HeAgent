"""Goal-level workflow state and checkpoint persistence.

``GoalWorkflowState`` is the serializable orchestration metadata for one goal;
``WorkflowCheckpointStore`` persists atomic, resumable checkpoints. The active
declarative runner lives in ``workflow_runner.py``. The legacy phase machine
(``WorkflowOrchestrator`` / ``TokenBudgetManager`` / ``RolloverCoordinator`` /
``RecoveryEnvelope`` / ``WorkflowRoute``) was removed in 2026-09 — the same
cleanup that retired the legacy GOAL.md Story flow in ``cli_goal.py``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from heagent.persist import atomic_write_text, load_json_model


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


class WorkflowPhase(StrEnum):
    """Phases of the goal workflow state."""

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
    outputs: dict[str, Any] = Field(default_factory=dict)
    acceptance_evidence: list[str] = Field(default_factory=list)
    completed_steps: list[int] = Field(default_factory=list)
    story_index: int | None = Field(default=None, ge=0)
    completed_stories: list[str] = Field(default_factory=list)
    story_outputs: dict[str, Any] = Field(default_factory=dict)
    active_stories: list[str] = Field(default_factory=list)
    story_statuses: dict[str, str] = Field(default_factory=dict)
    next_action: str = ""
    tool_in_flight: bool = False
    created_at: str = Field(default_factory=_iso_now)


class WorkflowCheckpointError(ValueError):
    """Raised when checkpoint persistence cannot safely proceed."""


class WorkflowCheckpointStore:
    """File-backed checkpoint store with deterministic idempotency."""

    def __init__(self, base_dir: str = ".heagent/checkpoints", *, workflow_path: str | None = None) -> None:
        self._base = Path(base_dir)
        self._workflow_path = Path(workflow_path) if workflow_path is not None else self._base.parent / "workflow.json"
        self._lock = asyncio.Lock()

    async def save(self, checkpoint: WorkflowCheckpoint, workflow_state: GoalWorkflowState | None = None) -> str:
        if checkpoint.tool_in_flight:
            raise WorkflowCheckpointError("cannot checkpoint a workflow with a tool in flight")
        path = self._path(checkpoint.checkpoint_id)
        state = workflow_state or self._state_from_checkpoint(checkpoint)
        if state.goal_id != checkpoint.goal_id:
            raise WorkflowCheckpointError("checkpoint and workflow state belong to different goals")
        async with self._lock:
            existing_workflow = await asyncio.to_thread(load_json_model, self._workflow_path, GoalWorkflowState)
            if self._workflow_path.exists() and existing_workflow is None:
                raise WorkflowCheckpointError(f"workflow state is corrupted: {self._workflow_path}")
            existing = await asyncio.to_thread(load_json_model, path, WorkflowCheckpoint)
            if path.exists() and existing is None:
                raise WorkflowCheckpointError(f"checkpoint is corrupted: {path}")
            if existing is not None:
                if self._logical_dump(existing) != self._logical_dump(checkpoint):
                    raise WorkflowCheckpointError(f"checkpoint conflict: {checkpoint.checkpoint_id}")
            else:
                payload = json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=False, indent=2)
                await asyncio.to_thread(atomic_write_text, path, payload)
            workflow_payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2)
            await asyncio.to_thread(atomic_write_text, self._workflow_path, workflow_payload)
        return str(path)

    async def load(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        path = self._path(checkpoint_id)
        checkpoint = await asyncio.to_thread(load_json_model, path, WorkflowCheckpoint)
        if path.exists() and checkpoint is None:
            raise WorkflowCheckpointError(f"checkpoint is corrupted: {path}")
        return checkpoint

    async def load_state(self) -> GoalWorkflowState | None:
        """Load the persisted aggregate run state (progress); corruption is an explicit failure.

        2026-09-20 自 ``load_workflow`` 改名：旧名与 ``goal/workflow_loader.read_workflow``
        （装载 workflow.md 声明）撞车，易误读为「加载工作流定义」。本方法只恢复运行时进度。
        """
        state = await asyncio.to_thread(load_json_model, self._workflow_path, GoalWorkflowState)
        if self._workflow_path.exists() and state is None:
            raise WorkflowCheckpointError(f"workflow state is corrupted: {self._workflow_path}")
        return state

    async def list_checkpoints(self, *, goal_id: str | None = None) -> list[WorkflowCheckpoint]:
        """Return valid checkpoints in deterministic creation/id order."""
        if not await asyncio.to_thread(self._base.exists):
            return []
        checkpoints: list[WorkflowCheckpoint] = []
        for path in sorted(await asyncio.to_thread(lambda: list(self._base.glob("*.json")))):
            checkpoint = await asyncio.to_thread(load_json_model, path, WorkflowCheckpoint)
            if checkpoint is None:
                raise WorkflowCheckpointError(f"checkpoint is corrupted: {path}")
            if goal_id is None or checkpoint.goal_id == goal_id:
                checkpoints.append(checkpoint)
        return sorted(checkpoints, key=lambda item: (item.created_at, item.checkpoint_id))

    async def load_latest_unfinished(self, goal_id: str) -> WorkflowCheckpoint | None:
        """Load the latest checkpoint that has not completed its workflow unit."""
        checkpoints = await self.list_checkpoints(goal_id=goal_id)
        for checkpoint in reversed(checkpoints):
            if checkpoint.status is not WorkflowStatus.COMPLETED:
                return checkpoint
        return None

    @staticmethod
    def _state_from_checkpoint(checkpoint: WorkflowCheckpoint) -> GoalWorkflowState:
        aggregate_status = checkpoint.status
        if aggregate_status is WorkflowStatus.COMPLETED and checkpoint.phase is not WorkflowPhase.DONE:
            # A checkpoint completes one unit; only the done phase completes the goal.
            aggregate_status = WorkflowStatus.RUNNING
        return GoalWorkflowState(
            goal_id=checkpoint.goal_id,
            phase=checkpoint.phase,
            active_skill=checkpoint.active_skill,
            active_step=checkpoint.active_step,
            active_story=checkpoint.active_story,
            active_stories=list(checkpoint.active_stories),
            story_statuses=dict(checkpoint.story_statuses),
            status=aggregate_status,
            artifact_refs=list(checkpoint.artifact_refs),
            next_action=checkpoint.next_action,
            updated_at=checkpoint.created_at,
        )

    @staticmethod
    def _logical_dump(checkpoint: WorkflowCheckpoint) -> dict[str, Any]:
        """Serialize checkpoint identity without the wall-clock persistence stamp.

        ``created_at`` legitimately differs between two writes of the same logical
        snapshot (for example a pause/resume cycle re-issuing the same pending
        checkpoint), so it must not participate in conflict detection.
        """
        return checkpoint.model_dump(mode="json", exclude={"created_at"})

    def _path(self, checkpoint_id: str) -> Path:
        if not checkpoint_id or Path(checkpoint_id).name != checkpoint_id or checkpoint_id in {".", ".."}:
            raise WorkflowCheckpointError("checkpoint id must be a single path-safe name")
        return self._base / f"{checkpoint_id}.json"


class GoalWorkflowState(BaseModel):
    """Serializable runtime metadata for one goal.

    The workflow's own artifacts stay the source of truth (``require.md`` for the request,
    ``02-epics.md`` for the Epic/Story lists). This model stores only orchestration metadata
    and therefore never mirrors or edits them.
    """

    model_config = ConfigDict(frozen=True, validate_assignment=True)

    goal_id: str = Field(default_factory=lambda: uuid4().hex[:8], min_length=1)
    phase: WorkflowPhase = WorkflowPhase.DISCOVERY
    active_skill: str | None = None
    active_step: int | None = Field(default=None, ge=0)
    active_story: str | None = None
    active_stories: list[str] = Field(default_factory=list)
    story_statuses: dict[str, str] = Field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.PENDING
    artifact_refs: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    transition_reason: str = ""
    next_action: str = ""
    updated_at: str = Field(default_factory=_iso_now)

    @model_validator(mode="after")
    def validate_terminal_status(self) -> GoalWorkflowState:
        if self.phase is WorkflowPhase.DONE and self.status is not WorkflowStatus.COMPLETED:
            raise ValueError("done phase requires completed status")
        if self.status is WorkflowStatus.COMPLETED and self.phase is not WorkflowPhase.DONE:
            raise ValueError("completed status requires done phase")
        return self
