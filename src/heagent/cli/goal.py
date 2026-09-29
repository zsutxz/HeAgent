"""/goal command family: declarative workflow dispatch, cron auto-advance, and goal mutex."""

from __future__ import annotations

import asyncio
import difflib
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import click

from heagent.cli.display import SUBAGENT_ANNOUNCER
from heagent.config import get_settings, resolve_runtime_config
from heagent.context.loader import load_context_files
from heagent.context.window_reset import WindowResetConfig
from heagent.cron.expr import cron_matches
from heagent.engine import (
    StorySpec,
    ToolExecutionMode,
    WorkflowCheckpointError,
    WorkflowResource,
    WorkflowStatus,
    WorkflowStepResult,
)
from heagent.goal.application import (
    _GOAL_SKILLS_ROOT,
    _GoalAdvanceContext,
    advance,
    checkpoint_mode,
    checkpoint_store,
    declarative_prompt,
    external_checkpoint_dir,
    initialize_checkpoint_workspace,
    pause_resume,
)
from heagent.goal.application import (
    resolve_skill_package as _resolve_skill_package,
)
from heagent.goal.application import (
    restore_runner as _goal_declarative_runner,
)
from heagent.goal.application import (
    validate_goal_workflow as _validate_goal_workflow,
)
from heagent.goal.doctor import diagnose_workflow
from heagent.goal.document import (
    _GOALS_DIR,
    _goal_description,
    _goal_document,
    _goal_document_path,
    _goal_document_title,
    _goal_id_is_valid,
    _goal_record_user_response,
    _goal_step_artifact_path,
    _goal_user_responses,
)
from heagent.goal.evidence import (
    CommandOutcome,
    EvidenceError,
    GitEvidence,
    build_command_evidence,
    classify_command_result,
    evidence_store,
    new_evidence_id,
)
from heagent.goal.naming import llm_project_id
from heagent.goal.quality_gates import verify_step
from heagent.goal.status_view import project_status_view
from heagent.goal.workflow_loader import SkillWorkflowError, read_workflow
from heagent.pub.persist import atomic_write_text, file_lock
from heagent.pub.types import ToolCall, ToolResult
from heagent.pub.workspace import WorkspacePaths

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from heagent.agent.sub import SubAgentResult
    from heagent.cron.jobs import JobStore
    from heagent.engine import EngineContainer
    from heagent.goal.evidence import CommandEvidence
    from heagent.goal.quality_gates import GovernedCommandPort, VerificationReport
    from heagent.memory.skill_packages import SkillPackage
    from heagent.providers.base import BaseProvider


logger = logging.getLogger(__name__)

# 测试仍经 ``heagent.cli.goal`` 访问的 re-export 符号：Phase 3 起确定性内核迁
# goal/application 后，这两个符号在本模块已无内部调用点，靠 ``__all__`` 钉住
# ruff F401（防自动移除）与 mypy no_implicit_reexport 的再导出语义。
__all__ = ["_goal_record_user_response", "_goal_user_responses"]

_GOAL_AUTO_DEFAULT_CRON = "*/15 * * * *"
_GOAL_AUTO_PREFIX = "goal-advance "
_goal_auto_lock = asyncio.Lock()

# goal 域跨进程锁：竞态是「读 current 指针 → 读状态 → 推进 → 写 checkpoint /
# workflow.json / brief.md」的整段读改写，per-file 锁防不了「两进程从同一状态各自
# 推进后互相覆盖」，故 goal 域一把域级锁。锁文件随 cwd 锚定（与 _GOALS_DIR 同锚定
# 方式），落在 .heagent/ 运行时状态区（见下文目录注释），不污染 _he-output/ 产物树。
_GOAL_LOCK_PATH = Path(".heagent/goal.lock")
_GOAL_LOCK_TIMEOUT = 5.0  # 并发方快速失败；cron 下一 tick 自动重试，手动方收到明确提示

# 工作流执行状态词汇与推进轮数上限：随编排分支（advance/execute 状态机）变，
# 不随文档约定变，故留本模块（goal/document.py 只做文档与命名，见其 docstring）。
# 工作流包 id 的默认值只在 Settings.goal_workflow_skill 一处声明；本模块一律从配置读。
# 技能库根（_GOAL_SKILLS_ROOT）与 open-question 兜底文案已随确定性内核迁
# goal/application.py，经顶部 import 保持本命名空间可用（Phase 3）。
_GOAL_ADVANCED = "advanced"
_GOAL_DONE = "done"
_GOAL_FAILED = "failed"
_GOAL_WAITING = "waiting"


