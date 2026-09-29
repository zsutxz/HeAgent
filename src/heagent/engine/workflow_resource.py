"""Declarative workflow resource models consumed by the engine runtime."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkflowStepResource(BaseModel):
    """One Markdown workflow step and its declarative execution contract."""

    index: int
    name: str
    instructions: str
    input: str = ""
    output: str = ""
    next: str | None = None
    checkpoint: str = ""
    validation_rules: str = ""
    role: str = ""
    story_loop: str = ""
    max_parallel_stories: int = Field(default=1, ge=1, le=5)
    # Per-step iteration budget; 0 = inherit Settings.goal_max_iterations.
    max_iterations: int = Field(default=0, ge=0)
    frontmatter: dict[str, Any] = Field(default_factory=dict)


CheckpointMode = Literal["", "auto", "prompt"]
OpenQuestionMode = Literal["", "block", "default"]

# 声明词汇的单一真源：workflow 只能声明「跑哪些预检 / 展示哪些状态字段」，
# 具体实现由 ``goal/doctor.py`` 与 ``goal/status_view.py`` 的注册表提供（两处必须与这里一致）。
DoctorCheck = Literal["package", "required_resources", "roles", "checkpoint_dir", "templates"]
StatusField = Literal["step", "epic", "story", "reason", "failures", "decisions", "next"]

DOCTOR_CHECKS: tuple[DoctorCheck, ...] = (
    "package",
    "required_resources",
    "templates",
    "roles",
    "checkpoint_dir",
)
STATUS_FIELDS: tuple[StatusField, ...] = ("step", "epic", "story", "reason", "failures", "decisions", "next")


class WorkflowResource(BaseModel):
    """A workflow declaration with steps in execution order."""

    name: str
    instructions: str
    steps: list[WorkflowStepResource]
    entrypoint: str = ""
    on_create: str = "persist_goal_identity"
    step_executor: str = "subagent"
    # Empty means the workflow defers to GOAL_CHECKPOINT_MODE/settings.
    checkpoint_mode: CheckpointMode = ""
    # Empty means the workflow defers to GOAL_OPEN_QUESTION_MODE/settings.
    open_question_mode: OpenQuestionMode = ""
    # /goal run 单次连续推进的步数上限（声明优先；缺失用默认值）。
    max_rounds: int = 10
    # /goal auto 的默认 cron；空 = 用 CLI 内置默认。
    auto_schedule: str = ""
    # open_question_mode 各自对应的一段策略文案；空 = 用 CLI 内置默认。
    open_question_default: str = ""
    open_question_block: str = ""
    # 包内 ``prompt-template.md`` / ``gate-template.md`` 的正文；空 = 包未携带。
    # 必需性由 workflow frontmatter 的 ``required_resources`` 声明，声明后缺失即加载失败。
    prompt_template: str = ""
    gate_template: str = ""
    # 预检项与状态字段的声明清单（取值见 ``DOCTOR_CHECKS`` / ``STATUS_FIELDS``）。
    # 空 = 引擎默认集：老包不声明即零行为变化；未知取值由加载器 fail-loud。
    doctor_checks: list[DoctorCheck] = Field(default_factory=list)
    status_fields: list[StatusField] = Field(default_factory=list)
    frontmatter: dict[str, Any] = Field(default_factory=dict)
