"""ToolCard — 工具调用折叠卡片（collapsible widget）。

Story 26-1：收到 StreamEvent(type="tool_call") 时插入折叠卡片，
StreamEvent(type="tool_result") 时更新状态和结果。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Collapsible, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ToolCard(Widget):
    """单个工具调用的折叠卡片。

    状态流转：pending → running → success / error。
    Reactive 驱动 UI 自动更新（Textual 框架特性）。
    """

    status: reactive[str] = reactive("pending")  # pending | running | success | error
    result_text: reactive[str] = reactive("")
    error_message: reactive[str] = reactive("")
    duration: reactive[str] = reactive("")

    def __init__(self, tool_name: str, *, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self.tool_name = tool_name

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(self._header_text(), id="card-header")
            with Collapsible(title="详情", collapsed=True), Vertical(id="card-body"):
                yield Static("", id="card-params")
                yield Static("", id="card-result")

    def _header_text(self) -> str:
        icon = {"pending": "⏳", "running": "🔧", "success": "✅", "error": "❌"}.get(self.status, "⬜")
        dur = f" ({self.duration})" if self.duration else ""
        return f"{icon} [bold]{self.tool_name}[/]{dur}"

    def watch_status(self, value: str) -> None:
        header = self.query_one("#card-header", Static)
        header.update(self._header_text())

    def set_result(self, content: str, *, is_error: bool = False, duration: str = "") -> None:
        """设置工具结果并更新状态。"""
        result_el = self.query_one("#card-result", Static)
        result_el.update(content)
        self.status = "error" if is_error else "success"
        if duration:
            self.duration = duration
