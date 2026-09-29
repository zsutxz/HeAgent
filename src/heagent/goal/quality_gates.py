"""通用质量门求值器：把 ``validation:`` 的结构化子句逐条匹配到证据与产物（Story 51-4）。

**AD-14 证明（为什么声明层表达不了）**：子句只声明*要什么*证据；「拿声明的规则去对齐
证据记录、文件系统与只读 Git」是运行期判定——需要读 :class:`~heagent.goal.evidence.EvidenceStore`、
探测工作区文件、访问只读 Git，Markdown 声明承载不了这些动作。求值器因此落在本模块，且保持
**通用**：不认识任何具体 Epic / Story / 步骤 / 角色（AD-13），只解释
:class:`~heagent.engine.workflow_resource.StepValidationClauses` 的结构化子句。

三条硬边界：

1. **缺证据不能用文本补齐**（AD-5）：``command:`` 子句只认证据存内**可定位**的匹配记录；
   步骤输出里出现等价的命令文本 / 原始 dict 一律不算证据（tests/test_goal_quality_gates.py
   有变异锚点）。被截断的证据摘要在**前缀唯一命中**时才可作匹配——命中多条声明命令时
   显性判「无法定位匹配」，不任配。
2. **未通过不分「没跑」与「跑了没过」**：非零退出码、错误 cwd、过期（含**未来时间戳**）、
   证据归属不符、超时 / 取消 / 策略阻断都记为该子句未通过，理由逐条写进结构化报告——
   失败 / 超时 / 取消 / 策略阻断与「缺证据」在门禁语义上同归「未通过」。
3. **宿主门不可削弱**：``gate:`` 只能引用 :data:`QUALITY_GATES` 注册表里的名字（加载期由
   ``goal/workflow_loader`` 校验，未注册即 fail-loud）；每个注册名在注册表里**绑定自己的
   求值函数**（分派表，无名字级兜底），门语义由宿主实现，workflow 声明不了自己的门实现，
   也没有可调弱的参数。

``section:`` 是**既有文本门禁**（``WorkflowRunner`` 在步骤输出上的判定，保留不动）；本求值器
只在调用方提供步骤输出文本时复验同一判定（单一真源
:func:`heagent.engine.workflow_resource.output_contains_section`）。
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, Field

from heagent.engine.workflow_resource import output_contains_section
from heagent.goal.evidence import (
    TRUNCATION_MARKER,
    CommandEvidence,
    CommandOutcome,
    EvidenceError,
    EvidenceRecord,
    EvidenceStore,
    new_evidence_id,
)
from heagent.pub.safe_logging import redact_secrets

if TYPE_CHECKING:
    from heagent.engine.workflow_resource import StepValidationClauses, WorkflowStepResource
    from heagent.goal.evidence import GitEvidence


# ── 结构化求值结果（AD-4：跨模块只传模型）──────────────────────────────────


class ClauseKind(StrEnum):
    """被求值的声明子句类别（与 ``StepValidationClauses`` 的字段一一对应）。"""

    SECTION = "section"
    COMMAND = "command"
    ARTIFACT = "artifact"
    GIT = "git"
    GATE = "gate"


class ClauseResult(BaseModel):
    """一条声明子句的求值结论：通过 / 失败与原因（失败理由必须可定位到证据或缺失）。"""

    kind: ClauseKind
    target: str
    passed: bool
    reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    """一次求值的结构化报告：逐条子句结论 + 求值自身的显性失败 + 受控重跑产生的证据 id。"""

    goal_id: str
    step: str
    story_id: str | None = None
    rerun: bool = False
    rerun_evidence: list[str] = Field(default_factory=list)
    results: list[ClauseResult] = Field(default_factory=list)
    # 求值本身的显性失败（受控重跑无端口、证据绑定漂移、端口抛错）：任一存在即「未通过」。
    errors: list[str] = Field(default_factory=list)

    @property
    def failed(self) -> list[ClauseResult]:
        """Clauses that did not pass, in declaration order."""
        return [item for item in self.results if not item.passed]

    @property
    def passed(self) -> bool:
        """True only when nothing failed and the evaluation itself had no explicit errors."""
        return not self.errors and all(item.passed for item in self.results)

    def render(self) -> list[str]:
        """Deterministic lines every entry point writes (the CLI routes them through ``_echo``)."""
        scope = f"step={self.step}" + (f" story={self.story_id}" if self.story_id else "")
        if self.results:
            summary = f"{len(self.results) - len(self.failed)}/{len(self.results)} passed"
        elif self.errors:
            # 零子句但有求值错误：独立汇总文案——verdict=failed 与「没声明子句」不能自相矛盾（review #18）。
            summary = f"0 clause(s) evaluated; {len(self.errors)} evaluation error(s)"
        else:
            summary = "no structured clauses declared (text gate only)"
        lines = [
            f"[goal] verify: {scope} rerun={'yes' if self.rerun else 'no'} "
            f"verdict={'passed' if self.passed else 'failed'} ({summary})"
        ]
        for item in self.results:
            mark = "PASS" if item.passed else "FAIL"
            line = f"[goal] verify: {mark} {item.kind.value}: {item.target}"
            if item.reason:
                line += f" — {item.reason}"
            lines.append(line)
        for error in self.errors:
            lines.append(f"[goal] verify: ERROR {error}")
        if self.rerun_evidence:
            lines.append(f"[goal] verify: recorded evidence: {', '.join(self.rerun_evidence)}")
        return lines


#: 受控重跑端口：入口层把一条声明命令经治理链（``PolicyEngine.evaluate() → ToolExecutor →
#: SafetyGuard → handler``）执行并**证据化**。求值器自身从不执行命令（AD-6），只消费端口
#: 产出的证据。
GovernedCommandPort = Callable[[str], Awaitable[CommandEvidence]]

# 命令证据的时效缺省：过期证据不再满足 ``command:`` / ``tests-pass``（AC：过期证据不通过）。
# 不引入顶层配置键（声明面口径）：需要不同窗口的工作流仍由调用方注入。
DEFAULT_EVIDENCE_MAX_AGE: Final = timedelta(hours=24)

# 失败理由里变更清单的上限：理由是给人读的，超长列表截断并计数（不静默丢语义）。
_MAX_REASON_CHANGES = 8


@dataclass(frozen=True)
class _GateContext:
    """一个命名门求值时可看的全部输入（每门同参，注册表分派统一形状）。"""

    declared_commands: list[str]
    entries: list[tuple[EvidenceRecord, CommandEvidence]]
    workspace: Path
    git: GitEvidence | None
    moment: datetime
    max_age: timedelta


# ── ``gate:`` 注册表：宿主内置命名质量门的通用词汇（名字 → 语义 + 求值函数）──────

GATE_TESTS_PASS = "tests-pass"  # noqa: S105 - gate vocabulary label, not a credential
GATE_GIT_CHANGES = "git-changes"


def _eval_tests_pass(context: _GateContext) -> ClauseResult:
    """``tests-pass``：步骤声明的每条 ``command:`` 的**最新证据**都必须通过（同 ``command:`` 判定）。

    cwd 正确、未过期、成功的检查因此与 ``command:`` 子句天然同规（同一
    :func:`_command_defect`）——它不是「范围内全量证据」的投影：范围内无关的旧证据不拖累门，
    重跑出新的成功证据即可放行（失败→修复→放行、过期→重跑→放行都成立，review #2）。
    """
    if not context.declared_commands:
        return ClauseResult(
            kind=ClauseKind.GATE,
            target=GATE_TESTS_PASS,
            passed=False,
            reason="no 'command:' clause is declared on this step; this gate has no evidence source to project "
            "(declare it together with at least one command clause)",
        )
    failures: list[str] = []
    evidence_ids: list[str] = []
    for declared in context.declared_commands:
        match, kind = _newest_match(context.entries, declared)
        if match is None:
            failures.append(f"{declared}: no matching command evidence is recorded")
            continue
        if kind == "prefix" and _truncated_prefix_is_ambiguous(context.declared_commands, declared, match[1].command):
            failures.append(f"{declared}: truncated evidence matches multiple declared commands; cannot locate")
            continue
        record, evidence = match
        evidence_ids.append(record.evidence_id)
        defect = _command_defect(
            evidence, record, workspace=context.workspace, moment=context.moment, max_age=context.max_age
        )
        if defect:
            failures.append(f"{declared}: {defect}")
    if failures:
        return ClauseResult(
            kind=ClauseKind.GATE,
            target=GATE_TESTS_PASS,
            passed=False,
            reason=(
                f"{len(failures)} of {len(context.declared_commands)} declared command(s) not verified "
                f"(first: {failures[0]})"
            ),
            evidence_ids=evidence_ids,
        )
    return ClauseResult(
        kind=ClauseKind.GATE,
        target=GATE_TESTS_PASS,
        passed=True,
        reason=f"all {len(context.declared_commands)} declared command(s) verified succeeded",
        evidence_ids=evidence_ids,
    )


def _eval_git_changes(context: _GateContext) -> ClauseResult:
    """``git-changes``：当前范围必须存在 Git 变更证据且变更集非空。"""
    if context.git is None:
        return ClauseResult(
            kind=ClauseKind.GATE,
            target=GATE_GIT_CHANGES,
            passed=False,
            reason="no git evidence is recorded in this scope",
        )
    changes = [*context.git.changed_files, *context.git.untracked_files]
    if not changes:
        return ClauseResult(
            kind=ClauseKind.GATE,
            target=GATE_GIT_CHANGES,
            passed=False,
            reason="git evidence records no changes (tracked or untracked)",
        )
    return ClauseResult(
        kind=ClauseKind.GATE,
        target=GATE_GIT_CHANGES,
        passed=True,
        reason=f"git evidence records {len(changes)} changed path(s)",
    )


class QualityGateSpec(BaseModel):
    """注册表条目：名字 + 宿主语义说明 + **绑定的求值函数**。

    ``evaluate`` 是该门唯一的求值实现（分派表，无名字级兜底，review #5）：注册一个门 =
    同时给出它的语义说明与求值函数；只登记名字不给实现进不了注册表。
    """

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evaluate: Callable[[_GateContext], ClauseResult]


#: 宿主内置命名质量门（通用词汇，AD-13/AD-14）：全部是**证据投影**——只读当前范围的证据
#: 并给结论，不含任何具体流程知识；workflow 只能引用名字，不能提供实现或削弱参数。
QUALITY_GATES: Final[Mapping[str, QualityGateSpec]] = MappingProxyType(
    {
        GATE_TESTS_PASS: QualityGateSpec(
            name=GATE_TESTS_PASS,
            description="步骤声明的每条 'command:' 子句的最新证据都必须成功（cwd 正确、未过期）；"
            "必须与至少一条 command: 子句同用——单独声明没有证据来源，加载期即拒绝。",
            evaluate=_eval_tests_pass,
        ),
        GATE_GIT_CHANGES: QualityGateSpec(
            name=GATE_GIT_CHANGES,
            description="当前范围必须存在 Git 变更证据，且变更集（tracked 变更或未跟踪文件）非空。",
            evaluate=_eval_git_changes,
        ),
    }
)


def is_registered_gate(name: str) -> bool:
    """``gate:`` 名字是否在宿主注册表内（``goal/workflow_loader`` 加载期校验的唯一判据）。"""
    return name in QUALITY_GATES


def gate_declaration_problem(clauses: StepValidationClauses) -> str | None:
    """命名门声明的**必要条件**（加载期校验；缺条件 = 声明错误，与未注册同归 fail-loud）。"""
    if GATE_TESTS_PASS in clauses.gates and not clauses.commands:
        return (
            f"quality gate '{GATE_TESTS_PASS}' projects the latest evidence of this step's declared "
            f"'command:' clauses; declare it together with at least one command clause "
            f"(alone it has no evidence source)"
        )
    return None


# ── 求值器 ────────────────────────────────────────────────────────────


async def verify_step(
    step: WorkflowStepResource,
    *,
    store: EvidenceStore,
    goal_id: str,
    story_id: str | None,
    workspace: Path,
    workflow_id: str = "",
    revision: str = "",
    output_text: str | None = None,
    git_evidence: GitEvidence | None = None,
    max_age: timedelta = DEFAULT_EVIDENCE_MAX_AGE,
    now: datetime | None = None,
    rerun: bool = False,
    run_command: GovernedCommandPort | None = None,
) -> VerificationReport:
    """Evaluate one step's declared structured clauses against evidence, artifacts and Git.

    证据范围 = ``goal_id`` + 步骤名 + **确切**的 ``story_id``（步骤级证据 ``story_id=None``
    只对步骤级求值可见；Story 步骤的求值看不到步骤级记录——归属必须同名同 Story）。
    ``workflow_id`` / ``revision`` 单侧声明漂移的证据被显性排除并进
    :attr:`VerificationReport.errors`。

    ``rerun=True`` 时先经 ``run_command`` 端口受控重跑声明的命令并落证据（append-only），
    再求值；声明了命令却拿不到端口 = 求值显性失败，绝不静默当作通过。求值时刻 ``now``
    在**重跑之后**取值：重跑刚落盘的证据不能因取值次序被误判成未来时间戳。
    """
    clauses = step.validation_clauses
    errors: list[str] = []
    rerun_ids: list[str] = []
    if rerun:
        errors.extend(
            await _controlled_rerun(
                clauses.commands,
                run_command,
                store=store,
                goal_id=goal_id,
                story_id=story_id,
                step_name=step.name,
                workflow_id=workflow_id,
                revision=revision,
                rerun_ids=rerun_ids,
            )
        )
    scope, drifted = await _collect_scope(
        store,
        step_name=step.name,
        goal_id=goal_id,
        story_id=story_id,
        workflow_id=workflow_id,
        revision=revision,
    )
    for record in drifted:
        errors.append(
            f"evidence {record.evidence_id} declares a different workflow binding "
            f"(workflow_id={record.workflow_id!r}, revision={record.revision!r}); excluded from this evaluation"
        )
    commands = [(record, evidence) for record in scope for evidence in record.commands]
    moment = now or datetime.now(UTC)
    scope_git = git_evidence or next((record.git for record in reversed(scope) if record.git is not None), None)
    gate_context = _GateContext(
        declared_commands=list(clauses.commands),
        entries=commands,
        workspace=workspace,
        git=scope_git,
        moment=moment,
        max_age=max_age,
    )
    results = [
        *_section_results(clauses, output_text),
        *_command_results(clauses, commands, workspace=workspace, moment=moment, max_age=max_age),
        *(await _artifact_results(clauses, workspace)),
        *_git_results(clauses, scope_git),
        *_gate_results(clauses.gates, gate_context),
    ]
    return VerificationReport(
        goal_id=goal_id,
        step=step.name,
        story_id=story_id,
        rerun=rerun,
        rerun_evidence=rerun_ids,
        results=results,
        errors=errors,
    )


async def _controlled_rerun(
    declared_commands: list[str],
    run_command: GovernedCommandPort | None,
    *,
    store: EvidenceStore,
    goal_id: str,
    story_id: str | None,
    step_name: str,
    workflow_id: str,
    revision: str,
    rerun_ids: list[str],
) -> list[str]:
    """受控重跑声明的命令并逐条落证据；返回显性失败文案（空 = 全部落盘成功）。"""
    if not declared_commands:
        return []
    if run_command is None:
        return ["controlled re-run has no governed command runner; declared commands cannot be verified"]
    errors: list[str] = []
    for command in declared_commands:
        try:
            evidence = await run_command(command)
        except Exception as exc:  # noqa: BLE001 - 端口失败 = 该命令未通过，显性记录不吞
            errors.append(f"controlled re-run of {command!r} failed: {exc}")
            continue
        record = EvidenceRecord(
            evidence_id=new_evidence_id(),
            goal_id=goal_id,
            workflow_id=workflow_id,
            revision=revision,
            step=step_name,
            story_id=story_id,
            commands=[evidence],
        )
        try:
            await store.append(record)
        except (EvidenceError, OSError) as exc:
            errors.append(f"evidence recording failed for {command!r}: {exc}")
            continue
        rerun_ids.append(record.evidence_id)
    return errors


async def _collect_scope(
    store: EvidenceStore,
    *,
    step_name: str,
    goal_id: str,
    story_id: str | None,
    workflow_id: str,
    revision: str,
) -> tuple[list[EvidenceRecord], list[EvidenceRecord]]:
    """范围内证据（goal + 步骤 + **确切** story 绑定）与绑定漂移证据，按记录时间升序返回。

    Story 归属是**严格相等**：步骤级记录（``story_id=None``）只对步骤级求值可见；Story
    步骤的求值看不到步骤级证据——否则一条未绑定 Story 的旧记录能冒充任何 Story 的证据
    （review #6）。漂移 = 记录与本侧**都声明了** ``workflow_id`` / ``revision`` 且不相等：
    排除并让调用方显性报告（不静默当作匹配证据）。
    """
    scope: list[EvidenceRecord] = []
    drifted: list[EvidenceRecord] = []
    for record in await store.list_records(goal_id=goal_id):
        if record.step != step_name or record.story_id != story_id:
            continue
        if any(
            expected and actual and expected != actual
            for expected, actual in ((workflow_id, record.workflow_id), (revision, record.revision))
        ):
            drifted.append(record)
            continue
        scope.append(record)
    return scope, drifted


def _section_results(clauses: StepValidationClauses, output_text: str | None) -> list[ClauseResult]:
    """``section:`` 复验（既有文本门禁同一判定）；没有输出文本 = 显性未过，不静默跳过。"""
    results: list[ClauseResult] = []
    for section in clauses.sections:
        present = output_text is not None and output_contains_section(output_text, section)
        reason = (
            ""
            if present
            else (
                "no step output was provided for the section gate"
                if output_text is None
                else f"output does not contain the required heading: ## {section}"
            )
        )
        results.append(ClauseResult(kind=ClauseKind.SECTION, target=section, passed=present, reason=reason))
    return results


def _command_results(
    clauses: StepValidationClauses,
    entries: list[tuple[EvidenceRecord, CommandEvidence]],
    *,
    workspace: Path,
    moment: datetime,
    max_age: timedelta,
) -> list[ClauseResult]:
    """``command:`` 子句：最新一条**匹配**证据必须成功、cwd 正确且未过期。"""
    results: list[ClauseResult] = []
    for declared in clauses.commands:
        match, kind = _newest_match(entries, declared)
        if match is None:
            results.append(
                ClauseResult(
                    kind=ClauseKind.COMMAND,
                    target=declared,
                    passed=False,
                    reason="no matching command evidence is recorded for this step/story "
                    "(a Markdown claim is not evidence)",
                )
            )
            continue
        record, evidence = match
        # 截断证据的前缀匹配必须**唯一**：同一条截断摘要命中多条声明命令时无法定位是哪条
        # 命令的证据，显性判不匹配（review #7），不做任配。
        if kind == "prefix" and _truncated_prefix_is_ambiguous(clauses.commands, declared, evidence.command):
            results.append(
                ClauseResult(
                    kind=ClauseKind.COMMAND,
                    target=declared,
                    passed=False,
                    reason="truncated evidence prefix-matches multiple declared commands; cannot locate the match",
                )
            )
            continue
        reason = _command_defect(evidence, record, workspace=workspace, moment=moment, max_age=max_age)
        results.append(
            ClauseResult(
                kind=ClauseKind.COMMAND,
                target=declared,
                passed=not reason,
                reason=reason,
                evidence_ids=[record.evidence_id],
            )
        )
    return results


def _newest_match(
    entries: list[tuple[EvidenceRecord, CommandEvidence]], declared: str
) -> tuple[tuple[EvidenceRecord, CommandEvidence] | None, str | None]:
    """最新一条与声明命令同身份的证据；返回 ``((record, evidence), kind)`` 或 ``(None, None)``。

    ``kind`` 是匹配的强度：``exact``（身份串相等）或 ``prefix``（仅经截断前缀命中）。
    """
    for record, evidence in reversed(entries):
        kind = _match_kind(declared, evidence.command)
        if kind is not None:
            return (record, evidence), kind
    return None, None


def _normalized_declared(declared: str) -> str:
    """声明命令的比较形式：先 ``redact_secrets``（与 recorded 侧**同规**，review #8），再压空白。"""
    return " ".join(redact_secrets(declared).split())


