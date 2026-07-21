"""可切换 Provider — 运行时在多个 LLM provider 之间手动/自动切换。

``SwitchableProvider`` 支持两种切换模式：
  - **手动切换**：用户通过 ``/model`` 命令主动选择 provider。
  - **自动回退**：当前 provider 触发限流 (429) 或瞬时错误时，自动尝试池中下一个
    provider；成功后粘性停留在该 provider（后续调用不再浪费配额重试已限流的）。

与 ``ProviderChain``（全自动、不复位）不同，``SwitchableProvider`` 以用户选择为
默认起点，自动回退是「当前选择不可用时的应急接管」。

每个命名 provider 持有独立的实例（含各自 API key、base_url、model），切换即时生效，
不会丢失未完成的上下文。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.exceptions import ProviderError
from heagent.providers.base import BaseProvider, ProviderMetadata, ProviderSummary
from heagent.providers.retry import ErrorCategory, classify_exception, wrap_provider_error

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


class SwitchableProvider:
    """持有多个命名 provider 并可运行时切换（手动 + 自动回退）。

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

    自动回退示例：
        # deepseek 触发 429 → 自动切到 kimi，后续调用粘性使用 kimi
        await sp.send(messages)          # deepseek 429 → kimi 成功 → 粘性 kimi
        await sp.send(messages)          # 直接走 kimi（不再重试 deepseek）
        sp.switch("deepseek")            # 用户手动切回 deepseek（配额已刷新）
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

    def info(self) -> dict[str, ProviderSummary]:
        """返回所有 provider 的元数据摘要，用于 ``/model`` 列表展示。"""
        result: dict[str, ProviderSummary] = {}
        for name, p in self._providers.items():
            meta = p.get_metadata()
            result[name] = ProviderSummary(
                model=meta.model,
                streaming=meta.supports_streaming,
                tools=meta.supports_tools,
                active=name == self._active,
            )
        return result

    @property
    def _current(self) -> BaseProvider:
        """当前活跃的 provider 实例（内部使用）。"""
        return self._providers[self._active]

    # ------------------------------------------------------------------
    # 自动回退：按「活跃 → 池中其余」顺序尝试，限流/瞬时错误触发
    # ------------------------------------------------------------------

    def _ordered_names(self) -> list[str]:
        """返回 provider 名称列表：活跃优先，其余保持注册顺序。"""
        return [self._active] + [n for n in self._providers if n != self._active]

    @staticmethod
    def _is_fallback_error(error: Exception) -> bool:
        """判断是否应触发自动回退（RATE_LIMITED 或 TRANSIENT）。

        仅这两类错误会在切换 provider 后好转；AUTH_FAILED / NON_TRANSIENT 不回退。
        """
        return classify_exception(error) in (ErrorCategory.RATE_LIMITED, ErrorCategory.TRANSIENT)

    def _note_fallback(self, from_name: str, to_name: str) -> None:
        """记录自动回退并粘性停留到新 provider。"""
        logger.warning(
            "Auto-fallback: %s unavailable → switched to %s (sticky until /model or next failure)",
            from_name,
            to_name,
        )

    # -- BaseProvider 协议实现 --

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """发送请求，当前 provider 不可用时自动回退。

        顺序：活跃 provider 优先 → 池中其余按注册顺序。
        仅 RATE_LIMITED (429) 和 TRANSIENT (5xx/超时) 触发回退；
        AUTH_FAILED / NON_TRANSIENT 直接上抛，不浪费时间重试。
        成功回退后粘性停留在新 provider（后续调用不再重试已限流的旧 provider）。
        """
        last_error: Exception | None = None
        active_before = self._active

        for name in self._ordered_names():
            provider = self._providers[name]
            try:
                resp = await provider.send(messages, tools=tools)
                if name != active_before:
                    self._note_fallback(active_before, name)
                    self._active = name  # 粘性停留
                return resp
            except Exception as e:
                if not self._is_fallback_error(e):
                    raise
                logger.warning("Provider '%s' unavailable (%s), trying next...", name, classify_exception(e).value)
                last_error = e

        # 池耗尽：重置到原始活跃 provider，上抛最后一个错误
        self._active = active_before
        if last_error is not None:
            raise wrap_provider_error(last_error) from last_error
        raise ProviderError("All providers exhausted")

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式请求，自动回退版本。

        与 ``send()`` 回退逻辑相同，但追加「已下发 chunk → 不回退」约束：
        一旦当前 provider 已产出任意 chunk，后续异常不回退——否则下一个 provider
        从头重放会导致消费者收到重复前缀。
        成功回退后同样粘性停留在新 provider。
        """
        last_error: Exception | None = None
        active_before = self._active

        for name in self._ordered_names():
            provider = self._providers[name]
            delivered = False
            try:
                async for chunk in provider.stream(messages, tools=tools):
                    delivered = True
                    yield chunk
                if name != active_before:
                    self._note_fallback(active_before, name)
                    self._active = name  # 粘性停留
                return
            except Exception as e:
                if delivered:
                    # 已下发输出，重放会重复——不回退，直接上抛
                    self._active = active_before
                    raise
                if not self._is_fallback_error(e):
                    raise
                logger.warning(
                    "Provider '%s' stream unavailable (%s), trying next...",
                    name,
                    classify_exception(e).value,
                )
                last_error = e

        self._active = active_before
        if last_error is not None:
            raise wrap_provider_error(last_error) from last_error
        raise ProviderError("All providers exhausted for stream")

    def get_metadata(self) -> ProviderMetadata:
        """返回当前活跃 provider 的能力描述。"""
        meta = self._current.get_metadata()
        return ProviderMetadata(
            name=f"switchable:{self._active}",
            model=meta.model,
            supports_streaming=meta.supports_streaming,
            supports_tools=meta.supports_tools,
        )
