"""SKILL.md 渲染与 frontmatter 就地改写（memory/skills 拆分层，Phase 4 C4）。

「只改元数据、正文逐字节保留」的唯一格式来源：:func:`render_skill_md`（整体渲染）、
:func:`body_survives_rerender`（正文可否无损重渲染的判定）、:func:`patch_frontmatter`
（行级 upsert/remove）、:func:`update_usage_frontmatter`（只改计数）。解析侧配对
模型见 :mod:`.skill_models`。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.memory.skill_models import FRONTMATTER_RE, SkillContent

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping


def metadata_lines(
    *,
    name: str,
    description: str,
    created: str,
    tags: list[str] | None,
    triggers: list[str] | None,
    negative_triggers: list[str] | None,
    priority: int,
    usage_count: int,
    last_used: str,
) -> list[str]:
    """frontmatter 主体行（不含首尾 ``---``）——渲染与就地改写共用的唯一格式来源。"""
    lines = [f"name: {name}", f'description: "{description}"', f"created: {created}"]
    for key, values in (
        ("tags", tags),
        ("triggers", triggers),
        ("negative_triggers", negative_triggers),
    ):
        if values:
            lines.append(f"{key}: [{', '.join(values)}]")
    if priority:
        lines.append(f"priority: {priority}")
    lines.append(f"usage_count: {usage_count}")
    if last_used:
        lines.append(f'last_used: "{last_used}"')
    return lines


def key_line(lines: list[str], key: str) -> str | None:
    """取 ``key:`` 开头的规范行；该字段缺省时返回 None。"""
    prefix = f"{key}:"
    return next((line for line in lines if line.startswith(prefix)), None)


def render_skill_md(
    name: str,
    description: str,
    pattern: str,
    steps: list[str],
    *,
    tags: list[str] | None,
    triggers: list[str] | None,
    negative_triggers: list[str] | None,
    priority: int,
    usage_count: int,
    last_used: str,
    created: str,
) -> str:
    """Render the canonical on-disk representation for one skill."""
    fm_lines = [
        "---",
        *metadata_lines(
            name=name,
            description=description,
            created=created,
            tags=tags,
            triggers=triggers,
            negative_triggers=negative_triggers,
            priority=priority,
            usage_count=usage_count,
            last_used=last_used,
        ),
        "---",
        "",
    ]

    body_lines = [f"# {name}", ""]
    if pattern:
        body_lines.extend(["## Pattern", pattern, ""])
    body_lines.append("## Steps")
    body_lines.extend(f"{i}. {step}" for i, step in enumerate(steps, 1))
    body_lines.append("")
    return "\n".join(fm_lines) + "\n" + "\n".join(body_lines)


def body_survives_rerender(raw: str) -> bool:
    """正文是否能被 :func:`render_skill_md` 无损表达。

    渲染器只产出 ``# <name>`` / ``## Pattern`` / ``## Steps``，解析器也只读后两节；
    其余章节（手写角色契约、附加说明）在任何整体重渲染中都会被丢弃。返回 False 的
    技能必须走「只改 frontmatter 计数、正文逐字节保留」的就地路径。
    """
    match = FRONTMATTER_RE.match(raw)
    body = raw[match.end() :] if match is not None else raw
    section = ""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "## Pattern":
            section = "pattern"
            continue
        if stripped == "## Steps":
            section = "steps"
            continue
        if stripped.startswith("#"):
            if stripped.startswith("# ") and not section:
                continue  # 渲染器写的 H1 标题，重渲染会原样重建
            return False
        if not section:
            return False
    return True


def patch_frontmatter(raw: str, upserts: Mapping[str, str], removals: Collection[str] = ()) -> str | None:
    """就地改写 frontmatter：``upserts`` 整行替换，``removals`` 删除整行。

    正文与未涉及的 frontmatter 行逐字节保留（按 group(1) 跨度替换，分隔符与空行不受
    影响）。无 frontmatter 块时返回 None——调用方保留原文件，不做猜测性改写。
    """
    match = FRONTMATTER_RE.match(raw)
    if match is None:
        return None
    remove = set(removals)
    keys = (*upserts, *remove)
    lines: list[str] = []
    seen: set[str] = set()
    for line in match.group(1).splitlines():
        stripped = line.strip()
        key = next((candidate for candidate in keys if stripped.startswith(f"{candidate}:")), None)
        if key is None:
            lines.append(line)
            continue
        seen.add(key)
        if key in upserts:
            lines.append(upserts[key])
    for key, replacement in upserts.items():
        if key not in seen:
            lines.append(replacement)
    return raw[: match.start(1)] + "\n".join(lines) + raw[match.end(1) :]


def update_usage_frontmatter(raw: str, existing: SkillContent, last_used: str) -> str | None:
    """只改写 usage_count / last_used，正文与其余行逐字节保留。

    供「正文含 ``## Pattern`` / ``## Steps`` 之外章节」的技能使用（见
    :func:`body_survives_rerender`）。无 frontmatter 时返回 None：不做猜测性
    改写，调用方保留原文件并记 warning（显性可观测，而非静默丢计数）。
    """
    lines = metadata_lines(
        name=existing.name,
        description=existing.description,
        created=existing.created,
        tags=existing.tags or None,
        triggers=existing.triggers or None,
        negative_triggers=existing.negative_triggers or None,
        priority=existing.priority,
        usage_count=existing.usage_count + 1,
        last_used=last_used,
    )
    return patch_frontmatter(
        raw,
        {
            "usage_count": key_line(lines, "usage_count") or f"usage_count: {existing.usage_count + 1}",
            "last_used": key_line(lines, "last_used") or f'last_used: "{last_used}"',
        },
    )
