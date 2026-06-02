"""Anthropic Claude Provider 实现。

消息格式转换：HeAgent Message ↔ Anthropic API 格式。
特殊处理：Anthropic API 将 system 消息作为独立参数传入（不在 messages 中）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall, ToolSchema


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, object]]:
    """将 HeAgent Message 转换为 Anthropic API 消息格式。

    与 OpenAI 的差异：
    - SYSTEM 消息不放在 messages 中（通过独立 system 参数传入）
    - TOOL 角色的消息映射为 user 角色（Anthropic API 约定）
    - tool_calls 映射为 content blocks（Anthropic 使用 block 数组而非顶层字段）
    """
    result: list[dict[str, object]] = []
    for msg in messages:
        # 跳过系统消息（Anthropic 通过独立参数传递）
        if msg.role == Role.SYSTEM:
            continue
        d: dict[str, object] = {"role": msg.role.value, "content": msg.content}
        # Anthropic 要求工具结果消息使用 user 角色
        if msg.role == Role.TOOL:
            d["role"] = "user"
            d["content"] = f"[Tool result {msg.tool_call_id}]: {msg.content}"
        # 将 tool_calls 转为 Anthropic 的 tool_use content blocks
        if msg.tool_calls:
            blocks: list[dict[str, object]] = []
            for tc in msg.tool_calls:
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
            d["content"] = blocks
        result.append(d)
    return result


def _extract_system(messages: list[Message]) -> str:
    """从消息列表中提取所有 SYSTEM 消息，合并为单个字符串。

    Anthropic API 要求 system 作为独立参数，不在 messages 中。
    """
    parts = [m.content for m in messages if m.role == Role.SYSTEM]
    return "\n".join(parts) if parts else ""


def _to_anthropic_tools(tools: list[ToolSchema]) -> list[dict[str, object]]:
    """将 HeAgent ToolSchema 转为 Anthropic tools 格式。

    Anthropic 使用 input_schema 而非 parameters。
    """
    return [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]


def _parse_tool_use_blocks(blocks: list[object]) -> list[ToolCall]:
    """解析 Anthropic API 返回的 tool_use content blocks 为 HeAgent ToolCall。

    Anthropic 在 content blocks 中返回工具调用，而非顶层字段。
    """
    result: list[ToolCall] = []
    for block in blocks:
        if getattr(block, "type", None) != "tool_use":
            continue
        result.append(ToolCall(id=getattr(block, "id", ""), name=getattr(block, "name", ""), arguments=getattr(block, "input", {})))
    return result


class AnthropicProvider:
    """Anthropic Claude API Provider 实现。"""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", max_tokens: int = 4096, base_url: str | None = None) -> None:
        self._model = model
        self._max_tokens = max_tokens  # Anthropic 要求显式设置最大输出 Token
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url)

    async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
        """单次调用 Anthropic API。"""
        system = _extract_system(messages)        # 提取系统消息（独立参数）
        api_msgs = _to_anthropic_messages(messages)  # 转换消息格式（排除 SYSTEM）
        kwargs: dict[str, object] = {"model": self._model, "max_tokens": self._max_tokens, "messages": api_msgs}
        if system:
            kwargs["system"] = system  # Anthropic 约定：system 作为顶层参数
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        resp = await self._client.messages.create(**kwargs)  # type: ignore

        # 提取文本内容（Anthropic 返回 content blocks 数组）
        text_parts: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        # 提取工具调用（Anthropic 使用 tool_use blocks）
        tool_calls = _parse_tool_use_blocks(resp.content)
        usage = TokenUsage(prompt_tokens=resp.usage.input_tokens, completion_tokens=resp.usage.output_tokens, total_tokens=resp.usage.input_tokens + resp.usage.output_tokens)
        return ProviderResponse(content="".join(text_parts), tool_calls=tool_calls, usage=usage, model=resp.model, finish_reason=resp.stop_reason or "end_turn")

    async def stream(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> AsyncIterator[ProviderResponse]:
        """流式调用 Anthropic API。"""
        system = _extract_system(messages)
        api_msgs = _to_anthropic_messages(messages)
        kwargs: dict[str, object] = {"model": self._model, "max_tokens": self._max_tokens, "messages": api_msgs}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)
        async with self._client.messages.stream(**kwargs) as stream:  # type: ignore
            async for text in stream.text_stream:
                yield ProviderResponse(content=text, tool_calls=[], usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0), model=self._model, finish_reason="")

    def get_metadata(self) -> ProviderMetadata:
        """返回 Provider 能力描述。"""
        return ProviderMetadata(name="anthropic", model=self._model, supports_streaming=True, supports_tools=True)