#: ``/goal`` 用户可见输出的**消息 sink**（GUI 用）。
#: 默认 ``None`` ⇒ 仍走 ``click.echo(..., err=True)``，CLI 行为逐字不变。
#: 为什么需要它：GUI 原先靠 ``contextlib.redirect_stderr`` 截获这些文案，但那会把**整个 stderr**
#: 一起吞掉——包括 ``logging`` 记录与第三方库输出，全部倒进对话区（台账 A4b）。
_MESSAGE_SINK: ContextVar[Callable[[str], None] | None] = ContextVar("goal_message_sink", default=None)


def _echo(message: str, *, err: bool = True) -> None:
    """``/goal`` 全部用户可见输出的**唯一出口**（历史 40+ 处 ``click.echo`` 收敛于此）。

    有 sink（GUI）时逐条投递；否则与历史行为逐字一致地写 stderr。``err`` 只为保持调用点原样
    （``click.echo(..., err=True)``）而保留，sink 路径忽略它。
    """
    sink = _MESSAGE_SINK.get()
    if sink is not None:
        sink(message)
        return
    click.echo(message, err=err)


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

# 需求文档与命名层（slug 词表 / goal_id 规则 / 目录命名 / brief.md 生成与增量更新）
# 已拆至 goal/document.py（cli/wiring.py 先例：文档约定与执行编排变化原因不同），见顶部
# re-export——测试经 heagent.cli.goal 导入这些符号，内部引用点继续按模块全局名解析。


def _goal_checkpoint_mode(workflow: WorkflowResource) -> str:
    """Resolve checkpoint policy: workflow declaration, then env-backed settings.

    确定性内核（goal/application.checkpoint_mode）不读配置；settings 回退值在此注入。
    """
    return checkpoint_mode(workflow, get_settings().goal_checkpoint_mode)


def _goal_checkpoint_prompt() -> bool:
    """Ask for checkpoint approval only when stdin is an interactive TTY."""
    if not sys.stdin.isatty():
        _echo("[goal] waiting for user response; use /goal resume <answer> to continue", err=True)
        return False
    try:
        approved = bool(click.confirm("[goal] checkpoint complete; continue to the next step?", default=False))
        if not approved:
            _echo("[goal] checkpoint paused; use /goal resume <answer> to continue", err=True)
        return approved
    except (EOFError, KeyboardInterrupt, click.Abort):
        _echo("[goal] checkpoint paused; use /goal resume <answer> to continue", err=True)
        return False


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
        workflow = read_workflow(package, "workflow.md")
        _validate_goal_workflow(workflow)
        return workflow
    except (SkillWorkflowError, ValueError, OSError) as exc:
        raise ValueError(f"declarative workflow configuration is invalid: {exc}") from exc


def _goal_declarative_active_dir() -> Path | None:
    goal_md = _goal_active_md()
    return goal_md.parent if goal_md is not None else None


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
    """渲染步骤执行提示词；确定性装配在 goal/application，settings 回退在此注入。"""
    return declarative_prompt(
        workflow,
        step_name,
        description,
        goal_dir,
        inputs,
        story=story,
        validation_rules=validation_rules,
        declared_inputs=declared_inputs,
        open_question_fallback=get_settings().goal_open_question_mode,
    )


