"""Tests for context compressor."""

from __future__ import annotations

import pytest

from heagent.context.compressor import ContextCompressor
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall


class StubProvider:
    def __init__(self, summary: str = "summary") -> None:
        self._summary = summary

    async def send(self, messages: list[Message], **kw: object) -> ProviderResponse:
        return ProviderResponse(
            content=self._summary,
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], **kw: object) -> object:
        yield await self.send(messages)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _msg(role: Role, content: str) -> Message:
    return Message(role=role, content=content)


def _asst_with_tools(call_ids: list[str], content: str = "") -> Message:
    """带 tool_calls 的 ASSISTANT 消息（call_ids 各对应一条后续 TOOL 结果）。"""
    return Message(
        role=Role.ASSISTANT,
        content=content,
        tool_calls=[ToolCall(id=cid, name="search", arguments={}) for cid in call_ids],
    )


def _tool_result(call_id: str, content: str) -> Message:
    """TOOL 结果消息，tool_call_id 关联到发起调用的 ASSISTANT。"""
    return Message(role=Role.TOOL, content=content, tool_call_id=call_id, name="search")


def _no_orphan_tool(messages: list[Message]) -> bool:
    """OpenAI 不变量：每条 TOOL 消息的 tool_call_id 必须来自其前方某条 assistant(tool_calls)。

    违反即「tool message 无前置 tool_calls」，正是 400 报错的根因。
    """
    seen: set[str] = set()
    for m in messages:
        if m.role == Role.ASSISTANT and m.tool_calls:
            seen.update(tc.id for tc in m.tool_calls)
        if m.role == Role.TOOL and m.tool_call_id not in seen:
            return False
    return True


@pytest.mark.asyncio
class TestContextCompressor:
    async def test_no_compress_below_threshold(self) -> None:
        comp = ContextCompressor(StubProvider(), threshold=0.8)
        msgs = [_msg(Role.USER, "hi"), _msg(Role.ASSISTANT, "hello")]
        result = await comp.compress(msgs, token_count=10, max_tokens=100)
        assert result is msgs

    async def test_compress_above_threshold(self) -> None:
        comp = ContextCompressor(StubProvider(), threshold=0.5, keep_recent=2)
        msgs = [
            _msg(Role.SYSTEM, "sys"),
            _msg(Role.USER, "q1"),
            _msg(Role.ASSISTANT, "a1"),
            _msg(Role.USER, "q2"),
            _msg(Role.ASSISTANT, "a2"),
            _msg(Role.USER, "q3"),
            _msg(Role.ASSISTANT, "a3"),
        ]
        result = await comp.compress(msgs, token_count=3600, max_tokens=4096)
        assert len(result) < len(msgs)
        assert result[0].content == "sys"
        assert "[Conversation summary]" in result[1].content
        assert result[-2].content == "q3"
        assert result[-1].content == "a3"

    async def test_keep_recent_too_few_messages(self) -> None:
        comp = ContextCompressor(StubProvider(), threshold=0.1, keep_recent=10)
        msgs = [_msg(Role.USER, "q"), _msg(Role.ASSISTANT, "a")]
        result = await comp.compress(msgs, token_count=3600, max_tokens=4096)
        assert result is msgs

    async def test_zero_max_tokens(self) -> None:
        comp = ContextCompressor(StubProvider())
        msgs = [_msg(Role.USER, "x")]
        result = await comp.compress(msgs, token_count=50, max_tokens=0)
        assert result is msgs

    async def test_summary_content_used(self) -> None:
        comp = ContextCompressor(StubProvider(summary="key fact: answer is 42"), threshold=0.1, keep_recent=2)
        msgs = [
            _msg(Role.USER, "q1"),
            _msg(Role.ASSISTANT, "a1"),
            _msg(Role.USER, "q2"),
            _msg(Role.ASSISTANT, "a2"),
        ]
        result = await comp.compress(msgs, token_count=3600, max_tokens=4096)
        assert "42" in result[0].content

    async def test_compress_does_not_orphan_tool_messages(self) -> None:
        """回归：按条数切分曾把 assistant(tool_calls) 与其 tool 结果分入不同窗口，
        recent 以无主 TOOL 开头 → OpenAI 400「tool must follow tool_calls」。

        keep_recent=3 时朴素切分 recent=[TOOL, TOOL, ASSISTANT]，首条 TOOL 的
        assistant(tool_calls) 已被摘要抹平。修复后切分前移越过这些 TOOL，结果不再孤儿。
        """
        comp = ContextCompressor(StubProvider(), threshold=0.5, keep_recent=3)
        msgs = [
            _msg(Role.SYSTEM, "sys"),
            _msg(Role.USER, "q1"),
            _msg(Role.ASSISTANT, "a1"),
            _msg(Role.USER, "q2"),
            _asst_with_tools(["c1", "c2"], "calling tools"),
            _tool_result("c1", "r1"),
            _tool_result("c2", "r2"),
            _msg(Role.ASSISTANT, "final"),
        ]
        result = await comp.compress(msgs, token_count=3600, max_tokens=4096)
        assert _no_orphan_tool(result), "compressed history orphaned a tool message"
        assert len(result) < len(msgs)  # 确实发生了压缩
        assert result[-1].content == "final"

    async def test_compress_recent_all_tool_skips(self) -> None:
        """recent 整段都是 TOOL（无可安全保留窗口）→ 放弃压缩、原样返回，绝不产生孤儿。"""
        comp = ContextCompressor(StubProvider(), threshold=0.5, keep_recent=2)
        msgs = [
            _msg(Role.SYSTEM, "sys"),
            _msg(Role.USER, "q"),
            _msg(Role.ASSISTANT, "a"),
            _asst_with_tools(["c1"], "call"),
            _tool_result("c1", "r1"),
            _tool_result("c1", "r1b"),
        ]
        result = await comp.compress(msgs, token_count=3600, max_tokens=4096)
        assert result is msgs
        assert _no_orphan_tool(result)
