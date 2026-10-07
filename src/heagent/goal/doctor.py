"""Read-only preflight of a configured Goal workflow and its role packages.

The preflight grades every observation instead of returning one flat string list:
``FAIL`` blocks a run, ``WARN`` is reported without blocking, ``PASS`` records the
checks that actually ran.  Grading matters because "no problems found" and "some
checks never ran" must not render the same way.

**Which checks run is declared, not hard-coded**: the workflow's ``doctor_checks``
frontmatter key picks an ordered subset of :data:`_CHECKS`; absent means
:data:`DEFAULT_DOCTOR_CHECKS`, so an existing package keeps its behaviour.  The
registry is the engine's generic vocabulary — no entry may know about a specific
workflow, step or role.
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
    from heagent.memory.skill_packages import SkillPackage

_TEMPLATE_PREFIX = "templates/"


class DoctorSeverity(StrEnum):
    """Grading of one preflight observation; ``WARN`` never counts as a pass."""

    PASS = "pass"  # noqa: S105 - grading label, not a credential
    WARN = "warn"
    FAIL = "fail"


class DoctorFinding(BaseModel):
    """One structured preflight observation."""

    severity: DoctorSeverity
    code: str = Field(min_length=1)
    subject: str = ""
    detail: str = ""

    def render(self) -> str:
        """One human-readable line; the ``subject: detail`` shape is a stable contract."""
        return f"{self.subject}: {self.detail}" if self.subject else self.detail


class GoalDoctorReport(BaseModel):
    """Structured, read-only preflight result for one Goal workflow."""

    workflow: str
    # 声明里实际跑过的检查（按声明顺序）；报告自身也记录它，避免「没跑」被读成「没问题」。
    checks: list[DoctorCheck] = Field(default_factory=list)
    findings: list[DoctorFinding] = Field(default_factory=list)

    @property
    def problems(self) -> list[DoctorFinding]:
        """Findings a caller has to act on or report (everything but ``PASS``)."""
        return [finding for finding in self.findings if finding.severity is not DoctorSeverity.PASS]

    @property
    def ok(self) -> bool:
        """True when nothing failed; a ``WARN`` is surfaced but does not block a run."""
        return all(finding.severity is not DoctorSeverity.FAIL for finding in self.findings)

    def render(self) -> str:
        """Stable one-line summary (the historical ``/goal doctor`` text when nothing is wrong)."""
        rendered = [finding.render() for finding in self.problems]
        return "; ".join(rendered) if rendered else "workflow packages OK"


@dataclass(frozen=True)
class _CheckContext:
    """Everything one preflight check may look at (all read-only)."""

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
    """Run the declared preflight checks and return a structured report.

    Every read goes through :class:`SkillPackage`, so an unreachable entry, a resource
    removed after loading, or a pinned-hash drift all surface as an explicit finding
    instead of silently succeeding.
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
    """The package entry and its ``workflow.md`` must both stay readable and hash-stable."""
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
    """Re-read every declared required resource so post-load drift cannot pass unnoticed."""
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
    """Report templates the package does not carry.

    A missing template is a ``WARN`` unless ``required_resources`` declares it — that case
    is already a hard failure reported by :func:`_check_required_resources`, and reporting
    it twice would make one problem look like two.
    """
    workflow = context.workflow
    provided = {"prompt-template.md": workflow.prompt_template, "gate-template.md": workflow.gate_template}
    return [
        DoctorFinding(
            severity=DoctorSeverity.WARN,
            code="optional_template_missing",
            subject=f"template {name}",
            detail="package does not provide it",
        )
        for name, body in provided.items()
        if name not in context.required and not body.strip()
    ]


def _check_roles(context: _CheckContext) -> list[DoctorFinding]:
    """Every role a step declares must resolve to a readable package."""
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
    """Probe the resolved checkpoint directory when the caller supplied one."""
    if context.checkpoint_dir is None:
        return []
    return [_probe_checkpoint_dir(context.checkpoint_dir)]


def _probe_checkpoint_dir(directory: Path) -> DoctorFinding:
    """Prove the checkpoint directory is writable without persisting any artifact.

    ``atomic_write_text`` creates missing parents, so an absent directory is not a
    problem by itself; the probe therefore targets the nearest existing ancestor
    instead of creating directories during a read-only preflight.  The probe writes
    and immediately drops one temporary file — no checkpoint, workflow state or goal
    document is touched.
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
