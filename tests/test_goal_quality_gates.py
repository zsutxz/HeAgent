"""Story 51-4：真实质量 Gate 与 ``/goal verify``——通用求值器、gate 注册表与受控重跑。

覆盖验收标准的可执行判据：声称命令通过但没有匹配证据时 Gate 失败；非零退出码 / 错误 cwd /
过期 / 证据不属于当前 Story → 未通过；``/goal verify`` 只检查或受控重跑声明的验证，不重跑
实现步骤、不改 Runner 状态；老包零行为变化；未注册 ``gate:`` 名字加载期 fail-loud；
只写 Markdown 不能补证据（变异锚点）。
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import heagent.cli.goal as cli_goal
from heagent.cli.goal import _goal_declarative_workflow, _goal_runner
from heagent.engine import EngineContainer, WorkflowRunner, WorkflowStatus
from heagent.engine.checkpoint import WorkflowCheckpointStore
from heagent.engine.ledger import ExecutionLedger, ExecutionStatus
from heagent.engine.workflow_resource import StepValidationClauses, WorkflowStepResource
from heagent.goal.evidence import (
    TRUNCATION_MARKER,
    CommandEvidence,
    CommandOutcome,
    EvidenceRecord,
    EvidenceStore,
    new_evidence_id,
)
from heagent.goal.quality_gates import (
    GATE_GIT_CHANGES,
    GATE_TESTS_PASS,
    QUALITY_GATES,
    ClauseKind,
    VerificationReport,
    is_registered_gate,
    verify_step,
)
from heagent.goal.workflow_loader import SkillWorkflowError, read_workflow
from heagent.skills.skill_packages import SkillPackage
from heagent.pub.types import ToolCall, ToolResult

_WORKSPACE = Path("E:/proj").resolve()
_NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def _step(clauses: StepValidationClauses, name: str = "step-01-verify.md") -> WorkflowStepResource:
    return WorkflowStepResource(index=1, name=name, instructions="do the work", validation_clauses=clauses)


def _record(
    *,
    story_id: str | None = None,
    goal_id: str = "goal-1",
    step: str = "step-01-verify.md",
    workflow_id: str = "demo-flow",
    created_at: str | None = None,
    commands: list[CommandEvidence] | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=new_evidence_id(),
        goal_id=goal_id,
        workflow_id=workflow_id,
        step=step,
        story_id=story_id,
        created_at=created_at or _NOW.isoformat(),
        commands=commands or [],
    )


def _command(
    command: str = "pytest -q",
    *,
    cwd: str = str(_WORKSPACE),
    outcome: CommandOutcome = CommandOutcome.SUCCEEDED,
    exit_code: int | None = 0,
) -> CommandEvidence:
    return CommandEvidence(command=command, cwd=cwd, outcome=outcome, exit_code=exit_code)


async def _evaluate(
    clauses: StepValidationClauses,
    store: EvidenceStore,
    *,
    story_id: str | None = None,
    **kwargs: object,
) -> VerificationReport:
    now = kwargs.pop("now", _NOW)
    return await verify_step(
        _step(clauses),
        store=store,
        goal_id="goal-1",
        story_id=story_id,
        workflow_id="demo-flow",
        workspace=kwargs.pop("workspace", _WORKSPACE),  # type: ignore[arg-type]
        **{"now": now, **kwargs},  # type: ignore[arg-type]
    )


# ── gate 注册表：宿主内置门的通用词汇 ─────────────────────────────────────


def test_registry_holds_the_generic_gate_vocabulary() -> None:
    assert set(QUALITY_GATES) == {GATE_TESTS_PASS, GATE_GIT_CHANGES}
    assert is_registered_gate(GATE_TESTS_PASS)
    assert not is_registered_gate("tests-pass-2")
    for spec in QUALITY_GATES.values():
        assert spec.description
        assert spec.name == spec.name.casefold() and " " not in spec.name
        assert callable(spec.evaluate)  # 分派表：每个注册名绑定自己的求值函数（review #5）


# ── command: 子句 ─────────────────────────────────────────────────────


async def test_claimed_command_without_evidence_fails_the_gate(tmp_path: Path) -> None:
    """声称命令通过但没有匹配证据：Gate 失败（AC 锚点）。"""
    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), EvidenceStore(tmp_path))

    assert not report.passed
    result = report.results[0]
    assert result.kind is ClauseKind.COMMAND
    assert "no matching command evidence" in result.reason


async def test_markdown_claim_can_never_substitute_evidence(tmp_path: Path) -> None:
    """只写 Markdown / 拼原始 dict 不能补命令证据（AD-5 变异锚点）。"""
    output = "## 测试证据\n\nexit_code=0\nall 3 passed\n\n"
    output += '{"command": "pytest -q", "exit_code": 0, "outcome": "succeeded"}'
    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), EvidenceStore(tmp_path), output_text=output)

    assert not report.passed
    assert "no matching command evidence" in report.results[0].reason


@pytest.mark.parametrize(
    "outcome",
    [CommandOutcome.FAILED, CommandOutcome.TIMEOUT, CommandOutcome.CANCELLED, CommandOutcome.POLICY_BLOCKED],
)
async def test_every_non_succeeded_outcome_is_a_failure(tmp_path: Path, outcome: CommandOutcome) -> None:
    """失败 / 超时 / 取消 / 策略阻断都算「未通过」，不分「没跑」与「跑了没过」。"""
    store = EvidenceStore(tmp_path)
    await store.append(
        _record(commands=[_command(outcome=outcome, exit_code=None if outcome is not CommandOutcome.FAILED else 1)])
    )

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)

    assert not report.passed
    assert "recorded outcome is" in report.results[0].reason


async def test_failed_exit_code_is_never_reported_as_passed(tmp_path: Path) -> None:
    """非零退出码 → 未通过（AC 锚点；变异 M3 的判据）。"""
    store = EvidenceStore(tmp_path)
    await store.append(_record(commands=[_command(outcome=CommandOutcome.FAILED, exit_code=1)]))

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)

    assert not report.passed
    assert "exit code 1" in report.results[0].reason


async def test_wrong_cwd_fails_the_gate(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    await store.append(_record(commands=[_command(cwd="E:/elsewhere")]))

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)

    assert not report.passed
    assert "cwd" in report.results[0].reason


async def test_expired_evidence_fails_the_gate(tmp_path: Path) -> None:
    """过期证据 → 未通过（AC 锚点）。"""
    store = EvidenceStore(tmp_path)
    stale = (_NOW - timedelta(hours=25)).isoformat()
    await store.append(_record(created_at=stale, commands=[_command()]))

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)

    assert not report.passed
    assert "expired" in report.results[0].reason


async def test_fresh_evidence_still_passes(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    fresh = (_NOW - timedelta(hours=1)).isoformat()
    await store.append(_record(created_at=fresh, commands=[_command()]))

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)

    assert report.passed
    assert report.results[0].evidence_ids


@pytest.mark.parametrize("recorded_story", ["S-9"])
async def test_evidence_bound_to_another_story_is_out_of_scope(tmp_path: Path, recorded_story: str) -> None:
    """证据不属于当前 Story：范围外 → 无匹配证据 → 未通过（AC 锚点）。"""
    store = EvidenceStore(tmp_path)
    await store.append(_record(story_id=recorded_story, commands=[_command()]))

    foreign = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store, story_id="S-1")
    owner = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store, story_id=recorded_story)

    assert not foreign.passed
    assert foreign.results[0].reason.startswith("no matching command evidence")
    assert owner.passed


async def test_command_identity_is_whitespace_normalized(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    await store.append(_record(commands=[_command("pytest   -q")]))

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)

    assert report.passed


async def test_binding_drift_is_reported_explicitly(tmp_path: Path) -> None:
    """workflow 绑定漂移的证据被显性排除并进 errors，不冒充匹配证据。"""
    store = EvidenceStore(tmp_path)
    await store.append(_record(workflow_id="another-flow", commands=[_command()]))

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)

    assert not report.passed
    assert any("different workflow binding" in error for error in report.errors)


# ── artifact: 子句 ────────────────────────────────────────────────────


async def test_artifact_clause_requires_the_file(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    missing = await _evaluate(StepValidationClauses(artifacts=["reports/verify.md"]), store, workspace=tmp_path)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "verify.md").write_text("ok", encoding="utf-8")
    present = await _evaluate(StepValidationClauses(artifacts=["reports/verify.md"]), store, workspace=tmp_path)

    assert not missing.passed
    assert "missing" in missing.results[0].reason
    assert present.passed


# ── git: 子句 ─────────────────────────────────────────────────────────


async def test_git_clause_without_any_evidence_fails(tmp_path: Path) -> None:
    report = await _evaluate(StepValidationClauses(git_paths=["src/x.py"]), EvidenceStore(tmp_path))

    assert not report.passed
    assert "no git evidence" in report.results[0].reason


async def test_git_clause_uses_the_live_query_first_then_recorded(tmp_path: Path) -> None:
    from heagent.goal.evidence import GitEvidence

    store = EvidenceStore(tmp_path)
    clauses = StepValidationClauses(git_paths=["src/x.py"])
    untouched = await _evaluate(clauses, store, git_evidence=GitEvidence(changed_files=["src/other.py"]))
    touched = await _evaluate(clauses, store, git_evidence=GitEvidence(changed_files=["src/x.py"]))
    await store.append(_record())  # 无 Git 证据的记录不顶替 live 查询
    recorded_only = GitEvidence(changed_files=[], untracked_files=["src/x.py"])
    await store.append(_record().model_copy(update={"git": recorded_only}))
    via_record = await _evaluate(clauses, store)

    assert not untouched.passed
    assert touched.passed
    assert via_record.passed  # live 缺席时回落到最新记录的 Git 证据


# ── section: 子句（既有文本门禁的复验）──────────────────────────────────


async def test_section_clause_reuses_the_text_gate_predicate(tmp_path: Path) -> None:
    clauses = StepValidationClauses(sections=["测试证据"])
    missing = await _evaluate(clauses, EvidenceStore(tmp_path), output_text="## 别的标题\n")
    present = await _evaluate(clauses, EvidenceStore(tmp_path), output_text="## 测试证据\nbody\n")
    no_output = await _evaluate(clauses, EvidenceStore(tmp_path), output_text=None)

    assert not missing.passed
    assert "## 测试证据" in missing.results[0].reason
    assert present.passed
    assert not no_output.passed
    assert "no step output" in no_output.results[0].reason


# ── gate: 子句（宿主门）────────────────────────────────────────────────


async def test_tests_pass_gate_requires_a_co_declared_command(tmp_path: Path) -> None:
    """tests-pass 单独声明没有证据来源：求值显性失败（加载期另有同文案拒绝，review #2）。"""
    report = await _evaluate(StepValidationClauses(gates=[GATE_TESTS_PASS]), EvidenceStore(tmp_path))

    assert not report.passed
    assert "no 'command:' clause" in report.results[0].reason