def _normalized_recorded(evidence_command: str) -> str:
    """证据摘要的比较形式：压空白（摘要已在落盘时脱敏）。"""
    return " ".join(evidence_command.split())


# 受治理重跑把声明命令包在工作区 ``cd`` 前缀里执行（cli/goal 的 `_workspace_cd_prefix`）；
# 两个格式必须同源——这里只认包装的**形状**（cd [+ /d] + 引号路径 + ``&&``），路径值不进本模块。
_CD_WRAPPER_PREFIX = re.compile(r"^cd\s+(?:/d\s+)?(?:\"[^\"]*\"|'[^']*')\s*&&\s*")


def _strip_workspace_cd(evidence_command: str) -> str:
    """剥掉受治理重跑的工作区定位前缀（与 cli/goal 的包装同一格式约定，review #1）。"""
    return _CD_WRAPPER_PREFIX.sub("", evidence_command, count=1)


def _match_kind(declared: str, evidence_command: str) -> str | None:
    """声明命令与证据摘要的身份匹配；返回 ``exact`` / ``prefix`` / ``None``。

    身份串：声明侧先 ``redact_secrets`` 再压空白（与 recorded 侧同规，review #8）；证据侧
    依次尝试全文与剥掉工作区 cd 包装后的形式。
    """
    want = _normalized_declared(declared)
    for got in (_normalized_recorded(evidence_command), _normalized_recorded(_strip_workspace_cd(evidence_command))):
        if got == want:
            return "exact"
        prefix = got.removesuffix(TRUNCATION_MARKER).rstrip()
        if got.endswith(TRUNCATION_MARKER) and bool(prefix) and want.startswith(prefix):
            return "prefix"
    return None


