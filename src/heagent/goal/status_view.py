"""单个 Goal 的统一只读状态投影。

CLI、GUI 与 cron 入口都渲染这一模型，而不是各自去读 runner 状态、checkpoint JSON 与
goal 文档：一份投影意味着「这个 Goal 在做什么、为什么、接下来会怎样」只有一个答案。

**展示哪些字段是声明的，不是硬编码的**：workflow 的 ``status_fields`` frontmatter 键
挑选 :data:`_FIELDS` 的一个有序子集；缺失即 :data:`DEFAULT_STATUS_FIELDS`，因此既有技能包
的渲染保持不变。进度行是固定基线，永不参与声明。
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

# 需要人工介入才能继续的 Story 状态。
_FAILED_STORY_STATUSES = frozenset({"failed", "blocked"})


class GoalStatusView(BaseModel):
    """单个 Goal 的当前交付状态，由 runner 与其 checkpoint 投影而来。"""

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
        """``completed/total`` 的步骤进度。"""
        return f"{len(self.completed_steps)}/{self.total_steps}"

    def render(self) -> list[str]:
        """每个入口都写出的确定性行（CLI 经 ``_echo`` 路由它们）。

        第一行是每个消费方都能依赖的固定基线；其余按声明（或默认）的字段序输出，而
        没有内容可报的字段完全不新增行。
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
    """把 runner 状态（唯一真源）投影到共享模型。

    这里渲染的一切都是**已持久化的事实**（AD-15）：Epic 取自 runner 状态（story 循环在那里
    记录它），因此读状态不碰任何文档，也不可能显示出一个从未被 checkpoint 的 run 见过的层级。
    ``open_decisions`` 是唯一注入的输入——它是决策日志的属性，不是 runner 状态的属性。
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
        # 串行化后「复数视图」至多单元素：由 active_story 现场派生（字段已删除）。
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
    """需要人工介入才能继续工作流的 story。"""
    return [
        f"{story} ({status})"
        for story, status in sorted(state.story_statuses.items())
        if status.casefold() in _FAILED_STORY_STATUSES
    ]


def _recommended_commands(state: WorkflowRunnerState) -> list[str]:
    """当前状态下确定性的下一步动作，绝不是自由文本建议。"""
    if state.status is WorkflowStatus.WAITING_USER and state.awaiting_approval:
        # 审批门挂起：只有显式人工决策能推进，resume 不在其列（不能隐式批准）。
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
    """一条带标签的行；字段无值时什么都不输出（未知不渲染）。"""
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
