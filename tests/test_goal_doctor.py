"""Goal preflight must surface missing role dependencies."""

from pathlib import Path

from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.goal.doctor import diagnose_workflow
from heagent.memory.skill_packages import SkillPackage


def test_doctor_reports_missing_role_without_executing_workflow(tmp_path: Path) -> None:
    package_root = tmp_path / "workflow"
    package_root.mkdir()
    (package_root / "SKILL.md").write_text("---\nname: workflow\ndescription: example\n---\n", encoding="utf-8")
    (package_root / "workflow.md").write_text("workflow", encoding="utf-8")
    workflow = WorkflowResource(
        name="example",
        instructions="",
        steps=[WorkflowStepResource(index=0, name="build", instructions="", role="missing-role")],
    )
    problems = diagnose_workflow(workflow, SkillPackage(skill_id="workflow", root=package_root), lambda _: None)
    assert problems == ["role package missing: missing-role"]
