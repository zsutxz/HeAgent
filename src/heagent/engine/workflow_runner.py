"""Deterministic one-step runner for declarative Markdown workflows."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from heagent.engine.checkpoint import (
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.events.protocol import error_kind_for
from heagent.pub.safe_logging import safe_log

logger = logging.getLogger(__name__)


def _elapsed_ms(started: float) -> int:
    """``perf_counter`` 起点 → 整数毫秒（下取整，非负）。"""
    return max(int((time.perf_counter() - started) * 1000), 0)


def _emit_step_event(
    emit: Callable[..., None] | None,
    kind: str,
    *,
    step: WorkflowStepResource,
    story: Any,
    duration_ms: int = 0,
    error_kind: str = "",
    **extra: Any,
) -> None:
    """步骤粒度观测事件（Phase 5 C1）：emit 异常隔离，可观测性不得改变业务控制流。

    ``duration_ms`` / ``error_kind`` 进 details，由传输层 ``from_engine_event`` 提升到
    RunEvent 顶层（EngineEvent 模型与 GUI 消费面不动）。
    """
    if emit is None:
        return
    payload: dict[str, Any] = {
        "step": step.name,
        "story": story.id if story is not None else "",
        "duration_ms": duration_ms,
        "error_kind": error_kind,
        **extra,
    }
    try:
        emit(kind, details=payload)
    except Exception:  # noqa: BLE001 - 观测失败仅告警
        safe_log(logger, logging.WARNING, "workflow step event %r emit failed; ignored", kind, exc_info=True)


_SECTION_RULE = re.compile(r"section\s*:\s*([^,;]+)", re.IGNORECASE)


def required_sections(validation_rules: str | None) -> list[str]:
    """Return the ``section:`` headings a step output must contain.

    Single parser shared by the post-step output gate and the pre-step prompt: an
    executor has to be told the exact headings it will be judged on, otherwise a
    long step can finish all its work and still be blocked on a heading it never
    saw.
    """
    if not validation_rules:
        return []
    return [item.strip() for item in _SECTION_RULE.findall(validation_rules) if item.strip()]


class WorkflowGateError(ValueError):
    """Raised when a step cannot satisfy its declared contract."""


class StorySpec(BaseModel):
    """One story in a story-loop step, parsed from a story-list artifact."""

    id: str = Field(min_length=1)
    summary: str = ""
    epic: str = ""


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
_EPIC_HEADING = re.compile(
    r"^#{1,6}\s+(?:epic[-_ ]*(?:e[-_ ]?)?|e[-_ ]?)(?P<epic>\d+)(?=$|[\s:：\-—.．])",
    re.IGNORECASE,
)
_EPIC_FIELD = re.compile(
    r"(?:父\s*Epic|parent[-_ ]*epic|epic_id)\s*\**\s*[:：]\s*\**\s*(?P<epic>e[-_ ]?\d+|\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _normalize_story_id(raw: str) -> str:
    match = _STORY_ID.fullmatch(raw.strip())
    if match is None:
        raise WorkflowGateError(f"invalid story id: {raw!r}")
    return f"S-{int(match.group(1))}"


def _normalize_epic_id(raw: str) -> str:
    """Normalize an Epic reference (``E1`` / ``e 1`` / ``epic 1``) to ``E1``."""
    digits = re.search(r"\d+", raw or "")
    return f"E{int(digits.group(0))}" if digits is not None else (raw or "").strip()


def _story_sort_key(spec: StorySpec) -> int:
    match = re.fullmatch(r"S-(\d+)", spec.id)
    return int(match.group(1)) if match else 0


def _is_epic_reference(cell: str) -> bool:
    """True when a table cell is a bare Epic reference (``E1`` / ``E-1`` / ``Epic 1``)."""
    return bool(re.fullmatch(r"(?:epic[-_ ]*(?:e[-_ ]?)?|e[-_ ]?)\d+", cell.strip(), re.IGNORECASE))


def _story_table_entry(stripped: str) -> tuple[str, str, str] | None:
    """Parse one table row into ``(id, summary, epic_hint)``; ``None`` for a non-story row.

    An overview table such as ``| S-1 | E1 | P0 | none | <title> |`` puts the Epic in
    the second column and the human summary in the last one, so the raw second cell
    must not be mistaken for the story title.
    """
    match = _STORY_TABLE.match(stripped)
    if match is None:
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    summary = match.group("summary").strip()
    epic_hint = ""
    if len(cells) >= 3 and _is_epic_reference(cells[1]):
        epic_hint = _normalize_epic_id(cells[1])
        summary = next((cell for cell in reversed(cells[2:]) if cell), summary)
    return match.group("id"), summary, epic_hint


def parse_story_list(text: str) -> list[StorySpec]:
    """Extract an ordered story list from Markdown.

    Recognizes three common shapes so a step may consume an Epic proposal,
    a dedicated story checklist, or a story table:

    * ``### S-1 Scene rendering`` (heading)
    * ``- [ ] S-1 Scene rendering`` (list/checklist item)
    * ``| S-1 | Scene rendering |`` (table row)

    Shapes are ranked for a repeated id: a story heading outranks a list item,
    which outranks a table row. A document therefore still keeps every story it
    declares (including table-only rows) while an overview table such as
    ``| S-1 | E1 | P0 | none | <title> |`` can no longer overwrite the titles and
    Epics owned by the story sections. Story ids normalize to ``S-<n>`` and are
    deduplicated by id, then sorted by their numeric suffix. Non-story rows
    (e.g. Epic ids such as ``E-1``) are ignored.

    Epic grouping is optional: a story inherits the Epic declared by the nearest
    preceding Epic heading (``## E1 ...`` / ``## Epic 1 ...``), and an explicit
    ``- **父 Epic**: E1`` field inside the story block wins over that heading. A
    source without grouping keeps the flat behaviour (``epic`` stays empty).
    """
    if not isinstance(text, str) or not text.strip():
        return []
    lines = text.splitlines()
    epic_headings: list[tuple[int, str]] = []
    epic_fields: list[tuple[int, str]] = []
    stories: list[tuple[int, str, str, str]] = []
    ranks: dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        epic_match = _EPIC_HEADING.match(stripped)
        if epic_match is not None:
            epic_headings.append((index, _normalize_epic_id(epic_match.group("epic"))))
            continue
        entry: tuple[str, str, str, int] | None = None
        heading_match = _STORY_HEADING.match(stripped)
        if heading_match is not None:
            entry = (heading_match.group("id"), heading_match.group("summary").strip(), "", 0)
        else:
            list_match = _STORY_LIST.match(stripped)
            if list_match is not None:
                entry = (list_match.group("id"), list_match.group("summary").strip(), "", 1)
            else:
                table_entry = _story_table_entry(stripped)
                entry = (*table_entry, 2) if table_entry is not None else None
        if entry is not None:
            try:
                story_id = _normalize_story_id(entry[0])
            except WorkflowGateError:
                story_id = ""
            if story_id:
                rank = ranks.get(story_id)
                if rank is None:
                    ranks[story_id] = entry[3]
                    stories.append((index, story_id, entry[1], entry[2]))
                elif entry[3] < rank:
                    ranks[story_id] = entry[3]
                    position = next(pos for pos, item in enumerate(stories) if item[1] == story_id)
                    stories[position] = (index, story_id, entry[1], entry[2])
                continue
        field_match = _EPIC_FIELD.search(stripped)
        if field_match is not None:
            epic_fields.append((index, _normalize_epic_id(field_match.group("epic"))))
    specs: list[StorySpec] = []
    for position, (index, story_id, summary, epic_hint) in enumerate(stories):
        end = stories[position + 1][0] if position + 1 < len(stories) else len(lines)
        epic = epic_hint or next((value for field_index, value in epic_fields if index < field_index < end), "")
        if not epic:
            epic = next((value for heading_index, value in reversed(epic_headings) if heading_index < index), "")
        specs.append(StorySpec(id=story_id, summary=summary, epic=epic))
    return sorted(specs, key=_story_sort_key)


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
    active_stories: list[str] = Field(default_factory=list)
    story_statuses: dict[str, str] = Field(default_factory=dict)


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
StoryWorkflowCallback = Callable[[WorkflowStepResource, StorySpec], WorkflowStepResult | Awaitable[WorkflowStepResult]]
CheckpointCallback = Callable[[WorkflowRunnerState], Awaitable[None] | None]


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
            active_stories=list(
                checkpoint.active_stories or ([checkpoint.active_story] if checkpoint.active_story else [])
            ),
            story_statuses=dict(checkpoint.story_statuses),
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
        emit: Callable[..., None] | None = None,
    ) -> WorkflowRunResult:
        """Invoke the callback once for the active step (or the active story).

        ``emit``（Phase 5 C1，可选注入）：``emit(kind, *, details=None)`` 形状的观测端口，
        步骤粒度发 ``workflow_step_started/completed/failed``（``duration_ms`` / ``error_kind``
        经 details 由传输层提升）。缺省 ``None`` = 零行为变化（既有调用方/测试不动）；
        emit 内部异常隔离（对齐 sink 先例：可观测性不得改变业务控制流）。
        """
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
        active_story: StorySpec | None = None
        if is_story_loop:
            if step.max_parallel_stories > 1 and story_specs and all(story.epic for story in story_specs):
                started = time.perf_counter()
                _emit_step_event(emit, "workflow_step_started", step=step, story=None)
                try:
                    result = await self._run_story_batch(callback, step, story_specs, checkpoint, emit=emit)
                except BaseException as exc:
                    _emit_step_event(
                        emit,
                        "workflow_step_failed",
                        step=step,
                        story=None,
                        duration_ms=_elapsed_ms(started),
                        error_kind=error_kind_for(exc),
                        error=str(exc),
                    )
                    raise
                _emit_step_event(
                    emit,
                    "workflow_step_completed",
                    step=step,
                    story=None,
                    duration_ms=_elapsed_ms(started),
                    result=result.status.value,
                )
                return result
            active_story = story_specs[self.state.story_index]
            self.state = self.state.model_copy(
                update={"active_story": active_story.id, "active_stories": [active_story.id]}
            )

        started = time.perf_counter()
        _emit_step_event(emit, "workflow_step_started", step=step, story=active_story)
        try:
            result = self._invoke_callback(callback, step, active_story)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, WorkflowStepResult):
                raise TypeError("step callback must return WorkflowStepResult")
        except BaseException as exc:
            _emit_step_event(
                emit,
                "workflow_step_failed",
                step=step,
                story=active_story,
                duration_ms=_elapsed_ms(started),
                error_kind=error_kind_for(exc),
                error=str(exc),
            )
            raise
        _emit_step_event(
            emit,
            "workflow_step_completed",
            step=step,
            story=active_story,
            duration_ms=_elapsed_ms(started),
            result=result.status.value,
        )

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

    async def _run_story_batch(
        self,
        callback: WorkflowCallback | StoryWorkflowCallback,
        step: WorkflowStepResource,
        story_specs: list[StorySpec],
        checkpoint: CheckpointCallback | None,
        emit: Callable[..., None] | None = None,
    ) -> WorkflowRunResult:
        """Run one bounded batch from the first incomplete Epic only.

        事件粒度：批级 started/completed 由 :meth:`run_step` 发（``story`` 为空，代表
        「这一步」）；**批内每个 story** 另发一组 ``workflow_step_started/completed/
        failed``（带自己的 ``story`` 与 ``duration_ms``）——否则并发批次下故事轨迹
        只剩「整批一条」，消费方（GUI / replay）无法定位单个 story 的耗时与失败。
        """
        completed = set(self.state.completed_stories)
        remaining = [story for story in story_specs if story.id not in completed]
        if not remaining:
            combined = "\n\n---\n\n".join(str(value) for value in self.state.story_outputs.values())
            self.state = self.state.model_copy(update=self._step_advance_update(step, combined))
            checkpoint_id = await self._persist(step, checkpoint)
            return WorkflowRunResult(status=self.state.status, step_index=step.index, checkpoint_id=checkpoint_id)
        epic = remaining[0].epic
        if not epic:
            raise WorkflowGateError("parallel story execution requires every scheduled story to declare an Epic")
        batch = [story for story in remaining if story.epic == epic][: step.max_parallel_stories]
        active_ids = [story.id for story in batch]
        statuses = {**self.state.story_statuses, **{story_id: "running" for story_id in active_ids}}
        self.state = self.state.model_copy(
            update={"active_story": active_ids[0], "active_stories": active_ids, "story_statuses": statuses}
        )
        await self._persist(step, checkpoint)

        async def execute(story: StorySpec) -> tuple[StorySpec, WorkflowStepResult | BaseException]:
            started = time.perf_counter()
            _emit_step_event(emit, "workflow_step_started", step=step, story=story)
            try:
                result = self._invoke_callback(callback, step, story)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, WorkflowStepResult):
                    raise TypeError("story callback must return WorkflowStepResult")
            except Exception as exc:  # isolate one Story failure from its batch
                _emit_step_event(
                    emit,
                    "workflow_step_failed",
                    step=step,
                    story=story,
                    duration_ms=_elapsed_ms(started),
                    error_kind=error_kind_for(exc),
                    error=str(exc),
                )
                return story, exc
            _emit_step_event(
                emit,
                "workflow_step_completed",
                step=step,
                story=story,
                duration_ms=_elapsed_ms(started),
                result=result.status.value,
            )
            return story, result

        results = await asyncio.gather(*(execute(story) for story in batch))
        completed_ids: list[str] = []
        story_outputs = dict(self.state.story_outputs)
        evidence = list(self.state.acceptance_evidence)
        failure_reason = ""
        for story, result in results:
            if isinstance(result, BaseException):
                statuses[story.id] = "failed"
                failure_reason = f"{story.id}: {result}"
                continue
            if result.status is not WorkflowStatus.COMPLETED:
                statuses[story.id] = result.status.value
                failure_reason = result.reason or f"{story.id}: {result.status.value}"
                continue
            try:
                self._validate_output(step, result.output)
            except WorkflowGateError as exc:
                statuses[story.id] = "failed"
                failure_reason = f"{story.id}: {exc}"
                continue
            statuses[story.id] = "completed"
            completed_ids.append(story.id)
            story_outputs[story.id] = result.output
            evidence.extend(result.evidence)
        all_completed = set(completed_ids)
        completed_stories = [*self.state.completed_stories, *[story.id for story in batch if story.id in all_completed]]
        active = [story.id for story in batch if statuses.get(story.id) == "running"]
        update: dict[str, Any] = {
            "completed_stories": completed_stories,
            "story_outputs": story_outputs,
            "acceptance_evidence": evidence,
            "active_stories": active,
            "active_story": active[0] if active else None,
            "story_statuses": statuses,
        }
        if failure_reason:
            update.update({"status": WorkflowStatus.FAILED, "reason": failure_reason})
        elif len(completed_stories) >= len(story_specs):
            combined = "\n\n---\n\n".join(str(value) for value in story_outputs.values())
            update.update(self._step_advance_update(step, combined))
            update.update({"active_stories": [], "active_story": None})
        else:
            update["status"] = (
                WorkflowStatus.WAITING_USER if self._checkpoint_declared(step) else WorkflowStatus.PENDING
            )
            update["reason"] = ""
        self.state = self.state.model_copy(update=update)
        checkpoint_id = await self._persist(step, checkpoint)
        return WorkflowRunResult(
            status=self.state.status,
            step_index=step.index,
            output={story_id: story_outputs[story_id] for story_id in completed_ids},
            reason=self.state.reason,
            checkpoint_id=checkpoint_id,
            story_id=completed_ids[0] if completed_ids else batch[0].id,
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
                    "active_stories": [],
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
            "active_stories": [next_story.id],
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
            if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD, parameter.VAR_POSITIONAL)
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
            active_stories=list(self.state.active_stories),
            story_statuses=dict(self.state.story_statuses),
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
            active_stories=list(self.state.active_stories),
            story_statuses=dict(self.state.story_statuses),
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
        """Build the idempotency key for one logical checkpoint position.

        The id must be a total function of the position, because the store treats
        a second write of the same id with different content as a conflict. For a
        story-loop step the position includes the active story: the same
        ``(step, story_index)`` slot legitimately holds two snapshots -- "the step
        has not entered its story yet" (no active story, written while the previous
        step advanced into this one) and "story S-1 is pending" (written when the
        runner resumed into an interrupted story). Omitting the story made the
        second write collide with the first and raise a bogus conflict.
        """
        story_part = ""
        if self._is_story_step(step):
            story_part = f"-story-{self.state.story_index}"
            if step.max_parallel_stories > 1:
                story_part += f"-parallel-{len(self.state.completed_stories)}"
            # Story ids are normalized upstream; sanitize defensively so a
            # hand-built spec can never produce a path-unsafe checkpoint id.
            label = re.sub(r"[^0-9A-Za-z]+", "-", self.state.active_story or "").strip("-")
            if label:
                story_part += f"-{label}"
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
            for section in required_sections(step.validation_rules):
                if not re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.I | re.M):
                    present = [item.strip() for item in re.findall(r"^##\s+(.+?)\s*$", text, re.M)][:8]
                    found = ", ".join(present) if present else "none"
                    raise WorkflowGateError(
                        f"step '{step.name}' output is missing section: {section} (present H2 headings: {found})"
                    )
        if step.output and isinstance(output, Mapping):
            names = WorkflowRunner._references(step.output)
            missing = [name for name in names if name not in output]
            if missing:
                raise WorkflowGateError("step output is missing: " + ", ".join(missing))
