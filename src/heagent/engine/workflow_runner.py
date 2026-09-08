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


class StorySpec(BaseModel):
    """One story in a story-loop step, parsed from a story-list artifact."""

    id: str = Field(min_length=1)
    summary: str = ""


_STORY_ID = re.compile(r"^(?:story|s)[-_ ]?(\d+)$", re.IGNORECASE)
_STORY_HEADING = re.compile(
    r"^#{1,6}\s+(?P<id>(?:story|s)[-_ ]?\d+)\s*[:：\-—]?\s*(?P<summary>.*)$",
    re.IGNORECASE,
)
_STORY_LIST = re.compile(
    r"^[-*+]\s+(?:\[[ xX]\]\s+)?(?P<id>(?:story|s)[-_ ]?\d+)\s*[:：\-—]?\s*(?P<summary>.*)$",
    re.IGNORECASE,
)
_STORY_TABLE = re.compile(
    r"^\|\s*(?P<id>(?:story|s)[-_ ]?\d+)\s*\|\s*(?P<summary>.*?)\s*\|",
    re.IGNORECASE,
)


def _normalize_story_id(raw: str) -> str:
    match = _STORY_ID.fullmatch(raw.strip())
    if match is None:
        raise WorkflowGateError(f"invalid story id: {raw!r}")
    return f"S-{int(match.group(1))}"


def _story_sort_key(spec: StorySpec) -> int:
    match = re.fullmatch(r"S-(\d+)", spec.id)
    return int(match.group(1)) if match else 0


