"""OpenAI Responses API Provider — 走 ``client.responses.create`` 的 OpenAI 兼容 provider。

区别于 ``openai.py`` 的 Chat Completions API（``client.chat.completions.create``）：
本 provider 使用 OpenAI **Responses API**（wire_api="responses"），用于接入仅支持
Responses API 的兼容中转站（如 komapi.top 中转的 GPT-5.x 模型）。codex 等工具配置里的
``wire_api = "responses"`` 即指此 API。

消息格式转换与 ``openai.py`` / ``anthropic.py`` 的差异：
  - SYSTEM 消息提取到顶层 ``instructions`` 参数（与 Anthropic 的顶层 system 字段同构）。
  - 工具调用（ASSISTANT 携带）拆为 ``function_call`` input item。
  - 工具结果（TOOL）转为 ``function_call_output`` input item。

注意：部分中转站会拦截 SDK 默认 ``User-Agent: OpenAI/Python/...``（返回 403），
故构造时默认以 ``default_headers`` 覆盖 User-Agent（可用 ``user_agent`` 参数覆盖）。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from heagent.providers.base import ProviderMetadata
from heagent.providers.retry import wrap_provider_error
from heagent.pub.types import Message, ProviderResponse, Role, TokenUsage, ToolCall, ToolSchema

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# 默认覆盖 SDK 的 User-Agent：部分中转站（komapi.top 等）对 ``OpenAI/Python/...`` 返回 403。
_DEFAULT_USER_AGENT = "Mozilla/5.0"

_ZERO_USAGE = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _extract_instructions(messages: list[Message]) -> str:
    """提取并合并所有 SYSTEM 消息为 Responses API 的顶层 instructions。"""
    parts = [m.content for m in messages if m.role == Role.SYSTEM and m.content]
    return "\n".join(parts)


def _to_responses_input(messages: list[Message]) -> list[dict[str, object]]:
    """将 HeAgent 消息列表转换为 Responses API 的 input item 列表。

    SYSTEM 消息不进入 input（由 ``_extract_instructions`` 提取为顶层 instructions）。
    ASSISTANT 携带 tool_calls 时拆为 assistant message + 若干 function_call item；
    TOOL 消息转为 function_call_output item（关联 call_id）。
    """
    result: list[dict[str, object]] = []
    for msg in messages:
        if msg.role == Role.SYSTEM:
            continue
        if msg.role == Role.TOOL:
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id or "",
                    "output": msg.content,
                }
            )
            continue
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            if msg.content:
                result.append({"role": "assistant", "content": msg.content})
            for tc in msg.tool_calls:
                result.append(
                    {
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    }
                )
            continue
        result.append({"role": msg.role.value, "content": msg.content})
    return result


def _to_responses_tools(tools: list[ToolSchema]) -> list[dict[str, object]]:
    """将 HeAgent ToolSchema 转换为 Responses API 的 tools 格式。"""
    return [
        {"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters} for t in tools
    ]


def _parse_output(output: list[object]) -> tuple[str, list[ToolCall]]:
    """从 Responses API 响应的 ``output`` 列表提取文本与工具调用。

    message item 的 ``content`` 是 content-part 列表（output_text / text），
    function_call item 携带 call_id / name / arguments（JSON 字符串）。
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for item in output:
        itype = getattr(item, "type", None)
        if itype == "function_call":
            args_str = getattr(item, "arguments", "") or ""
            try:
                parsed: object = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                parsed = {}
            arguments = parsed if isinstance(parsed, dict) else {}
            tool_calls.append(
                ToolCall(
                    id=getattr(item, "call_id", "") or "",
                    name=getattr(item, "name", "") or "",
                    arguments=arguments,
                )
            )
        elif itype == "message":
            for part in getattr(item, "content", []) or []:
                if getattr(part, "type", None) in ("output_text", "text"):
                    text_parts.append(getattr(part, "text", "") or "")
    return "".join(text_parts), tool_calls


def _build_usage(usage: object) -> TokenUsage:
    """从 Responses API usage 构建 TokenUsage（input/output/total_tokens）。"""
    if usage is None:
        return _ZERO_USAGE
    return TokenUsage(
        prompt_tokens=getattr(usage, "input_tokens", None) or 0,
        completion_tokens=getattr(usage, "output_tokens", None) or 0,
        total_tokens=getattr(usage, "total_tokens", None) or 0,
    )


class OpenAIResponsesProvider:
    """OpenAI Responses API 的 Provider 实现。

    通过 base_url 接入任意仅支持 Responses API 的 OpenAI 兼容服务。
    使用 openai AsyncOpenAI 客户端调用 ``responses.create``。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.6-terra",
        base_url: str | None = None,
        *,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        self._model = model
        self._instructions = instructions
        self._max_output_tokens = max_output_tokens
        # 覆盖默认 User-Agent：部分中转站拦截 ``OpenAI/Python/...``。
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={"User-Agent": user_agent},
        )

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
    ) -> dict[str, object]:
        """组装 Responses API 请求参数（model/instructions/input/tools）。"""
        kwargs: dict[str, object] = {
            "model": self._model,
            "input": _to_responses_input(messages),
        }
        instructions = self._instructions or _extract_instructions(messages)
        if instructions:
            kwargs["instructions"] = instructions
        if tools:
            kwargs["tools"] = _to_responses_tools(tools)
        if self._max_output_tokens is not None:
            kwargs["max_output_tokens"] = self._max_output_tokens
        return kwargs

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """单次调用 Responses API，返回完整响应。"""
        kwargs = self._build_kwargs(messages, tools)

        try:
            resp = await self._client.responses.create(**kwargs)  # type: ignore[call-overload]
        except Exception as e:
            raise wrap_provider_error(e) from e

        text, tool_calls = _parse_output(resp.output)
        finish_reason = "tool_calls" if tool_calls else "stop"
        return ProviderResponse(
            content=text,
            tool_calls=tool_calls,
            usage=_build_usage(resp.usage),
            model=resp.model,
            finish_reason=finish_reason,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式调用 Responses API，逐步返回文本片段，流末统一产出 tool_calls。

        文本增量（``response.output_text.delta``）即时下推；``response.completed``
        事件的 ``event.response`` 是完整响应对象，从中统一解析 tool_calls + usage
        （与非流式 ``send`` 共用 ``_parse_output`` / ``_build_usage``）。
        """
        kwargs = self._build_kwargs(messages, tools)
        kwargs["stream"] = True

        try:
            async with await self._client.responses.create(**kwargs) as stream:  # type: ignore[call-overload]
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        yield ProviderResponse(
                            content=event.delta or "",
                            tool_calls=[],
                            usage=_ZERO_USAGE,
                            model=self._model,
                            finish_reason="",
                        )
                    elif event.type == "response.completed":
                        resp = event.response
                        _, tool_calls = _parse_output(resp.output)
                        finish_reason = "tool_calls" if tool_calls else "stop"
                        yield ProviderResponse(
                            content="",
                            tool_calls=tool_calls,
                            usage=_build_usage(resp.usage),
                            model=resp.model,
                            finish_reason=finish_reason,
                        )
        except Exception as e:
            raise wrap_provider_error(e) from e

    def get_metadata(self) -> ProviderMetadata:
        """返回 Provider 能力描述。"""
        return ProviderMetadata(
            name="openai-responses",
            model=self._model,
            supports_streaming=True,
            supports_tools=True,
        )
