"""Tests for ProviderChain."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from heagent.exceptions import ProviderError
from heagent.providers.base import ProviderMetadata
from heagent.providers.chain import ProviderChain
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolSchema


def _make_provider(
    name: str,
    content: str = "ok",
    *,
    fail: bool = False,
    fail_stream: bool = False,
    fail_stream_mid: bool = False,
    fail_status: int = 503,
) -> object:
    """构造测试用 FakeProvider。

    fail_status 决定失败错误的分类：503（默认）= TRANSIENT 会触发回退；
    400/422 = NON_TRANSIENT 不应回退。send_calls/stream_calls 记录调用次数。
    fail_stream_mid：在 yield 首个 chunk 之后再抛异常，模拟流中途断开。
    """
    class FakeProvider:
        _name = name
        _content = content
        _fail = fail
        _fail_stream = fail_stream
        _fail_stream_mid = fail_stream_mid
        _fail_status = fail_status
        send_calls = 0
        stream_calls = 0

        async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
            self.send_calls += 1
            if self._fail:
                raise ProviderError(f"{self._name} send failed", status_code=self._fail_status)
            return ProviderResponse(content=self._content, usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2), model=self._name, finish_reason="stop")

        async def stream(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> AsyncIterator[ProviderResponse]:
            self.stream_calls += 1
            if self._fail_stream:
                raise ProviderError(f"{self._name} stream failed", status_code=self._fail_status)
            yield ProviderResponse(content=self._content, usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2), model=self._name, finish_reason="stop")
            if self._fail_stream_mid:
                raise ProviderError(f"{self._name} stream broke mid-flight", status_code=self._fail_status)

        def get_metadata(self) -> ProviderMetadata:
            return ProviderMetadata(name=self._name, model=self._name)

    return FakeProvider()


class TestChain:
    def test_requires_at_least_one(self) -> None:
        with pytest.raises(ValueError):
            ProviderChain([])

    def test_current_returns_first(self) -> None:
        chain = ProviderChain([_make_provider("a"), _make_provider("b")])
        assert chain.current.get_metadata().name == "a"

    async def test_send_uses_current(self) -> None:
        chain = ProviderChain([_make_provider("a", "hello")])
        resp = await chain.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "hello"

    async def test_send_fallback_on_failure(self) -> None:
        chain = ProviderChain([_make_provider("a", fail=True), _make_provider("b", "fallback")])
        resp = await chain.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "fallback"

    async def test_send_all_fail_raises(self) -> None:
        chain = ProviderChain([_make_provider("a", fail=True), _make_provider("b", fail=True)])
        with pytest.raises(ProviderError):
            await chain.send([Message(role=Role.USER, content="hi")])

    async def test_send_no_fallback_on_client_error(self) -> None:
        """NON_TRANSIENT（400/422 等客户端错误）不应回退到下一个 Provider（FR-4 精度）。"""
        a = _make_provider("a", fail=True, fail_status=400)
        b = _make_provider("b", "should-not-reach")
        chain = ProviderChain([a, b])
        with pytest.raises(ProviderError, match="a send failed") as exc_info:
            await chain.send([Message(role=Role.USER, content="hi")])
        # b 未被调用（send_calls == 0），且错误状态码保留
        assert b.send_calls == 0
        assert exc_info.value.status_code == 400
        # 索引重置回主 Provider，下一次请求从 a 开始
        assert chain.current.get_metadata().name == "a"

    async def test_send_falls_back_on_rate_limit(self) -> None:
        """RATE_LIMITED（429）应回退到下一个 Provider。"""
        chain = ProviderChain([_make_provider("a", fail=True, fail_status=429), _make_provider("b", "fallback")])
        resp = await chain.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "fallback"

    async def test_send_falls_back_on_auth_error(self) -> None:
        """AUTH_FAILED（401）跨 Provider 回退（不同 Provider 各自的有效密钥）。"""
        chain = ProviderChain([_make_provider("a", fail=True, fail_status=401), _make_provider("b", "fallback")])
        resp = await chain.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "fallback"

    async def test_send_resets_to_primary_after_fallback(self) -> None:
        """回退到次 Provider 成功后，索引应复位到主 Provider（不粘性旁路）。"""
        chain = ProviderChain([_make_provider("a", fail=True, fail_status=429), _make_provider("b", "fallback")])
        resp = await chain.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "fallback"
        assert chain.current.get_metadata().name == "a"

    async def test_stream_uses_current(self) -> None:
        chain = ProviderChain([_make_provider("a", "chunk")])
        chunks = [c async for c in chain.stream([Message(role=Role.USER, content="hi")])]
        assert chunks[0].content == "chunk"

    async def test_stream_fallback(self) -> None:
        chain = ProviderChain([_make_provider("a", fail_stream=True), _make_provider("b", "stream-ok")])
        chunks = [c async for c in chain.stream([Message(role=Role.USER, content="hi")])]
        assert chunks[0].content == "stream-ok"

    async def test_stream_no_fallback_on_client_error(self) -> None:
        """流式模式同样不对 NON_TRANSIENT（400）回退。"""
        a = _make_provider("a", fail_stream=True, fail_status=400)
        b = _make_provider("b", "should-not-reach")
        chain = ProviderChain([a, b])
        with pytest.raises(ProviderError, match="a stream failed"):
            async for _ in chain.stream([Message(role=Role.USER, content="hi")]):
                pass
        assert b.stream_calls == 0

    async def test_stream_no_fallback_after_delivery(self) -> None:
        """已向下游交付 chunk 后的流中途失败不应回退——否则下一 Provider 从头重放导致重复输出。"""
        a = _make_provider("a", "partial", fail_stream_mid=True, fail_status=503)
        b = _make_provider("b", "should-not-reach")
        chain = ProviderChain([a, b])
        collected: list[str] = []
        with pytest.raises(ProviderError, match="a stream broke mid-flight"):
            async for chunk in chain.stream([Message(role=Role.USER, content="hi")]):
                collected.append(chunk.content)
        # 消费者收到了首个（也是唯一的）chunk
        assert collected == ["partial"]
        # b 未被回退调用
        assert b.stream_calls == 0
        # 索引复位回主 Provider
        assert chain.current.get_metadata().name == "a"

    async def test_stream_resets_to_primary_after_fallback(self) -> None:
        """流式回退成功后同样复位到主 Provider。"""
        chain = ProviderChain([_make_provider("a", fail_stream=True), _make_provider("b", "stream-ok")])
        chunks = [c async for c in chain.stream([Message(role=Role.USER, content="hi")])]
        assert chunks[0].content == "stream-ok"
        assert chain.current.get_metadata().name == "a"

    def test_reset(self) -> None:
        chain = ProviderChain([_make_provider("a"), _make_provider("b")])
        chain._advance()
        assert chain.current.get_metadata().name == "b"
        chain.reset()
        assert chain.current.get_metadata().name == "a"

    def test_providers_returns_copy(self) -> None:
        p = _make_provider("a")
        chain = ProviderChain([p])
        assert len(chain.providers) == 1
