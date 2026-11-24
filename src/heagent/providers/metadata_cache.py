"""Provider 元数据缓存 — 聚合层 ``get_metadata()`` 的进程内 LRU。

为什么需要：``get_metadata()`` 同步、无 IO，但每轮都会被动用——状态行
（``cli/display.py::_format_status``）、``/provider`` 列表、路由/观测层各取一次，每次都
重建 ``ProviderMetadata``（Pydantic 模型 ⇒ 逐字段校验）。聚合层（``SwitchableProvider`` /
``ProviderChain``）转发到底层 provider，同一份不会变的信息被反复构造。

**设计取舍（改缓存前先读，四条都是正确性/契约前提）：**

1. **key = provider 对象本身（身份哈希）**，缓存实例挂在聚合层内部，不做全局单例——
   两个同名不同实例的 provider 必须互不串味，共享 key 空间会读到别人的元数据。
2. **失效靠显式 ``invalidate()``，不用 TTL、不用内容比对**：叶 provider 的 ``_model`` 与
   能力位只在 ``__init__`` 赋值，全仓 provider 没有 ``model`` setter（``grep "def model"``
   为空）⇒ 实例自身的元数据构造后不可变。唯一会改变聚合层返回值的是它自己的活跃指针
   （``SwitchableProvider._active`` / ``ProviderChain._current_index``），这些**唯一写点**
   都经 ``_set_active`` / ``_set_current_index`` 调 ``invalidate(self)``。新增活跃指针写点
   必须同样失效，否则会返回上一个 provider 的元数据。
3. 不加锁：调用方全在单线程事件循环内、方法同步无 await 点；不加 TTL：失效条件是状态
   变化而非时间流逝。
4. ``get()`` 命中时返回**同一个** ``ProviderMetadata`` 实例（不复制）：调用方只读——
   全仓调用点都只取 ``.name`` / ``.model`` / 能力位，不写字段；新增写字段的调用点必须先
   ``invalidate``，否则会污染后续所有读者。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

from heagent.pub.exceptions import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.providers.base import ProviderMetadata

#: 默认容量：远大于实际 provider 实例数（一个进程通常是池内几个到十几个聚合层实例），
#: 只为杜绝「每轮重建」而非压榨内存。
DEFAULT_MAX_SIZE = 64


class ProviderMetadataCache:
    """以 provider 对象为 key 的 LRU，兼作命中率观测面。

    用法（聚合层内部）::

        self._metadata_cache = ProviderMetadataCache()
        def get_metadata(self) -> ProviderMetadata:
            return self._metadata_cache.get(self, self._build_metadata)

    ``compute`` 由调用方给出而不是默认 ``provider.get_metadata``：聚合层需要在叶子元数据
    外包一层（如 ``name="switchable:<active>"``），若默认调 ``provider.get_metadata`` 则被
    聚合层自身调用时必然无限递归。
    """

    def __init__(self, *, max_size: int = DEFAULT_MAX_SIZE) -> None:
        """初始化缓存。

        Args:
            max_size: 最多缓存多少个 provider 的元数据，超出按 LRU 淘汰最久未用的一条。

        Raises:
            ValueError: ``max_size`` < 1。
        """
        if max_size < 1:
            raise ConfigurationError(f"ProviderMetadataCache max_size must be >= 1, got {max_size}")
        self._max_size = max_size
        self._entries: OrderedDict[object, ProviderMetadata] = OrderedDict()
        self._hits = 0
        self._misses = 0

    # ── 观测面 ──

    @property
    def max_size(self) -> int:
        """容量上限。"""
        return self._max_size

    @property
    def hits(self) -> int:
        """命中次数（``invalidate`` / ``clear`` 不计入）。"""
        return self._hits

    @property
    def misses(self) -> int:
        """未命中次数（每次未命中都会调用一次 ``compute``）。"""
        return self._misses

    @property
    def hit_rate(self) -> float:
        """``hits / (hits + misses)``；尚无任何查询时返回 0.0（不抛 ZeroDivisionError）。"""
        total = self._hits + self._misses
        return self._hits / total if total else 0.0

    def __len__(self) -> int:
        """当前缓存的条目数。"""
        return len(self._entries)

    # ── 读写 ──

    def get(self, provider: object, compute: Callable[[], ProviderMetadata]) -> ProviderMetadata:
        """取 ``provider`` 的元数据；未命中时调用 ``compute()`` 并存入缓存。

        命中会把该条目移到 LRU 末尾（最久未用者在容量溢出时被淘汰）。
        """
        cached = self._entries.get(provider)
        if cached is not None:
            self._hits += 1
            self._entries.move_to_end(provider)
            return cached
        self._misses += 1
        metadata = compute()
        self._entries[provider] = metadata
        self._entries.move_to_end(provider)
        while len(self._entries) > self._max_size:
            self._entries.popitem(last=False)  # 淘汰最久未用的一条
        return metadata

    def invalidate(self, provider: object) -> None:
        """丢弃 ``provider`` 的缓存条目（provider 内部状态变了，下次 ``get`` 重算）。

        对不存在的 key 静默无操作——失效点写在状态写路径上，那里不关心「之前是否缓存过」。
        """
        self._entries.pop(provider, None)

    def clear(self) -> None:
        """清空全部条目**并重置 hits / misses**（换 provider 池或观测窗口重开时用）。"""
        self._entries.clear()
        self._hits = 0
        self._misses = 0
