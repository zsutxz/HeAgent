"""Tests for OpenAIResponsesProvider — mocked SDK calls (Responses API, wire_api="responses")."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from heagent.exceptions import ProviderError
from heagent.providers.base import BaseProvider
from heagent.providers.responses import (
    OpenAIResponsesProvider,
    _build_usage,
    _extract_instructions,
    _parse_output,
    _to_responses_input,
    _to_responses_tools,
)
from heagent.types import Message, Role, ToolCall, ToolSchema


def _mock_usage(i: int = 10, o: int = 5, t: int = 15) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=i, output_tokens=o, total_tokens=t)


def _mock_text_part(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="output_text", text=text)


def _mock_message_item(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="message", role="assistant", content=[_mock_text_part(text)])


def _mock_function_call_item(
    call_id: str = "call_1", name: str = "run", arguments: str = '{"cmd":"ls"}'
) -> SimpleNamespace:
    return SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=arguments)


def _mock_response(
    output: list[object] | None = None,
    model: str = "gpt-5.6-terra",
    status: str = "completed",
    usage: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        output=output if output is not None else [_mock_message_item("hello")],
        model=model,
        status=status,
        usage=usage or _mock_usage(),
    )


def _mock_event(event_type: str, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, **kwargs)


class _FakeAsyncStream:
    """兼容 ``async with`` 的假流对象（模拟 Responses API 流事件序列）。"""

    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events
        self._idx = 0

    def __aiter__(self) -> _FakeAsyncStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._idx >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._idx]
        self._idx += 1
        return event

    async def __aenter__(self) -> _FakeAsyncStream:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class TestHelpers:
    def test_extract_instructions_merges_system(self) -> None:
        msgs = [
            Message(role=Role.SYSTEM, content="line1"),
            Message(role=Role.USER, content="hi"),
            Message(role=Role.SYSTEM, content="line2"),
        ]
        assert _extract_instructions(msgs) == "line1\nline2"

    def test_to_responses_input_basic(self) -> None:
        msgs = [Message(role=Role.SYSTEM, content="sys"), Message(role=Role.USER, content="hi")]
        result = _to_responses_input(msgs)
        # SYSTEM 不进入 input
        assert result == [{"role": "user", "content": "hi"}]

    def test_to_responses_input_tool_result(self) -> None:
        msgs = [Message(role=Role.TOOL, content="output", tool_call_id="tc1")]
        result = _to_responses_input(msgs)
        assert result == [{"type": "function_call_output", "call_id": "tc1", "output": "output"}]

    def test_to_responses_input_assistant_tool_calls(self) -> None:
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="tc1", name="run", arguments={"cmd": "ls"})],
            )
        ]
        result = _to_responses_input(msgs)
        assert result == [
            {"type": "function_call", "call_id": "tc1", "name": "run", "arguments": '{"cmd": "ls"}'}
        ]

    def test_to_responses_tools(self) -> None:
        tools = [ToolSchema(name="run", description="run cmd", parameters={"type": "object"})]
        result = _to_responses_tools(tools)
        assert result[0] == {
            "type": "function",
            "name": "run",
            "description": "run cmd",
            "parameters": {"type": "object"},
        }

    def test_parse_output_text(self) -> None:
        text, tool_calls = _parse_output([_mock_message_item("hello"), _mock_message_item(" world")])
        assert text == "hello world"
        assert tool_calls == []

    def test_parse_output_function_call(self) -> None:
        text, tool_calls = _parse_output([_mock_function_call_item()])
        assert text == ""
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "run"
        assert tool_calls[0].arguments == {"cmd": "ls"}

    def test_parse_output_function_call_bad_json(self) -> None:
        _, tool_calls = _parse_output([_mock_function_call_item(arguments="not-json")])
        assert tool_calls[0].arguments == {}

    def test_build_usage(self) -> None:
        usage = _build_usage(_mock_usage())
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 5
        assert usage.total_tokens == 15

    def test_build_usage_none(self) -> None:
        usage = _build_usage(None)
        assert usage.total_tokens == 0


class TestProtocol:
    def test_satisfies_base_provider(self) -> None:
        p = OpenAIResponsesProvider(api_key="sk-test")
        assert isinstance(p, BaseProvider)


class TestSend:
    @patch("heagent.providers.responses.AsyncOpenAI")
    async def test_send_basic(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.responses.create = AsyncMock(return_value=_mock_response([_mock_message_item("Hello!")]))

        p = OpenAIResponsesProvider(api_key="sk-test")
        resp = await p.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "Hello!"
        assert resp.model == "gpt-5.6-terra"
        assert resp.finish_reason == "stop"

    @patch("heagent.providers.responses.AsyncOpenAI")
    async def test_send_with_tool_call(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.responses.create = AsyncMock(return_value=_mock_response([_mock_function_call_item()]))

        p = OpenAIResponsesProvider(api_key="sk-test")
        resp = await p.send([Message(role=Role.USER, content="run ls")])
        assert resp.finish_reason == "tool_calls"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "run"

    @patch("heagent.providers.responses.AsyncOpenAI")
    async def test_send_usage(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.responses.create = AsyncMock(
            return_value=_mock_response([_mock_message_item("ok")], usage=_mock_usage(3, 2, 5))
        )

        resp = await OpenAIResponsesProvider(api_key="sk-test").send([Message(role=Role.USER, content="hi")])
        assert resp.usage.total_tokens == 5


class TestStream:
    @patch("heagent.providers.responses.AsyncOpenAI")
    async def test_stream_yields_text_deltas(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        events = [
            _mock_event("response.output_text.delta", delta="Hello"),
            _mock_event("response.output_text.delta", delta=" world"),
            _mock_event("response.completed", response=_mock_response([_mock_message_item("Hello world")])),
        ]
        mock_client.responses.create = AsyncMock(return_value=_FakeAsyncStream(events))

        p = OpenAIResponsesProvider(api_key="sk-test")
        chunks = [c async for c in p.stream([Message(role=Role.USER, content="hi")])]
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        # 最终 chunk 携带 usage + finish_reason
        assert chunks[-1].finish_reason == "stop"
        assert chunks[-1].usage.total_tokens == 15

    @patch("heagent.providers.responses.AsyncOpenAI")
    async def test_stream_tool_call(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        events = [
            _mock_event("response.output_text.delta", delta=""),
            _mock_event(
                "response.completed",
                response=_mock_response([_mock_function_call_item()], usage=_mock_usage(4, 3, 7)),
            ),
        ]
        mock_client.responses.create = AsyncMock(return_value=_FakeAsyncStream(events))

        chunks = [
            c
            async for c in OpenAIResponsesProvider(api_key="sk-test").stream(
                [Message(role=Role.USER, content="run ls")]
            )
        ]
        final = chunks[-1]
        assert final.finish_reason == "tool_calls"
        assert len(final.tool_calls) == 1
        assert final.tool_calls[0].name == "run"
        assert final.usage.total_tokens == 7


class _FakeSdkError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TestErrorWrapping:
    @patch("heagent.providers.responses.AsyncOpenAI")
    async def test_send_wraps_sdk_error(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.responses.create = AsyncMock(side_effect=_FakeSdkError("Rate limit exceeded", 429))

        p = OpenAIResponsesProvider(api_key="sk-test")
        with pytest.raises(ProviderError) as exc_info:
            await p.send([Message(role=Role.USER, content="hi")])
        assert exc_info.value.status_code == 429

    @patch("heagent.providers.responses.AsyncOpenAI")
    async def test_stream_wraps_sdk_error(self, mock_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.responses.create = AsyncMock(side_effect=_FakeSdkError("overloaded", 503))

        p = OpenAIResponsesProvider(api_key="sk-test")
        with pytest.raises(ProviderError) as exc_info:
            async for _ in p.stream([Message(role=Role.USER, content="hi")]):
                pass
        assert exc_info.value.status_code == 503


class TestConstruction:
    def test_metadata(self) -> None:
        p = OpenAIResponsesProvider(api_key="sk-test", model="gpt-5.6-terra")
        meta = p.get_metadata()
        assert meta.name == "openai-responses"
        assert meta.supports_streaming is True
        assert meta.supports_tools is True

    @patch("heagent.providers.responses.AsyncOpenAI")
    def test_custom_base_url_and_ua_override(self, mock_cls: MagicMock) -> None:
        OpenAIResponsesProvider(api_key="sk-test", base_url="http://localhost:1234/v1")
        mock_cls.assert_called_once_with(
            api_key="sk-test",
            base_url="http://localhost:1234/v1",
            default_headers={"User-Agent": "Mozilla/5.0"},
        )

    @patch("heagent.providers.responses.AsyncOpenAI")
    def test_custom_user_agent(self, mock_cls: MagicMock) -> None:
        OpenAIResponsesProvider(api_key="sk-test", user_agent="heagent/0.5")
        mock_cls.assert_called_once_with(
            api_key="sk-test",
            base_url=None,
            default_headers={"User-Agent": "heagent/0.5"},
        )
