"""Anthropic Claude provider implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

from heagent.providers.base import ProviderMetadata
from heagent.providers.retry import wrap_provider_error
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall, ToolSchema

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

logger = logging.getLogger(__name__)


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, object]]:
    """Convert HeAgent messages into Anthropic's Messages API format."""
    result: list[dict[str, object]] = []
    pending_tool_results: list[dict[str, object]] = []

    def flush_tool_results() -> None:
        if pending_tool_results:
            result.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results.clear()

    for msg in messages:
        if msg.role == Role.SYSTEM:
            continue

        if msg.role == Role.TOOL:
            if msg.tool_call_id:
                pending_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )
            else:
                flush_tool_results()
                result.append({"role": "user", "content": msg.content})
            continue

        flush_tool_results()

        if msg.role == Role.ASSISTANT and msg.tool_calls:
            blocks: list[dict[str, object]] = []
            if msg.content:
                blocks.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            result.append({"role": "assistant", "content": blocks})
            continue

        result.append({"role": msg.role.value, "content": msg.content})

    flush_tool_results()
    return result


def _extract_system(messages: list[Message]) -> str:
    """Extract and merge all system messages into Anthropic's top-level system field."""
    parts = [m.content for m in messages if m.role == Role.SYSTEM]
    return "\n".join(parts) if parts else ""


def _build_system_param(system: str, *, caching: bool) -> list[dict[str, object]] | str | None:
    """构建 Anthropic system 参数，可选注入提示词缓存断点。

    Anthropic 的提示词缓存通过 cache_control: {"type": "ephemeral"} 标记缓存断点，
    标记位置之前（含）的稳定内容（system prompt、工具定义等）在后续请求中复用，
    显著降低重复输入的 token 成本（缓存读 ~0.1x，写 ~1.25x）。

    返回：
        None — 无 system 内容，调用方应省略 system 字段
        str — 禁用缓存时的纯字符串（兼容不支持 cache_control 的代理）
        list — 启用缓存时的块列表，末块带 cache_control 断点
    """
    if not system:
        return None
    if not caching:
        return system
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _build_usage(usage: object) -> TokenUsage:
    """从 Anthropic usage 构建 TokenUsage，计入提示词缓存的读写 token。

    Anthropic 启用缓存后，usage 拆分为三部分：
      - input_tokens: 未命中缓存的输入
      - cache_creation_input_tokens: 写入缓存的输入
      - cache_read_input_tokens: 从缓存读取的输入
    三者之和才是真实输入量。若不合并，缓存命中时 prompt_tokens 会大幅低估。

    ``usage`` 为 None 时返回零用量（极少数情况下的防御性守卫）。
    """
    if usage is None:
        return _ZERO_USAGE
    inp = getattr(usage, "input_tokens", None) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", None) or 0
    out = getattr(usage, "output_tokens", None) or 0
    prompt = inp + cache_read + cache_create
    if cache_read or cache_create:
        logger.debug("Anthropic prompt cache: %d read, %d created", cache_read, cache_create)
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=out,
        total_tokens=prompt + out,
    )


_ZERO_USAGE = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _to_anthropic_tools(tools: list[ToolSchema]) -> list[dict[str, object]]:
    """Convert HeAgent tools into Anthropic's tool schema format."""
    return [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]


def _parse_tool_use_blocks(blocks: Sequence[object]) -> list[ToolCall]:
    """Parse Anthropic tool_use blocks into HeAgent tool calls."""
    result: list[ToolCall] = []
    for block in blocks:
        if getattr(block, "type", None) != "tool_use":
            continue
        result.append(
            ToolCall(
                id=getattr(block, "id", ""),
                name=getattr(block, "name", ""),
                arguments=getattr(block, "input", {}),
            )
        )
    return result


class AnthropicProvider:
    """Anthropic Claude API provider."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        base_url: str | None = None,
        prompt_caching: bool = True,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._prompt_caching = prompt_caching
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url)

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
    ) -> dict[str, object]:
        """组装 Anthropic Messages API 请求参数（model/max_tokens/messages/system/tools）。"""
        kwargs: dict[str, object] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": _to_anthropic_messages(messages),
        }
        system_param = _build_system_param(_extract_system(messages), caching=self._prompt_caching)
        if system_param is not None:
            kwargs["system"] = system_param
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)
        return kwargs

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """Send a single Anthropic Messages API request."""
        kwargs = self._build_kwargs(messages, tools)

        try:
            resp = await self._client.messages.create(**kwargs)  # type: ignore[call-overload]
        except Exception as e:
            # 统一包装 SDK 异常（RateLimitError/APITimeoutError 等）为 ProviderError，
            # 使下游 KeyRotatingProvider/retry/Chain 始终面对 HeAgent 体系异常。
            raise wrap_provider_error(e) from e

        text_parts: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        tool_calls = _parse_tool_use_blocks(resp.content)
        usage = _build_usage(resp.usage)
        return ProviderResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            usage=usage,
            model=resp.model,
            finish_reason=resp.stop_reason or "end_turn",
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """Stream an Anthropic Messages API request."""
        kwargs = self._build_kwargs(messages, tools)

        try:
            async with self._client.messages.stream(**kwargs) as stream:  # type: ignore[arg-type]
                async for text in stream.text_stream:
                    yield ProviderResponse(
                        content=text,
                        tool_calls=[],
                        usage=_ZERO_USAGE,
                        model=self._model,
                        finish_reason="",
                    )
                # 文本块流尽后用 get_final_message() 取完整响应，补发一个最终 chunk：
                # 携带真实 usage（驱动 token 累计与压缩触发）、tool_calls（流式工具调用）、
                # finish_reason。文本已在上方逐块 yield，此处 content="" 避免重复输出。
                final = await stream.get_final_message()
                yield ProviderResponse(
                    content="",
                    tool_calls=_parse_tool_use_blocks(final.content),
                    usage=_build_usage(final.usage),
                    model=getattr(final, "model", self._model),
                    finish_reason=final.stop_reason or "end_turn",
                )
        except Exception as e:
            raise wrap_provider_error(e) from e

    def get_metadata(self) -> ProviderMetadata:
        """Return provider capability metadata."""
        return ProviderMetadata(
            name="anthropic",
            model=self._model,
            supports_streaming=True,
            supports_tools=True,
        )
