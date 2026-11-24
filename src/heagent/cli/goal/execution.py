"""/goal 步骤执行面：声明式解析辅助、步骤执行、script 两阶段与 SubAgent 会话缝。"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any

import click

from heagent.cli.display import SUBAGENT_ANNOUNCER
from heagent.cli.goal.messages import _echo
from heagent.cli.goal.verify import (
    _goal_structured_gate,
    _goal_verify_report,
    _goal_verify_workspace,
    _workflow_event_emitter,
)
from heagent.config import get_settings
from heagent.context.window_reset import WindowResetConfig
from heagent.engine import (
    StepValidationClauses,
    WorkflowCheckpointError,
    WorkflowResource,
    WorkflowStatus,
    WorkflowStepResult,
)
from heagent.goal.application import (
    GoalAdvanceContext,
    checkpoint_mode,
    declarative_prompt,
    read_workflow_binding,
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
from heagent.goal.document import (
    GOALS_DIR,
    goal_description,
    goal_document_path,
    goal_id_is_valid,
    goal_step_artifact_path,
)
from heagent.goal.evidence import EvidenceError
from heagent.goal.quality_gates import gate_declaration_problem, is_registered_gate
from heagent.goal.script_api import ScriptRequest, ScriptResponse
from heagent.goal.script_runtime import GoalScriptRuntimeError, ScriptRuntime
from heagent.goal.workflow_loader import SkillWorkflowError
from heagent.goal.worktree import (
    WorktreeError,
    create_worktree,
    head_commit,
    promote_goal_products,
    promote_story_commit,
    remove_worktree,
)
from heagent.goal.write_audit import (
    _audit_git_evidence,
    _audit_story_writes,
    _emit_write_audit_event,
    _write_audit_baseline,
)
from heagent.pub.persist import atomic_write_text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from heagent.agent.sub import SubAgentResult
    from heagent.engine import EngineContainer
    from heagent.providers.base import BaseProvider
    from heagent.pub.types import StoryExecutionContext
    from heagent.skills.skill_packages import SkillPackage

# 工作流执行状态词汇与推进轮数上限：随编排分支（advance/execute 状态机）变，
# 不随文档约定变，故留本模块（goal/document.py 只做文档与命名，见其 docstring）。
# 工作流包 id 的默认值只在 Settings.goal_workflow_skill 一处声明；本模块一律从配置读。
# 技能库根（GOAL_SKILLS_ROOT）与 open-question 兜底文案已随确定性内核迁
# goal/application.py，经顶部 import 保持本命名空间可用。
_GOAL_ADVANCED = "advanced"
_GOAL_DONE = "done"
_GOAL_FAILED = "failed"
_GOAL_WAITING = "waiting"
# ── /goal 命令族（目标驱动开发工作流——skill 正文直读 + 逐 story 会话）──

# 需求文档与命名层（slug 词表 / goal_id 规则 / 目录命名 / brief.md 生成与增量更新）
# 已拆至 goal/document.py（cli/wiring.py 先例：文档约定与执行编排变化原因不同），见顶部
# re-export——测试经 heagent.cli.goal 导入这些符号，内部引用点继续按模块全局名解析。


def _goal_checkpoint_mode(workflow: WorkflowResource) -> str:
    """Resolve checkpoint policy: workflow declaration, then env-backed settings.

    确定性内核（goal/application.checkpoint_mode）不读配置；settings 回退值在此注入。
    """
    return checkpoint_mode(workflow, get_settings().goal_checkpoint_mode)


def _goal_checkpoint_prompt() -> bool:
    """仅当 stdin 是交互式 TTY 时才请求 checkpoint 批准。"""
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
    """解析配置好的流程包；未安装时返回 ``None``。"""
    return _resolve_skill_package(get_settings().goal_workflow_skill)


def _goal_declarative_workflow() -> WorkflowResource | None:
    """读取配置好的声明式 goal 流程（前提是其包已安装）。

    包缺失表示本机没有配置该流程（由调用方说明）；包存在但声明的流程不可用时属于显性
    错误，而不是静默改跑不兼容的旧流程的理由。
    """
    package = _goal_workflow_package()
    if package is None:
        return None
    try:
        return _load_validated_workflow(package)
    except (SkillWorkflowError, ValueError, OSError) as exc:
        raise ValueError(f"declarative workflow configuration is invalid: {exc}") from exc


def _goal_declarative_active_dir() -> Path | None:
    goal_md = _goal_active_md()
    return goal_md.parent if goal_md is not None else None


def _active_goal_dir_or_hint() -> Path | None:
    """活动 goal 目录空守卫单点：无活动 goal 回显 ``/goal new`` 提示，调用方拿 ``None`` 即 return。"""
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        _echo("[goal] no active declarative goal; use /goal new <description>", err=True)
    return goal_dir


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


async def _goal_declarative_prepare(workflow: WorkflowResource) -> tuple[str | None, GoalAdvanceContext | None]:
    """推进前读取并校验 goal 状态；返回值非 ``None`` 表示应停下。"""
    if (goal_dir := _active_goal_dir_or_hint()) is None:
        return _GOAL_FAILED, None
    try:
        description = goal_description(goal_dir)
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
    # 暂停/取消会落成 Runner 的非完成态；恢复是命令边界的显式动作，
    # 之后本调用可以继续推进该步骤。
    if runner.state.status is WorkflowStatus.WAITING_USER:
        if runner.state.awaiting_approval:
            # 审批门挂起：指向显式决策，resume 在此状态会被显性拒绝。
            _echo(
                "[goal] a step awaits a human decision: /goal approve | /goal reject <原因> | /goal amend <补充> "
                "(/goal decisions lists records)",
                err=True,
            )
        else:
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
    return None, GoalAdvanceContext(
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
    execution: StoryExecutionContext | None = None,
) -> WorkflowStepResult:
    """Execute one declared step through the selected trusted package executor.

    ``execution``（Epic 52 AD-17/AD-18，52-3）：Runner 授权声明门控并行时经第四参传入该
    Story 的执行上下文。非空时启用两端安全面——SubAgent 会话带 ``write_allowlist``
    （52-1 围栏，预防层）；会话 + 质量门结束后做 Git 写集审计（AD-18，检测层）：tracked
    增量越集（声明写集并集 + 宿主自写产物之外）→ 显性 FAILED（``write_violation=True``，
    Runner 据此置撤销闩，该 Goal 此后串行）；untracked 增量只发 ``workflow_write_audit``
    警告（验证夹具 / 新产物常态）；仓库不可用（``GitPortError``）跳过审计并发说明事件，
    围栏仍生效。脚本执行器无 SubAgent 会话，不消费 execution。

    物理隔离（A41 / AD-20）：``execution`` 非空时该 Story 在**自己的 git worktree** 里执行
    （会话的工作区根与写审计基线都钉在 worktree），完成后**先**把 worktree 里的提交
    cherry-pick 回主工作区（用户 2026-11-21 裁定：批内按声明顺序串行 pick，pick 前先建
    ``refs/heagent/stories/<story>`` 临时引用防 gc）、**再**搬产物——``--modified`` 档的未提交
    改动先落主工作区会让 pick 触同路径即被 git 拒绝（local changes would be overwritten）。合并冲突 ⇒ ``cherry-pick --abort``
    已恢复干净工作区后 FAILED 显性报出，不静默丢产出；worktree 在 finally 里移除
    （移除失败只 WARNING，残留可由 ``git worktree prune`` 回收）。
    """
    if step.executor_mode == "script":
        return await _goal_execute_script_step(engine, workflow, goal_dir, inputs, step, story)
    repo_root = _goal_verify_workspace(engine)
    if execution is None or story is None:
        # 串行 / 未授权并行：共享工作区（既有语义逐字不变）。
        return await _goal_run_declarative_step(
            provider,
            engine,
            workflow,
            description,
            goal_dir,
            inputs,
            step,
            story=story,
            execution=execution,
            workspace=repo_root,
        )
    try:
        worktree = await create_worktree(repo_root, goal_dir.name, story.id)
    except WorktreeError as exc:
        # 非 Git 工作区拿不到隔离 ⇒ 与 A41 之前逐字一致地走共享工作区（稍后审计自己会发
        # `git_unavailable`，此处不再重复）；Git 可用但 worktree 建不起来（路径占用 / 权限 /
        # 磁盘）则**显性降级**并留事件——降级必须可观测。
        if await _audit_git_evidence(repo_root) is None:
            return await _goal_run_declarative_step(
                provider,
                engine,
                workflow,
                description,
                goal_dir,
                inputs,
                step,
                story=story,
                execution=execution,
                workspace=repo_root,
            )
        _emit_write_audit_event(
            _workflow_event_emitter(engine),
            step=step,
            story=story,
            skipped=f"worktree_unavailable: {exc}"[:200],
        )
        return await _goal_run_declarative_step(
            provider,
            engine,
            workflow,
            description,
            goal_dir,
            inputs,
            step,
            story=story,
            execution=execution,
            workspace=repo_root,
        )
    try:
        base_rev = await head_commit(worktree)
        result = await _goal_run_declarative_step(
            provider,
            engine,
            workflow,
            description,
            goal_dir,
            inputs,
            step,
            story=story,
            execution=execution,
            workspace=worktree,
            context_dir=str(worktree),
        )
        if result.status is not WorkflowStatus.COMPLETED:
            # 失败/等待步骤同样要搬产物（步骤报告是排障唯一现场，失败更要留）：不 pick（既有口径），
            # 也就没有 pick 会挡 ``--modified`` 档的搬移。
            try:
                await promote_goal_products(repo_root, worktree, goal_dir)
            except (WorktreeError, OSError) as exc:
                return WorkflowStepResult(
                    status=WorkflowStatus.FAILED,
                    reason=(
                        f"story '{story.id}' products could not be moved back from its worktree: {exc}; "
                        "the worktree is removed and the step report is still in the goal directory only"
                    ),
                )
            return result
        story_head = await head_commit(worktree)
        if story_head != base_rev:
            # pick 先行：主工作区此刻在 Story 未提交改动的路径上还干净。产物搬回会把 ``--modified``
            # 档的未提交改动落进主工作区，先搬会让 cherry-pick 触同路径即被 git 拒绝（local changes
            # would be overwritten）⇒ 整步 FAILED、主工作区留脏文件、worktree 连带产物一起删。
            try:
                await promote_story_commit(repo_root, f"{goal_dir.name}-{story.id}", commit=story_head)
            except WorktreeError as exc:
                return WorkflowStepResult(
                    status=WorkflowStatus.FAILED,
                    reason=(
                        f"story '{story.id}' worktree could not be merged back into the main workspace: {exc}; "
                        "the cherry-pick was aborted and the main workspace is clean - resolve the conflict "
                        "manually, then rerun the story"
                    ),
                )
        # `_he-output/` 不进 cherry-pick（gitignore 面）：worktree 移除前把本 Story 写出的产物搬回
        # 主工作区，否则步骤报告随目录一起消失。必须在 pick **之后**搬（时序不变量，见上）；
        # 搬不动即显性 FAILED——静默丢产物比失败更糟。pick 已带回 tracked 增量，此处 ``--modified``
        # 档落下的未提交改动叠加在其上（同文件 = 提交态 + 未提交 delta，无信息丢失）。
        try:
            await promote_goal_products(repo_root, worktree, goal_dir)
        except (WorktreeError, OSError) as exc:
            return WorkflowStepResult(
                status=WorkflowStatus.FAILED,
                reason=(
                    f"story '{story.id}' products could not be moved back from its worktree: {exc}; "
                    "the worktree is removed and the step report is still in the goal directory only"
                ),
            )
        return result
    finally:
        await remove_worktree(repo_root, worktree)


async def _goal_run_declarative_step(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    description: str,
    goal_dir: Path,
    inputs: Mapping[str, Any],
    step: Any,
    *,
    story: Any,
    execution: StoryExecutionContext | None,
    workspace: Path,
    context_dir: str | None = None,
) -> WorkflowStepResult:
    """一次声明式步骤的会话 + 门 + 写审计（``workspace`` 由调用方决定：共享或 story worktree）。"""
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
    # 审计基线在会话**开始前**采集：Δ = after \ before，兄弟并发写与门命令产物
    # 因此天然落在 after 里、按声明排除。基线采集失败（非 Git）→ 跳过审计，围栏不撤。
    baseline = await _write_audit_baseline(workspace) if execution is not None else None
    if execution is not None and baseline is None:
        _emit_write_audit_event(_workflow_event_emitter(engine), step=step, story=story, skipped="git_unavailable")
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
        write_allowlist=list(execution.write_allowlist) if execution is not None else None,
        context_dir=context_dir,
    )
    if result is None:
        return WorkflowStepResult(
            status=WorkflowStatus.WAITING_USER, reason="interrupted; resume to retry the active step"
        )
    if not result.success:
        return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=str(result.output))
    try:
        if result.output is None or (isinstance(result.output, str) and not result.output.strip()):
            return WorkflowStepResult(
                status=WorkflowStatus.FAILED,
                reason=f"step '{step.name}' produced empty output",
            )
        output_text = result.output if isinstance(result.output, str) else str(result.output)
        atomic_write_text(goal_step_artifact_path(goal_dir, step, story), output_text)
    except OSError as exc:
        return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=f"failed to persist step output: {exc}")
    gate_reason = await _goal_structured_gate(engine, workflow, step, story, goal_dir)
    if gate_reason:
        return WorkflowStepResult(status=WorkflowStatus.BLOCKED, reason=gate_reason)
    if execution is not None and execution.write_allowlist and baseline is not None:
        # 空 write_set = 无判据（story 省略三字段的缺省串行形态，模板承诺零开销）：围栏
        # 侧空 allowlist 本就放行，审计侧同样跳过——拿空集判负会把合法源码写全判越界。
        violation_reason = await _audit_story_writes(
            _workflow_event_emitter(engine), workspace, goal_dir, step, story, execution, baseline
        )
        if violation_reason:
            return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=violation_reason, write_violation=True)
    return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output=result.output)


#: 脚本 facade 的**只读**操作：脚本执行期同步回答（读已持久化的输入 / 产物，不涉及状态）。
_SCRIPT_READ_OPERATIONS = frozenset({"input", "artifact"})


def _script_operation_names(operation: ScriptRequest) -> list[str]:
    """一个 ``step`` / ``parallel`` 请求声明的步骤名清单（``parallel`` 用 ``names``）。"""
    return [name for name in ([operation.name] if operation.name else list(operation.names)) if name]


def _script_validate_clauses(step: Any, gate: str) -> StepValidationClauses:
    """``validate(name)`` 的求值子句：只挂该命名门，命令证据源沿用**本步声明**的命令。

    与 ``gate:`` 词汇同规（``tests-pass`` 这类门投影的就是本步 ``command:`` 的证据）：脚本
    请求的门因此与声明门走**同一**求值器、同一必要声明条件，不新增可削弱路径（AD-5）。
    """
    return StepValidationClauses(gates=[gate], commands=list(step.validation_clauses.commands))


def _goal_script_declaration_error(workflow: WorkflowResource, step: Any, operation: ScriptRequest) -> str:
    """**声明期**校验（fail-loud、不落状态）：返回非空理由 = 该请求不可兑现。

    兑现发生在脚本返回之后的提交阶段（两阶段：脚本只声明，宿主按序提交）。不可兑现的请求
    必须在这里就失败，否则脚本会跑完才发现声明无效。
    """
    if operation.operation in _SCRIPT_READ_OPERATIONS or operation.operation in {"checkpoint", "decision"}:
        return ""
    if operation.operation == "validate":
        if not is_registered_gate(operation.name):
            return f"script validate: unknown quality gate {operation.name!r}"
        return gate_declaration_problem(_script_validate_clauses(step, operation.name)) or ""
    if operation.operation in {"step", "parallel"}:
        declared = {candidate.name for candidate in workflow.steps}
        names = _script_operation_names(operation)
        if not names:
            return f"script {operation.operation} requires at least one declared step name"
        unknown = [name for name in names if name not in declared]
        if unknown:
            return f"script {operation.operation}: not a declared workflow step: {', '.join(unknown)}"
        if step.name in names:
            return (
                f"script {operation.operation}: '{step.name}' is the step currently executing; "
                "a script cannot request itself"
            )
        # 名字合法即接受（声明期）：**向前性**与**幂等跳过**由 WorkflowRunner 在提交时裁决
        # （步骤顺序权在状态机，不在脚本、也不在入口层的重复实现里）。
        return ""
    return f"script operation {operation.operation!r} is not supported by this host"


async def _submit_script_requests(
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    step: Any,
    story: Any,
    goal_dir: Path,
    requests: list[ScriptRequest],
) -> tuple[list[str], str, list[str]]:
    """按声明顺序**提交**动作请求，返回 ``(证据行, 阻断理由, 声明的后续步骤)``。

    提交面全部落在既有通道上：``checkpoint`` / ``decision`` 落本步证据（随
    ``WorkflowStepResult.evidence`` 进 ``runner.state.acceptance_evidence``，由 Runner 持久化），
    ``validate`` 复用 Story 51-4 的求值器，``step`` / ``parallel`` 收集为**声明的后续步骤**
    交给上层的 advance 循环按序提交（``WorkflowRunner.run_declared_step``）。脚本从不直接写
    checkpoint / workflow / current，也不自己推进状态（AD-1）。只读请求在此跳过（执行期已答）。
    """
    evidence: list[str] = []
    requested: list[str] = []
    for operation in requests:
        if operation.operation in _SCRIPT_READ_OPERATIONS:
            continue
        if operation.operation == "checkpoint":
            # Runner 在步骤收尾本就会持久化 checkpoint；脚本声明的意图因此记进证据即可，
            # 不重复写状态——脚本无法、也不需要自己写 checkpoint。
            evidence.append(f"script-checkpoint: {operation.note or 'checkpoint requested'}")
        elif operation.operation == "decision":
            detail = f"script-decision: {operation.name}"
            if operation.value is not None:
                detail += f" = {operation.value}"
            if operation.note:
                detail += f" ({operation.note})"
            evidence.append(detail)
        elif operation.operation in {"step", "parallel"}:
            names = _script_operation_names(operation)
            requested.extend(names)
            evidence.append(f"script-{operation.operation}: {', '.join(names)} (declared; submitted after this step)")
        elif operation.operation == "validate":
            reason = await _goal_script_validate(engine, workflow, step, story, goal_dir, operation.name)
            if reason:
                return evidence, reason, requested
    return evidence, "", requested


async def _goal_script_validate(
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    step: Any,
    story: Any,
    goal_dir: Path,
    gate: str,
) -> str:
    """跑一个脚本请求的命名门；未过返回理由（非空 = 该步 BLOCKED）。"""
    target = step.model_copy(update={"validation_clauses": _script_validate_clauses(step, gate)})
    try:
        report = await _goal_verify_report(engine, workflow, target, story, goal_dir, rerun=False)
    except (EvidenceError, OSError) as exc:
        return f"script validate '{gate}' failed: {exc}"
    if report.passed:
        return ""
    parts = report.failure_summary_parts()
    return f"script validate '{gate}' failed: {'; '.join(parts) or 'gate did not pass'}"


async def _goal_execute_script_step(
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    goal_dir: Path,
    inputs: Mapping[str, Any],
    step: Any,
    story: Any = None,
) -> WorkflowStepResult:
    """Run a package-local script; the host submits its declared requests afterwards.

    **两阶段（Story 51-7 的 A 语义）**：脚本执行期只**声明**动作请求（只读操作同步作答），
    脚本返回后宿主按声明顺序**提交**——请求兑现全落在既有通道（Runner 证据 / 51-4 求值器），
    脚本自己不碰 checkpoint、workflow、current 或治理链内部（AD-1 / AD-9）。

    与 subagent 步骤**同一条完成门**（Story 51-4）：产物落盘后仍按该步 ``validation:`` 的
    结构化子句求值，未通过落 BLOCKED——脚本产物不得绕过质量 Gate（AD-5）。
    """
    binding = read_workflow_binding(goal_dir, get_settings().goal_workflow_skill)
    package = _resolve_skill_package(binding.workflow_id)
    if package is None:
        return WorkflowStepResult(
            status=WorkflowStatus.FAILED, reason=f"workflow package unavailable: {binding.workflow_id}"
        )

    async def request(operation: ScriptRequest) -> ScriptResponse:
        if operation.operation in _SCRIPT_READ_OPERATIONS:
            return ScriptResponse(value=inputs.get(operation.name, operation.value))
        problem = _goal_script_declaration_error(workflow, step, operation)
        # 其余动作请求在此**只声明**（不落状态）；兑现由脚本返回后的提交阶段完成。
        return ScriptResponse(accepted=not problem, reason=problem)

    try:
        result = await ScriptRuntime(
            max_requests=64,
            max_depth=8,
            timeout_seconds=30.0,
        ).run(package, step.script_resource, inputs=inputs, artifacts=inputs, request=request)
    except (GoalScriptRuntimeError, ValueError, OSError) as exc:
        return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=f"script step failed: {exc}")
    output = result.value
    if output is None:
        output = "\n".join(result.evidence) if result.evidence else "script completed"
    output_text = output if isinstance(output, str) else str(output)
    if not output_text.strip():
        return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=f"step '{step.name}' produced empty output")
    try:
        atomic_write_text(goal_step_artifact_path(goal_dir, step, story), output_text)
    except OSError as exc:
        return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=f"failed to persist script output: {exc}")
    submitted, blocked, requested = await _submit_script_requests(
        engine, workflow, step, story, goal_dir, list(result.requests)
    )
    evidence = [*submitted, *result.evidence]
    if blocked:
        return WorkflowStepResult(status=WorkflowStatus.BLOCKED, reason=blocked, evidence=evidence)
    gate_reason = await _goal_structured_gate(engine, workflow, step, story, goal_dir)
    if gate_reason:
        return WorkflowStepResult(status=WorkflowStatus.BLOCKED, reason=gate_reason, evidence=evidence)
    return WorkflowStepResult(
        status=WorkflowStatus.COMPLETED,
        output=output_text,
        evidence=evidence,
        requested_steps=requested,
    )


def _goal_active_md() -> Path | None:
    """解析活跃 goal 的需求文档路径；指针缺失/解码失败返回 None，内容非法显性报错。"""
    try:
        goal_id = (GOALS_DIR / "current").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        _echo(f"[goal] 显性失败：current 指针读取失败（{exc}）。", err=True)
        return None
    if not goal_id:
        return None
    # 指针内容须为字母 slug 或既有 8 位小写十六进制：防手改指针越界。
    # 把围栏外任意文件当需求文档注入 LLM prompt（仿 sandbox_session_dir 先例）。
    if not goal_id_is_valid(goal_id):
        _echo(f"[goal] current 指针内容非法：{goal_id!r}（须为英文字母 project id）。", err=True)
        return None
    goals_root = GOALS_DIR.resolve()
    goal_root = (GOALS_DIR / goal_id).resolve()
    if not goal_root.is_relative_to(goals_root):
        _echo("[goal] current 指针解析后越过 goals 根目录。", err=True)
        return None
    return goal_document_path(goal_root)


async def _goal_session(
    provider: BaseProvider,
    engine: EngineContainer | None,
    prompt: str,
    *,
    metadata: dict[str, Any] | None = None,
    max_iterations: int | None = None,
    write_allowlist: Sequence[str] | None = None,
    context_dir: str | None = None,
) -> SubAgentResult | None:
    """开一个**全新** SubAgent 会话执行一个 goal 步骤（流式经 SubAgent 内部收集）。

    每次 ``run()`` 新建 AgentLoop+RunContext；``window_reset`` 按设置阈值启用（长会话
    清窗续跑）。Ctrl+C / 任务取消不崩出交互层：捕获后回显「状态在盘」并返回 None。
    ``write_allowlist``（52-1/52-3 联动）：非空时注入 RunContext metadata，经
    PolicyEngine 的 per-run 写集围栏拦截越集工具写——声明门控并行的预防层。
    """
    from heagent.agent.sub import SubAgent  # noqa: PLC0415

    agent = SubAgent(
        provider,
        engine=engine,
        metadata=metadata,
        max_iterations=max_iterations if max_iterations is not None else get_settings().goal_max_iterations,
        window_reset=WindowResetConfig(threshold=get_settings().window_reset_threshold),
        announcer=SUBAGENT_ANNOUNCER,
        write_allowlist=write_allowlist,
        context_dir=context_dir,
    )
    try:
        return await agent.run(prompt)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _echo("[goal] 已中断：状态在盘（brief.md），/goal next 可续跑。", err=True)
        return None
