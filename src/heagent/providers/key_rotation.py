"""密钥池轮换 Provider — 同一 Provider 多密钥自动切换。

收到速率限制 (429) 或认证错误 (401) 时，自动切换到下一个密钥重试。
密钥池全部耗尽后抛出异常，由上层 ProviderChain 回退到其他 Provider。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from heagent.exceptions import ProviderError
from heagent.providers.base import BaseProvider, ProviderMetadata
from heagent.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


class KeyRotatingProvider:
    """同一 Provider 类型的多密钥轮换包装。

    持有同一 Provider 的多个实例（每个使用不同 API Key），
    429/401 时自动切换到下一个实例。

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

    @property
    def current(self) -> BaseProvider:
        """当前活跃的 Provider 实例。"""
        return self._providers[self._current_index]

    def _advance(self) -> bool:
        """切换到下一个密钥。全部耗尽返回 False。"""
        if self._current_index < len(self._providers) - 1:
            old = self._current_index
            self._current_index += 1
            logger.info(
                "Key rotation: %s (#%d) -> %s (#%d)",
                self._providers[old].get_metadata().name, old,
                self.current.get_metadata().name, self._current_index,
            )
            return True
        return False

    def _is_rotation_error(self, error: Exception) -> bool:
        """判断是否为可触发密钥轮换的错误（429/401）。"""
        if not isinstance(error, ProviderError):
            return False
        status = getattr(error, "status_code", None)
        if status in (429, 401, 403):
            return True
        msg = error.message.lower()
        return any(kw in msg for kw in ("rate", "429", "auth", "401", "forbidden"))

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """尝试当前密钥，429/401 时轮换重试。"""
        last_error: Exception | None = None
        start = self._current_index

        for _ in range(len(self._providers)):
            try:
                return await self.current.send(messages, tools=tools)
            except Exception as e:
                if not self._is_rotation_error(e):
                    raise
                last_error = e
                logger.warning(
                    "Key #%d failed (rotatable): %s", self._current_index, e,
                )
                if not self._advance():
                    break

        # 恢复原始索引
        self._current_index = start
        raise last_error or ProviderError("All keys exhausted")

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式调用的密钥轮换版本。"""
        start = self._current_index
        for _ in range(len(self._providers)):
            try:
                async for chunk in self.current.stream(messages, tools=tools):  # type: ignore[attr-defined]
                    yield chunk
                return
            except Exception as e:
                if not self._is_rotation_error(e):
                    raise
                logger.warning(
                    "Key #%d stream failed (rotatable): %s", self._current_index, e,
                )
                if not self._advance():
                    break
        self._current_index = start
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
