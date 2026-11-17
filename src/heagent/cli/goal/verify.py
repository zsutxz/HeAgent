"""/goal 验证面：质量门/证据求值/受治理重跑与 workflow 事件发射。"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from heagent.cli.goal.messages import _echo
from heagent.config import get_settings, resolve_runtime_config
from heagent.engine import ToolExecutionMode
from heagent.engine.ledger import LedgerAudit
from heagent.engine.observability import elapsed_ms
from heagent.engine.workflow_runner import _emit_step_event
from heagent.goal.application import read_workflow_binding
from heagent.goal.document import goal_step_artifact_path
from heagent.goal.evidence import (
    CommandEvidence,
    CommandOutcome,
    EvidenceError,
    GitEvidence,
    build_command_evidence,
    classify_command_result,
    evidence_store,
    new_evidence_id,
)
from heagent.goal.quality_gates import verify_step
from heagent.goal.write_audit import _audit_git_evidence
from heagent.pub.types import ToolCall, ToolResult
from heagent.pub.workspace import WorkspacePaths

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.engine import EngineContainer, WorkflowResource
    from heagent.goal.quality_gates import GovernedCommandPort, VerificationReport


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


def _emit_goal_gate_event(
    engine: EngineContainer | None,
    *,
    source: Literal["completion_gate", "verify_run"],
    step: Any,
    story: Any,
    report: VerificationReport,
    started: float,
    rerun: bool,
) -> None:
    """质量门求值的观测事件（51-4 递延「emit 接线」收口）。

    ``workflow_gate_evaluated`` 与 runner 的 ``workflow_step_*`` 同走 ``engine.events`` 总线，
    且共用同一份隔离包装 :func:`WorkflowRunner._emit_step_event`（A27 统一：emit-None 守卫 +
    try/except + ``safe_log`` 忽略的观测隔离契约全仓只有这一份实现）；``engine=None``
    （部分库消费者）不发事件。鸭子对象（step/story）的属性访问在隔离内；report 派生值
    是自有类型化模型字段，在实参处求值（不会抛）。
    """
    emit: Callable[..., None] | None = _workflow_event_emitter(engine)
    if emit is None:
        return
    _emit_step_event(
        emit,
        "workflow_gate_evaluated",
        step=step,
        story=story,
        duration_ms=elapsed_ms(started),
        source=source,
        verdict="passed" if report.passed else "failed",
        failed=len(report.failed),
        clause_errors=len(report.errors),
        rerun=rerun,
        rerun_evidence=list(report.rerun_evidence),
        reused_commands=list(report.reused_commands),
    )


# ── /goal verify 与结构化完成门 ───────────────────────────────────

# 受治理重跑的命令超时（秒）：声明验证可能是长测试套件，工具的 120s 默认会把长套件
# 钉成 TIMEOUT——显式给足上界；不新增顶层配置键。
_VERIFY_COMMAND_TIMEOUT_SECONDS = 600

# 完成门串行锁：并行 Story 的门命令不重叠。asyncio.Lock 绑定首个发生竞争
# 等待的事件循环，跨 loop 复用会 RuntimeError——按运行中 loop 各持一把（同 loop 内互斥
# 语义不变；跨 loop 本就无法用 asyncio 原语互斥，CLI 每进程单 loop 不受影响）。
_GOAL_GATE_LOCKS: dict[int, asyncio.Lock] = {}


def _goal_gate_lock() -> asyncio.Lock:
    """当前事件循环的完成门锁。锁内声明命令受 ``_VERIFY_COMMAND_TIMEOUT_SECONDS``
    上界约束：并行批内其他成员的门等待至多被拖长一个命令超时（受控重跑既有预算）。"""
    return _GOAL_GATE_LOCKS.setdefault(id(asyncio.get_running_loop()), asyncio.Lock())


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
    rerun_policy: Literal["always", "if_stale"] = "always",
) -> VerificationReport:
    """求值一个步骤 / Story 的 ``validation:`` 子句（``/goal verify`` 与完成门共用同一次实现）。

    证据 = ``<goal_dir>/evidence/``（唯一位置解析点）；产物 = 工作区文件；Git = 只读端口
    的实时查询（仓库不可用返回空证据：变更集为空，git 子句与 ``git-changes`` 门照实
    显性未过）；步骤输出 = 已持久化的步骤产物（section 门禁复验的输入，缺失由求值器
    显性记未过）。workspace 经 :func:`_goal_verify_workspace`（唯一解析点，review #1）。
    ``revision`` = goal 创建时冻结的绑定 revision（Story 51-6 收口 51-4 递延接线）：受控
    重跑写下的证据带同一 revision，绑定漂移的证据随求值范围显性排除（AD-5/AD-8）。
    ``rerun_policy`` 透传 :func:`verify_step`（完成门 always / verify run if_stale）。
    """
    workspace = _goal_verify_workspace(engine)
    try:
        binding = read_workflow_binding(goal_dir, get_settings().goal_workflow_skill)
    except (OSError, ValueError) as exc:
        raise EvidenceError(f"goal workflow binding is unreadable: {exc}") from exc
    return await verify_step(
        step,
        store=evidence_store(goal_dir),
        goal_id=goal_dir.name,
        story_id=story.id if story is not None else None,
        workspace=workspace,
        workflow_id=workflow.name,
        revision=binding.revision,
        output_text=await _goal_step_output_text(goal_dir, step, story),
        git_evidence=await _goal_live_git_evidence(workspace),
        rerun=rerun,
        rerun_policy=rerun_policy,
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

    模块级门锁（52-3 AC6）：并行 Story 的门命令串行——LLM 会话并行、受控重跑的命令
    执行不重叠（共享工作区的命令写互不踩踏）。串行路径无竞争，锁快取不落即过零变化。
    """
    if not step.validation_clauses.declared:
        return ""
    async with _goal_gate_lock():
        started = time.perf_counter()
        try:
            report = await _goal_verify_report(engine, workflow, step, story, goal_dir, rerun=True)
        except (EvidenceError, OSError) as exc:
            return f"quality gate failed for step '{step.name}': gate evaluation error: {exc}"
        _emit_goal_gate_event(
            engine,
            source="completion_gate",
            step=step,
            story=story,
            report=report,
            started=started,
            rerun=True,
        )
        if report.passed:
            return ""
        for line in report.render():
            _echo(line, err=True)
        return f"quality gate failed for step '{step.name}': {'; '.join(report.failure_summary_parts())}"


