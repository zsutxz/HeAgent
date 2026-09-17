"""``heagent.housekeeping`` 测试 — 日志 / 会话 / 编辑快照的保留期回收。

覆盖：三类各自的按天数回收与「新鲜不动」、非目标后缀不动、保留期 0 禁用、节流、
``run_housekeeping`` 的逐类隔离（一类失败不影响其余）与同步包装的短路。
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from heagent import housekeeping as hk
from heagent.config import Settings, reset_settings
from heagent.context.session import SessionStore
from heagent import persist
from heagent.housekeeping import prune_logs, prune_runtime_artifacts_sync, prune_sandbox_dirs, run_housekeeping
from heagent.tools.edits import prune_snapshots
from heagent.tools.sandbox import sandbox_sessions_root


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
        "sandbox_dir_retention_days": 7,
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


def _sandbox_dir(workspace: Path, run_id: str, *, age_days: float | None = None) -> Path:
    """造一个 per-run 沙箱会话目录（与 container 写入路径同源），可选把整棵树做旧。

    判活取「目录 + 直接子项」最新 mtime，故做旧必须连子项一起推——只推目录本身仍算活跃。
    """
    directory = sandbox_sessions_root(workspace) / run_id
    directory.mkdir(parents=True)
    (directory / "work.txt").write_text("x", encoding="utf-8")
    if age_days is not None:
        _age(directory, days=age_days)
        for child in directory.iterdir():
            _age(child, days=age_days)
    return directory


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


async def test_run_housekeeping_prunes_all_four_targets(tmp_path: Path) -> None:
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

    orphan = _sandbox_dir(tmp_path, "crashed-run", age_days=30)

    result = await run_housekeeping(settings=conf, workspace=tmp_path)

    assert result == {"logs": 1, "sessions": 1, "snapshots": 1, "sandboxes": 1}
    assert not old_log.exists()
    assert not session_file.exists()
    assert not snapshot_run.exists()
    assert not orphan.exists()
    # 节流标记必须落在 .heagent/ 下，不能在仓库根留未跟踪文件（logs/ 的父目录即仓库根）。
    assert not (tmp_path / ".logs.prune-stamp").exists()
    assert (tmp_path / ".heagent" / ".logs.prune-stamp").exists()
    assert (tmp_path / ".heagent" / ".sandboxes.prune-stamp").exists()


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
    """四类保留期全 0（测试环境）时不进事件循环——避免无谓的 asyncio.run。"""
    conf = _settings(
        tmp_path,
        log_retention_days=0,
        session_retention_days=0,
        edit_snapshot_retention_days=0,
        sandbox_dir_retention_days=0,
    )
    called = False

    async def _spy(**_kwargs: object) -> dict[str, int]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("heagent.housekeeping.run_housekeeping", _spy)

    assert prune_runtime_artifacts_sync(conf) == {"logs": 0, "sessions": 0, "snapshots": 0, "sandboxes": 0}
    assert called is False


# ── 沙箱会话目录回收（E40-D1：崩溃 run 的孤儿目录）────────────────────


async def test_prune_sandbox_dirs_removes_stale_keeps_active_and_fresh(tmp_path: Path) -> None:
    """孤儿删除；正在跑的 run（子项刚被写）与新建目录保留。

    判活依据是「目录 + 直接子项」最新 mtime：目录本身很旧但子项新鲜 = 仍在被使用。
    """
    orphan = _sandbox_dir(tmp_path, "crashed-run", age_days=30)
    active = _sandbox_dir(tmp_path, "running-run")
    _age(active, days=30)  # 目录自身做旧，子项保持新鲜 → 视为活跃
    fresh = _sandbox_dir(tmp_path, "fresh-run")

    assert await prune_sandbox_dirs(tmp_path, 7) == 1

    assert not orphan.exists()
    assert active.exists()
    assert fresh.exists()


async def test_prune_sandbox_dirs_disabled_when_zero(tmp_path: Path) -> None:
    orphan = _sandbox_dir(tmp_path, "crashed-run", age_days=999)

    assert await prune_sandbox_dirs(tmp_path, 0) == 0
    assert orphan.exists()


async def test_prune_sandbox_dirs_skips_malformed_entries(tmp_path: Path) -> None:
    """散落文件（非目录形态）不动——回收方只清理自己创建的目录形态。"""
    base = sandbox_sessions_root(tmp_path)
    base.mkdir(parents=True)
    stray = base / "stray.tmp"
    stray.write_text("x", encoding="utf-8")
    _age(stray, days=30)

    assert await prune_sandbox_dirs(tmp_path, 7) == 0

    assert stray.exists()


async def test_prune_sandbox_dirs_never_follows_symlinks(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """符号链接不删也不穿透（链接目标一字不动）。"""
    base = sandbox_sessions_root(tmp_path)
    base.mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    keep = target / "important.txt"
    keep.write_text("keep", encoding="utf-8")
    link = base / "linked-run"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - 平台/权限不允许建链接
        pytest.skip("symlink creation not permitted on this platform")

    with caplog.at_level(logging.WARNING, logger="heagent.housekeeping"):
        assert await prune_sandbox_dirs(tmp_path, 7) == 0

    assert link.exists()
    assert keep.exists()  # 绝不穿透链接删目标
    assert any("symlinked entry" in record.message for record in caplog.records)


async def test_prune_sandbox_dirs_is_bounded_per_pass(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """单趟删除数受 ``max_per_pass`` 限制，截断时记 warning（可观测，其余留待后续启动）。"""
    orphans = [_sandbox_dir(tmp_path, f"crashed-{i}", age_days=30) for i in range(3)]

    with caplog.at_level(logging.WARNING, logger="heagent.housekeeping"):
        assert await prune_sandbox_dirs(tmp_path, 7, max_per_pass=2) == 2

    assert sum(1 for path in orphans if path.exists()) == 1
    assert any("per-pass cap" in record.message for record in caplog.records)


def test_sandbox_dir_activity_refuses_symlinked_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """符号链接判定分支（平台不允许建链接时也能覆盖）：不透明、判为不可回收。"""
    directory = _sandbox_dir(tmp_path, "run-x", age_days=30)
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "run-x")

    with caplog.at_level(logging.WARNING, logger="heagent.housekeeping"):
        newest, reclaimable = hk._sandbox_dir_activity(directory)

    assert newest == 0.0
    assert reclaimable is False
    assert any("symlinked entry" in record.message for record in caplog.records)


async def test_prune_sandbox_dirs_reports_failure_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """删除失败（被占用 / 权限）只记 warning 并留待下次启动，不影响其余目录。"""
    locked = _sandbox_dir(tmp_path, "run-locked", age_days=30)
    removable = _sandbox_dir(tmp_path, "run-free", age_days=30)

    class _FlakyShutil:
        """只让 ``run-locked`` 的 rmtree 失败，其余委托真实现。"""

        def __init__(self, real: Any) -> None:
            self._real = real

        def rmtree(self, path: Any, **kwargs: Any) -> None:
            if Path(path).name == "run-locked":
                raise OSError("device or resource busy")
            self._real.rmtree(path, **kwargs)

    monkeypatch.setattr(persist, "shutil", _FlakyShutil(shutil))

    with caplog.at_level(logging.WARNING, logger="heagent.housekeeping"):
        assert await prune_sandbox_dirs(tmp_path, 7) == 1

    assert locked.exists()
    assert not removable.exists()
    assert any("could not be removed" in record.message for record in caplog.records)


async def test_prune_sandbox_dirs_is_throttled(tmp_path: Path) -> None:
    """节流：间隔内的第二次调用不再扫描 / 删除（自己的标记文件，独立于其他类别）。"""
    _sandbox_dir(tmp_path, "crashed-run", age_days=30)

    assert await prune_sandbox_dirs(tmp_path, 7, min_interval_seconds=3600) == 1

    another = _sandbox_dir(tmp_path, "crashed-run-2", age_days=30)
    assert await prune_sandbox_dirs(tmp_path, 7, min_interval_seconds=3600) == 0
    assert another.exists()
