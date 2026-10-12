"""声明式工作流加载：把技能包的 ``workflow.md`` 装配成引擎模型。

解析机器 2026-09-20 自 ``memory/skill_packages.py`` 归位到 /goal 领域层：技能包模块只保留
通用资源索引与安全读取，工作流声明（frontmatter 策略 / 内嵌步骤 / 模板必需性 ``required_resources``）
的确定性装配集中在此。运行时契约模型在 ``engine/workflow_resource.py``（runner / checkpoint /
gate 的消费对象），本模块只做「声明 → 模型」的装载，不执行任何步骤。
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Literal, cast, get_args

from heagent.engine.workflow_resource import (
    APPROVAL_KEYWORDS,
    DOCTOR_CHECKS,
    STATUS_FIELDS,
    CheckpointMode,
    DoctorCheck,
    OpenQuestionMode,
    StatusField,
    StepApproval,
    StepValidationClauses,
    WorkflowResource,
    WorkflowStepResource,
    ensure_workspace_relative_path,
    section_titles,
)
from heagent.engine.workflow_runner import WorkflowGateError
from heagent.goal.quality_gates import QUALITY_GATES, gate_declaration_problem, is_registered_gate
from heagent.pub.frontmatter import (
    FrontmatterSyntaxError,
    parse_strict_pairs,
    split_frontmatter,
)
from heagent.pub.types import StorySpec
from heagent.skills.skill_packages import SkillPackage, SkillPackageResourceError

LOGGER = logging.getLogger(__name__)


class SkillWorkflowError(SkillPackageResourceError):
    """Raised when a declarative workflow or its ordered steps are invalid."""


# ``validation:`` 里可声明的证据子句（引擎词汇，与 ``section:`` 同处一个字符串、同一分隔符）。
# 命名质量门 ``gate:`` 只声明名字；**名字必须在宿主注册表内**（goal/quality_gates 的
# QUALITY_GATES，Story 51-4）：workflow 只能引用宿主门、不能发明或削弱，写出未注册名字
# = 加载期 fail-loud。
_EVIDENCE_CLAUSE_NAMES = ("section", "command", "artifact", "git", "gate")
# 子句形态：段首的单词 + 冒号。多词前缀（``Given a user: …``）不是子句，仍是普通文本门禁。
_CLAUSE_PREFIX = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?P<value>.*)$", re.DOTALL)
# 子句名 → 模型字段（显式映射：确定性查表，不靠命名约定拼属性名）。
_CLAUSE_FIELDS: dict[str, str] = {
    "section": "sections",
    "command": "commands",
    "artifact": "artifacts",
    "git": "git_paths",
    "gate": "gates",
}


def parse_validation_clauses(package: SkillPackage, origin: str, validation_rules: str) -> StepValidationClauses:
    """Parse a step's ``validation:`` string into evidence clauses（声明 → 模型）.

    与既有 ``section:`` 同处一个字符串、同一分隔符。两个解析通道，各自与既有语义同源：

    - ``section:`` 提取**复用** :func:`heagent.engine.workflow_resource.section_titles`
      （即既有文本门禁的 ``required_sections`` 正则，全串扫描，含普通文本里的内嵌形态，
      如 ``must include section: X``）——两处解析永不漂移；
    - 其余子句按 ``,`` / ``;`` 切段（引号内的分隔符不拆段，引号不平衡显性报错），段首
      ``<名字>:`` 识别子句；名字不在词汇表内 = 声明错误，加载期 fail-loud（拼错的子句
      静默丢弃会让「要求证据」变成「不要求」，所以绝不静默忽略）。

    「老包零行为变化」的准确边界：声明里**没有** ``<Word>:`` 形态的段时完全不变
    （纯文本门禁如 ``has plan`` / ``given…when…then`` 原样留给 ``WorkflowRunner``）；
    形如 ``coverage: 85%`` 或 ``subsection: x`` 的段首单词冒号会被当作未知子句而
    fail-loud——这是「未知子句不静默忽略」的直接后果，如实声明。
    """
    if "\n" in validation_rules or "\r" in validation_rules:
        # 声明是单行字符串：换行会把第二条命令/子句走私进同一条记录。
        raise SkillWorkflowError(package.skill_id, origin, "validation declaration must be a single line")
    clauses = StepValidationClauses()
    # ``section:`` 单独通道（与既有解析器同源）；段内识别到 section 前缀时跳过，不重复计。
    clauses.sections = section_titles(validation_rules)
    for segment in _split_clause_segments(package, origin, validation_rules):
        text = segment.strip()
        if not text:
            continue
        match = _CLAUSE_PREFIX.match(text)
        if match is None:
            continue  # 普通文本门禁（既有语义，不进子句模型）
        name = match.group("name").casefold()
        if name == "section":
            continue  # 已由 section_titles 同源提取
        if name not in _EVIDENCE_CLAUSE_NAMES:
            raise SkillWorkflowError(
                package.skill_id,
                origin,
                f"unknown validation clause '{match.group('name')}:'; "
                f"expected one of {', '.join(_EVIDENCE_CLAUSE_NAMES)}",
            )
        value = _strip_outer_quotes(match.group("value").strip())
        if not value:
            raise SkillWorkflowError(package.skill_id, origin, f"validation clause '{name}:' requires a value")
        if name == "gate":
            _require_registered_gate(package, origin, value)
        if name in {"artifact", "git"}:
            _require_relative_path(package, origin, name, value)
        target: list[str] = getattr(clauses, _CLAUSE_FIELDS[name])
        target.append(value)
    # 命名门的**必要声明条件**（加载期，与未注册同归 fail-loud）：如 tests-pass 投影的是本步
    # 声明命令的证据，单独声明没有证据来源（判定单一真源在 quality_gates.gate_declaration_problem）。
    problem = gate_declaration_problem(clauses)
    if problem:
        raise SkillWorkflowError(package.skill_id, origin, problem)
    return clauses


def _split_clause_segments(package: SkillPackage, origin: str, validation_rules: str) -> list[str]:
    """按 ``,`` / ``;`` 切段；引号内的分隔符不拆段（``command: pytest -k "a,b"`` 是一条命令），
    引号不平衡显性报错（不得静默截断半条声明）。"""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for character in validation_rules:
        if quote is not None:
            current.append(character)
            if character == quote:
                quote = None
        elif character in {'"', "'"}:
            quote = character
            current.append(character)
        elif character in {",", ";"}:
            segments.append("".join(current))
            current = []
        else:
            current.append(character)
    if quote is not None:
        raise SkillWorkflowError(package.skill_id, origin, f"unbalanced quote {quote!r} in validation declaration")
    segments.append("".join(current))
    return segments


def _strip_outer_quotes(value: str) -> str:
    """剥掉**一对平衡的**外层引号；内层引号原样保留（声明的命令要逐字保真）。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _require_relative_path(package: SkillPackage, origin: str, clause: str, value: str) -> None:
    """产物 / Git 子句的路径必须落在工作区内；判定单一真源在
    :func:`heagent.engine.workflow_resource.ensure_workspace_relative_path`（模型校验器同规）。"""
    try:
        ensure_workspace_relative_path(value)
    except ValueError as exc:
        raise SkillWorkflowError(package.skill_id, origin, f"validation clause '{clause}:' {exc}") from exc


