"""MessageList — 流式 Markdown 消息列表（RichLog + ToolCard widgets）。

基于 Textual 的 RichLog widget（原生 Markdown 高亮），
在消息之间插入 ToolCard 表示工具调用。
"""

from __future__ import annotations

import time

from textual.widget import Widget
from textual.widgets import RichLog

from heagent.gui.widgets.tool_card import ToolCard


class MessageList(Widget):
    """聊天消息列表：流式 Markdown 渲染 + 工具调用卡片。"""

    def __init__(self, *, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self._log: RichLog | None = None
        # 当前正在流式写入的 agent 消息状态
        self._streaming_agent: bool = False
        # 最近一张 ToolCard（用于 tool_result 时更新）
        self._last_tool_card: ToolCard | None = None
        # 工具调用开始时间（用于计算耗时）
        self._tool_started_at: float = 0.0

    def compose(self):
        yield RichLog(
            id="chat-log",
            highlight=True,
            markup=True,
            wrap=True,
            min_width=40,
        )

    def on_mount(self) -> None:
        self._log = self.query_one("#chat-log", RichLog)

    # ── 公开 API ─────────────────────────────────────────────

    def append_user_message(self, text: str) -> None:
        """追加一条用户消息。"""
        assert self._log is not None
        self._log.write(f"[bold cyan]>[/] {text}")

    def begin_agent_message(self) -> None:
        """开始一条 agent 消息（后续 append_text 流式追加到同一段）。"""
        assert self._log is not None
        self._log.write("[bold green]🤖[/] ")
        self._streaming_agent = True

    def append_text(self, text: str) -> None:
        """流式追加一行 agent 文本（Markdown）。"""
        assert self._log is not None
        self._log.write(text)

    def insert_tool_card(self, tool_name: str) -> ToolCard:
        """插入一张工具调用卡片，返回引用供后续更新。"""
        assert self._log is not None
        self._streaming_agent = False
        self._tool_started_at = time.monotonic()
        card = ToolCard(tool_name)
        self._last_tool_card = card
        self._log.mount(card)
        return card

    def update_tool_result(self, content: str, is_error: bool = False) -> None:
        """更新最近一张工具卡片的结果。"""
        if self._last_tool_card is None:
            return
        duration = f"{time.monotonic() - self._tool_started_at:.1f}s"
        # 截断过长的工具结果（超 500 字符折叠）
        display = content if len(content) <= 500 else content[:500] + "..."
        self._last_tool_card.set_result(display, is_error=is_error, duration=duration)

    def end_agent_message(self) -> None:
        """结束当前 agent 消息。"""
        self._streaming_agent = False

    def append_system_message(self, text: str) -> None:
        """追加一条系统消息（中断 / 错误等）。"""
        assert self._log is not None
        self._log.write(f"[dim italic]{text}[/]")

    def clear(self) -> None:
        """清空消息列表。"""
        assert self._log is not None
        self._log.clear()
        self._streaming_agent = False
        self._last_tool_card = None
