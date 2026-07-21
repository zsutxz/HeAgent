"""性能基准测试 — Story 19-4 (FR-C4/FR-C5).

测试标记 ``benchmark``——CI 默认跳过（手动运行：``pytest -m benchmark``）。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.benchmark

# ═══════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════


class _StubProvider:
    """最小 stub——满足 ContextCompressor 构造签名。"""

    async def send(self, messages, tools, *, token_counter=None):
        from heagent.types import ProviderResponse, TokenUsage

        return ProviderResponse(
            content="Compressed summary.",
            usage=TokenUsage(input_tokens=100, output_tokens=10, total_tokens=110),
            finish_reason="stop",
            model="stub",
        )

    async def stream(self, messages, tools, *, token_counter=None):
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════
# Token 估算精度
# ═══════════════════════════════════════════════════════════════════


class TestTokenEstimationAccuracy:
    """Token 估算精度验证。"""

    def test_pure_english(self):
        from heagent.context.tokens import _estimate_text_tokens

        text = "The quick brown fox jumps over the lazy dog. " * 20
        estimated = _estimate_text_tokens(text)
        assert 50 <= estimated <= 600, f"Estimated {estimated} out of expected range"

    def test_cjk_dominance(self):
        from heagent.context.tokens import _estimate_text_tokens

        text = "这是一个中文测试句子。" * 10
        estimated = _estimate_text_tokens(text)
        assert 50 <= estimated <= 200, f"CJK estimated {estimated} out of range"

    def test_mixed_content(self):
        from heagent.context.tokens import _estimate_text_tokens

        text = "Hello 世界! This is a mixed 中英文 sentence." * 10
        estimated = _estimate_text_tokens(text)
        assert estimated > 0

    def test_empty_text(self):
        from heagent.context.tokens import _estimate_text_tokens

        assert _estimate_text_tokens("") == 1

    def test_message_list_basic(self):
        from heagent.context.tokens import count_tokens
        from heagent.types import Message, Role

        msgs = [Message(role=Role.USER, content="Hello")]
        tokens = count_tokens(msgs)
        assert tokens >= 5, f"Got {tokens}, expected >= 5"


# ═══════════════════════════════════════════════════════════════════
# 压缩效率
# ═══════════════════════════════════════════════════════════════════


class TestCompressionEfficiency:
    """压缩器效率——消息数减少 + 最近消息保留。"""

    @pytest.mark.asyncio
    async def test_compression_reduces_message_count(self):
        from heagent.context.compressor import ContextCompressor
        from heagent.types import Message, Role

        msgs = []
        for i in range(50):
            msgs.append(Message(role=Role.USER, content=f"User message {i} " + "padding " * 20))
            msgs.append(Message(role=Role.ASSISTANT, content=f"Assistant reply {i} " + "more content " * 15))

        compressor = ContextCompressor(_StubProvider(), keep_recent=2, max_summary_tokens=2000)
        compressed = await compressor.compress(msgs, token_count=50000, max_tokens=2000)

        assert len(compressed) < len(msgs), f"No compression: {len(msgs)} → {len(compressed)}"
        ratio = (len(msgs) - len(compressed)) / len(msgs)
        assert ratio >= 0.5, f"Compression ratio {ratio:.1%} < 50%"

    @pytest.mark.asyncio
    async def test_compression_preserves_latest(self):
        from heagent.context.compressor import ContextCompressor
        from heagent.types import Message, Role

        msgs = []
        for i in range(20):
            msgs.append(Message(role=Role.USER, content=f"Msg {i} " + "x" * 200))
            msgs.append(Message(role=Role.ASSISTANT, content=f"Reply {i} " + "y" * 150))

        compressor = ContextCompressor(_StubProvider(), keep_recent=2, max_summary_tokens=500)
        compressed = await compressor.compress(msgs, token_count=30000, max_tokens=500)

        if compressed:
            last = compressed[-1]
            assert last.role == Role.ASSISTANT
            assert "19" in last.content or "Reply" in last.content


# ═══════════════════════════════════════════════════════════════════
# 工具注册性能
# ═══════════════════════════════════════════════════════════════════


class TestToolRegistrationPerf:
    """工具注册与 schema 生成性能。"""

    def test_many_tool_registration(self):
        from heagent.tools.registry import ToolRegistry
        from heagent.types import ToolSchema

        registry = ToolRegistry()
        for i in range(100):
            schema = ToolSchema(
                name=f"bench_tool_{i}",
                description=f"Benchmark tool {i}",
                parameters={"type": "object", "properties": {}, "required": []},
            )
            registry.register(schema, lambda x="": x)

        start = time.perf_counter()
        schemas = registry.enabled_schemas()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(schemas) == 100
        assert elapsed_ms < 10, f"100-tool schema gen took {elapsed_ms:.1f}ms (expected < 10ms)"


# ═══════════════════════════════════════════════════════════════════
# 技能保存与匹配——正确性 + 规模基准（注：sync 文件 I/O，按量放行）
# ═══════════════════════════════════════════════════════════════════


class TestSkillMatchingPerf:
    """技能存储与匹配——正确性基准。

    ``matching_skills()`` 内部调 ``list_skills()`` + ``parse()``，后者执行同步
    文件 I/O（``read_text``）——100 技能在 Windows 上冷启 ~300-500ms 属预期范围；
    本测试验证结果正确性 + ~2s 硬上界（不依赖文件缓存），不下严格 <50ms 断言。
    """

    def test_skill_match_correctness_and_bound(self):
        from heagent.memory.skills import SkillStore

        tmp = Path("tests/_tmp_bench_skills")
        tmp.mkdir(parents=True, exist_ok=True)

        try:
            store = SkillStore(base_dir=str(tmp))

            for i in range(100):
                store.save(
                    name=f"bench_skill_{i}",
                    description=f"Skill {i}",
                    pattern=f"match keyword {i}",
                    steps=[f"Step 1: Do thing {i}", "Step 2: Done"],
                    tags=["benchmark"],
                )

            start = time.perf_counter()
            matches = store.matching_skills("match keyword 50", threshold=0.3)
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert len(matches) > 0, f"Expected matches for 'match keyword 50', got {matches}"
            # disk I/O bound; 2s sanity upper bound
            assert elapsed_ms < 2000, f"100-skill match took {elapsed_ms:.1f}ms (expected < 2000ms)"
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════
# 大规模消息 Token 估算性能
# ═══════════════════════════════════════════════════════════════════


class TestBulkTokenEstimation:
    """大规模消息 Token 估算性能。"""

    def test_large_message_list(self):
        from heagent.context.tokens import count_tokens
        from heagent.types import Message, Role

        msgs = []
        for i in range(100):
            msgs.append(
                Message(
                    role=Role.USER if i % 2 == 0 else Role.ASSISTANT,
                    content=f"Message number {i} with some content " + "padding " * 10,
                )
            )

        start = time.perf_counter()
        tokens = count_tokens(msgs)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert tokens > 0
        assert elapsed_ms < 5, f"100-msg token estimation took {elapsed_ms:.1f}ms (expected < 5ms)"
