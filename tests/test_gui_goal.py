"""GUI /goal 收口测试（2026-09-17 收口；2026-09-28 台账 A4b 改判据）。

覆盖台账三点：``/goal`` 由 goal runner 处理且**不**落到 ``bridge.submit``（锁定测试）、
``/goal`` 文案经 **on_message sink** 进 RichLog（不再是 stderr 全量重定向）、Esc 取消入口。
另加两条 A4b 判据：**日志 / 第三方 stderr 写不得进对话区**；GUI 侧源码不得再出现
``redirect_stderr``（结构性判据，CI 无 textual 时也由 ``test_goal_message_sink.py`` 覆盖）。
全部依赖 textual（可选组 gui），CI 无 textual 时经 :func:`pytest.importorskip` 跳过。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("textual")

from heagent.gui.state import GuiState

if TYPE_CHECKING:
    from collections.abc import Callable

CHAT_SOURCE = Path(__file__).resolve().parents[1] / "src" / "heagent" / "gui" / "screens" / "chat.py"


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


def _richlog_texts(rich_log: object) -> list[str]:
    return [strip.text for strip in rich_log.lines]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_goal_command_routes_to_goal_runner_not_bridge_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    """台账锁定测试：GUI 里 ``/goal status`` 进 goal runner，不当普通提示词提交。"""
    import heagent.cli.goal as cli_goal

    goal_calls: list[str] = []
    bridge_calls: list[str] = []

    async def fake_runner(
        provider: object, engine: object, args: str, *, cron_store: object = None, on_message: object = None
    ) -> None:
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
async def test_goal_progress_reaches_richlog_through_the_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4b：GUI 把 ``on_message`` 交给 runner，runner 投递的文案出现在 RichLog。"""
    import heagent.cli.goal as cli_goal

    async def sink_runner(
        provider: object, engine: object, args: str, *, cron_store: object = None, on_message: object = None
    ) -> None:
        assert callable(on_message), "GUI 必须传 on_message sink（台账 A4b）"
        on_message("[goal] step 1/3 running")  # type: ignore[operator]
        on_message("[goal] done")  # type: ignore[operator]

    monkeypatch.setattr(cli_goal, "_goal_runner", sink_runner)
    app, _bridge = _make_app()

    from heagent.gui.app import HeAgentApp

    assert isinstance(app, HeAgentApp)
    async with app.run_test() as pilot:
        from textual.widgets import RichLog

        rich_log = pilot.app.screen.query_one("#chat-log", RichLog)

        def _forwarded() -> bool:
            return any("[goal] step 1/3 running" in t for t in _richlog_texts(rich_log))

        await _submit_and_wait(pilot, "/goal status", until=_forwarded)
        texts = _richlog_texts(rich_log)
    assert any("[goal] step 1/3 running" in t for t in texts)
    assert any("[goal] done" in t for t in texts)


@pytest.mark.asyncio
async def test_goal_run_does_not_leak_logs_or_raw_stderr_into_the_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4b：``/goal`` 期间的 logging 记录与直接写 stderr 的内容**不得**进对话区。

    旧实现靠 ``redirect_stderr`` 截获文案 ⇒ logging（GUI 的 console handler）与第三方 stderr
    写入被一并吞进聊天日志。变异体：把 ``redirect_stderr`` 加回 chat.py ⇒ 本用例精确变红。
    """
    import heagent.cli.goal as cli_goal

    async def noisy_runner(
        provider: object, engine: object, args: str, *, cron_store: object = None, on_message: object = None
    ) -> None:
        logging.getLogger("heagent.tests.noisy").warning("SECRET-LOG-LINE")
        sys.stderr.write("RAW-STDERR-LINE\n")
        sys.stderr.flush()
        if callable(on_message):
            on_message("[goal] only this belongs in the chat")  # type: ignore[operator]

    monkeypatch.setattr(cli_goal, "_goal_runner", noisy_runner)
    app, _bridge = _make_app()

    from heagent.gui.app import HeAgentApp

    assert isinstance(app, HeAgentApp)
    async with app.run_test() as pilot:
        from textual.widgets import RichLog

        rich_log = pilot.app.screen.query_one("#chat-log", RichLog)

        def _ok() -> bool:
            return any("only this belongs" in t for t in _richlog_texts(rich_log))

        await _submit_and_wait(pilot, "/goal status", until=_ok)
        texts = _richlog_texts(rich_log)

    joined = "\n".join(texts)
    assert "only this belongs" in joined
    assert "SECRET-LOG-LINE" not in joined, "日志记录不得进对话区（A4b）"
    assert "RAW-STDERR-LINE" not in joined, "直接写 stderr 的内容不得进对话区（A4b）"


@pytest.mark.asyncio
async def test_escape_cancels_running_goal_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Esc 触发取消：goal task cancelled、is_running 复位（原先无任何取消入口）。"""
    import heagent.cli.goal as cli_goal

    async def hanging_runner(
        provider: object, engine: object, args: str, *, cron_store: object = None, on_message: object = None
    ) -> None:
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


def test_chat_screen_no_longer_redirects_stderr() -> None:
    """结构性判据（不依赖 textual 实例）：chat.py 不得再出现 stderr 全量重定向（A4b）。"""
    source = CHAT_SOURCE.read_text(encoding="utf-8")
    assert "redirect_stderr" not in source
    assert "_StderrToLogForwarder" not in source
    assert "on_message=" in source, "GUI 必须把 on_message sink 传给 goal runner"
