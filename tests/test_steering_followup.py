"""Tests for steering / follow-up message queue (P0 — Pi-inspired two-layer loop)."""

from __future__ import annotations

import pytest

from heagent.agent.loop import AgentLoop
from heagent.config import reset_settings
from heagent.providers.base import ProviderMetadata
from heagent.tools.registry import ToolRegistry
from heagent.types import (
    Message,
    ProviderResponse,
    Role,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolSchema,
)


class StubProvider:
    """In-memory provider that returns preconfigured responses."""

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)
        self._idx = 0
        self.calls: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls.append([message.model_copy(deep=True) for message in messages])
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return ProviderResponse(
            content="no more responses",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> object:
        """Minimal stream that yields one chunk then returns."""
        resp = await self.send(messages, tools=tools)
        yield resp

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _usage() -> TokenUsage:
    return TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)


def _final(content: str) -> ProviderResponse:
    return ProviderResponse(content=content, usage=_usage(), model="stub", finish_reason="stop")


def _tc(call_id: str, name: str, args: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args or {})


def _tool_resp(calls: list[ToolCall], content: str = "") -> ProviderResponse:
    return ProviderResponse(content=content, tool_calls=calls, usage=_usage(), model="stub", finish_reason="tool_calls")


def _msg_user(text: str) -> Message:
    return Message(role=Role.USER, content=text)


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    reset_settings()
    yield
    reset_settings()


class TestSteeringQueue:
    """AC1: steering 消息在每轮 LLM 调用前注入，LLM 下一轮回答体现 steering 指令。"""

    @pytest.mark.asyncio
    async def test_steering_injected_before_provider_call(self) -> None:
        """steering 消息出现在第二轮 provider 调用的消息列表中。

        用一次 tool_call 保持内层循环不退出，让 steering 在第二轮 LLM 调用前注入。
        """
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="echo", description="echo", parameters={"type": "object", "properties": {}}),
            lambda text="default": text,
        )

        call_count = 0

        async def steering_cb() -> list[Message]:
            nonlocal call_count
            call_count += 1
            # 第一次 poll（第一轮 LLM 调用前）：空
            if call_count == 1:
                return []
            # 第二次 poll（第二轮 LLM 调用前）：注入 steering
            return [_msg_user("STEERING: change direction")]

        provider = StubProvider(
            [
                _tool_resp([_tc("1", "echo", {"text": "first"})]),  # 第一轮：返回 tool_call
                _final("answer with steering"),  # 第二轮：steering 已注入
            ]
        )
        loop = AgentLoop(provider, registry=registry, max_iterations=10, steering_callback=steering_cb)
        result = await loop.run("original prompt")

        assert result == "answer with steering"
        assert len(provider.calls) == 2
        # 第二轮消息列表中应包含 "STEERING: change direction"
        second_call_texts = [m.content for m in provider.calls[1]]
        assert any("STEERING" in t for t in second_call_texts)

    @pytest.mark.asyncio
    async def test_steering_first_call_also_receives(self) -> None:
        """steering 如果第一轮 poll 就返回消息，也会在第一个 LLM 调用中生效。"""

        async def steering_cb() -> list[Message]:
            return [_msg_user("STEERING: override immediately")]

        provider = StubProvider([_final("overridden answer")])
        loop = AgentLoop(provider, max_iterations=10, steering_callback=steering_cb)
        result = await loop.run("original prompt")

        assert result == "overridden answer"
        # steering 消息出现在第一次调用的参数中
        assert any("STEERING" in m.content for m in provider.calls[0])

    @pytest.mark.asyncio
    async def test_steering_none_callback_no_effect(self) -> None:
        """AC3: steering_callback=None 时行为与原来一致。"""
        provider = StubProvider([_final("hello world")])
        loop = AgentLoop(provider, max_iterations=10)  # no steering_callback
        result = await loop.run("say hello")
        assert result == "hello world"
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_steering_empty_return_no_effect(self) -> None:
        """steering 回调返回空列表时不影响正常流程。"""

        async def empty_steering() -> list[Message]:
            return []

        provider = StubProvider([_final("hello")])
        loop = AgentLoop(provider, max_iterations=10, steering_callback=empty_steering)
        result = await loop.run("test")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_steering_with_tool_loop(self) -> None:
        """steering 在工具执行循环中也生效。"""
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="echo", description="echo", parameters={"type": "object", "properties": {}}),
            lambda text="default": text,
        )

        call_count = 0

        async def steering_cb() -> list[Message]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return [_msg_user("STEERING: stop using tools")]
            return []

        provider = StubProvider(
            [
                _tool_resp([_tc("1", "echo", {"text": "first"})]),
                _tool_resp([_tc("2", "echo", {"text": "second"})]),  # steering should arrive before this
                _final("stopped"),
            ]
        )
        loop = AgentLoop(provider, registry=registry, max_iterations=10, steering_callback=steering_cb)
        result = await loop.run("test")
        # steering 在 call_count==2 时返回消息，应在第二轮（第二次 LLM 调用）前注入
        assert result == "stopped"
        assert call_count >= 2  # steering was polled

    @pytest.mark.asyncio
    async def test_steering_callback_exception_silent(self) -> None:
        """steering 回调抛异常不应阻断主循环。"""

        async def broken_steering() -> list[Message]:
            raise RuntimeError("steering boom")

        provider = StubProvider([_final("survived")])
        loop = AgentLoop(provider, max_iterations=10, steering_callback=broken_steering)
        result = await loop.run("test")
        assert result == "survived"


