"""Story 66.3：技能匹配的批量预计算（``SkillMatchIndex`` / ``build_skill_index``）。

三条硬判据：
- **等价性**：新实现与「逐 prompt 逐技能 parse」的参照实现（本文件复刻旧逻辑）在名称、
  score、priority、matched_triggers 上逐条相等 —— 等价性用例即回归锁。
- **批量效果**：M 个技能 × N 个不同 prompt，``store.parse`` 总调用次数 = M（不再是 M×N）。
- **不影响启动**：索引只在**首次匹配**时构建，构造 ``SkillStore`` 时不 parse。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.skills.skill_catalog import (
    SkillIndexEntry,
    SkillMatchIndex,
    build_skill_index,
    match_skill_details,
    skill_tokens,
)
from heagent.skills.skill_meta import SkillMetaError
from heagent.skills.skill_models import SkillContent, SkillMatch
from heagent.skills.skill_store import SkillStore

ROOT = Path(__file__).resolve().parents[1]
REPO_SKILLS_DIR = ROOT / ".heagent" / "skills"


class CountingStore(SkillStore):
    """``parse`` 调用计数替身。"""

    def __init__(self, base_dir: str | Path) -> None:
        super().__init__(base_dir)
        self.parse_calls = 0

    def parse(self, name: str) -> SkillContent | None:
        self.parse_calls += 1
        return super().parse(name)


def reference_match_details(store: SkillStore, prompt: str, threshold: float) -> list[SkillMatch]:
    """旧实现逐字复刻（每个 prompt 对每个技能 parse 一次）——等价性的对照组。"""
    if not prompt.strip():
        return []
    prompt_text = prompt.casefold()
    prompt_tokens = skill_tokens(prompt)
    matches: list[SkillMatch] = []
    for name in store.list_skills():
        try:
            parsed = store.parse(name)
        except SkillMetaError:
            continue
        if parsed is None:
            continue
        if not parsed.model_invocable:
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
        score = 1.0 if trigger_hit else ratio
        if score >= threshold:
            matches.append(
                SkillMatch(name=name, score=score, priority=parsed.priority, matched_triggers=matched_triggers)
            )
    matches.sort(key=lambda item: (-bool(item.matched_triggers), -item.score, -item.priority, item.name))
    return matches


def projection(matches: list[SkillMatch]) -> list[tuple[str, float, int, list[str]]]:
    return [(m.name, m.score, m.priority, list(m.matched_triggers)) for m in matches]


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = "",
    pattern: str = "",
    triggers: list[str] | None = None,
    negative_triggers: list[str] | None = None,
    meta_extra: str = "",
    steps: list[str] | None = None,
) -> None:
    SkillStore(root).save(
        name=name,
        description=description or name,
        pattern=pattern,
        steps=steps or ["step one"],
        triggers=triggers or [],
        negative_triggers=negative_triggers or [],
    )
    if meta_extra:
        (root / name / "meta.yaml").write_text(meta_extra, encoding="utf-8", newline="\n")


@pytest.fixture()
def library(tmp_path: Path) -> CountingStore:
    """覆盖匹配分支的技能库：triggers / CJK / 负向触发 / 不可自动注入 / 旧格式残留 / 同分。"""
    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(
        root,
        "deploy_flow",
        description="deploy",
        pattern="deploy to production server",
        triggers=["发布上线", "ship it"],
        steps=["run deploy", "verify"],
    )
    _write_skill(
        root,
        "code_review_flow",
        description="review",
        pattern="code review boundaries and edge cases",
        triggers=["代码评审"],
        negative_triggers=["重构"],
    )
    _write_skill(
        root,
        "cjk_flow",
        description="cjk",
        pattern="数据库迁移 保持向后兼容",
        triggers=["迁移数据库"],
    )
    _write_skill(root, "trigger_only", description="only triggers", pattern="", triggers=["紧急回滚"])
    _write_skill(
        root,
        "review_alt",
        description="same pattern as code_review_flow",
        pattern="code review boundaries and edge cases",
        triggers=[],
    )
    _write_skill(root, "quiet_flow", description="quiet", pattern="deploy unrelated wording")
    _write_skill(
        root, "manual_flow", description="manual only", pattern="deploy manual", meta_extra="model_invocable: false\n"
    )
    # 旧格式残留：meta 契约键还写在 SKILL.md frontmatter 里 ⇒ 两边都告警后跳过。
    legacy = root / "legacy_flow"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text(
        "---\nname: legacy_flow\ndescription: legacy\nusage_count: 3\n---\n"
        "\n## Pattern\ndeploy legacy\n\n## Steps\n1. x\n",
        encoding="utf-8",
    )
    store = CountingStore(root)
    store.parse_calls = 0
    return store


PROMPTS = [
    "deploy to production server please",
    "帮我发布上线这个服务",
    "ship it now",
    "帮我评审一下这段代码，找找边界情况",
    "帮我重构，注意别过度设计",
    "数据库迁移要小心",
    "迁移数据库",
    "紧急回滚线上故障",
    "code review boundaries",
    "no match at all here",
]


class TestEquivalence:
    @pytest.mark.parametrize("threshold", [0.0, 0.3, 0.5, 0.8, 1.0])
    @pytest.mark.parametrize("prompt", PROMPTS)
    def test_matches_are_identical_to_the_reference(
        self, library: CountingStore, prompt: str, threshold: float
    ) -> None:
        expected = projection(reference_match_details(library, prompt, threshold))
        actual = projection(match_skill_details(library, prompt, threshold))

        assert actual == expected

    def test_repo_skill_library_is_equivalent(self) -> None:
        """真实 ``.heagent/skills``（47+ 包）上同样逐条相等；目录缺失时跳过（该目录不入库）。"""
        if not REPO_SKILLS_DIR.is_dir():
            pytest.skip(".heagent/skills 不在本工作区")
        store = SkillStore(REPO_SKILLS_DIR)
        for prompt in ("帮我评审一下这段代码", "我要做一个完整的项目，从需求到交付", "统计模型用量"):
            for threshold in (0.3, 0.6):
                assert projection(match_skill_details(store, prompt, threshold)) == projection(
                    reference_match_details(store, prompt, threshold)
                )

    def test_matched_triggers_keep_original_casing_and_order(self, library: CountingStore) -> None:
        matches = match_skill_details(library, "Ship It 与 发布上线 都要", 0.3)

        by_name = {m.name: m for m in matches}
        assert by_name["deploy_flow"].matched_triggers == ["发布上线", "ship it"]
        assert by_name["deploy_flow"].score == 1.0


class TestBatchPrecompute:
    def test_parse_calls_equal_skill_count_for_many_prompts(self, library: CountingStore) -> None:
        skill_count = len(library.list_skills())

        for prompt in PROMPTS:
            match_skill_details(library, prompt, 0.3)

        assert skill_count > 1, "夹具太小，计数断言没有意义"
        assert library.parse_calls == skill_count, "M 技能 × N prompt 的 parse 次数应为 M"

    def test_constructing_the_store_parses_nothing(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        root.mkdir()
        _write_skill(root, "one_flow", pattern="deploy one")

        store = CountingStore(root)

        assert store.parse_calls == 0
        assert len(store.match_cache.index) == 0
        assert store.list_skills() == ["one_flow"]
        assert store.parse_calls == 0

    def test_index_is_built_on_first_match_only(self, library: CountingStore) -> None:
        assert len(library.match_cache.index) == 0

        match_skill_details(library, "deploy", 0.3)

        assert len(library.match_cache.index) == 1
        assert len(library.match_cache.results) == 1

    def test_index_skips_non_invocable_and_legacy_skills(self, library: CountingStore) -> None:
        names = {entry.name for entry in build_skill_index(library).entries}

        assert "manual_flow" not in names, "model_invocable: false 不进自动匹配索引"
        assert "legacy_flow" not in names, "旧格式残留（SkillMetaError）跳过"
        assert {"deploy_flow", "cjk_flow", "trigger_only"} <= names

    def test_index_entries_carry_the_prompt_independent_features(self, library: CountingStore) -> None:
        index = build_skill_index(library)
        by_name = {entry.name: entry for entry in index.entries}

        entry = by_name["code_review_flow"]
        assert isinstance(entry, SkillIndexEntry)
        assert "代码评审" in entry.triggers
        assert "代码评审" in entry.triggers_folded
        assert "重构" in entry.negative_triggers_folded
        assert skill_tokens("code review boundaries and edge cases review") >= entry.pattern_tokens

    def test_fingerprint_matches_the_library_state(self, library: CountingStore) -> None:
        index = build_skill_index(library)

        assert isinstance(index, SkillMatchIndex)
        assert index.fingerprint
        assert index.fingerprint == build_skill_index(library).fingerprint, "同一文件状态 ⇒ 同一指纹"
