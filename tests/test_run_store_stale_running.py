"""``RunStore.close_stale_running``：陈旧 running 快照的收尾口径。

判据与三条不变量的来源（2026-11-12 runtime_stats 运维实测）：

- 判据：``status == running`` 且 ``updated_at`` 超 ``max_idle_hours``（活进程每轮迭代
  都 touch 快照）。
- 只能写 ``FAILED``：写 ``aborted`` 之类会让 ``RunSnapshot`` 校验失败，该 run 从统计里
  整条消失。
- ``updated_at`` 必须保持末次真实活动时刻：时长口径 ``updated_at - started_at``，写收尾
  时刻会把每个死 run 放大数小时到数天（实测 4 个死 run 让某日累计时长 4.2h → 4.0d）。
- payload（messages / results / final_answer）原样保留。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import pytest

from heagent.agent.loop import AgentLoop
from heagent.agent.tool_execution import _run_heartbeat_tick
from heagent.config import get_settings, reset_settings
from heagent.engine import EngineContainer
from heagent.engine.context import RunContext, RunStatus
from heagent.engine.store import RunStore
from heagent.pub.types import Message, ToolResult

NOW = datetime(2026, 11, 12, 10, 0, 0)


def _stale_ctx(*, idle_hours: float = 22.0) -> RunContext:
    """构造一个「最后活动于 idle_hours 小时前」的 running 上下文。"""
    ctx = RunContext()
    ctx.updated_at = (NOW - timedelta(hours=idle_hours)).isoformat(timespec="seconds")
    return ctx


async def _seed(store: RunStore, ctx: RunContext, *, messages=None, results=None) -> None:
    await store.start(ctx, prompt="p", system="s")
    if messages is not None or results is not None:
        await store.checkpoint(
            ctx,
            prompt="p",
            system="s",
            messages=messages or [],
            results=results or [],
            final_answer="done",
        )


class TestCloseStaleRunning:
    @pytest.mark.asyncio
    async def test_closes_stale_running_and_keeps_payload(self, tmp_path) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = _stale_ctx()
        messages = [Message(role="user", content="hello"), Message(role="assistant", content="hi")]
        results = [ToolResult(tool_call_id="c1", content="ok")]
        await _seed(store, ctx, messages=messages, results=results)

        closed = await store.close_stale_running(max_idle_hours=6, now=NOW)

        assert closed == [ctx.run_id]
        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        # 只能写 failed（写别值会让快照校验失败、整条从统计消失）
        assert snapshot.context.status is RunStatus.FAILED
        # updated_at 保持末次真实活动时刻，不收尾时刻
        assert snapshot.context.updated_at == ctx.updated_at
        assert snapshot.error is not None
        assert snapshot.error.startswith("interrupted: stale running snapshot")
        assert ctx.updated_at in snapshot.error
        # payload 原样保留
        assert snapshot.messages == messages
        assert snapshot.results == results
        assert snapshot.final_answer == "done"

    @pytest.mark.asyncio
    async def test_fresh_running_left_untouched(self, tmp_path) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = _stale_ctx(idle_hours=1)
        await _seed(store, ctx)

        assert await store.close_stale_running(max_idle_hours=6, now=NOW) == []
        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert snapshot.context.status is RunStatus.RUNNING
        assert snapshot.error is None

    @pytest.mark.asyncio
    async def test_boundary_idle_is_not_closed(self, tmp_path) -> None:
        """恰好等于阈值不算陈旧（``idle_hours <= max_idle_hours`` 放行）。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = _stale_ctx(idle_hours=6)
        await _seed(store, ctx)

        assert await store.close_stale_running(max_idle_hours=6, now=NOW) == []

    @pytest.mark.asyncio
    async def test_terminal_runs_left_untouched(self, tmp_path) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = _stale_ctx()
        stale = ctx.updated_at
        ctx.mark_terminal(RunStatus.COMPLETED)
        ctx.updated_at = stale  # mark_terminal 会推进时钟，这里还原成陈旧时刻
        await _seed(store, ctx)

        assert await store.close_stale_running(max_idle_hours=6, now=NOW) == []
        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert snapshot.context.status is RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_corrupt_snapshot_is_skipped(self, tmp_path) -> None:
        """损坏 JSON 不影响其余记录的收尾（load() 返回 None 即跳过）。"""
        base = tmp_path / "runs"
        store = RunStore(base_dir=str(base))
        ctx = _stale_ctx()
        await _seed(store, ctx)
        (base / "broken.json").write_text("{not json", encoding="utf-8")

        assert await store.close_stale_running(max_idle_hours=6, now=NOW) == [ctx.run_id]

    @pytest.mark.asyncio
    async def test_unparsable_updated_at_is_skipped(self, tmp_path, caplog) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = RunContext()
        ctx.updated_at = "not-a-timestamp"
        await _seed(store, ctx)

        with caplog.at_level("WARNING", logger="heagent.engine.store"):
            assert await store.close_stale_running(max_idle_hours=6, now=NOW) == []
        assert any("unparsable updated_at" in record.message for record in caplog.records)
        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert snapshot.context.status is RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_multiple_stale_runs_returned_sorted(self, tmp_path) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ids = []
        for idle in (30.0, 20.0, 40.0):
            ctx = _stale_ctx(idle_hours=idle)
            await _seed(store, ctx)
            ids.append(ctx.run_id)

        closed = await store.close_stale_running(max_idle_hours=6, now=NOW)

        assert closed == sorted(ids)

    @pytest.mark.asyncio
    async def test_negative_idle_hours_rejected(self, tmp_path) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        with pytest.raises(ValueError, match="max_idle_hours"):
            await store.close_stale_running(max_idle_hours=-1)


