"""OpenAI 兼容 Provider — 支持 OpenAI 及所有兼容 API（DeepSeek、智谱 AI 等）。

通过自定义 base_url 接入任何 OpenAI 兼容的 LLM 服务。
消息格式转换：HeAgent Message ↔ OpenAI API message dict。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from heagent.providers.base import ProviderMetadata
from heagent.providers.retry import wrap_provider_error
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall, ToolSchema


def _to_openai_messages(messages: list[Message]) -> list[dict[str, object]]:
    """将 HeAgent Message 列表转换为 OpenAI API 的消息格式。

    处理规则：
    - 基本字段：role, content
    - ASSISTANT 消息可能包含 tool_calls → 转为 OpenAI function calling 格式
    - TOOL 消息需要 tool_call_id 和 name 字段
    """
    result: list[dict[str, object]] = []
    for msg in messages:
        d: dict[str, object] = {"role": msg.role.value, "content": msg.content}
        # 转换工具调用（ASSISTANT 角色携带的 tool_calls）
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in msg.tool_calls
            ]
        # 工具执行结果需要关联的调用 ID 和工具名
        if msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
        if msg.name:
            d["name"] = msg.name
        result.append(d)
    return result


def _to_openai_tools(tools: list[ToolSchema]) -> list[dict[str, object]]:
    """将 HeAgent ToolSchema 转换为 OpenAI function calling 的 tools 格式。"""
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


def _parse_tool_calls(raw: list[object]) -> list[ToolCall]:
    """解析 OpenAI API 返回的 tool_calls 为 HeAgent ToolCall 列表。

    OpenAI 返回的对象有 function.name / function.arguments (JSON string)，
    需要反序列化为 dict。
    """
    result: list[ToolCall] = []
    for tc in raw:
        tc_id = getattr(tc, "id", "")
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        name = getattr(fn, "name", "")
        args_str = getattr(fn, "arguments", "{}")
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else {}
        except json.JSONDecodeError:
            args = {}
        result.append(ToolCall(id=tc_id, name=name, arguments=args))
    return result


class OpenAIProvider:
    """OpenAI 及兼容 API 的 Provider 实现。

    通过 base_url 参数可接入 DeepSeek、智谱 AI 等兼容服务。
    使用 openai AsyncOpenAI 客户端实现异步调用。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """单次调用 LLM，返回完整响应。"""
        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": _to_openai_messages(messages),
        }
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)

        try:
            resp = await self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
        except Exception as e:
            # 统一包装 SDK 异常（RateLimitError/APITimeoutError 等）为 ProviderError，
            # 使下游 KeyRotatingProvider/retry/Chain 始终面对 HeAgent 体系异常。
            raise wrap_provider_error(e) from e

        choice = resp.choices[0]
        message = choice.message
        # 解析工具调用（LLM 判断需要调用工具时返回）
        tool_calls = _parse_tool_calls(message.tool_calls) if message.tool_calls else []

        usage = TokenUsage(
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            total_tokens=resp.usage.total_tokens if resp.usage else 0,
        )

        return ProviderResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            usage=usage,
            model=resp.model,
            finish_reason=choice.finish_reason or "stop",
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式调用 LLM，逐步返回响应片段。"""
        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": _to_openai_messages(messages),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)

        try:
            stream = await self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                usage = TokenUsage(
                    prompt_tokens=chunk.usage.prompt_tokens if chunk.usage else 0,
                    completion_tokens=chunk.usage.completion_tokens if chunk.usage else 0,
                    total_tokens=chunk.usage.total_tokens if chunk.usage else 0,
                )
                yield ProviderResponse(
                    content=delta.content or "",
                    tool_calls=[],
                    usage=usage,
                    model=chunk.model,
                    finish_reason=chunk.choices[0].finish_reason or "",
                )
        except Exception as e:
            raise wrap_provider_error(e) from e

    def get_metadata(self) -> ProviderMetadata:
        """返回 Provider 能力描述。"""
        return ProviderMetadata(
            name="openai",
            model=self._model,
            supports_streaming=True,
            supports_tools=True,
        )
