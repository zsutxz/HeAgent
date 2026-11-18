"""CLI 进度反馈原语：工具执行计时行 + 大文件读写进度片段。

两个消费者共用本模块：

- :class:`ToolProgress` —— 消费 ``StreamEvent``，对**超过 ``TOOL_PROGRESS_MIN_SECONDS``** 的工具
  执行原地刷新一行耗时提示（``\\r`` 重写，不用 ANSI 光标序列）。未越阈值时**不产生任何任务与
  输出**：这是「不影响性能」的结构保证，而非采样结论。
- :class:`FileProgressBridge` / :func:`format_file_progress` —— 接收
  ``tools/builtins/file.py`` 分块上报的 ``(已处理字节, 计划总量字节)``，渲染
  「已处理 / 总量 / 百分比 / 预计剩余时间」，由 :class:`ToolProgress` 拼到同一行行尾。

纪律：:meth:`ToolProgress.on_event` 与 :meth:`FileProgressBridge.report` 都不做 I/O（前者跑在
``run_stream`` 消费协程里，后者跑在工具工作线程里）；唯一写操作在 :meth:`ToolProgress._tick`
协程内。非 tty（管道 / 重定向）下**一个字节都不写**（原地刷新在日志里只会留一堆半行）；
``ANNOUNCE_PROGRESS=false``（既有「operator 静音横幅」开关）时同样整体静默。
"""

from __future__ import annotations

import asyncio
import sys
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any, TextIO

from pydantic import BaseModel

from heagent.cli.display import tool_progress_label
from heagent.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.pub.types import StreamEvent

#: 工具耗时阈值（**秒**）：低于此值的工具执行不显示任何进度行（避免噪声）。
TOOL_PROGRESS_MIN_SECONDS: float = 3.0
#: 进度行刷新间隔（**秒**）：限频即性能上界，一行最多每 0.5 秒重写一次。
PROGRESS_REFRESH_SECONDS: float = 0.5

_MB = 1024 * 1024


class FileProgressSample(BaseModel):
    """一次大文件读写的最新进度样本（跨线程传递的不可变值）。"""

    processed: int
    """已处理字节数。"""

    total: int
    """本次操作的计划总量字节数（读为 ``min(文件大小, 读上限)``，写为 payload 字节数）。"""

    started_at: float
    """本次操作的起始时刻（``clock()`` 秒，用于推算速率与剩余时间）。"""


def _size(n: int) -> str:
    """字节数渲染为 ``N.N MB``（进度行固定用 MB，避免 B/KB/MB 三档切换抖动列宽）。"""
    return f"{max(0, n) / _MB:.1f} MB"


def format_file_progress(sample: FileProgressSample, *, now: float) -> str:
    """把样本渲染为「已处理 / 总量 / 百分比 / 预计剩余时间」四要素片段。

    ``now`` 由调用方传入（与 :class:`ToolProgress` 的时钟同源），保证同一行内各字段时点一致。
    速率取「已处理 / 已耗时」线性外推；已处理为 0 时没有速率可言，退化为「计算中」。
    """
    processed = max(0, sample.processed)
    total = max(0, sample.total)
    percent = 100 if total == 0 else min(100, int(processed * 100 / total))
    elapsed = max(1e-6, now - sample.started_at)
    rate = processed / elapsed
    remaining = max(0, total - processed)
    if remaining == 0:
        eta = "已完成"
    elif rate <= 0:
        eta = "估算中"
    else:
        eta = f"约剩 {remaining / rate:.1f}s"
    return f"{_size(processed)}/{_size(total)} {percent}% · {eta}"


