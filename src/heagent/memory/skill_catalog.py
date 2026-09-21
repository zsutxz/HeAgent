"""技能检索（memory/skills 拆分层，Phase 4 C4）。

基于关键词/触发词的可解释匹配与过期盘点：:func:`match_skill_details` /
:func:`matching_skills` / :func:`stale_skills`。均为以 :class:`~heagent.memory.skill_store.SkillStore`
为数据源的纯检索函数（本模块只经 TYPE_CHECKING 引用存储类型，依赖单向）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from heagent.memory.skill_models import SkillMatch

if TYPE_CHECKING:
    from heagent.memory.skill_store import SkillStore


def skill_tokens(text: str) -> set[str]:
    """Dependency-free mixed-language tokens with CJK bigrams/trigrams."""
    chunks = re.findall(r"[a-zA-Z0-9_]+|[㐀-鿿぀-ヿ가-힯]+", text.casefold())
    tokens: set[str] = set()
    for chunk in chunks:
        if not re.fullmatch(r"[㐀-鿿぀-ヿ가-힯]+", chunk):
            tokens.add(chunk)
            continue
        # Whole CJK runs depend on whitespace boundaries and make coverage unfair:
        # use only two/three-character evidence, excluding low-signal single characters.
        for size in (2, 3):
            tokens.update(chunk[i : i + size] for i in range(len(chunk) - size + 1))
    return tokens


def match_skill_details(store: SkillStore, prompt: str, threshold: float) -> list[SkillMatch]:
    """Return explainable, backward-compatible skill matches."""
    if not prompt.strip():
        return []
    prompt_text = prompt.casefold()
    prompt_tokens = skill_tokens(prompt)
    matches: list[SkillMatch] = []
    for name in store.list_skills():
        parsed = store.parse(name)
        if parsed is None:
            continue
        if any(trigger.casefold() in prompt_text for trigger in parsed.negative_triggers):
            continue
        pattern_tokens = skill_tokens(f"{parsed.pattern} {' '.join(parsed.tags)}")
        matched_triggers = [t for t in parsed.triggers if t.casefold() in prompt_text]
        trigger_hit = bool(matched_triggers)
        if not pattern_tokens and not trigger_hit:
            continue
        overlap = len(prompt_tokens & pattern_tokens)
        ratio = overlap / len(pattern_tokens) if pattern_tokens else 0.0
        # Explicit triggers are high-confidence; ordinary matching retains the old threshold semantics.
        score = 1.0 if trigger_hit else ratio
        if score >= threshold:
            matches.append(
                SkillMatch(name=name, score=score, priority=parsed.priority, matched_triggers=matched_triggers)
            )
    matches.sort(key=lambda item: (-bool(item.matched_triggers), -item.score, -item.priority, item.name))
    return matches


def matching_skills(store: SkillStore, prompt: str, threshold: float) -> list[str]:
    """Return matching names; retained as the legacy public API."""
    return [match.name for match in match_skill_details(store, prompt, threshold)]


def stale_skills(store: SkillStore, days: int = 30) -> list[str]:
    """返回超过 N 天未使用的技能名称列表。"""
    cutoff = datetime.now() - timedelta(days=days)
    stale: list[str] = []
    for name in store.list_skills():
        parsed = store.parse(name)
        if parsed is None:
            continue
        if parsed.usage_count == 0:
            stale.append(name)
        elif parsed.last_used:
            try:
                last = datetime.fromisoformat(parsed.last_used)
                if last < cutoff:
                    stale.append(name)
            except ValueError:
                pass
    return stale
