"""密钥池轮换 Provider — 同一 Provider 多密钥自动切换。

收到速率限制 (429) 或认证错误 (401/403) 时，自动切换到下一个密钥重试。
密钥池全部耗尽后抛出异常，由上层 ProviderChain 回退到其他 Provider。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from heagent.exceptions import ProviderError
from heagent.providers.base import BaseProvider, ProviderMetadata
from heagent.providers.retry import ErrorCategory, classify_exception, wrap_provider_error

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


def _raise_wrapped(error: Exception) -> None:
    """Raise ``error``, wrapping non-ProviderError into ProviderError (P1-3 修复)。

    统一保证 key_rotation chain 抛出的始终是 HeAgent Error 体系内的异常，
    不裸抛 SDK 异常穿透上层 ProviderChain。
    """
    if isinstance(error, ProviderError):
        raise error
    raise wrap_provider_error(error) from error


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

    def __init__(self, providers: list[BaseProvider]) -> None:
        if not providers:
            raise ValueError("KeyRotatingProvider requires at least one provider")
        self._providers = list(providers)
        self._current_index = 0
        self._lock = asyncio.Lock()  # 防并发索引漂移

    @property
    def current(self) -> BaseProvider:
        """当前活跃的 Provider 实例。"""
        return self._providers[self._current_index]

    @property
    def key_count(self) -> int:
        """密钥池中的 Provider 实例数。"""
        return len(self._providers)

    @staticmethod
    def _is_rotation_error(error: Exception) -> bool:
        """判断是否为可触发密钥轮换的错误（RATE_LIMITED 或 AUTH_FAILED）。

        委托 :func:`classify_exception`（retry.py 唯一分类源）避免两套分类漂移（H-4）。
        """
        if not isinstance(error, ProviderError):
            return False
        return classify_exception(error) in (ErrorCategory.RATE_LIMITED, ErrorCategory.AUTH_FAILED)

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """尝试当前密钥，429/401/403 时轮换重试。"""
        async with self._lock:
            last_error: Exception | None = None
            start = self._current_index

            for idx in range(start, len(self._providers)):
                provider = self._providers[idx]  # 本地捕获实例，免疫共享索引被并发协程改写
                try:
                    resp = await provider.send(messages, tools=tools)
                    self._current_index = idx  # 粘性：停在生效的 key 上（原 _advance 后不复位）
                    return resp
                except Exception as e:
                    if not self._is_rotation_error(e):
                        _raise_wrapped(e)  # P1-3 修复：统一包装为 ProviderError
                    last_error = e
                    logger.warning("Key #%d failed (rotatable): %s", idx, e)

            # 恢复原始索引
            self._current_index = start
            if last_error is not None:
                _raise_wrapped(last_error)
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
        """
        # P1-11：锁内快照索引 + provider 列表，释放锁后迭代
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
                    self._current_index = idx
                return
            except Exception as e:
                if delivered:
                    async with self._lock:
                        self._current_index = start
                    _raise_wrapped(e)
                if not self._is_rotation_error(e):
                    _raise_wrapped(e)
                last_error = e
                logger.warning("Key #%d stream failed (rotatable): %s", idx, e)
        async with self._lock:
            self._current_index = start
        if last_error is not None:
            _raise_wrapped(last_error)
        raise ProviderError("All keys exhausted for stream")
    def get_metadata(self) -> ProviderMetadata:
        """返回当前活跃 Provider 的能力描述。"""
        meta = self.current.get_metadata()
        return ProviderMetadata(
            name=f"{meta.name}+keypool",
            model=meta.model,
            supports_streaming=meta.supports_streaming,
            supports_tools=meta.supports_tools,
        )
