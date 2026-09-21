"""声明式工作流加载：把技能包的 ``workflow.md`` 装配成引擎模型。

解析机器 2026-09-20 自 ``memory/skill_packages.py`` 归位到 /goal 领域层：技能包模块只保留
通用资源索引与安全读取，工作流声明（frontmatter 策略 / 内嵌步骤 / 模板必需性 ``required_resources``）
的确定性装配集中在此。运行时契约模型在 ``engine/workflow_resource.py``（runner / checkpoint /
gate 的消费对象），本模块只做「声明 → 模型」的装载，不执行任何步骤。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from heagent.engine.workflow_resource import (
    CheckpointMode,
    OpenQuestionMode,
    WorkflowResource,
    WorkflowStepResource,
)
from heagent.frontmatter import (
    FrontmatterSyntaxError,
    parse_strict_pairs,
    split_frontmatter,
)
from heagent.memory.skill_packages import SkillPackage, SkillPackageResourceError


class SkillWorkflowError(SkillPackageResourceError):
    """Raised when a declarative workflow or its ordered steps are invalid."""


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
    declared = values.get("steps")
    inline = _parse_inline_workflow_steps(package, body)
    if declared is None or declared == "":
        names = [step.name for step in inline] if inline else _discover_workflow_steps(package)
    else:
        names = _resource_list(package, declared, resource)
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
        steps.append(
            WorkflowStepResource(
                index=index,
                name=name,
                instructions=step_body.strip(),
                input=_value_text(step_values, "input", "inputs"),
                output=_value_text(step_values, "output", "outputs"),
                next=_value_text(step_values, "next", "next_step") or None,
                checkpoint=_value_text(step_values, "checkpoint"),
                validation_rules=_value_text(step_values, "validation", "validation_rules", "verify"),
                role=_value_text(step_values, "role", "agent"),
                story_loop=_value_text(step_values, "story_loop"),
                max_parallel_stories=_parallel_limit(package, step_values, name),
                max_iterations=_iteration_budget(package, step_values, name),
                frontmatter=step_values,
            )
        )
    known = {step.name for step in steps}
    for step in steps:
        if step.next and step.next not in known:
            raise SkillWorkflowError(package.skill_id, step.name, f"next step reference is not declared: {step.next}")
    checkpoint_mode = _value_text(values, "checkpoint_mode").casefold()
    if checkpoint_mode not in {"", "auto", "prompt"}:
        raise SkillWorkflowError(
            package.skill_id,
            resource,
            f"invalid checkpoint_mode '{checkpoint_mode}'; expected auto or prompt",
        )
    open_question_mode = _value_text(values, "open_question_mode", "open_questions").casefold()
    if open_question_mode not in {"", "block", "default"}:
        raise SkillWorkflowError(
            package.skill_id,
            resource,
            f"invalid open_question_mode '{open_question_mode}'; expected block or default",
        )
    required = _required_templates(package, values, resource)
    return WorkflowResource(
        name=_value_text(values, "name", "id") or package.skill_id,
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
        prompt_template=_read_template_resource(package, "prompt-template.md", required),
        gate_template=_read_template_resource(package, "gate-template.md", required),
        frontmatter=values,
    )


def _read_optional_resource(package: SkillPackage, resource: str) -> str:
    """Read one ``templates/`` resource, returning ``""`` when it is absent or unreadable.

    Optional resources (step prompt / gate templates) must not make an otherwise
    valid workflow fail to load: requiredness, when it applies, is the workflow
    declaration's call (``required_resources``), enforced by ``_read_template_resource``.
    """
    try:
        return package.read_template(resource).strip()
    except SkillPackageResourceError:
        return ""


def _required_templates(package: SkillPackage, values: dict[str, Any], workflow: str) -> frozenset[str]:
    """``templates/`` file names the workflow declaration marks required (``required_resources``)."""
    declared = values.get("required_resources")
    if not declared:
        return frozenset()
    return frozenset(_resource_list(package, declared, workflow, "required_resources"))


def _read_template_resource(package: SkillPackage, resource: str, required: frozenset[str]) -> str:
    """Read one ``templates/`` resource; blank-or-missing is fatal when declared required.

    Requiredness is the workflow declaration's call, not the loader's: a package that
    lists a resource in ``required_resources`` fails the load without it, while a
    package that stays silent keeps the resource optional.
    """
    text = _read_optional_resource(package, resource)
    if resource in required and not text:
        raise SkillWorkflowError(package.skill_id, resource, "declared in required_resources but missing or blank")
    return text


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
            key, value = line.split(":", 1)
            key = key.strip()
            if not key or key in metadata:
                raise SkillWorkflowError(package.skill_id, name, f"invalid inline step metadata: {line}")
            metadata[key] = value.strip().strip("\"'")
            instruction_start = idx + 1
        steps.append(
            WorkflowStepResource(
                index=number,
                name=name,
                instructions="\n".join(lines[instruction_start:]).strip(),
                input=_value_text(metadata, "input", "inputs"),
                output=_value_text(metadata, "output", "outputs"),
                next=_value_text(metadata, "next", "next_step") or None,
                checkpoint=_value_text(metadata, "checkpoint"),
                validation_rules=_value_text(metadata, "validation", "validation_rules", "verify"),
                role=_value_text(metadata, "role", "agent"),
                story_loop=_value_text(metadata, "story_loop"),
                max_parallel_stories=_parallel_limit(package, metadata, name),
                max_iterations=_iteration_budget(package, metadata, name),
                frontmatter=metadata,
            )
        )
    return steps


def _step_sort_key(value: str) -> tuple[int, str]:
    match = re.match(r"^step-(\d+)", value, re.IGNORECASE)
    if match is None:
        raise ValueError(f"invalid step filename: {value}")
    return int(match.group(1)), value.lower()


def _resource_list(package: SkillPackage, value: Any, workflow: str, label: str = "steps") -> list[str]:
    if isinstance(value, str):
        items = [item.strip() for item in value.strip("[]").split(",") if item.strip()]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
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


def _parallel_limit(package: SkillPackage, values: dict[str, Any], resource: str) -> int:
    """Parse the bounded Step 07 concurrency setting without coercion."""
    return _bounded_int(package, values, resource, key="max_parallel_stories", default=1, maximum=5)


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
