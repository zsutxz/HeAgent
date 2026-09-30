"""Declarative workflow resource models consumed by the engine runtime.

也承载 ``validation:`` 词汇的两条**单一真源**实现（:func:`section_titles` 与
:func:`ensure_workspace_relative_path`）：``workflow_runner`` 的既有文本门禁与
``goal/workflow_loader`` 的子句解析共用，两处解析永不漂移。
"""

from __future__ import annotations

import re
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ``section:`` 提取的单一真源（大小写不敏感、值到 ``,`` / ``;`` 为止）——与历史
# ``workflow_runner._SECTION_RULE`` 逐字同语义；文本门禁与子句模型都从这里取。
_SECTION_CLAUSE = re.compile(r"section\s*:\s*([^,;]+)", re.IGNORECASE)


def section_titles(validation_rules: str | None) -> list[str]:
    """全部 ``section: <标题>``（含普通文本里的内嵌形态），既有文本门禁的原语义。"""
    if not validation_rules:
        return []
    return [item.strip() for item in _SECTION_CLAUSE.findall(validation_rules) if item.strip()]


def output_contains_section(text: str, section: str) -> bool:
    """Whether ``text`` carries the ``## <section>`` heading（文本门禁判定的单一真源）.

    ``WorkflowRunner`` 的步骤输出门禁与 ``goal/quality_gates`` 的 ``/goal verify`` 复验共用
    此判定，两处永不漂移。
    """
    return re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.I | re.M) is not None


# Windows 盘符**相对**路径（``C:foo``）对 PureWindowsPath 不是 absolute，但指向的是
# 「该盘当前目录」——工作区相对性声明里同样不允许。
_DRIVE_RELATIVE = re.compile(r"^[A-Za-z]:")


def ensure_workspace_relative_path(value: str) -> str:
    """Raise ``ValueError`` unless ``value`` names a path inside the workspace.

    artifact / git 子句值的单一守卫：绝对路径（POSIX / Windows 两口径）、盘符相对路径、
    含 ``..`` 段的逃逸路径一律拒绝。:mod:`heagent.goal.workflow_loader` 把它包成
    ``SkillWorkflowError``，:class:`StepValidationClauses` 的模型校验器直接用它——两条
    构造路径同规，绕过 loader 直接构造模型也逃不掉。
    """
    if (
        not value
        or _DRIVE_RELATIVE.match(value) is not None
        or any(parser(value).is_absolute() for parser in (PurePath, PurePosixPath, PureWindowsPath))
        or any(".." in parser(value).parts for parser in (PurePath, PurePosixPath, PureWindowsPath))
    ):
        raise ValueError(f"must be a workspace-relative path: {value!r}")
    return value


def _relative_workspace_paths(values: list[str]) -> list[str]:
    """``field_validator`` 共用体：逐项过 :func:`ensure_workspace_relative_path`。"""
    for value in values:
        ensure_workspace_relative_path(value)
    return values


class StepValidationClauses(BaseModel):
    """One step's parsed ``validation:`` evidence clauses（声明词汇的单一真源）.

    ``validation_rules`` keeps the raw declared string (the text gate and the gate
    prompt still read it verbatim); this model is its typed view. Clause syntax lives in
    ``goal/workflow_loader``（声明 → 模型），load 时在那里强制词汇表（unknown clause
    names fail at load time）——直接构造本模型也受 :func:`ensure_workspace_relative_path`
    同规约束，但不重复做子句名识别。

    「老包零行为变化」的准确边界：步骤声明里**没有** ``<Word>:`` 形态的段时完全不变
    （纯文本门禁照旧）；形如 ``coverage: 85%`` 或 ``subsection: x`` 的段首单词冒号会被
    当作未知子句而在加载期 fail-loud——这是「未知子句不静默忽略」的直接后果。
    Every list empty = the step declared no evidence clause.
    """

    sections: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    git_paths: list[str] = Field(default_factory=list)
    # 命名质量门：只存声明的名字。**名字的注册表校验由加载器接管**（goal/workflow_loader
    # 经 goal/quality_gates 的宿主注册表校验，未注册名字加载期 fail-loud，Story 51-4）；
    # 模型只承载声明，绕过 loader 直构造模型由求值器兜底显性失败。
    gates: list[str] = Field(default_factory=list)

    @field_validator("artifacts", "git_paths")
    @classmethod
    def _paths_stay_inside_the_workspace(cls, values: list[str]) -> list[str]:
        return _relative_workspace_paths(values)

    @property
    def declared(self) -> bool:
        """True when any evidence clause is present on this step."""
        return bool(self.sections or self.commands or self.artifacts or self.git_paths or self.gates)


# ``approval:`` 的关键词词汇（单一真源）：步骤只能声明「要不要人工确认」，合法关键词只有
# ``required``，其后可带一句给人读的说明（``approval: required 架构冻结前需人工确认``）。
# 未声明 = 该步不需要人工确认（老包零行为变化）；其余取值由加载器（goal/workflow_loader）
# 加载期 fail-loud。声明里只有「要不要」，没有步骤名 / 步骤序号（AD-13）。
APPROVAL_KEYWORDS: tuple[str, ...] = ("required",)


class StepApproval(BaseModel):
    """One step's parsed ``approval:`` declaration（声明词汇的类型视图）.

    ``required`` = 该步到达检查点时挂起等一个人工决策，只有 approve / reject / amend 能推进；
    ``note`` 是声明携带的一句说明，原样进入审批提示文案。语法解析与非法值报错在
    ``goal/workflow_loader``（声明 → 模型）；本模型只承载解析结果，直接构造时由校验器兜底
    「说明必须依附 required」的同规约束。
    """

    required: bool = False
    note: str = ""

    @model_validator(mode="after")
    def _note_requires_required(self) -> StepApproval:
        if self.note and not self.required:
            raise ValueError("approval note is only meaningful with 'approval: required'")
        return self


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
    # ``approval:`` 声明的类型视图（loader 解析；未声明 = 不需要人工确认、零行为变化）。
    approval: StepApproval = Field(default_factory=StepApproval)
    # ``validation:`` 里的结构化证据子句（loader 解析后的视图；未声明 = 全空、零行为变化）。
    validation_clauses: StepValidationClauses = Field(default_factory=StepValidationClauses)
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
    # workflow 的 revision（Story 51-6）：包 frontmatter 可显式声明；未声明时空串 = 由包内容
    # 推导（派生点唯一在 ``goal/workflow_loader.workflow_revision``）。声明与派生两条路都只是
    # 「提供被冻结的值」——创建时冻结、恢复时比对是引擎不变量（AD-8），本模型不承载比对。
    revision: str = ""
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
