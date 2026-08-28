"""终端键盘监听：运行期间按两次 Esc（双击）打断当前 run。

``KeyInterruptMonitor`` 在后台线程监听标准输入，检测到 Esc（0x1B）后经
``loop.call_soon_threadsafe`` 置位 ``asyncio.Event``，供 CLI 交互模式取消当前
正在执行的 ``AgentLoop.run_stream`` 并回到输入状态（程序不退出）。

需在 ``DOUBLE_PRESS_INTERVAL`` 秒内连按两次 Esc 才触发打断（单次不打断），
用于降低误触概率。

按 Esc 暂停当前 run，按 Enter 恢复；双击 Esc 打断（暂停不取消 run）。

跨平台实现：
- Windows：``msvcrt.kbhit`` + ``getwch`` 轮询控制台输入；
- POSIX：``select`` + 原始终端模式（关 ICANON/ECHO/IXON）。

关 IXON 以禁用 XON/XOFF 流控，避免运行期间按 Ctrl+S 冻结输出流。仅改输入标志、
保留 OPOST，流式输出排版不受影响。

非 tty 标准输入（管道/重定向）时自动停用（``active=False``），run 正常跑完。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop
    from collections.abc import Iterator
    from typing import Any

logger = logging.getLogger(__name__)

# Esc = 0x1B（27）。POSIX raw 模式下，方向键/功能键以 ESC 开头的转义序列（如 ESC [ A）
# 也以 0x1B 作为首字节，故需探测后续字节区分「单独 Esc」与转义序列（见 _read_key_posix）。
# Windows msvcrt.getwch 对 Esc 返回 \x1b，方向键返回 \x00 / \xe0 前缀，天然可区分。
ESC = 27

# Enter 键码：Windows msvcrt.getwch 对 Enter 返回 \r（13）；POSIX raw 模式（ICRNL 开启）
# 下 Enter 键的 CR 被转换为 \n（10）。两种都认，避免跨平台差异。
ENTER = 13  # \r（CR）
LF = 10  # \n（NL）

# 双击 Esc 的最大间隔（秒）：间隔内连按两次 Esc 判定为「双击打断」；
# 超过间隔无第二次按键则判定为「单击暂停」。同一值承担消歧窗口与暂停响应延迟。
DOUBLE_PRESS_INTERVAL = 1.0


def _stdin_is_tty() -> bool:
    """标准输入是否为交互式终端（非管道/重定向）。"""
    return hasattr(sys.stdin, "isatty") and bool(sys.stdin.isatty())


@contextlib.contextmanager
def _unix_raw_mode() -> Iterator[None]:
    """临时切 stdin 为非 canonical、无回显、关 IXON；退出时恢复原属性。"""
    import termios

    # termios 是 POSIX 专属模块：typeshed 在非 POSIX 平台不暴露其属性，
    # 统一经 Any 访问避免跨平台 mypy 误报（与 engine/persist.py 处理 fcntl 同法）。
    t: Any = termios
    fd = sys.stdin.fileno()
    old = t.tcgetattr(fd)
    new = t.tcgetattr(fd)
    new[0] &= ~t.IXON  # c_iflag：关输出流控（禁用 XON/XOFF）
    new[3] &= ~(t.ICANON | t.ECHO)  # c_lflag：关 canonical/回显
    t.tcsetattr(fd, t.TCSANOW, new)
    try:
        yield
    finally:
        t.tcsetattr(fd, t.TCSADRAIN, old)


class KeyInterruptMonitor:
    """后台监听按键：Esc 置位 ``pause_toggle``（暂停）；Enter 置位 ``resume``（恢复）；双击 Esc 置位 ``interrupted``（打断）。"""

    def __init__(self) -> None:
        self.interrupted: asyncio.Event = asyncio.Event()
        self.pause_toggle: asyncio.Event = asyncio.Event()
        self.resume: asyncio.Event = asyncio.Event()
        self._active = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stack: contextlib.ExitStack | None = None
        # POSIX 读键用的一字节回退缓冲：peek 到转义序列后续字节 / 双击的第二个 Esc 时先放回这里，
        # 下次 _read_key_posix 优先从这里取，避免字节丢失。
        self._pending: list[int] = []

    @property
    def active(self) -> bool:
        """是否真正在监听（非 tty 时为 False）。"""
        return self._active

    def start(self, loop: AbstractEventLoop) -> None:
        """启动监听。非 tty 时静默跳过（不置 active）。"""
        if not _stdin_is_tty():
            return
        self._stop.clear()
        self._stack = contextlib.ExitStack()
        if os.name == "posix":
            self._stack.enter_context(_unix_raw_mode())
        self._drain_pending_keys()
        self._active = True
        self._thread = threading.Thread(
            target=self._poll,
            args=(loop,),
            name="heagent-key-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止监听并恢复终端状态；幂等，可安全多次调用。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        self._active = False

    # -- 内部 ---------------------------------------------------------

    def _drain_pending_keys(self) -> None:
        """丢弃监听启动前残留在输入缓冲的按键。

        不排空的话，残留按键会被监听线程立即读走、误打断刚启动的 run。
        POSIX 须在 raw 模式下排空（canonical 模式 select 只对完整行报告可读）。
        """
        if os.name == "nt":
            import msvcrt

            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            import select

            while True:
                ready, _, _ = select.select([sys.stdin], [], [], 0)
                if not ready:
                    break
                if not sys.stdin.buffer.read(1):
                    break

    def _poll(self, loop: AbstractEventLoop) -> None:
        """后台线程主循环：Esc 置位暂停；Enter 置位恢复；双击 Esc 置位打断。"""
        try:
            while not self._stop.is_set():
                key = self._read_key()
                if key is None:
                    return  # stop 置位
                if key == ESC:
                    # 消歧：在 DOUBLE_PRESS_INTERVAL 内再读一键。
                    # 读到第二个 Esc → 双击打断；超时（无键）→ 单击暂停；
                    # 消歧窗口内读到 Enter → 一并置位恢复（Esc+Enter 快速连按）。
                    second = self._read_key(timeout=DOUBLE_PRESS_INTERVAL)
                    if second == ESC:
                        loop.call_soon_threadsafe(self.interrupted.set)
                        return
                    loop.call_soon_threadsafe(self.pause_toggle.set)
                    if second in (ENTER, LF):
                        loop.call_soon_threadsafe(self.resume.set)
                elif key in (ENTER, LF):
                    loop.call_soon_threadsafe(self.resume.set)
        except Exception as exc:  # 终端关闭 / stdin 不可读：静默退出，不影响主流程
            logger.debug("Key monitor poll aborted: %s", exc)

    def _read_key(self, *, timeout: float | None = None) -> int | None:
        """阻塞直到读到一键 / stop / 超时；返回键码（int）或 None（stop/超时）。

        ``timeout=None`` 表示无限等待；否则超时后返回 None。
        """
        if os.name == "nt":
            return self._read_key_windows(timeout)
        return self._read_key_posix(timeout)

    def _read_key_windows(self, timeout: float | None = None) -> int | None:
        import msvcrt

        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._stop.is_set():
            if msvcrt.kbhit():
                return ord(msvcrt.getwch())
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.02)
        return None

    def _read_key_posix(self, timeout: float | None = None) -> int | None:
        import select

        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._stop.is_set():
            # 优先返回被 peek 放回的字节（转义序列后续 / 双击的第二个 Esc）。
            if self._pending:
                return self._pending.pop(0)
            wait = 0.05
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                wait = min(0.05, remaining)
            ready, _, _ = select.select([sys.stdin], [], [], wait)
            if not ready:
                continue
            data = sys.stdin.buffer.read(1)
            if not data:
                continue
            key = data[0]
            if key == ESC:
                # 读到 Esc：探测 0.05s 内是否紧跟字节，区分「转义序列」与「双击 Esc」。
                # - 无后续字节 → 单独 Esc（单击暂停）；
                # - 后续是 Esc → 双击打断：返回本 Esc，第二个 Esc 放回 pushback 交给 _poll 消歧；
                # - 后续是其他字节（[ / O 等）→ 方向键/功能键转义序列：跳过本 Esc，后续字节放回继续读。
                ready2, _, _ = select.select([sys.stdin], [], [], 0.05)
                if ready2:
                    nxt = sys.stdin.buffer.read(1)
                    if nxt:
                        self._pending.append(nxt[0])
                        if nxt[0] == ESC:
                            return ESC
                        continue
                return ESC
            return key
        return None
