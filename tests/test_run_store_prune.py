"""RunStore.prune / EngineContainer.prune_runs_once 测试 — 过期 run 快照的回收。

覆盖：记录 + 配套 .lock + 产物目录的回收、无主锁清扫、在途（新鲜）条目保留、
轻量判定（不 load Pydantic，坏 JSON 照样回收）、失败不中断、去重标志与 ledger 相互独立、
批量 I/O（不再逐条起线程）与跨进程节流。
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

import pytest

from heagent.agent.loop import AgentLoop
from heagent.config import get_settings, reset_settings
from heagent import persist as persist_mod
from heagent.engine.container import EngineContainer
from heagent.engine.store import RunStore
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class _StubProvider:
    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        return ProviderResponse(
            content="done",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture(autouse=True)
def _clean_settings() -> Iterator[None]:
    reset_settings()
    yield
    reset_settings()


def _age(path: Path, *, days: float = 10) -> None:
    """把路径的 mtime/atime 设为 N 天前（prune 判定只看 mtime）。"""
    ts = time.time() - days * 86_400
    os.utime(path, (ts, ts))


def _store(tmp_path: Path) -> RunStore:
    return RunStore(str(tmp_path / "runs"))


def _record(store: RunStore, tmp_path: Path, run_id: str, *, days: float = 10) -> tuple[Path, Path]:
    """建一条「记录 + 配套锁」并设过期；返回两个路径。"""
    base = tmp_path / "runs"
    base.mkdir(parents=True, exist_ok=True)
    record = base / f"{run_id}.json"
    record.write_text('{"run_id": "' + run_id + '"}', encoding="utf-8")
    lock = base / f"{run_id}.json.lock"
    lock.write_text("", encoding="utf-8")
    _age(record, days=days)
    _age(lock, days=days)
    return record, lock


# ══════════════════════════════════════════════════════════════════════
# RunStore.prune
# ══════════════════════════════════════════════════════════════════════


class TestRunStorePrune:
    async def test_removes_expired_record_with_its_lock(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        record, lock = _record(store, tmp_path, "old-run")
        fresh_record, fresh_lock = _record(store, tmp_path, "fresh-run", days=0)

        assert await store.prune(retention_days=7) == 2

        assert not record.exists()
        assert not lock.exists()
        assert fresh_record.exists()  # 未过期（在途 run 的 mtime 会持续刷新）不动
        assert fresh_lock.exists()

    async def test_removes_artifact_directory_of_expired_run(self, tmp_path: Path) -> None:
        """过期 run 的产物目录（如 rollout）随记录一并回收，不留无主产物。"""
        store = _store(tmp_path)
        _record(store, tmp_path, "old-run")
        artifacts = tmp_path / "runs" / "old-run"
        artifacts.mkdir()
        (artifacts / "rollout.jsonl").write_text('{"kind": "run_started"}\n', encoding="utf-8")

        assert await store.prune(retention_days=7) == 3

        assert not artifacts.exists()

    async def test_keeps_artifact_directory_of_fresh_run(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        _record(store, tmp_path, "fresh-run", days=0)
        artifacts = tmp_path / "runs" / "fresh-run"
        artifacts.mkdir()
        (artifacts / "rollout.jsonl").write_text("x", encoding="utf-8")

        assert await store.prune(retention_days=7) == 0

        assert artifacts.exists()

    async def test_sweeps_orphan_lock_only_when_expired(self, tmp_path: Path) -> None:
        """无主锁（记录已被 delete）仅在自身也过期时回收；新鲜无主锁不动（可能正被写入）。"""
        store = _store(tmp_path)
        base = tmp_path / "runs"
        base.mkdir(parents=True, exist_ok=True)
        stale_orphan = base / "gone.json.lock"
        stale_orphan.write_text("", encoding="utf-8")
        fresh_orphan = base / "gone2.json.lock"
        fresh_orphan.write_text("", encoding="utf-8")
        _age(stale_orphan, days=30)

        assert await store.prune(retention_days=7) == 1

        assert not stale_orphan.exists()
        assert fresh_orphan.exists()

    async def test_orphan_lock_sweep_runs_after_record_removal(self, tmp_path: Path) -> None:
        """记录的锁即使第一遍没删掉，也会在无主锁清扫中被回收（两遍覆盖）。"""
        store = _store(tmp_path)
        record, lock = _record(store, tmp_path, "old-run")
        lock.unlink()  # 模拟锁文件已被单独删/写入失败 —— 仅留记录
        assert await store.prune(retention_days=7) == 1
        assert not record.exists()

    async def test_zero_or_negative_retention_is_noop(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        _record(store, tmp_path, "old-run")

        assert await store.prune(retention_days=0) == 0
        assert await store.prune(retention_days=-1) == 0
        assert (tmp_path / "runs" / "old-run.json").exists()

    async def test_missing_base_dir_returns_zero(self, tmp_path: Path) -> None:
        assert await RunStore(str(tmp_path / "does-not-exist")).prune(retention_days=7) == 0

    async def test_corrupt_json_is_still_pruned(self, tmp_path: Path) -> None:
        """轻量判定不 load Pydantic：损坏的过期快照照样能回收（不会因解析失败而永久堆积）。"""
        store = _store(tmp_path)
        base = tmp_path / "runs"
        base.mkdir(parents=True, exist_ok=True)
        broken = base / "broken.json"
        broken.write_text("{not json at all", encoding="utf-8")
        _age(broken, days=30)

        assert await store.prune(retention_days=7) == 1

        assert not broken.exists()

    async def test_unlink_failure_is_skipped_and_batch_continues(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """单条删除失败（此处用「名为 *.json 的目录」构造 OSError）不中断整批。"""
        store = _store(tmp_path)
        base = tmp_path / "runs"
        base.mkdir(parents=True, exist_ok=True)
        undeletable = base / "weird.json"
        undeletable.mkdir()
        _age(undeletable, days=30)
        record, _ = _record(store, tmp_path, "old-run")

        with caplog.at_level(logging.DEBUG, logger="heagent.engine.store"):
            deleted = await store.prune(retention_days=7)

        assert deleted == 2  # 过期记录 + 其配套锁（各计 1）；名为 *.json 的目录删不掉、被跳过
        assert not record.exists()
        assert undeletable.is_dir()  # 目录未被（也无法被）删除，且未抛异常

    async def test_before_style_boundary_keeps_just_inside_retention(self, tmp_path: Path) -> None:
        """边界：6.5 天前的快照在 7 天保留期下保留，8 天前的回收。"""
        store = _store(tmp_path)
        inside, _ = _record(store, tmp_path, "inside", days=6.5)
        outside, _ = _record(store, tmp_path, "outside", days=8)

        assert await store.prune(retention_days=7) == 2

        assert inside.exists()
        assert not outside.exists()

    async def test_prune_scans_and_deletes_in_two_batches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """批量 I/O 回归：整次 prune 只占「一次扫描 + 一次删除」两次线程跳转。

        旧实现逐条 `await asyncio.to_thread(path.stat)` / `.unlink()`（50 条即上百次跳转），
        万级文件下光跳转就要数秒。这里直接锁定「不再逐条起线程」这一结构性质。
        """
        store = _store(tmp_path)
        for i in range(50):
            _record(store, tmp_path, f"old-{i:02d}")
        scans = 0
        deletes = 0
        real_scan, real_delete = persist_mod.scan_dir, persist_mod.delete_entries

        def _count_scan(base: Path) -> list[persist_mod.DirEntry]:
            nonlocal scans
            scans += 1
            return real_scan(base)

        def _count_delete(files: list[Path], dirs: list[Path]) -> tuple[int, int]:
            nonlocal deletes
            deletes += 1
            return real_delete(files, dirs)

        monkeypatch.setattr("heagent.engine.store.scan_dir", _count_scan)
        monkeypatch.setattr("heagent.engine.store.delete_entries", _count_delete)

        assert await store.prune(retention_days=7) == 100  # 50 记录 + 50 锁

        assert scans == 1
        assert deletes == 1

    async def test_prune_is_throttled_across_calls(self, tmp_path: Path) -> None:
        """跨进程节流：距上次清理不足 ``min_interval_seconds`` 时不再扫描（直接返回 0）。

        短命 CLI 进程（每次调用都是新进程）靠这层省掉「每次启动重扫万级目录」。
        """
        store = _store(tmp_path)
        _record(store, tmp_path, "old-run")

        assert await store.prune(retention_days=7, min_interval_seconds=3600) == 2
        _record(store, tmp_path, "another-old-run")
        assert await store.prune(retention_days=7, min_interval_seconds=3600) == 0  # 被节流
        assert (tmp_path / "runs" / "another-old-run.json").exists()  # 确实没扫
        assert await store.prune(retention_days=7) == 2  # 关掉节流（默认 0）即照常清理

    async def test_zero_interval_never_throttles(self, tmp_path: Path) -> None:
        """``min_interval_seconds=0``（默认）每次都真扫——测试与手动调用的既有语义。"""
        store = _store(tmp_path)
        _record(store, tmp_path, "a")
        assert await store.prune(retention_days=7, min_interval_seconds=0) == 2
        _record(store, tmp_path, "b")
        assert await store.prune(retention_days=7, min_interval_seconds=0) == 2

    def test_prune_min_interval_default_is_fifteen_minutes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PRUNE_MIN_INTERVAL_SECONDS", raising=False)
        reset_settings()

        assert get_settings().prune_min_interval_seconds == 900

    def test_prune_min_interval_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PRUNE_MIN_INTERVAL_SECONDS", "60")
        reset_settings()

        assert get_settings().prune_min_interval_seconds == 60


# ══════════════════════════════════════════════════════════════════════
# EngineContainer.prune_runs_once
# ══════════════════════════════════════════════════════════════════════


class TestPruneRunsOnce:
    async def test_zero_retention_is_noop(self, tmp_path: Path) -> None:
        engine = EngineContainer(run_store=RunStore(str(tmp_path / "runs")))
        _record(RunStore(str(tmp_path / "runs")), tmp_path, "old-run")

        assert engine.run_retention_days == 0  # 手动构造默认 0（仅 default() 从 Settings 读）
        assert await engine.prune_runs_once() == 0

    async def test_prunes_then_dedupes(self, tmp_path: Path) -> None:
        store = RunStore(str(tmp_path / "runs"))
        engine = EngineContainer(run_store=store, run_retention_days=7)
        _record(store, tmp_path, "old-run")

        assert await engine.prune_runs_once() == 2
        # 第二次短路（_runs_pruned=True）——进程内只扫一次
        assert await engine.prune_runs_once() == 0

    async def test_dedupe_flag_is_independent_from_ledger(self, tmp_path: Path) -> None:
        """ledger 的进程内去重标志不阻塞 runs 清理（两者各自独立）。"""
        store = RunStore(str(tmp_path / "runs"))
        engine = EngineContainer(run_store=store, run_retention_days=7, ledger_retention_days=7)
        _record(store, tmp_path, "old-run")

        await engine.prune_ledger_once()
        assert await engine.prune_runs_once() == 2

    async def test_failure_is_logged_and_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """清理 IO 故障不中断 run：打 error 日志后返回 0。"""

        async def _boom(*, retention_days: int) -> int:
            raise OSError("disk gone")

        store = RunStore(str(tmp_path / "runs"))
        engine = EngineContainer(run_store=store, run_retention_days=7)
        monkeypatch.setattr(store, "prune", _boom)

        with caplog.at_level(logging.ERROR, logger="heagent.engine.container"):
            assert await engine.prune_runs_once() == 0

        assert any("Run snapshot prune failed" in record.message for record in caplog.records)


# ══════════════════════════════════════════════════════════════════════
# 接线：loop 在全新 run 启动时调用；Settings 默认与 env 覆盖
# ══════════════════════════════════════════════════════════════════════


class TestWiringAndSettings:
    async def test_loop_calls_prune_runs_once_at_run_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        loop = AgentLoop(_StubProvider(), max_iterations=3)
        calls: list[int] = []

        async def _spy() -> int:
            calls.append(1)
            return 0

        monkeypatch.setattr(loop.engine, "prune_runs_once", _spy)

        await loop.run("hi")

        assert len(calls) == 1

    def test_default_retention_is_seven_days(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # conftest 为测试隔离设了 RUN_RETENTION_DAYS=0（见 tests/conftest.py），
        # 故断言「出厂默认」前需先清掉该 env（对齐 test_config 的 ledger 写法）。
        monkeypatch.delenv("RUN_RETENTION_DAYS", raising=False)
        reset_settings()

        assert get_settings().run_retention_days == 7

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RUN_RETENTION_DAYS", "30")
        reset_settings()

        assert get_settings().run_retention_days == 30