async def test_tests_pass_gate_projects_the_latest_evidence_of_declared_commands(tmp_path: Path) -> None:
    """tests-pass = 每条声明命令的最新证据都通过；「失败→修复→放行」（review #2）。"""
    clauses = StepValidationClauses(gates=[GATE_TESTS_PASS], commands=["pytest -q"])
    store = EvidenceStore(tmp_path)
    await store.append(
        _record(
            created_at=(_NOW - timedelta(minutes=2)).isoformat(),
            commands=[_command(outcome=CommandOutcome.FAILED, exit_code=2)],
        )
    )
    broken = await _evaluate(clauses, store)
    assert not broken.passed
    assert "recorded outcome is failed" in broken.results[0].reason

    # append-only：修复后**新增**一条成功证据（created_at 显式更晚但仍为过去，
    # 不依赖墙钟微秒），最新投影放行，旧失败证据不再拖累。
    later = (_NOW - timedelta(minutes=1)).isoformat()
    await store.append(_record(created_at=later, commands=[_command()]))
    fixed = await _evaluate(clauses, store)
    assert fixed.passed
    gate = next(item for item in fixed.results if item.kind is ClauseKind.GATE)
    assert "all 1 declared command(s) verified succeeded" in gate.reason


async def test_tests_pass_gate_expires_then_rerun_clears_it(tmp_path: Path) -> None:
    """「过期→重跑→放行」（review #2）：过期成功证据挡门；受控重跑落新证据即放行。"""
    clauses = StepValidationClauses(gates=[GATE_TESTS_PASS], commands=["pytest -q"])
    store = EvidenceStore(tmp_path)
    stale = (_NOW - timedelta(hours=25)).isoformat()
    await store.append(_record(created_at=stale, commands=[_command()]))
    expired = await _evaluate(clauses, store)
    assert not expired.passed
    assert "expired" in expired.results[0].reason

    async def port(command: str) -> CommandEvidence:
        return _command(command)

    rerun = await _evaluate(clauses, store, rerun=True, run_command=port, now=None)
    assert rerun.passed
    assert rerun.rerun_evidence


