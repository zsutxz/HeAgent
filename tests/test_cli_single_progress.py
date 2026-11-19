"""单次执行（``heagent "长任务"``，非流式 ``loop.run``）的工具执行进度契约。

票面 verify 的主场景：交互模式已经有的「超 3 秒出耗时行 + 大文件进度」，单次模式此前完全没有
（非流式路径不发 ``StreamEvent``）。本文件钉死三件事：

1. **阈值语义**：秒表行只给 ≥3 秒（``TOOL_PROGRESS_MIN_SECONDS``），完成行（``done in``）恒写不限
   时长（耗时段由注入的假时钟决定，不用真等 3 秒）；
2. **静默边界**：``--json`` / 非 tty / ``ANNOUNCE_PROGRESS=false`` 三种情形一个字节都不写；
3. **收尾无残留**：作用域退出后引擎总线上的订阅者回到基线、无遗留 asyncio 任务。

引擎事件按 ``engine/executor.py::_emit_tool_event`` 的真实形状构造（``tool_call_started`` /
``tool_call_completed`` / ``tool_call_failed`` 带 ``tool_name`` + ``target``）。
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest

from heagent.cli import interactive
from heagent.cli.progress import (
    TOOL_PROGRESS_MIN_SECONDS,
    EngineToolProgressAdapter,
    ToolProgress,
)
from heagent.config import get_settings, reset_settings
from heagent.engine.observability import EventBus


class _FakeStream(io.StringIO):
    """可控 tty 的 stderr 替身（``isatty()`` 决定走实时刷新还是整体静默）。"""

    def __init__(self, *, tty: bool = True) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class _Clock:
    """假单调时钟：耗时由测试显式推进，阈值判定因此是确定性的。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _tracker(stream: io.StringIO, clock: _Clock, *, min_seconds: float = TOOL_PROGRESS_MIN_SECONDS) -> ToolProgress:
    """与 ``_run_single`` 同形态的进度原语，只把流 / 时钟 / 阈值换成可控值。"""
    return ToolProgress(stream=stream, min_seconds=min_seconds, refresh_seconds=0.01, clock=clock)


def _start(bus: EventBus, name: str = "shell", target: str = "pytest -q") -> None:
    bus.publish("tool_call_started", tool_name=name, target=target, details={"mode": "direct"})


def _complete(bus: EventBus, name: str = "shell") -> None:
    bus.publish("tool_call_completed", tool_name=name, target="pytest -q", details={"duration_ms": 3600})


class _FakeEngine:
    """``_single_run_progress`` 只需要 ``engine.events``（其余装配不在本票范围）。"""

    def __init__(self) -> None:
        self.events = EventBus()


class _FakeProvider:
    class _Meta:
        model = "stub-model"

    def get_metadata(self) -> _FakeProvider._Meta:
        return self._Meta()


class _FakeLoop:
    """最小 loop 替身：非流式 ``run``，期间按真实形状发一对工具事件。"""

    def __init__(self, engine: _FakeEngine, clock: _Clock) -> None:
        self.engine = engine
        self._clock = clock
        self.last_usage = None
        self.provider = _FakeProvider()

    async def run(self, prompt: str, *, system: str | None = None) -> str:
        _start(self.engine.events)
        await asyncio.sleep(0.05)
        self._clock.now = 3.6
        await asyncio.sleep(0.05)
        _complete(self.engine.events)
        return "done"


def _observers(bus: EventBus) -> list[Any]:
    """总线上的观察者列表（``EventBus`` 没有 unsubscribe 公共面，断言基线按实现细节取快照）。"""
    return list(bus._observers)  # noqa: SLF001 - 基线断言


@pytest.fixture()
def engine() -> _FakeEngine:
    return _FakeEngine()


async def test_tool_below_threshold_writes_only_finish_line(engine: _FakeEngine) -> None:
    """3 秒以内的工具没有秒表行，完成行恒写；同名两次调用各得一条（按计数配对）。"""
    stream = _FakeStream()
    clock = _Clock()
    tracker = _tracker(stream, clock)  # 阈值 = 生产常量 3.0s，假时钟走 2.9s
    engine.events.subscribe(EngineToolProgressAdapter(tracker))

    _start(engine.events)
    _start(engine.events)  # 重复开表：适配器按工具名计数，不重复建记录也不报错
    clock.now = 2.9
    _complete(engine.events)
    _complete(engine.events)
    await asyncio.sleep(0)
    await tracker.aclose()

    out = stream.getvalue()
    assert out.count("done in 2.9s") == 2
    assert "\r" not in out  # <3s：无秒表行、无原地刷新
    assert tracker.reported_lines == 2
    assert tracker.task is None


