"""Tests for declarative workflow and ordered step resources."""

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from heagent.engine.workflow_resource import StepApproval
from heagent.goal.workflow_loader import SkillWorkflowError, read_workflow, workflow_revision
from heagent.skills.skill_packages import SkillPackage


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


def test_informs_when_max_parallel_stories_exceeds_one(tmp_path: Path, caplog) -> None:
    """max_parallel_stories>1 = 声明门控并行可用（Epic 52）：发条件说明 INFO，不再 WARNING。"""
    package = _package(tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\n")
    (tmp_path / "step-01-first.md").write_text("---\nmax_parallel_stories: 3\n---\nFirst", encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="heagent.goal.workflow_loader"):
        workflow = read_workflow(package)
    assert workflow.steps[0].max_parallel_stories == 3
    assert "max_parallel_stories" in caplog.text
    assert "write_set" in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


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


def test_loads_evidence_clauses_from_step_validation(tmp_path: Path) -> None:
    """`validation:` 里的证据子句（与 section: 同串同分隔符）解析进步骤模型（51-3）。"""
    package = _package(tmp_path)
    (tmp_path / "step-01-first.md").write_text(
        "---\nvalidation: section: 测试证据; command: pytest -q, artifact: reports/verify.md; "
        "git: src/x.py, gate: tests-pass\n---\nFirst",
        encoding="utf-8",
    )

    step = read_workflow(package).steps[0]

    assert step.validation_clauses.sections == ["测试证据"]
    assert step.validation_clauses.commands == ["pytest -q"]
    assert step.validation_clauses.artifacts == ["reports/verify.md"]
    assert step.validation_clauses.git_paths == ["src/x.py"]
    assert step.validation_clauses.gates == ["tests-pass"]
    assert step.validation_clauses.declared is True


def test_loads_evidence_clauses_from_inline_step_metadata(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "workflow.md").write_text(
        "---\nname: inline\n---\n\n# Inline\n\n"
        "## Step 01: implement\n"
        "validation: command: pytest tests/ -q; gate: tests-pass\n\n"
        "Implement.\n",
        encoding="utf-8",
    )

    workflow = read_workflow(SkillPackage(skill_id="inline", root=tmp_path))

    clauses = workflow.steps[0].validation_clauses
    assert clauses.commands == ["pytest tests/ -q"]
    assert clauses.gates == ["tests-pass"]


def test_unknown_inline_evidence_clause_fails_the_load(tmp_path: Path) -> None:
    """未知子句 fail-loud（内嵌步骤与外置步骤文件同一规则），不做静默忽略。"""
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "workflow.md").write_text(
        "---\nname: inline\n---\n\n# Inline\n\n"
        "## Step 01: implement\n"
        "validation: section: A; comands: pytest -q\n\n"
        "Implement.\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillWorkflowError, match="unknown validation clause 'comands:'"):
        read_workflow(SkillPackage(skill_id="inline", root=tmp_path))


# ---- ``approval:`` 声明词汇（Story 51-5）---------------------------------------


def test_loads_approval_required_with_note(tmp_path: Path) -> None:
    """``approval: required``（可带一句说明）解析进步骤模型；说明原文保留。"""
    package = _package(tmp_path)
    (tmp_path / "step-01-first.md").write_text(
        "---\napproval: required 架构冻结前需人工确认\n---\nFirst", encoding="utf-8"
    )

    approval = read_workflow(package).steps[0].approval

    assert approval.required is True
    assert approval.note == "架构冻结前需人工确认"


def test_loads_bare_approval_required_without_note(tmp_path: Path) -> None:
    package = _package(tmp_path)
    (tmp_path / "step-01-first.md").write_text("---\napproval: required\n---\nFirst", encoding="utf-8")

    approval = read_workflow(package).steps[0].approval

    assert approval.required is True
    assert approval.note == ""


def test_undeclared_approval_keeps_the_step_unchanged(tmp_path: Path) -> None:
    """未声明 = 不需要人工确认（老包零行为变化的声明面）。"""
    assert read_workflow(_package(tmp_path)).steps[0].approval == StepApproval()
    assert read_workflow(_package(tmp_path)).steps[0].approval.required is False


def test_loads_approval_from_inline_step_metadata(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "workflow.md").write_text(
        "---\nname: inline\n---\n\n# Inline\n\n## Step 01: freeze\napproval: required\n\nFreeze the architecture.\n",
        encoding="utf-8",
    )

    workflow = read_workflow(SkillPackage(skill_id="inline", root=tmp_path))

    assert workflow.steps[0].approval.required is True


@pytest.mark.parametrize("value", ["maybe", "optional 请确认", "true", "false", "yes", "required!!"])
def test_invalid_approval_value_fails_the_load(tmp_path: Path, value: str) -> None:
    """非法取值加载期 fail-loud：「声明了审批」被吞成「不需要审批」会跨过人工 Gate。"""
    package = _package(tmp_path)
    (tmp_path / "step-01-first.md").write_text(f"---\napproval: {value}\n---\nFirst", encoding="utf-8")

    with pytest.raises(SkillWorkflowError, match="invalid approval declaration"):
        read_workflow(package)


@pytest.mark.parametrize("value", ["", "   ", "none", "null"])
def test_blank_approval_declaration_fails_the_load(tmp_path: Path, value: str) -> None:
    """声明了 approval 却空白 / none / null：静默吞成「无门」是人工 Gate 缺口（审查 #4）。"""
    package = _package(tmp_path)
    (tmp_path / "step-01-first.md").write_text(f"---\napproval: {value}\n---\nFirst", encoding="utf-8")

    with pytest.raises(SkillWorkflowError, match="present but blank"):
        read_workflow(package)


def test_approval_model_rejects_a_note_without_required() -> None:
    """模型自身是第二道门（loader 给更好的报错）：说明必须依附 required。"""
    with pytest.raises(ValidationError):
        StepApproval(note="说明")


# ---- ``revision:`` 声明词汇（Story 51-6）---------------------------------------


def test_loads_declared_revision_verbatim(tmp_path: Path) -> None:
    """frontmatter 的 ``revision:`` 原样进入模型（声明 revision 的演示路径）。"""
    package = _package(tmp_path, workflow='steps: [step-01-first.md, step-02-second.md]\nrevision: "1"\n')

    workflow = read_workflow(package)

    assert workflow.revision == "1"
    # 声明路径：派生值 = 声明值原样返回。
    assert workflow_revision(package, workflow) == "1"


def test_undeclared_revision_defaults_to_empty(tmp_path: Path) -> None:
    """缺省不报错、落空串（老包零行为变化），派生走内容摘要路径。"""
    package = _package(tmp_path)

    workflow = read_workflow(package)

    assert workflow.revision == ""
    derived = workflow_revision(package, workflow)
    assert len(derived) == 16
    int(derived, 16)  # 十六进制摘要
    # 确定性：同一份包内容派生同一指纹。
    assert workflow_revision(package, workflow) == derived


def test_derived_revision_moves_with_workflow_body(tmp_path: Path) -> None:
    """派生路径覆盖 workflow.md 正文：正文漂移 → 指纹变化。"""
    package = _package(tmp_path)
    before = workflow_revision(package, read_workflow(package))
    (tmp_path / "workflow.md").write_text(
        (tmp_path / "workflow.md").read_text(encoding="utf-8") + "\nDrifted.\n", encoding="utf-8"
    )

    assert workflow_revision(package, read_workflow(package)) != before


def test_derived_revision_covers_required_resources(tmp_path: Path) -> None:
    """派生路径覆盖 required_resources 声明的模板：模板漂移 → 指纹变化。"""
    package = _package(
        tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\nrequired_resources: prompt-template.md\n"
    )
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "prompt-template.md").write_text("PLAN {goal}\n", encoding="utf-8")
    before = workflow_revision(package, read_workflow(package))
    (templates / "prompt-template.md").write_text("CHANGED {goal}\n", encoding="utf-8")

    assert workflow_revision(package, read_workflow(package)) != before