def _truncated_prefix_is_ambiguous(declared_commands: list[str], declared: str, evidence_command: str) -> bool:
    """截断证据的前缀匹配是否歧义：同一条摘要还命中了**其他**声明命令（review #7）。"""
    return sum(1 for other in declared_commands if _match_kind(other, evidence_command) is not None) > 1


def _command_defect(
    evidence: CommandEvidence, record: EvidenceRecord, *, workspace: Path, moment: datetime, max_age: timedelta
) -> str:
    """最新匹配证据的缺陷文案；空串 = 成功、cwd 正确且未过期。"""
    if evidence.outcome is not CommandOutcome.SUCCEEDED:
        detail = f"recorded outcome is {evidence.outcome.value}"
        if evidence.exit_code is not None:
            detail += f" (exit code {evidence.exit_code})"
        return detail
    if not _same_directory(evidence.cwd, workspace):
        return f"evidence cwd {evidence.cwd!r} does not match the workspace root {str(workspace)!r}"
    recorded = _recorded_at(record)
    if recorded is None:
        return f"evidence {record.evidence_id} has an unparsable timestamp: {record.created_at!r}"
    if recorded > moment:
        return f"evidence {record.evidence_id} has a future timestamp ({record.created_at}); treated as expired"
    if moment - recorded > max_age:
        return f"evidence {record.evidence_id} is expired (recorded {record.created_at}; older than {max_age})"
    return ""


