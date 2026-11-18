"""进度原语契约：阈值、限频、非 tty 降级、静音开关、收尾无残留任务。

时间维度用注入的假时钟 + 注入的极小阈值/刷新间隔（真实 ``asyncio.sleep`` 只在毫秒级下跑），
因此断言是确定性的：耗时由 ``clock`` 决定，刷新次数由 ``reported_lines`` 上界约束。
"""

from __future__ import annotations

import asyncio
import inspect
import io

from heagent.cli.display import tool_progress_label
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
