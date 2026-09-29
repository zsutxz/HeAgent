"""The declared workflow vocabulary (``doctor_checks`` / ``status_fields``) drives behaviour.

These are contract tests for the declaration *mechanism*: what a workflow may declare, what
happens when it declares something the engine does not know, and that the engine registries
stay in step with the vocabulary the declaration model publishes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from heagent.engine.checkpoint import WorkflowStatus
from heagent.engine.workflow_resource import (
    DOCTOR_CHECKS,
    STATUS_FIELDS,
    WorkflowResource,
    WorkflowStepResource,
)
from heagent.engine.workflow_runner import WorkflowRunnerState
from heagent.goal import doctor as doctor_module
from heagent.goal import status_view as status_view_module
from heagent.goal.doctor import diagnose_workflow
from heagent.goal.status_view import DEFAULT_STATUS_FIELDS, project_status_view
from heagent.goal.workflow_loader import SkillWorkflowError, read_workflow
from heagent.memory.skill_packages import SkillPackage

_STEP_BODY = "\n## Step 01: plan\n\n指令正文\n"


def _package(tmp_path: Path, frontmatter: str) -> SkillPackage:
    root = tmp_path / "wf"
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text("---\nname: wf\ndescription: example\n---\n", encoding="utf-8")
    (root / "workflow.md").write_text(f"---\n{frontmatter}---\n{_STEP_BODY}", encoding="utf-8")
    return SkillPackage(skill_id="wf", root=root)


def _declaration_package(tmp_path: Path) -> SkillPackage:
    """Minimal package carrying only SKILL.md + workflow.md (no templates)."""
    root = tmp_path / "wf"
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text("---\nname: wf\ndescription: example\n---\n", encoding="utf-8")
    (root / "workflow.md").write_text("workflow", encoding="utf-8")
    return SkillPackage(skill_id="wf", root=root)


def _workflow(*, doctor_checks: list[str] | None = None, role: str = "") -> WorkflowResource:
    fields: dict[str, object] = {}
    if doctor_checks is not None:
        fields["doctor_checks"] = doctor_checks
    return WorkflowResource(
        name="wf",
        instructions="",
        steps=[
            WorkflowStepResource(index=1, name="step-01-plan.md", instructions=""),
            WorkflowStepResource(index=2, name="step-02-build.md", instructions="", role=role),
        ],
        **fields,  # type: ignore[arg-type]
    )


# ---- 加载器：声明 → 模型 -------------------------------------------------------


def test_workflow_declares_the_preflight_and_status_vocabulary(tmp_path: Path) -> None:
    package = _package(tmp_path, "name: wf\ndoctor_checks: package, roles\nstatus_fields: step, next\n")
    workflow = read_workflow(package)
    assert workflow.doctor_checks == ["package", "roles"]
    assert workflow.status_fields == ["step", "next"]


def test_absent_declaration_keeps_the_engine_defaults(tmp_path: Path) -> None:
    """An existing package that declares nothing must load and behave exactly as before."""
    workflow = read_workflow(_package(tmp_path, "name: wf\n"))
    assert workflow.doctor_checks == []
    assert workflow.status_fields == []


def test_unknown_declared_check_fails_at_load_time(tmp_path: Path) -> None:
    """A typo must not silently turn a requested preflight into no preflight."""
    package = _package(tmp_path, "name: wf\ndoctor_checks: package, not-a-check\n")
    with pytest.raises(SkillWorkflowError, match="unknown doctor_checks"):
        read_workflow(package)


def test_unknown_declared_status_field_fails_at_load_time(tmp_path: Path) -> None:
    package = _package(tmp_path, "name: wf\nstatus_fields: step, nope\n")
    with pytest.raises(SkillWorkflowError, match="unknown status_fields"):
        read_workflow(package)


def test_duplicate_declaration_entries_fail_at_load_time(tmp_path: Path) -> None:
    package = _package(tmp_path, "name: wf\nstatus_fields: step, step\n")
    with pytest.raises(SkillWorkflowError, match="duplicate entry in status_fields"):
        read_workflow(package)


def test_the_model_rejects_a_name_outside_the_vocabulary() -> None:
    """The declaration model itself is the second gate (the loader gives the better message)."""
    with pytest.raises(ValidationError):
        WorkflowResource(name="wf", instructions="", steps=[], doctor_checks=["not-a-check"])


# ---- 注册表 ↔ 词汇表 一致性 -----------------------------------------------------


def test_registries_match_the_declared_vocabulary() -> None:
    """Every declarable name must have an implementation, and vice versa."""
    assert sorted(doctor_module._CHECKS) == sorted(DOCTOR_CHECKS)
    assert sorted(status_view_module._FIELDS) == sorted(STATUS_FIELDS)
    assert set(doctor_module.DEFAULT_DOCTOR_CHECKS) <= set(DOCTOR_CHECKS)
    assert set(DEFAULT_STATUS_FIELDS) <= set(STATUS_FIELDS)


# ---- 声明真的驱动行为 -----------------------------------------------------------


def test_only_the_declared_checks_run(tmp_path: Path) -> None:
    workflow = _workflow(doctor_checks=["package"], role="missing-role")
    report = diagnose_workflow(workflow, _declaration_package(tmp_path), lambda _: None)
    assert report.checks == ["package"]
    assert all(finding.code != "role_package_missing" for finding in report.findings), (
        "a check left out of the declaration must not run"
    )


def test_undeclared_workflow_reports_the_default_checks(tmp_path: Path) -> None:
    report = diagnose_workflow(_workflow(role="missing-role"), _declaration_package(tmp_path), lambda _: None)
    assert report.checks == list(doctor_module.DEFAULT_DOCTOR_CHECKS)
    assert any(finding.code == "role_package_missing" for finding in report.findings)


def test_only_the_declared_status_fields_are_rendered() -> None:
    state = WorkflowRunnerState(active_step=1, status=WorkflowStatus.BLOCKED, reason="gate failed", completed_steps=[1])
    workflow = _workflow()
    default_lines = project_status_view(state, workflow).render()
    assert "[goal] reason: gate failed" in default_lines
    assert any(line.startswith("[goal] next:") for line in default_lines)

    declared = project_status_view(state, workflow, fields=["reason"]).render()
    assert declared == [
        "[goal] declarative progress: 1/2 status=blocked step=1",
        "[goal] reason: gate failed",
    ]