async def test_tool_over_threshold_writes_done_line(engine: _FakeEngine) -> None:
    """越过 3 秒阈值（假时钟 3.6s）⇒ 收尾行出现；阈值判定走生产常量。"""
    stream = _FakeStream()
    clock = _Clock()
    tracker = _tracker(stream, clock)
    engine.events.subscribe(EngineToolProgressAdapter(tracker))

    _start(engine.events)
    clock.now = 3.6
    _complete(engine.events)
    await asyncio.sleep(0)
    await tracker.aclose()

    assert "[calling shell → pytest -q done in 3.6s]" in stream.getvalue()
    assert tracker.task is None


async def test_live_refresh_line_while_tool_in_flight(engine: _FakeEngine) -> None:
    """在途期间有原地刷新的耗时行（阈值与刷新间隔是本用例唯一的注入差异）。"""
    stream = _FakeStream()
    clock = _Clock()
    tracker = _tracker(stream, clock, min_seconds=0.02)
    engine.events.subscribe(EngineToolProgressAdapter(tracker))

    _start(engine.events)
    clock.now = 3.6
    await asyncio.sleep(0.05)  # 越阈值后的首个刷新点（真实等待毫秒级）
    assert "\r[calling shell → pytest -q 3.6s]" in stream.getvalue()
    await tracker.aclose()


async def test_unpaired_engine_events_do_not_stop_other_tools(engine: _FakeEngine) -> None:
    """未开表的 ``tool_call_failed`` / ``tool_call_blocked`` 不得把在途工具的计时弹掉。"""
    stream = _FakeStream()
    clock = _Clock()
    tracker = _tracker(stream, clock)
    engine.events.subscribe(EngineToolProgressAdapter(tracker))

    _start(engine.events, "shell")
    engine.events.publish("tool_call_failed", tool_name="unknown_tool", details={"error": "unknown tool"})
    engine.events.publish("tool_call_blocked", tool_name="shell", details={"reason": "hook"})
    clock.now = 4.0
    _complete(engine.events, "shell")
    await asyncio.sleep(0)
    await tracker.aclose()
    assert "[calling shell → pytest -q done in 4.0s]" in stream.getvalue()


async def test_tool_failure_after_start_still_stops_the_clock(engine: _FakeEngine) -> None:
    """失败的调用也有配对的 ``tool_call_started`` ⇒ 同样停表（错误结果照常收尾）。"""
    stream = _FakeStream()
    clock = _Clock()
    tracker = _tracker(stream, clock)
    engine.events.subscribe(EngineToolProgressAdapter(tracker))

    _start(engine.events)
    clock.now = 5.0
    engine.events.publish("tool_call_failed", tool_name="shell", details={"error": "boom"})
    await tracker.aclose()
    assert "[calling shell → pytest -q done in 5.0s]" in stream.getvalue()


async def test_non_tty_is_silent(engine: _FakeEngine) -> None:
    """管道 / 重定向下一个字节都不写（进度行在日志里只会留一堆半行）。"""
    stream = _FakeStream(tty=False)
    clock = _Clock()
    tracker = _tracker(stream, clock)
    engine.events.subscribe(EngineToolProgressAdapter(tracker))

    _start(engine.events)
    clock.now = 10.0
    _complete(engine.events)
    assert stream.getvalue() == ""
    assert tracker.task is None


async def test_announce_progress_off_is_silent(engine: _FakeEngine) -> None:
    """``ANNOUNCE_PROGRESS=false`` 是既有静音开关，单次模式同样遵守。"""
    settings = get_settings()
    settings.announce_progress = False
    try:
        stream = _FakeStream()
        clock = _Clock()
        tracker = _tracker(stream, clock)
        engine.events.subscribe(EngineToolProgressAdapter(tracker))

        _start(engine.events)
        clock.now = 10.0
        _complete(engine.events)
        assert stream.getvalue() == ""
        assert tracker.task is None
    finally:
        reset_settings()


