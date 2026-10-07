"""Unified, read-only status projection for one Goal.

The CLI, the GUI and the cron entry points render this model instead of each reading
the runner state, the checkpoint JSON and the goal documents themselves: one
projection means one answer to "what is this Goal doing, why, and what happens next".

**Which fields are shown is declared, not hard-coded**: the workflow's ``status_fields``
frontmatter key picks an ordered subset of :data:`_FIELDS`; absent means
:data:`DEFAULT_STATUS_FIELDS`, so an existing package keeps its rendering.  The progress
line is a fixed baseline and never takes part in the declaration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from heagent.engine.checkpoint import WorkflowStatus
from heagent.engine.workflow_resource import (
    StatusField,  # noqa: TC001 - pydantic resolves the field annotation at class build
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from heagent.engine.workflow_resource import WorkflowResource
    from heagent.engine.workflow_runner import WorkflowRunnerState

# Story statuses that mean "this story needs a human before the workflow continues".
_FAILED_STORY_STATUSES = frozenset({"failed", "blocked"})


class GoalStatusView(BaseModel):
    """One Goal's current delivery state, projected from the runner and its checkpoints."""

    goal_id: str = ""
    workflow: str = ""
    status: WorkflowStatus = WorkflowStatus.PENDING
    active_step: int | None = None
    active_step_name: str = ""
    active_epic: str = ""
    active_story: str | None = None
    active_stories: list[str] = Field(default_factory=list)
    completed_steps: list[int] = Field(default_factory=list)
    completed_stories: list[str] = Field(default_factory=list)
    total_steps: int = 0
    story_statuses: dict[str, str] = Field(default_factory=dict)
    reason: str = ""
    recent_failures: list[str] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)
    recommended_commands: list[str] = Field(default_factory=list)
    # 渲染计划（workflow 声明的 ``status_fields``）；空 = 引擎默认集。
    fields: list[StatusField] = Field(default_factory=list)

    @property
    def progress(self) -> str:
        """``completed/total`` step progress."""
        return f"{len(self.completed_steps)}/{self.total_steps}"

    def render(self) -> list[str]:
        """Deterministic lines every entry point writes (the CLI routes them through ``_echo``).

        The first line is the fixed baseline every consumer can rely on; the rest follows
        the declared (or default) field order, and a field with nothing to report adds no
        line at all.
        """
        lines = [f"[goal] declarative progress: {self.progress} status={self.status.value} step={self.active_step}"]
        for name in self.fields or list(DEFAULT_STATUS_FIELDS):
            lines.extend(_FIELDS[name](self))
        return lines


def project_status_view(
    state: WorkflowRunnerState,
    workflow: WorkflowResource,
    *,
    goal_id: str = "",
    open_decisions: Sequence[str] = (),
    fields: Sequence[StatusField] = (),
) -> GoalStatusView:
    """Project the runner state (the single source of truth) into the shared model.

    Everything rendered here is a **persisted fact** (AD-15): the Epic comes from the runner
    state, where the story loop records it, so a status read touches no document and cannot
    show a hierarchy the checkpointed run never saw. ``open_decisions`` is the one injected
    input — it is a property of the decision log, not of the runner state.
    """
    step_name = workflow.steps[state.active_step].name if state.active_step < len(workflow.steps) else ""
    return GoalStatusView(
        goal_id=goal_id,
        workflow=workflow.name,
        status=state.status,
        active_step=state.active_step,
        active_step_name=step_name,
        active_epic=state.active_epic,
        active_story=state.active_story,
        # 串行化后「复数视图」至多单元素：由 active_story 现场派生（A26，字段已删除）。
        active_stories=[state.active_story] if state.active_story else [],
        completed_steps=sorted(state.completed_steps),
        completed_stories=list(state.completed_stories),
        total_steps=len(workflow.steps),
        story_statuses=dict(state.story_statuses),
        reason=state.reason,
        recent_failures=_recent_failures(state),
        open_decisions=list(open_decisions),
        recommended_commands=_recommended_commands(state),
        fields=list(fields),
    )


def _recent_failures(state: WorkflowRunnerState) -> list[str]:
    """Stories that need a human before the workflow can continue."""
    return [
        f"{story} ({status})"
        for story, status in sorted(state.story_statuses.items())
        if status.casefold() in _FAILED_STORY_STATUSES
    ]


def _recommended_commands(state: WorkflowRunnerState) -> list[str]:
    """Deterministic next actions for the current status, never a free-text suggestion."""
    if state.status is WorkflowStatus.WAITING_USER and state.awaiting_approval:
        # 审批门挂起（Story 51-5）：只有显式人工决策能推进，resume 不在其列（不能隐式批准）。
        return ["/goal approve", "/goal reject <原因>", "/goal amend <补充>", "/goal decisions"]
    match state.status:
        case WorkflowStatus.WAITING_USER:
            return ["/goal resume <answer>", "/goal status"]
        case WorkflowStatus.BLOCKED:
            return ["/goal resume <说明>", "/goal doctor"]
        case WorkflowStatus.FAILED:
            return ["/goal status", "/goal resume <说明>"]
        case WorkflowStatus.COMPLETED:
            return ["/goal status"]
        case _:
            return ["/goal next"]


def _line(label: str, value: str) -> list[str]:
    """One labelled line, or nothing when the field has no value (unknown stays unrendered)."""
    return [f"[goal] {label}: {value}"] if value else []


# 通用字段注册表：名字即 ``engine.workflow_resource.STATUS_FIELDS`` 的词汇；
# 每个条目对所有 workflow 成立（渲染既有事实），不得出现具体 Epic / 步骤的判断。
_FIELDS: dict[str, Callable[[GoalStatusView], list[str]]] = {
    "step": lambda view: _line("current step", view.active_step_name),
    "epic": lambda view: _line("current epic", view.active_epic),
    "story": lambda view: (
        _line("current stories", ", ".join(view.active_stories)) or _line("current story", view.active_story or "")
    ),
    "reason": lambda view: _line("reason", view.reason),
    "failures": lambda view: _line("recent failures", "; ".join(view.recent_failures)),
    "decisions": lambda view: _line("open decisions", "; ".join(view.open_decisions)),
    "next": lambda view: _line("next", " | ".join(view.recommended_commands)),
}

# 未声明 ``status_fields`` 的包渲染的默认集。
DEFAULT_STATUS_FIELDS: tuple[StatusField, ...] = ("step", "epic", "story", "reason", "failures", "decisions", "next")