async def test_tests_pass_gate_failure_in_scope_of_another_story_does_not_leak(tmp_path: Path) -> None:
    """Story 归属严格相等（review #6）：其他 Story 的失败证据不冒充、也不拖累本 Story。"""
    clauses = StepValidationClauses(gates=[GATE_TESTS_PASS], commands=["pytest -q"])
    store = EvidenceStore(tmp_path)
    await store.append(_record(story_id="S-2", commands=[_command(outcome=CommandOutcome.TIMEOUT, exit_code=None)]))
    await store.append(_record(created_at=(_NOW - timedelta(minutes=1)).isoformat(), commands=[_command()]))

    main = await _evaluate(clauses, store)
    other = await _evaluate(clauses, store, story_id="S-2")
    assert main.passed
    assert not other.passed
    gate = next(item for item in other.results if item.kind is ClauseKind.GATE)
    assert "not verified" in gate.reason and "outcome is timeout" in gate.reason


async def test_step_level_evidence_is_invisible_to_a_story_scope(tmp_path: Path) -> None:
    """步骤级证据（story_id=None）对 Story 求值不可见（review #6），只对步骤级求值可见。"""
    clauses = StepValidationClauses(commands=["pytest -q"])
    store = EvidenceStore(tmp_path)
    await store.append(_record(story_id=None, commands=[_command()]))

    step_level = await _evaluate(clauses, store)
    story_scope = await _evaluate(clauses, store, story_id="S-1")
    assert step_level.passed
    assert not story_scope.passed


async def test_git_changes_gate_projects_recorded_changes(tmp_path: Path) -> None:
    from heagent.goal.evidence import GitEvidence

    clauses = StepValidationClauses(gates=[GATE_GIT_CHANGES])
    none = await _evaluate(clauses, EvidenceStore(tmp_path))
    empty = await _evaluate(clauses, EvidenceStore(tmp_path), git_evidence=GitEvidence())
    changed = await _evaluate(clauses, EvidenceStore(tmp_path), git_evidence=GitEvidence(changed_files=["a.py"]))

    assert not none.passed and not empty.passed
    assert changed.passed


async def test_unregistered_gate_name_fails_loud_at_evaluation(tmp_path: Path) -> None:
    """绕过 loader 直构造模型也逃不掉：求值器对未注册名字显性失败。"""
    clauses = StepValidationClauses(gates=["host-secret-gate"])
    report = await _evaluate(clauses, EvidenceStore(tmp_path))

    assert not report.passed
    assert "not registered" in report.results[0].reason


# ── 老包零行为变化 ────────────────────────────────────────────────────


async def test_step_without_structured_clauses_passes_trivially(tmp_path: Path) -> None:
    """老包不声明结构化子句 = 不要求证据（零行为变化）。"""
    report = await _evaluate(StepValidationClauses(), EvidenceStore(tmp_path))

    assert report.passed
    assert report.results == []
    assert "no structured clauses" in report.render()[0]


# ── 受控重跑 ──────────────────────────────────────────────────────────


async def test_controlled_rerun_records_evidence_then_passes(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)

    async def port(command: str) -> CommandEvidence:
        return _command(command)

    report = await _evaluate(
        StepValidationClauses(commands=["pytest -q", "ruff check ."]),
        store,
        rerun=True,
        run_command=port,
        now=None,  # 重跑证据用真实时钟落盘：求值时刻不能是注入的过去（未来时间戳判过期）
    )

    assert report.passed
    assert len(report.rerun_evidence) == 2
    records = await store.list_records(goal_id="goal-1")
    assert len(records) == 2
    assert records[0].step == "step-01-verify.md"
    assert records[0].workflow_id == "demo-flow"


async def test_controlled_rerun_without_a_port_fails_loud(tmp_path: Path) -> None:
    """声明了命令却拿不到治理端口 = 求值显性失败，不静默放行。"""
    report = await _evaluate(
        StepValidationClauses(commands=["pytest -q"]),
        EvidenceStore(tmp_path),
        rerun=True,
        run_command=None,
    )

    assert not report.passed
    assert any("no governed command runner" in error for error in report.errors)


async def test_controlled_rerun_port_failure_is_explicit(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)

    async def port(command: str) -> CommandEvidence:
        raise RuntimeError("sandbox unavailable")

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store, rerun=True, run_command=port)

    assert not report.passed
    assert any("controlled re-run of 'pytest -q' failed" in error for error in report.errors)


