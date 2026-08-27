"""终端键盘打断监听（KeyInterruptMonitor）测试。"""

from __future__ import annotations

import asyncio

from heagent.terminal import ENTER_CR, ENTER_LF, KeyInterruptMonitor


class _FakeLoop:
    """替身事件循环：call_soon_threadsafe 立即同步执行回调。"""

    def call_soon_threadsafe(self, fn, *args, **kwargs) -> None:
        fn(*args, **kwargs)


def test_poll_triggers_interrupt_on_enter(monkeypatch) -> None:
    """Enter（CR / LF）均触发打断（方案 A：空回车打断）。"""
    for key in (ENTER_CR, ENTER_LF):
        monitor = KeyInterruptMonitor()
        monkeypatch.setattr(monitor, "_read_key", lambda k=key: k)
        monitor._poll(_FakeLoop())
        assert monitor.interrupted.is_set(), f"Enter key {key} should interrupt"


def test_poll_ignores_other_keys_until_enter(monkeypatch) -> None:
    monitor = KeyInterruptMonitor()
    keys = iter([ord("x"), ord("a"), ENTER_CR])
    monkeypatch.setattr(monitor, "_read_key", lambda: next(keys))
    monitor._poll(_FakeLoop())
    assert monitor.interrupted.is_set()


def test_poll_returns_without_reading_when_stopped(monkeypatch) -> None:
    monitor = KeyInterruptMonitor()
    monitor._stop.set()
    calls = {"n": 0}

    def _read_key() -> int | None:
        calls["n"] += 1
        return None

    monkeypatch.setattr(monitor, "_read_key", _read_key)
    monitor._poll(_FakeLoop())
    assert not monitor.interrupted.is_set()
    assert calls["n"] == 0  # stop 已置位，while 循环不进入


def test_start_inactive_when_stdin_not_tty(monkeypatch) -> None:
    class _FakeStdin:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("heagent.terminal.sys.stdin", _FakeStdin())
    monitor = KeyInterruptMonitor()
    loop = asyncio.new_event_loop()
    try:
        monitor.start(loop)
    finally:
        loop.close()
    assert not monitor.active
    monitor.stop()


def test_stop_is_idempotent() -> None:
    monitor = KeyInterruptMonitor()
    monitor.stop()
    monitor.stop()
    assert not monitor.active


def test_unix_raw_mode_clears_and_restores_flags(monkeypatch) -> None:
    import sys as _sys
    import types

    calls: list[tuple[int, int, int]] = []

    def _fake_tcgetattr(fd: int) -> list[int]:
        # [c_iflag, c_oflag, c_cflag, c_lflag, ispeed, ospeed, cc]
        return [0x1, 0, 0, 0x2 | 0x8, 0, 0, [0] * 32]

    def _fake_tcsetattr(fd: int, when: int, attrs: list[int]) -> None:
        calls.append((when, attrs[0], attrs[3]))

    mod = types.ModuleType("termios")
    mod.IXON = 0x1
    mod.ICANON = 0x2
    mod.ECHO = 0x8
    mod.TCSANOW = 1
    mod.TCSADRAIN = 2
    mod.tcgetattr = _fake_tcgetattr
    mod.tcsetattr = _fake_tcsetattr
    monkeypatch.setitem(_sys.modules, "termios", mod)

    class _FakeStdin:
        def fileno(self) -> int:
            return 0

    monkeypatch.setattr("heagent.terminal.sys.stdin", _FakeStdin())

    from heagent.terminal import _unix_raw_mode

    with _unix_raw_mode():
        assert len(calls) == 1
        assert calls[0][0] == 1  # TCSANOW
        assert calls[0][1] == 0  # IXON 清掉
        assert calls[0][2] == 0  # ICANON|ECHO 清掉

    assert len(calls) == 2
    assert calls[1][0] == 2  # TCSADRAIN
    assert calls[1][1] == 0x1  # 恢复 IXON
    assert calls[1][2] == 0x2 | 0x8  # 恢复 ICANON|ECHO
