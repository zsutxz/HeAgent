"""Provider 回退链 — 多 Provider 有序回退机制。

当主 Provider 调用失败时，自动切换到下一个 Provider 重试。
遍历所有 Provider 后仍失败，则重置索引并抛出最后的异常。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NoReturn

from heagent.exceptions import ProviderError
from heagent.providers.retry import ErrorCategory, classify_exception, wrap_provider_error

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.providers.base import BaseProvider, ProviderMetadata
    from heagent.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


def _raise_provider_error(error: Exception) -> NoReturn:
    """抛出统一的 ProviderError，保证回退链抛出的始终是 HeAgentError 体系内的异常。

    已是 ProviderError（P0-2 后 provider 源头已把 SDK 异常包装为此类型）则原样抛出——
    保留其既有 cause 链，避免二次包装产生 ProviderError→ProviderError→原始 SDK 的冗余链；
    否则把 SDK/未知异常包装为 ProviderError，并以原始异常为 cause，供上层中间件分类重试、
    CLI 统一捕获，避免裸 SDK 异常穿透导致未处理崩溃。
    """
    if isinstance(error, ProviderError):
        raise error
    raise wrap_provider_error(error) from error


class ProviderChain:
    """有序 Provider 列表，支持自动故障转移。

    示例：ProviderChain([deepseek, openai, anthropic])
    - 正常情况使用 deepseek
    - deepseek 失败 → 自动切换到 openai
    - openai 也失败 → 切换到 anthropic
    - 全部失败 → 重置为 deepseek 并抛出异常
    """

    def __init__(self, providers: list[BaseProvider]) -> None:
        if not providers:
            raise ValueError("ProviderChain requires at least one provider")
        self._providers = list(providers)
        self._current_index = 0  # 当前活跃 Provider 的索引

    @property
    def current(self) -> BaseProvider:
        """获取当前活跃的 Provider。"""
        return self._providers[self._current_index]

    @property
    def providers(self) -> list[BaseProvider]:
        """返回所有 Provider 的列表副本。"""
        return list(self._providers)

    def _advance(self) -> bool:
        """将活跃索引后移一位（故障转移）。

        返回 True 表示成功切换，False 表示已无可用的 Provider。
        """
        if self._current_index < len(self._providers) - 1:
            old = self._current_index
            self._current_index += 1
            logger.info(
                "Fallback: %s -> %s", self._providers[old].get_metadata().name, self.current.get_metadata().name
            )
            return True
        return False

    def reset(self) -> None:
        """重置到第一个 Provider（新一轮尝试时使用）。"""
        self._current_index = 0

    async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
        """依次尝试每个 Provider，直到成功或全部失败。

        回退精度（FR-4）：仅对 RATE_LIMITED / AUTH_FAILED / TRANSIENT 错误回退；
        NON_TRANSIENT（400/422 等客户端错误）立即抛出——切换 Provider 不会让坏请求变好，
        回退只会浪费配额并掩盖真实问题。回退链抛出的异常统一包装为 ProviderError。
        """
        last_error: Exception | None = None
        start = self._current_index  # 记录起始索引，失败后恢复

        for idx in range(start, len(self._providers)):
            provider = self._providers[idx]  # 本地捕获实例，免疫共享索引被并发协程改写
            try:
                resp = await provider.send(messages, tools=tools)
                self._current_index = start  # 成功后复位到主 Provider（不粘性旁路）
                return resp
            except Exception as e:
                category = classify_exception(e)
                logger.warning(
                    "Provider %s failed (%s): %s",
                    provider.get_metadata().name,
                    category.value,
                    e,
                )
                # 客户端错误 → 不回退，立即抛出
                if category == ErrorCategory.NON_TRANSIENT:
                    self._current_index = start
                    _raise_provider_error(e)
                last_error = e

        # 所有 Provider 均失败（均为可回退错误）→ 恢复索引，抛出最后的错误
        self._current_index = start
        if last_error is not None:
            _raise_provider_error(last_error)
        # 理论不可达：providers 非空（__init__ 保证）且任意迭代要么 return 要么设 last_error。
        # 仍以 ProviderError 兜底以遵守「禁止裸 Exception」契约。
        raise ProviderError("All providers failed")

    async def stream(
        self, messages: list[Message], *, tools: list[ToolSchema] | None = None
    ) -> AsyncIterator[ProviderResponse]:
        """流式调用的故障转移版本。

        与 send() 回退精度逻辑相同（FR-4），但追加一条约束：一旦已向下游交付
        过任何 chunk，后续异常不再回退——否则下一个 Provider 会从头重放，导致
        消费者收到重复前缀。仅在首个 chunk 之前的失败才按 FR-4 回退。
        """
        start = self._current_index
        last_error: Exception | None = None
        for idx in range(start, len(self._providers)):
            provider = self._providers[idx]  # 本地捕获实例，免疫共享索引被并发协程改写
            delivered = False
            try:
                async for chunk in provider.stream(messages, tools=tools):
                    delivered = True  # 已从当前 Provider 取得 chunk，回退将产生重复输出
                    yield chunk
                self._current_index = start  # 成功后复位到主 Provider（不粘性旁路）
                return
            except Exception as e:
                # 已交付部分输出 → 不可回退（重放会重复），直接抛出并复位索引
                if delivered:
                    self._current_index = start
                    _raise_provider_error(e)
                category = classify_exception(e)
                logger.warning(
                    "Provider %s stream failed (%s): %s",
                    provider.get_metadata().name,
                    category.value,
                    e,
                )
                if category == ErrorCategory.NON_TRANSIENT:
                    self._current_index = start
                    _raise_provider_error(e)
                last_error = e
        self._current_index = start
        if last_error is not None:
            _raise_provider_error(last_error)
        # 理论不可达：见 send() 同款注释。
        raise ProviderError("All providers failed for stream")

    def get_metadata(self) -> ProviderMetadata:
        """返回当前活跃 Provider 的能力描述。"""
        return self.current.get_metadata()
