"""Tests for AgentLoop.run_stream() — 流式输出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.agent.loop import AgentLoop
from heagent.providers.base import ProviderMetadata
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class StreamStubProvider:
    """模拟流式 Provider — 逐块返回文本。"""

    def __init__(
        self,
        chunks: list[str],
        *,
        tool_calls_response: ProviderResponse | None = None,
        stream_finish_reason: str = "stop",
        stream_usage: TokenUsage | None = None,
    ) -> None:
        self._chunks = chunks
        self._tool_calls_response = tool_calls_response
        self._stream_finish_reason = stream_finish_reason
        self._stream_usage = stream_usage or TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        self._send_count = 0

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:
        self._send_count += 1
        if self._tool_calls_response and self._send_count == 1:
            return self._tool_calls_response
        full = "".join(self._chunks)
        return ProviderResponse(
            content=full or "final answer",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=10, total_tokens=15),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools=None) -> AsyncIterator[ProviderResponse]:
        for i, chunk in enumerate(self._chunks):
            is_last = i == len(self._chunks) - 1
            yield ProviderResponse(
                content=chunk,
                usage=self._stream_usage
                if is_last
                else TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                model="stub",
                finish_reason=self._stream_finish_reason if is_last else "",
            )

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub", supports_streaming=True)


class TestRunStream:
    async def test_yields_text_events(self) -> None:
        provider = StreamStubProvider(["Hello", " world", "!"])
        loop = AgentLoop(provider)
        events = [e async for e in loop.run_stream("hi")]

        text_events = [e for e in events if e.type == "text"]
        assert len(text_events) == 3
        assert text_events[0].text == "Hello"
        assert text_events[1].text == " world"
        assert text_events[2].text == "!"

    async def test_yields_done_event(self) -> None:
        provider = StreamStubProvider(["answer"])
        loop = AgentLoop(provider)
        events = [e async for e in loop.run_stream("hi")]

        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert done_events[0].final_answer == "answer"

    async def test_accumulates_token_usage(self) -> None:
        usage = TokenUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8)
        provider = StreamStubProvider(["hello"], stream_usage=usage)
        loop = AgentLoop(provider)
        async for _ in loop.run_stream("hi"):
            pass

        assert loop.last_usage is not None
        assert loop.last_usage.total_tokens > 0

    async def test_stream_events_order(self) -> None:
        """所有 text 事件应在 done 之前。"""
        provider = StreamStubProvider(["a", "b"])
        loop = AgentLoop(provider)
        events = [e async for e in loop.run_stream("hi")]

        types = [e.type for e in events]
        assert types[-1] == "done"
        assert all(t == "text" for t in types[:-1])

    async def test_single_chunk(self) -> None:
        provider = StreamStubProvider(["complete answer"])
        loop = AgentLoop(provider)
        events = [e async for e in loop.run_stream("hi")]

        text_events = [e for e in events if e.type == "text"]
        assert len(text_events) == 1
        assert text_events[0].text == "complete answer"

    async def test_tool_calls_with_send_fallback(self) -> None:
        """当 stream 返回 finish_reason=tool_calls 时，回退到 send()。"""
        from heagent.tools.decorator import tool

        @tool
        async def echo_tool(text: str) -> str:
            """Echo the input text."""
            return text

        registry = ToolRegistry.get()
        tool_call = ToolCall(id="tc1", name="echo_tool", arguments={"text": "hi"})
        tc_response = ProviderResponse(
            content="",
            tool_calls=[tool_call],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="stub",
            finish_reason="tool_calls",
        )

        provider = StreamStubProvider(
            chunks=[""],
            tool_calls_response=tc_response,
            stream_finish_reason="tool_calls",
        )
        loop = AgentLoop(provider, registry=registry)
        try:
            events = [e async for e in loop.run_stream("test")]

            tc_events = [e for e in events if e.type == "tool_call"]
            tr_events = [e for e in events if e.type == "tool_result"]
            done_events = [e for e in events if e.type == "done"]
            assert len(tc_events) >= 1
            assert len(tr_events) >= 1
            assert len(done_events) == 1
        finally:
            # 只清理此测试注册的临时工具，不影响 builtin 注册表（断言失败也清理）
            registry.unregister("echo_tool")
