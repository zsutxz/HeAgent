"""EventLogScreen — 事件日志页面（Epic 28-1）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.screen import Screen
from textual.widgets import Footer, Header

if TYPE_CHECKING:
    from textual.app import ComposeResult


class EventLogScreen(Screen):
    """引擎事件日志查看页面。"""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
    ]

    CSS = """
    EventLogScreen {
        layout: vertical;
    }
    """

    def compose(self) -> ComposeResult:
        from heagent.gui.widgets.event_log import EventLog

        yield Header()
        yield EventLog()
        yield Footer()
