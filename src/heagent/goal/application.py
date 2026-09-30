"""``/goal`` 工作流的确定性内核（click-free use-case 层，Phase 3）。

**为什么单独成模块**（goal/document.py 先例）：此前 workflow 校验、gate 渲染、
story 选择、checkpoint 恢复、prompt 装配与推进编排全部混在 ``cli/goal.py``，与
``click.echo`` 渲染交织——确定性内核无法在无 Click 环境运行与测试，GUI 只能靠
stderr 重定向获知进度。本模块承载与渲染无关的确定性部分：**不导入 click /
heagent.cli* / heagent.gui***（架构契约测试钉死 import 图）；用户可见文案以
结构化 message 返回，由 ``cli/goal`` 统一渲染。

**配置注入原则**（Phase 1 延续）：本模块不调用 ``get_settings()``——checkpoint /
open-question 策略的 settings 回退值由入口（cli/goal）作为参数注入。

分层：本子包属入口层（与 cli/gui 同级，供 cli/goal 消费），依赖 ``heagent.engine``
/ ``heagent.memory`` / ``heagent.pub.persist`` 等下层模块，不被任何下层模块导入。
cli/goal 经 re-export / 薄壳保持原命名空间可用（monkeypatch 缝见 spec-phase3）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from heagent.engine import (
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowResource,
    WorkflowRunner,
    WorkflowStatus,
    WorkflowStepResult,
    parse_story_list,
    required_sections,
)
from heagent.goal.decisions import DecisionAction, DecisionRecord, decision_store, new_decision_id
from heagent.goal.document import _goal_document_path, _goal_record_user_response, _goal_user_responses
from heagent.goal.workflow_loader import SkillWorkflowError, read_workflow, workflow_revision
from heagent.memory.skill_packages import (
    SkillCatalog,
    SkillCatalogError,
    SkillPackage,
    SkillResolver,
)
from heagent.pub.frontmatter import parse_strict_pairs, split_frontmatter
from heagent.pub.persist import atomic_write_text
from heagent.pub.workspace import WorkspacePaths

logger = logging.getLogger(__name__)

# /goal 的技能库根：工作流包与每个步骤的角色包都从这里按 id 解析（单一来源）。
_GOAL_SKILLS_ROOT = Path(".heagent/skills")
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
        return SkillResolver(SkillCatalog([str(_GOAL_SKILLS_ROOT)]).scan()).resolve(skill_id)
    except (SkillCatalogError, ValueError, OSError) as exc:
        logger.debug("Skill package %r is unavailable under %s (%s)", skill_id, _GOAL_SKILLS_ROOT, exc)
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
    text = _goal_document_path(goal_dir).read_text(encoding="utf-8")
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


_CHECKPOINT_WORKSPACE_FILE = "checkpoint-workspace.txt"


def external_checkpoint_dir(goal_id: str, workspace: Path) -> Path:
    """Return the new-goal checkpoint directory for one workspace."""
    return WorkspacePaths.from_root(workspace).checkpoints / goal_id


def initialize_checkpoint_workspace(goal_dir: Path, workspace: Path) -> None:
    """Record the checkpoint workspace once, only when creating a new goal."""
    marker = goal_dir / _CHECKPOINT_WORKSPACE_FILE
    if marker.exists() or (goal_dir / "workflow.json").exists() or (goal_dir / "checkpoints").exists():
        raise ValueError("checkpoint workspace cannot be changed for an existing goal")
    atomic_write_text(marker, str(WorkspacePaths.from_root(workspace).root))


def checkpoint_store(goal_dir: Path) -> WorkflowCheckpointStore:
    """Legacy goals keep local checkpoints; new goals persist their workspace binding.

    这是 checkpoint 目录的**唯一解析点**：预检方（``/goal doctor``）通过
    ``WorkflowCheckpointStore.base_dir`` 取同一目录，不再另算一份。
    """
    try:
        recorded_root = (goal_dir / _CHECKPOINT_WORKSPACE_FILE).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        base = goal_dir / "checkpoints"
    else:
        if not recorded_root or not Path(recorded_root).is_absolute():
            raise ValueError("checkpoint workspace must be an absolute path")
        base = external_checkpoint_dir(goal_dir.name, Path(recorded_root))
    return WorkflowCheckpointStore(
        str(base),
        workflow_path=str(goal_dir / "workflow.json"),
    )


async def restore_runner(workflow: WorkflowResource, goal_dir: Path) -> WorkflowRunner:
    """Restore the latest Runner snapshot or create a new one for this goal.

    **checkpoint ↔ 运行状态的引用关系与恢复语义**（Phase 3 显式化）：一个 goal 目录内，
    ``checkpoints/*.json`` 是逐步的原子快照，``workflow.json``（GoalWorkflowState）是
    聚合进度；``brief.md``（存量 goal 为 ``require.md`` / ``GOAL.md``）的「原始需求」段与
    ``.heagent/goals/current`` 指针由入口层解析后传入 ``goal_dir``，本函数不回读指针。恢复顺序：
    ① 有 workflow.json 时按
    ``active_step + active_skill + status`` 匹配快照（status 宽容一个「快照已完成但聚合
    仍在跑」的相位差，见下），工作流改名靠 active_skill 而非 name 兜住；② 匹配落空且
    存在快照 → 配置与持久化状态不一致，显性抛
    :class:`~heagent.engine.WorkflowCheckpointError`（不静默重建）；③ 无 workflow.json
    时本 goal 目录私有 checkpoint 集的最新一条即权威恢复点（不依赖可选描述元数据）；
    ④ 全空 → 新建 Runner。幂等键：checkpoint 以 ``checkpoint_id`` 落盘，store 侧对同
    id 逻辑重复写做 conflict 检测（见 ``WorkflowCheckpointStore.save``）。
    """
    store = checkpoint_store(goal_dir)
    checkpoints = await store.list_checkpoints(goal_id=goal_dir.name)
    workflow_state = await store.load_state()
    if workflow_state is not None:
        # Match against the persisted active_skill (workflow.json) rather than the
        # current workflow.name, so a workflow rename does not strand existing goals.
        matching = [
            checkpoint
            for checkpoint in checkpoints
            if checkpoint.active_step == workflow_state.active_step
            and checkpoint.active_skill == workflow_state.active_skill
            and (
                checkpoint.status is workflow_state.status
                or (checkpoint.status is WorkflowStatus.COMPLETED and workflow_state.status is WorkflowStatus.RUNNING)
            )
        ]
        if matching:
            return WorkflowRunner.from_checkpoint(
                workflow,
                matching[-1],
                checkpoint_store=store,
                phase=WorkflowPhase.IMPLEMENTATION,
            )
        if checkpoints:
            raise WorkflowCheckpointError("workflow configuration does not match the persisted goal state")
    # Each goal owns its checkpoint directory, so the latest checkpoint for this
    # goal is the authoritative recovery point. Do not make recovery contingent
    # on optional descriptive metadata such as ``active_skill``.
    if checkpoints:
        return WorkflowRunner.from_checkpoint(
            workflow,
            checkpoints[-1],
            checkpoint_store=store,
            phase=WorkflowPhase.IMPLEMENTATION,
        )
    return WorkflowRunner(
        workflow,
        goal_id=goal_dir.name,
        checkpoint_store=store,
        phase=WorkflowPhase.IMPLEMENTATION,
    )


def gate_requirements(workflow: WorkflowResource, validation_rules: str) -> str:
    """Render the step's post-hoc gate contract so the executor sees it beforehand.

    ``validation: section: <title>`` is enforced by ``WorkflowRunner`` only *after* the
    step returns.  Without this block a long step can finish all its work and still be
    blocked on a heading it was never told to emit.  The wording lives in the workflow
    package (``gate-template.md``), so it changes without touching code.
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
            "gate-template.md",
            "step declares gate rules but the workflow package ships no gate template; "
            "add templates/gate-template.md or declare it in required_resources to fail at load",
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
        if not (isinstance(value, str) and value):
            continue
        current = chosen.get(value)
        if current is None or (name in wanted and current not in wanted):
            chosen[value] = name
    return [
        (name, value)
        for name, value in inputs.items()
        if not (isinstance(value, str) and value) or chosen[value] == name
    ]


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
        # 未声明 required 的包缺提示词模板：拒绝渲染空提示词（goal/角色/门禁上下文将全部丢失）。
        raise SkillWorkflowError(
            workflow.name,
            "prompt-template.md",
            "workflow package ships no prompt template; add templates/prompt-template.md "
            "or declare it in required_resources to fail at load",
        )
    template = workflow.prompt_template
    return render_template(
        template,
        {
            "workflow_instructions": workflow.instructions,
            "goal": description,
            "goal_dir": str(goal_dir.resolve()),
            "goal_document": _goal_document_path(goal_dir).name,
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
    source = step.story_loop.strip()
    root = goal_dir.resolve()
    path = (goal_dir / source).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"story source escapes the goal directory: {source}")
    return parse_story_list(path.read_text(encoding="utf-8"))


@dataclass
class _GoalAdvanceContext:
    """Prepared state for one declarative advance invocation."""

    runner: WorkflowRunner
    mode: str
    description: str
    goal_dir: Path


class GoalAdvanceStatus(StrEnum):
    """One declarative advance invocation's terminal word（值与 cli/goal 的 ``_GOAL_*`` 一致）."""

    ADVANCED = "advanced"
    DONE = "done"
    FAILED = "failed"
    WAITING = "waiting"


class GoalAdvanceOutcome(BaseModel):
    """Structured result of one ``advance`` invocation.

    用户可见文案以 ``messages``（已含 ``[goal]`` 前缀的完整行）携带，由入口层统一
    渲染——确定性内核不触碰 stderr；同一 use-case 因此可被 CLI/GUI/cron 共用而
    不经 Click（Phase 3 验收）。
    """

    status: GoalAdvanceStatus
    messages: list[str] = Field(default_factory=list)


# 入口注入的步骤执行端口：入参 (inputs, step, story)——inputs 由 advance 每轮装配后
# 传入，bridge 到 engine ``WorkflowRunner.run_step`` 的 ``(step, story)`` 回调契约。
StepExecutor = Callable[[Mapping[str, Any], Any, Any], Awaitable[WorkflowStepResult]]


class _StorySourceError(Exception):
    """A step's declared story source cannot be loaded (message is user-facing verbatim).

    单独类型而非裸 ``ValueError``：``advance`` 对「故事源读不了」与「工作流执行失败」给
    **不同**的用户可见文案，两者混在一个 except 里会让前者的提示被后者吞掉。
    """


def _stories_for(goal_dir: Path, step: Any) -> list[Any] | None:
    """该步声明的 story 清单（未声明 ``story_loop`` 返回 ``None``）。"""
    if not step.story_loop.strip():
        return None
    try:
        return load_stories(goal_dir, step)
    except (OSError, ValueError) as exc:
        raise _StorySourceError(str(exc)) from exc


async def _run_step_with_inputs(
    inputs: Mapping[str, Any],
    execute_step: StepExecutor,
    step: Any,
    story: Any = None,
) -> WorkflowStepResult:
    """``run_step`` 回调桥：把 advance 每轮装配的 inputs 携带给入口注入的执行端口。

    经 :class:`functools.partial` 绑定前两参后即为 ``run_step`` 的 ``(step, story)``
    回调契约；binding by value 也避开了循环内闭包对 ``inputs`` 的晚绑定歧义。
    """
    return await execute_step(inputs, step, story)


async def _advance_checkpoint_decision(
    result: Any,
    runner: WorkflowRunner,
    mode: str,
    confirm_checkpoint: Callable[[], bool],
    messages: list[str],
    emit: Callable[..., None] | None = None,
) -> GoalAdvanceStatus | None:
    """WAITING_USER checkpoint 决策（中断回调不算隐式批准）；``None`` → 继续推进。

    auto 模式直接 resume 持久化；manual 模式先问注入的 ``confirm_checkpoint`` 端口
    （CLI 为 TTY confirm 实现，其自身的提示文案由端口负责）。
    """
    if runner.state.awaiting_approval:
        # 审批门挂起（Story 51-5）：cron / 无人值守推进不得自动批准人工 Gate，只有
        # approve / reject / amend 三种显式决策能离开；文案按模式分流（审查 #13），
        # manual 模式不宣传 auto-advance。
        if mode == "auto":
            messages.append(
                "[goal] a step awaits a human decision: /goal approve | /goal reject <原因> | /goal amend <补充> "
                "(/goal decisions lists records); auto-advance will not approve it"
            )
        else:
            messages.append(
                "[goal] a step awaits a human decision; decide first with "
                "/goal approve | /goal reject <原因> | /goal amend <补充> (/goal decisions lists records)"
            )
        return GoalAdvanceStatus.WAITING
    step_checkpoint = result.step_index is not None and (result.step_index - 1) in runner.state.completed_steps
    story_checkpoint = result.story_id is not None and result.story_id in runner.state.completed_stories
    if not (step_checkpoint or story_checkpoint):
        return GoalAdvanceStatus.WAITING
    if mode == "auto":
        runner.resume(emit=emit)
    elif not confirm_checkpoint():
        return GoalAdvanceStatus.WAITING
    else:
        runner.resume(emit=emit)
    try:
        await runner.persist_state()
    except (WorkflowCheckpointError, ValueError, TypeError) as exc:
        messages.append(f"[goal] declarative checkpoint failed: {exc}")
        return GoalAdvanceStatus.FAILED
    return None


async def advance(
    context: _GoalAdvanceContext,
    execute_step: StepExecutor,
    *,
    confirm_checkpoint: Callable[[], bool],
    load_project_context: Callable[[], str | None],
    emit: Callable[[str], None] | None = None,
) -> GoalAdvanceOutcome:
    """Advance deterministically through steps and resolve completed checkpoints.

    端口注入：``execute_step``（LLM 会话，缝在 cli/goal）、``confirm_checkpoint``
    （manual 模式的 checkpoint 批准决策，CLI 为 TTY confirm 实现）、
    ``load_project_context``（cwd 锚定属入口）、``emit``（步骤粒度观测端口，
    Phase 5 C1：透传 ``WorkflowRunner.run_step`` 发 workflow_step_* 事件；缺省 None
    = 零行为变化）。其余——inputs 装配、story 选择、run_step 编排、BLOCKED 指路
    与 checkpoint 决策——全部确定性收敛于此。
    """
    runner = context.runner
    mode = context.mode
    description = context.description
    goal_dir = context.goal_dir
    messages: list[str] = []
    # 脚本步骤**声明**的后续声明步骤（Story 51-7 的 A2 提交点）：计划存在 Runner 状态里并随
    # checkpoint 持久化（重启后仍按同一选择恢复），本循环只负责按序取队首提交。只有脚本
    # 步骤会往里放东西，老 workflow 因此逐字不变。

    def outcome(status: GoalAdvanceStatus) -> GoalAdvanceOutcome:
        return GoalAdvanceOutcome(status=status, messages=messages)

    # Input declarations describe the context supplied by this deterministic CLI
    # boundary. Artifact names from completed steps remain available on resume.
    while True:
        try:
            user_responses = _goal_user_responses(goal_dir)
        except OSError as exc:
            messages.append(f"[goal] declarative requirement document is unreadable: {exc}")
            return outcome(GoalAdvanceStatus.FAILED)
        inputs: dict[str, Any] = {
            "user intent": description,
            "user responses": user_responses or "No user response has been recorded.",
            "existing project context": load_project_context()
            or "No project context file was found; inspect the current workspace before making assumptions.",
            **runner.state.outputs,
        }
        callback = partial(_run_step_with_inputs, inputs, execute_step)
        plan = runner.state.requested_steps
        try:
            if plan:
                # 上一步（脚本步骤）声明的后续声明步骤优先执行：顺序权仍在 Runner，由
                # :meth:`WorkflowRunner.run_declared_step` 校验并推进状态（Story 51-7 A1/A2）。
                result = await runner.run_declared_step(plan[0], callback, inputs=inputs, emit=emit)
            else:
                active_step = runner.workflow.steps[runner.state.active_step]
                stories = _stories_for(goal_dir, active_step)
                result = await runner.run_step(callback, inputs=inputs, stories=stories, emit=emit)
        except _StorySourceError as exc:
            messages.append(f"[goal] declarative story source failed: {exc}")
            return outcome(GoalAdvanceStatus.FAILED)
        except (WorkflowCheckpointError, ValueError, TypeError) as exc:
            messages.append(f"[goal] declarative workflow failed: {exc}")
            return outcome(GoalAdvanceStatus.FAILED)
        story_label = f" story={result.story_id}" if result.story_id else ""
        messages.append(
            f"[goal] declarative workflow: step={result.step_index if result.step_index is not None else '-'}"
            f"{story_label} status={result.status.value}"
        )
        if result.skipped:
            # 已完成的声明步骤：不重跑、不改状态（幂等），继续消费计划。
            messages.append(f"[goal] {result.reason}")
            continue
        if result.status is WorkflowStatus.COMPLETED:
            return outcome(GoalAdvanceStatus.DONE)
        if result.status is WorkflowStatus.PENDING:
            if runner.state.requested_steps or mode == "auto":
                continue
            return outcome(GoalAdvanceStatus.ADVANCED)
        if result.status is not WorkflowStatus.WAITING_USER:
            if result.status is WorkflowStatus.BLOCKED:
                reason = result.reason or runner.state.reason or "the step output failed its gate"
                messages.append(f"[goal] step blocked: {reason}")
                messages.append(
                    "[goal] the step must be re-run: record a human acknowledgement with "
                    "`/goal resume <说明>` (the active step then executes again); `/goal status` shows the state."
                )
            return outcome(GoalAdvanceStatus.FAILED)

        # WAITING_USER from a completed step is a checkpoint decision; an
        # interrupted callback must never be treated as implicit approval.
        decision = await _advance_checkpoint_decision(result, runner, mode, confirm_checkpoint, messages, emit)
        if decision is not None:
            return outcome(decision)


class PauseResumeStatus(StrEnum):
    """Terminal word of one pause/resume request."""

    RESUMED = "resumed"
    PAUSED = "paused"
    UNCHANGED = "unchanged"
    FAILED = "failed"


class PauseResumeOutcome(BaseModel):
    """Structured result of one pause/resume request（``proceed`` 对应旧布尔返回值）."""

    status: PauseResumeStatus
    proceed: bool = False
    message: str = ""


async def pause_resume(
    workflow: WorkflowResource,
    goal_dir: Path,
    *,
    resume: bool,
    response: str = "",
) -> PauseResumeOutcome:
    """Persist a pause or resume; ``proceed`` reports whether a step may now execute."""
    action = "workflow"
    try:
        runner = await restore_runner(workflow, goal_dir)
        if runner.done:
            return PauseResumeOutcome(
                status=PauseResumeStatus.UNCHANGED, message="[goal] declarative workflow is already complete"
            )
        if resume:
            if runner.state.status not in {WorkflowStatus.WAITING_USER, WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
                return PauseResumeOutcome(
                    status=PauseResumeStatus.UNCHANGED,
                    message=f"[goal] workflow status={runner.state.status.value}; resume is not required",
                )
            if runner.state.awaiting_approval:
                # 审批门挂起（Story 51-5）：resume 不能隐式等同批准——先做显式决策。
                return PauseResumeOutcome(
                    status=PauseResumeStatus.UNCHANGED,
                    message="[goal] the active step awaits a decision; /goal resume cannot approve it — "
                    "use /goal approve | /goal reject <原因> | /goal amend <补充>",
                )
            if response:
                _goal_record_user_response(goal_dir, response)
            runner.resume()
            # 决策日志契约（Story 51-5 引擎面）：resume 每次一条记录——它只标记「执行被
            # 恢复」，不改变审批门状态、不等于批准（挂门时的 resume 在上方被显性拒绝，
            # 不产生记录）。先落账再持久化，与 record_decision 同一次序。
            await decision_store(goal_dir).append(
                DecisionRecord(
                    decision_id=new_decision_id(),
                    goal_id=goal_dir.name,
                    action=DecisionAction.RESUME,
                    step=runner.current_step.name,
                    raw_text=response,
                    workflow_status=runner.state.status,
                    approval_round=runner.state.approval_round,
                )
            )
            action = "resumed"
        else:
            if runner.state.status is WorkflowStatus.WAITING_USER:
                return PauseResumeOutcome(
                    status=PauseResumeStatus.UNCHANGED, message="[goal] already paused; use /goal resume to continue"
                )
            runner.pause()
            action = "paused"
        await runner.persist_state()
    except (WorkflowCheckpointError, ValueError, OSError) as exc:
        return PauseResumeOutcome(status=PauseResumeStatus.FAILED, message=f"[goal] declarative {action} failed: {exc}")
    return PauseResumeOutcome(
        status=PauseResumeStatus.RESUMED if resume else PauseResumeStatus.PAUSED,
        proceed=resume,
        message=f"[goal] declarative workflow {action}: step={runner.state.active_step}",
    )


class DecisionStatus(StrEnum):
    """Terminal word of one human decision request（与 ``_GOAL_*`` 词汇同风格）."""

    RECORDED = "recorded"
    UNCHANGED = "unchanged"
    FAILED = "failed"


class DecisionOutcome(BaseModel):
    """Structured result of one approve / reject / amend request（messages 由入口层渲染）."""

    status: DecisionStatus
    proceed: bool = False
    decision_id: str = ""
    message: str = ""


async def record_decision(
    workflow: WorkflowResource,
    goal_dir: Path,
    *,
    action: DecisionAction,
    text: str = "",
) -> DecisionOutcome:
    """人工决策 use-case（Story 51-5）：落状态 + 追加一条决策记录，CLI / GUI 共用。

    - **approve**：接受挂起步骤的工作并落定完成簿记（runner 的唯一完成路径），随后入口层
      可继续推进下一条；**reject**：驳回，步骤保持未完成、落 BLOCKED 等待重做；
      **amend**：带补充重跑，步骤保持未完成、落 PENDING。三者语义独立（AD-3），各记一条。
    - 决策记录是**工作流产物**（``<goal_dir>/decisions/``，:func:`decision_store` 唯一解析点），
      追加式保存、重跑不覆盖历史；不写进 workflow 包。
    - reject / amend 的原文同时落需求文档「用户补充」段：决策日志是审计面事实，用户补充是
      执行面输入（重跑会话经 ``user responses`` 读到补充）。approve 不携带执行语义文本。
      用户补充写在决策**落账之后**：账已生效，补充写失败只降级为提示，不回滚决策。
    - 落定次序（审查 #2）：内存态变更 → 决策落账（append）→ 状态持久化——审计记录先于
      状态落盘，任何一步失败都在 FAILED 文案里披露已发生的部分副作用，不留「决策已生效
      却永无审计」或「无审计却已持久化」的静默态。
    - cron 无人值守推进**不调用**本函数（auto 推进在 :func:`_advance_checkpoint_decision`
      被审批门挡下），人工 Gate 不可能被自动批准。
    """
    if action is DecisionAction.RESUME:
        # resume 有自己的 use-case（pause_resume 记一条 RESUME 决策 / advance 检查点决策），
        # 不是决策命令；混进来会让「resume 当 approve 用」有一条静默通道（AD-3 负向验证锚点）。
        return DecisionOutcome(
            status=DecisionStatus.FAILED,
            message="[goal] resume is not a decision; use /goal resume (it cannot approve an approval gate)",
        )
    if action is not DecisionAction.APPROVE and not text.strip():
        # 审查 #8：空白的拒绝理由 / 修订补充会落成空 reason 的 BLOCKED 与空审计记录。
        return DecisionOutcome(
            status=DecisionStatus.FAILED,
            message=f"[goal] {action.value} requires a non-empty {'reason' if action is DecisionAction.REJECT else 'supplement'}; nothing was changed",
        )
    record: DecisionRecord | None = None
    try:
        runner = await restore_runner(workflow, goal_dir)
        if runner.done:
            return DecisionOutcome(
                status=DecisionStatus.UNCHANGED, message="[goal] declarative workflow is already complete"
            )
        if not runner.state.awaiting_approval:
            return DecisionOutcome(
                status=DecisionStatus.UNCHANGED,
                message=f"[goal] no step is awaiting a decision; workflow status={runner.state.status.value} "
                "(decisions apply to a step that declared 'approval: required')",
            )
        step = runner.current_step
        story_id = runner.state.active_story or ""
        if action is DecisionAction.APPROVE:
            runner.approve()
        elif action is DecisionAction.REJECT:
            runner.reject(text)
        else:
            runner.amend(text)
        record = DecisionRecord(
            decision_id=new_decision_id(),
            goal_id=goal_dir.name,
            action=action,
            step=step.name,
            story_id=story_id,
            raw_text=text,
            workflow_status=runner.state.status,
            approval_round=runner.state.approval_round,
        )
        await decision_store(goal_dir).append(record)
        await runner.persist_state()
    except (WorkflowCheckpointError, ValueError, TypeError, OSError) as exc:
        detail = (
            f"decision {record.decision_id[:8]} is already recorded" if record is not None else "no record was written"
        )
        return DecisionOutcome(
            status=DecisionStatus.FAILED,
            decision_id=record.decision_id if record is not None else "",
            message=f"[goal] {action.value} failed: {exc} ({detail}; check /goal decisions and /goal status)",
        )
    supplement_note = ""
    if text and action is not DecisionAction.APPROVE:
        try:
            _goal_record_user_response(goal_dir, text)
        except OSError as exc:
            # 账已生效：补充只是执行面输入，写失败不回滚决策，但必须显性暴露（不静默）。
            supplement_note = f" (warning: the text did not reach the requirement document: {exc})"
    message = (
        f"[goal] {action.value} recorded: step={step.name}"
        + (f" story={story_id}" if story_id else "")
        + f" status={runner.state.status.value} decision={record.decision_id[:8]}"
    )
    if (
        action is DecisionAction.APPROVE
        and runner.state.status is WorkflowStatus.WAITING_USER
        and not runner.state.awaiting_approval
    ):
        # 审查 #11：该步同时声明了 checkpoint——批准已完成簿记，剩下的是普通检查点等待。
        message += " (the completion is booked; this step also declared a checkpoint — /goal resume continues)"
    return DecisionOutcome(
        status=DecisionStatus.RECORDED,
        proceed=action is not DecisionAction.REJECT,
        decision_id=record.decision_id,
        message=message + supplement_note,
    )
