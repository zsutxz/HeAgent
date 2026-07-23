"""Textual App — root application shell."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer

from heagent.gui.screens.chat import ChatScreen


class HeAgentApp(App):
    """HeAgent terminal UI application."""

    TITLE = "HeAgent"
    SUB_TITLE = "A self-improving AI Agent core framework"

    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
    ]

    def on_mount(self) -> None:
        """Push the main chat screen on startup."""
        self.push_screen(ChatScreen())

    def compose(self) -> ComposeResult:
        yield Footer()
