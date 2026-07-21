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

from heagent.engine.persist import (
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


# ── _acquire_lock_posix ───────────────────────────────────────────


class TestAcquireLockPosix:
    def test_success(self, tmp_path, monkeypatch):
        """_acquire_lock_posix 正常获取锁。"""
        mock_fcntl = _make_mock_fcntl()
        monkeypatch.setitem(sys.modules, "fcntl", mock_fcntl)

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _acquire_lock_posix(fd, timeout=1.0)
            assert len(mock_fcntl._calls) == 1
            assert mock_fcntl._calls[0][1] == mock_fcntl.LOCK_EX | mock_fcntl.LOCK_NB
        finally:
            os.close(fd)

    def test_timeout_raises_oserror(self, tmp_path, monkeypatch):
        """_acquire_lock_posix 超时抛 OSError。"""
        mock_fcntl = _make_mock_fcntl(flock_side_effect=BlockingIOError())
        monkeypatch.setitem(sys.modules, "fcntl", mock_fcntl)

        # 让 time.monotonic 第一次返回 0（设 deadline），第二次就超过超时
        monotonic_ticks = iter([0.0, 100.0])
        monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_ticks))
        monkeypatch.setattr(time, "sleep", lambda s: None)

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            with pytest.raises(OSError, match="Failed to acquire"):
                _acquire_lock_posix(fd, timeout=0.01)
        finally:
            os.close(fd)


# ── _release_lock_posix ───────────────────────────────────────────


class TestReleaseLockPosix:
    def test_calls_flock_with_lock_un(self, tmp_path, monkeypatch):
        """_release_lock_posix 用 LOCK_UN 释放锁。"""
        mock_fcntl = _make_mock_fcntl()
        monkeypatch.setitem(sys.modules, "fcntl", mock_fcntl)

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _release_lock_posix(fd)
            assert len(mock_fcntl._calls) == 1
            assert mock_fcntl._calls[0][1] == mock_fcntl.LOCK_UN
        finally:
            os.close(fd)


# ── _acquire_lock_windows ─────────────────────────────────────────


class TestAcquireLockWindows:
    def test_success(self, tmp_path, monkeypatch):
        """_acquire_lock_windows 正常获取锁（mock msvcrt.locking 成功）。"""
        mock_msvcrt = _make_mock_msvcrt()
        monkeypatch.setitem(sys.modules, "msvcrt", mock_msvcrt)

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _acquire_lock_windows(fd, timeout=1.0)
            assert len(mock_msvcrt._calls) == 1
        finally:
            os.close(fd)

    def test_timeout_raises_oserror(self, tmp_path, monkeypatch):
        """_acquire_lock_windows 超时抛 OSError。"""
        mock_msvcrt = _make_mock_msvcrt(locking_side_effect=OSError())
        monkeypatch.setitem(sys.modules, "msvcrt", mock_msvcrt)

        monotonic_ticks = iter([0.0, 100.0])
        monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_ticks))
        monkeypatch.setattr(time, "sleep", lambda s: None)

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            with pytest.raises(OSError, match="Failed to acquire"):
                _acquire_lock_windows(fd, timeout=0.01)
        finally:
            os.close(fd)


# ── _release_lock_windows ─────────────────────────────────────────


class TestReleaseLockWindows:
    def test_success(self, tmp_path, monkeypatch):
        """_release_lock_windows 正常释放锁。"""
        mock_msvcrt = _make_mock_msvcrt()
        monkeypatch.setitem(sys.modules, "msvcrt", mock_msvcrt)

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _release_lock_windows(fd)
            assert len(mock_msvcrt._calls) == 1
            assert mock_msvcrt._calls[0][1] == mock_msvcrt.LK_UNLCK
        finally:
            os.close(fd)

    def test_oserror_on_unlock_is_silently_caught(self, tmp_path, monkeypatch):
        """_release_lock_windows 在 unlock 抛 OSError 时静默忽略（覆盖 lines 95-96）。"""
        mock_msvcrt = _make_mock_msvcrt(locking_side_effect=OSError("unlock failed"))
        monkeypatch.setitem(sys.modules, "msvcrt", mock_msvcrt)

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            # 不应抛异常
            _release_lock_windows(fd)
        finally:
            os.close(fd)


