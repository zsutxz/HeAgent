"""Goal preflight must surface missing dependencies as structured findings."""

from pathlib import Path

import pytest

from heagent.cli import goal as goal_cli
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.goal.application import checkpoint_store
from heagent.goal.doctor import DoctorSeverity, GoalDoctorReport, diagnose_workflow
from heagent.skills.skill_packages import SkillPackage


def _package(root: Path) -> SkillPackage:
    """Create a minimal, intact skill package under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text("---\nname: workflow\ndescription: example\n---\n", encoding="utf-8")
    (root / "workflow.md").write_text("workflow", encoding="utf-8")
    return SkillPackage(skill_id="workflow", root=root)


def _workflow(*, role: str = "", templates: bool = False, required: list[str] | None = None) -> WorkflowResource:
    return WorkflowResource(
        name="example",
        instructions="",
        steps=[WorkflowStepResource(index=0, name="build", instructions="", role=role)],
        prompt_template="prompt" if templates else "",
        gate_template="gate" if templates else "",
        frontmatter={} if required is None else {"required_resources": required},
    )


def _failures(report: GoalDoctorReport) -> list[str]:
    return [finding.code for finding in report.problems if finding.severity is DoctorSeverity.FAIL]


def _finding(report: GoalDoctorReport, code: str) -> str:
    """Rendered line of one finding; ``problems`` also carries warnings, so locate by code."""
    matches = [finding for finding in report.problems if finding.code == code]
    assert len(matches) == 1, f"expected exactly one {code!r} finding, got {len(matches)}"
    return matches[0].render()


def test_doctor_reports_missing_role_without_executing_workflow(tmp_path: Path) -> None:
    report = diagnose_workflow(_workflow(role="missing-role"), _package(tmp_path / "workflow"), lambda _: None)
    assert _failures(report) == ["role_package_missing"]
    assert report.ok is False
    assert _finding(report, "role_package_missing") == "role package missing: missing-role"


def test_doctor_passes_a_complete_workflow(tmp_path: Path) -> None:
    role = _package(tmp_path / "roles" / "dev")
    report = diagnose_workflow(_workflow(role="dev", templates=True), _package(tmp_path / "workflow"), lambda _: role)
    assert report.ok is True
    assert report.problems == []
    assert report.render() == "workflow packages OK"
    assert {finding.code for finding in report.findings} == {"workflow_package_ok", "role_package_ok"}


def test_doctor_fails_when_a_role_package_is_unreadable(tmp_path: Path) -> None:
    broken = _package(tmp_path / "roles" / "dev")
    (tmp_path / "roles" / "dev" / "SKILL.md").write_bytes(b"\xff\xfe\x00broken")
    report = diagnose_workflow(_workflow(role="dev"), _package(tmp_path / "workflow"), lambda _: broken)
    assert _failures(report) == ["role_package_unreadable"]
    assert _finding(report, "role_package_unreadable").startswith("role package dev:")


def test_doctor_warns_when_optional_templates_are_absent_without_blocking(tmp_path: Path) -> None:
    report = diagnose_workflow(_workflow(), _package(tmp_path / "workflow"), lambda _: None)
    assert report.ok is True
    assert {finding.code for finding in report.problems} == {"optional_template_missing"}
    assert all(finding.severity is DoctorSeverity.WARN for finding in report.problems)
    # A warning is reported, never rendered as the success line.
    assert "workflow packages OK" not in report.render()


def test_doctor_fails_on_a_required_resource_the_package_lacks(tmp_path: Path) -> None:
    report = diagnose_workflow(
        _workflow(required=["templates/prompt-template.md"]),
        _package(tmp_path / "workflow"),
        lambda _: None,
    )
    assert _failures(report) == ["required_resource_unreadable"]
    assert report.problems[0].subject == "required resource prompt-template.md"
    # Declaring it required must not also be reported once more as an optional warning.
    assert not any(
        finding.code == "optional_template_missing" and "prompt" in finding.subject for finding in report.problems
    )


def test_doctor_fails_when_the_checkpoint_path_is_not_a_directory(tmp_path: Path) -> None:
    blocker = tmp_path / "checkpoint-workspace.txt"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    report = diagnose_workflow(_workflow(), _package(tmp_path / "workflow"), lambda _: None, checkpoint_dir=blocker)
    assert _failures(report) == ["checkpoint_dir_not_a_directory"]
    assert report.ok is False


def test_doctor_probes_a_missing_checkpoint_directory_without_creating_it(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "checkpoints"
    report = diagnose_workflow(_workflow(), _package(tmp_path / "workflow"), lambda _: None, checkpoint_dir=target)
    assert report.ok is True
    assert any(finding.code == "checkpoint_dir_writable" for finding in report.findings)
    assert not target.exists(), "a read-only preflight must not create the checkpoint directory"


async def test_cli_doctor_probes_the_directory_the_store_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A preflight that probes a different directory than the writer uses is worse than none.

    Story 51-6 起 doctor 预检的是**活动 goal 冻结绑定**的包（AD-8）：绑定解析缝在此替换，
    预检目标路径必须仍与真实写者同源（``checkpoint_store`` 唯一解析点）。
    """
    goal_dir = tmp_path / "demo"
    goal_dir.mkdir()
    (goal_dir / "brief.md").write_text(goal_cli.goal_document("demo goal", "demo"), encoding="utf-8")
    seen: list[Path | None] = []

    def _spy(workflow: WorkflowResource, package: SkillPackage, resolve_role: object, *, checkpoint_dir=None):
        seen.append(checkpoint_dir)
        return GoalDoctorReport(workflow=workflow.name)

    monkeypatch.setattr(goal_cli, "_goal_declarative_active_dir", lambda: goal_dir)
    monkeypatch.setattr(goal_cli, "resolve_bound_workflow", lambda _goal_dir, _default: _workflow())
    monkeypatch.setattr(goal_cli, "_resolve_skill_package", lambda _skill_id: _package(tmp_path / "workflow"))
    monkeypatch.setattr(goal_cli, "diagnose_workflow", _spy)
    monkeypatch.setattr(goal_cli, "_echo", lambda message, *, err=True: None)

    await goal_cli._goal_declarative_doctor()

    assert seen == [checkpoint_store(goal_dir).base_dir]


