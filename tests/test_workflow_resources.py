"""Tests for declarative workflow and ordered step resources."""

from pathlib import Path

import pytest

from heagent.memory.skill_packages import SkillPackage, SkillWorkflowError


def _package(root: Path, workflow: str = "steps: [step-01-first.md, step-02-second.md]\n") -> SkillPackage:
    root.mkdir(exist_ok=True)
    (root / "workflow.md").write_text(f"---\nname: demo\n{workflow}---\n\n# Demo\n", encoding="utf-8")
    (root / "step-01-first.md").write_text(
        "---\ninput: brief\noutput: plan\nnext: step-02-second.md\n"
        "checkpoint: user\nvalidation: has plan\n---\n\nFirst",
        encoding="utf-8",
    )
    (root / "step-02-second.md").write_text(
        "---\ninput: plan\noutput: code\nnext: null\n---\n\nSecond", encoding="utf-8"
    )
    return SkillPackage(skill_id="demo", root=root)


def test_loads_workflow_and_ordered_step_contract(tmp_path: Path) -> None:
    workflow = _package(tmp_path).read_workflow()
    assert workflow.name == "demo"
    assert [step.index for step in workflow.steps] == [1, 2]
    assert workflow.steps[0].input == "brief"
    assert workflow.steps[0].output == "plan"
    assert workflow.steps[0].next == "step-02-second.md"
    assert workflow.steps[0].checkpoint == "user"
    assert workflow.steps[0].validation_rules == "has plan"
    assert workflow.steps[1].next is None


def test_discovers_steps_when_workflow_list_is_omitted(tmp_path: Path) -> None:
    workflow = _package(tmp_path, workflow="").read_workflow()
    assert [step.name for step in workflow.steps] == ["step-01-first.md", "step-02-second.md"]


def test_loads_inline_step_contracts_without_external_step_files(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "workflow.md").write_text(
        "---\nname: inline\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\n# Inline workflow\n\n"
        "## Step 01: clarify\noutput: scope\ncheckpoint: true\n\nClarify the request.\n\n"
        "## Step 02: implement\ninput: scope\noutput: change\n"
        "validation: focused tests pass\n\nImplement the change.\n",
        encoding="utf-8",
    )

    workflow = SkillPackage(skill_id="inline", root=tmp_path).read_workflow()

    assert workflow.entrypoint == "goal"
    assert workflow.on_create == "persist_goal_identity"
    assert workflow.step_executor == "subagent"
    assert [step.name for step in workflow.steps] == ["step-01-clarify.md", "step-02-implement.md"]
    assert workflow.steps[0].output == "scope"
    assert workflow.steps[0].checkpoint == "true"
    assert workflow.steps[1].input == "scope"


@pytest.mark.parametrize(
    ("workflow", "message"),
    [
        ("steps: [step-01-first.md, step-01-first.md]\n", "duplicate"),
        ("steps: [step-02-second.md]\n", "contiguous"),
        ("steps: [../outside.md]\n", "within package"),
        ("steps: [step-01-first.md, step-02-missing.md]\n", "missing"),
    ],
)
def test_invalid_step_references_fail_explicitly(tmp_path: Path, workflow: str, message: str) -> None:
    package = _package(tmp_path, workflow=workflow)
    with pytest.raises(SkillWorkflowError, match=message):
        package.read_workflow()


def test_next_reference_must_name_declared_step(tmp_path: Path) -> None:
    package = _package(tmp_path)
    (tmp_path / "step-01-first.md").write_text("---\nnext: missing.md\n---\nFirst", encoding="utf-8")
    with pytest.raises(SkillWorkflowError, match="next step reference"):
        package.read_workflow()
