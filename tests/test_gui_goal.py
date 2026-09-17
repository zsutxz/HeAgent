"""GUI /goal 收口测试（2026-09-17 deferred 收口）。

覆盖台账三点：``/goal`` 由 goal runner 处理且**不**落到 ``bridge.submit``（锁定测试）、
stderr 进度按行转发 RichLog、Esc 取消入口。全部依赖 textual（可选组 gui），CI 无
textual 时经 :func:`pytest.importorskip` 跳过（与 ``test_gui_tool_state.py`` 同口径）。
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import TYPE_CHECKING

import click
import pytest

pytest.importorskip("textual")

from heagent.gui.state import GuiState

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


# ---- 前置：stderr 行转发器（纯逻辑，不依赖运行中的 App）----


class _RecordingLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        self.lines.append(text)


class TestStderrToLogForwarder:
    def test_partial_lines_are_buffered_until_newline(self) -> None:
        from heagent.gui.screens.chat import _StderrToLogForwarder

        log = _RecordingLog()
        forwarder = _StderrToLogForwarder(log)  # type: ignore[arg-type]
        forwarder.write("step 1")
        assert log.lines == []
        forwarder.write(" done\nnext\n")
        assert log.lines == ["[dim]step 1 done[/]", "[dim]next[/]"]

    def test_markup_is_escaped_and_blank_lines_skipped(self) -> None:
        from heagent.gui.screens.chat import _StderrToLogForwarder

        log = _RecordingLog()
        forwarder = _StderrToLogForwarder(log)  # type: ignore[arg-type]
        forwarder.write("[red]x[/]\n\nok\n")
        assert log.lines == ["[dim]\\[red]x\\[/][/]", "[dim]ok[/]"]

    def test_close_flushes_trailing_partial_line_idempotently(self) -> None:
        from heagent.gui.screens.chat import _StderrToLogForwarder

        log = _RecordingLog()
        forwarder = _StderrToLogForwarder(log)  # type: ignore[arg-type]
        forwarder.write("tail without newline")
        forwarder.close()
        forwarder.close()
        assert log.lines == ["[dim]tail without newline[/]"]


# ---- 交互测试（pilot 驱动真实 ChatScreen）----


def _make_app() -> tuple[object, object]:
    """构造最小可跑的 HeAgentApp（fake loop 只需 .provider/.engine 非空）。"""
    from heagent.gui.app import HeAgentApp
    from heagent.gui.bridge import AgentBridge

    state = GuiState()
    bridge = AgentBridge(loop=None, state=state)  # type: ignore[arg-type]
    app = HeAgentApp(
        bridge,
        state,
        loop=SimpleNamespace(provider=object(), engine=object()),  # type: ignore[arg-type]
    )
    return app, bridge


async def _submit_and_wait(pilot: object, text: str, *, until: Callable[[], bool]) -> None:
    from textual.widgets import Input

    screen = pilot.app.screen
    inp = screen.query_one("#user-input", Input)
    inp.focus()
    inp.value = text
    await pilot.press("enter")
    for _ in range(100):
        if until():
            return
        await pilot.pause()
    raise AssertionError("等待条件超时：/goal task 未达到预期状态")


@pytest.mark.asyncio
async def test_goal_command_routes_to_goal_runner_not_bridge_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    """台账锁定测试：GUI 里 ``/goal status`` 进 goal runner，不当普通提示词提交。"""
    import heagent.cli_goal as cli_goal

    goal_calls: list[str] = []
    bridge_calls: list[str] = []

    async def fake_runner(provider: object, engine: object, args: str, *, cron_store: object = None) -> None:
        goal_calls.append(args)

    async def fake_submit(prompt: str) -> None:
        bridge_calls.append(prompt)

    monkeypatch.setattr(cli_goal, "_goal_runner", fake_runner)
    app, bridge = _make_app()
    monkeypatch.setattr(bridge, "submit", fake_submit)

    from heagent.gui.app import HeAgentApp

    assert isinstance(app, HeAgentApp)
    async with app.run_test() as pilot:
        await _submit_and_wait(pilot, "/goal status", until=lambda: bool(goal_calls))

    assert goal_calls == ["status"]
    assert bridge_calls == []


@pytest.mark.asyncio
async def test_stderr_progress_is_forwarded_to_richlog(monkeypatch: pytest.MonkeyPatch) -> None:
    """click.echo(err=True) 的进度行出现在 RichLog（原先用户只看到一行 completed）。"""
    import heagent.cli_goal as cli_goal

    async def echo_runner(provider: object, engine: object, args: str, *, cron_store: object = None) -> None:
        click.echo("[goal] step 1/3 running", err=True)
        click.echo("[goal] done", err=True)

    monkeypatch.setattr(cli_goal, "_goal_runner", echo_runner)
    app, _bridge = _make_app()

    from heagent.gui.app import HeAgentApp

    assert isinstance(app, HeAgentApp)
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        from textual.widgets import RichLog

        rich_log = screen.query_one("#chat-log", RichLog)

        def _forwarded() -> bool:
            texts = [strip.text for strip in rich_log.lines]
            return any("[goal] step 1/3 running" in t for t in texts)

        # 等「转发行出现」而非 is_running 翻转：任务在一轮 pause 内即可跑完，后者有竞态。
        await _submit_and_wait(pilot, "/goal status", until=_forwarded)
        texts = [strip.text for strip in rich_log.lines]
    assert any("[goal] step 1/3 running" in t for t in texts)
    assert any("[goal] done" in t for t in texts)


@pytest.mark.asyncio
async def test_escape_cancels_running_goal_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Esc 触发取消：goal task cancelled、is_running 复位（原先无任何取消入口）。"""
    import heagent.cli_goal as cli_goal

    async def hanging_runner(provider: object, engine: object, args: str, *, cron_store: object = None) -> None:
        await asyncio.Event().wait()  # 永不完成

    monkeypatch.setattr(cli_goal, "_goal_runner", hanging_runner)
    app, _bridge = _make_app()

    from heagent.gui.app import HeAgentApp

    assert isinstance(app, HeAgentApp)
    async with app.run_test() as pilot:
        screen = pilot.app.screen
        await _submit_and_wait(pilot, "/goal status", until=lambda: screen._state.is_running)

        await pilot.press("escape")
        task = screen._pending_submit
        assert task is not None
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2.0)
        assert task.cancelled()
        assert screen._state.is_running is False
