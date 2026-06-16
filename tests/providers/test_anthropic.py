"""Tests for AnthropicProvider — mocked SDK calls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from heagent.providers.anthropic import AnthropicProvider, _extract_system, _parse_tool_use_blocks, _to_anthropic_messages
from heagent.providers.base import BaseProvider
from heagent.types import Message, Role, ToolCall, ToolSchema


def _mock_usage(inp: int = 10, out: int = 5) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=inp, output_tokens=out)


def _mock_usage_cached(
    inp: int = 5,
    out: int = 3,
    cache_read: int = 0,
    cache_create: int = 0,
) -> SimpleNamespace:
    """带提示词缓存统计的 usage mock（模拟 Anthropic 缓存命中响应）。"""
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
    )


def _mock_text_block(text: str = "hi") -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _mock_tool_block(tid: str = "tu_1", name: str = "run", inp: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tid, name=name, input=inp or {"cmd": "ls"})


def _mock_response(content: list[object] | None = None, model: str = "claude-sonnet-4-6", stop: str = "end_turn", usage: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(content=content or [_mock_text_block()], model=model, stop_reason=stop, usage=usage or _mock_usage())


class TestHelpers:
    def test_extract_system(self) -> None:
        msgs = [Message(role=Role.SYSTEM, content="You are helpful"), Message(role=Role.USER, content="hi")]
        assert _extract_system(msgs) == "You are helpful"

    def test_extract_system_empty(self) -> None:
        assert _extract_system([Message(role=Role.USER, content="hi")]) == ""

    def test_to_anthropic_messages(self) -> None:
        result = _to_anthropic_messages([Message(role=Role.USER, content="hello")])
        assert result == [{"role": "user", "content": "hello"}]

    def test_to_anthropic_messages_with_tool_use_and_result_blocks(self) -> None:
        result = _to_anthropic_messages([
            Message(
                role=Role.ASSISTANT,
                content="Checking",
                tool_calls=[ToolCall(id="tu_1", name="run", arguments={"cmd": "ls"})],
            ),
            Message(role=Role.TOOL, content="done", tool_call_id="tu_1"),
        ])
        assert result == [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Checking"},
                    {"type": "tool_use", "id": "tu_1", "name": "run", "input": {"cmd": "ls"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "done"},
                ],
            },
        ]

    def test_to_anthropic_messages_groups_consecutive_tool_results(self) -> None:
        result = _to_anthropic_messages([
            Message(role=Role.TOOL, content="one", tool_call_id="tu_1"),
            Message(role=Role.TOOL, content="two", tool_call_id="tu_2"),
        ])
        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "one"},
                    {"type": "tool_result", "tool_use_id": "tu_2", "content": "two"},
                ],
            }
        ]

    def test_parse_tool_use_blocks(self) -> None:
        blocks = [_mock_tool_block(), _mock_text_block()]
        result = _parse_tool_use_blocks(blocks)
        assert len(result) == 1
        assert result[0].name == "run"


class TestProtocol:
    def test_satisfies_base_provider(self) -> None:
        p = AnthropicProvider(api_key="sk-test")
        assert isinstance(p, BaseProvider)


class TestSend:
    @patch("heagent.providers.anthropic.AsyncAnthropic")
    async def test_send_basic(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response([_mock_text_block("Hello!")]))
        p = AnthropicProvider(api_key="sk-test")
        resp = await p.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "Hello!"
        assert resp.finish_reason == "end_turn"

    @patch("heagent.providers.anthropic.AsyncAnthropic")
    async def test_send_with_tools(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response([_mock_tool_block()], stop="tool_use"))
        p = AnthropicProvider(api_key="sk-test")
        tools = [ToolSchema(name="run", description="run", parameters={"type": "object"})]
        resp = await p.send([Message(role=Role.USER, content="run ls")], tools=tools)
        assert resp.finish_reason == "tool_use"
        assert len(resp.tool_calls) == 1

    @patch("heagent.providers.anthropic.AsyncAnthropic")
    async def test_send_caches_system_prompt(self, mock_cls: MagicMock) -> None:
        """启用缓存时，system 应包装为带 cache_control 的块列表（FR-3）。"""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response([_mock_text_block("ok")]))
        p = AnthropicProvider(api_key="sk-test")  # prompt_caching 默认 True
        await p.send([
            Message(role=Role.SYSTEM, content="You are helpful"),
            Message(role=Role.USER, content="hi"),
        ])
        _, kwargs = mock_client.messages.create.call_args
        assert isinstance(kwargs["system"], list)
        assert kwargs["system"][-1]["cache_control"] == {"type": "ephemeral"}
        assert kwargs["system"][-1]["text"] == "You are helpful"

    @patch("heagent.providers.anthropic.AsyncAnthropic")
    async def test_send_no_cache_when_disabled(self, mock_cls: MagicMock) -> None:
        """禁用缓存时，system 保持纯字符串（兼容不支持 cache_control 的代理）。"""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response([_mock_text_block("ok")]))
        p = AnthropicProvider(api_key="sk-test", prompt_caching=False)
        await p.send([
            Message(role=Role.SYSTEM, content="You are helpful"),
            Message(role=Role.USER, content="hi"),
        ])
        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["system"] == "You are helpful"

    @patch("heagent.providers.anthropic.AsyncAnthropic")
    async def test_send_omits_system_when_empty(self, mock_cls: MagicMock) -> None:
        """无 system 消息时不发送 system 字段。"""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response([_mock_text_block("ok")]))
        p = AnthropicProvider(api_key="sk-test")
        await p.send([Message(role=Role.USER, content="hi")])
        _, kwargs = mock_client.messages.create.call_args
        assert "system" not in kwargs

    @patch("heagent.providers.anthropic.AsyncAnthropic")
    async def test_send_usage_includes_cache_tokens(self, mock_cls: MagicMock) -> None:
        """缓存命中时，prompt_tokens 应计入 cache_read/creation tokens（成本准确性）。"""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(usage=_mock_usage_cached(inp=5, out=3, cache_read=100, cache_create=8))
        )
        p = AnthropicProvider(api_key="sk-test")
        resp = await p.send([Message(role=Role.USER, content="hi")])
        # prompt_tokens = 非缓存输入(5) + 缓存写入(8) + 缓存读取(100) = 113
        assert resp.usage.prompt_tokens == 113


class TestStream:
    @patch("heagent.providers.anthropic.AsyncAnthropic")
    async def test_stream_yields_text(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        async def fake_stream(**kwargs: object) -> AsyncIterator[object]:
            yield

        mock_mgr = AsyncMock()
        mock_mgr.__aenter__ = AsyncMock(return_value=mock_mgr)
        mock_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_mgr.text_stream = AsyncIteratorStub(["Hello", " World"])
        mock_client.messages.stream = MagicMock(return_value=mock_mgr)

        p = AnthropicProvider(api_key="sk-test")
        chunks = [c async for c in p.stream([Message(role=Role.USER, content="hi")])]
        assert len(chunks) == 2


class AsyncIteratorStub:
    def __init__(self, items: list[str]) -> None:
        self._items = items

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self) -> str:
        if self._i >= len(self._items):
            raise StopAsyncIteration
        val = self._items[self._i]
        self._i += 1
        return val


class TestMetadata:
    def test_metadata(self) -> None:
        p = AnthropicProvider(api_key="sk-test")
        meta = p.get_metadata()
        assert meta.name == "anthropic"
        assert meta.supports_streaming is True
