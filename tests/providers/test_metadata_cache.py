"""``ProviderMetadataCache`` 的行为护栏：命中率 / LRU 容量 / 失效，以及聚合层接入后的正确性。

失效是这套缓存唯一的正确性风险面：``get_metadata()`` 的返回值随聚合层的活跃指针变化
（``SwitchableProvider._active`` / ``ProviderChain._current_index``）。因此本文件不只测缓存
类本身，还从**切换路径与回退路径**（``switch()`` / ``send()`` 自动回退 / ``_advance()``）
取一次 metadata，断言读到的是新 active——只测缓存类会让「忘了接线」的缺陷漏网。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from heagent.providers.base import ProviderMetadata
from heagent.providers.chain import ProviderChain
from heagent.providers.metadata_cache import ProviderMetadataCache
from heagent.providers.switchable import SwitchableProvider
from heagent.pub.exceptions import ProviderError
from heagent.pub.types import Message, ProviderResponse, Role, TokenUsage, ToolSchema

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _StubProvider:
    """最小 provider：metadata 可区分身份，可配置 send 是否失败（触发聚合层回退）。"""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self._name = name
        self._fail = fail
        self.metadata_calls = 0

    async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
        if self._fail:
            raise ProviderError(f"{self._name} unavailable", status_code=503)
        return ProviderResponse(
            content="ok",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model=f"model-{self._name}",
            finish_reason="stop",
        )

    async def stream(
        self, messages: list[Message], *, tools: list[ToolSchema] | None = None
    ) -> AsyncIterator[ProviderResponse]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        self.metadata_calls += 1
        return ProviderMetadata(
            name=self._name,
            model=f"model-{self._name}",
            supports_streaming=True,
            supports_tools=True,
        )


def _messages() -> list[Message]:
    return [Message(role=Role.USER, content="hi")]


# ---------------------------------------------------------------------------
# 缓存类本身
# ---------------------------------------------------------------------------


def test_hit_rate_after_warmup_is_99_percent() -> None:
    """预热 1 次（miss）后连打 99 次 ⇒ hits=99 / misses=1 / hit_rate=0.99（>80% 目标）。"""
    cache = ProviderMetadataCache()
    provider = _StubProvider("a")

    first = cache.get(provider, provider.get_metadata)
    for _ in range(99):
        assert cache.get(provider, provider.get_metadata) is first

    assert (cache.hits, cache.misses) == (99, 1)
    assert cache.hit_rate == pytest.approx(0.99)
    assert cache.hit_rate > 0.8
    assert provider.metadata_calls == 1  # 底层只构造一次


def test_capacity_evicts_least_recently_used() -> None:
    """max_size=2 时插入第 3 个 provider 淘汰最久未用的一条；被淘汰者下次是 miss。"""
    cache = ProviderMetadataCache(max_size=2)
    a, b, c = _StubProvider("a"), _StubProvider("b"), _StubProvider("c")

    cache.get(a, a.get_metadata)
    cache.get(b, b.get_metadata)
    assert len(cache) == 2

    cache.get(c, c.get_metadata)  # 溢出 ⇒ 淘汰 a（最久未用）
    assert len(cache) == 2
    assert (cache.hits, cache.misses) == (0, 3)

    cache.get(b, b.get_metadata)  # 命中，b 移到 LRU 末尾
    cache.get(c, c.get_metadata)  # 命中，c 移到 LRU 末尾
    assert (cache.hits, cache.misses) == (2, 3)

    cache.get(a, a.get_metadata)  # a 已被淘汰 ⇒ miss（若未淘汰则 b 才是被淘汰者）
    assert (cache.hits, cache.misses) == (2, 4)
    assert a.metadata_calls == 2


def test_lru_hit_refreshes_recency() -> None:
    """命中会刷新 recency：先命中 a 再插 c，被淘汰的是 b 而不是 a。"""
    cache = ProviderMetadataCache(max_size=2)
    a, b, c = _StubProvider("a"), _StubProvider("b"), _StubProvider("c")
    cache.get(a, a.get_metadata)
    cache.get(b, b.get_metadata)
    cache.get(a, a.get_metadata)  # a 成为最近使用
    cache.get(c, c.get_metadata)  # 淘汰 b

    cache.get(a, a.get_metadata)
    assert a.metadata_calls == 1  # a 仍在缓存
    cache.get(b, b.get_metadata)
    assert b.metadata_calls == 2  # b 被淘汰后重算


def test_invalidate_forces_recompute_and_counts_correctly() -> None:
    """invalidate 不计入 hit/miss，下一次 get 记一次 miss 并重新计算。"""
    cache = ProviderMetadataCache()
    provider = _StubProvider("a")

    cache.get(provider, provider.get_metadata)
    cache.get(provider, provider.get_metadata)
    assert (cache.hits, cache.misses) == (1, 1)

    cache.invalidate(provider)
    assert (cache.hits, cache.misses) == (1, 1)  # 失效本身不改计数
    assert len(cache) == 0

    cache.get(provider, provider.get_metadata)
    assert (cache.hits, cache.misses) == (1, 2)
    assert provider.metadata_calls == 2

    cache.invalidate(_StubProvider("never-cached"))  # 不存在的 key 静默无操作
    assert (cache.hits, cache.misses) == (1, 2)


def test_key_is_provider_identity_not_name() -> None:
    """同名不同实例互不串味（key = 对象身份，不是 name 字段）。"""
    cache = ProviderMetadataCache()
    first, second = _StubProvider("same"), _StubProvider("same")
    cache.get(first, first.get_metadata)
    cache.get(second, second.get_metadata)
    assert (cache.hits, cache.misses) == (0, 2)


def test_clear_resets_entries_and_counters() -> None:
    """clear() 清空条目并重置观测计数；空缓存的 hit_rate 为 0.0（不抛除零）。"""
    cache = ProviderMetadataCache()
    provider = _StubProvider("a")
    cache.get(provider, provider.get_metadata)
    cache.get(provider, provider.get_metadata)
    cache.clear()

    assert len(cache) == 0
    assert (cache.hits, cache.misses, cache.hit_rate) == (0, 0, 0.0)


def test_max_size_must_be_positive() -> None:
    """max_size < 1 在构造期显性失败（静默退化成不缓存会悄悄拖性能）。"""
    with pytest.raises(ValueError, match="max_size"):
        ProviderMetadataCache(max_size=0)


# ---------------------------------------------------------------------------
# 聚合层接入：失效必须接到状态写路径上
# ---------------------------------------------------------------------------


async def test_switchable_metadata_follows_active_after_switch() -> None:
    """``switch()`` 之后 name/model 跟随新 active（证明失效接线到切换路径，不是过期值）。"""
    switchable = SwitchableProvider(
        {"a": _StubProvider("a"), "b": _StubProvider("b")},
        default="a",
    )

    before = switchable.get_metadata()
    assert (before.name, before.model) == ("switchable:a", "model-a")
    assert switchable.get_metadata() is before  # 缓存命中，返回同一对象
    assert switchable.metadata_cache.hit_rate == pytest.approx(0.5)

    await switchable.switch("b")
    after = switchable.get_metadata()
    assert (after.name, after.model) == ("switchable:b", "model-b")
    assert after is not before
    assert (switchable.metadata_cache.hits, switchable.metadata_cache.misses) == (1, 2)

    # 切回 a 同样跟随（不是一次性失效）
    await switchable.switch("a")
    assert switchable.get_metadata().name == "switchable:a"


async def test_switchable_metadata_follows_auto_fallback() -> None:
    """自动回退（send 成功粘性切到下一个 provider）也必须失效缓存。"""
    switchable = SwitchableProvider(
        {"a": _StubProvider("a", fail=True), "b": _StubProvider("b")},
        default="a",
    )
    assert switchable.get_metadata().name == "switchable:a"

    await switchable.send(_messages())
    assert switchable.active == "b"
    assert switchable.get_metadata().name == "switchable:b"


async def test_switchable_no_op_switch_keeps_cache_hit() -> None:
    """切到当前 active（值未变）不失效——避免无意义重算把命中率打穿。"""
    switchable = SwitchableProvider({"a": _StubProvider("a")}, default="a")
    switchable.get_metadata()
    await switchable.switch("a")
    assert switchable.metadata_cache.misses == 1


async def test_switchable_hit_rate_through_wrapper_exceeds_80_percent() -> None:
    """聚合层视角：预热 1 次后连打 99 次，``metadata_cache.hit_rate`` = 99%。"""
    switchable = SwitchableProvider({"a": _StubProvider("a")}, default="a")
    switchable.get_metadata()
    for _ in range(99):
        switchable.get_metadata()
    assert switchable.metadata_cache.hit_rate == pytest.approx(0.99)


def test_chain_metadata_follows_index_advance_and_reset() -> None:
    """``_advance()`` / ``reset()`` 改变索引后 metadata 跟随（失效接到索引写路径）。"""
    a, b = _StubProvider("a"), _StubProvider("b")
    chain = ProviderChain([a, b])  # type: ignore[list-item]

    assert chain.get_metadata().name == "a"
    assert chain.get_metadata().name == "a"  # 命中
    assert (chain.metadata_cache.hits, chain.metadata_cache.misses) == (1, 1)

    assert chain._advance() is True
    assert chain.get_metadata().name == "b"
    assert (chain.metadata_cache.hits, chain.metadata_cache.misses) == (1, 2)

    chain.reset()
    assert chain.get_metadata().name == "a"
    assert (chain.metadata_cache.hits, chain.metadata_cache.misses) == (1, 3)


async def test_chain_success_keeps_cache_hit() -> None:
    """主 Provider 成功时索引不变 ⇒ 元数据缓存保持命中（回退路径的空转失效会被这条抓住）。"""
    a, b = _StubProvider("a"), _StubProvider("b")
    chain = ProviderChain([a, b])  # type: ignore[list-item]
    chain.get_metadata()
    await chain.send(_messages())
    assert chain.get_metadata().name == "a"
    assert (chain.metadata_cache.hits, chain.metadata_cache.misses) == (1, 1)


def test_cache_max_size_is_configurable_through_wrapper() -> None:
    """聚合层可注入缓存实例 ⇒ max_size 可配置（默认 64，这里压到 1 验证接线）。"""
    cache = ProviderMetadataCache(max_size=1)
    chain = ProviderChain([_StubProvider("a")], metadata_cache=cache)  # type: ignore[list-item]
    assert chain.metadata_cache is cache
    assert chain.metadata_cache.max_size == 1
    assert ProviderMetadataCache().max_size == 64
