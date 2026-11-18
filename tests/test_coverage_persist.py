"""补 engine/persist.py 未覆盖行：POSIX 锁路径 + 错误/日志分支。

覆盖目标：
- _acquire_lock_posix 正常获取锁 / 超时抛 OSError
- _release_lock_posix fcntl.flock(LOCK_UN)
- _acquire_lock / _release_lock 平台分发 (sys.platform=linux → POSIX 分支)
- _acquire_lock_windows / _release_lock_windows (mock msvcrt)
- atomic_write_text lock 获取失败时 os.close + raise (lines 152-153)
- atomic_write_text lock 释放失败时 debug 日志 (lines 175-177)
"""

from __future__ import annotations

import logging
import os
import sys
import time
import types

import pytest

from heagent.pub.persist import (
    _acquire_lock,
    _acquire_lock_posix,
    _acquire_lock_windows,
    _release_lock,
    _release_lock_posix,
    _release_lock_windows,
    atomic_write_text,
)

# ── helpers ───────────────────────────────────────────────────────


def _make_mock_fcntl(*, flock_side_effect=None):
    """创建 mock fcntl 模块（含 LOCK_EX / LOCK_NB / LOCK_UN 常量）。"""
    mod = types.ModuleType("fcntl")
    mod.LOCK_EX = 2
    mod.LOCK_NB = 4
    mod.LOCK_UN = 8
    calls = []

    def _flock(fd, op):
        calls.append((fd, op))
        if flock_side_effect is not None:
            if callable(flock_side_effect):
                return flock_side_effect(fd, op)
            raise flock_side_effect  # type: ignore[misc]

    mod.flock = _flock
    mod._calls = calls  # 方便断言
    return mod


def _make_mock_msvcrt(*, locking_side_effect=None):
    """创建 mock msvcrt 模块（含 LK_NBLCK / LK_UNLCK 常量）。"""
    mod = types.ModuleType("msvcrt")
    mod.LK_NBLCK = 1
    mod.LK_UNLCK = 2
    calls = []

    def _locking(fd, mode, nbytes):
        calls.append((fd, mode, nbytes))
        if locking_side_effect is not None:
            if callable(locking_side_effect):
                return locking_side_effect(fd, mode, nbytes)
            raise locking_side_effect  # type: ignore[misc]

    mod.locking = _locking
    mod._calls = calls
    return mod


@pytest.fixture()
def lock_fd(tmp_path):
    """已打开的锁文件 fd（原 9 处 os.open + finally os.close 样板收敛）。"""
    fd = os.open(str(tmp_path / "test.lock"), os.O_CREAT | os.O_RDWR)
    try:
        yield fd
    finally:
        os.close(fd)


# ── 平台锁：acquire / release（POSIX 与 Windows 同构对合并参数化）──


class TestPlatformLockAcquire:
    """fcntl（POSIX）与 msvcrt（Windows）两平台 acquire 同构行为合并参数化。"""

    @pytest.mark.parametrize(
        ("make_mod", "modname", "target", "expected_op"),
        [
            pytest.param(
                lambda: _make_mock_fcntl(),
                "fcntl",
                _acquire_lock_posix,
                lambda mod: mod.LOCK_EX | mod.LOCK_NB,
                id="posix",
            ),
            pytest.param(
                lambda: _make_mock_msvcrt(),
                "msvcrt",
                _acquire_lock_windows,
                None,
                id="windows",
            ),
        ],
    )
    def test_success(self, lock_fd, monkeypatch, make_mod, modname, target, expected_op):
        """正常获取锁：记录恰好一次调用；POSIX 额外断言 LOCK_EX|LOCK_NB 旗标。"""
        mod = make_mod()
        monkeypatch.setitem(sys.modules, modname, mod)
        target(lock_fd, timeout=1.0)
        assert len(mod._calls) == 1
        if expected_op is not None:
            assert mod._calls[0][1] == expected_op(mod)

    @pytest.mark.parametrize(
        ("make_mod", "modname", "target"),
        [
            pytest.param(
                lambda: _make_mock_fcntl(flock_side_effect=BlockingIOError()),
                "fcntl",
                _acquire_lock_posix,
                id="posix",
            ),
            pytest.param(
                lambda: _make_mock_msvcrt(locking_side_effect=OSError()),
                "msvcrt",
                _acquire_lock_windows,
                id="windows",
            ),
        ],
    )
    def test_timeout_raises_oserror(self, lock_fd, monkeypatch, make_mod, modname, target):
        """超时抛 OSError（Failed to acquire）：伪时钟两跳越过 deadline。"""
        monkeypatch.setitem(sys.modules, modname, make_mod())
        # 让 time.monotonic 第一次返回 0（设 deadline），第二次就超过超时
        monotonic_ticks = iter([0.0, 100.0])
        monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_ticks))
        monkeypatch.setattr(time, "sleep", lambda s: None)
        with pytest.raises(OSError, match="Failed to acquire"):
            target(lock_fd, timeout=0.01)


