"""``heagent.housekeeping`` 测试 — 日志 / 会话 / 编辑快照的保留期回收。

覆盖：三类各自的按天数回收与「新鲜不动」、非目标后缀不动、保留期 0 禁用、节流、
``run_housekeeping`` 的逐类隔离（一类失败不影响其余）与同步包装的短路。
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from heagent import housekeeping as hk
from heagent.config import Settings, reset_settings
from heagent.context.session import SessionStore
from heagent.housekeeping import prune_logs, prune_runtime_artifacts_sync, run_housekeeping
from heagent.tools.edits import prune_snapshots

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _age(path: Path, *, days: float) -> None:
    """把文件/目录的 mtime 往前推 ``days`` 天（prune 只看 mtime）。"""
    stamp = time.time() - days * 86_400
    os.utime(path, (stamp, stamp))


def _settings(tmp_path: Path, **overrides: int | str) -> Settings:
    """构造只走显式参数的 Settings（不经 .env），并指向 tmp 目录。"""
    reset_settings()
    values: dict[str, int | str] = {
        "log_retention_days": 14,
        "session_retention_days": 30,
        "edit_snapshot_retention_days": 7,
        "prune_min_interval_seconds": 0,
        "log_dir": str(tmp_path / "logs"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _make_logs(tmp_path: Path) -> tuple[Path, Path, Path]:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    old, fresh, other = (
        log_dir / "heagent-20260101-000000.log",
        log_dir / "heagent-20260915-000000.log",
        log_dir / "keep.txt",
    )
    for path in (old, fresh, other):
        path.write_text("x", encoding="utf-8")
    _age(old, days=30)
    _age(other, days=30)
    return old, fresh, other


async def test_prune_logs_removes_old_keeps_fresh_and_other_suffixes(tmp_path: Path) -> None:
    old, fresh, other = _make_logs(tmp_path)

    assert await prune_logs(tmp_path / "logs", 14) == 1

    assert not old.exists()
    assert fresh.exists()
    assert other.exists()


async def test_prune_logs_disabled_when_zero(tmp_path: Path) -> None:
    old, _fresh, _other = _make_logs(tmp_path)

    assert await prune_logs(tmp_path / "logs", 0) == 0
    assert old.exists()


async def test_session_store_prune_removes_old_sessions(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / "sessions"))
    base = tmp_path / "sessions"
    base.mkdir()
    old, fresh = base / "old-session.json", base / "fresh-session.json"
    for path in (old, fresh):
        path.write_text('{"session_id": "x", "messages": []}', encoding="utf-8")
    _age(old, days=60)

    assert await store.prune(30) == 1

    assert not old.exists()
    assert fresh.exists()


async def test_session_store_prune_disabled_when_zero(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / "sessions"))
    base = tmp_path / "sessions"
    base.mkdir()
    old = base / "old-session.json"
    old.write_text("{}", encoding="utf-8")
    _age(old, days=999)

    assert await store.prune(0) == 0
    assert old.exists()


async def test_prune_snapshots_removes_old_run_dirs(tmp_path: Path) -> None:
    base = tmp_path / ".heagent" / "tmp" / "edit-snapshots"
    old_run, fresh_run = base / "run-old", base / "run-fresh"
    for directory in (old_run, fresh_run):
        directory.mkdir(parents=True)
        (directory / "file.py.bak").write_text("x", encoding="utf-8")
    _age(old_run, days=30)

    assert await prune_snapshots(7, workspace=tmp_path) == 1

    assert not old_run.exists()
    assert fresh_run.exists()


async def test_prune_snapshots_disabled_when_zero(tmp_path: Path) -> None:
    run_dir = tmp_path / ".heagent" / "tmp" / "edit-snapshots" / "run-old"
    run_dir.mkdir(parents=True)
    (run_dir / "x.bak").write_text("x", encoding="utf-8")
    _age(run_dir.parent, days=999)

    assert await prune_snapshots(0, workspace=tmp_path) == 0
    assert run_dir.exists()


async def test_run_housekeeping_prunes_all_three_targets(tmp_path: Path) -> None:
    conf = _settings(tmp_path)
    old_log, _fresh, _other = _make_logs(tmp_path)

    sessions = tmp_path / ".heagent" / "sessions"
    sessions.mkdir(parents=True)
    session_file = sessions / "old-session.json"
    session_file.write_text("{}", encoding="utf-8")
    _age(session_file, days=60)

    snapshot_run = tmp_path / ".heagent" / "tmp" / "edit-snapshots" / "run-old"
    snapshot_run.mkdir(parents=True)
    (snapshot_run / "x.bak").write_text("x", encoding="utf-8")
    _age(snapshot_run, days=30)

    result = await run_housekeeping(settings=conf, workspace=tmp_path)

    assert result == {"logs": 1, "sessions": 1, "snapshots": 1}
    assert not old_log.exists()
    assert not session_file.exists()
    assert not snapshot_run.exists()


async def test_run_housekeeping_is_throttled_across_calls(tmp_path: Path) -> None:
    """节流共享 ``PRUNE_MIN_INTERVAL_SECONDS``：间隔内第二次调用不再清理。"""
    conf = _settings(tmp_path, prune_min_interval_seconds=3600)
    sessions = tmp_path / ".heagent" / "sessions"
    sessions.mkdir(parents=True)
    old_session = sessions / "old-session.json"
    old_session.write_text("{}", encoding="utf-8")
    _age(old_session, days=60)

    assert (await run_housekeeping(settings=conf, workspace=tmp_path))["sessions"] == 1

    another = sessions / "another-old.json"
    another.write_text("{}", encoding="utf-8")
    _age(another, days=60)

    assert (await run_housekeeping(settings=conf, workspace=tmp_path))["sessions"] == 0  # 被节流
    assert another.exists()


async def test_run_housekeeping_isolates_target_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """一类清理抛错不影响其余，也不上抛（best-effort）。"""
    conf = _settings(tmp_path)
    sessions = tmp_path / ".heagent" / "sessions"
    sessions.mkdir(parents=True)
    old_session = sessions / "old-session.json"
    old_session.write_text("{}", encoding="utf-8")
    _age(old_session, days=60)

    async def _boom(*_args: object, **_kwargs: object) -> int:
        raise OSError("log dir gone")

    monkeypatch.setattr(hk, "prune_logs", _boom)

    with caplog.at_level(logging.WARNING, logger="heagent.housekeeping"):
        result = await run_housekeeping(settings=conf, workspace=tmp_path)

    assert result["logs"] == 0
    assert result["sessions"] == 1  # 其余照常
    assert any("log retention cleanup failed" in record.message for record in caplog.records)


def test_sync_wrapper_short_circuits_when_all_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """三类保留期全 0（测试环境）时不进事件循环——避免无谓的 asyncio.run。"""
    conf = _settings(tmp_path, log_retention_days=0, session_retention_days=0, edit_snapshot_retention_days=0)
    called = False

    async def _spy(**_kwargs: object) -> dict[str, int]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("heagent.housekeeping.run_housekeeping", _spy)

    assert prune_runtime_artifacts_sync(conf) == {"logs": 0, "sessions": 0, "snapshots": 0}
    assert called is False
