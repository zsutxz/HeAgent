"""缓存容量配置键与 ``DEBUG_MODE`` 命中率出口（台账 A59 闭合判据）。

三件事各有一组断言：

- **配置面**：``PROVIDER_METADATA_CACHE_SIZE`` / ``SKILL_*_CACHE_ENTRIES`` 三个键存在、
  默认值与代码常量对齐（配置面不依赖 providers/skills，故是两处字面量，靠本用例钉一致）、
  非正值被 pydantic 拒。
- **装配面**：聚合层缓存容量真按 Settings 值构造（经 ``composition._cache_size`` 单点读取，
  不在四个构造点各读配置）。
- **出口面**：``log_metadata_cache_stats`` 在 debug 开时**恰一条**日志、关时零输出；栈里没有
  聚合层时同样零输出（单 provider 直返是常见形态，不能刷噪声）。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from heagent.config import Settings
from heagent.providers.base import ProviderMetadata
from heagent.providers.cache_report import collect_metadata_caches, log_metadata_cache_stats
from heagent.providers.composition import _cache_size
from heagent.providers.metadata_cache import DEFAULT_MAX_SIZE, ProviderMetadataCache
from heagent.providers.switchable import SwitchableProvider
from heagent.skills.skill_catalog import DEFAULT_MATCH_CACHE_ENTRIES, _INDEX_CACHE_ENTRIES
from heagent.skills.skill_store import SkillStore


class _MinimalProvider:
    """最小 provider 替身：只满足聚合层取元数据所需的面（不参与任何真实调用）。"""

    def __init__(self, name: str) -> None:
        self.name = name

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name=self.name, model=f"{self.name}-model")


# ------------------------------------------------------------------ 配置面


def test_settings_defaults_track_module_constants(clean_settings: None) -> None:
    """默认值必须与 providers / skills 的模块常量一致（两处字面量，靠本条钉住）。"""
    settings = Settings()
    assert settings.provider_metadata_cache_size == DEFAULT_MAX_SIZE
    assert settings.skill_match_cache_entries == DEFAULT_MATCH_CACHE_ENTRIES
    assert settings.skill_index_cache_entries == _INDEX_CACHE_ENTRIES


@pytest.mark.parametrize(
    "field",
    ["provider_metadata_cache_size", "skill_match_cache_entries", "skill_index_cache_entries"],
)
@pytest.mark.parametrize("bad", [0, -1])
def test_cache_size_rejects_non_positive(clean_settings: None, field: str, bad: int) -> None:
    """容量 0 会让缓存永久淘汰自己 —— 判定为配置错误而非静默退化。"""
    with pytest.raises(ValidationError):
        Settings(**{field: bad})


# ------------------------------------------------------------------ 装配面


def test_composition_reads_capacity_from_settings(clean_settings: None) -> None:
    assert _cache_size(Settings(provider_metadata_cache_size=7)) == 7


def test_capacity_evicts_beyond_settings_value() -> None:
    """容量取自 Settings 时 LRU 语义不变：超出容量淘汰最久未用的一条。"""
    cache = ProviderMetadataCache(max_size=2)
    keys = [_MinimalProvider(f"p{i}") for i in range(3)]
    for key in keys:
        cache.get(key, key.get_metadata)

    assert len(cache) == 2
    assert cache.misses == 3
    assert cache.hits == 0

    # 最早那条已被淘汰 ⇒ 再取必然是未命中（不是命中旧值）
    cache.get(keys[0], keys[0].get_metadata)
    assert cache.misses == 4
    # 最近用过的那条仍存活 ⇒ 命中
    cache.get(keys[2], keys[2].get_metadata)
    assert cache.hits == 1


def test_skill_store_snapshots_settings_capacity(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """``SkillStore`` 构造期把 Settings 的容量快照进两个 LRU（进程级配置、实例级快照）。"""
    fake = SimpleNamespace(skill_match_cache_entries=5, skill_index_cache_entries=2)
    monkeypatch.setattr("heagent.skills.skill_store.get_settings", lambda: fake)

    store = SkillStore(tmp_path)
    assert store.match_cache.results._max_entries == 5
    assert store.match_cache.index._max_entries == 2


# ------------------------------------------------------------------ 出口面


def _pool_with_cache() -> tuple[SwitchableProvider, ProviderMetadataCache]:
    cache = ProviderMetadataCache(max_size=4)
    stub = _MinimalProvider("inner")
    return SwitchableProvider({"inner": stub}, default="inner", metadata_cache=cache), cache


def test_collect_walks_aggregate_stack() -> None:
    pool, cache = _pool_with_cache()
    assert collect_metadata_caches(pool) == [cache]


def test_debug_mode_emits_exactly_one_line(caplog: pytest.LogCaptureFixture) -> None:
    pool, _ = _pool_with_cache()
    pool.get_metadata()  # 一次未命中，让行里有可断言的非零计数

    with caplog.at_level(logging.INFO, logger="heagent.providers.cache_report"):
        log_metadata_cache_stats(pool, debug_mode=True)
        log_metadata_cache_stats(pool, debug_mode=False)

    lines = [rec.getMessage() for rec in caplog.records if "provider metadata cache:" in rec.getMessage()]
    assert len(lines) == 1, lines
    assert "hits=0" in lines[0]
    assert "misses=1" in lines[0]
    assert "hit_rate=0.00" in lines[0]


def test_zero_query_window_stays_silent(caplog: pytest.LogCaptureFixture) -> None:
    """一次查询都没有时不打 ``hit_rate=0.00``：否则与「真命中率为 0」不可区分。"""
    pool, _ = _pool_with_cache()

    with caplog.at_level(logging.INFO, logger="heagent.providers.cache_report"):
        log_metadata_cache_stats(pool, debug_mode=True)

    assert [rec for rec in caplog.records if "provider metadata cache:" in rec.getMessage()] == []


def test_report_carries_the_eviction_count(caplog: pytest.LogCaptureFixture) -> None:
    """容量不足的判据在日志里：``evictions`` 非零说明 provider 实例数已超出缓存容量。"""
    cache = ProviderMetadataCache(max_size=1)
    pool = SwitchableProvider({"inner": _MinimalProvider("inner")}, default="inner", metadata_cache=cache)
    outsider = _MinimalProvider("outsider")
    cache.get(outsider, outsider.get_metadata)  # 先占满唯一槽位
    pool.get_metadata()  # 溢出 ⇒ 淘汰 outsider，evictions=1

    with caplog.at_level(logging.INFO, logger="heagent.providers.cache_report"):
        log_metadata_cache_stats(pool, debug_mode=True)

    lines = [rec.getMessage() for rec in caplog.records if "provider metadata cache:" in rec.getMessage()]
    assert len(lines) == 1, lines
    assert "evictions=1" in lines[0]


def test_disabled_debug_and_leaf_provider_stay_silent(caplog: pytest.LogCaptureFixture) -> None:
    """非 debug、以及栈里没有聚合层（叶 provider 直返）时都不许打日志。"""
    pool, _ = _pool_with_cache()

    with caplog.at_level(logging.INFO, logger="heagent.providers.cache_report"):
        log_metadata_cache_stats(pool, debug_mode=False)
        log_metadata_cache_stats(_MinimalProvider("leaf"), debug_mode=True)

    assert [rec for rec in caplog.records if "provider metadata cache:" in rec.getMessage()] == []