class FileProgressBridge:
    """``file_read`` / ``file_write`` 的分块上报接收端（工具线程写、事件循环读）。

    只保存「最近一个样本」：进度行不需要历史，读到旧样本最多让 ETA 落后一帧。写入是整体替换
    一个不可变 :class:`FileProgressSample`，GIL 下原子，故不加锁。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.sample: FileProgressSample | None = None

    def report(self, processed: int, total: int) -> None:
        """``(已处理字节, 计划总量字节)`` —— 工具侧唯一的上报入口。"""
        sample = self.sample
        same_op = sample is not None and sample.total == total and processed >= sample.processed
        self.sample = FileProgressSample(
            processed=processed,
            total=total,
            started_at=sample.started_at if same_op and sample is not None else self._clock(),
        )

    def reset(self) -> None:
        self.sample = None

    def fragment(self, now: float) -> str:
        """渲染进度片段；无样本时返回空串（调用方据此不追加）。"""
        sample = self.sample
        return "" if sample is None else format_file_progress(sample, now=now)


class _ActiveTool(BaseModel):
    """在途工具的一条开表记录。"""

    label: str
    started: float


def _is_tty(stream: TextIO) -> bool:
    """流是否为终端；被替换掉的流可能连 ``isatty`` 都没有（按非 tty 处理）。"""
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


class ToolProgress:
    """工具执行的实时进度行（惰性任务 + 限频刷新 + 原地重写）。

    ``enabled=None`` 时按 ``ANNOUNCE_PROGRESS`` 与 ``stream.isatty()`` 推导；``enabled=True``
    但流不是终端 ⇒ **降级模式**：不起任务、不刷新中间行，仅在工具耗时越过阈值时写一行收尾摘要。
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        stream: TextIO | None = None,
        min_seconds: float = TOOL_PROGRESS_MIN_SECONDS,
        refresh_seconds: float = PROGRESS_REFRESH_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        file_bridge: FileProgressBridge | None = None,
    ) -> None:
        self._stream: TextIO = sys.stderr if stream is None else stream
        self._min = min_seconds
        self._refresh = refresh_seconds
        self._clock = clock
        self._interactive = _is_tty(self._stream)
        self._enabled = (get_settings().announce_progress and self._interactive) if enabled is None else enabled
        self._active: list[_ActiveTool] = []
        self._task: asyncio.Task[None] | None = None
        self._width = 0
        self.reported_lines = 0
        """已写出的进度行数（刷新 + 收尾），供测试断言限频上界。"""
        self.file_bridge = file_bridge if file_bridge is not None else FileProgressBridge(clock)

    @property
    def task(self) -> asyncio.Task[None] | None:
        """在跑的刷新任务；已结束 / 未启动均为 ``None``（残留任务检测点）。"""
        task = self._task
        return None if task is None or task.done() else task

    # ── 事件入口（同步、无 I/O） ───────────────────────────────────────────

    def on_event(self, event: StreamEvent) -> None:
        """按事件类型开表 / 停表 / 清行；不做任何写操作。"""
        if event.type == "tool_call":
            if not self._enabled:
                return
            label = tool_progress_label(event) or event.tool_name
            self._active.append(_ActiveTool(label=label, started=self._clock()))
            self._ensure_task()
        elif event.type == "tool_result":
            record = self._pop(event.tool_name)
            if record is None:
                return
            elapsed = max(0.0, self._clock() - record.started)
            if self._enabled and elapsed >= self._min:
                self._finish_line(record, elapsed)
            if not self._active:
                self._cancel_task()
        elif self._width:
            # 正文 / 收尾事件要与进度行抢同一行：先清干净，否则文字会粘在半个进度行后面。
            self._clear_line()

    def _pop(self, tool_name: str) -> _ActiveTool | None:
        """按「同名最早一条」出表：``tool_result`` 只带工具名，没有调用 id。"""
        for index, record in enumerate(self._active):
            # 必须按「名字 + 分隔符」匹配：`cron` 这类短名工具不能把 `cron_list` 的在途记录弹掉。
            if tool_name and (record.label == tool_name or record.label.startswith(tool_name + " ")):
                return self._active.pop(index)
        return self._active.pop(0) if self._active else None

    # ── 任务生命周期 ──────────────────────────────────────────────────────

    def _ensure_task(self) -> None:
        if not self._interactive or self.task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # 无运行中的事件循环（同步调用面）：不刷新，保持零副作用
            return
        self._task = loop.create_task(self._tick())

    def _cancel_task(self) -> None:
        task = self._task
        if task is not None and not task.done():
            task.cancel()

    async def _tick(self) -> None:
        """首个刷新点就是阈值本身：未越阈值的工具因此永远走不到 ``_render``。"""
        await asyncio.sleep(self._min)
        while self._active:
            self._render()
            await asyncio.sleep(self._refresh)

    # ── 渲染 ──────────────────────────────────────────────────────────────

    def _render(self) -> None:
        record = self._active[0]
        parts = [f"[calling {record.label} {max(0.0, self._clock() - record.started):.1f}s"]
        if len(self._active) > 1:
            parts.append(f" (+{len(self._active) - 1} more)")
        fragment = self.file_bridge.fragment(self._clock())
        if fragment:
            parts.append(f" · {fragment}")
        parts.append("]")
        self._write_line("".join(parts))
        self.reported_lines += 1

    def _finish_line(self, record: _ActiveTool, elapsed: float) -> None:
        parts = [f"[calling {record.label} done in {elapsed:.1f}s"]
        fragment = self.file_bridge.fragment(self._clock())
        if fragment:
            parts.append(f" · {fragment}")
        parts.append("]")
        if self._interactive:
            self._clear_line()
        self._safe_write("".join(parts) + "\n")
        self.reported_lines += 1

    def _write_line(self, text: str) -> None:
        """``\\r`` 原地重写；用空格补齐到上次宽度，避免残字（不用 ANSI 清行序列）。"""
        padded = text.ljust(self._width)
        self._width = max(self._width, len(text))
        self._safe_write("\r" + padded)

    def _clear_line(self) -> None:
        if self._width:
            self._safe_write("\r" + " " * self._width + "\r")
            self._width = 0

    def _safe_write(self, text: str) -> None:
        """写终端；目标流编码不支持标签字符时按 ``errors="replace"`` 降级（同 ``_icon`` 立场）。"""
        stream: Any = self._stream
        try:
            stream.write(text)
            stream.flush()
        except UnicodeEncodeError:
            encoding = getattr(stream, "encoding", None) or "utf-8"
            stream.write(text.encode(encoding, "replace").decode(encoding, "replace"))
            stream.flush()
        except OSError:  # 终端已关闭 / 管道破裂：进度不是业务结果，静默放弃
            return

    async def aclose(self) -> None:
        """收尾：取消刷新任务、清行、清空在途表（幂等，异常路径也可安全调用）。"""
        task, self._task = self._task, None
        if task is not None:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._clear_line()
        self._active.clear()
