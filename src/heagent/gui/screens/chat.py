"""Main chat screen — placeholder for 24-2."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class ChatScreen(Screen):
    """Main chat interface screen."""

    def compose(self) -> ComposeResult:
        yield Static("[bold]HeAgent[/]\n\n终端聊天界面即将推出...\n\n按 Ctrl+Q 退出")
