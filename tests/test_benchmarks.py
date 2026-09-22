"""性能基准测试 — Story 21-1 (pytest-benchmark fixture 重构).

测试标记 ``benchmark``——CI 默认跳过（手动运行：``pytest -m benchmark``）。

重构要点：``time.perf_counter()`` 手工计时 → ``benchmark`` fixture（pytest-benchmark），
支持跨 commit 性能对比。async 路径用 ``_sync`` helper 桥接。
"""

from __future__ import annotations

import asyncio
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


def _sync(fn, *args, **kwargs):
    """在全新 event loop 中跑 async fn，供 ``benchmark`` fixture 调用。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(fn(*args, **kwargs))
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════
# Token 估算精度
# ═══════════════════════════════════════════════════════════════════


class TestTokenEstimationAccuracy:
    """Token 估算精度验证 + 性能跟踪。"""

    def test_pure_english(self, benchmark):
        from heagent.context.tokens import _estimate_text_tokens

        text = "The quick brown fox jumps over the lazy dog. " * 20
        estimated = benchmark(_estimate_text_tokens, text)
        assert 50 <= estimated <= 600, f"Estimated {estimated} out of expected range"

    def test_cjk_dominance(self, benchmark):
        from heagent.context.tokens import _estimate_text_tokens

        text = "这是一个中文测试句子。" * 10
        estimated = benchmark(_estimate_text_tokens, text)
        assert 50 <= estimated <= 200, f"CJK estimated {estimated} out of range"

    def test_mixed_content(self, benchmark):
        from heagent.context.tokens import _estimate_text_tokens

        text = "Hello 世界! This is a mixed 中英文 sentence." * 10
        estimated = benchmark(_estimate_text_tokens, text)
        assert estimated > 0

    def test_empty_text(self, benchmark):
        from heagent.context.tokens import _estimate_text_tokens

        assert benchmark(_estimate_text_tokens, "") == 1

    def test_message_list_basic(self, benchmark):
        from heagent.context.tokens import count_tokens
        from heagent.types import Message, Role

        msgs = [Message(role=Role.USER, content="Hello")]
        tokens = benchmark(count_tokens, msgs)
        assert tokens >= 5, f"Got {tokens}, expected >= 5"


# ═══════════════════════════════════════════════════════════════════
# 压缩效率
# ═══════════════════════════════════════════════════════════════════


class TestCompressionEfficiency:
    """压缩器效率——消息数减少 + 最近消息保留。

    async 压缩调用经 ``_sync`` 桥接供 ``benchmark`` fixture 使用。
    """

    def test_compression_reduces_message_count(self, benchmark):
        from heagent.context.compressor import ContextCompressor
        from heagent.types import Message, Role

        msgs = []
        for i in range(50):
            msgs.append(Message(role=Role.USER, content=f"User message {i} " + "padding " * 20))
            msgs.append(Message(role=Role.ASSISTANT, content=f"Assistant reply {i} " + "more content " * 15))

        compressor = ContextCompressor(_StubProvider(), keep_recent=2, max_summary_tokens=2000)
        compressed = benchmark(_sync, compressor.compress, msgs, token_count=50000, max_tokens=2000)

        assert len(compressed) < len(msgs), f"No compression: {len(msgs)} → {len(compressed)}"
        ratio = (len(msgs) - len(compressed)) / len(msgs)
        assert ratio >= 0.5, f"Compression ratio {ratio:.1%} < 50%"

    def test_compression_preserves_latest(self, benchmark):
        from heagent.context.compressor import ContextCompressor
        from heagent.types import Message, Role

        msgs = []
        for i in range(20):
            msgs.append(Message(role=Role.USER, content=f"Msg {i} " + "x" * 200))
            msgs.append(Message(role=Role.ASSISTANT, content=f"Reply {i} " + "y" * 150))

        compressor = ContextCompressor(_StubProvider(), keep_recent=2, max_summary_tokens=500)
        compressed = benchmark(_sync, compressor.compress, msgs, token_count=30000, max_tokens=500)

        if compressed:
            last = compressed[-1]
            assert last.role == Role.ASSISTANT
            assert "19" in last.content or "Reply" in last.content


# ═══════════════════════════════════════════════════════════════════
# 工具注册性能
# ═══════════════════════════════════════════════════════════════════


class TestToolRegistrationPerf:
    """工具注册与 schema 生成性能。"""

    def test_many_tool_registration(self, benchmark):
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

        schemas = benchmark(registry.enabled_schemas)
        assert len(schemas) == 100


# ═══════════════════════════════════════════════════════════════════
# 技能保存与匹配——正确性 + 规模基准
# ═══════════════════════════════════════════════════════════════════


class TestSkillMatchingPerf:
    """技能存储与匹配——正确性基准。

    ``matching_skills()`` 内部调 ``list_skills()`` + ``parse()``，后者执行同步
    文件 I/O（``read_text``）——100 技能在 Windows 上冷启 ~300-500ms 属预期范围；
    本测试验证结果正确性，性能经 ``benchmark`` fixture 记录。
    """

    def test_skill_match_correctness(self, benchmark):
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

            matches = benchmark(store.matching_skills, "match keyword 50", threshold=0.3)
            assert len(matches) > 0, f"Expected matches for 'match keyword 50', got {matches}"
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════
# 大规模消息 Token 估算性能
# ═══════════════════════════════════════════════════════════════════


class TestBulkTokenEstimation:
    """大规模消息 Token 估算性能。"""

    def test_large_message_list(self, benchmark):
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

        tokens = benchmark(count_tokens, msgs)
        assert tokens > 0


# ═══════════════════════════════════════════════════════════════════
# Phase 5 C2：provider 延迟 / 并发工具批次 / 会话恢复 / 事件写入吞吐
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture()
def _bench_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """基准隔离：重置 Settings 单例 + cwd 锚到 tmp（engine 默认装配不写真实 .heagent）。"""
    from heagent.config import reset_settings

    reset_settings()
    monkeypatch.chdir(tmp_path)
    yield
    reset_settings()


class _FinalStubProvider:
    """单轮即返回最终答案的 stub（provider 延迟基准：测 loop 编排开销，非模型耗时）。"""

    async def send(self, messages, *, tools=None):
        from heagent.types import ProviderResponse, TokenUsage

        return ProviderResponse(
            content="final answer",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="bench-stub",
            finish_reason="stop",
        )

    async def stream(self, messages, *, tools=None):
        yield await self.send(messages, tools=tools)

    def get_metadata(self):
        from heagent.providers.base import ProviderMetadata

        return ProviderMetadata(name="bench-stub", model="bench-stub")


class TestProviderCallLatency:
    """provider 调用延迟基准：StubProvider 单迭代完整 ``loop.run``（含治理 + 事件发射）。"""

    @pytest.mark.usefixtures("_bench_env")
    def test_single_iteration_run(self, benchmark) -> None:
        from heagent.agent.loop import AgentLoop

        def run_once() -> str:
            # 每轮新建 loop：隔离 run 状态（台账/运行快照是 per-run 的）
            return (
                asyncio.get_event_loop_policy()
                .new_event_loop()
                .run_until_complete(AgentLoop(_FinalStubProvider(), max_iterations=3).run("bench"))
            )

        answer = benchmark(run_once)
        assert answer == "final answer"


class TestConcurrentToolBatch:
    """并发工具批次基准：gather N 个并发 sleep 工具，批次 wall ≈ 单工具耗时（并发生效）。"""

    def test_batch_of_8_sleeping_tools(self, benchmark) -> None:
        import time

        async def run_batch() -> float:
            async def fake_tool() -> None:
                await asyncio.sleep(0.02)

            started = time.perf_counter()
            await asyncio.gather(*(fake_tool() for _ in range(8)))
            return time.perf_counter() - started

        wall = benchmark(lambda: _sync(run_batch))
        # 并发生效断言：批次 wall 应接近单工具 sleep（0.02s）而非串行和（0.16s）。
        # 宽松上界（< 0.10s）防 CI 抖动误报——数量级守护，非微优化门禁。
        assert wall < 0.10, f"concurrent batch took {wall:.3f}s — concurrency degraded?"


class TestSessionRestoreRun:
    """会话恢复基准：带 20 条历史消息的 SessionStore 跑一轮完整 run。"""

    @pytest.mark.usefixtures("_bench_env")
    def test_run_with_restored_history(self, benchmark) -> None:
        from heagent.agent.loop import AgentLoop
        from heagent.context.session import SessionStore
        from heagent.types import Message, Role

        store = SessionStore()
        history = [
            Message(role=Role.USER if i % 2 == 0 else Role.ASSISTANT, content=f"历史消息 {i} " + "x" * 50)
            for i in range(20)
        ]
        store.save("bench-session", history)

        def run_once() -> str:
            loop = asyncio.new_event_loop()
            try:
                agent = AgentLoop(_FinalStubProvider(), session=store, max_iterations=3)
                return loop.run_until_complete(agent.run("bench restore", session_id="bench-session"))
            finally:
                loop.close()

        answer = benchmark(run_once)
        assert answer == "final answer"


class TestEventSinkThroughput:
    """事件写入吞吐基准：JsonlSink rollout 逐事件落盘（crash 前缀可回放契约的代价可见化）。"""

    def test_rollout_write_50_events(self, benchmark, tmp_path: Path) -> None:
        from heagent.engine.observability import EngineEvent
        from heagent.events.sink import JsonlSink

        events = [
            EngineEvent(
                event_type="tool_call_completed",
                run_id="bench",
                iteration=1,
                tool_name="shell",
                target="ls",
                details={"mode": "direct", "duration_ms": i, "content_length": 10},
            )
            for i in range(50)
        ]

        def write_all() -> int:
            sink = JsonlSink(rollout_dir=tmp_path / "rollouts")
            for event in events:
                sink.handle(event)
            return sink.seq

        seq = benchmark(write_all)
        assert seq == len(events)
