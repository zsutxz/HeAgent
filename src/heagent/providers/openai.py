"""OpenAI 兼容 Provider — 支持 OpenAI 及所有兼容 API（DeepSeek、智谱 AI 等）。

通过自定义 base_url 接入任何 OpenAI 兼容的 LLM 服务。
消息格式转换：HeAgent Message ↔ OpenAI API message dict。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from heagent.providers.base import ProviderMetadata
from heagent.providers.retry import wrap_provider_error
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall, ToolSchema

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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


def _build_usage(usage: object) -> TokenUsage:
    """从 OpenAI usage 对象构建 TokenUsage（usage 为 None 时归零）。"""
    return TokenUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )


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

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        *,
        stream: bool = False,
    ) -> dict[str, object]:
        """组装 OpenAI Chat Completions 请求参数（stream 时追加 stream=True）。"""
        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": _to_openai_messages(messages),
        }
        if stream:
            kwargs["stream"] = True
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
        return kwargs

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """单次调用 LLM，返回完整响应。"""
        kwargs = self._build_kwargs(messages, tools)

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

        return ProviderResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            usage=_build_usage(resp.usage),
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
        kwargs = self._build_kwargs(messages, tools, stream=True)

        try:
            stream = await self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                yield ProviderResponse(
                    content=delta.content or "",
                    tool_calls=[],
                    usage=_build_usage(chunk.usage),
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