@pytest.mark.asyncio
async def test_if_stale_rerun_reuses_fresh_successful_evidence(tmp_path: Path) -> None:
    """``if_stale``（51-4 递延收口）：完成门刚写下的新鲜成功证据复用不重跑，reuse 显性进报告。"""
    store = EvidenceStore(tmp_path)
    await store.append(_record(commands=[_command("pytest -q")]))
    calls: list[str] = []

    async def port(command: str) -> CommandEvidence:
        calls.append(command)
        return _command(command)

    report = await _evaluate(
        StepValidationClauses(commands=["pytest -q"]),
        store,
        rerun=True,
        rerun_policy="if_stale",
        run_command=port,
    )

    assert calls == []
    assert report.reused_commands == ["pytest -q"]
    assert report.rerun_evidence == []
    assert report.passed


@pytest.mark.asyncio
async def test_if_stale_rerun_still_reruns_failed_evidence(tmp_path: Path) -> None:
    """最新证据失败时不复用：``verify run`` 重跑是「检查是否修好」的合法路径。"""
    store = EvidenceStore(tmp_path)
    await store.append(_record(commands=[_command("pytest -q", outcome=CommandOutcome.FAILED, exit_code=1)]))
    calls: list[str] = []

    async def port(command: str) -> CommandEvidence:
        calls.append(command)
        return _command(command)

    report = await _evaluate(
        StepValidationClauses(commands=["pytest -q"]),
        store,
        rerun=True,
        rerun_policy="if_stale",
        run_command=port,
        now=None,  # 重跑证据带真实时钟；_NOW 会把它判成未来时间戳
    )

    assert calls == ["pytest -q"]
    assert report.reused_commands == []
    assert report.rerun_evidence
    assert report.passed


@pytest.mark.asyncio
async def test_if_stale_reruns_when_evidence_is_stale(tmp_path: Path) -> None:
    """过期证据不满足复用条件：重跑后拿到新鲜证据。"""
    store = EvidenceStore(tmp_path)
    stale = _NOW - timedelta(hours=25)
    await store.append(_record(created_at=stale.isoformat(), commands=[_command("pytest -q")]))
    calls: list[str] = []

    async def port(command: str) -> CommandEvidence:
        calls.append(command)
        return _command(command)

    report = await _evaluate(
        StepValidationClauses(commands=["pytest -q"]),
        store,
        rerun=True,
        rerun_policy="if_stale",
        run_command=port,
        now=None,  # 重跑证据带真实时钟；_NOW 会把它判成未来时间戳
    )

    assert calls == ["pytest -q"]
    assert report.reused_commands == []
    assert report.passed


@pytest.mark.asyncio
async def test_always_policy_reruns_even_with_fresh_success(tmp_path: Path) -> None:
    """完成门语义锁定：默认 ``always`` 无条件重跑——证据必须反映当前这次步骤执行（AD-5）。"""
    store = EvidenceStore(tmp_path)
    await store.append(_record(commands=[_command("pytest -q")]))
    calls: list[str] = []

    async def port(command: str) -> CommandEvidence:
        calls.append(command)
        return _command(command)

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store, rerun=True, run_command=port)

    assert calls == ["pytest -q"]
    assert report.reused_commands == []
    assert report.rerun_evidence


async def test_rerun_false_never_invokes_the_port(tmp_path: Path) -> None:
    """只检查模式绝不执行命令（verify 的「绝不重跑实现步骤」锚点之一）。"""
    calls: list[str] = []

    async def port(command: str) -> CommandEvidence:
        calls.append(command)
        return _command(command)

    report = await _evaluate(
        StepValidationClauses(commands=["pytest -q"]),
        EvidenceStore(tmp_path),
        rerun=False,
        run_command=port,
    )

    assert calls == []
    assert not report.passed  # 无证据：只检查如实失败


# ── 声明面：gate: 名字的加载期注册表校验 ─────────────────────────────────


def _package_with_step(tmp_path: Path, validation: str, *, inline: bool = False) -> SkillPackage:
    if inline:
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "workflow.md").write_text(
            f"---\nname: inline\n---\n\n# Inline\n\n## Step 01: work\nvalidation: {validation}\n\nDo it.\n",
            encoding="utf-8",
        )
    else:
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "workflow.md").write_text("---\nname: demo\nsteps: [step-01-a.md]\n---\n\n# D\n", encoding="utf-8")
        (tmp_path / "step-01-a.md").write_text(f"---\nvalidation: {validation}\n---\nBody", encoding="utf-8")
    return SkillPackage(skill_id="demo", root=tmp_path)


@pytest.mark.parametrize("inline", [False, True])
def test_unregistered_gate_name_fails_the_load(tmp_path: Path, inline: bool) -> None:
    """引用未注册 gate 名字 = 加载期 fail-loud（AC 锚点；变异 M2 的判据）。"""
    with pytest.raises(SkillWorkflowError, match="unknown quality gate 'made-up'"):
        read_workflow(_package_with_step(tmp_path, "gate: made-up", inline=inline))


def test_tests_pass_gate_requires_a_command_clause_at_load(tmp_path: Path) -> None:
    """tests-pass 必须与 command: 同用：加载期拒绝单独声明（review #2 的 loader 校验文案）。"""
    with pytest.raises(SkillWorkflowError, match="at least one command clause"):
        read_workflow(_package_with_step(tmp_path, "gate: tests-pass"))


def test_registered_gate_load_error_lists_the_host_gate_semantics(tmp_path: Path) -> None:
    """未注册报错附宿主门语义（含必要声明条件）——文案单一真源在注册表 description。"""
    with pytest.raises(SkillWorkflowError, match="command: 子句同用") as excinfo:
        read_workflow(_package_with_step(tmp_path, "gate: made-up"))
    assert "tests-pass" in str(excinfo.value)


