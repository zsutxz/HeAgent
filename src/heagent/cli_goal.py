"""/goal command family: declarative workflow dispatch, cron auto-advance, and goal mutex."""

from __future__ import annotations

import asyncio
import difflib
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from heagent.cli_display import SUBAGENT_ANNOUNCER
from heagent.config import get_settings
from heagent.context.loader import load_context_files
from heagent.context.window_reset import WindowResetConfig
from heagent.cron.expr import cron_matches
from heagent.engine import (
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowRunner,
    WorkflowStatus,
    WorkflowStepResult,
    parse_story_list,
    required_sections,
)
from heagent.goal.document import (
    _GOALS_DIR,
    _goal_description,
    _goal_document,
    _goal_document_path,
    _goal_document_title,
    _goal_id_is_valid,
    _goal_project_id,
    _goal_record_user_response,
    _goal_step_artifact_path,
    _goal_user_responses,
)
from heagent.memory.skill_packages import (
    SkillCatalog,
    SkillCatalogError,
    SkillPackage,
    SkillResolver,
    SkillWorkflowError,
    WorkflowResource,
)
from heagent.persist import atomic_write_text, file_lock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from heagent.agent.sub import SubAgentResult
    from heagent.cron.jobs import JobStore
    from heagent.engine import EngineContainer
    from heagent.providers.base import BaseProvider


logger = logging.getLogger(__name__)

_GOAL_AUTO_DEFAULT_CRON = "*/15 * * * *"
_GOAL_AUTO_PREFIX = "goal-advance "
_goal_auto_lock = asyncio.Lock()

# goal 域跨进程锁：竞态是「读 current 指针 → 读状态 → 推进 → 写 checkpoint /
# workflow.json / require.md」的整段读改写，per-file 锁防不了「两进程从同一状态各自
# 推进后互相覆盖」，故 goal 域一把域级锁。锁文件随 cwd 锚定（与 _GOALS_DIR 同锚定
# 方式），落在 .heagent/ 运行时状态区（见下文目录注释），不污染 _he-output/ 产物树。
_GOAL_LOCK_PATH = Path(".heagent/goal.lock")
_GOAL_LOCK_TIMEOUT = 5.0  # 并发方快速失败；cron 下一 tick 自动重试，手动方收到明确提示

# 工作流执行状态词汇与推进轮数上限：随编排分支（advance/execute 状态机）变，
# 不随文档约定变，故留本模块（goal/document.py 只做文档与命名，见其 docstring）。
# 工作流包 id 的默认值只在 Settings.goal_workflow_skill 一处声明；本模块一律从配置读。
# /goal 的技能库根：工作流包与每个步骤的角色包都从这里按 id 解析（单一来源）。
_GOAL_SKILLS_ROOT = Path(".heagent/skills")
# 以下两段文案是**兜底**：workflow 包 frontmatter 声明了对应内容时以包为准（工作流逻辑尽量不进代码）。
# 提示词与门禁模板**不在代码里**：由 workflow 包的 templates/ 携带；必需性由包 frontmatter 的
# ``required_resources`` 声明，缺失在包加载（read_workflow）时显性报错。
_DEFAULT_OPEN_QUESTION_DEFAULT = (
    "When a competing interpretation requires a stakeholder choice, proceed with the recommended "
    "default and record the assumption explicitly; do not stop with waiting_user."
)
_DEFAULT_OPEN_QUESTION_BLOCK = "Stop with waiting_user when competing interpretations require stakeholder choice."
_GOAL_ADVANCED = "advanced"
_GOAL_DONE = "done"
_GOAL_FAILED = "failed"
_GOAL_WAITING = "waiting"

# 模板占位符单遍渲染：值里再出现 ``{xxx}`` 字样也不会被二次替换（链式 str.replace 会）。
_TEMPLATE_FIELD_RE = re.compile(r"\{(\w+)\}")


def _render_template(template: str, fields: Mapping[str, str]) -> str:
    """Render ``{name}`` placeholders in one pass; unknown placeholders stay verbatim."""
    return _TEMPLATE_FIELD_RE.sub(lambda match: fields.get(match.group(1), match.group(0)), template)


