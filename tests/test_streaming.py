"""Tests for AgentLoop.run_stream() — 流式输出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.agent.loop import AgentLoop
from heagent.providers.base import ProviderMetadata
from heagent.tools.registry import ToolRegistry
from heagent.pub.types import Message, ProviderResponse, StreamEvent, TokenUsage, ToolCall

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

    async def test_tracks_last_context_tokens(self) -> None:
        """run 结束后 last_context_tokens 反映当前上下文占用（>0，区别于累计 last_usage）。"""
        provider = StreamStubProvider(["answer"])
        loop = AgentLoop(provider)
        async for _ in loop.run_stream("hi"):
            pass

        assert loop.last_context_tokens > 0

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

    async def test_tool_call_event_carries_target_and_precedes_execution(self) -> None:
        """tool_call 事件带「作用对象」摘要，且在工具真正执行之前发出（展示层据此时时提示）。"""
        from heagent.tools.decorator import tool

        executed: list[str] = []

        @tool
        async def probe_tool(path: str) -> str:
            """Read a file-like path."""
            executed.append(path)
            return f"content of {path}"

        registry = ToolRegistry.get()
        tool_call = ToolCall(id="tc1", name="probe_tool", arguments={"path": "docs/frame.md"})
        tc_response = ProviderResponse(
            content="",
            tool_calls=[tool_call],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="stub",
            finish_reason="tool_calls",
        )
        provider = StreamStubProvider(chunks=[""], tool_calls_response=tc_response, stream_finish_reason="tool_calls")
        loop = AgentLoop(provider, registry=registry)
        try:
            announced: list[StreamEvent] = []
            events: list[StreamEvent] = []
            async for event in loop.run_stream("test"):
                if event.type == "tool_call":
                    announced.append(event)
                    # 公告必须早于执行——此刻 handler 尚未被调用。
                    assert executed == []
                events.append(event)

            assert [(e.tool_name, e.tool_target) for e in announced] == [("probe_tool", "docs/frame.md")]
            assert executed == ["docs/frame.md"]
            types = [e.type for e in events]
            assert types.index("tool_call") < types.index("tool_result")
        finally:
            registry.unregister("probe_tool")

    async def test_tool_result_event_marks_failure(self) -> None:
        """工具 handler 抛异常 → tool_result 带 tool_error=True（展示层据此归因失败）。"""
        from heagent.tools.decorator import tool

        @tool
        async def boom_tool(path: str) -> str:
            """Always fails."""
            raise RuntimeError(f"cannot read {path}")

        registry = ToolRegistry.get()
        tool_call = ToolCall(id="tc1", name="boom_tool", arguments={"path": "missing.txt"})
        tc_response = ProviderResponse(
            content="",
            tool_calls=[tool_call],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="stub",
            finish_reason="tool_calls",
        )
        provider = StreamStubProvider(chunks=[""], tool_calls_response=tc_response, stream_finish_reason="tool_calls")
        loop = AgentLoop(provider, registry=registry)
        try:
            events = [e async for e in loop.run_stream("test")]

            calls = [e for e in events if e.type == "tool_call"]
            results = [e for e in events if e.type == "tool_result"]
            assert [(e.tool_name, e.tool_target) for e in calls] == [("boom_tool", "missing.txt")]
            assert [(e.tool_name, e.tool_error) for e in results] == [("boom_tool", True)]
            assert "cannot read missing.txt" in results[0].tool_result_content
        finally:
            registry.unregister("boom_tool")


class _EventRecorder:
    """最小 EventBus 观察者（记录事件类型序列）。"""

    def __init__(self) -> None:
        self.events: list[str] = []

    def handle(self, event) -> None:  # noqa: ANN001 - 引擎事件类型
        self.events.append(event.event_type)


class TestAbandonedStream:
    """提前放弃流式输出（消费者 break / GUI 取消）必须确定性地收尾。

    回归（2026-09-22）：``run_stream`` 是 ``stream_run`` 生成器的包装层，而 ``async for``
    在被提前关闭时不会关闭内层生成器——内层只能等 event loop 的 asyncgen finalizer 在
    **另一个 Context** 里收尾，``ContextVar.reset(token)`` 因此抛 ``ValueError``，被
    ``stream_run`` 的 ``except Exception`` 当成运行失败：既写 FAILED 终态、又发
    run_failed 事件，session 落盘还被推迟到调用方返回之后。修复靠 ``contextlib.aclosing``。
    """

    async def test_abandoned_stream_persists_and_is_not_marked_failed(self, tmp_path) -> None:
        from heagent.engine.container import EngineContainer
        from heagent.engine.context import RunStatus
        from heagent.engine.ledger import ExecutionLedger
        from heagent.engine.store import RunStore

        engine = EngineContainer(
            run_store=RunStore(str(tmp_path / "runs")),
            ledger=ExecutionLedger(str(tmp_path / "ledger")),
        )
        recorder = _EventRecorder()
        engine.events.subscribe(recorder)
        loop = AgentLoop(StreamStubProvider(["Hello", " world"]), engine=engine)

        stream = loop.run_stream("hi")
        async for _event in stream:
            break
        await stream.aclose()

        # 收尾在 aclose 处同步完成（修复前此处 last_run_context 仍为 None）。
        assert loop.last_run_context is not None
        assert loop.last_run_context.status is RunStatus.RUNNING  # 提前放弃≠失败，仍可 resume
        assert "run_failed" not in recorder.events
        assert "run_started" in recorder.events
