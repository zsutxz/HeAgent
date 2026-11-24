"""/goal 命令面：命令处理器、解析/分发、cron 自动推进与 runner 入口。"""

from __future__ import annotations

import asyncio
import difflib
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from heagent.cli.goal.execution import (
    _GOAL_ADVANCED,
    _GOAL_DONE,
    _GOAL_FAILED,
    _active_goal_dir_or_hint,
    _goal_active_md,
    _goal_checkpoint_prompt,
    _goal_declarative_active_dir,
    _goal_declarative_prepare,
    _goal_declarative_workflow,
    _goal_execute_step,
)
from heagent.cli.goal.messages import _MESSAGE_SINK, _echo
from heagent.cli.goal.verify import (
    _emit_goal_gate_event,
    _goal_verify_report,
    _workflow_event_emitter,
)
from heagent.config import get_settings
from heagent.context.loader import load_context_files
from heagent.cron.expr import cron_matches
from heagent.engine import (
    StorySpec,
    WorkflowCheckpointError,
    WorkflowResource,
    WorkflowStepResult,
)
from heagent.goal.application import (
    GOAL_SKILLS_ROOT,
    DecisionStatus,
    advance,
    checkpoint_store,
    external_checkpoint_dir,
    initialize_checkpoint_workspace,
    pause_resume,
    read_workflow_binding,
    record_decision,
    resolve_bound_workflow,
)
from heagent.goal.application import (
    load_validated_workflow as _load_validated_workflow,
)
from heagent.goal.application import (
    resolve_skill_package as _resolve_skill_package,
)
from heagent.goal.application import (
    restore_runner as _goal_declarative_runner,
)
from heagent.goal.decisions import DecisionAction, DecisionRecord, decision_store
from heagent.goal.doctor import diagnose_workflow
from heagent.goal.document import (
    GOALS_DIR,
    goal_document,
    goal_document_title,
    goal_id_is_valid,
    reserve_goal_id,
    write_goal_bundle,
)
from heagent.goal.evidence import EvidenceError
from heagent.goal.mutex import goal_mutex
from heagent.goal.naming import llm_project_id
from heagent.goal.status_view import project_status_view
from heagent.goal.workflow_loader import SkillWorkflowError, workflow_revision
from heagent.pub.workspace import WorkspacePaths

# cron 计划的标准五字段（CLI 侧入参校验；调度语义见 cron/expr.py）。
_CRON_FIELD_COUNT = 5

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from heagent.cron.jobs import JobStore
    from heagent.engine import EngineContainer
    from heagent.providers.base import BaseProvider
    from heagent.pub.types import StoryExecutionContext

_GOAL_AUTO_DEFAULT_CRON = "*/15 * * * *"
_GOAL_AUTO_PREFIX = "goal-advance "


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
        execution: StoryExecutionContext | None = None,
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
            execution,
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
    workflow_id: str = "",
    workflow_revision: str = "",
    cron_store: JobStore | None = None,
) -> None:
    """Create the minimum durable declarative-goal identity, then run step one.

    ``workflow_id`` / ``workflow_revision`` 由调用方算好传入（Story 51-6，AD-8）：创建时把
    选定的流程包 id 与 revision 冻结进需求文档 frontmatter；本函数只落盘，不做选择。
    """
    previous = _goal_declarative_active_dir()
    base_id = await llm_project_id(provider, description)
    workspace = WorkspacePaths.from_root((engine.workspace_root if engine else None) or os.getcwd())
    goal_id = reserve_goal_id(base_id, workspace.root, checkpoint_dir_for=external_checkpoint_dir)
    if goal_id is None:
        _echo("[goal] unable to allocate a unique project goal id", err=True)
        return
    goal_dir = GOALS_DIR / goal_id
    try:
        document_text = goal_document(
            description, goal_id, workflow_id=workflow_id, workflow_revision=workflow_revision
        )
        goal_document_title(document_text)
        write_goal_bundle(
            goal_dir, document_text, workspace.root, init_checkpoint_workspace=initialize_checkpoint_workspace
        )
    except (OSError, ValueError) as exc:
        _echo(f"[goal] failed to persist declarative goal: {exc}", err=True)
        return
    if previous is not None and cron_store is not None:
        _goal_auto_remove(cron_store, previous.name)
    await _goal_declarative_advance(provider, engine, workflow)


