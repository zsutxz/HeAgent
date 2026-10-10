"""仓库内**受跟踪**技能的自动匹配契约。

为什么需要：技能是「靠自然语言触发」的资产——匹配器把 `pattern + tags` 揉成词元袋做**分母**，
`triggers` 命中则直接给 score=1.0。2026-09-28 实测：`code_review` 当时**没有** `triggers`，
「帮我评审一下这段代码，找找边界情况」**零命中**（中文提示词与英文字 tag 交集为空 ⇒ 比值远低于 0.3
阈值）⇒ 该技能只能用 `skill_load` 显式点名，自动注入永远不会发生。

这些用例读的是**真实仓库路径**（`.heagent/skills/`），而不是 tmp 夹具：夹具自造「约定路径」的写法
会让「文件改名 / 字段丢失」两类漂移长期无人发现。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.skills.skill_store import SkillStore

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".heagent" / "skills"
THRESHOLD = 0.3

#: 仓库内必须能被自然语言命中的技能 → 一条代表性提示词（triggers 命中即 1.0）。
AUTO_MATCH_CASES = {
    "code_review": "帮我评审一下这段代码，找找边界情况",
    "karpathy-guidelines": "帮我重构，注意别过度设计",
    "he-goal": "我要做一个完整的项目，从需求到交付",
}


def _matches(prompt: str) -> set[str]:
    return {m.name for m in SkillStore(str(SKILLS_DIR)).match_skill_details(prompt, THRESHOLD)}


@pytest.mark.parametrize(("skill_id", "prompt"), sorted(AUTO_MATCH_CASES.items()))
def test_tracked_skill_is_matched_by_its_natural_language_prompt(skill_id: str, prompt: str) -> None:
    """缺 `triggers` 的技能在自然语言下**必然** miss（分母是 `pattern + tags` 的词元袋）。"""
    if not (SKILLS_DIR / skill_id / "SKILL.md").is_file():
        pytest.skip(f"{skill_id} 不在本工作区（未跟踪的本地技能不进 CI）")

    assert skill_id in _matches(prompt), f"{skill_id} 未被自然语言命中（triggers 缺失或写错？）"


@pytest.mark.parametrize(
    ("prompt", "forbidden"),
    [
        ("帮我评审一下这段代码，找找边界情况", "he-goal"),
        ("帮我重构，注意别过度设计", "he-goal"),
    ],
)
def test_negative_triggers_keep_the_workflow_skill_out(prompt: str, forbidden: str) -> None:
    """`he-goal` 的 `negative_triggers`（代码评审 / 重构 / code review）必须挡住这类提示词。

    工作流契约有 5 KB 量级，被无关提示词自动注入会白占预算并误导行为——负向触发是它的护栏。
    """
    if not (SKILLS_DIR / forbidden / "SKILL.md").is_file():
        pytest.skip(f"{forbidden} 不在本工作区")

    assert forbidden not in _matches(prompt), f"{forbidden} 不该被这条提示词注入"
