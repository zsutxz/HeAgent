"""EventLogScreen — 引擎事件日志面板（Epic 28-1）。

实时展示 EventBus 事件流，Space 暂停/恢复，Ctrl+L 清空。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header

from heagent.gui.widgets.event_log import EventLog


class EventLogScreen(Screen):
    """引擎事件日志面板。"""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
        ("space", "toggle_pause", "暂停/恢复"),
        ("ctrl+l", "clear_log", "清空日志"),
    ]

    CSS = """
    EventLogScreen {
        layout: vertical;
    }
    #event-log-container {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield EventLog(id="event-log-container")
        yield Footer()

    def action_toggle_pause(self) -> None:
        log = self.query_one(EventLog)
        log.paused = not log.paused

    def action_clear_log(self) -> None:
        self.query_one(EventLog).clear()
