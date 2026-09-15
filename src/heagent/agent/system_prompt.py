"""系统提示词拼装 —— 把人格 / 项目上下文 / 技能 / 记忆 / 画像合并成一条 SYSTEM 提示词。

从 ``AgentLoop`` 抽出的纯函数（无循环、无 async、无 engine 依赖），供
``AgentLoop._build_system`` 薄包装调用，使 ``loop.py`` 聚焦于「LLM ↔ 工具循环」。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.config import get_settings
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
) -> str | None:
    """合并生成一条系统提示词（含人格 / 项目上下文 / 沙箱工作目录 / 技能 / 记忆 / 用户画像）。

    各块按以下**注入顺序**拼装（顺序即优先级呈现，影响 LLM 对提示的权重）：

      1. ``<identity>``    SOUL.md 人格（用 insert(0) 放到**最前**，作为基底身份）；
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

    if sandbox_workspace:
        # E40-D2：把 per-run shell 工作目录显式告诉模型。这是**唯一**的暴露通道
        # （system prompt），而非 tool schema / result——单一来源避免两处说法漂移。
        parts.append(
            "<shell-workspace>\n"
            "Shell commands in this run start in this directory and keep their working directory "
            "across commands:\n"
            f"{sandbox_workspace}\n\n"
            "It is per-run scratch space. Relative paths in file tools resolve against the workspace "
            "root instead, so pass an absolute path when a shell command and a file tool must touch "
            "the same file.\n"
            "</shell-workspace>"
        )
        logger.debug("Injected per-run shell workspace into system prompt: %s", sandbox_workspace)

    if skills:
        settings = get_settings()
        # 按相似度匹配技能，截断到 skill_max_auto_invoke 上限，避免注入过多。
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
            if contents:
                block = "\n\n---\n\n".join(contents)
                parts.append(
                    "<skills>\n"
                    "The following skills are relevant to the user's request:\n\n"
                    f"{block}\n\n"
                    "You can use skill_list to see all skills, skill_load to read one by name, "
                    "skill_create to add new ones, or skill_update to modify.\n"
                    "</skills>"
                )
                logger.debug("Auto-invoked %d skill(s): %s", len(matched), matched)
        elif skills.list_skills():
            # 未命中但技能库非空：给一条引导，提示用户可手动创建/浏览技能。
            parts.append(
                "<skills>\n"
                "No skills matched the current request. "
                "You can use skill_create to save reusable patterns, skill_list to browse existing skills, "
                "skill_load to read one by name, or skill_update to refine them.\n"
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
