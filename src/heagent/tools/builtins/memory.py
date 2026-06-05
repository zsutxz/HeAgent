"""记忆管理工具 — 供 LLM 自主保存事实和更新用户画像。

通过 configure_memory_tools(facts, profile) 注入 Store 实例。
未配置时所有工具返回错误提示，不会抛异常。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.tools.decorator import tool

if TYPE_CHECKING:
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore

_fact_store: FactStore | None = None
_profile_store: ProfileStore | None = None


def configure_memory_tools(
    facts: FactStore | None = None,
    profile: ProfileStore | None = None,
) -> None:
    """注入 FactStore 和 ProfileStore 实例，激活记忆管理工具。"""
    global _fact_store, _profile_store
    _fact_store = facts
    _profile_store = profile


def reset_memory_tools() -> None:
    """重置模块级 Store（测试清理用）。"""
    global _fact_store, _profile_store
    _fact_store = None
    _profile_store = None


@tool
async def fact_add(fact: str) -> str:
    """保存一条事实到长期记忆。内容应简洁明确，如用户偏好、项目约定、关键决策等。

    参数：
        fact: 要保存的事实内容
    """
    if _fact_store is None:
        return "Error: fact tools not configured."
    if _fact_store.add(fact):
        return f"Fact saved: {fact}"
    return "Fact already exists (duplicate detected)."


@tool
async def profile_update(section: str, value: str) -> str:
    """更新用户画像的指定部分。用于记录用户的技术背景、偏好风格、交互习惯等。

    参数：
        section: 画像部分名称（如 Background, Preferences, CommunicationStyle）
        value: 该部分的内容描述
    """
    if _profile_store is None:
        return "Error: profile tools not configured."
    _profile_store.update_section(section, value)
    return f"Profile section '{section}' updated."
