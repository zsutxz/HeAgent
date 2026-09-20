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
    frontmatter: dict[str, Any] = Field(default_factory=dict)
