from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from heagent.goal.workflow_loader import SkillWorkflowError, read_workflow
from heagent.skills.skill_packages import SkillPackage


def _package(tmp_path: Path, step_metadata: str, *, script: str | None = "script.py") -> SkillPackage:
    root = tmp_path / "he-flow"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: he-flow\n---\n", encoding="utf-8")
    (root / "meta.yaml").write_text("canonical_id: he-flow\n", encoding="utf-8")
    (root / "templates").mkdir()
    (root / "templates" / "prompt-template.md").write_text("prompt", encoding="utf-8")
    (root / "templates" / "gate-template.md").write_text("gate", encoding="utf-8")
    if script is not None:
        (root / "scripts").mkdir()
        (root / "scripts" / script).write_text("async def build_workflow(goal):\n    return 'ok'\n", encoding="utf-8")
    (root / "workflow.md").write_text(
        "---\nname: flow\nentrypoint: goal\non_create: persist_goal_identity\n"
        "required_resources: prompt-template.md, gate-template.md\n---\n\n"
        "## Step 01: one\n" + step_metadata + "\n\nRun it.\n",
        encoding="utf-8",
    )
    return SkillPackage(skill_id="he-flow", root=root)


def test_script_step_loads_package_resource(tmp_path: Path) -> None:
    workflow = read_workflow(_package(tmp_path, "executor_mode: script\nscript_resource: script.py"))
    assert workflow.steps[0].executor_mode == "script"
    assert workflow.steps[0].script_resource == "script.py"


def test_script_step_requires_resource(tmp_path: Path) -> None:
    with pytest.raises(SkillWorkflowError, match="requires script_resource"):
        read_workflow(_package(tmp_path, "executor_mode: script", script=None))


def test_script_resource_must_be_a_single_package_local_name(tmp_path: Path) -> None:
    with pytest.raises(SkillWorkflowError, match="package-local"):
        read_workflow(_package(tmp_path, "executor_mode: script\nscript_resource: ../secret.py"))


def test_default_executor_remains_subagent(tmp_path: Path) -> None:
    workflow = read_workflow(_package(tmp_path, "output: result"))
    assert workflow.steps[0].executor_mode == "subagent"
    assert workflow.steps[0].script_resource == ""


def test_script_hash_drift_is_rejected_by_package_integrity(tmp_path: Path) -> None:
    package = _package(tmp_path, "executor_mode: script\nscript_resource: script.py")
    script_path = package.root / "scripts" / "script.py"
    digest = hashlib.sha256(script_path.read_bytes()).hexdigest()
    (package.root / "manifest.json").write_text(
        json.dumps({"outputs": {"scripts/script.py": digest}}), encoding="utf-8"
    )
    script_path.write_text("async def main(api):\n    return 'changed'\n", encoding="utf-8")
    with pytest.raises(SkillWorkflowError, match="content hash differs"):
        read_workflow(package)
