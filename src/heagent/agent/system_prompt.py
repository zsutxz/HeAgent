"""系统提示词拼装 —— 把人格 / 项目上下文 / 技能 / 记忆 / 画像合并成一条 SYSTEM 提示词。

从 ``AgentLoop`` 抽出的纯函数（无循环、无 async、无 engine 依赖），供
``AgentLoop._build_system`` 薄包装调用，使 ``loop.py`` 聚焦于「LLM ↔ 工具循环」。

本模块把每个提示词块拆成独立的 ``_*_block`` 生成函数（返回 ``str | None``，None = 该块不注入），
``build_system_prompt`` 里只留一份**有序列表**——注入顺序是硬约束（影响 LLM 权重），
把它写成字面量顺序比埋在一长串连续 ``append`` 里更不容易被后来者改错。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.config import Settings, get_settings
from heagent.context.tokens import estimate_text_tokens

if TYPE_CHECKING:
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore

logger = logging.getLogger(__name__)


def build_system_prompt(
    user_system: str | None,
    prompt: str,
    *,
    soul: SoulStore | None,
    context_dir: str | None,
    skills: SkillStore | None,
    facts: FactStore | None,
    profile: ProfileStore | None,
    sandbox_workspace: str | None = None,
    settings: Settings | None = None,
) -> str | None:
    """合并生成一条系统提示词（含人格 / 项目上下文 / 沙箱工作目录 / 技能 / 记忆 / 用户画像）。

    各块按以下**注入顺序**拼装（顺序即优先级呈现，影响 LLM 对提示的权重）：

      1. ``<identity>``    SOUL.md 人格（放在**最前**，作为基底身份）；
      2. user_system       调用方显式传入的附加系统提示词；
      3. ``<project-context>`` 项目上下文文件（受 settings.context_files_enabled 开关）；
      4. ``<shell-workspace>`` per-run 沙箱会话目录（仅在其**真正生效**时注入；见
                           ``sandbox_workspace``）——让模型知道 shell 命令的工作目录在哪，
                           避免 shell 写入位置与 file 工具的相对路径假设分叉（E40-D2）；
      5. ``<skills>``      按 prompt 相似度自动匹配的技能（命中则注入内容；未命中但
                           存在技能时给一条引导提示）；
      6. ``<memory>``      facts 长期记忆；若开启 memory_nudge 再追加 ``<memory-nudge>`` 提醒；
      7. ``<profile>``     用户画像。

    无任何内容时返回 None（不插入空 SYSTEM 消息）。``prompt`` 仅用于技能相似度匹配。

    ``sandbox_workspace`` 为「本 run 的 shell 工作目录」绝对路径；未绑定（或有开关但无真实
    沙箱后端）时传 None——**不可在未生效时报路径**，否则提示词与真实 cwd 不一致，比不提示更坏。

    ``settings``：运行配置快照（Phase 1，由 loop 传入）；缺省回退全局 Settings（仅供直接调用的
    测试/外部脚本，运行中路径必须显式传快照）。
    """
    blocks: list[str | None] = [
        _identity_block(soul),
        user_system,
        _project_context_block(context_dir, settings),
        _shell_workspace_block(sandbox_workspace),
        _skills_block(skills, prompt, settings),
        _memory_block(facts),
        _memory_nudge_block(facts, settings),
        _profile_block(profile),
    ]
    parts = [block for block in blocks if block]
    return "\n\n".join(parts) if parts else None


def _identity_block(soul: SoulStore | None) -> str | None:
    """``<identity>``：SOUL.md 人格（基底身份，故列在块列表最前）。"""
    if not soul:
        return None
    soul_content = soul.load()
    if not soul_content:
        return None
    logger.debug("Injected SOUL.md personality into system prompt")
    return f"<identity>\n{soul_content}\n</identity>"


def _project_context_block(context_dir: str | None, settings: Settings | None = None) -> str | None:
    """``<project-context>``：分层发现的上下文文件（受 ``context_files_enabled`` 开关）。"""
    if not context_dir:
        return None
    settings = settings or get_settings()
    if not settings.context_files_enabled:
        return None
    from heagent.context.loader import load_context_files

    # 显式传快照值：运行中不再由 loader 回读全局设置（Phase 1）。
    context = load_context_files(
        context_dir,
        max_bytes=settings.context_files_max_bytes,
        user_level=settings.context_files_user_level,
    )
    if not context:
        return None
    logger.debug("Injected project context files into system prompt")
    return f"<project-context>\n{context}\n</project-context>"


def _shell_workspace_block(sandbox_workspace: str | None) -> str | None:
    """``<shell-workspace>``：per-run shell 工作目录（仅**真正生效**时注入）。

    E40-D2：这是该目录暴露给模型的**唯一**通道（system prompt），而非 tool schema / result
    ——单一来源避免两处说法漂移。
    """
    if not sandbox_workspace:
        return None
    logger.debug("Injected per-run shell workspace into system prompt: %s", sandbox_workspace)
    return (
        "<shell-workspace>\n"
        "Shell commands in this run start in this directory and keep their working directory "
        "across commands:\n"
        f"{sandbox_workspace}\n\n"
        "It is per-run scratch space. Relative paths in file tools resolve against the workspace "
        "root instead, so pass an absolute path when a shell command and a file tool must touch "
        "the same file.\n"
        "</shell-workspace>"
    )


def _skills_block(skills: SkillStore | None, prompt: str, settings: Settings | None = None) -> str | None:
    """``<skills>``：按 prompt 相似度匹配并注入技能正文（含 ``record_usage`` 副作用）。

    命中技能时按 ``skill_max_auto_invoke`` 限制条数、按 ``skill_max_auto_invoke_tokens``
    限制累计预算；未命中但技能库非空时退化为一条引导提示。
    """
    if not skills:
        return None
    settings = settings or get_settings()
    candidates = skills.match_skill_details(prompt, threshold=settings.skill_match_threshold)
    matched: list[str] = []
    contents: list[str] = []
    used_tokens = 0
    for candidate in candidates:
        if len(matched) >= settings.skill_max_auto_invoke:
            break
        raw = skills.load(candidate.name)
        if not raw:
            continue
        cost = estimate_text_tokens(raw)
        budget = settings.skill_max_auto_invoke_tokens
        if budget is not None and used_tokens + cost > budget:
            logger.debug("Skipped skill %s: estimated token budget exceeded", candidate.name)
            continue
        matched.append(candidate.name)
        contents.append(raw)
        used_tokens += cost

    if matched:
        # 只记录最终注入的技能，避免预算跳过项被误记为使用。
        for skill_name in matched:
            skills.record_usage(skill_name)
        if not contents:
            return None
        block = "\n\n---\n\n".join(contents)
        logger.debug("Auto-invoked %d skill(s): %s", len(matched), matched)
        return (
            "<skills>\n"
            "The following skills are relevant to the user's request:\n\n"
            f"{block}\n\n"
            "You can use skill_list to see all skills, skill_load to read one by name, "
            "skill_create to add new ones, or skill_update to modify.\n"
            "</skills>"
        )

    if not skills.list_skills():
        return None
    # 未命中但技能库非空：给一条引导，提示用户可手动创建/浏览技能。
    return (
        "<skills>\n"
        "No skills matched the current request. "
        "You can use skill_create to save reusable patterns, skill_list to browse existing skills, "
        "skill_load to read one by name, or skill_update to refine them.\n"
        "</skills>"
    )


def _memory_block(facts: FactStore | None) -> str | None:
    """``<memory>``：facts 长期记忆条目。"""
    if not facts:
        return None
    facts_list = facts.load()
    if not facts_list:
        return None
    items = "\n".join(f"- {fact}" for fact in facts_list)
    logger.debug("Injected %d fact(s) into system prompt", len(facts_list))
    return f"<memory>\nThe following facts are remembered from previous conversations:\n\n{items}\n</memory>"


def _memory_nudge_block(facts: FactStore | None, settings: Settings | None = None) -> str | None:
    """``<memory-nudge>``：提醒模型主动落盘长期事实（受 ``memory_nudge_enabled`` 开关）。

    与 ``<memory>`` 是两个独立块：此块**不**依赖是否已有 facts，只依赖开关与 facts 存储是否可用。
    """
    if not facts:
        return None
    if not (settings or get_settings()).memory_nudge_enabled:
        return None
    return (
        "<memory-nudge>\n"
        "After completing a complex task or learning something important, "
        "consider using fact_add to save key insights for future sessions.\n"
        "</memory-nudge>"
    )


def _profile_block(profile: ProfileStore | None) -> str | None:
    """``<profile>``：用户画像。"""
    if not profile:
        return None
    profile_text = profile.load()
    if not profile_text:
        return None
    logger.debug("Injected user profile into system prompt")
    return f"<profile>\nUser profile (adapt your responses accordingly):\n\n{profile_text}\n</profile>"