async def _goal_declarative_prepare(workflow: WorkflowResource) -> tuple[str | None, _GoalAdvanceContext | None]:
    """Load and validate goal state before advancing; a non-None outcome means stop."""
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        _echo("[goal] no active declarative goal; use /goal new <description>", err=True)
        return _GOAL_FAILED, None
    try:
        description = _goal_description(goal_dir)
    except (OSError, ValueError) as exc:
        _echo(f"[goal] declarative requirement document is invalid: {exc}", err=True)
        return _GOAL_FAILED, None
    if not description:
        _echo("[goal] declarative requirement document has no title", err=True)
        return _GOAL_FAILED, None
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
    except (WorkflowCheckpointError, ValueError) as exc:
        _echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
        return _GOAL_FAILED, None
    if runner.done:
        _echo("[goal] declarative workflow is already complete", err=True)
        return _GOAL_DONE, None
    # A pause/cancellation is persisted as a non-completed Runner state. Resume
    # is explicit at the command boundary, then this call may continue the step.
    if runner.state.status is WorkflowStatus.WAITING_USER:
        _echo("[goal] declarative workflow is paused; use /goal resume first", err=True)
        return _GOAL_WAITING, None
    if runner.state.status in {WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
        _echo(f"[goal] declarative workflow is {runner.state.status.value}: {runner.state.reason}", err=True)
        return _GOAL_FAILED, None
    try:
        mode = _goal_checkpoint_mode(workflow)
    except ValueError as exc:
        _echo(f"[goal] invalid checkpoint mode: {exc}", err=True)
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
    gate_reason = await _goal_structured_gate(engine, workflow, step, story, goal_dir)
    if gate_reason:
        return WorkflowStepResult(status=WorkflowStatus.BLOCKED, reason=gate_reason)
    return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output=result.output)


def _workflow_event_emitter(engine: EngineContainer | None) -> Callable[[str], None] | None:
    """workflow 步骤事件的入口侧发射器（Phase 5 C1）：绑 EngineContainer.events 总线。

    ``engine=None``（部分库消费者）返回 None = 不发事件；观测失败由
    ``WorkflowRunner._emit_step_event`` 隔离，不影响步骤执行。
    """
    if engine is None:
        return None

    def emit(kind: str, *, details: dict[str, Any] | None = None) -> None:
        engine.events.publish(kind, details=details)

    return emit


async def _goal_declarative_advance(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
) -> str:
    """推进声明式工作流：准备 → 注入端口调 use-case（goal/application.advance）→ 渲染 messages。

    确定性推进循环已收敛 goal/application（Phase 3）；本函数是缝宿主（`_goal_session`
    缝链的调用方）与渲染边界：messages 逐行经 _echo(err=True) 原文输出。
    """
    outcome, context = await _goal_declarative_prepare(workflow)
    if outcome is not None or context is None:
        return outcome or _GOAL_FAILED

    async def execute_step(
        inputs: Mapping[str, Any],
        step: Any,
        story: Any = None,
    ) -> WorkflowStepResult:
        return await _goal_execute_step(
            provider,
            engine,
            workflow,
            context.description,
            context.goal_dir,
            inputs,
            step,
            story,
        )

    paths = WorkspacePaths.from_root((engine.workspace_root if engine else None) or os.getcwd())
    result = await advance(
        context,
        execute_step,
        confirm_checkpoint=_goal_checkpoint_prompt,
        load_project_context=lambda: load_context_files(str(paths.root)),
        emit=_workflow_event_emitter(engine),
    )
    for message in result.messages:
        _echo(message, err=True)
    return result.status.value


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
    base_id = await llm_project_id(provider, description)
    workspace = WorkspacePaths.from_root((engine.workspace_root if engine else None) or os.getcwd())
    goal_id = base_id
    goal_dir = _GOALS_DIR / goal_id
    for suffix in [""] + [f"-{chr(ord('a') + index)}" for index in range(26)]:
        if not goal_dir.exists() and not external_checkpoint_dir(goal_id, workspace.root).exists():
            break
        goal_id = base_id + suffix
        goal_dir = _GOALS_DIR / goal_id
    else:
        _echo("[goal] unable to allocate a unique project goal id", err=True)
        return
    try:
        goal_document = _goal_document(description, goal_id)
        _goal_document_title(goal_document)
        atomic_write_text(_goal_document_path(goal_dir), goal_document)
        paths = WorkspacePaths.from_root((engine.workspace_root if engine else None) or os.getcwd())
        initialize_checkpoint_workspace(goal_dir, paths.root)
        atomic_write_text(_GOALS_DIR / "current", goal_id)
    except (OSError, ValueError) as exc:
        _echo(f"[goal] failed to persist declarative goal: {exc}", err=True)
        return
    if previous is not None and cron_store is not None:
        _goal_auto_remove(cron_store, previous.name)
    await _goal_declarative_advance(provider, engine, workflow)


