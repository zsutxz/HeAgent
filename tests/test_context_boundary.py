"""大上下文窗口边界测试 —— 接近 512K tokens 规模的压缩触发、完整性与估算准确性。

512K 来源：``Settings.max_context_tokens`` 默认 512000。覆盖四条边界：

  1. 触发边界：compressor（80% 阈值）与 window_reset（60% 阈值）在 512K 窗口下的
     「恰好达标触发 / 差一点不触发」——触发只看上报 token 数与窗口的比值，
     与消息内容实际规模无关；
  2. 压缩完整性：~512K 规模对话压缩后不变量保持——无孤儿 TOOL、系统消息保位、
     最近消息原文保留、原列表不被就地修改；
  3. 摘要输入有界性：512K 规模对话的摘要请求本身不超过 ``max_summary_tokens``，
     从末尾向前保留（最新优先、最旧先丢）——这是大规模下「不爆窗」的保证；
  4. 估算准确性与有界状态：纯启发式估算在 512K 规模下精确、``count_tokens``
     对消息列表线性缩放；重复大压缩不增长模块级缓存（按模型键控，非按调用）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from heagent.agent.context_runtime import maybe_compress
from heagent.agent.run_lifecycle import AgentState
from heagent.context import tokens as tokens_mod
from heagent.context.compressor import ContextCompressor
from heagent.context.tokens import (
    _TOKENS_PER_MESSAGE,
    _TOKENS_REPLY_PRIMING,
    count_tokens,
    estimate_text_tokens,
)
from heagent.context.window_reset import WindowReset
from heagent.pub.types import Message, ProviderResponse, Role, TokenUsage, ToolCall
from heagent.providers.base import ProviderMetadata

# Settings.max_context_tokens 默认值（512K 窗口）
MAX_CTX = 512_000
# ContextCompressor 默认触发阈值
COMPRESS_THRESHOLD = 0.8
# WindowReset 默认触发阈值
RESET_THRESHOLD = 0.6
# ContextCompressor 默认摘要输入上限
MAX_SUMMARY_TOKENS = 4096

_ASCII_CHARS_PER_TOKEN = 4
# 每轮对话的构造规格：USER 1500t + ASSISTANT 200t + TOOL×2 各 500t ≈ 2500 tokens/轮
_ROUND_USER_TOKENS = 1500
_ROUND_ASSISTANT_TOKENS = 200
_ROUND_TOOL_TOKENS = 500
# 220 轮 × ~2500t ≈ 550K tokens，稳超 512K 规模
_SCALE_ROUNDS = 220


def _ascii_tokens(n_tokens: int) -> str:
    """生成约 ``n_tokens`` 个 token 的 ASCII 文本（4 字符/token）。"""
    return "a" * (n_tokens * _ASCII_CHARS_PER_TOKEN)


def _round(i: int) -> list[Message]:
    """构造一轮对话：USER 提问 → ASSISTANT 发起两个工具调用 → 两条 TOOL 结果。"""
    return [
        Message(role=Role.USER, content=f"[R{i:03d}] " + _ascii_tokens(_ROUND_USER_TOKENS)),
        Message(
            role=Role.ASSISTANT,
            content=f"[A{i:03d}] " + _ascii_tokens(_ROUND_ASSISTANT_TOKENS),
            tool_calls=[
                ToolCall(id=f"c{i}-1", name="search", arguments={}),
                ToolCall(id=f"c{i}-2", name="read", arguments={}),
            ],
        ),
        Message(
            role=Role.TOOL,
            content=f"[T{i:03d}a] " + _ascii_tokens(_ROUND_TOOL_TOKENS),
            tool_call_id=f"c{i}-1",
            name="search",
        ),
        Message(
            role=Role.TOOL,
            content=f"[T{i:03d}b] " + _ascii_tokens(_ROUND_TOOL_TOKENS),
            tool_call_id=f"c{i}-2",
            name="read",
        ),
    ]


def _scale_conversation(rounds: int = _SCALE_ROUNDS, *, system: bool = False) -> list[Message]:
    """构造 ~512K+ tokens 规模的多轮对话。"""
    msgs: list[Message] = [Message(role=Role.SYSTEM, content="system prompt")] if system else []
    for i in range(rounds):
        msgs.extend(_round(i))
    return msgs


def _no_orphan_tool(messages: list[Message]) -> bool:
    """OpenAI 不变量：每条 TOOL 消息的 tool_call_id 必须来自其前方某条 assistant(tool_calls)。"""
    seen: set[str] = set()
    for m in messages:
        if m.role == Role.ASSISTANT and m.tool_calls:
            seen.update(tc.id for tc in m.tool_calls)
        if m.role == Role.TOOL and m.tool_call_id not in seen:
            return False
    return True


def _estimated_tokens(messages: list[Message]) -> int:
    """按启发式口径估算消息列表 token 总量（仅用于确认构造规模，不参与断言口径）。"""
    total = _TOKENS_REPLY_PRIMING
    for m in messages:
        total += _TOKENS_PER_MESSAGE
        total += estimate_text_tokens(m.content or "")
        for tc in m.tool_calls or []:
            total += estimate_text_tokens(tc.name)
            total += estimate_text_tokens(str(tc.arguments))
        if m.tool_call_id:
            total += estimate_text_tokens(m.tool_call_id)
    return total


class CapturingStubProvider:
    """记录全部 ``send`` 请求的桩 Provider——验证摘要请求的实际输入规模。"""

    def __init__(self, summary: str = "summary") -> None:
        self.summary = summary
        self.requests: list[list[Message]] = []

    async def send(self, messages: list[Message], **_kw: object) -> ProviderResponse:
        self.requests.append(messages)
        return ProviderResponse(
            content=self.summary,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="stub-capture",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], **_kw: object) -> object:
        yield await self.send(messages)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub-capture", model="stub-capture")


class TestCompressorTriggerAt512K:
    """compressor 触发边界：512K 窗口下 80% 阈值两侧的行为。"""

    async def test_just_below_threshold_no_compress(self) -> None:
        """409,599 < 0.8 × 512,000：内容本身已达 ~512K 规模，但上报数差一点 → 不压缩。"""
        comp = ContextCompressor(CapturingStubProvider())
        msgs = _scale_conversation()
        assert _estimated_tokens(msgs) >= MAX_CTX  # 内容规模真实达标
        result = await comp.compress(msgs, token_count=409_599, max_tokens=MAX_CTX)
        assert result is msgs
        assert comp.provider.requests == []  # 未触发摘要调用

    async def test_exactly_at_threshold_compresses(self) -> None:
        """409,600 / 512,000 恰等于 0.8：>= 语义触发压缩。"""
        comp = ContextCompressor(CapturingStubProvider(), keep_recent=4)
        msgs = _scale_conversation()
        result = await comp.compress(msgs, token_count=409_600, max_tokens=MAX_CTX)
        assert result is not msgs
        assert len(result) < len(msgs)

    async def test_overfull_window_compresses(self) -> None:
        """上报数超出窗口上限（600K > 512K）：防御性触发压缩。"""
        comp = ContextCompressor(CapturingStubProvider(), keep_recent=4)
        msgs = _scale_conversation()
        result = await comp.compress(msgs, token_count=600_000, max_tokens=MAX_CTX)
        assert result is not msgs
        assert len(result) < len(msgs)


class TestCompressIntegrityAtScale:
    """~512K 规模对话压缩后的结构不变量。"""

    async def test_compress_preserves_invariants_at_scale(self) -> None:
        comp = ContextCompressor(CapturingStubProvider(summary="scale summary"), keep_recent=4)
        msgs = _scale_conversation(system=True)
        original_len = len(msgs)
        result = await comp.compress(msgs, token_count=MAX_CTX, max_tokens=MAX_CTX)

        # 压缩发生且原列表不被就地修改
        assert result is not msgs
        assert len(msgs) == original_len
        # [SYSTEM, 摘要USER, recent×4]
        assert len(result) == 6
        assert result[0].role == Role.SYSTEM
        assert result[0].content == "system prompt"
        assert result[1].role == Role.USER
        assert result[1].content.startswith("[Conversation summary]")
        assert "scale summary" in result[1].content
        # OpenAI 不变量：无孤儿 TOOL
        assert _no_orphan_tool(result)
        # 最近消息原文保留（最后一条 TOOL 结果逐字保留）
        last = _round(_SCALE_ROUNDS - 1)[-1]
        assert result[-1].content == last.content


class TestSummaryInputBounded:
    """摘要输入有界性：512K 规模对话的摘要请求不携带全窗，最新优先、最旧先丢。"""

    async def test_summary_request_stays_bounded_at_scale(self) -> None:
        """~550K 规模对话的摘要请求 ≤ max_summary_tokens，且从末尾保留。"""
        provider = CapturingStubProvider()
        comp = ContextCompressor(provider, keep_recent=4)
        msgs = _scale_conversation()
        await comp.compress(msgs, token_count=MAX_CTX, max_tokens=MAX_CTX)

        assert len(provider.requests) == 1
        summary_request = provider.requests[0]
        assert len(summary_request) == 1
        content = summary_request[0].content or ""
        assert content.startswith("Summarize the conversation")
        # 有界性：无论对话多大，摘要输入不超过 max_summary_tokens
        assert estimate_text_tokens(content) <= MAX_SUMMARY_TOKENS
        # 从末尾向前保留：最后一轮 old 的标记在、前一轮与最早轮被截掉
        last_old = _SCALE_ROUNDS - 2
        assert f"[R{last_old:03d}]" in content
        assert f"[R{last_old - 1:03d}]" not in content
        assert "[R000]" not in content


class TestWindowResetBoundaryAt512K:
    """window_reset 触发边界：512K 窗口下 60% 阈值两侧的行为。"""

    async def test_boundaries(self) -> None:
        wr = WindowReset(CapturingStubProvider())
        # 307,199 < 0.6 × 512,000 → 不触发
        assert wr.should_trigger(token_count=307_199, max_tokens=MAX_CTX) is False
        # 307,200 恰等于 0.6 × 512,000 → >= 语义触发
        assert wr.should_trigger(token_count=307_200, max_tokens=MAX_CTX) is True
        # 满窗触发
        assert wr.should_trigger(token_count=MAX_CTX, max_tokens=MAX_CTX) is True
        # 窗口非正永不触发
        assert wr.should_trigger(token_count=RESET_THRESHOLD * MAX_CTX, max_tokens=0) is False


class TestTokenEstimationAtScale:
    """512K 规模下的 token 估算准确性与线性缩放。"""

    def test_ascii_exact_at_512k(self) -> None:
        assert estimate_text_tokens(_ascii_tokens(MAX_CTX)) == MAX_CTX

    def test_cjk_exact_at_512k(self) -> None:
        assert estimate_text_tokens("境" * MAX_CTX) == MAX_CTX

    def test_mixed_exact_at_512k(self) -> None:
        text = "境" * (MAX_CTX // 2) + _ascii_tokens(MAX_CTX // 2)
        assert estimate_text_tokens(text) == MAX_CTX

    def test_count_tokens_scales_linearly_at_scale(self) -> None:
        """同一消息复制 N 份：总增量恰为 (N-1) × 单份主体 token（含 tiktoken 路径也成立）。"""
        msg = Message(role=Role.USER, content=_ascii_tokens(100_000))
        one = count_tokens([msg])
        n = 6
        many = count_tokens([msg] * n)
        body = one - _TOKENS_PER_MESSAGE - _TOKENS_REPLY_PRIMING
        assert many - one == (n - 1) * (body + _TOKENS_PER_MESSAGE)
        # 总规模真实达标（~600K）
        assert many >= MAX_CTX


class TestBoundedStateAtScale:
    """大规模压缩的有界状态：模块级缓存按模型键控，不随调用次数增长。"""

    async def test_repeated_large_compress_keeps_caches_bounded(self) -> None:
        provider = CapturingStubProvider()
        comp = ContextCompressor(provider, keep_recent=4)
        before_encoding = len(tokens_mod._ENCODING_CACHE)
        before_calibration = len(tokens_mod._CALIBRATION)

        for _ in range(3):
            msgs = _scale_conversation()
            result = await comp.compress(msgs, token_count=MAX_CTX, max_tokens=MAX_CTX)
            assert result is not msgs
            assert len(result) < len(msgs)

        # send_accounted 每次记账只可能新增/更新当前模型键；encoding 缓存同理按模型键控
        assert len(tokens_mod._ENCODING_CACHE) <= before_encoding + 1
        assert len(tokens_mod._CALIBRATION) <= before_calibration + 1

    async def test_compress_does_not_mutate_input_list(self) -> None:
        comp = ContextCompressor(CapturingStubProvider(), keep_recent=4)
        msgs = _scale_conversation()
        snapshot = list(msgs)
        await comp.compress(msgs, token_count=MAX_CTX, max_tokens=MAX_CTX)
        assert msgs == snapshot


class TestMaybeCompressAtScale:
    """AgentLoop 内层的 ``maybe_compress`` 步骤在 512K 窗口下的接线行为。"""

    @staticmethod
    def _fake_loop(comp: ContextCompressor, *, emitted: list[tuple[str, dict[str, Any]]]) -> Any:
        return SimpleNamespace(
            compressor=comp,
            _runtime=SimpleNamespace(max_context_tokens=MAX_CTX),
            _emit=lambda event, **kw: emitted.append((event, kw)),
        )

    async def test_over_threshold_replaces_messages_and_emits(self) -> None:
        emitted: list[tuple[str, dict[str, Any]]] = []
        comp = ContextCompressor(CapturingStubProvider(), keep_recent=4)
        loop = self._fake_loop(comp, emitted=emitted)
        state = AgentState(messages=_scale_conversation())
        before = len(state.messages)

        usage = TokenUsage(prompt_tokens=MAX_CTX, completion_tokens=0, total_tokens=MAX_CTX)
        await maybe_compress(loop, state, SimpleNamespace(), usage)

        assert len(state.messages) < before
        assert _no_orphan_tool(state.messages)
        expected = [("context_compressed", {"before": before, "after": len(state.messages)})]
        assert [(e, kw["details"]) for e, kw in emitted] == expected

    async def test_below_threshold_keeps_identity(self) -> None:
        emitted: list[tuple[str, dict[str, Any]]] = []
        comp = ContextCompressor(CapturingStubProvider(), keep_recent=4)
        loop = self._fake_loop(comp, emitted=emitted)
        state = AgentState(messages=_scale_conversation())

        usage = TokenUsage(prompt_tokens=300_000, completion_tokens=7_199, total_tokens=307_199)
        await maybe_compress(loop, state, SimpleNamespace(), usage)

        assert any(e == "context_compressed" for e, _ in emitted) is False
        assert len(state.messages) == _SCALE_ROUNDS * 4

    async def test_missing_usage_skips(self) -> None:
        emitted: list[tuple[str, dict[str, Any]]] = []
        comp = ContextCompressor(CapturingStubProvider(), keep_recent=4)
        loop = self._fake_loop(comp, emitted=emitted)
        state = AgentState(messages=_scale_conversation())

        await maybe_compress(loop, state, SimpleNamespace(), None)

        assert emitted == []
        assert len(state.messages) == _SCALE_ROUNDS * 4