def _require_registered_gate(package: SkillPackage, origin: str, name: str) -> None:
    """``gate:`` 名字必须在宿主注册表（:data:`heagent.goal.quality_gates.QUALITY_GATES`）内。

    workflow 只能**引用**宿主内置门，不能发明名字（更不能自带实现或削弱参数）；拼错 /
    未经注册的名字静默通过会让「声明了质量门」变成「没有门」，因此加载期显性失败。
    报错文案附每个注册门的宿主语义（含其必要声明条件，如 tests-pass 必须与 command: 同用）
    ——文案单一真源在注册表的 ``description`` 字段，不在本模块复写。
    """
    if is_registered_gate(name):
        return
    registered = "; ".join(f"{spec.name} ({spec.description})" for spec in QUALITY_GATES.values()) or "none"
    raise SkillWorkflowError(
        package.skill_id,
        origin,
        f"unknown quality gate '{name}'; registered gates: {registered}",
    )


def _step_approval(package: SkillPackage, origin: str, values: dict[str, Any]) -> StepApproval:
    """解析步骤的 ``approval:`` 声明（声明 → 模型，加载期 fail-loud，Story 51-5）。

    合法形态只有 ``approval: required``（可带一句说明：``approval: required 架构冻结前需
    人工确认``）；关键词词汇单一真源在
    :data:`heagent.engine.workflow_resource.APPROVAL_KEYWORDS`。未声明（键缺失）= 不需要
    人工确认，零行为变化；**声明了键却是空白 / ``none`` / ``null``** 同样加载期显性报错
    （审查 #4：声明意图不明确，「声明了审批」被静默吞成「无门」是人工 Gate 缺口）；其余
    取值（含拼错的关键词）一律显性报错——静默吞掉声明会跨过人工 Gate。
    """
    if "approval" not in values:
        return StepApproval()
    raw = _value_text(values, "approval")
    if not raw:
        raise SkillWorkflowError(
            package.skill_id,
            origin,
            "approval declaration is present but blank (or 'none'/'null'); "
            "declare 'approval: required' or remove the key",
        )
    parts = raw.split(None, 1)
    keyword = parts[0].casefold()
    if keyword not in APPROVAL_KEYWORDS:
        raise SkillWorkflowError(
            package.skill_id,
            origin,
            f"invalid approval declaration {raw!r}; expected 'approval: required' "
            f"(optionally followed by a short note); valid keywords: {', '.join(APPROVAL_KEYWORDS)}",
        )
    return StepApproval(required=True, note=parts[1].strip() if len(parts) > 1 else "")