async def _goal_declarative_doctor(workflow: WorkflowResource) -> None:
    """Run the read-only preflight and render its structured report.

    The checkpoint directory is resolved from the active goal (legacy goals keep a
    local directory; new goals persist a workspace binding). Without an active goal
    the workflow and its role packages are still checked — the preflight never
    invents a target path just to have something to probe.
    """
    package = _goal_workflow_package()
    if package is None:
        _echo("[goal] doctor: workflow package is unavailable", err=True)
        return
    goal_dir = _goal_declarative_active_dir()
    try:
        checkpoint_dir = checkpoint_store(goal_dir).base_dir if goal_dir is not None else None
        report = diagnose_workflow(workflow, package, _resolve_skill_package, checkpoint_dir=checkpoint_dir)
    except (OSError, ValueError) as exc:
        _echo(f"[goal] doctor: {exc}", err=True)
        return
    summary = report.render()
    if report.problems and report.ok:
        summary = f"{summary} (warning; the workflow can still run)"
    _echo(f"[goal] doctor: {summary}", err=True)


async def _goal_declarative_status(workflow: WorkflowResource) -> None:
    """Render the single status projection; CLI, GUI and cron share this model."""
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        _echo("[goal] no active declarative goal", err=True)
        return
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
    except (WorkflowCheckpointError, ValueError) as exc:
        _echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
        return
    for line in project_status_view(
        runner.state,
        workflow,
        goal_id=goal_dir.name,
        fields=workflow.status_fields,
    ).render():
        _echo(line, err=True)


async def _goal_declarative_pause_resume(workflow: WorkflowResource, *, resume: bool, response: str = "") -> bool:
    """Persist a pause or resume and report whether a step may now execute.

    决策内核在 goal/application.pause_resume；本函数只做指针解析与 message 渲染。
    """
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        _echo("[goal] no active declarative goal", err=True)
        return False
    outcome = await pause_resume(workflow, goal_dir, resume=resume, response=response)
    if outcome.message:
        _echo(outcome.message, err=True)
    return outcome.proceed


# ── /goal verify 与结构化完成门（Story 51-4）───────────────────────────────

# 受治理重跑的命令超时（秒）：声明验证可能是长测试套件，工具的 120s 默认会把长套件
# 钉成 TIMEOUT——显式给足上界（review #16；不新增顶层配置键）。
_VERIFY_COMMAND_TIMEOUT_SECONDS = 600


def _goal_verify_workspace(engine: EngineContainer | None) -> Path:
    """/goal 验证工作区根的**唯一解析点**（review #1）：受治理执行在哪里跑（``cd`` 前缀）、
    证据 ``cwd`` 记录什么、求值器拿什么当期望值——三处都取这一个值，永不各自解析。"""
    return Path(WorkspacePaths.from_root((engine.workspace_root if engine else None) or os.getcwd()).root).resolve()


def _workspace_cd_prefix(workspace: Path) -> str:
    """受治理重跑的工作区定位前缀：让声明命令在**工作区根**执行（git.py ``_run_git`` 的
    ``cwd=workspace_root()`` 先例；本端口不改 sandbox ``CommandRunner`` 契约）。剥离侧在
    ``goal/quality_gates._strip_workspace_cd``，两个格式必须同源。"""
    text = str(workspace)
    if os.name == "nt":
        return f'cd /d "{text}" && '
    return f"cd '{text.replace(chr(39), chr(39) + chr(92) + chr(39))}' && "


async def _goal_verify_report(
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    step: Any,
    story: Any,
    goal_dir: Path,
    *,
    rerun: bool,
) -> VerificationReport:
    """求值一个步骤 / Story 的结构化子句（``/goal verify`` 与完成门共用同一次实现）。

    证据 = ``<goal_dir>/evidence/``（唯一位置解析点）；产物 = 工作区文件；Git = 只读端口
    的实时查询（仓库不可用返回空证据：变更集为空，git 子句与 ``git-changes`` 门照实
    显性未过）；步骤输出 = 已持久化的步骤产物（section 门禁复验的输入，缺失由求值器
    显性记未过）。workspace 经 :func:`_goal_verify_workspace`（唯一解析点，review #1）。
    """
    workspace = _goal_verify_workspace(engine)
    return await verify_step(
        step,
        store=evidence_store(goal_dir),
        goal_id=goal_dir.name,
        story_id=story.id if story is not None else None,
        workspace=workspace,
        workflow_id=workflow.name,
        output_text=await _goal_step_output_text(goal_dir, step, story),
        git_evidence=await _goal_live_git_evidence(workspace),
        rerun=rerun,
        run_command=_goal_verify_command_runner(engine) if rerun else None,
    )