@asynccontextmanager
async def _goal_mutex() -> AsyncIterator[None]:
    """进程内 asyncio.Lock + 跨进程文件锁的复合互斥（/goal 全部变更入口共用）。

    同进程两协程走 asyncio.Lock 快速路径，不排队文件锁；跨进程（双 CLI / CLI×GUI /
    cron×手动）由 ``.heagent/goal.lock`` 互斥。文件锁超时抛 ``OSError``——显性失败，
    由 ``_goal_runner`` / ``_goal_cron_advance`` 收口为用户可见提示。
    """
    async with _goal_auto_lock, file_lock(_GOAL_LOCK_PATH, timeout=_GOAL_LOCK_TIMEOUT):
        yield


# =============================================================================
# /goal 命令族（Story 41.1：目标驱动开发工作流——skill 正文直读 + 逐 story 会话）
# =============================================================================

# 需求文档与命名层（slug 词表 / goal_id 规则 / 目录命名 / require.md 生成与增量更新）
# 已拆至 goal/document.py（wiring.py 先例：文档约定与执行编排变化原因不同），见顶部
# re-export——测试经 heagent.cli_goal 导入这些符号，内部引用点继续按模块全局名解析。


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


def _goal_open_question_mode(workflow: WorkflowResource) -> str:
    """Resolve open-question policy: workflow declaration, env-backed settings, default."""
    declared = workflow.open_question_mode.strip().casefold()
    if declared:
        return declared
    return get_settings().goal_open_question_mode


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


def _resolve_skill_package(skill_id: str) -> SkillPackage | None:
    """Resolve one package from the skill library by canonical id or alias.

    The catalog owns the id/alias rules (``he-*`` canonical, ``bmad-*`` alias, plus each
    package's own ``aliases`` metadata), so the workflow package and the per-step role
    packages are addressed by id instead of by hand-built paths or a private alias table.
    ``None`` means "not installed here"; callers decide whether that is a missing
    configuration (workflow) or a hard failure (a role a step declared).
    """
    try:
        return SkillResolver(SkillCatalog([str(_GOAL_SKILLS_ROOT)]).scan()).resolve(skill_id)
    except (SkillCatalogError, ValueError, OSError) as exc:
        logger.debug("Skill package %r is unavailable under %s (%s)", skill_id, _GOAL_SKILLS_ROOT, exc)
        return None


def _goal_workflow_package() -> SkillPackage | None:
    """Resolve the configured workflow package; ``None`` when it is not installed."""
    return _resolve_skill_package(get_settings().goal_workflow_skill)


def _goal_declarative_workflow() -> WorkflowResource | None:
    """Load the configured declarative goal workflow, if its package is installed.

    A missing package means the workflow is not configured here (the caller says so);
    a package that exists but declares an unusable workflow is an explicit error rather
    than a reason to silently run the incompatible legacy flow.
    """
    package = _goal_workflow_package()
    if package is None:
        return None
    try:
        workflow = package.read_workflow("workflow.md")
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


def _goal_gate_requirements(workflow: WorkflowResource, validation_rules: str) -> str:
    """Render the step's post-hoc gate contract so the executor sees it beforehand.

    ``validation: section: <title>`` is enforced by ``WorkflowRunner`` only *after* the
    step returns.  Without this block a long step can finish all its work and still be
    blocked on a heading it was never told to emit.  The wording lives in the workflow
    package (``gate-template.md``), so it changes without touching code.
    """
    rules = (validation_rules or "").strip()
    sections = required_sections(rules)
    needs_given_when_then = "given" in rules.casefold()
    if not sections and not needs_given_when_then:
        return ""
    headings = ""
    if sections:
        headings = (
            "- Your final response must contain each of these Markdown headings exactly as written, each on its own "
            "line with nothing else on that line:\n"
            + "\n".join(f"  - ## {section}" for section in sections)
            + "\n- A missing, renamed, or suffixed heading blocks the whole step: the workflow will not advance and "
            "this step's work has to be redone.\n"
        )
    acceptance = "- Acceptance criteria must be written as Given / When / Then.\n" if needs_given_when_then else ""
    template = workflow.gate_template
    return _render_template(
        template,
        {"sections": headings, "acceptance": acceptance, "rules": f"- Declared validation rules (verbatim): {rules}"},
    )


