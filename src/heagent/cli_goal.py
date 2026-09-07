"""/goal command family: declarative workflow dispatch, questionnaire gating, and cron auto-advance."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from pydantic import BaseModel

from heagent.config import get_settings
from heagent.context.loader import load_context_files
from heagent.context.window_reset import WindowResetConfig
from heagent.cron.expr import cron_matches
from heagent.engine import (
    GoalArtifact,
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowRunner,
    WorkflowStatus,
    WorkflowStepResult,
    parse_artifact,
)
from heagent.engine.persist import atomic_update_text, atomic_write_text
from heagent.memory.skill_packages import SkillPackage, SkillWorkflowError, WorkflowResource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from heagent.agent.sub import SubAgentResult
    from heagent.cron.jobs import JobStore
    from heagent.engine import EngineContainer
    from heagent.providers.base import BaseProvider


_GOAL_AUTO_DEFAULT_CRON = "*/15 * * * *"
_GOAL_AUTO_PREFIX = "goal-advance "
_goal_auto_lock = asyncio.Lock()


# =============================================================================
# /goal 命令族（Story 41.1：目标驱动开发工作流——skill 正文直读 + 逐 story 会话）
# =============================================================================

# goal 状态目录与声明式 workflow 路径（相对路径，使用时锚定 Path.cwd()）。
# Durable user-facing Goal and workflow artifacts belong under the project output
# root. ``.heagent`` remains reserved for runtime configuration and skill code.
_GOALS_DIR = Path("_he-output/goals")
_GOAL_DECLARATIVE_WORKFLOW_PATH = Path(".heagent/workflows/workflow.md")
_GOAL_HEX = frozenset("0123456789abcdef")  # 兼容既有 8 位十六进制 goal_id
_GOAL_ID_RE = re.compile(r"^[a-z][a-z-]*$")
_GOAL_NAME_WORDS = {
    "继续": "continue",
    "开发": "development",
    "项目": "project",
    "功能": "feature",
    "需求": "requirements",
    "分析": "analysis",
    "设计": "design",
    "实现": "implementation",
    "修复": "fix",
    "增强": "enhancement",
    "安全": "security",
    "发布": "release",
    "部署": "deployment",
    "测试": "testing",
    "数据": "data",
    "服务": "service",
    "界面": "interface",
    "工作流": "workflow",
    "智能体": "agent",
    "代理": "agent",
}
_GOAL_RUN_MAX_ROUNDS = 10
_GOAL_ADVANCED = "advanced"
_GOAL_DONE = "done"
_GOAL_FAILED = "failed"
_GOAL_WAITING = "waiting"


class GoalQuestion(BaseModel):
    """One declarative question parsed from the goal workflow Markdown."""

    number: int
    identifier: str
    prompt: str
    options: list[str] = []
    when_key: str | None = None
    when_values: list[str] = []
    value_type: str = "text"
    minimum: float | None = None


class GoalQuestionnaireSpec(BaseModel):
    """A workflow-defined questionnaire; its product rules never live in CLI code."""

    name: str
    applies_when: str
    questions: list[GoalQuestion]
    include_in_step: str | None = None


class GoalQuestionnaire(BaseModel):
    """Validated responses to a workflow-defined questionnaire."""

    name: str
    answers: dict[str, str]

    def render(self, spec: GoalQuestionnaireSpec) -> str:
        return "\n".join(
            f"Q{question.number} {question.prompt}：{self.answers[question.identifier]}"
            for question in spec.questions
            if question.identifier in self.answers
        )


def _goal_document(description: str, goal_id: str) -> str:
    """Create the standard BMad Goal artifact used as the durable goal record."""
    title = " ".join(description.split())
    fence_size = max((len(run) for run in re.findall(r"`+", description)), default=0) + 1
    fence = "`" * max(3, fence_size)
    original = description if description.endswith("\n") else description + "\n"
    return (
        "---\n"
        f"id: goal-{goal_id}\n"
        "type: goal\n"
        "status: planning\n"
        f"title: {title}\n"
        "---\n\n"
        f"# {title}\n\n"
        "## 原始需求（Original Request）\n\n"
        f"{fence}\n{original}{fence}\n\n"
        "## Epics\n\n"
        "- No epics have been decomposed yet.\n"
    )


def _goal_project_id(description: str) -> str:
    """Extract a stable English, letter-only project id from the request."""
    text = re.sub(r"^\s*/goal(?:\s+new)?\s*", "", description.strip(), flags=re.IGNORECASE)
    terms = "|".join(re.escape(item) for item in sorted(_GOAL_NAME_WORDS, key=len, reverse=True))
    words = [
        _GOAL_NAME_WORDS.get(match.group(0), match.group(0)) for match in re.finditer(rf"(?:{terms})|[A-Za-z]+", text)
    ]
    slug = re.sub(r"-+", "-", "-".join(words).casefold()).strip("-")
    slug = re.sub(r"-?(?:19|20)\d{2}(?:-?\d{1,2}){0,2}$", "", slug).strip("-")
    return slug or "project"


def _goal_id_is_valid(goal_id: str) -> bool:
    """Accept new letter-only ids and legacy eight-character hex ids."""
    return bool(_GOAL_ID_RE.fullmatch(goal_id)) or (len(goal_id) == 8 and all(char in _GOAL_HEX for char in goal_id))


def _goal_step_artifact_path(goal_dir: Path, step: Any) -> Path:
    """Map a declared workflow step to its durable output document."""
    name = re.sub(r"^step-\d+-", "", step.name.casefold())
    name = re.sub(r"\.md$", "", name)
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "step"
    return goal_dir / f"step-{step.index:02d}-{slug}.md"


def _goal_description(goal_dir: Path) -> str:
    """Load the marked original request from GOAL.md, with legacy fallback."""
    text = (goal_dir / "GOAL.md").read_text(encoding="utf-8")
    artifact = parse_artifact(text)
    section = artifact.sections.get("原始需求（original request）")
    if section:
        match = re.fullmatch(r"(`{3,})\n(.*?)\n\1", section, flags=re.DOTALL)
        return match.group(2) if match else section
    return _goal_document_title(text)


def _goal_user_responses(goal_dir: Path) -> str:
    """Return the accumulated user answers recorded in GOAL.md."""
    text = (goal_dir / "GOAL.md").read_text(encoding="utf-8")
    artifact = parse_artifact(text)
    return artifact.sections.get("用户补充（user responses）", "")


def _goal_record_user_response(goal_dir: Path, response: str) -> None:
    """Append one exact user answer to the single durable Goal document."""
    if not response.strip():
        return
    fence_size = max((len(run) for run in re.findall(r"`+", response)), default=0) + 1
    fence = "`" * max(3, fence_size)
    answer = response if response.endswith("\n") else response + "\n"

    def update(raw: str) -> tuple[str, None]:
        artifact = parse_artifact(raw)
        section_name = "用户补充（User Responses）"
        existing = artifact.sections.get(section_name.casefold(), "")
        response_number = len(re.findall(r"(?m)^### Response \d+\s*$", existing)) + 1
        entry = f"### Response {response_number}\n\n{fence}\n{answer}{fence}\n"
        if existing:
            return raw.rstrip() + "\n\n" + entry, None
        return raw.rstrip() + f"\n\n## {section_name}\n\n" + entry, None

    atomic_update_text(goal_dir / "GOAL.md", update)


_GOAL_QUESTIONNAIRE_FILE = "QUESTIONNAIRE.md"


def _goal_questionnaire_spec(goal_dir: Path) -> GoalQuestionnaireSpec | None:
    """Load a questionnaire owned by the concrete goal directory.

    New goals keep the declarative questionnaire in ``GOAL.md``. The standalone
    file fallback is retained for legacy/test packages that have not migrated.
    """
    goal_path = goal_dir / "GOAL.md"
    text = goal_path.read_text(encoding="utf-8") if goal_path.is_file() else ""
    section = re.search(r"(?ms)^##? Questionnaire\s*$\n(.*?)(?=^##\s|\Z)", text)
    if section is None:
        legacy_path = Path(_GOAL_QUESTIONNAIRE_FILE)
        text = legacy_path.read_text(encoding="utf-8") if legacy_path.is_file() else ""
        section = re.search(r"(?ms)^#(?:#)? Questionnaire\s*$\n(.*)\Z", text)
    if section is None:
        return None
    header, *question_blocks = re.split(r"(?m)^###\s+", section.group(1).strip())
    metadata = dict(re.findall(r"(?m)^(applies_when|include_in_step|name)\s*:\s*(.+?)\s*$", header))
    applies_when = metadata.get("applies_when", "").strip()
    name = metadata.get("name", "Questionnaire").strip()
    if not applies_when:
        raise ValueError("questionnaire requires applies_when")
    questions: list[GoalQuestion] = []
    for block in question_blocks:
        heading, _, body = block.partition("\n")
        match = re.fullmatch(r"Q(\d+)\s+(.+)", heading.strip())
        if match is None:
            raise ValueError(f"invalid questionnaire heading: {heading}")
        fields = dict(re.findall(r"(?m)^(id|options|when|type|minimum)\s*:\s*(.+?)\s*$", body))
        identifier = fields.get("id", "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", identifier):
            raise ValueError(f"questionnaire Q{match.group(1)} requires id")
        when_key, separator, raw_values = fields.get("when", "").partition("=")
        if fields.get("when") and (not separator or not when_key.strip() or not raw_values.strip()):
            raise ValueError(f"questionnaire Q{match.group(1)} has invalid when")
        value_type = fields.get("type", "text").strip()
        if value_type not in {"text", "number"}:
            raise ValueError(f"questionnaire Q{match.group(1)} type must be text or number")
        try:
            minimum = float(fields["minimum"]) if "minimum" in fields else None
        except ValueError as exc:
            raise ValueError(f"questionnaire Q{match.group(1)} has invalid minimum") from exc
        if minimum is not None and value_type != "number":
            raise ValueError(f"questionnaire Q{match.group(1)} minimum requires type number")
        questions.append(
            GoalQuestion(
                number=int(match.group(1)),
                identifier=identifier,
                prompt=match.group(2).strip(),
                options=[item.strip() for item in fields.get("options", "").split("|") if item.strip()],
                when_key=when_key.strip() or None,
                when_values=[item.strip() for item in raw_values.split("|") if item.strip()],
                value_type=value_type,
                minimum=minimum,
            )
        )
    if not questions or [question.number for question in questions] != list(range(1, len(questions) + 1)):
        raise ValueError("questionnaire questions must start at Q1 and be contiguous")
    identifiers = {question.identifier for question in questions}
    if len(identifiers) != len(questions):
        raise ValueError("questionnaire question ids must be unique")
    for index, question in enumerate(questions):
        if question.when_key is not None and question.when_key not in {prior.identifier for prior in questions[:index]}:
            raise ValueError(f"questionnaire Q{question.number} when must reference an earlier question")
    return GoalQuestionnaireSpec(
        name=name,
        applies_when=applies_when,
        questions=questions,
        include_in_step=metadata.get("include_in_step", "").strip() or None,
    )


def _goal_questionnaire_applies(spec: GoalQuestionnaireSpec | None, description: str) -> bool:
    if spec is None:
        return False
    try:
        return re.search(spec.applies_when, description, re.IGNORECASE) is not None
    except re.error as exc:
        raise ValueError(f"questionnaire applies_when is invalid: {exc}") from exc


def _goal_question_value_error(question: GoalQuestion, value: str) -> str:
    """Validate one answer against its declared question; empty string means valid."""
    if not value:
        return f"缺少 Q{question.number} {question.prompt}"
    if question.options and value not in question.options:
        return f"Q{question.number} 必须是：" + "、".join(question.options)
    if question.value_type == "number":
        try:
            numeric = float(value)
        except ValueError:
            return f"Q{question.number} 必须是数字"
        if question.minimum is not None and numeric < question.minimum:
            return f"Q{question.number} 不能小于 {question.minimum:g}"
    return ""


def _goal_questionnaire_from_text(text: str, spec: GoalQuestionnaireSpec) -> tuple[GoalQuestionnaire | None, str]:
    """Validate answers against the workflow declaration without product-specific rules."""
    values = {
        int(number): answer.strip() for number, answer in re.findall(r"(?mi)^Q(\d+)\s*[^：:\n]*[：:]\s*(.+?)\s*$", text)
    }
    answers = {question.identifier: values.get(question.number, "") for question in spec.questions}
    for question in spec.questions:
        active = question.when_key is None or answers.get(question.when_key, "") in question.when_values
        if not active:
            answers.pop(question.identifier, None)
            continue
        error = _goal_question_value_error(question, answers[question.identifier])
        if error:
            return None, error
    return GoalQuestionnaire(name=spec.name, answers=answers), ""


def _goal_questionnaire(goal_dir: Path, spec: GoalQuestionnaireSpec) -> GoalQuestionnaire | None:
    text = (goal_dir / "GOAL.md").read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^## Questionnaire: {re.escape(spec.name)}\s*$\n(.*?)(?=^##\s|\Z)", text)
    if match is None:
        return None
    questionnaire, error = _goal_questionnaire_from_text(match.group(1), spec)
    if questionnaire is None:
        raise ValueError(f"questionnaire is invalid: {error}")
    return questionnaire


def _goal_record_questionnaire(goal_dir: Path, questionnaire: GoalQuestionnaire, spec: GoalQuestionnaireSpec) -> None:
    if _goal_questionnaire(goal_dir, spec) is not None:
        return

    def update(raw: str) -> tuple[str, None]:
        return raw.rstrip() + f"\n\n## Questionnaire: {spec.name}\n\n{questionnaire.render(spec)}\n", None

    atomic_update_text(goal_dir / "GOAL.md", update)


def _goal_collect_questionnaire(spec: GoalQuestionnaireSpec) -> GoalQuestionnaire | None:
    """Collect only questions declared in the workflow, retaining answers in memory."""
    if not sys.stdin.isatty():
        return None
    answers: dict[str, str] = {}
    try:
        for question in spec.questions:
            if question.when_key is not None and answers.get(question.when_key) not in question.when_values:
                continue
            prompt_type: Any = (
                click.Choice(question.options)
                if question.options
                else float
                if question.value_type == "number"
                else str
            )
            while True:
                value = str(click.prompt(f"Q{question.number} {question.prompt}", type=prompt_type)).strip()
                error = _goal_question_value_error(question, value)
                if error:
                    click.echo(f"请重新输入：{error}", err=True)
                    continue
                answers[question.identifier] = value
                break
        return GoalQuestionnaire(name=spec.name, answers=answers)
    except (EOFError, KeyboardInterrupt, click.Abort, click.BadParameter):
        return None


def _goal_show_questionnaire_prompt(spec: GoalQuestionnaireSpec, error: str = "") -> None:
    if error:
        click.echo(f"[goal] questionnaire invalid: {error}", err=True)
    template = "\n".join(f"Q{question.number} {question.prompt}：<answer>" for question in spec.questions)
    click.echo(f"[goal] answer with /goal resume followed by:\n{template}", err=True)


def _goal_document_title(text: str) -> str:
    """Read a Goal artifact title without introducing a second metadata file."""
    artifact = parse_artifact(text)
    if not isinstance(artifact, GoalArtifact):
        raise ValueError("declarative GOAL.md must be a Goal artifact")
    return artifact.title


def _validate_goal_workflow(workflow: WorkflowResource) -> None:
    """Restrict workflow declarations to deterministic CLI capabilities."""
    if workflow.entrypoint not in {"", "goal"}:
        raise ValueError(f"unsupported goal workflow entrypoint: {workflow.entrypoint}")
    if workflow.on_create != "persist_goal_identity":
        raise ValueError(f"unsupported goal workflow on_create hook: {workflow.on_create}")
    if workflow.step_executor != "subagent":
        raise ValueError(f"unsupported goal workflow step executor: {workflow.step_executor}")


def _goal_checkpoint_mode(workflow: WorkflowResource) -> str:
    """Resolve checkpoint policy: workflow declaration, env-backed settings, default."""
    declared = workflow.checkpoint_mode.strip().casefold()
    if declared:
        return declared
    return get_settings().goal_checkpoint_mode


def _goal_checkpoint_prompt() -> bool:
    """Ask for checkpoint approval only when stdin is an interactive TTY."""
    if not sys.stdin.isatty():
        click.echo("[goal] waiting for user response; use /goal resume <answer> to continue", err=True)
        return False
    try:
        approved = bool(click.confirm("[goal] checkpoint complete; continue to the next step?", default=False))
        if not approved:
            click.echo("[goal] checkpoint paused; use /goal resume <answer> to continue", err=True)
        return approved
    except (EOFError, KeyboardInterrupt, click.Abort):
        click.echo("[goal] checkpoint paused; use /goal resume <answer> to continue", err=True)
        return False


def _goal_declarative_workflow() -> WorkflowResource | None:
    """Load the explicitly configured declarative goal workflow, if enabled.

    The configuration file is the feature flag. A malformed configured workflow is
    an error rather than a reason to silently run the incompatible GOAL.md flow.
    """
    if not _GOAL_DECLARATIVE_WORKFLOW_PATH.is_file():
        return None
    try:
        package = SkillPackage(
            skill_id="goal-declarative-workflow",
            root=_GOAL_DECLARATIVE_WORKFLOW_PATH.parent,
        )
        workflow = package.read_workflow(_GOAL_DECLARATIVE_WORKFLOW_PATH.name)
        _validate_goal_workflow(workflow)
        return workflow
    except (SkillWorkflowError, ValueError, OSError) as exc:
        raise ValueError(f"declarative workflow configuration is invalid: {exc}") from exc


def _goal_declarative_store(goal_dir: Path) -> WorkflowCheckpointStore:
    return WorkflowCheckpointStore(
        str(goal_dir / "checkpoints"),
        workflow_path=str(goal_dir / "workflow.json"),
    )


def _goal_declarative_active_dir() -> Path | None:
    goal_md = _goal_active_md()
    return goal_md.parent if goal_md is not None else None


async def _goal_declarative_runner(
    workflow: WorkflowResource,
    goal_dir: Path,
) -> WorkflowRunner:
    """Restore the latest Runner snapshot or create a new one for this goal."""
    store = _goal_declarative_store(goal_dir)
    checkpoints = await store.list_checkpoints(goal_id=goal_dir.name)
    workflow_state = await store.load_workflow()
    if workflow_state is not None:
        # Match against the persisted active_skill (workflow.json) rather than the
        # current workflow.name, so a workflow rename does not strand existing goals.
        matching = [
            checkpoint
            for checkpoint in checkpoints
            if checkpoint.active_step == workflow_state.active_step
            and checkpoint.active_skill == workflow_state.active_skill
            and (
                checkpoint.status is workflow_state.status
                or (checkpoint.status is WorkflowStatus.COMPLETED and workflow_state.status is WorkflowStatus.RUNNING)
            )
        ]
        if matching:
            return WorkflowRunner.from_checkpoint(
                workflow,
                matching[-1],
                checkpoint_store=store,
                phase=WorkflowPhase.IMPLEMENTATION,
            )
        if checkpoints:
            raise WorkflowCheckpointError("workflow configuration does not match the persisted goal state")
    # Each goal owns its checkpoint directory, so the latest checkpoint for this
    # goal is the authoritative recovery point. Do not make recovery contingent
    # on optional descriptive metadata such as ``active_skill``.
    if checkpoints:
        return WorkflowRunner.from_checkpoint(
            workflow,
            checkpoints[-1],
            checkpoint_store=store,
            phase=WorkflowPhase.IMPLEMENTATION,
        )
    return WorkflowRunner(
        workflow,
        goal_id=goal_dir.name,
        checkpoint_store=store,
        phase=WorkflowPhase.IMPLEMENTATION,
    )


async def _goal_wait_for_questionnaire(workflow: WorkflowResource, goal_dir: Path, error: str = "") -> None:
    """Persist a recoverable questionnaire gate before any SubAgent can run."""
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
        runner.state = runner.state.model_copy(
            update={"status": WorkflowStatus.WAITING_USER, "reason": "workflow questionnaire is required"}
        )
        await runner.persist_state()
    except (WorkflowCheckpointError, ValueError) as exc:
        click.echo(f"[goal] failed to persist questionnaire gate: {exc}", err=True)
        return
    try:
        spec = _goal_questionnaire_spec(goal_dir)
    except ValueError as exc:
        click.echo(f"[goal] declarative questionnaire configuration is invalid: {exc}", err=True)
        return
    if spec is not None:
        _goal_show_questionnaire_prompt(spec, error)


def _goal_declarative_prompt(
    workflow: WorkflowResource,
    step_name: str,
    description: str,
    goal_dir: Path,
    inputs: Mapping[str, Any],
) -> str:
    role = _goal_role_instructions(step_name)
    supplied_inputs = "\n\n".join(f"## {name}\n{value}" for name, value in inputs.items())
    return (
        f"{workflow.instructions}\n\n# Declarative workflow step\n"
        f"Goal: {description}\n"
        f"Goal directory: {goal_dir.resolve()}\n"
        f"Project output root: {goal_dir.parent.parent.resolve()}\n"
        f"Step: {step_name}\n"
        f"Role instructions:\n{role}\n"
        f"Declared inputs:\n{supplied_inputs}\n"
        "Execute only this declared step. Write every durable non-code project artifact under the project output root; "
        "source code remains in its established repository location. Return the complete artifact body as your final "
        "response; do not return a summary, link, or claim that you wrote it elsewhere."
    )


def _goal_role_instructions(step_name: str) -> str:
    """Load the role contract assigned to a workflow step."""
    workflow = _goal_declarative_workflow()
    role_name = next((step.role for step in workflow.steps if step.name == step_name), "") if workflow else ""
    if not role_name:
        return "No specialized BMad role assigned."
    aliases = {
        "bmad-agent-analyst": "he-agent-analyst",
        "bmad-agent-pm": "he-agent-pm",
        "bmad-agent-ux-designer": "he-agent-ux",
        "bmad-agent-architect": "he-agent-architect",
        "bmad-agent-dev": "he-agent-dev",
    }
    package_id = aliases.get(role_name, role_name)
    try:
        return SkillPackage(skill_id=package_id, root=Path(".heagent/skills") / package_id).read_entry().text
    except (SkillWorkflowError, ValueError, OSError) as exc:
        raise ValueError(f"workflow role '{role_name}' is unavailable: {exc}") from exc


async def _goal_declarative_advance(  # noqa: C901
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
) -> str:
    """Advance deterministically through steps and resolve completed checkpoints."""
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        click.echo("[goal] no active declarative goal; use /goal new <description>", err=True)
        return _GOAL_FAILED
    try:
        description = _goal_description(goal_dir)
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] declarative GOAL.md is invalid: {exc}", err=True)
        return _GOAL_FAILED
    if not description:
        click.echo("[goal] declarative GOAL.md has no title", err=True)
        return _GOAL_FAILED
    try:
        questionnaire_spec = _goal_questionnaire_spec(goal_dir)
    except (ValueError, OSError) as exc:
        click.echo(f"[goal] declarative questionnaire configuration is invalid: {exc}", err=True)
        return _GOAL_FAILED
    try:
        questionnaire = _goal_questionnaire(goal_dir, questionnaire_spec) if questionnaire_spec is not None else None
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] declarative questionnaire is invalid: {exc}", err=True)
        return _GOAL_FAILED
    try:
        applies = _goal_questionnaire_applies(questionnaire_spec, description)
    except ValueError as exc:
        click.echo(f"[goal] declarative questionnaire configuration is invalid: {exc}", err=True)
        return _GOAL_FAILED
    if applies and questionnaire is None:
        await _goal_wait_for_questionnaire(workflow, goal_dir)
        return _GOAL_WAITING
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
    except WorkflowCheckpointError as exc:
        click.echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
        return _GOAL_FAILED
    if runner.done:
        click.echo("[goal] declarative workflow is already complete", err=True)
        return _GOAL_DONE
    # A pause/cancellation is persisted as a non-completed Runner state. Resume
    # is explicit at the command boundary, then this call may continue the step.
    if runner.state.status is WorkflowStatus.WAITING_USER:
        click.echo("[goal] declarative workflow is paused; use /goal resume first", err=True)
        return _GOAL_WAITING
    if runner.state.status in {WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
        click.echo(f"[goal] declarative workflow is {runner.state.status.value}: {runner.state.reason}", err=True)
        return _GOAL_FAILED

    try:
        mode = _goal_checkpoint_mode(workflow)
    except ValueError as exc:
        click.echo(f"[goal] invalid checkpoint mode: {exc}", err=True)
        return _GOAL_FAILED

    async def execute_step(step: Any) -> WorkflowStepResult:
        result = await _goal_session(
            provider,
            engine,
            _goal_declarative_prompt(workflow, step.name, description, goal_dir, inputs) + f"\n\n{step.instructions}",
            metadata={"goal_id": goal_dir.name, "goal_kind": "declarative", "workflow_step": step.name},
        )
        if result is None:
            return WorkflowStepResult(
                status=WorkflowStatus.WAITING_USER, reason="interrupted; resume to retry the active step"
            )
        if not result.success:
            return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=str(result.output))
        try:
            output_text = result.output if isinstance(result.output, str) else str(result.output)
            if result.output is None or (isinstance(result.output, str) and not output_text.strip()):
                return WorkflowStepResult(
                    status=WorkflowStatus.FAILED,
                    reason=f"step '{step.name}' produced empty output",
                )
            if (
                questionnaire is not None
                and questionnaire_spec is not None
                and questionnaire_spec.include_in_step == step.name
            ):
                output_text = (
                    "## Confirmed Questionnaire\n\n"
                    + questionnaire.render(questionnaire_spec)
                    + "\n\n---\n\n"
                    + output_text
                )
            atomic_write_text(_goal_step_artifact_path(goal_dir, step), output_text)
        except OSError as exc:
            return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=f"failed to persist step output: {exc}")
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output=result.output)

    # Input declarations describe the context supplied by this deterministic CLI
    # boundary. Artifact names from completed steps remain available on resume.
    while True:
        try:
            user_responses = _goal_user_responses(goal_dir)
        except OSError as exc:
            click.echo(f"[goal] declarative GOAL.md is unreadable: {exc}", err=True)
            return _GOAL_FAILED
        inputs: dict[str, Any] = {
            "user intent": description,
            "user responses": user_responses or "No user response has been recorded.",
            "existing project context": load_context_files(os.getcwd())
            or "No project context file was found; inspect the current workspace before making assumptions.",
            **runner.state.outputs,
        }
        if questionnaire is not None and questionnaire_spec is not None:
            inputs["questionnaire"] = questionnaire.render(questionnaire_spec)
        try:
            result = await runner.run_step(execute_step, inputs=inputs)
        except (WorkflowCheckpointError, ValueError, TypeError) as exc:
            click.echo(f"[goal] declarative workflow failed: {exc}", err=True)
            return _GOAL_FAILED
        click.echo(
            f"[goal] declarative workflow: step={result.step_index if result.step_index is not None else '-'} "
            f"status={result.status.value}",
            err=True,
        )
        if result.status is WorkflowStatus.COMPLETED:
            return _GOAL_DONE
        if result.status is WorkflowStatus.PENDING:
            if mode == "auto":
                continue
            return _GOAL_ADVANCED
        if result.status is not WorkflowStatus.WAITING_USER:
            return _GOAL_FAILED

        # WAITING_USER from a completed step is a checkpoint decision. An
        # interrupted callback also uses WAITING_USER, but must never be treated
        # as implicit approval.
        checkpoint_completed = result.step_index is not None and (result.step_index - 1) in runner.state.completed_steps
        if not checkpoint_completed:
            return _GOAL_WAITING
        if mode == "auto":
            runner.resume()
            try:
                await runner.persist_state()
            except (WorkflowCheckpointError, ValueError, TypeError) as exc:
                click.echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
                return _GOAL_FAILED
            continue
        if not _goal_checkpoint_prompt():
            return _GOAL_WAITING
        runner.resume()
        try:
            await runner.persist_state()
        except (WorkflowCheckpointError, ValueError, TypeError) as exc:
            click.echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
            return _GOAL_FAILED


async def _goal_declarative_new(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    description: str,
    *,
    cron_store: JobStore | None = None,
) -> None:
    """Create the minimum durable declarative-goal identity, then run step one."""
    previous = _goal_declarative_active_dir()
    goal_id = _goal_project_id(description)
    goal_dir = _GOALS_DIR / goal_id
    for suffix in [""] + [f"-{chr(ord('a') + index)}" for index in range(26)]:
        if not goal_dir.exists():
            break
        goal_id = _goal_project_id(description) + suffix
        goal_dir = _GOALS_DIR / goal_id
    else:
        click.echo("[goal] unable to allocate a unique project goal id", err=True)
        return
    try:
        goal_document = _goal_document(description, goal_id)
        _goal_document_title(goal_document)
        atomic_write_text(goal_dir / "GOAL.md", goal_document)
        atomic_write_text(_GOALS_DIR / "current", goal_id)
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] failed to persist declarative goal: {exc}", err=True)
        return
    if previous is not None and cron_store is not None:
        _goal_auto_remove(cron_store, previous.name)
    try:
        questionnaire_spec = _goal_questionnaire_spec(goal_dir)
        applies = _goal_questionnaire_applies(questionnaire_spec, description)
    except (ValueError, OSError) as exc:
        click.echo(f"[goal] declarative questionnaire configuration is invalid: {exc}", err=True)
        return
    if applies and questionnaire_spec is not None:
        questionnaire = _goal_collect_questionnaire(questionnaire_spec)
        if questionnaire is None:
            await _goal_wait_for_questionnaire(workflow, goal_dir)
            return
        try:
            _goal_record_questionnaire(goal_dir, questionnaire, questionnaire_spec)
        except (ValueError, OSError) as exc:
            click.echo(f"[goal] failed to persist questionnaire: {exc}", err=True)
            return
    await _goal_declarative_advance(provider, engine, workflow)


async def _goal_declarative_status(workflow: WorkflowResource) -> None:
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        click.echo("[goal] no active declarative goal", err=True)
        return
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
    except (WorkflowCheckpointError, ValueError) as exc:
        click.echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
        return
    click.echo(
        f"[goal] declarative progress: {len(runner.state.completed_steps)}/{len(workflow.steps)} "
        f"status={runner.state.status.value} step={runner.state.active_step}",
        err=True,
    )
    if runner.state.status is WorkflowStatus.WAITING_USER:
        click.echo("[goal] waiting for user response; use /goal resume <answer> to continue", err=True)


async def _goal_declarative_pause_resume(workflow: WorkflowResource, *, resume: bool, response: str = "") -> bool:
    """Persist a pause or resume and report whether a step may now execute."""
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        click.echo("[goal] no active declarative goal", err=True)
        return False
    action = "workflow"
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
        if runner.done:
            click.echo("[goal] declarative workflow is already complete", err=True)
            return False
        if resume:
            if runner.state.status not in {WorkflowStatus.WAITING_USER, WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
                click.echo(f"[goal] workflow status={runner.state.status.value}; resume is not required", err=True)
                return False
            description = _goal_description(goal_dir)
            questionnaire_spec = _goal_questionnaire_spec(goal_dir)
            questionnaire = (
                _goal_questionnaire(goal_dir, questionnaire_spec) if questionnaire_spec is not None else None
            )
            if _goal_questionnaire_applies(questionnaire_spec, description) and questionnaire is None:
                if questionnaire_spec is None:
                    return False
                parsed, error = _goal_questionnaire_from_text(response, questionnaire_spec)
                if parsed is None:
                    _goal_show_questionnaire_prompt(questionnaire_spec, error)
                    return False
                _goal_record_questionnaire(goal_dir, parsed, questionnaire_spec)
            elif response:
                _goal_record_user_response(goal_dir, response)
            runner.resume()
            action = "resumed"
        else:
            if runner.state.status is WorkflowStatus.WAITING_USER:
                click.echo("[goal] already paused; use /goal resume to continue", err=True)
                return False
            runner.state = runner.state.model_copy(
                update={"status": WorkflowStatus.WAITING_USER, "reason": "user requested pause; resume to continue"}
            )
            action = "paused"
        await runner.persist_state()
    except (WorkflowCheckpointError, ValueError, OSError) as exc:
        click.echo(f"[goal] declarative {action} failed: {exc}", err=True)
        return False
    click.echo(f"[goal] declarative workflow {action}: step={runner.state.active_step}", err=True)
    return resume


async def _goal_declarative_run(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
) -> None:
    try:
        for _ in range(_GOAL_RUN_MAX_ROUNDS):
            async with _goal_auto_lock:
                outcome = await _goal_declarative_advance(provider, engine, workflow)
            if outcome != _GOAL_ADVANCED:
                return
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("[goal] declarative workflow interrupted; use /goal resume to continue", err=True)


async def _goal_declarative_auto(
    workflow: WorkflowResource,
    args: str,
    cron_store: JobStore | None,
) -> None:
    goal_dir = _goal_declarative_active_dir()
    if args == "off":
        if cron_store is None or goal_dir is None:
            click.echo("[goal] cron is not enabled or there is no active declarative goal", err=True)
            return
        click.echo(f"[goal] auto disabled: removed {_goal_auto_remove(cron_store, goal_dir.name)} job(s)", err=True)
        return
    if cron_store is None or goal_dir is None:
        click.echo("[goal] cron is not enabled or there is no active declarative goal", err=True)
        return
    schedule = args or _GOAL_AUTO_DEFAULT_CRON
    try:
        fields = schedule.split()
        if len(fields) != 5 or any(not field or any(not part.strip() for part in field.split(",")) for field in fields):
            raise ValueError("cron must contain five non-empty fields")
        cron_matches(schedule, datetime.now(UTC))
    except (TypeError, ValueError) as exc:
        click.echo(f"[goal] invalid cron expression: {exc}", err=True)
        return
    _goal_auto_remove(cron_store, goal_dir.name)
    job = cron_store.create_job(f"{_GOAL_AUTO_PREFIX}{goal_dir.name}", schedule)
    cron_store.add(job)
    click.echo(f"[goal] declarative auto registered: {job.id} workflow={workflow.name}", err=True)


async def _goal_declarative_dispatch(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    args: str,
    *,
    cron_store: JobStore | None,
) -> None:
    """Route the supported /goal commands without touching the legacy board."""
    parts = args.split(None, 1)
    head = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not parts:
        await _goal_declarative_status(workflow)
    elif head == "new":
        if not rest:
            _goal_usage()
        else:
            async with _goal_auto_lock:
                await _goal_declarative_new(provider, engine, workflow, rest, cron_store=cron_store)
    elif head in ("next", "status", "reset", "run", "pause", "audit") and rest:
        _goal_usage()
    elif head == "next":
        async with _goal_auto_lock:
            await _goal_declarative_advance(provider, engine, workflow)
    elif head == "run":
        await _goal_declarative_run(provider, engine, workflow)
    elif head == "status":
        await _goal_declarative_status(workflow)
    elif head == "pause":
        await _goal_declarative_pause_resume(workflow, resume=False)
    elif head == "resume":
        async with _goal_auto_lock:
            if await _goal_declarative_pause_resume(workflow, resume=True, response=rest):
                await _goal_declarative_advance(provider, engine, workflow)
    elif head == "audit":
        await _goal_audit(engine)
    elif head == "reset":
        _goal_reset()
    elif head == "auto":
        await _goal_declarative_auto(workflow, rest, cron_store)
    else:
        async with _goal_auto_lock:
            await _goal_declarative_new(provider, engine, workflow, args.strip(), cron_store=cron_store)


def _goal_usage() -> None:
    """打印 /goal 子命令用法表（缺参 / 未实现 / 拼错时）。"""
    click.echo(
        "/goal 用法：\n"
        "  /goal <目标描述>      新建 goal 并执行 planning 规程\n"
        "  /goal new <目标描述>  同上（显式 new 形式）\n"
        "  /goal next            推进下一条 story（每步全新会话）\n"
        "  /goal status          查看进度与 GOAL.md 全文\n"
        "  /goal reset           清除 current 指针（goal 目录保留）\n"
        f"  /goal run             连续推进 goal（最多 {_GOAL_RUN_MAX_ROUNDS} 步；Ctrl+C 可中断）\n"
        "  /goal resume [回复]   记录用户回答并继续 waiting_user 步骤\n"
        "  /goal auto [cron]     注册 cron 自动推进（默认 */15 * * * *；off 注销）",
        err=True,
    )


def _goal_active_md() -> Path | None:
    """解析活跃 goal 的 GOAL.md 路径；指针缺失/解码失败返回 None，内容非法显性报错。"""
    try:
        goal_id = (_GOALS_DIR / "current").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] 显性失败：current 指针读取失败（{exc}）。", err=True)
        return None
    if not goal_id:
        return None
    # 指针内容须为字母 slug 或既有 8 位小写十六进制：防手改指针越界。
    # 把围栏外任意文件当 GOAL.md 注入 LLM prompt（仿 sandbox_session_dir 先例）。
    if not _goal_id_is_valid(goal_id):
        click.echo(f"[goal] current 指针内容非法：{goal_id!r}（须为英文字母 project id）。", err=True)
        return None
    goals_root = _GOALS_DIR.resolve()
    goal_root = (_GOALS_DIR / goal_id).resolve()
    if not goal_root.is_relative_to(goals_root):
        click.echo("[goal] current 指针解析后越过 goals 根目录。", err=True)
        return None
    return goal_root / "GOAL.md"


async def _goal_session(
    provider: BaseProvider,
    engine: EngineContainer | None,
    prompt: str,
    *,
    metadata: dict[str, Any] | None = None,
    max_iterations: int | None = None,
) -> SubAgentResult | None:
    """开一个**全新** SubAgent 会话执行一个 goal 步骤（非流式，流式 deferred）。

    每次 ``run()`` 新建 AgentLoop+RunContext；``window_reset`` 按设置阈值启用（长会话
    清窗续跑）。Ctrl+C / 任务取消不崩出交互层：捕获后回显「状态在盘」并返回 None。
    """
    from heagent.agent.sub import SubAgent  # noqa: PLC0415

    agent = SubAgent(
        provider,
        engine=engine,
        metadata=metadata,
        max_iterations=max_iterations if max_iterations is not None else get_settings().goal_max_iterations,
        window_reset=WindowResetConfig(threshold=get_settings().window_reset_threshold),
    )
    try:
        return await agent.run(prompt)
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("[goal] 已中断：状态在盘（GOAL.md），/goal next 可续跑。", err=True)
        return None


async def _goal_audit(engine: EngineContainer | None) -> None:
    goal_md = _goal_active_md()
    if goal_md is None:
        click.echo("[goal] no active goal available for audit", err=True)
        return
    goal_id = goal_md.parent.name
    if engine is None:
        click.echo("[goal] audit unavailable without engine", err=True)
        return
    records = [record for record in await engine.ledger.list_records() if record.metadata.get("goal_id") == goal_id]
    events = [
        event
        for event in engine.events.recent_events
        if event.details.get("goal_id") == goal_id or event.run_id == goal_id
    ]
    click.echo(f"[goal] audit: goal={goal_id} records={len(records)} events={len(events)}", err=True)
    for record in records:
        click.echo(
            f"  record={record.key} status={record.status.value} run={record.run_id or '-'} "
            f"started={record.started_at} finished={record.finished_at or '-'} error={record.error or '-'}",
            err=True,
        )
    for event in events:
        click.echo(
            f"  event={event.event_type} run={event.run_id or '-'} at={event.timestamp} details={event.details}",
            err=True,
        )


def _goal_reset() -> None:
    """清除 current 指针（不删任何其他文件）；goal 目录保留并回显路径。"""
    try:
        (_GOALS_DIR / "current").unlink(missing_ok=True)  # missing_ok：竞态下指针已消失视为已清
    except OSError as exc:
        click.echo(f"[goal] 落盘失败：清除 current 指针失败（{exc}）。", err=True)
        return
    click.echo(f"[goal] current 指针已清除；goal 目录保留：{_GOALS_DIR.resolve()}", err=True)


def _goal_auto_remove(store: JobStore, goal_id: str) -> int:
    removed = 0
    for job in store.list_jobs():
        if job.prompt == f"{_GOAL_AUTO_PREFIX}{goal_id}" and store.remove(job.id):
            removed += 1
    return removed


def _goal_auto_goal_id(prompt: str) -> str | None:
    """Return the exact goal id from a scheduler-owned auto prompt, if any."""
    if not prompt.startswith(_GOAL_AUTO_PREFIX):
        return None
    goal_id = prompt[len(_GOAL_AUTO_PREFIX) :].strip()
    if _goal_id_is_valid(goal_id):
        return goal_id
    return None


async def _goal_cron_advance(
    provider: BaseProvider, engine: EngineContainer | None, store: JobStore, goal_id: str
) -> None:
    """Run one scheduled goal step under the same process lock as manual commands."""
    async with _goal_auto_lock:
        current = _goal_active_md()
        if current is None or current.parent.name != goal_id:
            removed = _goal_auto_remove(store, goal_id)
            if removed:
                click.echo(f"[goal] auto 已收口：goal {goal_id} 已非当前 goal，注销 {removed} 个 job。", err=True)
            return
        try:
            declarative_workflow = _goal_declarative_workflow()
        except ValueError as exc:
            click.echo(f"[goal] auto stopped: {exc}", err=True)
            _goal_auto_remove(store, goal_id)
            return
        if declarative_workflow is not None:
            outcome = await _goal_declarative_advance(provider, engine, declarative_workflow)
            if outcome in {_GOAL_DONE, _GOAL_FAILED}:
                removed = _goal_auto_remove(store, goal_id)
                click.echo(f"[goal] declarative auto closed: goal {goal_id}, removed {removed} job(s)", err=True)
            return
        click.echo("[goal] auto stopped: workflow.md is required; legacy goal fallback is unavailable", err=True)
        _goal_auto_remove(store, goal_id)


async def _goal_runner(  # noqa: C901
    provider: BaseProvider,
    engine: EngineContainer | None,
    args: str,
    *,
    cron_store: JobStore | None = None,
) -> None:
    """/goal 子命令族总入口：加载声明式 workflow 后交给确定性分发器。

    workflow.md 缺失或无效时显性失败，不回退到已移除的 legacy goal board。
    """
    try:
        declarative_workflow = _goal_declarative_workflow()
    except ValueError as exc:
        click.echo(f"[goal] {exc}", err=True)
        return
    if declarative_workflow is not None:
        await _goal_declarative_dispatch(provider, engine, declarative_workflow, args, cron_store=cron_store)
        return
    click.echo(
        "[goal] workflow.md is required; the legacy GOAL.md Story flow has been removed. "
        f"Create {_GOAL_DECLARATIVE_WORKFLOW_PATH} to configure goal execution.",
        err=True,
    )
    return