class _FakeEngine:
    """只暴露 ``run_store`` 的假 engine：心跳 tick 的唯一依赖（不构造真容器）。"""

    def __init__(self, store: RunStore) -> None:
        self.run_store = store


class _FakeLoop:
    """``_run_heartbeat_tick`` 只读 ``loop.engine.run_store``，故按鸭子类型给最小替身。"""

    def __init__(self, store: RunStore) -> None:
        self.engine = _FakeEngine(store)


def _age(path, hours: float) -> None:
    """把文件 mtime 拨到 ``NOW - hours``（心跳新鲜度按 mtime 判，测试需要固定时钟）。"""
    ts = (NOW - timedelta(hours=hours)).timestamp()
    os.utime(path, (ts, ts))


class TestHeartbeatKeepsLiveRun:
    """工具在途心跳：快照时钟陈旧、但进程仍在干活时不得被收尾。

    现实来源（2026-11-25 运维实测）：一次长工具把 ``updated_at`` 拖过阈值，另一个进程启动时
    把在跑的 run 标成 failed。快照只在轮边界 checkpoint 刷新，因此「还活着」必须另有磁盘信号
    ——`RunStore.heartbeat()` 写的 ``<run_id>.alive``；fresh 即证进程在跑。
    """

    @pytest.mark.asyncio
    async def test_fresh_heartbeat_blocks_the_sweep(self, tmp_path) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = _stale_ctx(idle_hours=22)
        await _seed(store, ctx)
        await store.heartbeat(ctx.run_id)
        _age(store._heartbeat_path(ctx.run_id), hours=1)

        assert await store.close_stale_running(max_idle_hours=6, now=NOW) == []
        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert snapshot.context.status is RunStatus.RUNNING
        assert snapshot.error is None
        assert store._heartbeat_path(ctx.run_id).exists()

    @pytest.mark.asyncio
    async def test_stale_heartbeat_does_not_block_and_is_removed(self, tmp_path) -> None:
        """心跳本身也陈旧 ⇒ 证实进程已死，正常收尾并顺手清掉心跳文件。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = _stale_ctx(idle_hours=22)
        await _seed(store, ctx)
        await store.heartbeat(ctx.run_id)
        _age(store._heartbeat_path(ctx.run_id), hours=22)

        assert await store.close_stale_running(max_idle_hours=6, now=NOW) == [ctx.run_id]
        assert not store._heartbeat_path(ctx.run_id).exists()

    @pytest.mark.asyncio
    async def test_terminal_checkpoint_and_delete_clean_the_heartbeat(self, tmp_path) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = RunContext()
        await _seed(store, ctx)
        await store.heartbeat(ctx.run_id)
        assert store._heartbeat_path(ctx.run_id).exists()

        ctx.mark_terminal(RunStatus.COMPLETED)
        await store.checkpoint(ctx, prompt="p", system="s", messages=[], results=[], final_answer="done")
        assert not store._heartbeat_path(ctx.run_id).exists()

        await store.heartbeat(ctx.run_id)
        assert await store.delete(ctx.run_id) is True
        assert not store._heartbeat_path(ctx.run_id).exists()

    @pytest.mark.asyncio
    async def test_prune_reaps_heartbeats_of_gone_and_expired_records(self, tmp_path) -> None:
        """心跳不会永久堆积：记录已不存在（无主）或记录本轮过期，都随 prune 回收。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        # ① 无主心跳：从来没有对应快照（delete 之后残留 / 手工清理过记录）。
        orphan_id = "deadbeefdeadbeefdeadbeefdeadbeef"
        await store.heartbeat(orphan_id)
        _age(store._heartbeat_path(orphan_id), hours=24 * 30)
        # ② 过期记录 + 心跳：记录过期被删时心跳随之清掉。
        ctx = _stale_ctx()
        await _seed(store, ctx)
        await store.heartbeat(ctx.run_id)
        _age(store._path(ctx.run_id), hours=24 * 30)
        _age(store._heartbeat_path(ctx.run_id), hours=24 * 30)

        assert await store.prune(retention_days=7) >= 2
        assert not store._heartbeat_path(orphan_id).exists()
        assert not store._heartbeat_path(ctx.run_id).exists()


