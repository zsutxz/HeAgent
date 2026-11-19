"""进度原语契约：阈值、限频、非 tty 降级、静音开关、收尾无残留任务。

时间维度用注入的假时钟 + 注入的极小阈值/刷新间隔（真实 ``asyncio.sleep`` 只在毫秒级下跑），
因此断言是确定性的：耗时由 ``clock`` 决定，刷新次数由 ``reported_lines`` 上界约束。
"""

from __future__ import annotations

import asyncio
import inspect
import io

from heagent.cli.display import display_width, tool_progress_label
from heagent.cli.progress import (
    PROGRESS_REFRESH_SECONDS,
    TOOL_PROGRESS_MIN_SECONDS,
    ToolProgress,
)
from heagent.config import get_settings, reset_settings
from heagent.pub.types import StreamEvent


class _FakeStream(io.StringIO):
    """可控 tty 的 stderr 替身：``isatty()`` 决定走实时刷新还是单行降级。"""

    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class _Clock:
    """假单调时钟：测试显式推进，避免用真实耗时判定阈值。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _call(name: str = "shell", target: str = "pytest -q") -> StreamEvent:
    return StreamEvent(type="tool_call", tool_name=name, tool_target=target)


def _result(name: str = "shell", *, error: bool = False) -> StreamEvent:
    return StreamEvent(type="tool_result", tool_name=name, tool_error=error)


def _tracker(
    stream: io.StringIO,
    clock: _Clock,
    *,
    min_seconds: float = 0.01,
    refresh_seconds: float = 0.01,
    enabled: bool | None = True,
) -> ToolProgress:
    return ToolProgress(
        enabled=enabled,
        stream=stream,
        min_seconds=min_seconds,
        refresh_seconds=refresh_seconds,
        clock=clock,
    )


def test_thresholds_are_module_constants() -> None:
    """阈值与刷新间隔只认模块常量：默认参数即常量，禁止散落魔法数。"""
    params = inspect.signature(ToolProgress.__init__).parameters
    assert params["min_seconds"].default == TOOL_PROGRESS_MIN_SECONDS == 3.0
    assert params["refresh_seconds"].default == PROGRESS_REFRESH_SECONDS == 0.5


def test_label_comes_from_display_and_ignores_non_tool_events() -> None:
    """事件形状只在 display 层解读：进度原语拿到的就是最终标签。"""
    assert tool_progress_label(_call()) == "shell → pytest -q"
    assert tool_progress_label(StreamEvent(type="text", text="hi")) is None
    assert tool_progress_label(StreamEvent(type="done", final_answer="ok")) is None


async def test_tool_below_threshold_prints_nothing() -> None:
    """<3 秒的工具不显示任何额外行，也不产生刷新任务。"""
    stream = _FakeStream(tty=True)
    clock = _Clock()
    tracker = _tracker(stream, clock, min_seconds=0.5)

    tracker.on_event(_call())
    await asyncio.sleep(0.05)  # 真实耗时远短于阈值 ⇒ 刷新点尚未到达
    assert stream.getvalue() == ""
    assert tracker.reported_lines == 0

    tracker.on_event(_result())  # 假时钟耗时仍为 0 < 阈值 ⇒ 连收尾摘要也不写
    await asyncio.sleep(0)
    assert stream.getvalue() == ""
    assert tracker.task is None
    await tracker.aclose()


async def test_slow_tool_refreshes_within_limit_then_reports_final_elapsed() -> None:
    stream = _FakeStream(tty=True)
    clock = _Clock()
    tracker = _tracker(stream, clock)

    tracker.on_event(_call())
    assert tracker.task is not None  # 越阈值前任务已在等待首个 sleep

    await asyncio.sleep(0.06)
    mid = stream.getvalue()
    assert "\r[calling shell → pytest -q 0.0s]" in mid
    assert mid.count("\r") >= 2
    assert 2 <= tracker.reported_lines <= 50  # 限频上界：远少于「每毫秒一次」

    clock.now = 4.2
    tracker.on_event(_result())
    await asyncio.sleep(0)
    assert "[calling shell → pytest -q done in 4.2s]" in stream.getvalue()
    assert tracker.task is None  # 停表即取消刷新任务
    await tracker.aclose()


async def test_concurrent_tools_show_pending_count() -> None:
    """并发批次里同刻多个工具在跑时只给在途计数，不伪造逐条进度。"""
    stream = _FakeStream(tty=True)
    clock = _Clock()
    tracker = _tracker(stream, clock)

    tracker.on_event(_call("shell", "first"))
    tracker.on_event(_call("shell", "second"))
    await asyncio.sleep(0.04)
    assert "(+1 more)" in stream.getvalue()

    tracker.on_event(_result("shell"))
    tracker.on_event(_result("shell"))
    await tracker.aclose()
    assert tracker.task is None


async def test_text_event_clears_the_progress_line() -> None:
    """模型正文到达前必须清掉半行进度，否则文字会粘在进度行后面。"""
    stream = _FakeStream(tty=True)
    tracker = _tracker(stream, _Clock())

    tracker.on_event(_call())
    await asyncio.sleep(0.04)
    assert not stream.getvalue().endswith("\r")

    tracker.on_event(StreamEvent(type="text", text="继续输出"))
    assert stream.getvalue().endswith("\r")
    await tracker.aclose()


async def test_non_tty_degrades_to_single_summary_line() -> None:
    """管道 / 重定向下不起任务、不刷屏，只写一行收尾摘要。"""
    stream = _FakeStream(tty=False)
    clock = _Clock()
    tracker = _tracker(stream, clock)

    tracker.on_event(_call())
    await asyncio.sleep(0.04)
    assert tracker.task is None
    assert stream.getvalue() == ""

    clock.now = 3.5
    tracker.on_event(_result())
    assert stream.getvalue() == "[calling shell → pytest -q done in 3.5s]\n"
    await tracker.aclose()


async def test_announce_progress_off_silences_everything() -> None:
    """``ANNOUNCE_PROGRESS=false`` 是既有静音开关，进度也遵守它。"""
    settings = get_settings()
    settings.announce_progress = False
    try:
        stream = _FakeStream(tty=True)
        clock = _Clock()
        tracker = ToolProgress(stream=stream, min_seconds=0.01, refresh_seconds=0.01, clock=clock)
        tracker.on_event(_call())
        await asyncio.sleep(0.04)
        clock.now = 10.0
        tracker.on_event(_result())
        assert stream.getvalue() == ""
        assert tracker.task is None
        await tracker.aclose()
    finally:
        reset_settings()


async def test_run_end_leaves_no_residual_task() -> None:
    """run 结束后（含取消路径）不得留下刷新任务，``aclose`` 幂等。"""
    before = asyncio.all_tasks()
    stream = _FakeStream(tty=True)
    tracker = _tracker(stream, _Clock())

    tracker.on_event(_call())
    await asyncio.sleep(0.03)
    assert tracker.task is not None

    await tracker.aclose()
    await tracker.aclose()
    assert tracker.task is None
    assert asyncio.all_tasks() - before == set()
    assert stream.getvalue().endswith("\r")  # 清行后不留残字


async def test_result_without_start_is_ignored() -> None:
    """没有对应 ``tool_call`` 的结果事件（如批次中断）不得凭空计时或写行。"""
    stream = _FakeStream(tty=True)
    tracker = _tracker(stream, _Clock())
    tracker.on_event(_result("never_started"))
    await tracker.aclose()
    assert stream.getvalue() == ""
    assert tracker.reported_lines == 0


def test_line_fits_terminal_width_and_keeps_elapsed_suffix() -> None:
    """裁剪只能吃掉标签：毫秒/秒表等后缀必须完整保留（否则进度行失去意义）。"""
    tracker = ToolProgress(enabled=False, stream=io.StringIO(), columns=40)
    line = tracker._line("shell → " + "y" * 100, " 3.2s]")
    assert len(line) == display_width(line) == 40
    assert line.startswith("[calling shell → y")
    assert line.endswith(" 3.2s]")
    assert "…" in line


def test_line_clips_cjk_labels_by_display_columns() -> None:
    """中文命令按**显示列**裁：``len()`` 少算一倍宽度，裁到 40 码位仍占 80 列、照样折行留残影。"""
    tracker = ToolProgress(enabled=False, stream=io.StringIO(), columns=40)
    line = tracker._line("shell → " + "重复显示" * 10, " 0.0s]")

    assert display_width(line) <= 40
    assert len(line) < display_width(line)  # 确实含宽字符，不是纯 ASCII 退化路径
    assert line.startswith("[calling shell → 重复")
    assert line.endswith(" 0.0s]")
    assert "…" in line


def test_write_line_pads_by_display_columns() -> None:
    """宽字符行按**列**补齐：按码位补会少补一半，``\\r`` 覆盖后留下上一行的残字。"""
    stream = _FakeStream(tty=True)
    tracker = ToolProgress(enabled=False, stream=stream, columns=80)
    wide_line = "[calling shell → 中文 0.0s]"

    tracker._write_line(wide_line)
    tracker._write_line("[calling shell → x 0.0s]")

    first = stream.getvalue().split("\r")[1]
    second = stream.getvalue().rsplit("\r", 1)[-1]
    assert display_width(first) == display_width(wide_line)
    assert display_width(second) == display_width(wide_line)  # 补齐到同一显示宽度
    assert len(second) == display_width(second)  # 纯 ASCII 行：码位 == 列数
    assert tracker._width == display_width(wide_line)


async def test_line_width_is_reread_each_frame(monkeypatch) -> None:
    """终端 resize 后按新宽度重排：宽度不冻结在构造时刻（否则缩窄窗口又折行留残影）。"""
    from heagent.cli import progress as progress_module

    current = {"columns": 30}
    monkeypatch.setattr(progress_module, "stream_columns", lambda stream=None: current["columns"])
    stream = _FakeStream(tty=True)
    tracker = ToolProgress(enabled=True, stream=stream, min_seconds=0.01, refresh_seconds=0.01, clock=_Clock())

    tracker.on_event(_call("shell", "y" * 200))
    await asyncio.sleep(0.06)
    narrow = stream.getvalue()
    frames = [frame for frame in narrow.split("\r") if frame]
    assert frames and all(display_width(frame) <= 30 for frame in frames)

    current["columns"] = 80
    await asyncio.sleep(0.06)
    frames_after = [frame for frame in stream.getvalue()[len(narrow) :].split("\r") if frame]
    assert frames_after
    assert max(display_width(frame) for frame in frames_after) > 30  # 重读生效，换成了新宽度
    assert all(display_width(frame) <= 80 for frame in frames_after)
    await tracker.aclose()


def test_line_stays_bounded_even_when_suffix_alone_overflows() -> None:
    """后缀本身比终端还宽时仍不超宽（宁可只留省略号，也不留下会折行的残影）。"""
    tracker = ToolProgress(enabled=False, stream=io.StringIO(), columns=10)
    line = tracker._line("shell → " + "z" * 50, " done in 3.2s · " + "9" * 60 + "]")
    assert display_width(line) <= max(10, 24)
    assert line.endswith("…]")  # 兜底截断仍保住结尾的 ``]``，行有闭合感


async def test_long_command_progress_is_single_row_per_frame() -> None:
    """长 shell 命令的每一帧都不超终端宽度：``\\r`` 才能真的覆盖同一行，不再堆成重复残片。"""
    stream = _FakeStream(tty=True)
    clock = _Clock()
    tracker = ToolProgress(enabled=True, stream=stream, min_seconds=0.01, refresh_seconds=0.01, clock=clock, columns=60)

    tracker.on_event(_call("shell", "x" * 300))
    await asyncio.sleep(0.06)
    frames = [frame for frame in stream.getvalue().split("\r") if frame]
    assert frames  # 已刷新过至少一帧
    assert all(len(frame) <= 60 for frame in frames)
    assert frames[-1].startswith("[calling shell → x")
    assert frames[-1].endswith("0.0s]")
    assert "…" in frames[-1]

    clock.now = 4.2
    tracker.on_event(_result())
    await asyncio.sleep(0)
    final = stream.getvalue().rsplit("\r", 1)[-1].rstrip("\n")
    assert len(final) <= 60
    assert final.endswith("done in 4.2s]")
    await tracker.aclose()