def test_derived_revision_covers_frontmatter_fields(tmp_path: Path) -> None:
    """指纹哈希 ``workflow.md`` 全文（含 frontmatter）：仅改声明字段 → 指纹必变（51-6 审查 M2）。

    变异判据：改 ``checkpoint_mode`` / ``name`` 这样的纯 frontmatter 字段若不触发漂移，
    冻结绑定的「包漂移 fail-loud」就会漏掉策略声明被篡改的形态。
    """
    package = _package(tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\ncheckpoint_mode: auto\n")
    before = workflow_revision(package, read_workflow(package))

    (tmp_path / "workflow.md").write_text(
        "---\nname: demo\nsteps: [step-01-first.md, step-02-second.md]\ncheckpoint_mode: prompt\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    after_checkpoint_mode = workflow_revision(package, read_workflow(package))
    assert after_checkpoint_mode != before

    (tmp_path / "workflow.md").write_text(
        "---\nname: renamed\nsteps: [step-01-first.md, step-02-second.md]\ncheckpoint_mode: prompt\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    assert workflow_revision(package, read_workflow(package)) not in {before, after_checkpoint_mode}


def test_template_digest_order_is_sorted_not_declaration_order(tmp_path: Path) -> None:
    """``required_resources`` 的模板按**排序后**顺序入哈希，与声明顺序解耦（51-6 审查 M2）。

    「同内容仅声明顺序不同 → 同指纹」在指纹层面不可观察（workflow.md 全文入哈希，声明
    顺序变化必然改变文本），故按同一配方手工复算指纹钉住 sorted() 语义：实现若改成按
    声明顺序哈希模板，本测试即红。声明顺序在这里刻意取逆字母序。用**内联步骤**的包，
    使配方里没有外挂步骤文件条目（M1 扩展不掺入）。
    """
    import hashlib

    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "workflow.md").write_text(
        "---\nname: inline\n"
        "required_resources: prompt-template.md, gate-template.md\n"  # 故意逆字母序声明
        "---\n\n# Inline\n\n## Step 01: only\ninput: x\noutput: y\n\nDo it.\n",
        encoding="utf-8",
    )
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "prompt-template.md").write_text("P", encoding="utf-8")
    (templates / "gate-template.md").write_text("G", encoding="utf-8")
    package = SkillPackage(skill_id="inline", root=tmp_path)

    hasher = hashlib.sha256()
    hasher.update((tmp_path / "workflow.md").read_text(encoding="utf-8").encode("utf-8"))
    for name in ("gate-template.md", "prompt-template.md"):  # sorted 顺序，非声明顺序
        hasher.update(b"\x00")
        hasher.update((templates / name).read_text(encoding="utf-8").encode("utf-8"))

    assert workflow_revision(package, read_workflow(package)) == hasher.hexdigest()[:16]


def test_derived_revision_covers_declared_step_files(tmp_path: Path) -> None:
    """派生路径覆盖 ``steps:`` 声明的外挂步骤文件：步骤正文漂移 → 指纹变化（51-6 审查 M1）。"""
    package = _package(tmp_path)
    before = workflow_revision(package, read_workflow(package))
    (tmp_path / "step-01-first.md").write_text(
        "---\ninput: brief\noutput: plan\nnext: step-02-second.md\ncheckpoint: user\nvalidation: has plan\n"
        "---\n\nFirst drifted",
        encoding="utf-8",
    )

    assert workflow_revision(package, read_workflow(package)) != before


def test_derived_revision_covers_discovered_step_files(tmp_path: Path) -> None:
    """自动发现形态（无 ``steps:`` 声明）同样覆盖：改步骤文件 → 指纹变化（51-6 审查 M1）。"""
    package = _package(tmp_path, workflow="")
    before = workflow_revision(package, read_workflow(package))
    (tmp_path / "step-02-second.md").write_text(
        "---\ninput: plan\noutput: code\n---\n\nSecond drifted", encoding="utf-8"
    )

    assert workflow_revision(package, read_workflow(package)) != before


def test_inline_step_packages_keep_their_fingerprint_scope(tmp_path: Path) -> None:
    """全内联步骤的包不追加步骤条目：根目录多出的散落 step 文件不改变指纹（冻结值语义兼容）。"""
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "workflow.md").write_text(
        "---\nname: inline\n---\n\n# Inline\n\n## Step 01: only\ninput: x\noutput: y\n\nDo it.\n",
        encoding="utf-8",
    )
    package = SkillPackage(skill_id="inline", root=tmp_path)
    before = workflow_revision(package, read_workflow(package))
    (tmp_path / "step-09-stray.md").write_text("---\ninput: x\noutput: y\n---\n\nStray", encoding="utf-8")

    assert workflow_revision(package, read_workflow(package)) == before


def test_derived_revision_detects_a_pinned_resource_drift(tmp_path: Path) -> None:
    """模板经 manifest 钉住后内容漂移：``workflow_revision`` 的摘要通道读取即显性失败，不产指纹。"""
    import hashlib
    import json

    package = _package(
        tmp_path, workflow="steps: [step-01-first.md, step-02-second.md]\nrequired_resources: prompt-template.md\n"
    )
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "prompt-template.md").write_text("PLAN {goal}\n", encoding="utf-8")
    digest = hashlib.sha256((templates / "prompt-template.md").read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(
        json.dumps({"outputs": {"templates/prompt-template.md": digest}}), encoding="utf-8"
    )
    workflow = read_workflow(package)  # 装载时模板与 manifest 一致
    (templates / "prompt-template.md").write_text("TAMPERED {goal}\n", encoding="utf-8")

    # loader 的必需性检查把摘要漂移报成「missing or blank」；直接走派生通道拿到原始摘要错。
    with pytest.raises(Exception, match="content hash differs"):
        workflow_revision(package, workflow)