def read_workflow(package: SkillPackage, resource: str = "workflow.md") -> WorkflowResource:  # noqa: C901
    """Load ``workflow.md`` and all declared/discovered steps in order.

    The workflow file is the only authority for an explicit ``steps`` list.
    A workflow may keep its step contracts in the same file using ``## Step
    NN: name`` sections; external ``step-NN-*.md`` resources remain
    supported for compatibility with existing packages.
    """
    try:
        text = package.read_resource(resource)
    except SkillPackageResourceError as exc:
        raise SkillWorkflowError(package.skill_id, resource, exc.reason) from exc
    try:
        values, body = _parse_resource_frontmatter(text)
    except ValueError as exc:
        raise SkillWorkflowError(package.skill_id, resource, str(exc)) from exc
    inline, names = _resolve_workflow_step_names(package, values, body, resource)
    if not names:
        raise SkillWorkflowError(package.skill_id, resource, "workflow has no steps")
    steps: list[WorkflowStepResource] = []
    seen_names: set[str] = set()
    seen_indexes: set[int] = set()
    for position, name in enumerate(names, 1):
        if name in seen_names:
            raise SkillWorkflowError(package.skill_id, name, "duplicate step reference")
        seen_names.add(name)
        match = re.match(r"^step-(\d+)(?:[-_].*)?\.md$", Path(name).name, re.IGNORECASE)
        if match is None:
            raise SkillWorkflowError(package.skill_id, name, "step filename must use step-NN-*.md order")
        index = int(match.group(1))
        if index in seen_indexes:
            raise SkillWorkflowError(package.skill_id, name, "duplicate step number")
        seen_indexes.add(index)
        if index != position:
            raise SkillWorkflowError(package.skill_id, name, "step order must start at 1 and be contiguous")
        inline_step = next((step for step in inline if step.name == name), None)
        if inline_step is not None:
            steps.append(inline_step.model_copy(update={"index": index}))
            continue
        try:
            step_text = package.read_resource(name)
        except SkillPackageResourceError as exc:
            raise SkillWorkflowError(package.skill_id, name, exc.reason) from exc
        try:
            step_values, step_body = _parse_resource_frontmatter(step_text)
        except ValueError as exc:
            raise SkillWorkflowError(package.skill_id, name, str(exc)) from exc
        # 声明串只求值一次：raw 与解析视图必须来自同一份文本（求值两次 = 漂移温床）。
        validation_text = _value_text(step_values, "validation", "validation_rules", "verify")
        steps.append(
            WorkflowStepResource(
                index=index,
                name=name,
                instructions=step_body.strip(),
                input=_value_text(step_values, "input", "inputs"),
                output=_value_text(step_values, "output", "outputs"),
                next=_value_text(step_values, "next", "next_step") or None,
                checkpoint=_value_text(step_values, "checkpoint"),
                validation_rules=validation_text,
                validation_clauses=parse_validation_clauses(package, name, validation_text),
                role=_value_text(step_values, "role", "agent"),
                story_loop=_value_text(step_values, "story_loop"),
                max_parallel_stories=_parallel_limit(package, step_values, name),
                max_iterations=_iteration_budget(package, step_values, name),
                executor_mode=_executor_mode(package, step_values, name),
                script_resource=_script_resource(package, step_values, name),
                approval=_step_approval(package, name, step_values),
                frontmatter=step_values,
            )
        )
    known = {step.name for step in steps}
    for step in steps:
        if step.next and step.next not in known:
            raise SkillWorkflowError(package.skill_id, step.name, f"next step reference is not declared: {step.next}")
    checkpoint_mode = _value_text(values, "checkpoint_mode").casefold()
    if checkpoint_mode not in set(get_args(CheckpointMode)):
        # 合法值单一真源：CheckpointMode Literal（含空串=未声明），不在此手抄集合。
        raise SkillWorkflowError(
            package.skill_id,
            resource,
            f"invalid checkpoint_mode '{checkpoint_mode}'; "
            f"expected {' or '.join(mode for mode in get_args(CheckpointMode) if mode)}",
        )
    open_question_mode = _value_text(values, "open_question_mode", "open_questions").casefold()
    if open_question_mode not in set(get_args(OpenQuestionMode)):
        raise SkillWorkflowError(
            package.skill_id,
            resource,
            f"invalid open_question_mode '{open_question_mode}'; "
            f"expected {' or '.join(mode for mode in get_args(OpenQuestionMode) if mode)}",
        )
    _required_templates(package, values, resource)  # 声明条目的存在性校验（有副作用：缺失即抛）
    doctor_checks = _declared_members(package, values, resource, key="doctor_checks", allowed=DOCTOR_CHECKS)
    status_fields = _declared_members(package, values, resource, key="status_fields", allowed=STATUS_FIELDS)
    return WorkflowResource(
        name=_value_text(values, "name", "id") or package.skill_id,
        # ``revision``（Story 51-6）：缺省不报错、落空串 = 由包内容派生（workflow_revision）；
        # 老包不声明零行为变化。声明值原样保留（str(value).strip()，不做语义解释）。
        revision=_value_text(values, "revision"),
        instructions=(body.split("\n## Step ", 1)[0] if inline else body).strip(),
        steps=steps,
        entrypoint=_value_text(values, "entrypoint"),
        on_create=_value_text(values, "on_create", "initialize") or "persist_goal_identity",
        step_executor=_value_text(values, "step_executor", "executor") or "subagent",
        checkpoint_mode=cast("CheckpointMode", checkpoint_mode),
        open_question_mode=cast("OpenQuestionMode", open_question_mode),
        max_rounds=_bounded_int(package, values, resource, key="max_rounds", default=10, maximum=100),
        auto_schedule=_value_text(values, "auto_schedule"),
        open_question_default=_value_text(values, "open_question_default"),
        open_question_block=_value_text(values, "open_question_block"),
        prompt_template=_declared_template(package, values, resource, "prompt_template"),
        gate_template=_declared_template(package, values, resource, "gate_template"),
        doctor_checks=cast("list[DoctorCheck]", doctor_checks),
        status_fields=cast("list[StatusField]", status_fields),
        frontmatter=values,
    )


