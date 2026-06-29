"""系统提示词拼装 —— 把人格 / 项目上下文 / 技能 / 记忆 / 画像合并成一条 SYSTEM 提示词。

从 ``AgentLoop`` 抽出的纯函数（无循环、无 async、无 engine 依赖），供
``AgentLoop._build_system`` 薄包装调用，使 ``loop.py`` 聚焦于「LLM ↔ 工具循环」。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.config import get_settings

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
) -> str | None:
    """合并生成一条系统提示词（含人格 / 项目上下文 / 技能 / 记忆 / 用户画像）。

    各块按以下**注入顺序**拼装（顺序即优先级呈现，影响 LLM 对提示的权重）：

      1. ``<identity>``    SOUL.md 人格（用 insert(0) 放到**最前**，作为基底身份）；
      2. user_system       调用方显式传入的附加系统提示词；
      3. ``<project-context>`` 项目上下文文件（受 settings.context_files_enabled 开关）；
      4. ``<skills>``      按 prompt 相似度自动匹配的技能（命中则注入内容；未命中但
                           存在技能时给一条引导提示）；
      5. ``<memory>``      facts 长期记忆；若开启 memory_nudge 再追加 ``<memory-nudge>`` 提醒；
      6. ``<profile>``     用户画像。

    无任何内容时返回 None（不插入空 SYSTEM 消息）。``prompt`` 仅用于技能相似度匹配。
    """
    parts: list[str] = []
    if user_system:
        parts.append(user_system)

    if soul:
        soul_content = soul.load()
        if soul_content:
            # insert(0)：把人格放到系统提示词最前，确立基底身份。
            parts.insert(0, f"<identity>\n{soul_content}\n</identity>")
            logger.debug("Injected SOUL.md personality into system prompt")

    if context_dir:
        settings = get_settings()
        if settings.context_files_enabled:
            from heagent.context.loader import load_context_files

            context = load_context_files(context_dir)
            if context:
                parts.append(f"<project-context>\n{context}\n</project-context>")
                logger.debug("Injected project context files into system prompt")

    if skills:
        settings = get_settings()
        # 按相似度匹配技能，截断到 skill_max_auto_invoke 上限，避免注入过多。
        matched = skills.matching_skills(
            prompt,
            threshold=settings.skill_match_threshold,
        )[: settings.skill_max_auto_invoke]

        if matched:
            # 命中：先记录用法（影响后续排序），再拼装技能正文。
            for skill_name in matched:
                skills.record_usage(skill_name)
            contents: list[str] = []
            for name in matched:
                raw = skills.load(name)
                if raw:
                    contents.append(raw)
            if contents:
                block = "\n\n---\n\n".join(contents)
                parts.append(
                    "<skills>\n"
                    "The following skills are relevant to the user's request:\n\n"
                    f"{block}\n\n"
                    "You can use skill_list to see all skills, "
                    "skill_create to add new ones, or skill_update to modify.\n"
                    "</skills>"
                )
                logger.debug("Auto-invoked %d skill(s): %s", len(matched), matched)
        elif skills.list_skills():
            # 未命中但技能库非空：给一条引导，提示用户可手动创建/浏览技能。
            parts.append(
                "<skills>\n"
                "No skills matched the current request. "
                "You can use skill_create to save reusable patterns, "
                "skill_list to browse existing skills, or skill_update to refine them.\n"
                "</skills>"
            )

    if facts:
        facts_list = facts.load()
        if facts_list:
            items = "\n".join(f"- {fact}" for fact in facts_list)
            parts.append(
                f"<memory>\nThe following facts are remembered from previous conversations:\n\n{items}\n</memory>"
            )
            logger.debug("Injected %d fact(s) into system prompt", len(facts_list))

    if facts and get_settings().memory_nudge_enabled:
        parts.append(
            "<memory-nudge>\n"
            "After completing a complex task or learning something important, "
            "consider using fact_add to save key insights for future sessions.\n"
            "</memory-nudge>"
        )

    if profile:
        profile_text = profile.load()
        if profile_text:
            parts.append(f"<profile>\nUser profile (adapt your responses accordingly):\n\n{profile_text}\n</profile>")
            logger.debug("Injected user profile into system prompt")

    return "\n\n".join(parts) if parts else None