def parse_story_list(text: str) -> list[StorySpec]:
    """Extract an ordered story list from Markdown.

    Recognizes three common shapes so a step may consume an Epic proposal,
    a dedicated story checklist, or a story table:

    * ``### S-1 Scene rendering`` (heading)
    * ``- [ ] S-1 Scene rendering`` (list/checklist item)
    * ``| S-1 | Scene rendering |`` (table row)

    Story ids normalize to ``S-<n>`` and are deduplicated by id, then sorted by
    their numeric suffix. Non-story rows (e.g. Epic ids such as ``E-1``) are
    ignored.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    seen: dict[str, StorySpec] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in (_STORY_HEADING, _STORY_LIST, _STORY_TABLE):
            match = pattern.match(stripped)
            if match is None:
                continue
            try:
                story_id = _normalize_story_id(match.group("id"))
            except WorkflowGateError:
                continue
            if story_id not in seen:
                seen[story_id] = StorySpec(id=story_id, summary=match.group("summary").strip())
            break
    return sorted(seen.values(), key=_story_sort_key)


class WorkflowRunnerState(BaseModel):
    """Serializable progress for a declarative workflow."""

    active_step: int = Field(default=0, ge=0)
    status: WorkflowStatus = WorkflowStatus.PENDING
    completed_steps: list[int] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    acceptance_evidence: list[str] = Field(default_factory=list)
    reason: str = ""
    active_story: str | None = None
    story_index: int = Field(default=0, ge=0)
    completed_stories: list[str] = Field(default_factory=list)
    story_outputs: dict[str, Any] = Field(default_factory=dict)


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
    story_id: str | None = None
    story_index: int | None = None


WorkflowCallback = Callable[[WorkflowStepResource], WorkflowStepResult | Awaitable[WorkflowStepResult]]
StoryWorkflowCallback = Callable[
    [WorkflowStepResource, StorySpec], WorkflowStepResult | Awaitable[WorkflowStepResult]
]
CheckpointCallback = Callable[[WorkflowRunnerState], None | Awaitable[None]]


class WorkflowRunner:
    """Run exactly one workflow step and never synthesize completion.

    Step declarations are authoritative. A non-completed callback result leaves
    the active step unchanged, allowing callers to resume after checkpoints.

    A step may declare ``story_loop: <artifact>``; such a step expands into one
    callback invocation per story (each an independently checkpointable
    increment), advancing the step only after every story has completed.
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
            outputs=(
                dict(checkpoint.outputs)
                if checkpoint.outputs
                else {reference: None for reference in checkpoint.artifact_refs}
            ),
            acceptance_evidence=list(checkpoint.acceptance_evidence),
            reason=checkpoint.next_action,
            active_story=checkpoint.active_story,
            story_index=checkpoint.story_index if checkpoint.story_index is not None else 0,
            completed_stories=list(checkpoint.completed_stories),
            story_outputs=dict(checkpoint.story_outputs),
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
        if len(set(self.state.completed_stories)) != len(self.state.completed_stories):
            raise ValueError("completed story ids must be unique")

    async def run_step(
        self,
        callback: WorkflowCallback | StoryWorkflowCallback,
        *,
        inputs: Mapping[str, Any] | Iterable[str] | None = None,
        artifacts: Mapping[str, Any] | Iterable[str] | None = None,
        checkpoint: CheckpointCallback | None = None,
        stories: Iterable[StorySpec] | None = None,
    ) -> WorkflowRunResult:
        """Invoke the callback once for the active step (or the active story)."""
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
        is_story_loop = self._is_story_step(step)
        try:
            story_specs = self._resolve_stories(step, stories)
        except WorkflowGateError as exc:
            return await self._stop(WorkflowStatus.BLOCKED, step, str(exc), [], checkpoint)
        active_story = story_specs[self.state.story_index] if is_story_loop else None
        if is_story_loop:
            self.state = self.state.model_copy(update={"active_story": active_story.id})

        result = self._invoke_callback(callback, step, active_story)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, WorkflowStepResult):
            raise TypeError("step callback must return WorkflowStepResult")

        executed_story_id: str | None = None
        executed_story_index: int | None = None
        if result.status is WorkflowStatus.COMPLETED:
            try:
                self._validate_output(step, result.output)
            except WorkflowGateError as exc:
                return await self._stop(WorkflowStatus.BLOCKED, step, str(exc), [], checkpoint)
            executed_story_id = active_story.id if active_story is not None else None
            executed_story_index = self.state.story_index if is_story_loop else None
            update: dict[str, Any] = {
                "acceptance_evidence": [*self.state.acceptance_evidence, *result.evidence],
            }
            if is_story_loop:
                update.update(self._story_advance_update(step, story_specs, result.output))
            else:
                update.update(self._step_advance_update(step, result.output))
            self.state = self.state.model_copy(update=update)
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
            story_id=executed_story_id,
            story_index=executed_story_index,
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

    def _step_advance_update(self, step: WorkflowStepResource, output: Any) -> dict[str, Any]:
        completed = [*self.state.completed_steps, self.state.active_step]
        next_status = (
            WorkflowStatus.COMPLETED
            if self.state.active_step + 1 >= len(self.workflow.steps)
            else WorkflowStatus.PENDING
        )
        if self.state.active_step + 1 < len(self.workflow.steps) and self._checkpoint_declared(step):
            next_status = WorkflowStatus.WAITING_USER
        outputs = {**self.state.outputs, step.name: output}
        for reference in self._references(step.output):
            outputs[reference] = output
        return {
            "active_step": self.state.active_step + 1,
            "status": next_status,
            "completed_steps": completed,
            "outputs": outputs,
        }

    def _story_advance_update(
        self, step: WorkflowStepResource, story_specs: list[StorySpec], output: Any
    ) -> dict[str, Any]:
        current = story_specs[self.state.story_index]
        completed_stories = [*self.state.completed_stories, current.id]
        story_outputs = {**self.state.story_outputs, current.id: output}
        if self.state.story_index + 1 >= len(story_specs):
            combined = "\n\n---\n\n".join(
                str(value) for value in story_outputs.values() if value is not None and str(value) != ""
            )
            update = self._step_advance_update(step, combined)
            update.update(
                {
                    "active_story": None,
                    "story_index": 0,
                    "completed_stories": [],
                    "story_outputs": {},
                }
            )
            return update
        next_story = story_specs[self.state.story_index + 1]
        next_status = WorkflowStatus.WAITING_USER if self._checkpoint_declared(step) else WorkflowStatus.PENDING
        return {
            "story_index": self.state.story_index + 1,
            "status": next_status,
            "completed_stories": completed_stories,
            "story_outputs": story_outputs,
            "active_story": next_story.id,
        }

    def _resolve_stories(self, step: WorkflowStepResource, stories: Iterable[StorySpec] | None) -> list[StorySpec]:
        if not self._is_story_step(step):
            return []
        specs = list(stories or [])
        if not specs:
            raise WorkflowGateError(f"story-loop step '{step.name}' requires a story list")
        if self.state.story_index >= len(specs):
            raise WorkflowGateError(
                f"story index {self.state.story_index} is out of range for {len(specs)} story/stories"
            )
        return specs

    @staticmethod
    def _is_story_step(step: WorkflowStepResource) -> bool:
        return bool(step.story_loop and step.story_loop.strip())

    @staticmethod
    def _invoke_callback(callback: Callable[..., Any], step: WorkflowStepResource, story: StorySpec | None) -> Any:
        if story is not None:
            if not WorkflowRunner._accepts_story(callback):
                raise TypeError("story-loop step callback must accept (step, story)")
            return callback(step, story)
        return callback(step)

    @staticmethod
    def _accepts_story(callback: Callable[..., Any]) -> bool:
        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            return False
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD, parameter.VAR_POSITIONAL)
        ]
        return len(positional) >= 2

    @staticmethod
    def _checkpoint_declared(step: WorkflowStepResource) -> bool:
        return step.checkpoint.strip().casefold() in {"true", "user", "human", "checkpoint", "waiting_user"}

    async def _persist(self, step: WorkflowStepResource, callback: CheckpointCallback | None) -> str | None:
        if callback:
            result = callback(self.state.model_copy(deep=True))
            if inspect.isawaitable(result):
                await result
        if self.checkpoint_store is None:
            return None
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=self._checkpoint_id(step),
            goal_id=self.goal_id,
            phase=self.phase,
            status=self.state.status,
            run_id=self.run_id,
            active_skill=self.workflow.name,
            active_step=self.state.active_step,
            active_story=self.state.active_story,
            story_index=self.state.story_index if self._is_story_step(step) else None,
            completed_stories=list(self.state.completed_stories),
            story_outputs=dict(self.state.story_outputs),
            artifact_refs=list(self.state.outputs),
            outputs=dict(self.state.outputs),
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
            active_story=self.state.active_story,
            status=aggregate_status,
            artifact_refs=list(self.state.outputs),
            blocked_reason=self.state.reason
            if self.state.status in {WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}
            else None,
            next_action=self.state.reason,
        )
        await self.checkpoint_store.save(checkpoint, workflow_state)
        return checkpoint.checkpoint_id

    def _checkpoint_id(self, step: WorkflowStepResource) -> str:
        story_part = f"-story-{self.state.story_index}" if self._is_story_step(step) else ""
        return (
            f"{self.goal_id}-{self.run_id}-step-{step.index}{story_part}"
            f"-active-{self.state.active_step}-{self.state.status.value}"
        )

    @staticmethod
    def _missing_inputs(step: WorkflowStepResource, values: Mapping[str, Any] | Iterable[str]) -> list[str]:
        required = WorkflowRunner._references(step.input)
        available = set(values)
        lowered = {str(key).lower() for key in available}
        return [item for item in required if item not in available and item.lower() not in lowered]

    @staticmethod
    def _references(declaration: str) -> list[str]:
        """Parse the workflow's explicit comma/newline-delimited artifact references."""
        return [item.strip() for item in re.split(r"[,\n]", declaration) if item.strip()]

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
            names = WorkflowRunner._references(step.output)
            missing = [name for name in names if name not in output]
            if missing:
                raise WorkflowGateError("step output is missing: " + ", ".join(missing))