class TestPlatformLockRelease:
    """两平台 release 同构行为合并参数化；Windows 的静默吞错语义相反，单列。"""

    @pytest.mark.parametrize(
        ("make_mod", "modname", "target", "unlock_flag"),
        [
            pytest.param(lambda: _make_mock_fcntl(), "fcntl", _release_lock_posix, "LOCK_UN", id="posix"),
            pytest.param(lambda: _make_mock_msvcrt(), "msvcrt", _release_lock_windows, "LK_UNLCK", id="windows"),
        ],
    )
    def test_calls_unlock(self, lock_fd, monkeypatch, make_mod, modname, target, unlock_flag):
        """正常释放：以 UN 旗标记录恰好一次调用。"""
        mod = make_mod()
        monkeypatch.setitem(sys.modules, modname, mod)
        target(lock_fd)
        assert len(mod._calls) == 1
        assert mod._calls[0][1] == getattr(mod, unlock_flag)

    def test_oserror_on_unlock_is_silently_caught(self, lock_fd, monkeypatch):
        """_release_lock_windows 在 unlock 抛 OSError 时静默忽略（覆盖 lines 95-96）。"""
        monkeypatch.setitem(sys.modules, "msvcrt", _make_mock_msvcrt(locking_side_effect=OSError("unlock failed")))
        # 不应抛异常
        _release_lock_windows(lock_fd)


# ── _acquire_lock / _release_lock 平台分发 ──────────────────────


class TestPlatformDispatch:
    """_acquire_lock / _release_lock 按 sys.platform 分发到对应平台实现（4 形态合一）。"""

    @pytest.mark.parametrize(
        ("entry", "impl_attr", "platform_name"),
        [
            pytest.param(_acquire_lock, "_acquire_lock_posix", "linux", id="acquire-linux"),
            pytest.param(_acquire_lock, "_acquire_lock_windows", "win32", id="acquire-win32"),
            pytest.param(_release_lock, "_release_lock_posix", "linux", id="release-linux"),
            pytest.param(_release_lock, "_release_lock_windows", "win32", id="release-win32"),
        ],
    )
    def test_dispatches_to_platform_impl(self, lock_fd, monkeypatch, entry, impl_attr, platform_name):
        """sys.platform 命中 ⇒ 分发恰一次且收到原 fd。"""
        calls = []
        monkeypatch.setattr(
            f"heagent.pub.persist.{impl_attr}",
            lambda fd, *args: calls.append(fd),
        )
        monkeypatch.setattr(sys, "platform", platform_name)
        if entry is _acquire_lock:
            entry(lock_fd, 1.0)
        else:
            entry(lock_fd)
        assert calls == [lock_fd]


# ── atomic_write_text 错误路径 ────────────────────────────────────


class TestAtomicWriteTextErrorPaths:
    def test_lock_acquire_failure_closes_fd_and_raises(self, tmp_path, monkeypatch):
        """_acquire_lock 抛 BaseException → os.close(fd) + re-raise（覆盖 lines 152-153）。"""
        close_calls: list[int] = []
        monkeypatch.setattr(os, "close", lambda fd: close_calls.append(fd))

        def _fail_acquire(fd, timeout):
            raise KeyboardInterrupt()

        monkeypatch.setattr("heagent.pub.persist._acquire_lock", _fail_acquire)

        target = tmp_path / "f.json"
        with pytest.raises(KeyboardInterrupt):
            atomic_write_text(target, '{"a": 1}', lock=True)

        # 验证 os.close 被调用（锁 fd 在 except 块关闭）
        assert len(close_calls) == 1

    def test_release_lock_failure_logs_debug(self, tmp_path, monkeypatch, caplog):
        """_release_lock 抛 Exception → logger.debug + 写仍然成功（覆盖 lines 175-177）。"""
        # _acquire_lock 正常返回
        monkeypatch.setattr("heagent.pub.persist._acquire_lock", lambda fd, timeout: None)

        def _fail_release(fd):
            raise RuntimeError("unlock error")

        monkeypatch.setattr("heagent.pub.persist._release_lock", _fail_release)

        target = tmp_path / "f.json"
        with caplog.at_level(logging.DEBUG, logger="heagent.pub.persist"):
            atomic_write_text(target, '{"a": 1}', lock=True)

        assert target.read_text(encoding="utf-8") == '{"a": 1}'
        assert "Failed to release lock" in caplog.text