def _goal_open_question_policy(workflow: WorkflowResource) -> str:
    """Resolve the open-question policy wording: workflow declaration, then built-in default."""
    if _goal_open_question_mode(workflow) == "default":
        return workflow.open_question_default or _DEFAULT_OPEN_QUESTION_DEFAULT
    return workflow.open_question_block or _DEFAULT_OPEN_QUESTION_BLOCK


def _dedupe_inputs(inputs: Mapping[str, Any], declared: str = "") -> list[tuple[str, Any]]:
    """Render each distinct input body once, under its most meaningful key.

    A completed step stores its artifact under both the declared output names and the
    artifact file name, so rendering every key duplicated whole artifacts in the step
    prompt (the step-07 prompt measured ~130k tokens with roughly half of it repeated
    text).  Among keys sharing one body, the one this step declares in ``input:`` wins;
    otherwise the first occurrence wins.  Nothing unique is dropped.
    """
    wanted = {item.strip() for item in re.split(r"[,\n]", declared) if item.strip()}
    chosen: dict[str, str] = {}
    for name, value in inputs.items():
        if not (isinstance(value, str) and value):
            continue
        current = chosen.get(value)
        if current is None or (name in wanted and current not in wanted):
            chosen[value] = name
    return [
        (name, value)
        for name, value in inputs.items()
        if not (isinstance(value, str) and value) or chosen[value] == name
    ]


def _goal_declarative_prompt(
    workflow: WorkflowResource,
    step_name: str,
    description: str,
    goal_dir: Path,
    inputs: Mapping[str, Any],
    story: Any = None,
    validation_rules: str = "",
    declared_inputs: str = "",
) -> str:
    role = _goal_role_instructions(workflow, step_name)
    gate = _goal_gate_requirements(workflow, validation_rules)
    gate_block = f"{gate}\n\n" if gate else ""
    supplied_inputs = "\n\n".join(f"## {name}\n{value}" for name, value in _dedupe_inputs(inputs, declared_inputs))
    open_question_policy = _goal_open_question_policy(workflow)
    story_context = ""
    if story is not None:
        epic_ref = str(getattr(story, "epic", "") or "")
        story_context = (
            f"Active story: {story.id}"
            + (f" - {story.summary}" if story.summary else "")
            + (f"\nParent epic: {epic_ref}" if epic_ref else "")
            + "\nWork only on this one story; leave all other stories for subsequent increments.\n"
        )
    template = workflow.prompt_template
    return _render_template(
        template,
        {
            "workflow_instructions": workflow.instructions,
            "goal": description,
            "goal_dir": str(goal_dir.resolve()),
            "output_root": str(goal_dir.parent.parent.resolve()),
            "step": step_name,
            "story_context": story_context,
            "role": role,
            "open_question_policy": open_question_policy,
            "inputs": supplied_inputs,
            "gate": gate_block,
        },
    )


def _goal_load_stories(goal_dir: Path, step: Any) -> list[Any]:
    """Load and parse the story list referenced by a story-loop step."""
    source = step.story_loop.strip()
    root = goal_dir.resolve()
    path = (goal_dir / source).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"story source escapes the goal directory: {source}")
    return parse_story_list(path.read_text(encoding="utf-8"))


def _goal_role_instructions(workflow: WorkflowResource, step_name: str) -> str:
    """Load the role contract assigned to a workflow step.

    角色在**传入的 workflow** 上查——此前这里按 step 名重载全局 ``_goal_declarative_workflow()``，
    而调用方本来就持有 workflow：等于把参数静默替换成另一份来源。后果是测试传合成 workflow 时
    仍按**真实** workflow 解析 role，从而依赖本机 ``.heagent/skills/`` 技能库（该目录 gitignore），
    在干净检出（CI）上必然报 "workflow role ... is unavailable" 而红。
    """
    role_name = next((step.role for step in workflow.steps if step.name == step_name), "")
    if not role_name:
        return "No specialized BMad role assigned."
    package = _resolve_skill_package(role_name)
    if package is None:
        raise ValueError(f"workflow role '{role_name}' is unavailable: no skill package named '{role_name}'")
    return package.read_entry().text


