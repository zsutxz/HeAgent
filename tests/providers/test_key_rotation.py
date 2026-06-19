"""Tests for KeyRotatingProvider — 密钥池轮换。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from heagent.exceptions import ProviderError
from heagent.providers.base import ProviderMetadata
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.openai import OpenAIProvider
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolSchema


def _make_provider(
    name: str,
    content: str = "ok",
    *,
    fail_with: ProviderError | None = None,
) -> object:
    """创建模拟 Provider，可配置失败行为。"""

    class FakeProvider:
        _name = name
        _content = content
        _fail_with = fail_with

        async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
            if self._fail_with:
                raise self._fail_with
            return ProviderResponse(
                content=self._content,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model=self._name,
                finish_reason="stop",
            )

        async def stream(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> AsyncIterator[ProviderResponse]:
            if self._fail_with:
                raise self._fail_with
            yield ProviderResponse(
                content=self._content,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model=self._name,
                finish_reason="stop",
            )

        def get_metadata(self) -> ProviderMetadata:
            return ProviderMetadata(name=self._name, model=self._name, supports_streaming=True, supports_tools=True)

    return FakeProvider()


class TestKeyRotatingProvider:
    def test_requires_at_least_one(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            KeyRotatingProvider([])

    async def test_send_uses_first_key(self) -> None:
        rp = KeyRotatingProvider([_make_provider("a", "hello")])
        resp = await rp.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "hello"

    async def test_send_rotates_on_429(self) -> None:
        rp = KeyRotatingProvider([
            _make_provider("a", fail_with=ProviderError("rate limited", status_code=429)),
            _make_provider("b", "fallback"),
        ])
        resp = await rp.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "fallback"

    async def test_send_rotates_on_401(self) -> None:
        rp = KeyRotatingProvider([
            _make_provider("a", fail_with=ProviderError("auth failed", status_code=401)),
            _make_provider("b", "ok"),
        ])
        resp = await rp.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "ok"

    async def test_send_raises_non_rotation_error(self) -> None:
        rp = KeyRotatingProvider([
            _make_provider("a", fail_with=ProviderError("server error", status_code=500)),
            _make_provider("b", "unused"),
        ])
        with pytest.raises(ProviderError, match="server error"):
            await rp.send([Message(role=Role.USER, content="hi")])

    async def test_send_all_keys_exhausted(self) -> None:
        rp = KeyRotatingProvider([
            _make_provider("a", fail_with=ProviderError("rate", status_code=429)),
            _make_provider("b", fail_with=ProviderError("rate", status_code=429)),
        ])
        with pytest.raises(ProviderError, match="rate"):
            await rp.send([Message(role=Role.USER, content="hi")])

    async def test_send_resets_index_after_exhaustion(self) -> None:
        """密钥池耗尽后，索引应恢复到起始位置。"""
        rp = KeyRotatingProvider([
            _make_provider("a", fail_with=ProviderError("rate", status_code=429)),
            _make_provider("b", fail_with=ProviderError("rate", status_code=429)),
        ])
        with pytest.raises(ProviderError):
            await rp.send([Message(role=Role.USER, content="hi")])
        # 索引应恢复到 0
        assert rp._current_index == 0

    async def test_stream_uses_first_key(self) -> None:
        rp = KeyRotatingProvider([_make_provider("a", "chunk")])
        chunks = [c async for c in rp.stream([Message(role=Role.USER, content="hi")])]
        assert chunks[0].content == "chunk"

    async def test_stream_rotates_on_429(self) -> None:
        rp = KeyRotatingProvider([
            _make_provider("a", fail_with=ProviderError("rate", status_code=429)),
            _make_provider("b", "stream-ok"),
        ])
        chunks = [c async for c in rp.stream([Message(role=Role.USER, content="hi")])]
        assert chunks[0].content == "stream-ok"

    async def test_stream_all_keys_exhausted(self) -> None:
        rp = KeyRotatingProvider([
            _make_provider("a", fail_with=ProviderError("rate", status_code=429)),
            _make_provider("b", fail_with=ProviderError("rate", status_code=429)),
        ])
        with pytest.raises(ProviderError, match="All keys exhausted"):
            async for _ in rp.stream([Message(role=Role.USER, content="hi")]):
                pass

    def test_metadata_includes_keypool(self) -> None:
        rp = KeyRotatingProvider([_make_provider("openai")])
        meta = rp.get_metadata()
        assert "+keypool" in meta.name
        assert meta.supports_streaming is True

    def test_current_property(self) -> None:
        rp = KeyRotatingProvider([_make_provider("a"), _make_provider("b")])
        assert rp.current.get_metadata().name == "a"

    async def test_rotation_by_message_keyword(self) -> None:
        """通过错误消息中的关键词触发轮换（无 status_code）。"""
        rp = KeyRotatingProvider([
            _make_provider("a", fail_with=ProviderError("Rate limit exceeded")),
            _make_provider("b", "ok"),
        ])
        resp = await rp.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "ok"


class _FakeSdkError(Exception):
    """模拟 openai SDK 的 APIStatusError：带 status_code 与 message（非 ProviderError）。"""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _ok_openai_response(content: str = "ok") -> SimpleNamespace:
    """构造 OpenAIProvider.send 能正常解析的成功响应。"""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason="stop",
            )
        ],
        model="gpt-4o",
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


class TestRotationWithRealProvider:
    """用真实 OpenAIProvider（mock SDK 抛原始异常）验证密钥轮换在生产行为下生效。"""

    @patch("heagent.providers.openai.AsyncOpenAI")
    async def test_rotates_on_real_sdk_429(self, mock_cls: MagicMock) -> None:
        """真实 OpenAIProvider 抛 SDK 风格 429 时，KeyRotatingProvider 应轮换到下一 key。

        修复前：openai.send 抛原始 _FakeSdkError（非 ProviderError）→ _is_rotation_error
        判定 False → 立即 re-raise，不轮换（密钥轮换在生产路径下是死代码）。
        修复后：openai.send 包装为 ProviderError(status_code=429) → 轮换生效。
        """
        client_a = AsyncMock()
        client_a.chat.completions.create = AsyncMock(
            side_effect=_FakeSdkError("rate limited", 429)
        )
        client_b = AsyncMock()
        client_b.chat.completions.create = AsyncMock(return_value=_ok_openai_response("from-key-b"))
        # 每次 OpenAIProvider(...) 构造消耗一个 mock client
        mock_cls.side_effect = [client_a, client_b]

        p_a = OpenAIProvider(api_key="sk-a")
        p_b = OpenAIProvider(api_key="sk-b")
        rp = KeyRotatingProvider([p_a, p_b])

        resp = await rp.send([Message(role=Role.USER, content="hi")])
        assert resp.content == "from-key-b"  # 轮换到 B 后成功
        assert rp._current_index == 1
