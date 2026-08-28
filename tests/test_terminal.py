"""终端键盘打断/暂停监听（KeyInterruptMonitor）测试。"""

from __future__ import annotations

import asyncio

from heagent.terminal import ENTER, ESC, LF, KeyInterruptMonitor


class _FakeLoop:
    """替身事件循环：call_soon_threadsafe 立即同步执行回调。"""

    def call_soon_threadsafe(self, fn, *args, **kwargs) -> None:
        fn(*args, **kwargs)


def test_poll_double_escape_interrupts(monkeypatch) -> None:
    """双击 Esc（间隔内第二次）触发打断，不触发暂停。"""
    monitor = KeyInterruptMonitor()
    keys = iter([ESC, ESC])
    monkeypatch.setattr(monitor, "_read_key", lambda timeout=None: next(keys))
    monitor._poll(_FakeLoop())
    assert monitor.interrupted.is_set()
    assert not monitor.pause_toggle.is_set()


def test_poll_single_escape_pauses(monkeypatch) -> None:
    """单击 Esc（超时无第二次）触发暂停，不打断。"""
    monitor = KeyInterruptMonitor()
    keys = iter([ESC, None, None])
    monkeypatch.setattr(monitor, "_read_key", lambda timeout=None: next(keys))
    monitor._poll(_FakeLoop())
    assert monitor.pause_toggle.is_set()
    assert not monitor.interrupted.is_set()


def test_poll_ignores_other_keys_until_double_escape(monkeypatch) -> None:
    """非 Esc 键被忽略，不影响后续 Esc 消歧。"""
    monitor = KeyInterruptMonitor()
    keys = iter([ord("x"), ord("a"), ESC, ESC])
    monkeypatch.setattr(monitor, "_read_key", lambda timeout=None: next(keys))
    monitor._poll(_FakeLoop())
    assert monitor.interrupted.is_set()


def test_poll_pause_then_double_escape_interrupts(monkeypatch) -> None:
    """单击 Esc 暂停后监听不退出，后续双击 Esc 仍能打断。"""
    monitor = KeyInterruptMonitor()
    keys = iter([ESC, None, ESC, ESC])
    monkeypatch.setattr(monitor, "_read_key", lambda timeout=None: next(keys))
    monitor._poll(_FakeLoop())
    assert monitor.pause_toggle.is_set()
    assert monitor.interrupted.is_set()


def test_poll_returns_without_reading_when_stopped(monkeypatch) -> None:
    monitor = KeyInterruptMonitor()
    monitor._stop.set()
    calls = {"n": 0}

    def _read_key(timeout=None) -> int | None:
        calls["n"] += 1
        return None

    monkeypatch.setattr(monitor, "_read_key", _read_key)
    monitor._poll(_FakeLoop())
    assert not monitor.interrupted.is_set()
    assert not monitor.pause_toggle.is_set()
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


def test_read_key_posix_esc_alone(monkeypatch) -> None:
    """单独 Esc（无转义序列后续字节）返回 0x1B。"""
    import select as _select

    class _Buffer:
        def read(self, n: int) -> bytes:
            return b"\x1b"

    class _Stdin:
        buffer = _Buffer()

    call = {"n": 0}

    def _fake_select(rlist, wlist, xlist, timeout):
        call["n"] += 1
        # 第一次 select（主循环等待）：可读；第二次 select（转义探测）：不可读
        return (list(rlist), [], []) if call["n"] == 1 else ([], [], [])

    monkeypatch.setattr("heagent.terminal.sys.stdin", _Stdin())
    monkeypatch.setattr(_select, "select", _fake_select)

    monitor = KeyInterruptMonitor()
    assert monitor._read_key_posix() == ESC


def test_read_key_posix_arrow_sequence_skipped(monkeypatch) -> None:
    """方向键转义序列（ESC [ A）首字节不误判为 Esc，返回后续字节。"""
    import select as _select

    data = [b"\x1b", b"["]

    class _Buffer:
        def read(self, n: int) -> bytes:
            return data.pop(0)

    class _Stdin:
        buffer = _Buffer()

    def _fake_select(rlist, wlist, xlist, timeout):
        # 转义探测始终可读（存在后续字节），验证 Esc 首字节被跳过
        return (list(rlist), [], [])

    monkeypatch.setattr("heagent.terminal.sys.stdin", _Stdin())
    monkeypatch.setattr(_select, "select", _fake_select)

    monitor = KeyInterruptMonitor()
    assert monitor._read_key_posix() == ord("[")


def test_read_key_posix_double_escape(monkeypatch) -> None:
    """快速双击 Esc（两个 Esc 紧跟）不误判为转义序列：两次调用各返回一个 Esc。"""
    import select as _select

    data = [b"\x1b", b"\x1b"]

    class _Buffer:
        def read(self, n: int) -> bytes:
            return data.pop(0)

    class _Stdin:
        buffer = _Buffer()

    def _fake_select(rlist, wlist, xlist, timeout):
        # 主循环等待与转义探测均始终可读（存在第二个 Esc）
        return (list(rlist), [], [])

    monkeypatch.setattr("heagent.terminal.sys.stdin", _Stdin())
    monkeypatch.setattr(_select, "select", _fake_select)

    monitor = KeyInterruptMonitor()
    assert monitor._read_key_posix() == ESC  # 第一个 Esc
    assert monitor._read_key_posix() == ESC  # 第二个 Esc（经 pushback 返回）


def test_poll_enter_cr_resumes(monkeypatch) -> None:
    """Enter（CR）触发恢复事件，不触发暂停/打断。"""
    monitor = KeyInterruptMonitor()
    keys = iter([ENTER, None])
    monkeypatch.setattr(monitor, "_read_key", lambda timeout=None: next(keys))
    monitor._poll(_FakeLoop())
    assert monitor.resume.is_set()
    assert not monitor.pause_toggle.is_set()
    assert not monitor.interrupted.is_set()


def test_poll_enter_lf_resumes(monkeypatch) -> None:
    """Enter（LF）触发恢复事件，不触发暂停/打断。"""
    monitor = KeyInterruptMonitor()
    keys = iter([LF, None])
    monkeypatch.setattr(monitor, "_read_key", lambda timeout=None: next(keys))
    monitor._poll(_FakeLoop())
    assert monitor.resume.is_set()
    assert not monitor.pause_toggle.is_set()
    assert not monitor.interrupted.is_set()


def test_poll_escape_then_enter_sets_pause_and_resume(monkeypatch) -> None:
    """Esc 后消歧窗口内按 Enter：暂停与恢复事件同时置位，不打断。"""
    monitor = KeyInterruptMonitor()
    keys = iter([ESC, ENTER, None])
    monkeypatch.setattr(monitor, "_read_key", lambda timeout=None: next(keys))
    monitor._poll(_FakeLoop())
    assert monitor.pause_toggle.is_set()
    assert monitor.resume.is_set()
    assert not monitor.interrupted.is_set()