@dataclass
class _GoalAdvanceContext:
    """Prepared state for one declarative advance invocation."""

    runner: WorkflowRunner
    mode: str
    description: str
    goal_dir: Path


async def _goal_declarative_prepare(workflow: WorkflowResource) -> tuple[str | None, _GoalAdvanceContext | None]:
    """Load and validate goal state before advancing; a non-None outcome means stop."""
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        click.echo("[goal] no active declarative goal; use /goal new <description>", err=True)
        return _GOAL_FAILED, None
    try:
        description = _goal_description(goal_dir)
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] declarative requirement document is invalid: {exc}", err=True)
        return _GOAL_FAILED, None
    if not description:
        click.echo("[goal] declarative requirement document has no title", err=True)
        return _GOAL_FAILED, None
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
    except WorkflowCheckpointError as exc:
        click.echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
        return _GOAL_FAILED, None
    if runner.done:
        click.echo("[goal] declarative workflow is already complete", err=True)
        return _GOAL_DONE, None
    # A pause/cancellation is persisted as a non-completed Runner state. Resume
    # is explicit at the command boundary, then this call may continue the step.
    if runner.state.status is WorkflowStatus.WAITING_USER:
        click.echo("[goal] declarative workflow is paused; use /goal resume first", err=True)
        return _GOAL_WAITING, None
    if runner.state.status in {WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
        click.echo(f"[goal] declarative workflow is {runner.state.status.value}: {runner.state.reason}", err=True)
        return _GOAL_FAILED, None
    try:
        mode = _goal_checkpoint_mode(workflow)
    except ValueError as exc:
        click.echo(f"[goal] invalid checkpoint mode: {exc}", err=True)
        return _GOAL_FAILED, None
    return None, _GoalAdvanceContext(
        runner=runner,
        mode=mode,
        description=description,
        goal_dir=goal_dir,
    )


async def _goal_execute_step(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    description: str,
    goal_dir: Path,
    inputs: Mapping[str, Any],
    step: Any,
    story: Any = None,
) -> WorkflowStepResult:
    """Execute one declared step through a fresh SubAgent session."""
    prompt = _goal_declarative_prompt(
        workflow,
        step.name,
        description,
        goal_dir,
        inputs,
        story=story,
        validation_rules=step.validation_rules,
        declared_inputs=step.input,
    )
    result = await _goal_session(
        provider,
        engine,
        prompt + f"\n\n{step.instructions}",
        metadata={
            "goal_id": goal_dir.name,
            "goal_kind": "declarative",
            "workflow_step": step.name,
            "workflow_story": story.id if story is not None else None,
            "purpose": (step.role or step.name) + (f" / {story.id}" if story is not None else ""),
        },
        max_iterations=step.max_iterations or None,
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
        atomic_write_text(_goal_step_artifact_path(goal_dir, step, story), output_text)
    except OSError as exc:
        return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=f"failed to persist step output: {exc}")
    return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output=result.output)