async def _goal_declarative_doctor(args: str = "") -> None:
    """Run the read-only preflight and render its structured report.

    预检对象（Story 51-6）：有活动 goal 时预检该 goal **冻结绑定**的包（AD-8——doctor 看
    的是运行中 goal 的真实流程，不看当前配置）；无活动 goal 时支持用 ``--workflow <包id>``
    任选一个包预检（缺省预检 ``Settings.goal_workflow_skill``）。``diagnose_workflow``
    本身与包名无关，语义不变。checkpoint 目录仍从活动 goal 解析（老 goal 本地目录、新 goal
    工作区绑定）；没有活动 goal 时只查 workflow 及其角色包——预检绝不发明目标路径。
    """
    try:
        leftover, option = _goal_workflow_option(args)
    except ValueError as exc:
        _echo(f"[goal] doctor: {exc}", err=True)
        return
    if leftover:
        _goal_usage()
        return
    goal_dir = _goal_declarative_active_dir()
    workflow: WorkflowResource | None = None
    if goal_dir is not None:
        if option:
            # 有活动 goal 时预检的是冻结绑定的包：显性提示选项被忽略，不静默失效。
            _echo(
                "[goal] doctor: the active goal is preflighted against its frozen binding; --workflow is ignored",
                err=True,
            )
        try:
            binding = read_workflow_binding(goal_dir, get_settings().goal_workflow_skill)
            package = _resolve_skill_package(binding.workflow_id)
            if package is None:
                _echo(f"[goal] doctor: workflow package is unavailable: {binding.workflow_id}", err=True)
                return
            workflow = resolve_bound_workflow(goal_dir, get_settings().goal_workflow_skill)
        except (WorkflowCheckpointError, OSError, ValueError) as exc:
            _echo(f"[goal] doctor: {exc}", err=True)
            return
    else:
        skill_id = option or get_settings().goal_workflow_skill
        package = _resolve_skill_package(skill_id)
        if package is None:
            _echo(f"[goal] doctor: workflow package is unavailable: {skill_id}", err=True)
            return
        try:
            workflow = _load_validated_workflow(package)
        except (SkillWorkflowError, OSError, ValueError) as exc:
            _echo(f"[goal] doctor: declarative workflow configuration is invalid: {exc}", err=True)
            return
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
    """渲染唯一的状态投影；CLI、GUI 与 cron 共用该模型。"""
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        _echo("[goal] no active declarative goal", err=True)
        return
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
    except (WorkflowCheckpointError, ValueError) as exc:
        _echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
        return
    open_decisions = (
        ["a step awaits a decision (/goal approve | /goal reject <原因> | /goal amend <补充>)"]
        if runner.state.awaiting_approval
        else []
    )
    for line in project_status_view(
        runner.state,
        workflow,
        goal_id=goal_dir.name,
        open_decisions=open_decisions,
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


# ── 步骤级审批与决策记录 ──────────────────────────────────

# /goal decisions 列表里单条原文的展示上限：决策日志保存全文，回显只留可定位的一行。
_DECISION_TEXT_DISPLAY_LIMIT = 120


def _decision_display_text(raw: str) -> str:
    """单行化并截断决策原文（截断有标记，不静默丢语义）。"""
    text = " ".join(raw.split())
    if len(text) <= _DECISION_TEXT_DISPLAY_LIMIT:
        return text
    return text[: _DECISION_TEXT_DISPLAY_LIMIT - 1] + "…"


async def _goal_declarative_decision(
    workflow: WorkflowResource,
    args: str,
    *,
    action: DecisionAction,
    provider: BaseProvider,
    engine: EngineContainer | None,
) -> None:
    """/goal approve | reject | amend：显式人工决策（CLI/GUI 共用的应用服务，决策日志追加一条）。

    approve / amend 落定后立即推进（与 ``/goal resume`` 的「落定即推进」同款，复用
    :func:`_goal_declarative_advance` 同一推进缝）——amend 推进的就是带补充的重跑；reject
    不推进（工作被驳回，BLOCKED 等待修订后 resume）。
    """
    async with goal_mutex():
        if (goal_dir := _active_goal_dir_or_hint()) is None:
            return
        outcome = await record_decision(workflow, goal_dir, action=action, text=args.strip())
        if outcome.message:
            _echo(outcome.message, err=True)
        if outcome.status is not DecisionStatus.RECORDED or not outcome.proceed:
            return
        await _goal_declarative_advance(provider, engine, workflow)


async def _goal_declarative_decisions(workflow: WorkflowResource) -> None:
    """/goal decisions：只读回显当前 goal 的追加式决策日志（经 _echo 漏斗）。

    读取也进 goal 域锁（审查 #9）：并发写方 append 一半时读方不会把半截文件误报成
    「损坏」——锁内读是防止撕裂读的防线（store 自身的独占创建只保证写侧）。
    """
    async with goal_mutex():
        goal_dir = _goal_declarative_active_dir()
        if goal_dir is None:
            _echo("[goal] no active declarative goal", err=True)
            return
        try:
            records = await decision_store(goal_dir).list_records(goal_id=goal_dir.name)
        except ValueError as exc:
            _echo(f"[goal] decisions: {exc}", err=True)
            return
        _render_decision_records(records)


def _render_decision_records(records: list[DecisionRecord]) -> None:
    """决策日志的确定性渲染（调用方已持 goal 域锁并解析 goal 目录）。"""
    if not records:
        _echo("[goal] decisions: none recorded yet", err=True)
        return
    _echo(f"[goal] decisions: {len(records)} record(s), oldest first", err=True)
    for record in records:
        line = (
            f"[goal] {record.created_at} {record.action.value} step={record.step or '-'}"
            + (f" story={record.story_id}" if record.story_id else "")
            + f" status={record.workflow_status.value} decision={record.decision_id[:8]}"
        )
        if record.raw_text:
            line += f": {_decision_display_text(record.raw_text)}"
        _echo(line, err=True)


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
    async with goal_mutex():
        if (goal_dir := _active_goal_dir_or_hint()) is None:
            return
        try:
            runner = await _goal_declarative_runner(workflow, goal_dir)
        except (WorkflowCheckpointError, ValueError) as exc:
            _echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
            return
        if runner.done:
            _echo("[goal] declarative workflow is already complete; there is no active step to verify", err=True)
            return
        # 显性守卫：活动步越界 / 缺失（如 new 后尚未落任何 checkpoint 的残状）
        # 显性提示返回，不 TypeError、不静默取 min() 兜底。
        active_step = runner.state.active_step
        if active_step is None or active_step >= len(workflow.steps):
            _echo("[goal] verify: the workflow has no active step to verify yet", err=True)
            return
        step = workflow.steps[active_step]
        story_id = runner.state.active_story
        # 跨模块数据用引擎模型：StorySpec 的 (id, epic) 即 `goal_step_artifact_path`
        # 消费的鸭子契约；不用裸 SimpleNamespace。
        story = StorySpec(id=story_id, epic=runner.state.active_epic) if story_id else None
        started = time.perf_counter()
        try:
            report = await _goal_verify_report(
                engine,
                workflow,
                step,
                story,
                goal_dir,
                rerun=args == "run",
                # verify run 只补缺/失败/过期证据，不重复执行：完成门刚写下的
                # 新鲜成功证据复用不重跑（复用清单显性进报告）。verify 不重跑实现步骤，
                # 两次求值之间没有步骤执行，新鲜证据仍然有效。
                rerun_policy="if_stale",
            )
        except (EvidenceError, OSError) as exc:
            _echo(f"[goal] verify failed: {exc}", err=True)
            return
        _emit_goal_gate_event(
            engine,
            source="verify_run",
            step=step,
            story=story,
            report=report,
            started=started,
            rerun=args == "run",
        )
        for line in report.render():
            _echo(line, err=True)


async def _goal_declarative_run(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
) -> None:
    try:
        for _ in range(workflow.max_rounds):
            async with goal_mutex():
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
        if len(fields) != _CRON_FIELD_COUNT or any(
            not field or any(not part.strip() for part in field.split(",")) for field in fields
        ):
            raise ValueError("cron must contain five non-empty fields")
        cron_matches(schedule, datetime.now(UTC))
    except (TypeError, ValueError) as exc:
        _echo(f"[goal] invalid cron expression: {exc}", err=True)
        return
    _goal_auto_remove(cron_store, goal_dir.name)
    job = cron_store.create_job(f"{_GOAL_AUTO_PREFIX}{goal_dir.name}", schedule)
    cron_store.add(job)
    _echo(f"[goal] declarative auto registered: {job.id} workflow={workflow.name}", err=True)


def _goal_workflow_option(args: str) -> tuple[str, str]:
    """拆出字符串参数里的 ``--workflow <包id>``（或 ``--workflow=<包id>``）选项；返回 ``(剩余文本, 包 id)``。

    ``new``（含裸 ``/goal <描述>`` 兜底）与 ``doctor`` 的选项口径：``--workflow`` 后必须
    紧跟包 id（``=`` 形态直接内联），缺参显性报错（不做静默兜底）；重复给出显性报错
    （静默取第一个会把第二个连同包 id 留在描述里）。描述文本恰含 ``--workflow`` token 时
    会按选项解析而显性失败——可接受的 fail-loud（usage 已注明）。未给出时包 id 为空串，
    由调用方回退 ``Settings.goal_workflow_skill``。剩余文本还原为空格连接（描述语义不变）。
    """
    tokens = args.split()
    indices = [index for index, word in enumerate(tokens) if word == "--workflow" or word.startswith("--workflow=")]
    if not indices:
        return args, ""
    if len(indices) > 1:
        raise ValueError("--workflow may be given at most once")
    index = indices[0]
    word = tokens[index]
    if word.startswith("--workflow="):
        package_id = word.removeprefix("--workflow=")
        if not package_id:
            raise ValueError("--workflow requires a package id")
        remaining = tokens[:index] + tokens[index + 1 :]
    else:
        if index + 1 >= len(tokens):
            raise ValueError("--workflow requires a package id")
        package_id = tokens[index + 1]
        remaining = tokens[:index] + tokens[index + 2 :]
    return " ".join(remaining), package_id


async def _goal_resolve_bound() -> tuple[Path, WorkflowResource] | None:
    """解析活动 goal 的目录与其冻结绑定的 workflow；失败渲染用户可见错误并返回 ``None``。

    所有**作用于既有 goal** 的命令经此取流程（Story 51-6，AD-8）：漂移 / 缺包 / 配置非法
    在此显性失败，绝不静默换流程。默认包 id 由入口注入（``Settings.goal_workflow_skill``）。
    """
    if (goal_dir := _active_goal_dir_or_hint()) is None:
        return None
    try:
        return goal_dir, resolve_bound_workflow(goal_dir, get_settings().goal_workflow_skill)
    except (WorkflowCheckpointError, OSError, ValueError) as exc:
        _echo(f"[goal] workflow binding failed: {exc}", err=True)
        return None


async def _goal_bound_workflow() -> WorkflowResource | None:
    """活动 goal 的冻结绑定流程；无活动 goal 或绑定失败时 ``None``。

    :func:`_goal_resolve_bound` 的流程维度投影（A33②）：dispatch 的 11 处
    ``resolved = await _goal_resolve_bound(); if resolved is not None:`` 前导收敛到此，
    只解一元组索引；错误渲染仍单点在 :func:`_goal_resolve_bound`。
    """
    resolved = await _goal_resolve_bound()
    return resolved[1] if resolved is not None else None


async def _goal_start_new(
    provider: BaseProvider,
    engine: EngineContainer | None,
    args: str,
    *,
    cron_store: JobStore | None = None,
) -> None:
    """``/goal new``（含裸描述兜底）：解析 ``--workflow`` → 显性校验包 → 冻结创建。

    选定的包不存在或声明非法都显性失败（不静默回退默认包）；revision 由
    :func:`workflow_revision` 在**创建前**算出，与包 id 一起冻结进需求文档（AD-8）。
    """
    try:
        description, option = _goal_workflow_option(args)
    except ValueError as exc:
        _echo(f"[goal] {exc}", err=True)
        return
    if not description:
        _goal_usage()
        return
    skill_id = option or get_settings().goal_workflow_skill
    if not skill_id:
        # 显式置空是配置错误：pathlib 丢弃空段会拼出 catalog 永远解析不到的
        # ``.heagent/skills/workflow.md``，故单独提示，不走「包不存在」文案。
        _echo(
            "[goal] workflow.md is required: GOAL_WORKFLOW_SKILL is set to an empty package id; "
            "unset it or set a valid skill package id.",
            err=True,
        )
        return
    package = _resolve_skill_package(skill_id)
    if package is None:
        hint = (
            f"create {GOAL_SKILLS_ROOT / skill_id / 'workflow.md'} "
            "(with a meta.yaml declaring its canonical_id) to configure goal execution"
        )
        _echo(f"[goal] workflow.md is required: workflow package '{skill_id}' is unavailable; {hint}", err=True)
        return
    try:
        workflow = _load_validated_workflow(package)
        revision = workflow_revision(package, workflow)
    except (SkillWorkflowError, OSError, ValueError) as exc:
        _echo(f"[goal] declarative workflow configuration is invalid: {exc}", err=True)
        return
    await _goal_declarative_new(
        provider,
        engine,
        workflow,
        description,
        workflow_id=skill_id,
        workflow_revision=revision,
        cron_store=cron_store,
    )


_GOAL_SUBCOMMAND_NAMES = (
    "new",
    "next",
    "run",
    "status",
    "pause",
    "resume",
    "auto",
    "reset",
    "doctor",
    "verify",
    "approve",
    "reject",
    "amend",
    "decisions",
)


def _goal_typo_subcommand(args: str) -> str | None:
    """把已知子命令的单 token 笔误映射到该子命令。

    ``/goal <其它内容>`` 会新建 goal，所以像 ``/goal resume\\`` 这样的手滑会静默烧掉整个
    goal 的第一步。只有与某个已知子命令相近的单 token 输入才按笔误处理；多词描述原样透传。
    """
    parts = args.split()
    if len(parts) != 1:
        return None
    matches = difflib.get_close_matches(parts[0].casefold(), _GOAL_SUBCOMMAND_NAMES, n=1, cutoff=0.8)
    return matches[0] if matches else None


async def _goal_declarative_dispatch(
    provider: BaseProvider,
    engine: EngineContainer | None,
    args: str,
    *,
    cron_store: JobStore | None,
) -> None:
    """Route the supported /goal commands without touching the legacy board.

    作用于**既有 goal** 的命令（advance/run/status/verify/pause/resume/approve/reject/
    amend/decisions/auto/doctor）一律经 :func:`_goal_bound_workflow`（→ :func:`_goal_resolve_bound`）
    按 goal 冻结的绑定解析流程（Story 51-6，AD-8：改配置不让运行中 goal 静默换流程）；
    ``new``（含裸描述兜底）经 :func:`_goal_start_new` 在创建时冻结选定的包 id 与 revision。
    各分支的 ``_goal_mutex`` 持有面与解析落点（锁内 / 锁外）逐字保持（A33② 冻结边界）。
    """
    parts = args.split(None, 1)
    head = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not parts:
        if (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_status(workflow)
    elif head == "new":
        if not rest:
            _goal_usage()
        else:
            async with goal_mutex():
                await _goal_start_new(provider, engine, rest, cron_store=cron_store)
    elif head in ("next", "status", "reset", "run", "pause", "decisions") and rest:
        _goal_usage()
    elif head == "next":
        async with goal_mutex():
            if (workflow := await _goal_bound_workflow()) is not None:
                await _goal_declarative_advance(provider, engine, workflow)
    elif head == "run":
        if (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_run(provider, engine, workflow)
    elif head == "status":
        if (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_status(workflow)
    elif head == "doctor":
        await _goal_declarative_doctor(rest)
    elif head == "verify":
        if rest and rest != "run":
            _goal_usage()
        elif (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_verify(workflow, engine, args=rest)
    elif head == "pause":
        if (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_pause_resume(workflow, resume=False)
    elif head == "resume":
        async with goal_mutex():
            if (workflow := await _goal_bound_workflow()) is not None and await _goal_declarative_pause_resume(
                workflow, resume=True, response=rest
            ):
                await _goal_declarative_advance(provider, engine, workflow)
    elif head == "approve":
        if rest:
            _goal_usage()
        elif (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_decision(
                workflow, "", action=DecisionAction.APPROVE, provider=provider, engine=engine
            )
    elif head in ("reject", "amend"):
        if not rest:
            _goal_usage()
        elif (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_decision(
                workflow,
                rest,
                action=DecisionAction.REJECT if head == "reject" else DecisionAction.AMEND,
                provider=provider,
                engine=engine,
            )
    elif head == "decisions":
        if (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_decisions(workflow)
    elif head == "audit":
        _echo("[goal] audit subcommand has been removed; supported subcommands are listed below.", err=True)
        _goal_usage()
    elif head == "reset":
        async with goal_mutex():
            _goal_reset()
    elif head == "auto":
        if (workflow := await _goal_bound_workflow()) is not None:
            await _goal_declarative_auto(workflow, rest, cron_store)
    elif (intended := _goal_typo_subcommand(args)) is not None:
        _echo(f"[goal] unknown subcommand {args.strip()!r}; did you mean `/goal {intended}`?", err=True)
        _goal_usage()
    else:
        async with goal_mutex():
            await _goal_start_new(provider, engine, args.strip(), cron_store=cron_store)


def _goal_usage() -> None:
    """打印 /goal 子命令用法表（缺参 / 未实现 / 拼错时）。"""
    _echo(
        "/goal 用法：\n"
        "  /goal <目标描述>      新建 goal 并执行 planning 规程\n"
        "  /goal new <目标描述>  同上（显式 new 形式）\n"
        "  /goal new <描述> --workflow <包id>（或 --workflow=<包id>）\n"
        "                        指定 workflow 包创建（缺省 GOAL_WORKFLOW_SKILL）；包 id 与 revision\n"
        "                        在创建时冻结，运行中改配置不换流程（既有 goal 按冻结绑定执行；\n"
        "                        例外：当前配置包存在但声明非法时，入口预校验显性失败会挡住全部\n"
        "                        命令——包括绑定另一合法包的活动 goal）。描述文本恰含 --workflow\n"
        "                        时按选项解析并显性报错，不会吞进描述\n"
        "  /goal next            推进下一条 story（每步全新会话）\n"
        "  /goal status          查看进度\n"
        "  /goal doctor [--workflow <包id>]\n"
        "                        预检工作流及角色技能包（有活动 goal 预检绑定的包；无活动 goal\n"
        "                        时 --workflow 任选包，缺省预检配置的包）\n"
        "  /goal verify [run]    按声明子句复核证据（run = 受控重跑声明的验证命令）\n"
        "  /goal approve         批准等待审批的步骤（唯一能把该步标记完成的路径）\n"
        "  /goal reject <原因>   驳回等待审批的工作（步骤未完成，修订后 /goal resume 重跑）\n"
        "  /goal amend <补充>    带补充重跑等待审批的步骤（步骤未完成，补充进需求文档）\n"
        "  /goal decisions       查看追加式决策日志（approve/reject/amend/resume 每次一条）\n"
        "  /goal reset           清除 current 指针（goal 目录保留）\n"
        "  /goal run             连续推进 goal（步数上限由 workflow 的 max_rounds 声明；Ctrl+C 可中断）\n"
        "  /goal resume [回复]   记录用户回答并继续 waiting_user 步骤\n"
        "  /goal auto [cron]     注册 cron 自动推进（默认 */15 * * * *；off 注销）",
        err=True,
    )


def _goal_reset() -> None:
    """清除 current 指针（不删任何其他文件）；goal 目录保留并回显路径。"""
    try:
        (GOALS_DIR / "current").unlink(missing_ok=True)  # missing_ok：竞态下指针已消失视为已清
    except OSError as exc:
        _echo(f"[goal] 落盘失败：清除 current 指针失败（{exc}）。", err=True)
        return
    _echo(f"[goal] current 指针已清除；goal 目录保留：{GOALS_DIR.resolve()}", err=True)


def _goal_auto_remove(store: JobStore, goal_id: str) -> int:
    removed = 0
    for job in store.list_jobs():
        if job.prompt == f"{_GOAL_AUTO_PREFIX}{goal_id}" and store.remove(job.id):
            removed += 1
    return removed


def _goal_auto_goal_id(prompt: str) -> str | None:
    """返回调度器自有的 auto prompt 里的精确 goal id；非该形态则为 ``None``。"""
    if not prompt.startswith(_GOAL_AUTO_PREFIX):
        return None
    goal_id = prompt[len(_GOAL_AUTO_PREFIX) :].strip()
    if goal_id_is_valid(goal_id):
        return goal_id
    return None


async def _goal_cron_advance(
    provider: BaseProvider, engine: EngineContainer | None, store: JobStore, goal_id: str
) -> None:
    """Run one scheduled goal step under the same process lock as manual commands.

    cron 与手动命令同一解析口径（Story 51-6，AD-8）：推进的是 goal **冻结绑定**的
    workflow，不读当前配置——配置换包后 cron 仍按绑定推进或显性失败，绝不静默换流程。
    """
    try:
        async with goal_mutex():
            current = _goal_active_md()
            if current is None or current.parent.name != goal_id:
                removed = _goal_auto_remove(store, goal_id)
                if removed:
                    _echo(f"[goal] auto 已收口：goal {goal_id} 已非当前 goal，注销 {removed} 个 job。", err=True)
                return
            try:
                declarative_workflow = resolve_bound_workflow(current.parent, get_settings().goal_workflow_skill)
            except (WorkflowCheckpointError, OSError, ValueError) as exc:
                _echo(f"[goal] auto stopped: {exc}", err=True)
                _goal_auto_remove(store, goal_id)
                return
            outcome = await _goal_declarative_advance(provider, engine, declarative_workflow)
            if outcome in {_GOAL_DONE, _GOAL_FAILED}:
                removed = _goal_auto_remove(store, goal_id)
                _echo(f"[goal] declarative auto closed: goal {goal_id}, removed {removed} job(s)", err=True)
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
    """分发器内核（sink 绑定由 :func:`_goal_runner` 负责，不要直接调用）。

    settings 声明的 workflow 在此**预校验**（声明非法显性失败，缝被 sink 测试钉住）；包
    未安装时不再整体短路——真正的流程选择分两条路，各自显性失败：既有 goal 走冻结绑定
    （:func:`resolve_bound_workflow`），``new`` 走选定包（:func:`_goal_start_new`）。
    """
    try:
        _goal_declarative_workflow()
    except ValueError as exc:
        _echo(f"[goal] {exc}", err=True)
        return
    try:
        await _goal_declarative_dispatch(provider, engine, args, cron_store=cron_store)
    except OSError:
        # 跨进程文件锁等待超时：显性失败（显性失败原则，不静默降级）。
        _echo(
            "[goal] 另一进程正在推进同一 goal（.heagent/goal.lock 等待超时）；本次未执行，请稍后重试。",
            err=True,
        )