async def _goal_step_output_text(goal_dir: Path, step: Any, story: Any) -> str | None:
    """已持久化的步骤产物文本（section 门禁复验输入）；缺失 / 不可读返回 ``None``（显性未过）。"""
    try:
        return await asyncio.to_thread(goal_step_artifact_path(goal_dir, step, story).read_text, encoding="utf-8")
    except (OSError, ValueError):
        return None


async def _goal_live_git_evidence(workspace: Path) -> GitEvidence:
    """只读 Git 端口的实时查询（白名单内确定性查询，AD-11）；仓库不可用时返回空证据。"""
    return await _audit_git_evidence(workspace) or GitEvidence()


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

    台账审计（51-4 递延「ledger 接线」收口；A28 下沉 engine）：每次受治理执行在
    ``ExecutionLedger`` 留一条 ``scope="goal-verify"`` 记录（command / outcome / duration
    进 metadata）。键含唯一 call id——只审计、**不去重**：verify 重跑是显性请求，永远
    允许再次执行。acquire → 在途续租 → complete/fail 的配对由
    :class:`~heagent.engine.ledger.LedgerAudit` 经 ``executor.execute(audit=...)`` 单点完成
    （含租约在途续租——修复「慢 verify 跑超静态租约被 prune 误判孤儿」的审计面失配）；
    本函数只传规格，台账故障不影响执行结果（观测不得改变业务控制流）。
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
    # handler 缺席的早退在前：没有真实治理执行就不留台账记录。
    verdict = engine.policy.evaluate_tool_call(call, context=run_context, schema=registry.get_schema("shell"))
    executable = cast("Callable[..., Any]", handler)

    async def invoke(call: ToolCall) -> object:
        produced = executable(**call.arguments)
        if asyncio.iscoroutine(produced):
            return await produced
        return produced

    # 容器构造期快照优先，缺席（手工构造的容器）才回退现场解析。
    runtime = engine.runtime_config or resolve_runtime_config()

    def classify_outcome(result: ToolResult) -> CommandOutcome:
        """证据与审计共用的 outcome 归类核心（策略阻断 / 证据失形 → 未通过，不从文本猜层）。"""
        if verdict.mode in {ToolExecutionMode.BLOCKED, ToolExecutionMode.APPROVAL_REQUIRED}:
            return CommandOutcome.POLICY_BLOCKED
        try:
            return classify_command_result(result)
        except EvidenceError:
            return CommandOutcome.POLICY_BLOCKED

    # 命令失败（非零退出）≠ 执行失败：受治理执行本身完成，outcome 如实进 metadata。
    # command 并入 complete 的 metadata（ledger.complete 整体替换 metadata）：
    # 审计记录必须能回答「哪条声明命令被受治理执行过」。租约须覆盖静态超时上界。
    audit = LedgerAudit(
        ledger=engine.ledger,
        key=f"goal-verify:{call.id}",
        scope="goal-verify",
        lease_seconds=_VERIFY_COMMAND_TIMEOUT_SECONDS + 60,
        metadata={"command": command},
        result_metadata=lambda result: {"command": command, "outcome": classify_outcome(result).value},
    )
    result = await engine.executor.execute(
        call=call,
        verdict=verdict,
        guard=SafetyGuard(blocked_tools=list(runtime.safety_blocked_tools)),
        handler=invoke,
        run_context=run_context,
        audit=audit,
    )
    duration_ms = elapsed_ms(started)
    return build_command_evidence(
        call, result, cwd=str(workspace), duration_ms=duration_ms, outcome=classify_outcome(result)
    )