async def _goal_declarative_advance(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
) -> str:
    """Advance deterministically through steps and resolve completed checkpoints."""
    outcome, context = await _goal_declarative_prepare(workflow)
    if outcome is not None or context is None:
        return outcome or _GOAL_FAILED
    runner = context.runner
    mode = context.mode
    description = context.description
    goal_dir = context.goal_dir

    async def execute_step(step: Any, story: Any = None) -> WorkflowStepResult:
        return await _goal_execute_step(
            provider,
            engine,
            workflow,
            description,
            goal_dir,
            inputs,
            step,
            story,
        )

    # Input declarations describe the context supplied by this deterministic CLI
    # boundary. Artifact names from completed steps remain available on resume.
    while True:
        try:
            user_responses = _goal_user_responses(goal_dir)
        except OSError as exc:
            click.echo(f"[goal] declarative requirement document is unreadable: {exc}", err=True)
            return _GOAL_FAILED
        inputs: dict[str, Any] = {
            "user intent": description,
            "user responses": user_responses or "No user response has been recorded.",
            "existing project context": load_context_files(os.getcwd())
            or "No project context file was found; inspect the current workspace before making assumptions.",
            **runner.state.outputs,
        }
        active_step = runner.workflow.steps[runner.state.active_step]
        stories = None
        if active_step.story_loop.strip():
            try:
                stories = _goal_load_stories(goal_dir, active_step)
            except (OSError, ValueError) as exc:
                click.echo(f"[goal] declarative story source failed: {exc}", err=True)
                return _GOAL_FAILED
        try:
            result = await runner.run_step(execute_step, inputs=inputs, stories=stories)
        except (WorkflowCheckpointError, ValueError, TypeError) as exc:
            click.echo(f"[goal] declarative workflow failed: {exc}", err=True)
            return _GOAL_FAILED
        story_label = f" story={result.story_id}" if result.story_id else ""
        click.echo(
            f"[goal] declarative workflow: step={result.step_index if result.step_index is not None else '-'}"
            f"{story_label} status={result.status.value}",
            err=True,
        )
        if result.status is WorkflowStatus.COMPLETED:
            return _GOAL_DONE
        if result.status is WorkflowStatus.PENDING:
            if mode == "auto":
                continue
            return _GOAL_ADVANCED
        if result.status is not WorkflowStatus.WAITING_USER:
            if result.status is WorkflowStatus.BLOCKED:
                reason = result.reason or runner.state.reason or "the step output failed its gate"
                click.echo(f"[goal] step blocked: {reason}", err=True)
                click.echo(
                    "[goal] the step must be re-run: record a human acknowledgement with "
                    "`/goal resume <说明>` (the active step then executes again); `/goal status` shows the state.",
                    err=True,
                )
            return _GOAL_FAILED

        # WAITING_USER from a completed step is a checkpoint decision. An
        # interrupted callback also uses WAITING_USER, but must never be treated
        # as implicit approval.
        step_checkpoint = result.step_index is not None and (result.step_index - 1) in runner.state.completed_steps
        story_checkpoint = result.story_id is not None and result.story_id in runner.state.completed_stories
        checkpoint_completed = step_checkpoint or story_checkpoint
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
    base_id = _goal_project_id(description)
    goal_id = base_id
    goal_dir = _GOALS_DIR / goal_id
    for suffix in [""] + [f"-{chr(ord('a') + index)}" for index in range(26)]:
        if not goal_dir.exists():
            break
        goal_id = base_id + suffix
        goal_dir = _GOALS_DIR / goal_id
    else:
        click.echo("[goal] unable to allocate a unique project goal id", err=True)
        return
    try:
        goal_document = _goal_document(description, goal_id)
        _goal_document_title(goal_document)
        atomic_write_text(_goal_document_path(goal_dir), goal_document)
        atomic_write_text(_GOALS_DIR / "current", goal_id)
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] failed to persist declarative goal: {exc}", err=True)
        return
    if previous is not None and cron_store is not None:
        _goal_auto_remove(cron_store, previous.name)
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
            if response:
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
        for _ in range(workflow.max_rounds):
            async with _goal_mutex():
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
    schedule = args or workflow.auto_schedule or _GOAL_AUTO_DEFAULT_CRON
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


_GOAL_SUBCOMMAND_NAMES = ("new", "next", "run", "status", "pause", "resume", "auto", "reset")


def _goal_typo_subcommand(args: str) -> str | None:
    """Map a single-token typo of a known subcommand to that subcommand.

    ``/goal <anything else>`` starts a new goal, so a hand slip such as ``/goal resume\\``
    silently burned a whole goal's first step.  Only single-token inputs close to a
    known subcommand are treated as typos; multi-word descriptions pass through.
    """
    parts = args.split()
    if len(parts) != 1:
        return None
    matches = difflib.get_close_matches(parts[0].casefold(), _GOAL_SUBCOMMAND_NAMES, n=1, cutoff=0.8)
    return matches[0] if matches else None


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
            async with _goal_mutex():
                await _goal_declarative_new(provider, engine, workflow, rest, cron_store=cron_store)
    elif head in ("next", "status", "reset", "run", "pause") and rest:
        _goal_usage()
    elif head == "next":
        async with _goal_mutex():
            await _goal_declarative_advance(provider, engine, workflow)
    elif head == "run":
        await _goal_declarative_run(provider, engine, workflow)
    elif head == "status":
        await _goal_declarative_status(workflow)
    elif head == "pause":
        await _goal_declarative_pause_resume(workflow, resume=False)
    elif head == "resume":
        async with _goal_mutex():
            if await _goal_declarative_pause_resume(workflow, resume=True, response=rest):
                await _goal_declarative_advance(provider, engine, workflow)
    elif head == "audit":
        click.echo("[goal] audit subcommand has been removed; supported subcommands are listed below.", err=True)
        _goal_usage()
    elif head == "reset":
        async with _goal_mutex():
            _goal_reset()
    elif head == "auto":
        await _goal_declarative_auto(workflow, rest, cron_store)
    elif (intended := _goal_typo_subcommand(args)) is not None:
        click.echo(f"[goal] unknown subcommand {args.strip()!r}; did you mean `/goal {intended}`?", err=True)
        _goal_usage()
    else:
        async with _goal_mutex():
            await _goal_declarative_new(provider, engine, workflow, args.strip(), cron_store=cron_store)