async def _goal_structured_gate(
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    step: Any,
    story: Any,
    goal_dir: Path,
) -> str:
    """完成门（Story 51-4）：步骤产物落盘后按声明子句求值；未通过返回 BLOCKED 理由。

    声明的验证命令在此**受控重跑**（经治理链、落证据）——完成判定依赖真实 Evidence，
    未运行或运行失败的声明验证不能放行步骤（AD-5/AD-6）。未声明任何结构化子句的步骤
    返回空串（老包零行为变化）。BLOCKED 经 ``WorkflowRunner`` 的 ``GATE_FAILED`` 事件落
    状态，本函数不直接改 Runner 状态。求值自身的故障（``EvidenceError`` / ``OSError``）
    同归「未通过」并写进理由——完成门不崩整个 run，也不静默放行（review #4）。
    """
    if not step.validation_clauses.declared:
        return ""
    try:
        report = await _goal_verify_report(engine, workflow, step, story, goal_dir, rerun=True)
    except (EvidenceError, OSError) as exc:
        return f"quality gate failed for step '{step.name}': gate evaluation error: {exc}"
    if report.passed:
        return ""
    for line in report.render():
        _echo(line, err=True)
    failures = [
        f"{item.kind.value}: {item.target}" + (f" — {item.reason}" if item.reason else "") for item in report.failed
    ]
    # failures 与 errors **分别**限额：求值错误不被失败子句挤到无声丢光（review #17）。
    parts = [*failures[:5], *report.errors[:5]]
    if len(failures) > 5:
        parts.append(f"…({len(failures) - 5} more failed clause(s) not shown)")
    if len(report.errors) > 5:
        parts.append(f"…({len(report.errors) - 5} more evaluation error(s) not shown)")
    return f"quality gate failed for step '{step.name}': {'; '.join(parts)}"


async def _goal_declarative_verify(
    workflow: WorkflowResource,
    engine: EngineContainer | None,
    args: str,
) -> None:
    """/goal verify：只检查或受控重跑声明里列出的验证，绝不重跑实现步骤、不改 Runner 状态。

    ``args`` 为空 = 只检查（读证据 / 产物 / 只读 Git）；``run`` = 先受控重跑声明的验证命令
    再检查。对 BLOCKED / FAILED 状态同样可用（恢复后先复核证据是合法诉求）。
    求值路径的 ``EvidenceError`` / ``OSError`` 在此收口为用户可见失败——它们**不是** goal
    域锁竞争，不得落进外层的「另一进程正在推进」误诊文案（review #4）。
    """
    async with _goal_mutex():
        goal_dir = _goal_declarative_active_dir()
        if goal_dir is None:
            _echo("[goal] no active declarative goal; use /goal new <description>", err=True)
            return
        try:
            runner = await _goal_declarative_runner(workflow, goal_dir)
        except (WorkflowCheckpointError, ValueError) as exc:
            _echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
            return
        if runner.done:
            _echo("[goal] declarative workflow is already complete; there is no active step to verify", err=True)
            return
        # 显性守卫（review #14）：活动步越界 / 缺失（如 new 后尚未落任何 checkpoint 的残状）
        # 显性提示返回，不 TypeError、不静默取 min() 兜底。
        active_step = runner.state.active_step
        if active_step is None or active_step >= len(workflow.steps):
            _echo("[goal] verify: the workflow has no active step to verify yet", err=True)
            return
        step = workflow.steps[active_step]
        story_id = runner.state.active_story
        # 跨模块数据用引擎模型（AD-4）：StorySpec 的 (id, epic) 即 `_goal_step_artifact_path`
        # 消费的鸭子契约；不用裸 SimpleNamespace（review #13）。
        story = StorySpec(id=story_id, epic=runner.state.active_epic) if story_id else None
        try:
            report = await _goal_verify_report(engine, workflow, step, story, goal_dir, rerun=args == "run")
        except (EvidenceError, OSError) as exc:
            _echo(f"[goal] verify failed: {exc}", err=True)
            return
        for line in report.render():
            _echo(line, err=True)


