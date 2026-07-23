"""EventLogScreen — 引擎事件日志面板（Epic 28 占位）。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class EventLogScreen(Screen):
    """引擎事件日志面板 —— Epic 28 将实现 EventBus 实时订阅渲染。"""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[dim]事件日志面板将在 Epic 28 中实现[/]\n\n"
                     "功能：EventBus 实时事件流 / 过滤 / 暂停/恢复")
        yield Footer()