def _goal_usage() -> None:
    """打印 /goal 子命令用法表（缺参 / 未实现 / 拼错时）。"""
    click.echo(
        "/goal 用法：\n"
        "  /goal <目标描述>      新建 goal 并执行 planning 规程\n"
        "  /goal new <目标描述>  同上（显式 new 形式）\n"
        "  /goal next            推进下一条 story（每步全新会话）\n"
        "  /goal status          查看进度\n"
        "  /goal reset           清除 current 指针（goal 目录保留）\n"
        "  /goal run             连续推进 goal（步数上限由 workflow 的 max_rounds 声明；Ctrl+C 可中断）\n"
        "  /goal resume [回复]   记录用户回答并继续 waiting_user 步骤\n"
        "  /goal auto [cron]     注册 cron 自动推进（默认 */15 * * * *；off 注销）",
        err=True,
    )


def _goal_active_md() -> Path | None:
    """解析活跃 goal 的需求文档路径；指针缺失/解码失败返回 None，内容非法显性报错。"""
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
    # 把围栏外任意文件当需求文档注入 LLM prompt（仿 sandbox_session_dir 先例）。
    if not _goal_id_is_valid(goal_id):
        click.echo(f"[goal] current 指针内容非法：{goal_id!r}（须为英文字母 project id）。", err=True)
        return None
    goals_root = _GOALS_DIR.resolve()
    goal_root = (_GOALS_DIR / goal_id).resolve()
    if not goal_root.is_relative_to(goals_root):
        click.echo("[goal] current 指针解析后越过 goals 根目录。", err=True)
        return None
    return _goal_document_path(goal_root)


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
        announcer=SUBAGENT_ANNOUNCER,
    )
    try:
        return await agent.run(prompt)
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("[goal] 已中断：状态在盘（require.md），/goal next 可续跑。", err=True)
        return None


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
    try:
        async with _goal_mutex():
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
    except OSError:
        # 另一进程正持 goal 锁：显性失败并提示，cron 下一 tick 自动重试。
        click.echo("[goal] 另一进程正在推进 goal（锁等待超时）；本 tick 跳过，下一 tick 自动重试。", err=True)


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
        try:
            await _goal_declarative_dispatch(provider, engine, declarative_workflow, args, cron_store=cron_store)
        except OSError:
            # 跨进程文件锁等待超时：显性失败（显性失败原则，不静默降级）。
            click.echo(
                "[goal] 另一进程正在推进同一 goal（.heagent/goal.lock 等待超时）；本次未执行，请稍后重试。",
                err=True,
            )
        return
    skill_id = get_settings().goal_workflow_skill
    if skill_id:
        hint = f"Create {_GOAL_SKILLS_ROOT / skill_id / 'workflow.md'} (with a SKILL.md declaring its canonical_id) "
        "to configure goal execution."
    else:
        # 显式置空不会早于此崩溃（resolve("") 被捕获返回 None）；pathlib 丢弃空段会拼出
        # catalog 永远解析不到的 ``.heagent/skills/workflow.md``，故单独提示配置错误。
        hint = "GOAL_WORKFLOW_SKILL is set to an empty package id; unset it or set a valid skill package id."
    click.echo(
        "[goal] workflow.md is required; the legacy story-board flow has been removed. " + hint,
        err=True,
    )
    return