async def test_scope_leaves_no_subscription_or_task(engine: _FakeEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """作用域退出后：订阅者回基线、刷新任务清零、后续引擎事件不再产生输出。"""
    stream = _FakeStream()
    clock = _Clock()
    monkeypatch.setattr(interactive, "ToolProgress", lambda **_: _tracker(stream, clock))
    baseline = _observers(engine.events)
    before_tasks = asyncio.all_tasks()

    async with interactive._single_run_progress(engine, json_output=False) as progress:
        assert progress is not None
        assert len(_observers(engine.events)) == len(baseline) + 1
        _start(engine.events)
        assert progress.task is not None

    assert _observers(engine.events) == baseline
    assert progress.task is None
    assert asyncio.all_tasks() - before_tasks == set()

    written = stream.getvalue()
    _complete(engine.events)  # 注销后的事件必须全部早退
    assert stream.getvalue() == written


async def test_json_mode_never_subscribes(engine: _FakeEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--json`` 时连进度装配都不建：stdout 的 JSONL 流与 stderr 的零字节都是结构保证。"""
    stream = _FakeStream()
    monkeypatch.setattr(interactive, "ToolProgress", lambda **_: _tracker(stream, _Clock()))
    baseline = _observers(engine.events)

    async with interactive._single_run_progress(engine, json_output=True) as progress:
        assert progress is None
        assert _observers(engine.events) == baseline
        _start(engine.events)
        _complete(engine.events)

    assert stream.getvalue() == ""


async def test_file_progress_binding_is_released(engine: _FakeEngine) -> None:
    """大文件进度与交互模式同一条路：作用域内绑定 reporter，退出即解绑（不留上下文残留）。"""
    from heagent.tools.builtins.file import _progress_reporter  # noqa: PLC0415 - 读取点即唯一判据

    before = _progress_reporter(100 * 1024 * 1024)
    async with interactive._single_run_progress(engine, json_output=False):
        pass
    assert _progress_reporter(100 * 1024 * 1024) is before
    assert before is None


async def test_single_run_wires_progress_and_restores_bus(
    engine: _FakeEngine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """端到端：``_run_single`` 真的把引擎事件接进进度行，退出后总线回基线、stdout 输出不变。"""
    stream = _FakeStream()
    clock = _Clock()
    monkeypatch.setattr(interactive, "ToolProgress", lambda **_: _tracker(stream, clock))
    monkeypatch.setattr(interactive, "_prepare_engine", lambda **_kw: (engine, None))
    monkeypatch.setattr(interactive, "_build_event_sink", lambda *_a, **_kw: None)
    monkeypatch.setattr(interactive, "_build_loop", lambda *_a, **_kw: (_FakeLoop(engine, clock), None))
    monkeypatch.setattr(interactive, "show_tool_activity", lambda _loop: None)
    monkeypatch.setattr(interactive, "_print_usage", lambda *_a, **_kw: None)
    baseline = _observers(engine.events)

    await interactive._run_single("跑一个长任务", _FakeProvider(), None, 5)  # type: ignore[arg-type]

    out = capsys.readouterr()
    assert out.out == "done\n"  # 最终答案原样输出，进度行不污染 stdout
    assert "[calling shell → pytest -q done in 3.6s]" in stream.getvalue()
    assert _observers(engine.events) == baseline  # run 结束后不留订阅


async def test_single_run_json_keeps_stderr_empty(
    engine: _FakeEngine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--json`` 下单次执行：stdout 仍是 JSONL 流，进度一个字节都不出现在 stderr。"""
    stream = _FakeStream()
    clock = _Clock()
    monkeypatch.setattr(interactive, "ToolProgress", lambda **_: _tracker(stream, clock))
    monkeypatch.setattr(interactive, "_prepare_engine", lambda **_kw: (engine, None))
    monkeypatch.setattr(interactive, "_build_event_sink", lambda *_a, **_kw: None)
    monkeypatch.setattr(interactive, "_build_loop", lambda *_a, **_kw: (_FakeLoop(engine, clock), None))
    monkeypatch.setattr(interactive, "show_tool_activity", lambda _loop: None)
    monkeypatch.setattr(interactive, "_print_usage", lambda *_a, **_kw: None)

    await interactive._run_single("跑一个长任务", _FakeProvider(), None, 5, json_output=True)  # type: ignore[arg-type]

    out = capsys.readouterr()
    assert stream.getvalue() == ""
    assert out.out == "done\n"  # sink 为 None 时仍回落到 echo（本断言只盯进度不污染输出）
    assert "[calling" not in out.err