def _recorded_at(record: EvidenceRecord) -> datetime | None:
    """证据创建时刻（UTC）；无法解析返回 ``None``（调用方显性判未过，不猜测）。"""
    try:
        recorded = datetime.fromisoformat(record.created_at)
    except ValueError:
        return None
    return recorded if recorded.tzinfo is not None else recorded.replace(tzinfo=UTC)


def _same_directory(left: str, right: Path) -> bool:
    """cwd 一致性：两侧都按解析后的规范路径比较（符号链接 / 盘符大小写不误伤）。

    空串 / 含 null byte 的 cwd **判不匹配**：``Path("")`` 会落成当前目录（空 cwd 冒充
    「就是在正确目录跑的」）、null byte 让 ``Path`` 抛 ``ValueError``（review #12）。
    """
    if not left or "\x00" in left:
        return False
    try:
        return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(right.resolve()))
    except (OSError, ValueError):
        return False


async def _artifact_results(clauses: StepValidationClauses, workspace: Path) -> list[ClauseResult]:
    """``artifact:`` 子句：工作区内该产物**文件**必须存在（目录不算产物，review #11）。"""
    results: list[ClauseResult] = []
    for declared in clauses.artifacts:
        is_file = await asyncio.to_thread((workspace / declared).is_file)
        results.append(
            ClauseResult(
                kind=ClauseKind.ARTIFACT,
                target=declared,
                passed=is_file,
                reason="" if is_file else "artifact is missing from the workspace (or is not a file)",
            )
        )
    return results