class TestFollowUpQueue:
    """AC2: follow-up 在 Agent 完成当前任务（无 tool_calls）后被 poll，
    返回消息则自动接续新一轮 LLM 调用。"""

    @pytest.mark.asyncio
    async def test_follow_up_continues_after_completion(self) -> None:
        """follow-up 使 Agent 在自然完成后继续执行。"""
        follow_up_called = False

        async def follow_up_cb() -> list[Message]:
            nonlocal follow_up_called
            if not follow_up_called:
                follow_up_called = True
                return [_msg_user("FOLLOW-UP: summarize the above")]
            return []

        provider = StubProvider([_final("task done"), _final("summary: all good")])
        loop = AgentLoop(provider, max_iterations=10, follow_up_callback=follow_up_cb)
        result = await loop.run("do task")

        assert follow_up_called
        assert result == "summary: all good"
        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_follow_up_none_callback_no_effect(self) -> None:
        """AC3: follow_up_callback=None 时行为与原来一致。"""
        provider = StubProvider([_final("done")])
        loop = AgentLoop(provider, max_iterations=10)
        result = await loop.run("test")
        assert result == "done"
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_follow_up_empty_return_no_effect(self) -> None:
        """follow-up 返回空列表时正常退出。"""

        async def empty_follow_up() -> list[Message]:
            return []

        provider = StubProvider([_final("done")])
        loop = AgentLoop(provider, max_iterations=10, follow_up_callback=empty_follow_up)
        result = await loop.run("test")
        assert result == "done"

    @pytest.mark.asyncio
    async def test_follow_up_multiple_rounds(self) -> None:
        """follow-up 可以触发多轮接续。"""
        rounds = 0

        async def follow_up_cb() -> list[Message]:
            nonlocal rounds
            rounds += 1
            if rounds <= 2:
                return [_msg_user(f"FOLLOW-UP round {rounds}")]
            return []

        provider = StubProvider([_final("step 1"), _final("step 2"), _final("step 3")])
        loop = AgentLoop(provider, max_iterations=10, follow_up_callback=follow_up_cb)
        result = await loop.run("start")

        assert result == "step 3"
        assert len(provider.calls) == 3

    @pytest.mark.asyncio
    async def test_follow_up_callback_exception_silent(self) -> None:
        """follow-up 回调抛异常不应阻断主循环。"""

        async def broken_follow_up() -> list[Message]:
            raise RuntimeError("follow-up boom")

        provider = StubProvider([_final("survived")])
        loop = AgentLoop(provider, max_iterations=10, follow_up_callback=broken_follow_up)
        result = await loop.run("test")
        assert result == "survived"