def workflow_revision(package: SkillPackage, workflow: WorkflowResource) -> str:
    """workflow revision 的**唯一派生点**（Story 51-6，AD-8 的冻结值来源）。

    - 包 frontmatter 显式声明了 ``revision``（:attr:`WorkflowResource.revision` 非空）→ 原样返回，
      包内容改动**不**触发漂移（版本由声明方负责推进）；
    - 未声明 → 对 ``workflow.md`` 全文 + ``required_resources`` 与 ``prompt_template`` /
      ``gate_template`` 键声明的全部资源内容（按相对路径排序，逐个经 ``package.read_resource``
      的**摘要通道**读取，manifest 漂移在此即失败）+ **外挂步骤文件**内容（``steps:`` 声明或
      自动发现的 ``step-NN-*.md``；步骤正文 / validation 声明漂移 = 流程漂移）做 sha256，返回
      十六进制摘要的**前 16 字符**——创建时冻结与恢复时
      比对都只认这 64 bit 指纹：它是防「静默换流程」的漂移判据，不是安全边界，全量 64 hex
      无比对收益。

    外挂步骤的发现与 :func:`read_workflow` 同源（``_resolve_workflow_step_names`` 单一实现）；
    全内联步骤的包（随包发布的模板包全部内联）不追加任何条目，**指纹取值不变**——冻结值
    语义兼容。

    资源读取失败（缺失 / hash 漂移）按原样抛 :class:`SkillPackageResourceError`——冻结一个
    读不到的值等于冻结未知，必须显性失败。
    """
    if workflow.revision.strip():
        return workflow.revision.strip()
    hasher = hashlib.sha256()
    text = package.read_resource("workflow.md")
    hasher.update(text.encode("utf-8"))
    declared = workflow.frontmatter.get("required_resources")
    names = _resource_list(package, declared, "workflow.md", "required_resources") if declared else []
    for name in sorted(f"templates/{item.removeprefix('templates/')}" for item in names):
        hasher.update(b"\x00")
        hasher.update(package.read_resource(name).encode("utf-8"))
    # 专用键指名的模板同属可执行契约：指名文件的措辞漂移 = 流程漂移。
    for key in ("prompt_template", "gate_template"):
        declared_template = workflow.frontmatter.get(key)
        if declared_template is None or not str(declared_template).strip():
            continue
        for name in _resource_list(package, declared_template, "workflow.md", key):
            hasher.update(b"\x00")
            hasher.update(package.read_resource(f"templates/{name.removeprefix('templates/')}").encode("utf-8"))
    # 外挂步骤文件进指纹；发现逻辑与 read_workflow 同源，内嵌步骤（名字命中内嵌集合）跳过。
    values, body = _parse_resource_frontmatter(text)
    inline, step_names = _resolve_workflow_step_names(package, values, body, "workflow.md")
    inline_names = {step.name for step in inline}
    for name in step_names:
        if name in inline_names:
            continue
        hasher.update(b"\x00")
        hasher.update(package.read_resource(name).encode("utf-8"))
    # Script resources are part of the executable workflow contract.  Include
    # each declared script exactly once, after the step declarations.
    scripts = sorted({step.script_resource for step in workflow.steps if step.script_resource})
    for name in scripts:
        hasher.update(b"\x00scripts/")
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(package.read_script(name).encode("utf-8"))
    return hasher.hexdigest()[:16]


def _read_optional_resource(package: SkillPackage, resource: str) -> str:
    """Read one ``templates/`` resource, returning ``""`` when it is absent or unreadable.

    Optional resources (step prompt / gate templates) must not make an otherwise
    valid workflow fail to load: requiredness, when it applies, is the workflow
    declaration's call (``required_resources``), enforced by ``_required_templates``.
    """
    try:
        return package.read_template(resource).strip()
    except SkillPackageResourceError:
        return ""


def _declared_template(package: SkillPackage, values: dict[str, Any], workflow: str, key: str) -> str:
    """frontmatter ``key``（``prompt_template`` / ``gate_template``）指名模板文件的正文。

    模板文件名声明在 ``workflow.md``（声明驱动，代码不携带固定文件名）。声明即承诺：键指名的
    文件缺失（或只剩空白）加载即失败，拼错名字同样显性报错；键不存在返回空串（包不携带，
    渲染期若用到由 application 显性失败）。
    """
    declared = values.get(key)
    if declared is None or not str(declared).strip():
        return ""
    names = _resource_list(package, declared, workflow, key)
    if len(names) != 1:
        raise SkillWorkflowError(package.skill_id, key, f"{key} must declare exactly one template file")
    name = names[0].removeprefix("templates/")
    body = _read_optional_resource(package, name)
    if not body:
        raise SkillWorkflowError(package.skill_id, name, f"declared in {key} but missing or blank")
    return body


