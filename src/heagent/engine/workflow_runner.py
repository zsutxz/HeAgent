"""Deterministic one-step runner for declarative Markdown workflows."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from heagent.engine.workflow import (
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)
from heagent.memory.skill_packages import WorkflowResource, WorkflowStepResource


class WorkflowGateError(ValueError):
    """Raised when a step cannot satisfy its declared contract."""


class WorkflowRunnerState(BaseModel):
    """Serializable progress for a declarative workflow."""

    active_step: int = Field(default=0, ge=0)
    status: WorkflowStatus = WorkflowStatus.PENDING
    completed_steps: list[int] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    acceptance_evidence: list[str] = Field(default_factory=list)
    reason: str = ""


class WorkflowStepResult(BaseModel):
    """Callback result returned after executing one step."""

    status: WorkflowStatus = WorkflowStatus.COMPLETED
    output: Any = None
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""


class WorkflowRunResult(BaseModel):
    """Validated public result of one runner invocation."""

    status: WorkflowStatus
    step_index: int | None = None
    output: Any = None
    reason: str = ""
    missing: list[str] = Field(default_factory=list)
    acceptance_evidence: list[str] = Field(default_factory=list)
    checkpoint_id: str | None = None


WorkflowCallback = Callable[[WorkflowStepResource], WorkflowStepResult | Awaitable[WorkflowStepResult]]
CheckpointCallback = Callable[[WorkflowRunnerState], None | Awaitable[None]]


class WorkflowRunner:
    """Run exactly one workflow step and never synthesize completion.

    Step declarations are authoritative. A non-completed callback result leaves
    the active step unchanged, allowing callers to resume after checkpoints.
    """

    def __init__(
        self,
        workflow: WorkflowResource,
        state: WorkflowRunnerState | None = None,
        *,
        goal_id: str | None = None,
        run_id: str | None = None,
        checkpoint_store: WorkflowCheckpointStore | None = None,
        phase: WorkflowPhase = WorkflowPhase.IMPLEMENTATION,
    ) -> None:
        if not workflow.steps:
            raise ValueError("workflow requires at least one step")
        self.workflow = workflow
        self.state = state or WorkflowRunnerState()
        self.goal_id = goal_id or uuid4().hex[:8]
        self.run_id = run_id or uuid4().hex
        self.checkpoint_store = checkpoint_store
        self.phase = phase
        self._validate_state()

    @classmethod
    def from_checkpoint(
        cls, workflow: WorkflowResource, checkpoint: WorkflowCheckpoint, **kwargs: Any
    ) -> WorkflowRunner:
        """Restore runner progress from a persisted checkpoint."""
        state = WorkflowRunnerState(
            active_step=checkpoint.active_step if checkpoint.active_step is not None else len(workflow.steps),
            status=checkpoint.status,
            completed_steps=list(checkpoint.completed_steps),
            outputs={reference: None for reference in checkpoint.artifact_refs},
            acceptance_evidence=list(checkpoint.acceptance_evidence),
        )
        kwargs.setdefault("phase", checkpoint.phase)
        return cls(workflow, state, goal_id=checkpoint.goal_id, run_id=checkpoint.run_id, **kwargs)

    @property
    def done(self) -> bool:
        return self.state.status is WorkflowStatus.COMPLETED and self.state.active_step >= len(self.workflow.steps)

    def _validate_state(self) -> None:
        if self.state.active_step > len(self.workflow.steps):
            raise ValueError("active step is out of range")
        if len(set(self.state.completed_steps)) != len(self.state.completed_steps):
            raise ValueError("completed step indexes must be unique")
        if any(index < 0 or index >= len(self.workflow.steps) for index in self.state.completed_steps):
            raise ValueError("completed step index is out of range")

    async def run_step(
        self,
        callback: WorkflowCallback,
        *,
        inputs: Mapping[str, Any] | Iterable[str] | None = None,
        artifacts: Mapping[str, Any] | Iterable[str] | None = None,
        checkpoint: CheckpointCallback | None = None,
    ) -> WorkflowRunResult:
        """Invoke the callback once for the active step."""
        if not callable(callback):
            raise TypeError("step callback must be callable")
        if self.done:
            return WorkflowRunResult(status=WorkflowStatus.COMPLETED, step_index=None, reason="workflow is complete")
        if self.state.status in {WorkflowStatus.WAITING_USER, WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
            return WorkflowRunResult(
                status=self.state.status, step_index=self.state.active_step, reason=self.state.reason
            )
        step = self.workflow.steps[self.state.active_step]
        missing = self._missing_inputs(step, inputs or artifacts or {})
        if missing:
            return await self._stop(
                WorkflowStatus.BLOCKED, step, "missing required inputs: " + ", ".join(missing), missing, checkpoint
            )
        result = callback(step)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, WorkflowStepResult):
            raise TypeError("step callback must return WorkflowStepResult")
        if result.status is WorkflowStatus.COMPLETED:
            try:
                self._validate_output(step, result.output)
            except WorkflowGateError as exc:
                return await self._stop(WorkflowStatus.BLOCKED, step, str(exc), [], checkpoint)
            completed = [*self.state.completed_steps, self.state.active_step]
            next_status = (
                WorkflowStatus.COMPLETED
                if self.state.active_step + 1 >= len(self.workflow.steps)
                else WorkflowStatus.PENDING
            )
            if self.state.active_step < len(self.workflow.steps) and step.checkpoint.strip().casefold() in {
                "true",
                "user",
                "human",
                "checkpoint",
                "waiting_user",
            }:
                next_status = WorkflowStatus.WAITING_USER
            outputs = {**self.state.outputs, step.name: result.output}
            if step.output:
                outputs[step.output] = result.output
            self.state = self.state.model_copy(
                update={
                    "active_step": self.state.active_step + 1,
                    "status": next_status,
                    "completed_steps": completed,
                    "outputs": outputs,
                    "acceptance_evidence": [*self.state.acceptance_evidence, *result.evidence],
                    "reason": result.reason,
                }
            )
        else:
            self.state = self.state.model_copy(update={"status": result.status, "reason": result.reason})
        checkpoint_id = await self._persist(step, checkpoint)
        return WorkflowRunResult(
            status=self.state.status,
            step_index=step.index,
            output=result.output,
            reason=result.reason,
            acceptance_evidence=result.evidence,
            checkpoint_id=checkpoint_id,
        )

    run = run_step

    def resume(self) -> WorkflowRunnerState:
        """Explicitly resume a paused, blocked, or failed active step."""
        if self.done:
            return self.state.model_copy(deep=True)
        if self.state.status in {WorkflowStatus.WAITING_USER, WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
            self.state = self.state.model_copy(update={"status": WorkflowStatus.PENDING, "reason": ""})
        return self.state.model_copy(deep=True)

    async def persist_state(self) -> str | None:
        """Persist a command-boundary state change without invoking a callback.

        Pause and resume are CLI state changes, not workflow steps. Keeping this
        operation on the Runner prevents callers from rebuilding checkpoint
        payloads and accidentally losing completed-step history on recovery.
        """
        step = self.workflow.steps[min(self.state.active_step, len(self.workflow.steps) - 1)]
        return await self._persist(step, None)

    async def _stop(
        self,
        status: WorkflowStatus,
        step: WorkflowStepResource,
        reason: str,
        missing: list[str],
        checkpoint: CheckpointCallback | None,
    ) -> WorkflowRunResult:
        self.state = self.state.model_copy(update={"status": status, "reason": reason})
        checkpoint_id = await self._persist(step, checkpoint)
        return WorkflowRunResult(
            status=status, step_index=step.index, reason=reason, missing=missing, checkpoint_id=checkpoint_id
        )

    async def _persist(self, step: WorkflowStepResource, callback: CheckpointCallback | None) -> str | None:
        if callback:
            result = callback(self.state.model_copy(deep=True))
            if inspect.isawaitable(result):
                await result
        if self.checkpoint_store is None:
            return None
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=(
                f"{self.goal_id}-{self.run_id}-step-{step.index}-active-{self.state.active_step}-{self.state.status.value}"
            ),
            goal_id=self.goal_id,
            phase=self.phase,
            status=self.state.status,
            run_id=self.run_id,
            active_skill=self.workflow.name,
            active_step=self.state.active_step,
            artifact_refs=list(self.state.outputs),
            acceptance_evidence=list(self.state.acceptance_evidence),
            completed_steps=list(self.state.completed_steps),
            next_action=self.state.reason,
        )
        aggregate_status = self.state.status
        if aggregate_status is WorkflowStatus.COMPLETED and self.phase is not WorkflowPhase.DONE:
            aggregate_status = WorkflowStatus.RUNNING
        workflow_state = GoalWorkflowState(
            goal_id=self.goal_id,
            phase=self.phase,
            active_skill=self.workflow.name,
            active_step=self.state.active_step,
            status=aggregate_status,
            artifact_refs=list(self.state.outputs),
            blocked_reason=self.state.reason
            if self.state.status in {WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}
            else None,
            next_action=self.state.reason,
        )
        await self.checkpoint_store.save(checkpoint, workflow_state)
        return checkpoint.checkpoint_id

    @staticmethod
    def _missing_inputs(step: WorkflowStepResource, values: Mapping[str, Any] | Iterable[str]) -> list[str]:
        required = [item.strip() for item in re.split(r"[,\n]", step.input) if item.strip()]
        available = set(values)
        lowered = {str(key).lower() for key in available}
        return [item for item in required if item not in available and item.lower() not in lowered]

    @classmethod
    def validate_input(cls, step: WorkflowStepResource, values: Mapping[str, Any] | Iterable[str]) -> list[str]:
        """Return declared inputs absent from a step invocation."""
        return cls._missing_inputs(step, values)

    @staticmethod
    def validate_output(step: WorkflowStepResource, output: Any) -> None:
        """Validate a step output against its output and validation declarations."""
        WorkflowRunner._validate_output(step, output)

    @staticmethod
    def _validate_output(step: WorkflowStepResource, output: Any) -> None:
        if step.output and (output is None or output == ""):
            raise WorkflowGateError(f"step '{step.name}' requires output: {step.output}")
        text = output if isinstance(output, str) else ""
        if step.validation_rules:
            rules = step.validation_rules.casefold()
            if "given" in rules and not re.search(r"given.*when.*then", text, re.I | re.S):
                raise WorkflowGateError(f"step '{step.name}' output failed validation: {step.validation_rules}")
            for section in re.findall(r"section\s*:\s*([^,;]+)", rules):
                if not re.search(rf"^##\s+{re.escape(section.strip())}\s*$", text, re.I | re.M):
                    raise WorkflowGateError(f"step '{step.name}' output is missing section: {section.strip()}")
        if step.output and isinstance(output, Mapping):
            names = [item.strip() for item in re.split(r"[,\n]", step.output) if item.strip()]
            missing = [name for name in names if name not in output]
            if missing:
                raise WorkflowGateError("step output is missing: " + ", ".join(missing))
