"""Provider 回退链 — 多 Provider 有序回退机制。

当主 Provider 调用失败时，自动切换到下一个 Provider 重试。
遍历所有 Provider 后仍失败，则重置索引并抛出最后的异常。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from heagent.providers.base import BaseProvider, ProviderMetadata
from heagent.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


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
            logger.info("Fallback: %s -> %s", self._providers[old].get_metadata().name, self.current.get_metadata().name)
            return True
        return False

    def reset(self) -> None:
        """重置到第一个 Provider（新一轮尝试时使用）。"""
        self._current_index = 0

    async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
        """依次尝试每个 Provider，直到成功或全部失败。

        遍历逻辑：当前 Provider 失败 → _advance() 切换下一个 → 重试
        全部失败后恢复原始索引，避免后续请求跳过主 Provider。
        """
        last_error: Exception | None = None
        start = self._current_index  # 记录起始索引，失败后恢复

        for _ in range(len(self._providers)):
            try:
                return await self.current.send(messages, tools=tools)
            except Exception as e:
                last_error = e
                logger.warning("Provider %s failed: %s", self.current.get_metadata().name, e)
                if not self._advance():
                    break

        # 恢复原始索引，下一次调用重新从主 Provider 开始
        self._current_index = start
        raise last_error or RuntimeError("All providers failed")

    async def stream(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> AsyncIterator[ProviderResponse]:
        """流式调用的故障转移版本。

        与 send() 逻辑相同，但处理 AsyncIterator 返回类型。
        """
        start = self._current_index
        for _ in range(len(self._providers)):
            try:
                async for chunk in self.current.stream(messages, tools=tools):  # type: ignore[attr-defined]
                    yield chunk
                return
            except Exception as e:
                logger.warning("Provider %s stream failed: %s", self.current.get_metadata().name, e)
                if not self._advance():
                    break
        self._current_index = start
        raise RuntimeError("All providers failed for stream")

    def get_metadata(self) -> ProviderMetadata:
        """返回当前活跃 Provider 的能力描述。"""
        return self.current.get_metadata()