async def _goal_step_output_text(goal_dir: Path, step: Any, story: Any) -> str | None:
    """已持久化的步骤产物文本（section 门禁复验输入）；缺失 / 不可读返回 ``None``（显性未过）。"""
    try:
        return await asyncio.to_thread(_goal_step_artifact_path(goal_dir, step, story).read_text, encoding="utf-8")
    except (OSError, ValueError):
        return None


async def _goal_live_git_evidence(workspace: Path) -> GitEvidence:
    """只读 Git 端口的实时查询（白名单内确定性查询，AD-11）；仓库不可用时返回空证据。"""
    from heagent.goal.git_port import GitPortError, ReadOnlyGitPort  # noqa: PLC0415

    try:
        return await ReadOnlyGitPort(workspace).evidence()
    except GitPortError:
        return GitEvidence()


def _goal_verify_command_runner(engine: EngineContainer | None) -> GovernedCommandPort | None:
    """受控重跑端口：声明命令经治理链执行并证据化。

    ``engine`` 缺席（库消费者 / 部分测试）时返回 ``None``——求值器把「无法受控重跑」记为
    显性失败，绝不静默放行。
    """
    if engine is None:
        return None

    async def run(command: str) -> CommandEvidence:
        return await _run_governed_verify_command(engine, command)

    return run


async def _run_governed_verify_command(engine: EngineContainer, command: str) -> CommandEvidence:
    """一次声明命令的受治理执行：``PolicyEngine 裁决 → ToolExecutor（含 SafetyGuard）→ shell handler``。

    治理 = 这四层，**到此为止**：本端口不经 ``agent/tool_execution`` 的 PreToolUse /
    PostToolUse hooks（那是 AgentLoop 的模型工具路径；verify 是宿主发起，hooks 不在链上）
    ——如实声明覆盖面，不冒称（review #15）。结果未以受治理 ``exit_code=`` 形状到达
    （策略 / 审批阻断、guard 拦截、handler 异常）一律记
    :attr:`CommandOutcome.POLICY_BLOCKED`——门禁语义上与失败同归「未通过」，不从结果文本
    猜测具体分层（与 ``goal/evidence.classify_command_result`` 的不猜测立场一致）。

    声明命令在**工作区根**执行（review #1）：``_workspace_cd_prefix`` 的 ``cd`` 前缀包装
    （git.py ``_run_git`` 的 ``cwd=workspace_root()`` 先例；不改 sandbox ``CommandRunner``
    契约）。证据 ``cwd`` 记 :func:`_goal_verify_workspace` 的同一取值——与求值器期望值同源。
    """
    from heagent.tools.registry import ToolRegistry  # noqa: PLC0415
    from heagent.tools.safety import SafetyGuard  # noqa: PLC0415

    started = time.perf_counter()
    workspace = _goal_verify_workspace(engine)
    call = ToolCall(
        id=f"verify-{new_evidence_id()}",
        name="shell",
        arguments={
            "command": f"{_workspace_cd_prefix(workspace)}{command}",
            "timeout": _VERIFY_COMMAND_TIMEOUT_SECONDS,
        },
    )
    run_context = engine.create_run_context(metadata={"purpose": "/goal verify controlled re-run"})
    registry = ToolRegistry.get()
    handler = registry.get_handler("shell")
    if handler is None:
        missing = ToolResult(tool_call_id=call.id, content="shell tool is not registered", is_error=True)
        return build_command_evidence(call, missing, cwd=str(workspace), outcome=CommandOutcome.POLICY_BLOCKED)
    verdict = engine.policy.evaluate_tool_call(call, context=run_context, schema=registry.get_schema("shell"))
    executable = cast("Callable[..., Any]", handler)

    async def invoke(call: ToolCall) -> object:
        produced = executable(**call.arguments)
        if asyncio.iscoroutine(produced):
            return await produced
        return produced

    # 容器构造期快照优先（review #22），缺席（手工构造的容器）才回退现场解析。
    runtime = engine.runtime_config or resolve_runtime_config()
    result = await engine.executor.execute(
        call=call,
        verdict=verdict,
        guard=SafetyGuard(blocked_tools=list(runtime.safety_blocked_tools)),
        handler=invoke,
        run_context=run_context,
    )
    duration_ms = max(int((time.perf_counter() - started) * 1000), 0)
    if verdict.mode in {ToolExecutionMode.BLOCKED, ToolExecutionMode.APPROVAL_REQUIRED}:
        outcome = CommandOutcome.POLICY_BLOCKED
    else:
        try:
            outcome = classify_command_result(result)
        except EvidenceError:
            outcome = CommandOutcome.POLICY_BLOCKED
    return build_command_evidence(call, result, cwd=str(workspace), duration_ms=duration_ms, outcome=outcome)


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
        _echo("[goal] declarative workflow interrupted; use /goal resume to continue", err=True)


