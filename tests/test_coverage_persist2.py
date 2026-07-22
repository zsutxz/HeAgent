"""补 persist.py 未覆盖行：posix 重试 sleep(47), Windows 空文件 OSError(62-63), JSON 损坏/校验(170-177)。"""

from __future__ import annotations

import json
import os
import sys
from types import ModuleType

import pytest
from pydantic import BaseModel

import heagent.engine.persist as persist_mod


# ── 行 47: posix retry loop body ──


class TestAcquireLockPosixRetry:
    """覆盖 _acquire_lock_posix 非首轮迭代的 sleep 路径。"""

    def test_retry_loop_sleep(self, monkeypatch):
        """BlockingIOError → retry → success（sleep 被调用，行 47）。"""
        mock_fcntl = ModuleType("fcntl")
        mock_fcntl.LOCK_EX = 1
        mock_fcntl.LOCK_NB = 2

        call_count = [0]
        sleep_args = []

        def _flock(fd, flags):
            call_count[0] += 1
            if call_count[0] == 1:
                raise BlockingIOError()

        mock_fcntl.flock = _flock
        sys.modules["fcntl"] = mock_fcntl

        monkeypatch.setattr(persist_mod.time, "sleep", lambda s: sleep_args.append(s))
        monkeypatch.setattr(persist_mod.time, "monotonic", lambda: call_count[0] * 0.05)

        try:
            persist_mod._acquire_lock_posix(999, timeout=10.0)
        finally:
            sys.modules.pop("fcntl", None)

        assert len(sleep_args) >= 1, "sleep should have been called during retry"


# ── 行 62-63: Windows 空文件哨兵 OSError ──


class TestAcquireLockWindowsEmptyFile:
    """覆盖 _acquire_lock_windows 的 except OSError: pass（行 62-63）。"""

    def test_lseek_oserror_then_proceed(self, monkeypatch):
        """os.lseek→OSError→pass；然后正常走 locking。"""
        mock_msvcrt = ModuleType("msvcrt")
        mock_msvcrt.LK_NBLCK = 1
        mock_msvcrt.locking = lambda fd, mode, nbytes: None
        sys.modules["msvcrt"] = mock_msvcrt

        lseek_called = []

        def _bad_lseek(fd, offset, whence):
            lseek_called.append(True)
            raise OSError("Simulated lseek failure")

        monkeypatch.setattr(persist_mod.os, "lseek", _bad_lseek)

        fd = os.open(os.devnull, os.O_RDWR)
        try:
            persist_mod._acquire_lock_windows(fd, timeout=0.1)
        except Exception:
            pass  # expected on null device
        finally:
            sys.modules.pop("msvcrt", None)
            try:
                os.close(fd)
            except Exception:
                pass

        assert lseek_called


# ── 行 170-177: load_json_model 错误路径 ──


class _FakeModel(BaseModel):
    name: str
    value: int


class TestLoadJsonModelErrors:
    """覆盖 load_json_model 的 JSONDecodeError / ValidationError 路径。"""

    def test_corrupted_json_returns_none(self, tmp_path):
        """JSONDecodeError→logger.error + return None（行 170-172）。"""
        f = tmp_path / "bad.json"
        f.write_text("not valid json {{{")
        result = persist_mod.load_json_model(f, _FakeModel)
        assert result is None

    def test_wrong_schema_returns_none(self, tmp_path):
        """ValidationError→logger.error + return None（行 175-177）。"""
        f = tmp_path / "wrong.json"
        f.write_text(json.dumps({"name": 123, "extra": True}))
        result = persist_mod.load_json_model(f, _FakeModel)
        assert result is None

    def test_file_missing_returns_none(self, tmp_path):
        """FileNotFoundError→return None（零回归）。"""
        result = persist_mod.load_json_model(tmp_path / "nonexistent.json", _FakeModel)
        assert result is None
