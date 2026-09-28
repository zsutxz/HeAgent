"""EventLog — 引擎事件实时日志 widget（RichLog + 自动滚动）。

Epic 28-1：订阅 GuiEventObserver 缓冲，定时拉取渲染。

2026-09-28（台账 A24）修两处展示缺陷：

* **差分冻结** —— 旧实现用「缓冲窗口长度 − 已渲染数」做差，窗口一到上限
  （``get_recent(limit=200)``，环形缓冲 500）两者恒相等 ⇒ 差分恒为 0，日志此后**永久
  不再渲染**。现改为消费观察者的**单调总数**（``EventCursor``，纯逻辑在
  ``heagent.pub.event_lines``，不进 GUI 包 ⇒ 在 CI（无 textual）也能被单测钉住）。
* **暂停即丢事件** —— 旧实现在暂停时照样推进索引，恢复后那段事件永久丢失。现暂停期间
  不推进游标，恢复时补渲染（窗口溢出则显式提示丢了几条）。

渲染字段：耗时（``duration=12ms``）/ 失败分类（``kind=…``）/ 迭代 / 作用对象 / workflow
步骤与 story。数值全部经 ``rich.markup.escape``——事件值（含工具输出、错误文本）**不可信**，
其中形如 ``[red]`` 的片段在 ``markup=True`` 的 RichLog 里会被当标记解释。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog

from heagent.pub.event_lines import EventCursor, format_event_line

if TYPE_CHECKING:
    from textual.app import ComposeResult

#: 事件类型 → RichLog 颜色（未知类型按 ``dim`` 原样渲染，开集语义）。
_COLORS: dict[str, str] = {
    "tool_call_started": "green",
    "tool_call_completed": "bright_green",
    "tool_call_failed": "red",
    "tool_call_blocked": "yellow",
    "provider_call_started": "blue",
    "provider_call_completed": "bright_blue",
    "run_completed": "bright_cyan",
    "run_failed": "red",
    "iteration_started": "dim",
    "workflow_step_started": "magenta",
    "workflow_step_completed": "bright_magenta",
    "workflow_step_failed": "red",
}


class EventLog(Widget):
    """实时引擎事件日志（基于 RichLog）。

    Space 暂停/恢复渲染，Ctrl+L 清空。
    """

    paused: reactive[bool] = reactive(False)

    def __init__(self, *, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self._log: RichLog | None = None
        self._cursor = EventCursor()

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="event-log-view",
            highlight=True,
            markup=True,
            wrap=True,
        )

    def on_mount(self) -> None:
        self._log = self.query_one("#event-log-view", RichLog)
        self._log.write("[dim]事件日志 — 等待引擎事件...[/]")
        self.set_interval(0.5, self._poll)

    async def _poll(self) -> None:
        """拉取新事件并渲染；差分与格式化的纯逻辑在 ``heagent.pub.event_lines``。"""
        from heagent.gui.app import HeAgentApp

        app = HeAgentApp.get_current_app()
        if not isinstance(app, HeAgentApp):
            return
        observer = getattr(app, "_event_observer", None)
        if observer is None or self._log is None:
            return
        if self.paused:
            # 暂停 = 暂停渲染，不丢事件：不推进游标，恢复时一并渲染。
            return

        events, total = observer.snapshot()
        new_events, lost = self._cursor.take(total, events)
        if lost:
            self._log.write(f"[dim]…（缓冲滚动，{lost} 条较早事件未显示）[/]")
        for _ts, evt_type, details in new_events:
            color = _COLORS.get(evt_type, "dim")
            self._log.write(f"[{color}]{escape(format_event_line(evt_type, details))}[/]")

    def watch_paused(self, value: bool) -> None:
        if not value and self._log:
            self._log.write("[dim]— 渲染已恢复（暂停期间的事件在此补显示）—[/]")

    def clear(self) -> None:
        if self._log:
            self._log.clear()
            self._log.write("[dim]事件日志已清空[/]")
        from heagent.gui.app import HeAgentApp

        app = HeAgentApp.get_current_app()
        if isinstance(app, HeAgentApp):
            observer = getattr(app, "_event_observer", None)
            if observer:
                observer.clear()
        self._cursor.reset()
