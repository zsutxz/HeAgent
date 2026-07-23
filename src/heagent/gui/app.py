"""Textual App — root application shell.

持有 AgentLoop / AgentBridge / GuiState，管理 Screen 栈和全局快捷键。
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer

from heagent.gui.bridge import AgentBridge
from heagent.gui.screens.chat import ChatScreen
from heagent.gui.state import GuiState


class HeAgentApp(App):
    """HeAgent terminal UI application."""

    TITLE = "HeAgent"
    SUB_TITLE = "A self-improving AI Agent"

    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
    ]

    def __init__(
        self,
        bridge: AgentBridge,
        state: GuiState,
        *,
        loop=None,  # AgentLoop, 供 ChatScreen 在 done 时读取 last_usage/last_iteration
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._state = state
        self._loop = loop  # type: ignore[assignment]

    def on_mount(self) -> None:
        """Push the main chat screen on startup."""
        self.push_screen(ChatScreen(self._bridge, self._state))

    def compose(self) -> ComposeResult:
        yield Footer()
