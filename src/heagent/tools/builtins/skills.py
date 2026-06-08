"""技能管理工具 — 供 LLM 自主创建、更新、列出和删除技能。

通过 configure_skill_tools(store) 注入 SkillStore 实例。
未配置时所有工具返回错误提示，不会抛异常。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.tools.decorator import tool

if TYPE_CHECKING:
    from heagent.memory.skills import SkillStore

_skill_store: SkillStore | None = None


def configure_skill_tools(store: SkillStore) -> None:
    """注入 SkillStore 实例，激活技能管理工具。"""
    global _skill_store
    _skill_store = store


def reset_skill_tools() -> None:
    """重置模块级 SkillStore（测试清理用）。"""
    global _skill_store
    _skill_store = None


@tool
async def skill_create(
    name: str,
    description: str,
    pattern: str,
    steps: str,
    tags: str = "",
) -> str:
    """创建一个新的可复用技能。name 必须使用英文（仅 a-z, 0-9, _, -）。
    steps 用管道符分隔（如 step1|step2|step3）。tags 用管道符分隔（如 deploy|production）。

    参数：
        name: 技能名称（必须英文，如 deploy_production）
        description: 技能描述
        pattern: 模式描述（何时使用此技能）
        steps: 执行步骤，用 | 分隔
        tags: 标签，用 | 分隔（可选）
    """
    if _skill_store is None:
        return "Error: skill tools not configured."
    existing = _skill_store.load(name)
    if existing is not None:
        return f"Error: skill '{name}' already exists. Use skill_update to modify it."
    step_list = [s.strip() for s in steps.split("|") if s.strip()]
    if not step_list:
        return "Error: at least one step is required."
    tag_list = [t.strip() for t in tags.split("|") if t.strip()] if tags else None
    try:
        path = _skill_store.save(name, description, pattern, step_list, tags=tag_list)
    except ValueError as e:
        return f"Error: {e}"
    return f"Skill '{name}' created at {path}"


@tool
async def skill_update(
    name: str,
    description: str = "",
    pattern: str = "",
    steps: str = "",
    tags: str = "",
) -> str:
    """更新已有技能的内容。仅更新非空字段，空字段保持原样。

    参数：
        name: 技能名称
        description: 新的技能描述（空则不修改）
        pattern: 新的模式描述（空则不修改）
        steps: 新的执行步骤，用 | 分隔（空则不修改）
        tags: 新的标签，用 | 分隔（空则不修改）
    """
    if _skill_store is None:
        return "Error: skill tools not configured."
    parsed = _skill_store.parse(name)
    if parsed is None:
        return f"Error: skill '{name}' not found. Use skill_create first."
    desc = description if description else None
    pat = pattern if pattern else None
    step_list = [s.strip() for s in steps.split("|") if s.strip()] if steps else None
    tag_list = [t.strip() for t in tags.split("|") if t.strip()] if tags else None
    path = _skill_store.update(name, description=desc, pattern=pat, steps=step_list, tags=tag_list)
    if path is None:
        return f"Error: failed to update skill '{name}'."
    return f"Skill '{name}' updated at {path}"


@tool
async def skill_list() -> str:
    """列出所有已存储的技能名称和描述。"""
    if _skill_store is None:
        return "Error: skill tools not configured."
    names = _skill_store.list_skills()
    if not names:
        return "No skills stored yet. Use skill_create to add one."
    lines: list[str] = []
    for n in names:
        parsed = _skill_store.parse(n)
        desc = parsed.description if parsed else "(unable to parse)"
        lines.append(f"- {n}: {desc}")
    return "\n".join(lines)


@tool
async def skill_delete(name: str) -> str:
    """删除指定的技能。

    参数：
        name: 技能名称
    """
    if _skill_store is None:
        return "Error: skill tools not configured."
    if _skill_store.delete(name):
        return f"Skill '{name}' deleted."
    return f"Error: skill '{name}' not found."


@tool
async def skill_curate(days: str = "30") -> str:
    """查看过期技能。列出超过 N 天未使用的技能（含使用次数和最后使用时间）。
    用于保持技能库整洁，配合 skill_archive 归档不再需要的技能。

    参数：
        days: 多少天未使用视为过期（默认 30）
    """
    if _skill_store is None:
        return "Error: skill tools not configured."
    try:
        stale_days = int(days)
    except ValueError:
        return "Error: days must be a number."
    stale = _skill_store.stale_skills(days=stale_days)
    if not stale:
        return f"No stale skills found (all used within {stale_days} days)."
    lines: list[str] = [f"Found {len(stale)} stale skill(s) (unused for {stale_days}+ days):\n"]
    for name in stale:
        parsed = _skill_store.parse(name)
        if parsed:
            lines.append(f"- {name}: used {parsed.usage_count}x, last: {parsed.last_used or 'never'}")
        else:
            lines.append(f"- {name}: (parse error)")
    return "\n".join(lines)


@tool
async def skill_archive(name: str) -> str:
    """归档一个不再需要的技能。归档后技能不会出现在匹配和列表中，但可从 .archive/ 恢复。

    参数：
        name: 要归档的技能名称
    """
    if _skill_store is None:
        return "Error: skill tools not configured."
    if _skill_store.archive(name):
        return f"Skill '{name}' archived to .heagent/skills/.archive/"
    return f"Error: skill '{name}' not found."
