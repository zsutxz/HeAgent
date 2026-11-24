"""对已配置的 Goal 工作流及其角色包做只读预检。

预检给每条观察结果分级，而不是返回一个扁平字符串列表：
``FAIL`` 阻断运行，``WARN`` 只报告不阻断，``PASS`` 记录真正跑过的检查。
分级之所以重要，是因为「没发现问题」与「有些检查根本没跑」不能渲染成同一形态。

**跑哪些检查是声明的，不是硬编码的**：工作流的 ``doctor_checks``
frontmatter 键从 :data:`_CHECKS` 里挑出一个有序子集；缺省即
:data:`DEFAULT_DOCTOR_CHECKS`，因此既有包保持原有行为。该注册表是引擎的
通用词汇表——任何条目都不得知道具体的工作流、步骤或角色。
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from heagent.engine.workflow_resource import (
    DoctorCheck,  # noqa: TC001 - pydantic resolves the field annotation at class build
)
from heagent.goal.workflow_loader import frontmatter_name_list

if TYPE_CHECKING:
    from pathlib import Path

    from heagent.engine.workflow_resource import WorkflowResource
    from heagent.skills.skill_packages import SkillPackage

_TEMPLATE_PREFIX = "templates/"


class DoctorSeverity(StrEnum):
    """对单条预检观察结果的分级；``WARN`` 永不计为通过。"""

    PASS = "pass"  # nosec B105 - 分级标签，非凭证 # noqa: S105
    WARN = "warn"
    FAIL = "fail"


class DoctorFinding(BaseModel):
    """一条结构化的预检观察结果。"""

    severity: DoctorSeverity
    code: str = Field(min_length=1)
    subject: str = ""
    detail: str = ""

    def render(self) -> str:
        """单行人读文本；``subject: detail`` 的形态是稳定契约。"""
        return f"{self.subject}: {self.detail}" if self.subject else self.detail


class GoalDoctorReport(BaseModel):
    """某个 Goal 工作流的结构化只读预检结果。"""

    workflow: str
    # 声明里实际跑过的检查（按声明顺序）；报告自身也记录它，避免「没跑」被读成「没问题」。
    checks: list[DoctorCheck] = Field(default_factory=list)
    findings: list[DoctorFinding] = Field(default_factory=list)

    @property
    def problems(self) -> list[DoctorFinding]:
        """调用方必须处理或上报的 finding（除 ``PASS`` 外的全部）。"""
        return [finding for finding in self.findings if finding.severity is not DoctorSeverity.PASS]

    @property
    def ok(self) -> bool:
        """无失败即 True；``WARN`` 会露出但不阻断运行。"""
        return all(finding.severity is not DoctorSeverity.FAIL for finding in self.findings)

    def render(self) -> str:
        """稳定的一行摘要（无问题时即历史 ``/goal doctor`` 文案）。"""
        rendered = [finding.render() for finding in self.problems]
        return "; ".join(rendered) if rendered else "workflow packages OK"


@dataclass(frozen=True)
class _CheckContext:
    """单条预检检查可看到的一切（全部只读）。"""

    workflow: WorkflowResource
    package: SkillPackage
    resolve_role: Callable[[str], SkillPackage | None]
    required: list[str]
    checkpoint_dir: Path | None


CheckFn = Callable[["_CheckContext"], "list[DoctorFinding]"]


def diagnose_workflow(
    workflow: WorkflowResource,
    package: SkillPackage,
    resolve_role: Callable[[str], SkillPackage | None],
    *,
    checkpoint_dir: Path | None = None,
) -> GoalDoctorReport:
    """运行已声明的预检检查，返回结构化报告。

    所有读取都经 :class:`SkillPackage`，因此不可达的条目、加载后被移除的资源、
    固定哈希漂移，都会以显式 finding 浮出，而不是悄悄算作通过。
    """
    declared = list(workflow.doctor_checks) or list(DEFAULT_DOCTOR_CHECKS)
    context = _CheckContext(
        workflow=workflow,
        package=package,
        resolve_role=resolve_role,
        required=_declared_required(workflow),
        checkpoint_dir=checkpoint_dir,
    )
    findings: list[DoctorFinding] = []
    for name in declared:
        findings.extend(_CHECKS[name](context))
    return GoalDoctorReport(workflow=workflow.name, checks=declared, findings=findings)


def _check_package(context: _CheckContext) -> list[DoctorFinding]:
    """包条目与其 ``workflow.md`` 都必须保持可读且哈希稳定。"""
    package = context.package
    checks: tuple[tuple[str, Callable[[], object]], ...] = (
        ("workflow_entry_unreadable", package.read_entry),
        ("workflow_resource_unreadable", lambda: package.read_resource("workflow.md")),
    )
    findings: list[DoctorFinding] = []
    for code, read in checks:
        try:
            read()
        except (OSError, ValueError) as exc:
            findings.append(
                DoctorFinding(severity=DoctorSeverity.FAIL, code=code, subject="workflow package", detail=str(exc))
            )
    if not findings:
        findings.append(
            DoctorFinding(
                severity=DoctorSeverity.PASS,
                code="workflow_package_ok",
                subject="workflow package",
                detail="entry and workflow.md are readable",
            )
        )
    return findings


def _declared_required(workflow: WorkflowResource) -> list[str]:
    """Resource names from the workflow's ``required_resources`` declaration (order preserved).

    A30②：解析核与 loader 的 :func:`~heagent.goal.workflow_loader.frontmatter_name_list`
    单源。类型不符返回空表是**有意的宽容度分叉**——doctor 对老工作流 fail-soft（缺声明
    = 无必查项，诊断照常跑完），loader 对新工作流 fail-closed；判据见
    ``test_goal_doctor.py::test_declared_required_tolerance_divergence_is_intentional``。
    """
    items = frontmatter_name_list(workflow.frontmatter.get("required_resources"))
    if items is None:
        return []
    return [item.removeprefix(_TEMPLATE_PREFIX) for item in items]


def _check_required_resources(context: _CheckContext) -> list[DoctorFinding]:
    """重读每条声明的必需资源，使加载后的漂移无法蒙混过关。"""
    findings: list[DoctorFinding] = []
    for name in context.required:
        subject = f"required resource {name}"
        try:
            text = context.package.read_template(name)
        except (OSError, ValueError) as exc:
            findings.append(
                DoctorFinding(
                    severity=DoctorSeverity.FAIL, code="required_resource_unreadable", subject=subject, detail=str(exc)
                )
            )
            continue
        if not text.strip():
            findings.append(
                DoctorFinding(
                    severity=DoctorSeverity.FAIL,
                    code="required_resource_blank",
                    subject=subject,
                    detail="declared in required_resources but blank",
                )
            )
        else:
            findings.append(
                DoctorFinding(
                    severity=DoctorSeverity.PASS, code="required_resource_ok", subject=subject, detail="present"
                )
            )
    return findings


def _check_templates(context: _CheckContext) -> list[DoctorFinding]:
    """Report template declarations that will not resolve, and gates left undeclared.

    ``prompt_template`` / ``gate_template`` 指名文件在加载阶段已强制存在；这里的发现意味着
    装载后的漂移。反过来，步骤声明了 ``validation:`` 而包未声明 ``gate_template`` 的包会在
    渲染门禁时显性失败——值得在任何 goal 运行前给出 ``WARN``。
    """
    workflow = context.workflow
    declared = {
        str(workflow.frontmatter.get(key) or "").strip(): body
        for key, body in (
            ("prompt_template", workflow.prompt_template),
            ("gate_template", workflow.gate_template),
        )
    }
    findings = [
        DoctorFinding(
            severity=DoctorSeverity.WARN,
            code="optional_template_missing",
            subject=f"template {name.removeprefix('templates/')}",
            detail="declared but not provided",
        )
        for name, body in sorted(declared.items())
        if name and not body.strip()
    ]
    if not str(workflow.frontmatter.get("gate_template") or "").strip() and any(
        step.validation_rules.strip() for step in workflow.steps
    ):
        findings.append(
            DoctorFinding(
                severity=DoctorSeverity.WARN,
                code="gate_template_undeclared",
                subject="gate_template",
                detail="steps declare validation but frontmatter declares no gate_template",
            )
        )
    return findings


def _check_roles(context: _CheckContext) -> list[DoctorFinding]:
    """步骤声明的每个角色都必须能解析到一个可读的包。"""
    findings: list[DoctorFinding] = []
    roles = sorted({step.role.strip() for step in context.workflow.steps if step.role.strip()})
    for role in roles:
        role_package = context.resolve_role(role)
        if role_package is None:
            findings.append(
                DoctorFinding(
                    severity=DoctorSeverity.FAIL,
                    code="role_package_missing",
                    subject="role package missing",
                    detail=role,
                )
            )
            continue
        try:
            role_package.read_entry()
        except (OSError, ValueError) as exc:
            findings.append(
                DoctorFinding(
                    severity=DoctorSeverity.FAIL,
                    code="role_package_unreadable",
                    subject=f"role package {role}",
                    detail=str(exc),
                )
            )
        else:
            findings.append(
                DoctorFinding(
                    severity=DoctorSeverity.PASS,
                    code="role_package_ok",
                    subject=f"role package {role}",
                    detail="entry is readable",
                )
            )
    return findings


def _check_checkpoint_dir(context: _CheckContext) -> list[DoctorFinding]:
    """调用方提供了 checkpoint 目录时，探测解析后的该目录。"""
    if context.checkpoint_dir is None:
        return []
    return [_probe_checkpoint_dir(context.checkpoint_dir)]


def _probe_checkpoint_dir(directory: Path) -> DoctorFinding:
    """在不落任何产物的前提下证明 checkpoint 目录可写。

    ``atomic_write_text`` 会创建缺失的父目录，因此目录不存在本身不算问题；
    探针改为瞄准最近的存在祖先，而不是在只读预检里造目录。探针只写一个临时
    文件并立即删除——不碰任何 checkpoint、工作流状态或 goal 文档。
    """
    subject = "checkpoint directory"
    if directory.exists() and not directory.is_dir():
        return DoctorFinding(
            severity=DoctorSeverity.FAIL,
            code="checkpoint_dir_not_a_directory",
            subject=subject,
            detail=f"{directory} exists and is not a directory",
        )
    target = next((candidate for candidate in (directory, *directory.parents) if candidate.is_dir()), None)
    if target is None:
        return DoctorFinding(
            severity=DoctorSeverity.FAIL,
            code="checkpoint_dir_unreachable",
            subject=subject,
            detail=f"{directory} has no existing directory in its ancestry",
        )
    try:
        with tempfile.TemporaryFile(dir=target):
            pass
    except OSError as exc:
        return DoctorFinding(
            severity=DoctorSeverity.FAIL, code="checkpoint_dir_unwritable", subject=subject, detail=f"{target}: {exc}"
        )
    return DoctorFinding(
        severity=DoctorSeverity.PASS,
        code="checkpoint_dir_writable",
        subject=subject,
        detail=f"{directory} (probed at {target})",
    )


# 通用检查注册表：名字即 ``engine.workflow_resource.DOCTOR_CHECKS`` 的词汇；
# 每个条目对所有 workflow 成立，不得出现具体 Epic / 步骤 / 角色的判断。
_CHECKS: dict[str, CheckFn] = {
    "package": _check_package,
    "required_resources": _check_required_resources,
    "templates": _check_templates,
    "roles": _check_roles,
    "checkpoint_dir": _check_checkpoint_dir,
}

# 未声明 ``doctor_checks`` 的包跑的默认集（与本次改动前的行为一致）。
DEFAULT_DOCTOR_CHECKS: tuple[DoctorCheck, ...] = (
    "package",
    "required_resources",
    "templates",
    "roles",
    "checkpoint_dir",
)