@pytest.mark.asyncio
async def test_run_heartbeat_tick_refreshes_the_store_file(tmp_path) -> None:
    """工具在途续租的附带动作：每个 tick 刷新一次心跳文件（``_run_heartbeat_tick`` 的唯一职责）。"""
    store = RunStore(base_dir=str(tmp_path / "runs"))
    ctx = RunContext()
    tick = _run_heartbeat_tick(_FakeLoop(store), ctx)

    await tick()

    assert store._heartbeat_path(ctx.run_id).exists()


class _StubProvider:
    async def send(self, messages, *, tools=None):
        from heagent.pub.types import ProviderResponse, TokenUsage

        return ProviderResponse(
            content="done",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages, *, tools=None):
        yield await self.send(messages, tools=tools)

    def get_metadata(self):
        from heagent.providers.base import ProviderMetadata

        return ProviderMetadata(name="stub", model="stub")


class TestCloseStaleRunsOnce:
    """``EngineContainer.close_stale_runs_once``：与 prune_runs_once 同构的去重/故障立场 + 接线。"""

    @pytest.mark.asyncio
    async def test_sweeps_then_dedupes(self, tmp_path) -> None:
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = _stale_ctx()
        await _seed(store, ctx)
        engine = EngineContainer(run_store=store, run_stale_idle_hours=6.0)

        assert await engine.close_stale_runs_once() == 1
        # 进程内只扫一次（_runs_stale_closed 去重）
        assert await engine.close_stale_runs_once() == 0

    @pytest.mark.asyncio
    async def test_zero_threshold_disables_sweep(self, tmp_path) -> None:
        """run_stale_idle_hours <= 0 = 禁用收尾扫描（测试经 conftest env 全局关闭）。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = _stale_ctx()
        await _seed(store, ctx)
        engine = EngineContainer(run_store=store, run_stale_idle_hours=0)

        assert await engine.close_stale_runs_once() == 0
        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert snapshot.context.status is RunStatus.RUNNING  # 未被动过

    def test_default_threshold_is_six_hours(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # conftest 为测试隔离设了 RUN_STALE_IDLE_HOURS=0（见 tests/conftest.py），
        # 故断言「出厂默认」前需先清掉该 env（对齐 test_run_store_prune 的 retention 写法）。
        monkeypatch.delenv("RUN_STALE_IDLE_HOURS", raising=False)
        reset_settings()

        assert get_settings().run_stale_idle_hours == 6.0

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RUN_STALE_IDLE_HOURS", "12")
        reset_settings()

        assert get_settings().run_stale_idle_hours == 12.0

    @pytest.mark.asyncio
    async def test_failure_is_logged_and_swallowed(self, tmp_path, monkeypatch, caplog) -> None:
        async def _boom() -> list[str]:
            raise OSError("disk gone")

        store = RunStore(base_dir=str(tmp_path / "fresh"))
        engine = EngineContainer(run_store=store, run_stale_idle_hours=6.0)
        monkeypatch.setattr(store, "close_stale_running", _boom)

        with caplog.at_level(logging.ERROR, logger="heagent.engine.container"):
            assert await engine.close_stale_runs_once() == 0

        assert any("Stale running sweep failed" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_loop_triggers_at_run_start(self, tmp_path, monkeypatch) -> None:
        """全新 run 启动时触发一次（resume 不触发）——与 prune_runs_once 同挂点。"""
        monkeypatch.chdir(tmp_path)
        loop = AgentLoop(_StubProvider(), max_iterations=3)
        calls: list[int] = []

        async def _spy() -> int:
            calls.append(1)
            return 0

        monkeypatch.setattr(loop.engine, "close_stale_runs_once", _spy)

        await loop.run("hi")

        assert len(calls) == 1
