"""可切换 Provider — 运行时在多个 LLM provider 之间手动切换。

与 ``ProviderChain``（自动故障转移）不同，``SwitchableProvider`` 由用户主动控制
使用哪个后端。在交互模式下通过 ``/model`` 命令切换；也可在代码中调用 ``switch()``。

每个命名 provider 持有独立的实例（含各自 API key、base_url、model），切换即时生效，
不会丢失未完成的上下文。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from heagent.providers.base import BaseProvider, ProviderMetadata

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


class SwitchableProvider:
    """持有多个命名 provider 并可运行时切换。

    实现了 ``BaseProvider`` 协议，对 ``AgentLoop`` 完全透明——它只看到「一个 provider」，
    切换发生在内部委托层。

    示例：
        sp = SwitchableProvider({
            "deepseek": OpenAIProvider(api_key="sk-xxx", model="deepseek-chat", base_url="..."),
            "kimi":     OpenAIProvider(api_key="sk-yyy", model="moonshot-v1-8k", base_url="..."),
            "openai":   OpenAIProvider(api_key="sk-zzz", model="gpt-4o"),
        }, default="deepseek")

        await sp.send(messages)          # 使用 deepseek
        sp.switch("kimi")
        await sp.send(messages)          # 现在使用 kimi
    """

    def __init__(self, providers: dict[str, BaseProvider], *, default: str) -> None:
        """初始化可切换 provider 池。

        Args:
            providers: ``{名称: provider 实例}`` 的字典，名称即 ``/model <name>`` 中的 name。
            default: 初始活跃 provider 的名称，必须在 providers 中存在。
        """
        if not providers:
            raise ValueError("SwitchableProvider requires at least one provider")
        if default not in providers:
            raise ValueError(f"Default provider {default!r} not in provider pool")
        self._providers = dict(providers)
        self._active: str = default
        self._lock = asyncio.Lock()  # 防并发的 switch + send 竞态

    # -- 公共 API --

    @property
    def active(self) -> str:
        """当前活跃 provider 的名称。"""
        return self._active

    @property
    def names(self) -> list[str]:
        """所有可用 provider 名称列表。"""
        return list(self._providers.keys())

    def switch(self, name: str) -> None:
        """切换到指定名称的 provider。

        Raises:
            ValueError: 名称不存在。
        """
        if name not in self._providers:
            raise ValueError(
                f"Unknown provider {name!r}. Available: {', '.join(sorted(self._providers.keys()))}"
            )
        old = self._active
        self._active = name
        logger.info("Provider switched: %s → %s", old, name)

    def info(self) -> dict[str, object]:
        """返回所有 provider 的元数据摘要，用于 ``/model`` 列表展示。"""
        result: dict[str, object] = {}
        for name, p in self._providers.items():
            meta = p.get_metadata()
            result[name] = {
                "model": meta.model,
                "streaming": meta.supports_streaming,
                "tools": meta.supports_tools,
                "active": name == self._active,
            }
        return result

    @property
    def _current(self) -> BaseProvider:
        """当前活跃的 provider 实例（内部使用）。"""
        return self._providers[self._active]

    # -- BaseProvider 协议实现 --

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """委托给当前活跃 provider 的 send。"""
        async with self._lock:
            return await self._current.send(messages, tools=tools)

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """委托给当前活跃 provider 的 stream。

        注意：stream 期间不应切换 provider——切换会等到下一次 send/stream 才生效，
        已开始的 stream 不受影响（每个 chunk 走同一个 provider）。
        """
        # 在 __iter__ 之前捕获当前 provider，保证整个 stream 生命周期使用同一实例。
        async with self._lock:
            provider = self._current
        async for chunk in provider.stream(messages, tools=tools):
            yield chunk

    def get_metadata(self) -> ProviderMetadata:
        """返回当前活跃 provider 的能力描述。"""
        meta = self._current.get_metadata()
        return ProviderMetadata(
            name=f"switchable:{self._active}",
            model=meta.model,
            supports_streaming=meta.supports_streaming,
            supports_tools=meta.supports_tools,
        )
