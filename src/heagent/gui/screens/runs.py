"""RunsScreen — 运行历史面板（Epic 28 占位）。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class RunsScreen(Screen):
    """运行历史面板 —— Epic 28 将实现 RunStore.build_run_tree 渲染。"""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[dim]运行历史面板将在 Epic 28 中实现[/]\n\n"
                     "功能：运行树渲染 / 详情查看 / 恢复运行")
        yield Footer()