async def test_cli_doctor_with_an_active_goal_says_the_workflow_option_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """有活动 goal 时 ``--workflow`` 被忽略但必须显性提示（51-6 审查 L2），不静默失效。

    预检对象仍是活动 goal 冻结绑定的包（AD-8）；提示风格对齐既有 ``[goal] doctor:`` 行。
    """
    goal_dir = tmp_path / "demo"
    goal_dir.mkdir()
    (goal_dir / "brief.md").write_text(goal_cli.goal_document("demo goal", "demo"), encoding="utf-8")

    def _spy(workflow: WorkflowResource, package: SkillPackage, resolve_role: object, *, checkpoint_dir=None):
        return GoalDoctorReport(workflow=workflow.name)

    monkeypatch.setattr(goal_cli, "_goal_declarative_active_dir", lambda: goal_dir)
    monkeypatch.setattr(goal_cli, "resolve_bound_workflow", lambda _goal_dir, _default: _workflow())
    monkeypatch.setattr(goal_cli, "_resolve_skill_package", lambda _skill_id: _package(tmp_path / "workflow"))
    monkeypatch.setattr(goal_cli, "diagnose_workflow", _spy)

    await goal_cli._goal_declarative_doctor("--workflow he-elsewhere")

    err = capsys.readouterr().err
    assert "--workflow is ignored" in err
    assert "[goal] doctor:" in err


def test_declared_required_tolerance_divergence_is_intentional(tmp_path: Path) -> None:
    """A30②：解析核单源后两处宽容度分叉是有意的——doctor 对类型不符的 ``required_resources``
    fail-soft（空表、诊断照常跑完），loader 对同类输入 fail-closed（抛 ``SkillWorkflowError``）。"""
    from heagent.goal.doctor import _declared_required
    from heagent.goal.workflow_loader import SkillWorkflowError, _resource_list

    assert _declared_required(_workflow(required=42)) == []  # type: ignore[arg-type]

    package = _package(tmp_path / "workflow")
    with pytest.raises(SkillWorkflowError, match="must be a list"):
        _resource_list(package, 42, "workflow.md", "required_resources")


def test_declared_required_parses_str_and_list_forms_identically() -> None:
    """A30②：解析核单源——字符串与数组两种声明形态给出同一批名字（templates/ 前缀同规剥离）。"""
    from heagent.goal.doctor import _declared_required

    as_str = _declared_required(_workflow(required="templates/a.md, templates/b.md"))
    as_list = _declared_required(_workflow(required=["templates/a.md", "templates/b.md"]))
    assert as_str == as_list == ["a.md", "b.md"]
