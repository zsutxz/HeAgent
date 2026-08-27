"""终端键盘监听：运行期间按 Enter 打断当前 run。

``KeyInterruptMonitor`` 在后台线程监听标准输入，检测到 Enter（CR=0x0D / LF=0x0A，
终端经 ICRNL 可能把 CR 转成 LF）后经 ``loop.call_soon_threadsafe`` 置位
``asyncio.Event``，供 CLI 交互模式取消当前正在执行的 ``AgentLoop.run_stream``
并回到输入状态（程序不退出）。

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

# Enter = CR(0x0D) / LF(0x0A)。POSIX raw 模式下 ICRNL 默认开启，Enter 可能以 LF 到达；
# Windows msvcrt.getwch 按 Enter 返回 CR。二者都算打断键。
ENTER_CR = 13
ENTER_LF = 10

# 打断键集合：Enter（CR / LF）。
INTERRUPT_KEYS = frozenset({ENTER_CR, ENTER_LF})


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
    """后台监听 Enter；命中即线程安全地置位 ``interrupted`` 事件。"""

    def __init__(self) -> None:
        self.interrupted: asyncio.Event = asyncio.Event()
        self._active = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stack: contextlib.ExitStack | None = None

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
        """丢弃监听启动前残留在输入缓冲的按键（如提交输入时双击 Enter 的第二次）。

        不排空的话，残留 Enter 会被监听线程立即读走、误打断刚启动的 run。
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
        """后台线程主循环：读键直到命中打断键或 stop；非打断键忽略。"""
        try:
            while not self._stop.is_set():
                key = self._read_key()
                if key is None:
                    return  # stop 置位
                if key in INTERRUPT_KEYS:
                    loop.call_soon_threadsafe(self.interrupted.set)
                    return
        except Exception as exc:  # 终端关闭 / stdin 不可读：静默退出，不影响主流程
            logger.debug("Key monitor poll aborted: %s", exc)

    def _read_key(self) -> int | None:
        """阻塞直到读到一键或 stop；返回键码（int）或 None（stop）。"""
        if os.name == "nt":
            return self._read_key_windows()
        return self._read_key_posix()

    def _read_key_windows(self) -> int | None:
        import msvcrt

        while not self._stop.is_set():
            if msvcrt.kbhit():
                return ord(msvcrt.getwch())
            time.sleep(0.05)
        return None

    def _read_key_posix(self) -> int | None:
        import select

        while not self._stop.is_set():
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            if ready:
                data = sys.stdin.buffer.read(1)
                if data:
                    return data[0]
        return None