def _required_templates(package: SkillPackage, values: dict[str, Any], workflow: str) -> frozenset[str]:
    """``templates/`` file names the workflow declaration marks required (``required_resources``).

    步骤/门禁模板已走专用键（``prompt_template`` / ``gate_template``，见 :func:`_declared_template`）；
    本函数继续兜住 ``required_resources`` 声明的其余 ``templates/`` 资源。每个声明条目都是硬承诺：
    文件缺失（或只剩空白）即加载失败——拼错名字同样显性报错，不做静默忽略。条目可带
    ``templates/`` 前缀，装载时归一化后匹配。
    """
    declared = values.get("required_resources")
    if not declared:
        return frozenset()
    names = frozenset(
        name.removeprefix("templates/") for name in _resource_list(package, declared, workflow, "required_resources")
    )
    for name in sorted(names):
        if not _read_optional_resource(package, name):
            raise SkillWorkflowError(package.skill_id, name, "declared in required_resources but missing or blank")
    return names


def _resolve_workflow_step_names(
    package: SkillPackage, values: dict[str, Any], body: str, resource: str
) -> tuple[list[WorkflowStepResource], list[str]]:
    """workflow 步骤名清单的**唯一发现逻辑**（``read_workflow`` 装载与 ``workflow_revision``
    派生共用，两处永不漂移）。

    优先级固定：frontmatter ``steps:`` 声明 → 内嵌 ``## Step NN:`` 区块 → 自动发现
    ``step-NN-*.md``。返回 ``(内嵌步骤模型, 全部步骤名)``：内嵌步骤的名字同时出现在
    ``names`` 里，装载时优先用内嵌模型、不重读文件；派生侧据此把 ``names`` 减去内嵌名
    即得**外挂步骤文件**集合。
    """
    declared = values.get("steps")
    inline = _parse_inline_workflow_steps(package, body)
    if declared is None or declared == "":
        names = [step.name for step in inline] if inline else _discover_workflow_steps(package)
    else:
        names = _resource_list(package, declared, resource)
    return inline, names


def _discover_workflow_steps(package: SkillPackage) -> list[str]:
    candidates = sorted(
        (
            path.name
            for path in package.root.iterdir()
            if path.is_file() and re.match(r"^step-\d+.*\.md$", path.name, re.I)
        ),
        key=_step_sort_key,
    )
    return candidates


def _parse_inline_workflow_steps(package: SkillPackage, body: str) -> list[WorkflowStepResource]:
    """Parse step contracts embedded in ``workflow.md``.

    Each section starts with ``## Step NN: name``. Metadata immediately
    following the heading uses the same ``key: value`` syntax as a step
    file; the remaining section is the step instruction text.
    """
    matches = list(re.finditer(r"(?m)^##\s+Step\s+(\d+)\s*:\s*([^\n]+)\s*$", body))
    if not matches:
        return []
    steps: list[WorkflowStepResource] = []
    for position, match in enumerate(matches, 1):
        number = int(match.group(1))
        if number != position:
            raise SkillWorkflowError(
                package.skill_id, "workflow.md", "inline step order must start at 1 and be contiguous"
            )
        raw_name = re.sub(r"[^a-z0-9]+", "-", match.group(2).strip().casefold()).strip("-")
        name = f"step-{number:02d}-{raw_name or 'step'}.md"
        end = matches[position].start() if position < len(matches) else len(body)
        section = body[match.end() : end].strip("\n")
        lines = section.splitlines()
        metadata: dict[str, Any] = {}
        instruction_start = 0
        for idx, line in enumerate(lines):
            if not line.strip():
                instruction_start = idx + 1
                break
            if ":" not in line or line[:1].isspace():
                instruction_start = idx
                break
            if re.match(r"^[-*+]\s", line):
                # 列表式元数据（``- input: x``）是常见笔误：收下会存成 ``- input`` 键、真实契约静默变空；
                # 想用 bullet 写正文，空一行隔开即可（空行终止元数据区）。
                raise SkillWorkflowError(
                    package.skill_id,
                    name,
                    f"inline step metadata must be bare 'key: value' lines, not markdown bullets: {line}",
                )
            key, value = line.split(":", 1)
            key = key.strip()
            if not key or key in metadata:
                raise SkillWorkflowError(package.skill_id, name, f"invalid inline step metadata: {line}")
            metadata[key] = value.strip().strip("\"'")
            instruction_start = idx + 1
        # 声明串只求值一次：raw 与解析视图必须来自同一份文本（求值两次 = 漂移温床）。
        validation_text = _value_text(metadata, "validation", "validation_rules", "verify")
        steps.append(
            WorkflowStepResource(
                index=number,
                name=name,
                instructions="\n".join(lines[instruction_start:]).strip(),
                input=_value_text(metadata, "input", "inputs"),
                output=_value_text(metadata, "output", "outputs"),
                next=_value_text(metadata, "next", "next_step") or None,
                checkpoint=_value_text(metadata, "checkpoint"),
                validation_rules=validation_text,
                validation_clauses=parse_validation_clauses(package, name, validation_text),
                role=_value_text(metadata, "role", "agent"),
                story_loop=_value_text(metadata, "story_loop"),
                max_parallel_stories=_parallel_limit(package, metadata, name),
                max_iterations=_iteration_budget(package, metadata, name),
                executor_mode=_executor_mode(package, metadata, name),
                script_resource=_script_resource(package, metadata, name),
                approval=_step_approval(package, name, metadata),
                frontmatter=metadata,
            )
        )
    return steps