async def _goal_declarative_auto(
    workflow: WorkflowResource,
    args: str,
    cron_store: JobStore | None,
) -> None:
    goal_dir = _goal_declarative_active_dir()
    if args == "off":
        if cron_store is None or goal_dir is None:
            _echo("[goal] cron is not enabled or there is no active declarative goal", err=True)
            return
        _echo(f"[goal] auto disabled: removed {_goal_auto_remove(cron_store, goal_dir.name)} job(s)", err=True)
        return
    if cron_store is None or goal_dir is None:
        _echo("[goal] cron is not enabled or there is no active declarative goal", err=True)
        return
    schedule = args or workflow.auto_schedule or _GOAL_AUTO_DEFAULT_CRON
    try:
        fields = schedule.split()
        if len(fields) != 5 or any(not field or any(not part.strip() for part in field.split(",")) for field in fields):
            raise ValueError("cron must contain five non-empty fields")
        cron_matches(schedule, datetime.now(UTC))
    except (TypeError, ValueError) as exc:
        _echo(f"[goal] invalid cron expression: {exc}", err=True)
        return
    _goal_auto_remove(cron_store, goal_dir.name)
    job = cron_store.create_job(f"{_GOAL_AUTO_PREFIX}{goal_dir.name}", schedule)
    cron_store.add(job)
    _echo(f"[goal] declarative auto registered: {job.id} workflow={workflow.name}", err=True)


_GOAL_SUBCOMMAND_NAMES = ("new", "next", "run", "status", "pause", "resume", "auto", "reset", "doctor", "verify")


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
    elif head in ("next", "status", "reset", "run", "pause", "doctor") and rest:
        _goal_usage()
    elif head == "next":
        async with _goal_mutex():
            await _goal_declarative_advance(provider, engine, workflow)
    elif head == "run":
        await _goal_declarative_run(provider, engine, workflow)
    elif head == "status":
        await _goal_declarative_status(workflow)
    elif head == "doctor":
        await _goal_declarative_doctor(workflow)
    elif head == "verify":
        if rest and rest != "run":
            _goal_usage()
        else:
            await _goal_declarative_verify(workflow, engine, args=rest)
    elif head == "pause":
        await _goal_declarative_pause_resume(workflow, resume=False)
    elif head == "resume":
        async with _goal_mutex():
            if await _goal_declarative_pause_resume(workflow, resume=True, response=rest):
                await _goal_declarative_advance(provider, engine, workflow)
    elif head == "audit":
        _echo("[goal] audit subcommand has been removed; supported subcommands are listed below.", err=True)
        _goal_usage()
    elif head == "reset":
        async with _goal_mutex():
            _goal_reset()
    elif head == "auto":
        await _goal_declarative_auto(workflow, rest, cron_store)
    elif (intended := _goal_typo_subcommand(args)) is not None:
        _echo(f"[goal] unknown subcommand {args.strip()!r}; did you mean `/goal {intended}`?", err=True)
        _goal_usage()
    else:
        async with _goal_mutex():
            await _goal_declarative_new(provider, engine, workflow, args.strip(), cron_store=cron_store)