def test_registered_gate_names_parse_at_load(tmp_path: Path) -> None:
    step = read_workflow(_package_with_step(tmp_path, "command: pytest -q; gate: tests-pass, gate: git-changes")).steps[
        0
    ]

    assert step.validation_clauses.gates == ["tests-pass", "git-changes"]


# ── /goal verify：入口接线 ────────────────────────────────────────────


_WORKFLOW = (
    "---\nname: gate-flow\nentrypoint: goal\non_create: persist_goal_identity\nstep_executor: subagent\n---\n\n"
    "workflow instructions\n\n"
    "## Step 01: build\ninput: user intent, existing project context\noutput: implementation\n"
    "validation: artifact: reports/first.md\n\nbuild the story\n\n"
    "## Step 02: ship\ninput: implementation\noutput: delivery\ncheckpoint: true\n\nship it\n"
)


@pytest.fixture()
def gate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_workflow_root: Path) -> Path:
    """带 ``artifact:`` 子句的两步工作流；cwd 为 tmp 工作区。"""
    monkeypatch.chdir(tmp_path)
    (goal_workflow_root / "workflow.md").write_text(_WORKFLOW, encoding="utf-8")
    (tmp_path / "_he-output" / "goals").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _rewrite_package_workflow(gate_cwd: Path, command: str) -> None:
    """把包内工作流的步骤子句换成 ``command: <command>``（模拟声明驱动换门禁：src/ 零改动）。"""
    package = gate_cwd / ".heagent" / "skills" / "he-goal"
    (package / "workflow.md").write_text(
        _WORKFLOW.replace("validation: artifact: reports/first.md", f"validation: command: {command}"),
        encoding="utf-8",
    )


