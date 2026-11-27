"""Provider 元数据缓存命中率的运行期出口（``DEBUG_MODE`` 门控）。

缓存实例住在各聚合层内部（``SwitchableProvider`` / ``RoutingProvider`` /
``KeyRotatingProvider`` / ``ProviderChain`` 的 ``metadata_cache`` 属性），刻意没有全局登记表
（见 ``metadata_cache`` 模块的设计取舍 1）。本模块只在**读侧**把 provider 栈递归走一遍，
把各层的命中 / 容量求和成**一行**日志。

唯一调用点：``agent.run_lifecycle.persist_and_cache``（run 收尾的 ``finally``）——一次 run
一条，不是每轮迭代。门控由调用方传入的 ``debug_mode`` 决定，本模块不读配置：providers 层
运行期不依赖 ``config``。
"""

from __future__ import annotations

import logging

from heagent.providers.chain import ProviderChain
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.metadata_cache import ProviderMetadataCache
from heagent.providers.router import RoutingProvider
from heagent.providers.switchable import SwitchableProvider

logger = logging.getLogger(__name__)

#: 递归深度上限（与 ``router.active_model`` 的走栈守卫同量级）：provider 栈是手工装配的有限
#: 嵌套，深度异常说明装配错了——宁可少报一层，也不要无限递归。
MAX_WALK_DEPTH = 8


def _children(provider: object) -> list[object]:
    """聚合层的子 provider（叶 provider 返回空表）。"""
    if isinstance(provider, SwitchableProvider):
        return list(provider.providers.values())
    if isinstance(provider, RoutingProvider):
        return list(provider.providers.values())
    if isinstance(provider, (KeyRotatingProvider, ProviderChain)):
        return list(provider.providers)
    return []


def collect_metadata_caches(provider: object) -> list[ProviderMetadataCache]:
    """收集 provider 栈里所有聚合层的元数据缓存（按实例去重，装配序）。"""
    found: list[ProviderMetadataCache] = []
    seen: set[int] = set()

    def walk(node: object, depth: int) -> None:
        if depth > MAX_WALK_DEPTH:
            return
        cache = getattr(node, "metadata_cache", None)
        if isinstance(cache, ProviderMetadataCache) and id(cache) not in seen:
            seen.add(id(cache))
            found.append(cache)
        for child in _children(node):
            walk(child, depth + 1)

    walk(provider, 0)
    return found


def log_metadata_cache_stats(provider: object, *, debug_mode: bool) -> None:
    """``DEBUG_MODE`` 下把整栈命中率打成一**条**日志；否则立刻返回（零输出）。

    用 ``logger.info`` 而不是 ``logger.debug``：门控是 ``debug_mode`` 本身，而 ``LOG_LEVEL``
    默认 INFO——走 debug 级会让 http-server / gui 入口（不抬日志级别）即使在 ``DEBUG_MODE``
    下也看不到这一行。栈里没有聚合层（单 provider 直返）时同样零输出。
    """
    if not debug_mode:
        return
    caches = collect_metadata_caches(provider)
    if not caches:
        return
    hits = sum(cache.hits for cache in caches)
    misses = sum(cache.misses for cache in caches)
    queries = hits + misses
    if not queries:
        # 一次查询都没有（这次 run 既没渲染状态行、也没列 provider）：打 ``hit_rate=0.00``
        # 会把「真命中率为 0」与「压根没用过」看成同一条，故整条静默。
        return
    logger.info(
        "provider metadata cache: hits=%d misses=%d hit_rate=%.2f size=%d/%d evictions=%d",
        hits,
        misses,
        hits / queries,
        sum(len(cache) for cache in caches),
        sum(cache.max_size for cache in caches),
        sum(cache.evictions for cache in caches),
    )