class TestCombinedSteeringFollowUp:
    """steering 和 follow-up 同时使用时的交互。"""

    @pytest.mark.asyncio
    async def test_steering_then_follow_up(self) -> None:
        """先 steering 重定向，再 follow-up 接续。"""
        steering_calls = 0

        async def steering_cb() -> list[Message]:
            nonlocal steering_calls
            steering_calls += 1
            if steering_calls == 1:
                return [_msg_user("STEERING: do task B instead")]
            return []

        follow_up_called = False

        async def follow_up_cb() -> list[Message]:
            nonlocal follow_up_called
            if not follow_up_called:
                follow_up_called = True
                return [_msg_user("FOLLOW-UP: add summary")]
            return []

        provider = StubProvider([_final("task B result"), _final("summary of B")])
        loop = AgentLoop(
            provider,
            max_iterations=10,
            steering_callback=steering_cb,
            follow_up_callback=follow_up_cb,
        )
        result = await loop.run("do task A")

        assert steering_calls >= 1
        assert follow_up_called
        assert result == "summary of B"

    @pytest.mark.asyncio
    async def test_follow_up_respects_max_iterations(self) -> None:
        """follow-up 受 max_iterations 约束。"""

        async def infinite_follow_up() -> list[Message]:
            return [_msg_user("keep going")]

        # 1 initial + 2 follow-up = 3 rounds; max_iterations=2 should hit limit
        provider = StubProvider([_final("r1"), _final("r2"), _final("r3")])
        loop = AgentLoop(provider, max_iterations=2, follow_up_callback=infinite_follow_up)

        from heagent.exceptions import BudgetExceeded

        with pytest.raises(BudgetExceeded):
            await loop.run("test")

    @pytest.mark.asyncio
    async def test_steering_with_follow_up_during_tools(self) -> None:
        """steering + follow-up 在工具循环中同时生效。"""
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="echo", description="echo", parameters={"type": "object", "properties": {}}),
            lambda text="default": text,
        )

        steering_count = 0

        async def steering_cb() -> list[Message]:
            nonlocal steering_count
            steering_count += 1
            if steering_count == 2:
                return [_msg_user("STEERING: finish now")]
            return []

        follow_up_count = 0

        async def follow_up_cb() -> list[Message]:
            nonlocal follow_up_count
            follow_up_count += 1
            if follow_up_count == 1:
                return [_msg_user("FOLLOW-UP: one more task")]
            return []

        provider = StubProvider(
            [
                _tool_resp([_tc("1", "echo", {"text": "a"})]),  # inner: tool call → continues
                _final("done after steering"),  # inner: steering says finish → exits
                _final("follow-up task result"),  # outer: follow-up → new round
            ]
        )
        loop = AgentLoop(
            provider,
            registry=registry,
            max_iterations=10,
            steering_callback=steering_cb,
            follow_up_callback=follow_up_cb,
        )
        result = await loop.run("start")
        assert result == "follow-up task result"
        assert follow_up_count >= 1


class TestStreamSteeringFollowUp:
    """AC4: run_stream() 同样支持 steering/follow-up。"""

    @pytest.mark.asyncio
    async def test_stream_steering_injected(self) -> None:
        """流式模式下 steering 也生效。

        用一次 tool_call 保持内层不退出，让 steering 在第二轮 LLM 调用前注入。
        """
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="echo", description="echo", parameters={"type": "object", "properties": {}}),
            lambda text="default": text,
        )

        call_count = 0

        async def steering_cb() -> list[Message]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            return [_msg_user("STEERING: redirect")]

        provider = StubProvider(
            [
                _tool_resp([_tc("1", "echo", {"text": "first"})]),  # tool call → inner loop continues
                _final("redirected response"),  # steering injected before this
            ]
        )
        loop = AgentLoop(provider, registry=registry, max_iterations=10, steering_callback=steering_cb)

        events: list[StreamEvent] = []
        async for event in loop.run_stream("test"):
            events.append(event)

        assert call_count >= 2
        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert done_events[0].final_answer == "redirected response"

    @pytest.mark.asyncio
    async def test_stream_follow_up_continues(self) -> None:
        """流式模式下 follow-up 也生效。"""
        follow_up_called = False

        async def follow_up_cb() -> list[Message]:
            nonlocal follow_up_called
            if not follow_up_called:
                follow_up_called = True
                return [_msg_user("FOLLOW-UP: more")]
            return []

        provider = StubProvider([_final("step 1"), _final("step 2")])
        loop = AgentLoop(provider, max_iterations=10, follow_up_callback=follow_up_cb)

        events: list[StreamEvent] = []
        async for event in loop.run_stream("test"):
            events.append(event)

        assert follow_up_called
        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert done_events[0].final_answer == "step 2"

    @pytest.mark.asyncio
    async def test_stream_no_callbacks_zero_regression(self) -> None:
        """AC3 + AC4: 流式无回调时行为不变。"""
        provider = StubProvider([_final("stream done")])
        loop = AgentLoop(provider, max_iterations=10)

        events: list[StreamEvent] = []
        async for event in loop.run_stream("test"):
            events.append(event)

        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert done_events[0].final_answer == "stream done"