def _normalized_git_path(value: str) -> str:
    """Git 路径的比对形式：去引号 / 反斜线归一 / ``./`` 前缀剥除 / 大小写归一（review #9）。"""
    text = value.strip().strip('"').strip("'").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.casefold().rstrip("/")


def _git_path_touched(declared: str, changed: list[str]) -> bool:
    """声明路径是否被变更集触及：精确相等，或声明是**目录前缀**（其下任一变更命中）。"""
    want = _normalized_git_path(declared)
    if not want:
        return False
    for path in changed:
        got = _normalized_git_path(path)
        if got == want or got.startswith(f"{want}/"):
            return True
    return False


def _git_results(clauses: StepValidationClauses, evidence: GitEvidence | None) -> list[ClauseResult]:
    """``git:`` 子句：该路径必须出现在 Git 变更集（tracked 变更或未跟踪文件）里。"""
    if not clauses.git_paths:
        return []
    if evidence is None:
        return [
            ClauseResult(
                kind=ClauseKind.GIT,
                target=declared,
                passed=False,
                reason="no git evidence: no live query was provided and none is recorded for this step/story",
            )
            for declared in clauses.git_paths
        ]
    changed = [*evidence.changed_files, *evidence.untracked_files]
    overflow = len(changed) - _MAX_REASON_CHANGES
    listing = ", ".join(changed[:_MAX_REASON_CHANGES]) + (f" (+{overflow} more)" if overflow > 0 else "")
    results: list[ClauseResult] = []
    for declared in clauses.git_paths:
        touched = _git_path_touched(declared, changed)
        results.append(
            ClauseResult(
                kind=ClauseKind.GIT,
                target=declared,
                passed=touched,
                reason="" if touched else f"no recorded change touches this path (changes: {listing or 'none'})",
            )
        )
    return results


def _gate_results(gate_names: list[str], context: _GateContext) -> list[ClauseResult]:
    """``gate:`` 子句：按注册表**分派表**求值（每名绑定自己的求值函数，无兜底，review #5）。"""
    results: list[ClauseResult] = []
    for name in gate_names:
        spec = QUALITY_GATES.get(name)
        if spec is None:
            results.append(
                ClauseResult(
                    kind=ClauseKind.GATE,
                    target=name,
                    passed=False,
                    reason=f"gate is not registered; registered gates: {', '.join(sorted(QUALITY_GATES))}",
                )
            )
            continue
        results.append(spec.evaluate(context))
    return results