@pytest.fixture()
def successful_step(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(prompt)
        return SimpleNamespace(success=True, output=f"output-{len(calls)}")

    monkeypatch.setattr("heagent.cli.goal._goal_session", run_step)
    return calls


@pytest.mark.asyncio
async def test_completion_gate_blocks_until_the_declared_artifact_exists(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """完成判定依赖真实证据：产物缺失 → BLOCKED；补上产物后 resume → 放行。"""
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    err = capsys.readouterr().err
    assert "status=blocked" in err
    assert "quality gate failed for step 'step-01-build.md'" in err
    assert "[goal] verify: FAIL artifact: reports/first.md" in err
    assert len(successful_step) == 1
    goal_id = (gate_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    checkpoints = await WorkflowCheckpointStore(str(gate_cwd / ".heagent" / "checkpoints" / goal_id)).list_checkpoints(
        goal_id=goal_id
    )
    assert checkpoints[-1].completed_steps == []

    (gate_cwd / "reports").mkdir()
    (gate_cwd / "reports" / "first.md").write_text("done", encoding="utf-8")
    await _goal_runner(SimpleNamespace(), None, "resume retried after artifact")
    assert len(successful_step) == 2
    persisted = await WorkflowCheckpointStore(str(gate_cwd / ".heagent" / "checkpoints" / goal_id)).list_checkpoints(
        goal_id=goal_id
    )
    assert persisted[-1].completed_steps == [0]


@pytest.mark.asyncio
async def test_goal_verify_reports_missing_evidence_without_touching_state(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """/goal verify 只检查：缺产物如实报 FAIL，不改 Runner 状态、不重跑实现步骤。"""
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    capsys.readouterr()
    assert len(successful_step) == 1

    await _goal_runner(SimpleNamespace(), None, "verify")
    err = capsys.readouterr().err
    assert "[goal] verify: FAIL artifact: reports/first.md" in err
    assert "verdict=failed" in err
    assert len(successful_step) == 1  # 实现步骤没有被重跑


@pytest.mark.asyncio
async def test_goal_verify_run_without_engine_reports_the_missing_runner(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    _rewrite_package_workflow(gate_cwd, "pytest -q")
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    capsys.readouterr()

    await _goal_runner(SimpleNamespace(), None, "verify run")
    err = capsys.readouterr().err
    assert "verdict=failed" in err
    assert "no governed command runner" in err


@pytest.mark.asyncio
async def test_goal_verify_run_uses_the_governed_port_and_records_evidence(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """完成门先失败（证据未通过）→ ``verify run`` 受控重跑通过 → resume 放行。"""
    recorded: list[str] = []
    passing = {"ok": False}

    async def port(command: str) -> CommandEvidence:
        recorded.append(command)
        return CommandEvidence(
            command=command,
            cwd=str(gate_cwd.resolve()),
            outcome=CommandOutcome.SUCCEEDED if passing["ok"] else CommandOutcome.FAILED,
            exit_code=0 if passing["ok"] else 1,
        )

    monkeypatch.setattr(cli_goal, "_goal_verify_command_runner", lambda engine: port)
    _rewrite_package_workflow(gate_cwd, "pytest -q")
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    err = capsys.readouterr().err
    assert "status=blocked" in err  # 完成门：失败证据不能放行
    assert "exit code 1" in err

    passing["ok"] = True
    await _goal_runner(SimpleNamespace(), None, "verify run")
    err = capsys.readouterr().err
    assert recorded == ["pytest -q", "pytest -q"]  # 完成门一次 + verify run 一次
    assert "verdict=passed" in err
    assert "recorded evidence:" in err

    await _goal_runner(SimpleNamespace(), None, "resume continue")
    assert len(successful_step) == 2  # 证据通过后步骤放行


@pytest.mark.asyncio
async def test_goal_verify_run_reuses_fresh_command_evidence(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """51-4 递延收口：完成门刚写下的新鲜成功证据，``verify run`` 复用而不重复执行命令。"""
    recorded: list[str] = []

    async def port(command: str) -> CommandEvidence:
        recorded.append(command)
        return CommandEvidence(
            command=command,
            cwd=str(gate_cwd.resolve()),
            outcome=CommandOutcome.SUCCEEDED,
            exit_code=0,
        )

    monkeypatch.setattr(cli_goal, "_goal_verify_command_runner", lambda engine: port)
    package = gate_cwd / ".heagent" / "skills" / "he-goal"
    # command 过 + artifact 缺：门挂起（步骤保持活动），命令证据已新鲜成功
    (package / "workflow.md").write_text(
        _WORKFLOW.replace(
            "validation: artifact: reports/first.md",
            "validation: command: pytest -q; artifact: reports/first.md",
        ),
        encoding="utf-8",
    )
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    err = capsys.readouterr().err
    assert "status=blocked" in err  # artifact 缺 → BLOCKED；命令证据此刻已落
    assert recorded == ["pytest -q"]

    await _goal_runner(SimpleNamespace(), None, "verify run")
    err = capsys.readouterr().err
    assert recorded == ["pytest -q"]  # 新鲜成功证据被复用，未重复执行
    assert "reused" in err
    assert "verdict=failed" in err  # artifact 仍缺，判定如实失败，复用不放水


@pytest.mark.asyncio
async def test_gate_and_verify_emit_gate_evaluated_events(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """51-4 递延收口：质量门求值发 ``workflow_gate_evaluated``（完成门与 verify run 各一条）。"""
    events: list[tuple[str, dict[str, object]]] = []

    def capture(engine: object) -> object:
        def emit(kind: str, *, details: dict[str, object] | None = None) -> None:
            events.append((kind, details or {}))

        return emit

    monkeypatch.setattr(cli_goal, "_workflow_event_emitter", capture)
    recorded: list[str] = []
    passing = {"ok": False}

    async def port(command: str) -> CommandEvidence:
        recorded.append(command)
        return CommandEvidence(
            command=command,
            cwd=str(gate_cwd.resolve()),
            outcome=CommandOutcome.SUCCEEDED if passing["ok"] else CommandOutcome.FAILED,
            exit_code=0 if passing["ok"] else 1,
        )

    monkeypatch.setattr(cli_goal, "_goal_verify_command_runner", lambda engine: port)
    _rewrite_package_workflow(gate_cwd, "pytest -q")
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    capsys.readouterr()
    passing["ok"] = True
    await _goal_runner(SimpleNamespace(), None, "verify run")
    capsys.readouterr()

    # runner 的 workflow_step_* 事件与门事件走同一总线，过滤后断言门事件
    gate_events = [details for kind, details in events if kind == "workflow_gate_evaluated"]
    assert len(gate_events) == 2
    gate_event, verify_event = gate_events
    assert gate_event["source"] == "completion_gate"
    assert gate_event["verdict"] == "failed"
    assert gate_event["step"] == "step-01-build.md"
    assert verify_event["source"] == "verify_run"
    assert verify_event["verdict"] == "passed"
    assert verify_event["rerun"] is True
    for details in (gate_event, verify_event):
        assert isinstance(details["duration_ms"], int)


@pytest.mark.asyncio
async def test_goal_verify_without_an_active_goal_says_so(gate_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
    await _goal_runner(SimpleNamespace(), None, "verify")

    assert "no active declarative goal" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_goal_verify_rejects_unknown_arguments(gate_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
    await _goal_runner(SimpleNamespace(), None, "verify aggressive")

    assert "用法" in capsys.readouterr().err


# ── 受治理执行链端口（AD-6：不绕过工具治理链）─────────────────────────────


@pytest.mark.asyncio
async def test_governed_port_runs_the_shell_through_the_chain(tmp_path: Path) -> None:
    """真实治理链：policy DIRECT → guard → shell handler → exit_code=0 证据；台账留审计记录。"""
    import heagent.tools.builtins.shell  # noqa: F401  注册 shell handler

    engine = EngineContainer()
    engine.ledger = ExecutionLedger(str(tmp_path / "ledger"))
    evidence = await cli_goal._run_governed_verify_command(engine, f'"{sys.executable}" -c "print(40+2)"')

    assert evidence.outcome is CommandOutcome.SUCCEEDED
    assert evidence.exit_code == 0
    assert "42" in evidence.output_summary
    records = [record for record in await engine.ledger.list_records() if record.scope == "goal-verify"]
    assert len(records) == 1
    assert records[0].status is ExecutionStatus.COMPLETED
    assert records[0].metadata["outcome"] == "succeeded"
    assert records[0].metadata["command"] == f'"{sys.executable}" -c "print(40+2)"'  # 审计可回答「执行了哪条命令」


@pytest.mark.asyncio
async def test_governed_port_records_a_nonzero_exit_as_failed(tmp_path: Path) -> None:
    import heagent.tools.builtins.shell  # noqa: F401

    engine = EngineContainer()
    engine.ledger = ExecutionLedger(str(tmp_path / "ledger"))
    evidence = await cli_goal._run_governed_verify_command(engine, f'"{sys.executable}" -c "import sys; sys.exit(3)"')

    assert evidence.outcome is CommandOutcome.FAILED
    assert evidence.exit_code == 3
    records = [record for record in await engine.ledger.list_records() if record.scope == "goal-verify"]
    assert records[0].metadata["outcome"] == "failed"  # 命令失败 ≠ 执行失败：执行本身完成，outcome 如实记


@pytest.mark.asyncio
async def test_governed_port_records_a_policy_block_as_not_passed(tmp_path: Path) -> None:
    import heagent.tools.builtins.shell  # noqa: F401

    engine = EngineContainer()
    engine.ledger = ExecutionLedger(str(tmp_path / "ledger"))
    engine.policy.allowed_tools = {"not-shell"}

    evidence = await cli_goal._run_governed_verify_command(engine, f'"{sys.executable}" -c "print(1)"')

    assert evidence.outcome is CommandOutcome.POLICY_BLOCKED
    assert evidence.exit_code is None
    records = [record for record in await engine.ledger.list_records() if record.scope == "goal-verify"]
    assert records[0].metadata["outcome"] == "policy_blocked"


def test_tool_call_argument_shape_is_the_declared_command_plus_timeout() -> None:
    """端口 ToolCall 形状：command + 显式 timeout（治理链裁决与摘要都消费这个形状）。"""
    call = ToolCall(id="verify-x", name="shell", arguments={"command": "pytest -q", "timeout": 600})
    assert call.name == "shell" and call.arguments["command"] == "pytest -q"
    assert call.arguments["timeout"] == 600
    assert ToolResult(tool_call_id=call.id, content="exit_code=0\n").content.startswith("exit_code=")


class _StubNamingProvider:
    """goal 命名路径的最小 provider：固定回 project（真引擎 e2e 只关心治理链）。"""

    async def send(self, messages: list[object], *, tools: list[object] | None = None) -> object:
        from heagent.pub.types import ProviderResponse, TokenUsage

        return ProviderResponse(
            content="project",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="stub",
            finish_reason="stop",
        )


@pytest.mark.asyncio
async def test_real_engine_gate_runs_the_declared_command_at_the_workspace_root(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """真引擎端到端（review #1/#3）：不 mock 治理端口；engine.workspace_root ≠ 进程 cwd，
    声明命令必须在工作区根执行（marker 落工作区而非进程 cwd），正确命令放行。"""
    import heagent.tools.builtins.shell  # noqa: F401

    workspace = gate_cwd / "ws"
    workspace.mkdir()
    engine = EngineContainer(workspace_root=str(workspace))
    _rewrite_package_workflow(gate_cwd, "echo ok > marker.txt")

    await _goal_runner(_StubNamingProvider(), engine, "new build the real thing")

    err = capsys.readouterr().err
    assert "status=pending" in err  # 步骤 1/2 完成并推进（非末步 → PENDING）
    assert len(successful_step) == 1
    assert (workspace / "marker.txt").read_text(encoding="utf-8").strip() == "ok"  # 命令在工作区根执行
    assert not (gate_cwd / "marker.txt").exists()  # 进程 cwd 没有被误用为执行目录
    goal_id = (gate_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    evidence_files = list((gate_cwd / "_he-output" / "goals" / goal_id / "evidence").glob("*.json"))
    assert len(evidence_files) == 1  # 治理链产出落了证据
    checkpoints = await WorkflowCheckpointStore(str(workspace / ".heagent" / "checkpoints" / goal_id)).list_checkpoints(
        goal_id=goal_id
    )
    assert checkpoints[-1].completed_steps == [0]  # 步骤经真实治理端口放行


@pytest.mark.asyncio
async def test_real_engine_gate_blocks_a_failing_declared_command(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """真引擎端到端（review #3）：失败命令经真实治理端口 → 完成门 BLOCKED。"""
    import heagent.tools.builtins.shell  # noqa: F401

    engine = EngineContainer(workspace_root=str(gate_cwd))
    _rewrite_package_workflow(gate_cwd, "exit 3")

    await _goal_runner(_StubNamingProvider(), engine, "new build the real thing")

    err = capsys.readouterr().err
    assert "status=blocked" in err
    assert "exit code 3" in err
    assert len(successful_step) == 1  # 实现步骤跑过一次，BLOCKED 后不自动重跑


@pytest.mark.asyncio
async def test_governed_port_passes_an_explicit_timeout(tmp_path: Path) -> None:
    """受治理重跑显式传 timeout（review #16）：不用 120s 默认钉死长验证套件。"""
    import heagent.tools.builtins.shell  # noqa: F401
    from heagent.tools.registry import ToolRegistry

    registry = ToolRegistry.get()
    original = registry._handlers.get("shell")
    captured: dict[str, object] = {}

    async def recording(**kwargs: object) -> str:
        captured.update(kwargs)
        return "exit_code=0\n"

    registry._handlers["shell"] = recording
    engine = EngineContainer()
    engine.ledger = ExecutionLedger(str(tmp_path / "ledger"))
    try:
        evidence = await cli_goal._run_governed_verify_command(engine, "pytest -q")
    finally:
        if original is None:
            registry._handlers.pop("shell", None)
        else:
            registry._handlers["shell"] = original

    assert captured["timeout"] == cli_goal._VERIFY_COMMAND_TIMEOUT_SECONDS == 600
    assert evidence.outcome is CommandOutcome.SUCCEEDED


@pytest.mark.asyncio
async def test_governed_port_records_policy_blocked_when_shell_is_unregistered() -> None:
    """shell handler 未注册：POLICY_BLOCKED（未通过），不崩、不放行（review #23）。"""
    from heagent.tools.registry import ToolRegistry

    registry = ToolRegistry.get()
    original = registry._handlers.get("shell")
    registry._handlers.pop("shell", None)
    try:
        evidence = await cli_goal._run_governed_verify_command(EngineContainer(), "pytest -q")
    finally:
        if original is not None:
            registry._handlers["shell"] = original

    assert evidence.outcome is CommandOutcome.POLICY_BLOCKED
    assert "not registered" in evidence.output_summary


@pytest.mark.asyncio
async def test_goal_verify_reports_a_workflow_without_an_active_step(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """活动步越界 / 缺失：显性提示返回，不 TypeError（review #14）。"""
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    capsys.readouterr()
    workflow = _goal_declarative_workflow()
    runner = WorkflowRunner(workflow)
    runner.state = runner.state.model_copy(update={"active_step": len(workflow.steps)})

    async def restored(_workflow: object, _goal_dir: object) -> WorkflowRunner:
        return runner

    monkeypatch.setattr(cli_goal, "_goal_declarative_runner", restored)

    await _goal_runner(SimpleNamespace(), None, "verify")

    assert "no active step to verify" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_goal_verify_exits_early_on_a_completed_workflow(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """workflow 已完成：verify 早退提示（review #23 的 done 分支）。"""
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    capsys.readouterr()
    workflow = _goal_declarative_workflow()
    runner = WorkflowRunner(workflow)
    runner.state = runner.state.model_copy(
        update={"active_step": len(workflow.steps), "status": WorkflowStatus.COMPLETED}
    )

    async def restored(_workflow: object, _goal_dir: object) -> WorkflowRunner:
        return runner

    monkeypatch.setattr(cli_goal, "_goal_declarative_runner", restored)

    await _goal_runner(SimpleNamespace(), None, "verify")

    assert "already complete" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_goal_verify_reports_its_own_io_failure_not_a_lock_contention(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """verify 求值路径的 OSError 收口为本命令失败，不落「锁竞争」误诊文案（review #4）。"""
    await _goal_runner(SimpleNamespace(), None, "new build a gate")
    capsys.readouterr()

    def broken(_goal_dir: Path) -> object:
        raise OSError("disk gone")

    monkeypatch.setattr(cli_goal, "evidence_store", broken)

    await _goal_runner(SimpleNamespace(), None, "verify")

    err = capsys.readouterr().err
    assert "[goal] verify failed" in err and "disk gone" in err
    assert "另一进程" not in err


@pytest.mark.asyncio
async def test_completion_gate_turns_an_evaluation_failure_into_blocked(
    gate_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """完成门求值故障（OSError）→ BLOCKED 理由，不崩整个 run、不放行（review #4）。"""

    def broken(_goal_dir: Path) -> object:
        raise OSError("disk gone")

    monkeypatch.setattr(cli_goal, "evidence_store", broken)

    await _goal_runner(SimpleNamespace(), None, "new build a gate")

    err = capsys.readouterr().err
    assert "status=blocked" in err
    assert "gate evaluation error" in err and "disk gone" in err


# ── review 修复批次的新判据（#7/#8/#9/#10/#11/#12）──────────────────────────


async def test_truncated_evidence_prefix_must_match_uniquely(tmp_path: Path) -> None:
    """截断证据前缀命中多条声明命令：显性判「无法定位匹配」，不任配（review #7）。"""
    clauses = StepValidationClauses(commands=["pytest -q", "pytest tests/"])
    store = EvidenceStore(tmp_path)
    truncated = f"pytest {TRUNCATION_MARKER}"
    await store.append(_record(commands=[_command(truncated)]))

    report = await _evaluate(clauses, store)

    assert not report.passed
    for item in report.results:
        assert "cannot locate the match" in item.reason

    unambiguous = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)
    assert unambiguous.passed  # 唯一候选时前缀匹配合法


async def test_declared_command_is_redacted_before_matching(tmp_path: Path) -> None:
    """声明命令先 redact_secrets 再比对（与 recorded 侧同规，review #8）：含密钥样 token 的
    合法命令经真实证据构建器落证后仍能匹配。"""
    from heagent.goal.evidence import build_command_evidence
    from heagent.pub.types import ToolCall

    secret_command = "pytest --api-token sk-verysecretvalue -q"  # noqa: S105 - 故意的脱敏判据
    store = EvidenceStore(tmp_path)
    built = build_command_evidence(
        ToolCall(id="call-1", name="shell", arguments={"command": secret_command}),
        ToolResult(tool_call_id="call-1", content="exit_code=0\n"),
        cwd=str(_WORKSPACE),
    )
    assert "sk-verysecretvalue" not in built.command  # 前置：证据侧确实脱敏了
    await store.append(_record(commands=[built]))

    report = await _evaluate(StepValidationClauses(commands=[secret_command]), store)

    assert report.passed


async def test_git_path_matching_normalizes_prefix_case_dir_and_quotes(tmp_path: Path) -> None:
    """git 路径归一（review #9）：``./`` 前缀、Windows 大小写、目录前缀、引号形式。"""
    from heagent.goal.evidence import GitEvidence

    store = EvidenceStore(tmp_path)
    git = GitEvidence(changed_files=["src/x.py"])

    for declared in ["./src/x.py", "SRC\\X.PY", "src", '"src/x.py"']:
        report = await _evaluate(StepValidationClauses(git_paths=[declared]), store, git_evidence=git)
        assert report.passed, declared

    report = await _evaluate(StepValidationClauses(git_paths=["src/other.py"]), store, git_evidence=git)
    assert not report.passed


async def test_future_timestamped_evidence_is_expired(tmp_path: Path) -> None:
    """未来时间戳证据（recorded > now）一律过期（review #10）。"""
    store = EvidenceStore(tmp_path)
    future = (_NOW + timedelta(hours=1)).isoformat()
    await store.append(_record(created_at=future, commands=[_command()]))

    report = await _evaluate(StepValidationClauses(commands=["pytest -q"]), store)

    assert not report.passed
    assert "future timestamp" in report.results[0].reason


async def test_artifact_clause_rejects_a_directory(tmp_path: Path) -> None:
    """目录不算产物：``artifact:`` 必须命中文件（review #11）。"""
    (tmp_path / "reports").mkdir()
    report = await _evaluate(StepValidationClauses(artifacts=["reports"]), EvidenceStore(tmp_path), workspace=tmp_path)

    assert not report.passed
    assert "not a file" in report.results[0].reason


async def test_empty_or_null_byte_cwd_never_matches(tmp_path: Path) -> None:
    """证据 cwd 空串 / null byte：判不匹配，不落 Path("") 冒充当前目录（review #12）。"""
    clauses = StepValidationClauses(commands=["pytest -q"])
    store = EvidenceStore(tmp_path)
    await store.append(_record(commands=[_command(cwd="")]))
    empty = await _evaluate(clauses, store)
    assert not empty.passed

    poisoned_cwd = "E:\\proj\\x\x00y"
    await store.append(_record(story_id="S-2", commands=[_command(cwd=poisoned_cwd)]))
    poisoned = await _evaluate(clauses, store, story_id="S-2")
    assert not poisoned.passed