def _step_sort_key(value: str) -> tuple[int, str]:
    match = re.match(r"^step-(\d+)", value, re.IGNORECASE)
    if match is None:
        raise ValueError(f"invalid step filename: {value}")
    return int(match.group(1)), value.lower()


def _declared_members(
    package: SkillPackage, values: dict[str, Any], resource: str, *, key: str, allowed: tuple[str, ...]
) -> list[str]:
    """Read one declaration list of engine vocabulary names, validating every entry.

    A workflow only chooses *which* registered check / field runs; inventing a name is a
    load error rather than a silently dropped entry, because a typo would otherwise turn a
    requested preflight into no preflight at all. An absent key yields an empty list, which
    callers read as "the engine default set" — existing packages keep their behaviour.
    """
    if key not in values:
        return []
    names = _resource_list(package, values[key], resource, key)
    unknown = [name for name in names if name not in allowed]
    if unknown:
        raise SkillWorkflowError(
            package.skill_id,
            resource,
            f"unknown {key} value(s): {', '.join(unknown)}; expected one of {', '.join(allowed)}",
        )
    if len(set(names)) != len(names):
        raise SkillWorkflowError(package.skill_id, resource, f"duplicate entry in {key}")
    return names


def frontmatter_name_list(value: Any) -> list[str] | None:
    """解析 frontmatter 的逗号分隔名称列表（A30② 单源解析核）。

    接受两种形态：``"[]"`` 包裹的逗号分隔字符串、字符串数组；其余类型返回 ``None``，
    **宽容度由调用方裁定**——loader 抛 :class:`SkillWorkflowError`（新工作流 fail-closed）、
    doctor 返回空表（老工作流诊断 fail-soft 仍能跑完）。除宽容度外的解析规则（strip /
    逗号切分 / 空项过滤）此处唯一实现，两调用方不得再持逐字副本。
    """
    if isinstance(value, str):
        return [item.strip() for item in value.strip("[]").split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return None


def _resource_list(package: SkillPackage, value: Any, workflow: str, label: str = "steps") -> list[str]:
    items = frontmatter_name_list(value)
    if items is None:
        raise SkillWorkflowError(package.skill_id, workflow, f"{label} must be a list")
    for item in items:
        if SkillPackage.is_absolute(item) or SkillPackage.has_parent(item):
            raise SkillWorkflowError(package.skill_id, item, f"{label} reference must stay within package root")
    return items


def _value_text(values: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in values and values[key] is not None:
            value = values[key]
            if isinstance(value, list):
                return ", ".join(str(item) for item in value)
            result = str(value).strip().strip("\"'")
            return "" if result.casefold() in {"none", "null"} else result
    return ""


def _bounded_int(
    package: SkillPackage, values: dict[str, Any], resource: str, *, key: str, default: int, maximum: int
) -> int:
    """解析有界整数设置（缺省取 ``default``；bool / 非数字 / 越界一律抛，不做强制转换）。

    ``max_parallel_stories`` 与 ``max_iterations`` 的校验规则本来逐字相同（各持一份副本），
    此处参数化为唯一实现：**两条规则必须一致**，否则同一份 frontmatter 在两处得到不同宽容度。
    """
    if key not in values:
        return default
    message = f"{key} must be an integer from 1 to {maximum}"
    raw = values[key]
    if isinstance(raw, bool):
        raise SkillWorkflowError(package.skill_id, resource, message)
    text = str(raw).strip().strip("\"'")
    if not re.fullmatch(r"[1-9]\d*", text or "") or int(text) > maximum:
        raise SkillWorkflowError(package.skill_id, resource, message)
    return int(text)


def _executor_mode(package: SkillPackage, values: dict[str, Any], resource: str) -> Literal["subagent", "script"]:
    raw = _value_text(values, "executor_mode") or "subagent"
    mode = raw.casefold()
    if mode not in {"subagent", "script"}:
        raise SkillWorkflowError(package.skill_id, resource, "executor_mode must be 'subagent' or 'script'")
    return cast("Literal['subagent', 'script']", mode)


def _script_resource(package: SkillPackage, values: dict[str, Any], resource: str) -> str:
    mode = _value_text(values, "executor_mode") or "subagent"
    script = _value_text(values, "script", "script_resource")
    if mode.casefold() != "script":
        if script:
            raise SkillWorkflowError(package.skill_id, resource, "script_resource requires executor_mode: script")
        return ""
    if not script:
        raise SkillWorkflowError(package.skill_id, resource, "executor_mode: script requires script_resource")
    if SkillPackage.is_absolute(script) or SkillPackage.has_parent(script):
        raise SkillWorkflowError(package.skill_id, resource, "script_resource must be a package-local path")
    try:
        package.read_script(script)
    except SkillPackageResourceError as exc:
        raise SkillWorkflowError(package.skill_id, resource, f"script resource is unavailable: {exc.reason}") from exc
    return script


def _parallel_limit(package: SkillPackage, values: dict[str, Any], resource: str) -> int:
    """Parse the bounded Step 07 concurrency setting without coercion."""
    limit = _bounded_int(package, values, resource, key="max_parallel_stories", default=1, maximum=5)
    if limit > 1:
        # 声明门控并行（Epic 52 AD-16/17）：>1 只是授权门的第一个条件，实际并发由批派生的
        # 七条件门控（write_set / parallel_group / depends_on / 撤销闩 / 回调契约等）——
        # 声明不等于并发度，这个语义差异必须显性告知模板作者，但不构成警告。
        LOGGER.info(
            "%s: %s declares max_parallel_stories=%d; declarative gated parallelism is available, "
            "actual concurrency is still gated by write_set / parallel_group / depends_on",
            package.skill_id,
            resource,
            limit,
        )
    return limit


def _iteration_budget(package: SkillPackage, values: dict[str, Any], resource: str) -> int:
    """Parse the optional per-step iteration budget (0 = inherit the global setting)."""
    return _bounded_int(package, values, resource, key="max_iterations", default=0, maximum=1000)


def _parse_resource_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    split = split_frontmatter(text, closed_at_eof=True)
    if split is None:
        return {}, text
    raw_block, end, _body = split
    try:
        pairs = parse_strict_pairs(raw_block)
    except FrontmatterSyntaxError as exc:
        # 异常类型（裸 ValueError）与消息文案保持收敛前契约（测试锁定）。
        if exc.kind == "invalid_line":
            raise ValueError(f"invalid workflow frontmatter line: {exc.line}") from exc
        raise ValueError(f"duplicate workflow frontmatter key: {exc.key}") from exc
    values: dict[str, Any] = {}
    for key, raw in pairs.items():
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            values[key] = [item.strip().strip("\"'") for item in raw[1:-1].split(",") if item.strip()]
        elif raw.lower() in {"true", "false"}:
            values[key] = raw.lower() == "true"
        else:
            values[key] = raw.strip("\"'")
    return values, text[end:]


# ── story 列表解析（A31② 自 engine/workflow_runner 迁入：BMad S-1/E1 形状解析属声明域）──
_STORY_ID = re.compile(r"^(?:story|s)[-_ ]?(\d+)$", re.IGNORECASE)
_STORY_HEADING = re.compile(
    r"^#{1,6}\s+(?P<id>(?:story|s)[-_ ]?\d+)\s*[:：\-—]?\s*(?P<summary>.*)$",
    re.IGNORECASE,
)
_STORY_LIST = re.compile(
    r"^[-*+]\s+(?:\[[ xX]\]\s+)?(?P<id>(?:story|s)[-_ ]?\d+)\s*[:：\-—]?\s*(?P<summary>.*)$",
    re.IGNORECASE,
)
_STORY_TABLE = re.compile(
    r"^\|\s*(?P<id>(?:story|s)[-_ ]?\d+)\s*\|\s*(?P<summary>.*?)\s*\|",
    re.IGNORECASE,
)
_EPIC_HEADING = re.compile(
    r"^#{1,6}\s+(?:epic[-_ ]*(?:e[-_ ]?)?|e[-_ ]?)(?P<epic>\d+)(?=$|[\s:：\-—.．])",
    re.IGNORECASE,
)
_STORY_METADATA = re.compile(r"^[-*]?\s*\*{0,2}(depends_on|parallel_group|write_set)\*{0,2}\s*[:：]\s*(.*?)\s*$", re.I)
_EPIC_FIELD = re.compile(
    r"(?:父\s*Epic|parent[-_ ]*epic|epic_id)\s*\**\s*[:：]\s*\**\s*(?P<epic>e[-_ ]?\d+|\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _normalize_story_id(raw: str) -> str:
    match = _STORY_ID.fullmatch(raw.strip())
    if match is None:
        raise WorkflowGateError(f"invalid story id: {raw!r}")
    return f"S-{int(match.group(1))}"


def _normalize_epic_id(raw: str) -> str:
    """Normalize an Epic reference (``E1`` / ``e 1`` / ``epic 1``) to ``E1``."""
    digits = re.search(r"\d+", raw or "")
    return f"E{int(digits.group(0))}" if digits is not None else (raw or "").strip()


def _story_sort_key(spec: StorySpec) -> int:
    match = re.fullmatch(r"S-(\d+)", spec.id)
    return int(match.group(1)) if match else 0


def _is_epic_reference(cell: str) -> bool:
    """True when a table cell is a bare Epic reference (``E1`` / ``E-1`` / ``Epic 1``)."""
    return bool(re.fullmatch(r"(?:epic[-_ ]*(?:e[-_ ]?)?|e[-_ ]?)\d+", cell.strip(), re.IGNORECASE))


def _story_table_entry(stripped: str) -> tuple[str, str, str] | None:
    """Parse one table row into ``(id, summary, epic_hint)``; ``None`` for a non-story row.

    An overview table such as ``| S-1 | E1 | P0 | none | <title> |`` puts the Epic in
    the second column and the human summary in the last one, so the raw second cell
    must not be mistaken for the story title.
    """
    match = _STORY_TABLE.match(stripped)
    if match is None:
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    summary = match.group("summary").strip()
    epic_hint = ""
    if len(cells) >= 3 and _is_epic_reference(cells[1]):
        epic_hint = _normalize_epic_id(cells[1])
        summary = next((cell for cell in reversed(cells[2:]) if cell), summary)
    return match.group("id"), summary, epic_hint


def _story_metadata(lines: list[str], start: int, end: int) -> dict[str, Any]:
    """Read declarations scoped to a story heading; other list shapes are unscoped."""
    metadata: dict[str, Any] = {}
    for line in lines[start + 1 : end]:
        if re.match(r"^#{1,6}\s", line.strip()):
            break
        match = _STORY_METADATA.match(line.strip())
        if match is None:
            continue
        key, value = match.groups()
        key = key.lower()
        if key in metadata:
            raise WorkflowGateError(f"duplicate story declaration: {key}")
        if key == "parallel_group":
            metadata[key] = value.strip()
        elif key == "depends_on":
            refs = [part.strip() for part in value.strip("[]").split(",") if part.strip()]
            metadata[key] = [_normalize_story_id(ref) for ref in refs]
        else:
            metadata[key] = [part.strip() for part in value.strip("[]").split(",") if part.strip()]
    return metadata


def parse_story_list(text: str) -> list[StorySpec]:
    """Extract an ordered story list from Markdown.

    Recognizes three common shapes so a step may consume an Epic proposal,
    a dedicated story checklist, or a story table:

    * ``### S-1 Scene rendering`` (heading)
    * ``- [ ] S-1 Scene rendering`` (list/checklist item)
    * ``| S-1 | Scene rendering |`` (table row)

    Shapes are ranked for a repeated id: a story heading outranks a list item,
    which outranks a table row. A document therefore still keeps every story it
    declares (including table-only rows) while an overview table such as
    ``| S-1 | E1 | P0 | none | <title> |`` can no longer overwrite the titles and
    Epics owned by the story sections. Story ids normalize to ``S-<n>`` and are
    deduplicated by id, then sorted by their numeric suffix. Non-story rows
    (e.g. Epic ids such as ``E-1``) are ignored.

    Epic grouping is optional: a story inherits the Epic declared by the nearest
    preceding Epic heading (``## E1 ...`` / ``## Epic 1 ...``), and an explicit
    ``- **父 Epic**: E1`` field inside the story block wins over that heading. A
    source without grouping keeps the flat behaviour (``epic`` stays empty).
    """
    if not isinstance(text, str) or not text.strip():
        return []
    lines = text.splitlines()
    epic_headings: list[tuple[int, str]] = []
    epic_fields: list[tuple[int, str]] = []
    stories: list[tuple[int, str, str, str]] = []
    ranks: dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        epic_match = _EPIC_HEADING.match(stripped)
        if epic_match is not None:
            epic_headings.append((index, _normalize_epic_id(epic_match.group("epic"))))
            continue
        entry: tuple[str, str, str, int] | None = None
        heading_match = _STORY_HEADING.match(stripped)
        if heading_match is not None:
            entry = (heading_match.group("id"), heading_match.group("summary").strip(), "", 0)
        else:
            list_match = _STORY_LIST.match(stripped)
            if list_match is not None:
                entry = (list_match.group("id"), list_match.group("summary").strip(), "", 1)
            else:
                table_entry = _story_table_entry(stripped)
                entry = (*table_entry, 2) if table_entry is not None else None
        if entry is not None:
            try:
                story_id = _normalize_story_id(entry[0])
            except WorkflowGateError:
                story_id = ""
            if story_id:
                rank = ranks.get(story_id)
                if rank is None:
                    ranks[story_id] = entry[3]
                    stories.append((index, story_id, entry[1], entry[2]))
                elif entry[3] < rank:
                    ranks[story_id] = entry[3]
                    position = next(pos for pos, item in enumerate(stories) if item[1] == story_id)
                    stories[position] = (index, story_id, entry[1], entry[2])
                continue
        field_match = _EPIC_FIELD.search(stripped)
        if field_match is not None:
            epic_fields.append((index, _normalize_epic_id(field_match.group("epic"))))
    specs: list[StorySpec] = []
    for position, (index, story_id, summary, epic_hint) in enumerate(stories):
        end = stories[position + 1][0] if position + 1 < len(stories) else len(lines)
        epic = epic_hint or next((value for field_index, value in epic_fields if index < field_index < end), "")
        if not epic:
            epic = next((value for heading_index, value in reversed(epic_headings) if heading_index < index), "")
        # Only a scoped heading owns metadata; a table or list cannot authorize parallelism.
        metadata = _story_metadata(lines, index, end) if ranks[story_id] == 0 else {}
        specs.append(StorySpec(id=story_id, summary=summary, epic=epic, **metadata))
    return sorted(specs, key=_story_sort_key)
