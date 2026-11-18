"""workflow 声明面：包加载/校验、绑定冻结、门禁与 open-question 策略、prompt 装配。

与 :mod:`heagent.goal.application` 的分界：本模块只做**声明面读取与渲染**
（不触碰 Runner 状态、不落盘进度），供 application 的 use-case 与 cli/goal 共用。
无 click / 入口层依赖（架构契约测试钉死）。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from heagent.engine import (
    WorkflowCheckpointError,
    WorkflowResource,
    required_sections,
)
from heagent.goal.document import goal_document_path
from heagent.goal.workflow_loader import SkillWorkflowError, parse_story_list, read_workflow, workflow_revision
from heagent.pub.frontmatter import parse_strict_pairs, split_frontmatter
from heagent.skills.skill_packages import (
    SkillCatalog,
    SkillCatalogError,
    SkillPackage,
    SkillResolver,
)
from heagent.skills.skill_store import default_skill_roots
from heagent.tools.path_safety import resolve_under_root

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

# /goal 的技能库根：工作流包与每个步骤的角色包都从这里按 id 解析（单一来源）。
GOAL_SKILLS_ROOT = Path(".heagent/skills")
# 以下两段文案是**兜底**：workflow 包 frontmatter 声明了对应内容时以包为准（工作流逻辑尽量不进代码）。
# 提示词与门禁模板**不在代码里**：由 workflow 包的 templates/ 携带；必需性由包 frontmatter 的
# ``required_resources`` 声明，缺失在包加载（read_workflow）时显性报错。
_DEFAULT_OPEN_QUESTION_DEFAULT = (
    "When a competing interpretation requires a stakeholder choice, proceed with the recommended "
    "default and record the assumption explicitly; do not stop with waiting_user."
)
_DEFAULT_OPEN_QUESTION_BLOCK = "Stop with waiting_user when competing interpretations require stakeholder choice."

# 模板占位符单遍渲染：值里再出现 ``{xxx}`` 字样也不会被二次替换（链式 str.replace 会）。
_TEMPLATE_FIELD_RE = re.compile(r"\{(\w+)\}")


def render_template(template: str, fields: Mapping[str, str]) -> str:
    """Render ``{name}`` placeholders in one pass; unknown placeholders stay verbatim."""
    return _TEMPLATE_FIELD_RE.sub(lambda match: fields.get(match.group(1), match.group(0)), template)


def load_validated_workflow(package: SkillPackage) -> WorkflowResource:
    """读取 skill 包的 ``workflow.md`` 并做 goal 能力校验（读+校验的单一口径）。"""
    workflow = read_workflow(package, "workflow.md")
    validate_goal_workflow(workflow)
    return workflow


def validate_goal_workflow(workflow: WorkflowResource) -> None:
    """Restrict workflow declarations to deterministic CLI capabilities."""
    if workflow.entrypoint not in {"", "goal"}:
        raise ValueError(f"unsupported goal workflow entrypoint: {workflow.entrypoint}")
    if workflow.on_create != "persist_goal_identity":
        raise ValueError(f"unsupported goal workflow on_create hook: {workflow.on_create}")
    if workflow.step_executor not in {"subagent", "script"}:
        raise ValueError(f"unsupported goal workflow step executor: {workflow.step_executor}")
    if workflow.step_executor == "script":
        raise ValueError("workflow-level script execution is not supported; declare executor_mode on a step")
    for step in workflow.steps:
        if step.executor_mode == "script" and not step.script_resource:
            raise ValueError(f"script step {step.name} has no script resource")


def checkpoint_mode(workflow: WorkflowResource, fallback: str) -> str:
    """Resolve checkpoint policy: workflow declaration, then the injected settings value."""
    declared = workflow.checkpoint_mode.strip().casefold()
    if declared:
        return declared
    return fallback


def open_question_mode(workflow: WorkflowResource, fallback: str) -> str:
    """Resolve open-question policy: workflow declaration, then the injected settings value."""
    declared = workflow.open_question_mode.strip().casefold()
    if declared:
        return declared
    return fallback


def resolve_skill_package(skill_id: str) -> SkillPackage | None:
    """Resolve one package from the skill library by canonical id or alias.

    The catalog owns the id/alias rules (``he-*`` canonical, ``bmad-*`` alias, plus each
    package's own ``aliases`` metadata), so the workflow package and the per-step role
    packages are addressed by id instead of by hand-built paths or a private alias table.
    ``None`` means "not installed here"; callers decide whether that is a missing
    configuration (workflow) or a hard failure (a role a step declared).
    """
    try:
        # Path(".")：本地根保持 cwd 相对（scan 时才解析）；非入口层不得直取进程工作目录（cwd 兜底契约）。
        roots = default_skill_roots(Path("."))
        return SkillResolver(SkillCatalog(roots).scan()).resolve(skill_id)
    except (SkillCatalogError, ValueError, OSError) as exc:
        logger.debug("Skill package %r is unavailable under %s (%s)", skill_id, GOAL_SKILLS_ROOT, exc)
        return None


class WorkflowBinding(BaseModel):
    """一个 goal 冻结的 workflow 绑定（Story 51-6，AD-4：跨模块状态用模型不传 dict）。

    ``workflow_id`` 是 skill catalog 可解析的**包 id**；``revision`` 是创建时冻结的
    revision（:func:`workflow_revision` 的声明或派生值），空串 = 创建时尚无冻结值
    （存量 goal 兼容形态），恢复时不做 revision 比对。
    """

    workflow_id: str
    revision: str = ""


def read_workflow_binding(goal_dir: Path, default_workflow_id: str) -> WorkflowBinding:
    """读取 goal 需求文档 frontmatter 里冻结的 workflow 绑定（**只读**，AD-8）。

    - 文档声明了非空 ``workflow:`` 键 → 返回冻结值（``workflow_revision`` 缺键时落空串：
      两键由创建路径一起写入，半键属手改，绑定 id 仍以声明为准、不发明 revision；
      空串 revision 在恢复时**不比对漂移**——手改文档形态下冻结保证的显式兼容决定）；
    - **反向半键（有 ``workflow_revision`` 无 ``workflow``）显性抛** :class:`ValueError`：
      外来 revision 配到当前配置包上几乎必然误报漂移（指纹撞车则静默换包），拒绝猜测；
    - **缺键（存量 goal）→ 兼容规则**绑定调用方注入的 ``default_workflow_id``（入口层取
      ``Settings.goal_workflow_skill``，引擎面不认识任何具体包名，AD-13），**不写回原件**
      ——只读路径改写会让并发读方互踩文档，且「隐式迁移」正是 AD-8 要挡的静默行为；
    - frontmatter 解析复用 :mod:`heagent.pub.frontmatter`（架构契约
      ``test_frontmatter_parsing_is_centralized``）；文档损坏（无 frontmatter / 键值非法）
      显性抛 :class:`OSError` / :class:`ValueError`，不做静默兜底。
    """
    text = goal_document_path(goal_dir).read_text(encoding="utf-8")
    split = split_frontmatter(text)
    if split is None:
        # 存量文档没有 frontmatter（极老的 GOAL.md 形态）：同样走兼容绑定，不发明冻结值。
        return WorkflowBinding(workflow_id=default_workflow_id)
    values = parse_strict_pairs(split[0])
    workflow_id = str(values.get("workflow", "")).strip().strip("\"'")
    revision = str(values.get("workflow_revision", "")).strip().strip("\"'")
    if revision and not workflow_id:
        raise ValueError(
            f"goal document declares 'workflow_revision' without the 'workflow' key; "
            f"refusing to guess the bound package for goal '{goal_dir.name}'"
        )
    return WorkflowBinding(workflow_id=workflow_id or default_workflow_id, revision=revision)


def resolve_bound_workflow(goal_dir: Path, default_workflow_id: str) -> WorkflowResource:
    """按 goal 冻结的绑定解析 workflow；漂移 / 缺包 fail-loud（Story 51-6，AD-8）。

    链路：:func:`read_workflow_binding` → ``resolve_skill_package``（缺包显性报错，文案含
    缺的包 id）→ ``read_workflow`` + :func:`validate_goal_workflow` → 绑定 revision 非空时
    与 :func:`workflow_revision` 的当前派生/声明值比对，不一致抛
    :class:`~heagent.engine.WorkflowCheckpointError`（文案含两个 revision 与 goal id）。
    空对空（存量 goal + 未声明 revision 的包）不比对——兼容规则不发明历史冻结值。
    这样改配置（``Settings.goal_workflow_skill``）或改包内容都不会让运行中 goal 静默换流程。
    """
    binding = read_workflow_binding(goal_dir, default_workflow_id)
    package = resolve_skill_package(binding.workflow_id)
    if package is None:
        raise WorkflowCheckpointError(
            f"workflow package '{binding.workflow_id}' is unavailable under the skill library; "
            f"goal '{goal_dir.name}' is bound to it and will not silently switch workflows"
        )
    try:
        workflow = read_workflow(package, "workflow.md")
        validate_goal_workflow(workflow)
    except (SkillWorkflowError, ValueError, OSError) as exc:
        raise WorkflowCheckpointError(
            f"workflow '{binding.workflow_id}' bound by goal '{goal_dir.name}' is invalid: {exc}"
        ) from exc
    current = workflow_revision(package, workflow)
    if binding.revision and current != binding.revision:
        raise WorkflowCheckpointError(
            f"workflow '{binding.workflow_id}' drifted since goal '{goal_dir.name}' was created: "
            f"frozen revision {binding.revision}, current revision {current}; "
            "restore the package (or its declared revision) before advancing this goal"
        )
    return workflow


def gate_requirements(workflow: WorkflowResource, validation_rules: str) -> str:
    """Render the step's post-hoc gate contract so the executor sees it beforehand.

    ``validation: section: <title>`` is enforced by ``WorkflowRunner`` only *after* the
    step returns.  Without this block a long step can finish all its work and still be
    blocked on a heading it was never told to emit.  The wording lives in the workflow
    package (the file the frontmatter ``gate_template`` key names), so it changes without
    touching code.
    """
    rules = (validation_rules or "").strip()
    sections = required_sections(rules)
    needs_given_when_then = "given" in rules.casefold()
    if not sections and not needs_given_when_then:
        return ""
    if not workflow.gate_template.strip():
        # 步骤声明了门禁规则却渲染不出门禁块：显性失败。产出空门禁会让执行者
        # 干完全部工作、再被 WorkflowRunner 的事后闸门拦下重做（本函数要防的正是这个）。
        raise SkillWorkflowError(
            workflow.name,
            "gate_template",
            "step declares gate rules but the workflow package declares no gate template; "
            "set gate_template: templates/<file>.md in workflow.md frontmatter "
            "(the declared file is enforced at load)",
        )
    headings = ""
    if sections:
        headings = (
            "- Your final response must contain each of these Markdown headings exactly as written, each on its own "
            "line with nothing else on that line:\n"
            + "\n".join(f"  - ## {section}" for section in sections)
            + "\n- A missing, renamed, or suffixed heading blocks the whole step: the workflow will not advance and "
            "this step's work has to be redone.\n"
        )
    acceptance = "- Acceptance criteria must be written as Given / When / Then.\n" if needs_given_when_then else ""
    template = workflow.gate_template
    return render_template(
        template,
        {"sections": headings, "acceptance": acceptance, "rules": f"- Declared validation rules (verbatim): {rules}"},
    )


def open_question_policy(workflow: WorkflowResource, fallback_mode: str) -> str:
    """Resolve the open-question policy wording: workflow declaration, then built-in default."""
    if open_question_mode(workflow, fallback_mode) == "default":
        return workflow.open_question_default or _DEFAULT_OPEN_QUESTION_DEFAULT
    return workflow.open_question_block or _DEFAULT_OPEN_QUESTION_BLOCK


def _is_input_body(value: Any) -> bool:
    """该输入项是否承载可渲染正文：去重只针对非空字符串（其余原样保留）。"""
    return isinstance(value, str) and bool(value)


def dedupe_inputs(inputs: Mapping[str, Any], declared: str = "") -> list[tuple[str, Any]]:
    """Render each distinct input body once, under its most meaningful key.

    A completed step stores its artifact under both the declared output names and the
    artifact file name, so rendering every key duplicated whole artifacts in the step
    prompt (the step-07 prompt measured ~130k tokens with roughly half of it repeated
    text).  Among keys sharing one body, the one this step declares in ``input:`` wins;
    otherwise the first occurrence wins.  Nothing unique is dropped.
    """
    wanted = {item.strip() for item in re.split(r"[,\n]", declared) if item.strip()}
    chosen: dict[str, str] = {}
    for name, value in inputs.items():
        if not _is_input_body(value):
            continue
        current = chosen.get(value)
        if current is None or (name in wanted and current not in wanted):
            chosen[value] = name
    return [(name, value) for name, value in inputs.items() if not _is_input_body(value) or chosen[value] == name]


def role_instructions(workflow: WorkflowResource, step_name: str) -> str:
    """Load the role contract assigned to a workflow step.

    角色在**传入的 workflow** 上查——此前这里按 step 名重载全局 ``_goal_declarative_workflow()``，
    而调用方本来就持有 workflow：等于把参数静默替换成另一份来源。后果是测试传合成 workflow 时
    仍按**真实** workflow 解析 role，从而依赖本机 ``.heagent/skills/`` 技能库（该目录 gitignore），
    在干净检出（CI）上必然报 "workflow role ... is unavailable" 而红。
    """
    role_name = next((step.role for step in workflow.steps if step.name == step_name), "")
    if not role_name:
        return "No specialized BMad role assigned."
    package = resolve_skill_package(role_name)
    if package is None:
        raise ValueError(f"workflow role '{role_name}' is unavailable: no skill package named '{role_name}'")
    return package.read_entry().text


def declarative_prompt(
    workflow: WorkflowResource,
    step_name: str,
    description: str,
    goal_dir: Path,
    inputs: Mapping[str, Any],
    story: Any = None,
    validation_rules: str = "",
    declared_inputs: str = "",
    *,
    open_question_fallback: str,
) -> str:
    """Assemble one step's executor prompt; ``open_question_fallback`` is injected by the entry."""
    role = role_instructions(workflow, step_name)
    gate = gate_requirements(workflow, validation_rules)
    gate_block = f"{gate}\n\n" if gate else ""
    supplied_inputs = "\n\n".join(f"## {name}\n{value}" for name, value in dedupe_inputs(inputs, declared_inputs))
    open_question = open_question_policy(workflow, open_question_fallback)
    story_context = ""
    if story is not None:
        epic_ref = str(getattr(story, "epic", "") or "")
        story_context = (
            f"Active story: {story.id}"
            + (f" - {story.summary}" if story.summary else "")
            + (f"\nParent epic: {epic_ref}" if epic_ref else "")
            + "\nWork only on this one story; leave all other stories for subsequent increments.\n"
        )
    if not workflow.prompt_template.strip():
        # 未声明 prompt_template 的包缺提示词模板：拒绝渲染空提示词（goal/角色/门禁上下文将全部丢失）。
        raise SkillWorkflowError(
            workflow.name,
            "prompt_template",
            "workflow package ships no prompt template; set prompt_template: templates/<file>.md "
            "in workflow.md frontmatter (the declared file is enforced at load)",
        )
    template = workflow.prompt_template
    return render_template(
        template,
        {
            "workflow_instructions": workflow.instructions,
            "goal": description,
            "goal_dir": str(goal_dir.resolve()),
            "goal_document": goal_document_path(goal_dir).name,
            "output_root": str(goal_dir.parent.parent.resolve()),
            "step": step_name,
            "story_context": story_context,
            "role": role,
            "open_question_policy": open_question,
            "inputs": supplied_inputs,
            "gate": gate_block,
        },
    )


def load_stories(goal_dir: Path, step: Any) -> list[Any]:
    """Load and parse the story list referenced by a story-loop step."""
    # 围栏走 path_safety 单算法（逃逸 = WorkspacePathError，ValueError 子类，调用方已捕获）。
    path = resolve_under_root(step.story_loop.strip(), goal_dir)
    return parse_story_list(path.read_text(encoding="utf-8"))
