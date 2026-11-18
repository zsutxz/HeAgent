"""后台任务进度注册表（``heagent.engine.tasks``）与压缩生产者的契约测试。

覆盖三块：

- **状态机与 percent**：四态流转、单调不减、终态不可回退、未知 id 的 ``None`` 语义；
- **保留策略**：TTL（注入时钟，不真实等待）与「只留最近 N 条终态」，在途任务永不被淘汰；
- **真实生产者**：``ContextCompressor`` 的分段循环经 :func:`compression_progress` 上报，
  以及 ``cli.interactive._compact_session``（``/compact``）把进度写进进程内注册表。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from heagent.cli import interactive
from heagent.context.compressor import ContextCompressor, compression_progress
from heagent.context.session import SessionStore
from heagent.engine.tasks import (
    TERMINAL_STATUSES,
    TaskProgress,
    TaskRegistry,
    TaskScope,
    TaskStatus,
    default_task_registry,
)
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, Role, TokenUsage

_BASE = datetime(2026, 1, 1, tzinfo=UTC)
# 摘要循环的上报区间（与 ``compressor`` 的常量同值）：循环中的百分比必须落在开区间内，
# 才能证明「逐条推进」而不只是起止两条。
_PERCENT_MIN = 20
_PERCENT_MAX = 90


class _Clock:
    """可控时钟：``advance()`` 只推时间，不睡眠。"""

    def __init__(self) -> None:
        self.now = _BASE

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class _StubProvider:
    """只回固定摘要的 provider（不联网、不调真实 API）。"""

    def __init__(self, summary: str = "summary") -> None:
        self.summary = summary

    async def send(self, messages: list[Message], **kwargs: object) -> ProviderResponse:
        return ProviderResponse(
            content=self.summary,
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], **kwargs: object) -> object:
        yield await self.send(messages)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _conversation(count: int) -> list[Message]:
    return [Message(role=Role.USER, content=f"m{i}") for i in range(count)]


class TestTaskRegistryStateMachine:
    """四态流转与 percent 单调性。"""

    def test_start_registers_pending_zero_percent(self) -> None:
        registry = TaskRegistry()
        task_id = registry.start("context_compression", message="queued")

        progress = registry.get(task_id)
        assert progress is not None
        assert progress.status is TaskStatus.PENDING
        assert progress.percent == 0
        assert progress.message == "queued"
        assert progress.kind == "context_compression"
        assert progress.finished is False
        assert progress.started_at == progress.updated_at

    def test_begin_moves_to_running_without_changing_started_at(self) -> None:
        clock = _Clock()
        registry = TaskRegistry(clock=clock)
        task_id = registry.start("kind")
        clock.advance(5)

        progress = registry.begin(task_id, message="working")
        assert progress is not None
        assert progress.status is TaskStatus.RUNNING
        assert progress.started_at == _BASE
        assert progress.updated_at == _BASE + timedelta(seconds=5)

    def test_report_percent_is_monotonic_and_clamped(self) -> None:
        registry = TaskRegistry()
        task_id = registry.start("kind")
        registry.begin(task_id)

        assert registry.report(task_id, 40).percent == 40  # type: ignore[union-attr]
        # 回退值被吞（单调不减）
        assert registry.report(task_id, 10).percent == 40  # type: ignore[union-attr]
        # 越界值夹到 0..100
        assert registry.report(task_id, 250).percent == 100  # type: ignore[union-attr]
        assert registry.report(task_id, -7).percent == 100  # type: ignore[union-attr]

    def test_report_from_pending_moves_to_running(self) -> None:
        registry = TaskRegistry()
        task_id = registry.start("kind")

        progress = registry.report(task_id, 15, message="step")
        assert progress is not None
        assert progress.status is TaskStatus.RUNNING
        assert progress.message == "step"

    def test_finish_sets_completed_and_full_percent(self) -> None:
        registry = TaskRegistry()
        task_id = registry.start("kind")
        registry.report(task_id, 55, message="halfway")

        progress = registry.finish(task_id)
        assert progress is not None
        assert progress.status is TaskStatus.COMPLETED
        assert progress.percent == 100
        # message 只在显式给出时被替换：收尾不抹掉「最后在干什么」
        assert progress.message == "halfway"

    def test_fail_keeps_last_percent(self) -> None:
        registry = TaskRegistry()
        task_id = registry.start("kind")
        registry.report(task_id, 30)

        progress = registry.fail(task_id, message="boom")
        assert progress is not None
        assert progress.status is TaskStatus.FAILED
        assert progress.percent == 30
        assert progress.message == "boom"

    def test_terminal_state_never_regresses(self) -> None:
        registry = TaskRegistry()
        task_id = registry.start("kind")
        registry.finish(task_id)

        assert registry.report(task_id, 10).percent == 100  # type: ignore[union-attr]
        assert registry.get(task_id).status is TaskStatus.COMPLETED  # type: ignore[union-attr]
        # 终态之后 finish / fail 都无副作用
        assert registry.fail(task_id).status is TaskStatus.COMPLETED  # type: ignore[union-attr]

    @pytest.mark.parametrize("method", ["begin", "report", "finish", "fail"])
    def test_unknown_task_operations_return_none(self, method: str) -> None:
        registry = TaskRegistry()
        args: tuple[object, ...] = ("missing", 10) if method == "report" else ("missing",)
        assert getattr(registry, method)(*args) is None

    def test_explicit_task_id_and_re_registration(self) -> None:
        registry = TaskRegistry()
        assert registry.start("kind", task_id="fixed") == "fixed"
        # 同 id 重注册覆盖旧条目（留 WARNING，不抛）
        registry.finish("fixed")
        assert registry.start("kind", task_id="fixed") == "fixed"
        assert registry.get("fixed").status is TaskStatus.PENDING  # type: ignore[union-attr]

    def test_invalid_inputs_fail_loud(self) -> None:
        registry = TaskRegistry()
        with pytest.raises(ValidationError):
            registry.start("   ")
        with pytest.raises(ValidationError):
            registry.start("kind", task_id="x" * 65)
        with pytest.raises(ValueError):
            TaskRegistry(retention_seconds=-1)
        with pytest.raises(ValueError):
            TaskRegistry(max_finished=-1)

    def test_snapshot_is_newest_first_and_bounded(self) -> None:
        clock = _Clock()
        registry = TaskRegistry(clock=clock)
        for index in range(3):
            registry.start("kind", task_id=f"t{index}")
            clock.advance(1)

        # t2 最新（updated_at 最大）⇒ 排第一
        assert [progress.task_id for progress in registry.snapshot()] == ["t2", "t1", "t0"]
        assert [progress.task_id for progress in registry.snapshot(limit=2)] == ["t2", "t1"]
        assert registry.snapshot(limit=0) == []

    def test_terminal_statuses_set_matches_model(self) -> None:
        assert {TaskStatus.COMPLETED, TaskStatus.FAILED} == TERMINAL_STATUSES
        assert TaskProgress.model_fields["percent"].metadata  # 上界由模型声明（ge/le）


class TestTaskRegistryRetention:
    """终态保留：TTL + 最近 N 条；在途任务永不淘汰。"""

    def test_terminal_entry_expires_after_ttl(self) -> None:
        clock = _Clock()
        registry = TaskRegistry(retention_seconds=60, clock=clock)
        done = registry.start("kind", task_id="done")
        registry.finish(done)
        running = registry.start("kind", task_id="running")
        registry.begin(running)

        clock.advance(61)
        assert registry.get(done) is None
        assert registry.get(running) is not None  # 在途不淘汰

    def test_terminal_entry_survives_inside_ttl(self) -> None:
        clock = _Clock()
        registry = TaskRegistry(retention_seconds=60, clock=clock)
        task_id = registry.start("kind", task_id="t")
        registry.finish(task_id)
        clock.advance(59)
        assert registry.get("t") is not None

    def test_max_finished_keeps_newest_terminal_entries(self) -> None:
        clock = _Clock()
        registry = TaskRegistry(max_finished=2, retention_seconds=3600, clock=clock)
        for index in range(4):
            task_id = registry.start("kind", task_id=f"t{index}")
            registry.finish(task_id)
            clock.advance(1)

        remaining = sorted(progress.task_id for progress in registry.snapshot())
        assert remaining == ["t2", "t3"]

    def test_prune_reports_removed_count(self) -> None:
        clock = _Clock()
        registry = TaskRegistry(retention_seconds=10, clock=clock)
        for index in range(2):
            registry.finish(registry.start("kind", task_id=f"t{index}"))
        clock.advance(11)

        assert registry.prune() == 2
        assert registry.prune() == 0

    def test_prune_never_drops_running_tasks_even_over_limit(self) -> None:
        registry = TaskRegistry(max_finished=0, retention_seconds=0)
        live = registry.start("kind", task_id="live")
        registry.begin(live)

        assert registry.prune() == 0
        assert registry.get("live") is not None


class TestTaskScope:
    """``TaskScope`` 是生产者侧唯一用法：进入即 running，退出必收尾。"""

    def test_normal_exit_completes(self) -> None:
        registry = TaskRegistry()
        with registry.scope("context_compression", message="go") as task:
            assert isinstance(task, TaskScope)
            task.report(50, "half")
            assert registry.get(task.task_id).status is TaskStatus.RUNNING  # type: ignore[union-attr]

        progress = registry.get(task.task_id)
        assert progress is not None
        assert progress.status is TaskStatus.COMPLETED
        assert progress.percent == 100

    def test_exception_marks_failed_and_propagates(self) -> None:
        registry = TaskRegistry()
        with pytest.raises(RuntimeError), registry.scope("kind") as task:
            task.report(30)
            raise RuntimeError("boom")

        progress = registry.get(task.task_id)
        assert progress is not None
        assert progress.status is TaskStatus.FAILED
        assert progress.percent == 30
        assert progress.message == "boom"

    def test_explicit_finish_is_idempotent(self) -> None:
        registry = TaskRegistry()
        with registry.scope("kind") as task:
            task.finish("done")
            task.fail("ignored")
            task.finish()
        assert registry.get(task.task_id).status is TaskStatus.COMPLETED  # type: ignore[union-attr]

    def test_default_registry_is_process_wide_singleton(self) -> None:
        assert default_task_registry() is default_task_registry()


class TestCompressorProgressProducer:
    """``ContextCompressor`` 的分段循环是真实进度来源。"""

    async def test_reports_monotonic_progress_through_summary_loop(self) -> None:
        registry = TaskRegistry()
        reported: list[tuple[int, str]] = []
        compressor = ContextCompressor(_StubProvider(), keep_recent=2)

        with registry.scope("context_compression") as task:

            def record(percent: int, message: str) -> None:
                reported.append((percent, message))
                task.report(percent, message)

            with compression_progress(record):
                compressed = await compressor.compress(_conversation(8), token_count=9000, max_tokens=10000)
                assert registry.get(task.task_id).status is TaskStatus.RUNNING  # type: ignore[union-attr]

        assert len(compressed) < 8
        progress = registry.get(task.task_id)
        assert progress is not None
        assert progress.status is TaskStatus.COMPLETED
        assert progress.percent == 100
        # 上报确实来自摘要分段循环（带条目计数的中间档），不是只有起止两条
        assert any(message.startswith("summarizing") for _, message in reported)
        assert [value for value, _ in reported] == sorted(value for value, _ in reported)

    async def test_reported_percents_are_monotonic(self) -> None:
        percent: list[int] = []
        compressor = ContextCompressor(_StubProvider(), keep_recent=2)

        # 真实窗口（够放摘要提示词 + 回复）⇒ 摘要循环逐条推进
        with compression_progress(lambda value, _message: percent.append(value)):
            await compressor.compress(_conversation(10), token_count=9000, max_tokens=10000)

        assert percent
        assert percent == sorted(percent)
        assert percent[0] < percent[-1]
        assert percent[-1] == 100
        # 循环确实上报了中间档（不只是起止两条）
        assert any(_PERCENT_MIN < value < _PERCENT_MAX for value in percent)

    async def test_hook_absent_keeps_behaviour_unchanged(self) -> None:
        compressor = ContextCompressor(_StubProvider(), keep_recent=2)
        compressed = await compressor.compress(_conversation(6), token_count=9000, max_tokens=10000)
        assert len(compressed) == 3  # 摘要 1 + 最近 2
        assert compressed[0].content.startswith("[Conversation summary]")

    async def test_no_report_when_compression_does_not_start(self) -> None:
        percent: list[int] = []
        compressor = ContextCompressor(_StubProvider(), threshold=0.8)

        with compression_progress(lambda value, _message: percent.append(value)):
            # 未超阈值：一次都不报（那不算「进行中的任务」）
            unchanged = await compressor.compress(_conversation(6), token_count=10, max_tokens=100)
            assert len(unchanged) == 6

        assert percent == []

    async def test_broken_reporter_does_not_break_compression(self) -> None:
        def boom(_percent: int, _message: str) -> None:
            raise RuntimeError("reporter failed")

        compressor = ContextCompressor(_StubProvider(), keep_recent=2)
        with compression_progress(boom):
            compressed = await compressor.compress(_conversation(6), token_count=1, max_tokens=1)

        assert len(compressed) == 3

    async def test_scope_is_restored_after_exit(self) -> None:
        seen: list[int] = []
        first = lambda value, _message: seen.append(value)  # noqa: E731 - 极简测试替身
        compressor = ContextCompressor(_StubProvider(), keep_recent=2)

        with compression_progress(first):
            with compression_progress(None):
                await compressor.compress(_conversation(6), token_count=1, max_tokens=1)
            assert seen == []  # 内层屏蔽上报（且未泄漏到外层）
            await compressor.compress(_conversation(6), token_count=1, max_tokens=1)

        assert seen  # 外层恢复生效


class TestCompactSessionWiring:
    """``/compact`` 是注册表的生产接线点：任务结束必须留下可查询的终态。"""

    async def test_compact_records_completed_task(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        registry = TaskRegistry()
        monkeypatch.setattr("heagent.engine.tasks._default_registry", registry)
        store = SessionStore(str(tmp_path / "sessions"))
        store.save("s-compact", _conversation(6))
        loop = SimpleNamespace(
            compressor=ContextCompressor(_StubProvider(), keep_recent=2),
            window_reset=None,
            last_context_tokens=0,
        )

        await interactive._compact_session(loop, store, "s-compact")  # type: ignore[arg-type]

        tasks = registry.snapshot()
        assert len(tasks) == 1
        assert tasks[0].kind == "context_compression"
        assert tasks[0].status is TaskStatus.COMPLETED
        assert tasks[0].percent == 100

    async def test_compact_failure_is_recorded_as_failed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        registry = TaskRegistry()
        monkeypatch.setattr("heagent.engine.tasks._default_registry", registry)

        class _BrokenCompressor:
            async def compress(self, messages: list[Message], token_count: int, max_tokens: int) -> list[Message]:
                raise RuntimeError("compression blew up")

        store = SessionStore(str(tmp_path / "sessions"))
        store.save("s-broken", _conversation(3))
        loop = SimpleNamespace(compressor=_BrokenCompressor(), window_reset=None, last_context_tokens=0)

        with pytest.raises(RuntimeError):
            await interactive._compact_session(loop, store, "s-broken")  # type: ignore[arg-type]

        tasks = registry.snapshot()
        assert len(tasks) == 1
        assert tasks[0].status is TaskStatus.FAILED
