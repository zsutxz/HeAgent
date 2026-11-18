"""Story 66.2：技能匹配结果缓存（key = 技能库指纹 + prompt + threshold）。

判据分三层：
- **计数**（主判据）：同一 prompt 第二次匹配 ``SkillStore.parse`` 调用数为 0；
  改动任一技能的 ``SKILL.md`` / ``meta.yaml`` 后指纹变化 ⇒ 下一次匹配重新解析。
- **指纹**：只覆盖文件状态（name/mtime_ns/size），不读内容；增删技能也会换指纹。
- **提速**（``-m benchmark``，默认门禁不跑）：同 prompt 重复匹配显著快于冷启动。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from heagent.skills.skill_catalog import (
    DEFAULT_MATCH_CACHE_ENTRIES,
    SkillMatchCache,
    skill_library_fingerprint,
)
from heagent.skills.skill_store import SkillStore

if TYPE_CHECKING:
    from heagent.skills.skill_models import SkillContent

THRESHOLD = 0.3


class CountingStore(SkillStore):
    """``parse`` 调用计数替身：缓存命中判据只认这个数字。"""

    def __init__(self, base_dir: str | Path) -> None:
        super().__init__(base_dir)
        self.parse_calls = 0
        self.parsed_names: list[str] = []

    def parse(self, name: str) -> SkillContent | None:
        self.parse_calls += 1
        self.parsed_names.append(name)
        return super().parse(name)


def _seed(store: SkillStore, count: int = 3) -> None:
    for index in range(count):
        store.save(
            name=f"skill_{index}",
            description=f"Skill {index}",
            pattern=f"deploy keyword {index}",
            steps=["step one"],
            tags=["deploy"],
            triggers=[f"trigger{index}"],
        )


@pytest.fixture()
def store(tmp_path: Path) -> CountingStore:
    counting = CountingStore(tmp_path / "skills")
    _seed(counting)
    counting.parse_calls = 0
    counting.parsed_names.clear()
    return counting


class TestMatchResultCache:
    def test_second_match_of_same_prompt_parses_nothing(self, store: CountingStore) -> None:
        first = store.match_skill_details("deploy keyword 0", THRESHOLD)
        cold_parses = store.parse_calls

        second = store.match_skill_details("deploy keyword 0", THRESHOLD)

        assert cold_parses > 0, "冷启动必须真解析过技能库（否则计数断言没意义）"
        assert store.parse_calls == cold_parses, "同 prompt 第二次匹配不该再 parse"
        assert second == first

    def test_different_prompt_still_hits_the_cached_index(self, store: CountingStore) -> None:
        """索引与 prompt 无关：换 prompt 不重新解析，只是重新做集合运算。"""
        store.match_skill_details("deploy keyword 0", THRESHOLD)
        cold_parses = store.parse_calls

        store.match_skill_details("deploy keyword 1", THRESHOLD)
        store.match_skill_details("trigger2", THRESHOLD)

        assert store.parse_calls == cold_parses

    def test_different_threshold_is_a_separate_cache_slot(self, store: CountingStore) -> None:
        store.match_skill_details("deploy keyword 0", 0.3)
        cold_parses = store.parse_calls

        store.match_skill_details("deploy keyword 0", 0.9)

        # 结果缓存按 threshold 分槽（未命中），但索引仍然命中 ⇒ 零 parse。
        assert store.parse_calls == cold_parses
        assert len(store.match_cache.results) == 2

    def test_cached_list_is_isolated_from_caller_mutation(self, store: CountingStore) -> None:
        store.match_skill_details("deploy keyword 0", THRESHOLD)
        leaked = store.match_skill_details("deploy keyword 0", THRESHOLD)
        leaked.clear()

        again = store.match_skill_details("deploy keyword 0", THRESHOLD)

        assert again, "调用方清空返回列表不得影响缓存载荷"

    def test_result_cache_short_circuits_even_without_an_index(self, store: CountingStore) -> None:
        """66.2 的判据独立成立：丢掉索引缓存后，结果缓存本身仍让重复匹配零 parse。"""
        store.match_skill_details("deploy keyword 2", THRESHOLD)
        store.parse_calls = 0
        store.match_cache.index.clear()

        store.match_skill_details("deploy keyword 2", THRESHOLD)

        assert store.parse_calls == 0

    def test_empty_prompt_short_circuits_without_touching_the_library(self, store: CountingStore) -> None:
        assert store.match_skill_details("   ", THRESHOLD) == []
        assert store.parse_calls == 0
        assert len(store.match_cache.results) == 0


class TestFingerprintInvalidation:
    def test_skill_md_rewrite_invalidates_cache(self, store: CountingStore) -> None:
        store.match_skill_details("deploy keyword 0", THRESHOLD)
        before = skill_library_fingerprint(store)
        skill_md = store.authoring_root / "skill_0" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8").replace("deploy", "release"), encoding="utf-8", newline="\n"
        )

        assert skill_library_fingerprint(store) != before, "SKILL.md 被改写后指纹必须变"
        store.parse_calls = 0
        store.match_skill_details("deploy keyword 0", THRESHOLD)

        assert store.parse_calls > 0, "指纹变化 ⇒ 缓存失效 ⇒ 重新解析"

    def test_meta_yaml_rewrite_invalidates_cache(self, store: CountingStore) -> None:
        """``record_usage`` 与 ``update`` 都只回写 meta.yaml——它必须同样能失效缓存。"""
        store.match_skill_details("deploy keyword 0", THRESHOLD)
        before = skill_library_fingerprint(store)
        meta = store.authoring_root / "skill_0" / "meta.yaml"
        meta.write_text("model_invocable: false\n", encoding="utf-8", newline="\n")

        assert skill_library_fingerprint(store) != before
        store.parse_calls = 0
        names = [match.name for match in store.match_skill_details("deploy keyword 0", THRESHOLD)]

        assert store.parse_calls > 0
        assert "skill_0" not in names, "失效后必须看到新的 model_invocable: false"

    def test_record_usage_rewrites_meta_and_invalidates(self, store: CountingStore) -> None:
        store.match_skill_details("trigger1", THRESHOLD)
        before = skill_library_fingerprint(store)

        store.record_usage("skill_1")

        assert skill_library_fingerprint(store) != before
        store.parse_calls = 0
        store.match_skill_details("trigger1", THRESHOLD)
        assert store.parse_calls > 0

    def test_adding_and_removing_skills_changes_the_fingerprint(self, store: CountingStore) -> None:
        before = skill_library_fingerprint(store)
        store.save(name="extra_skill", description="Extra", pattern="extra pattern", steps=["s"])

        added = skill_library_fingerprint(store)
        assert added != before

        store.delete("extra_skill")
        assert skill_library_fingerprint(store) != added

    def test_fingerprint_depends_only_on_file_state(self, store: CountingStore) -> None:
        """指纹只由文件状态决定，不含实例身份 ⇒ 新实例（同一目录）算出同一个值。"""
        assert skill_library_fingerprint(store) == skill_library_fingerprint(SkillStore(store.roots[0]))


class TestCacheShape:
    def test_default_capacity_is_32_results(self) -> None:
        assert DEFAULT_MATCH_CACHE_ENTRIES == 32
        cache = SkillMatchCache()
        assert len(cache.results) == 0
        assert len(cache.index) == 0

    def test_result_cache_is_lru_bounded(self, store: CountingStore) -> None:
        """超出容量按最久未用淘汰；命中会刷新位序。"""
        store.match_cache = SkillMatchCache(results=2)
        store.match_skill_details("deploy keyword 0", THRESHOLD)
        store.match_skill_details("deploy keyword 1", THRESHOLD)
        store.match_skill_details("deploy keyword 0", THRESHOLD)  # 刷新 0 的位序
        store.match_skill_details("deploy keyword 2", THRESHOLD)

        assert len(store.match_cache.results) == 2
        store.parse_calls = 0
        store.match_skill_details("deploy keyword 0", THRESHOLD)
        assert store.parse_calls == 0, "刚命中过的槽位不该被淘汰"

        store.match_skill_details("deploy keyword 1", THRESHOLD)
        assert store.parse_calls == 0, "索引仍在缓存 ⇒ 换 prompt 也只是重新做集合运算"
        assert len(store.match_cache.results) == 2

    def test_constructing_store_does_not_scan_the_library(self, tmp_path: Path) -> None:
        _seed(CountingStore(tmp_path / "skills"))

        fresh = CountingStore(tmp_path / "skills")

        assert fresh.parse_calls == 0
        assert len(fresh.match_cache.results) == 0
        assert len(fresh.match_cache.index) == 0


@pytest.mark.benchmark
class TestMatchCacheSpeedup:
    """``-m benchmark``：同 prompt 重复匹配（命中）vs 冷启动（未命中）的耗时比值。"""

    def test_cached_match_is_at_least_30_percent_faster(self, tmp_path: Path) -> None:
        store = SkillStore(tmp_path / "skills")
        for index in range(40):
            store.save(
                name=f"bench_skill_{index}",
                description=f"Skill {index}",
                pattern=f"deploy keyword {index} alpha beta gamma",
                steps=["step one"],
                tags=["deploy", "benchmark"],
            )

        def median_seconds(action) -> float:  # type: ignore[no-untyped-def]
            samples = []
            for _ in range(7):
                started = time.perf_counter()
                action()
                samples.append(time.perf_counter() - started)
            samples.sort()
            return samples[len(samples) // 2]

        def cold() -> None:
            store.match_cache = SkillMatchCache()  # 清空 ⇒ 下一轮必然重建索引 + 结果
            store.match_skill_details("deploy keyword 7", THRESHOLD)

        def warm() -> None:
            store.match_skill_details("deploy keyword 7", THRESHOLD)

        warm_seconds = median_seconds(warm)
        cold_seconds = median_seconds(cold)

        assert warm_seconds < cold_seconds * 0.7, (
            f"缓存命中应至少快 30%：warm={warm_seconds:.6f}s cold={cold_seconds:.6f}s"
        )