def _goal_usage() -> None:
    """打印 /goal 子命令用法表（缺参 / 未实现 / 拼错时）。"""
    _echo(
        "/goal 用法：\n"
        "  /goal <目标描述>      新建 goal 并执行 planning 规程\n"
        "  /goal new <目标描述>  同上（显式 new 形式）\n"
        "  /goal next            推进下一条 story（每步全新会话）\n"
        "  /goal status          查看进度\n"
        "  /goal doctor          检查工作流及角色技能包\n"
        "  /goal verify [run]    按声明子句复核证据（run = 受控重跑声明的验证命令）\n"
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
        _echo(f"[goal] 显性失败：current 指针读取失败（{exc}）。", err=True)
        return None
    if not goal_id:
        return None
    # 指针内容须为字母 slug 或既有 8 位小写十六进制：防手改指针越界。
    # 把围栏外任意文件当需求文档注入 LLM prompt（仿 sandbox_session_dir 先例）。
    if not _goal_id_is_valid(goal_id):
        _echo(f"[goal] current 指针内容非法：{goal_id!r}（须为英文字母 project id）。", err=True)
        return None
    goals_root = _GOALS_DIR.resolve()
    goal_root = (_GOALS_DIR / goal_id).resolve()
    if not goal_root.is_relative_to(goals_root):
        _echo("[goal] current 指针解析后越过 goals 根目录。", err=True)
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
        _echo("[goal] 已中断：状态在盘（brief.md），/goal next 可续跑。", err=True)
        return None


def _goal_reset() -> None:
    """清除 current 指针（不删任何其他文件）；goal 目录保留并回显路径。"""
    try:
        (_GOALS_DIR / "current").unlink(missing_ok=True)  # missing_ok：竞态下指针已消失视为已清
    except OSError as exc:
        _echo(f"[goal] 落盘失败：清除 current 指针失败（{exc}）。", err=True)
        return
    _echo(f"[goal] current 指针已清除；goal 目录保留：{_GOALS_DIR.resolve()}", err=True)


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
                    _echo(f"[goal] auto 已收口：goal {goal_id} 已非当前 goal，注销 {removed} 个 job。", err=True)
                return
            try:
                declarative_workflow = _goal_declarative_workflow()
            except ValueError as exc:
                _echo(f"[goal] auto stopped: {exc}", err=True)
                _goal_auto_remove(store, goal_id)
                return
            if declarative_workflow is not None:
                outcome = await _goal_declarative_advance(provider, engine, declarative_workflow)
                if outcome in {_GOAL_DONE, _GOAL_FAILED}:
                    removed = _goal_auto_remove(store, goal_id)
                    _echo(f"[goal] declarative auto closed: goal {goal_id}, removed {removed} job(s)", err=True)
                return
            _echo("[goal] auto stopped: workflow.md is required; legacy goal fallback is unavailable", err=True)
            _goal_auto_remove(store, goal_id)
    except OSError:
        # 另一进程正持 goal 锁：显性失败并提示，cron 下一 tick 自动重试。
        _echo("[goal] 另一进程正在推进 goal（锁等待超时）；本 tick 跳过，下一 tick 自动重试。", err=True)


async def _goal_runner(
    provider: BaseProvider,
    engine: EngineContainer | None,
    args: str,
    *,
    cron_store: JobStore | None = None,
    on_message: Callable[[str], None] | None = None,
) -> None:
    """/goal 子命令族总入口：加载声明式 workflow 后交给确定性分发器。

    workflow.md 缺失或无效时显性失败，不回退到已移除的 legacy goal board。
    ``on_message`` 提供时（GUI），本函数调用链上的全部用户可见输出改投该 sink；
    默认 ``None`` ⇒ 仍写 stderr（CLI 行为逐字不变，台账 A4b）。
    """
    token = _MESSAGE_SINK.set(on_message)
    try:
        await _goal_runner_inner(provider, engine, args, cron_store=cron_store)
    finally:
        _MESSAGE_SINK.reset(token)


async def _goal_runner_inner(  # noqa: C901
    provider: BaseProvider,
    engine: EngineContainer | None,
    args: str,
    *,
    cron_store: JobStore | None = None,
) -> None:
    """分发器内核（sink 绑定由 :func:`_goal_runner` 负责，不要直接调用）。"""
    try:
        declarative_workflow = _goal_declarative_workflow()
    except ValueError as exc:
        _echo(f"[goal] {exc}", err=True)
        return
    if declarative_workflow is not None:
        try:
            await _goal_declarative_dispatch(provider, engine, declarative_workflow, args, cron_store=cron_store)
        except OSError:
            # 跨进程文件锁等待超时：显性失败（显性失败原则，不静默降级）。
            _echo(
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
    _echo(
        "[goal] workflow.md is required; the legacy story-board flow has been removed. " + hint,
        err=True,
    )
    return