# ── _acquire_lock / _release_lock 平台分发 ──────────────────────


class TestAcquireLockDispatch:
    def test_linux_dispatches_to_posix(self, tmp_path, monkeypatch):
        """sys.platform='linux' → _acquire_lock 走 POSIX 分支。"""
        posix_called = []
        monkeypatch.setattr(
            "heagent.engine.persist._acquire_lock_posix",
            lambda fd, timeout: posix_called.append(fd),
        )
        monkeypatch.setattr(sys, "platform", "linux")

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _acquire_lock(fd, 1.0)
            assert len(posix_called) == 1
            assert posix_called[0] == fd
        finally:
            os.close(fd)

    def test_win32_dispatches_to_windows(self, tmp_path, monkeypatch):
        """sys.platform='win32' → _acquire_lock 走 Windows 分支。"""
        win_called = []
        monkeypatch.setattr(
            "heagent.engine.persist._acquire_lock_windows",
            lambda fd, timeout: win_called.append(fd),
        )
        monkeypatch.setattr(sys, "platform", "win32")

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _acquire_lock(fd, 1.0)
            assert len(win_called) == 1
            assert win_called[0] == fd
        finally:
            os.close(fd)


class TestReleaseLockDispatch:
    def test_linux_dispatches_to_posix(self, tmp_path, monkeypatch):
        """sys.platform='linux' → _release_lock 走 POSIX 分支。"""
        posix_called = []
        monkeypatch.setattr(
            "heagent.engine.persist._release_lock_posix",
            lambda fd: posix_called.append(fd),
        )
        monkeypatch.setattr(sys, "platform", "linux")

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _release_lock(fd)
            assert len(posix_called) == 1
            assert posix_called[0] == fd
        finally:
            os.close(fd)

    def test_win32_dispatches_to_windows(self, tmp_path, monkeypatch):
        """sys.platform='win32' → _release_lock 走 Windows 分支。"""
        win_called = []
        monkeypatch.setattr(
            "heagent.engine.persist._release_lock_windows",
            lambda fd: win_called.append(fd),
        )
        monkeypatch.setattr(sys, "platform", "win32")

        lock_path = tmp_path / "test.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _release_lock(fd)
            assert len(win_called) == 1
            assert win_called[0] == fd
        finally:
            os.close(fd)


# ── atomic_write_text 错误路径 ────────────────────────────────────


class TestAtomicWriteTextErrorPaths:
    def test_lock_acquire_failure_closes_fd_and_raises(self, tmp_path, monkeypatch):
        """_acquire_lock 抛 BaseException → os.close(fd) + re-raise（覆盖 lines 152-153）。"""
        close_calls: list[int] = []
        monkeypatch.setattr(os, "close", lambda fd: close_calls.append(fd))

        def _fail_acquire(fd, timeout):
            raise KeyboardInterrupt()

        monkeypatch.setattr("heagent.engine.persist._acquire_lock", _fail_acquire)

        target = tmp_path / "f.json"
        with pytest.raises(KeyboardInterrupt):
            atomic_write_text(target, '{"a": 1}', lock=True)

        # 验证 os.close 被调用（锁 fd 在 except 块关闭）
        assert len(close_calls) == 1

    def test_release_lock_failure_logs_debug(self, tmp_path, monkeypatch, caplog):
        """_release_lock 抛 Exception → logger.debug + 写仍然成功（覆盖 lines 175-177）。"""
        # _acquire_lock 正常返回
        monkeypatch.setattr("heagent.engine.persist._acquire_lock", lambda fd, timeout: None)

        def _fail_release(fd):
            raise RuntimeError("unlock error")

        monkeypatch.setattr("heagent.engine.persist._release_lock", _fail_release)

        target = tmp_path / "f.json"
        with caplog.at_level(logging.DEBUG, logger="heagent.engine.persist"):
            atomic_write_text(target, '{"a": 1}', lock=True)

        assert target.read_text(encoding="utf-8") == '{"a": 1}'
        assert "Failed to release lock" in caplog.text
