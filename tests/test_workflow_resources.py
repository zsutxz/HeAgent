"""Tests for declarative workflow and ordered step resources."""

from pathlib import Path

import pytest

from heagent.goal.workflow_loader import SkillWorkflowError, read_workflow
from heagent.memory.skill_packages import SkillPackage


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
    workflow = read_workflow(_package(tmp_path))
    assert workflow.name == "demo"
    assert [step.index for step in workflow.steps] == [1, 2]
    assert workflow.steps[0].input == "brief"
    assert workflow.steps[0].output == "plan"
    assert workflow.steps[0].next == "step-02-second.md"
    assert workflow.steps[0].checkpoint == "user"
    assert workflow.steps[0].validation_rules == "has plan"
    assert workflow.steps[1].next is None


def test_discovers_steps_when_workflow_list_is_omitted(tmp_path: Path) -> None:
    workflow = read_workflow(_package(tmp_path, workflow=""))
    assert [step.name for step in workflow.steps] == ["step-01-first.md", "step-02-second.md"]


def test_loads_inline_step_contracts_without_external_step_files(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "workflow.md").write_text(
        "---\nname: inline\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\n# Inline workflow\n\n"
        "## Step 01: clarify\noutput: scope\ncheckpoint: true\n\nClarify the request.\n\n"
        "## Step 02: implement\ninput: scope\noutput: change\n"
        "validation: focused tests pass\nmax_parallel_stories: 4\n\nImplement the change.\n",
        encoding="utf-8",
    )

    workflow = read_workflow(SkillPackage(skill_id="inline", root=tmp_path))

    assert workflow.entrypoint == "goal"
    assert workflow.on_create == "persist_goal_identity"
    assert workflow.step_executor == "subagent"
    assert [step.name for step in workflow.steps] == ["step-01-clarify.md", "step-02-implement.md"]
    assert workflow.steps[0].output == "scope"
    assert workflow.steps[0].checkpoint == "true"
    assert workflow.steps[1].input == "scope"
    assert workflow.steps[1].max_parallel_stories == 4


def test_loads_max_parallel_stories_with_default_and_bound(tmp_path: Path) -> None:
    package = _package(tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\n")
    (tmp_path / "step-01-first.md").write_text("---\nmax_parallel_stories: 3\n---\nFirst", encoding="utf-8")
    workflow = read_workflow(package)
    assert workflow.steps[0].max_parallel_stories == 3
    assert workflow.steps[1].max_parallel_stories == 1


def test_reads_step_iteration_budget_with_default_and_bound(tmp_path: Path) -> None:
    """`max_iterations:` overrides the global budget; absent = inherit (0)."""
    package = _package(tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\n")
    (tmp_path / "step-01-first.md").write_text("---\nmax_iterations: 40\n---\nFirst", encoding="utf-8")
    workflow = read_workflow(package)
    assert workflow.steps[0].max_iterations == 40
    assert workflow.steps[1].max_iterations == 0


@pytest.mark.parametrize("value", ["0", "1001", "1.5", "true", "null", ""])
def test_rejects_invalid_step_iteration_budget(tmp_path: Path, value: str) -> None:
    package = _package(tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\n")
    (tmp_path / "step-01-first.md").write_text(f"---\nmax_iterations: {value}\n---\nFirst", encoding="utf-8")
    with pytest.raises(SkillWorkflowError, match="max_iterations"):
        read_workflow(package)


@pytest.mark.parametrize("value", ["0", "6", "1.5", "true", "null", ""])
def test_rejects_invalid_max_parallel_stories(tmp_path: Path, value: str) -> None:
    package = _package(tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\n")
    (tmp_path / "step-01-first.md").write_text(f"---\nmax_parallel_stories: {value}\n---\nFirst", encoding="utf-8")
    with pytest.raises(SkillWorkflowError, match="max_parallel_stories"):
        read_workflow(package)


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
        read_workflow(package)


def test_next_reference_must_name_declared_step(tmp_path: Path) -> None:
    package = _package(tmp_path)
    (tmp_path / "step-01-first.md").write_text("---\nnext: missing.md\n---\nFirst", encoding="utf-8")
    with pytest.raises(SkillWorkflowError, match="next step reference"):
        read_workflow(package)


def test_templates_stay_optional_without_required_resources_declaration(tmp_path: Path) -> None:
    """No ``required_resources`` line, no enforcement: a minimal package keeps loading."""
    workflow = read_workflow(_package(tmp_path))
    assert workflow.prompt_template == ""
    assert workflow.gate_template == ""


def test_declared_required_templates_load_when_present(tmp_path: Path) -> None:
    package = _package(
        tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\nrequired_resources: prompt-template.md\n"
    )
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "prompt-template.md").write_text("PLAN {goal} :: {step}\n", encoding="utf-8")

    workflow = read_workflow(package)

    assert workflow.prompt_template == "PLAN {goal} :: {step}"
    assert workflow.gate_template == ""


@pytest.mark.parametrize("template_body", ["", "   \n"])
def test_declared_required_templates_fail_when_missing_or_blank(tmp_path: Path, template_body: str) -> None:
    package = _package(
        tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\nrequired_resources: prompt-template.md\n"
    )
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "prompt-template.md").write_text(template_body, encoding="utf-8")

    with pytest.raises(SkillWorkflowError, match="required_resources"):
        read_workflow(package)
