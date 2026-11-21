"""密钥池轮换 Provider — 同一 Provider 多密钥自动切换。

收到速率限制 (429) 或认证错误 (401/403) 时，自动切换到下一个密钥重试。
密钥池全部耗尽后抛出异常，由上层 ProviderChain 回退到其他 Provider。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from heagent.providers.base import BaseProvider, ProviderMetadata
from heagent.providers.fallback_base import FallbackPolicy, raise_as_provider_error
from heagent.providers.metadata_cache import ProviderMetadataCache
from heagent.pub.exceptions import ConfigurationError, ProviderError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.pub.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


class KeyRotatingProvider:
    """同一 Provider 类型的多密钥轮换包装。

    持有同一 Provider 的多个实例（每个使用不同 API Key），
    429/401/403 时自动切换到下一个实例。

    示例：
        provider = KeyRotatingProvider([
            OpenAIProvider(api_key="sk-1", model="gpt-4o"),
            OpenAIProvider(api_key="sk-2", model="gpt-4o"),
        ])
    """

    def __init__(
        self,
        providers: list[BaseProvider],
        *,
        metadata_cache: ProviderMetadataCache | None = None,
    ) -> None:
        """初始化密钥池。

        Args:
            providers: 同一 provider 的多个实例，每个持不同 API key。
            metadata_cache: 可选的元数据缓存实例（调容量 / 共享观测面用）；None 则自建默认容量。
        """
        if not providers:
            raise ConfigurationError("KeyRotatingProvider requires at least one provider")
        self._providers = list(providers)
        self._current_index = 0
        self._lock = asyncio.Lock()  # 防并发索引漂移
        self._metadata_cache = metadata_cache if metadata_cache is not None else ProviderMetadataCache()

    @property
    def current(self) -> BaseProvider:
        """当前活跃的 Provider 实例。"""
        return self._providers[self._current_index]

    @property
    def providers(self) -> list[BaseProvider]:
        """池内全部 provider 的只读副本（观测/调试用；与 ``ProviderChain.providers`` 同形）。"""
        return list(self._providers)

    @property
    def metadata_cache(self) -> ProviderMetadataCache:
        """元数据缓存实例（观测面：``hits`` / ``misses`` / ``hit_rate``）。"""
        return self._metadata_cache

    def _set_current_index(self, index: int) -> None:
        """写 ``_current_index`` 的**唯一入口**：值真的变了才失效元数据缓存。

        ``get_metadata()`` 转发 ``current``，索引一变返回值就变（池内实例可能配不同模型）；
        所有索引写入都必须走本方法，否则 ``get_metadata()`` 会继续返回轮换前的元数据。
        """
        if self._current_index != index:
            self._current_index = index
            self._metadata_cache.invalidate(self)

    @staticmethod
    def _is_rotation_error(error: Exception) -> bool:
        """判断是否为可触发密钥轮换的错误（RATE_LIMITED 或 AUTH_FAILED）。

        委托 :class:`FallbackPolicy` 避免两套分类漂移（H-4）。
        """
        return FallbackPolicy.should_fallback_key_rotation(error)

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """尝试当前密钥，429/401/403 时轮换重试。"""
        # 与 stream() 同口径：锁内快照索引与 provider 列表，网络 I/O 不持锁。
        async with self._lock:
            start = self._current_index
            providers_snapshot = list(self._providers)

        last_error: Exception | None = None
        for idx in range(start, len(providers_snapshot)):
            provider = providers_snapshot[idx]  # 本地捕获实例，免疫共享索引被并发协程改写
            try:
                resp = await provider.send(messages, tools=tools)
            except Exception as e:
                if not self._is_rotation_error(e):
                    raise_as_provider_error(e)
                last_error = e
                logger.warning("Key #%d failed (rotatable): %s", idx, e)
                continue
            async with self._lock:
                self._set_current_index(idx)  # 粘性：停在生效的 key 上（原 _advance 后不复位）
            return resp

        # 恢复原始索引
        async with self._lock:
            self._set_current_index(start)
        if last_error is not None:
            raise_as_provider_error(last_error)
        raise ProviderError("All keys exhausted")

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式调用的密钥轮换版本。

        P1-11 修复：与 chain.py/switchable.py 对齐——锁内仅快照索引，释放锁后
        迭代，避免持锁覆盖整个流式迭代串行化并发 consumer。

        与 ``ProviderChain.stream`` 结构同构，但**索引语义有意不同**：本类成功后停留到成功的
        那把密钥（粘性，后续复用），chain 则复位到 ``start``。故两者不共用模板。
        """
        # 锁内快照索引 + provider 列表，释放锁后迭代
        async with self._lock:
            start = self._current_index
            providers_snapshot = list(self._providers)  # 快照，免疫并发修改

        last_error: Exception | None = None
        for idx in range(start, len(providers_snapshot)):
            provider = providers_snapshot[idx]  # 本地捕获实例
            delivered = False
            try:
                async for chunk in provider.stream(messages, tools=tools):
                    delivered = True
                    yield chunk
                # 成功 → 锁内更新索引（粘性停留）
                async with self._lock:
                    self._set_current_index(idx)
                return
            except Exception as e:
                if delivered:
                    async with self._lock:
                        self._set_current_index(start)
                    raise_as_provider_error(e)
                if not self._is_rotation_error(e):
                    raise_as_provider_error(e)
                last_error = e
                logger.warning("Key #%d stream failed (rotatable): %s", idx, e)
        async with self._lock:
            self._set_current_index(start)
        if last_error is not None:
            raise_as_provider_error(last_error)
        raise ProviderError("All keys exhausted for stream")

    def _build_metadata(self) -> ProviderMetadata:
        """组装当前活跃 Provider 的能力描述（``+keypool`` 后缀标明轮换层）。"""
        meta = self.current.get_metadata()
        return ProviderMetadata(
            name=f"{meta.name}+keypool",
            model=meta.model,
            supports_streaming=meta.supports_streaming,
            supports_tools=meta.supports_tools,
        )

    def get_metadata(self) -> ProviderMetadata:
        """返回当前活跃 Provider 的能力描述（经元数据缓存；索引变化后由缓存失效跟随）。"""
        return self._metadata_cache.get(self, self._build_metadata)
