"""EventLog — 引擎事件实时日志 widget（RichLog + 自动滚动）。

Epic 28-1：订阅 GuiEventObserver 缓冲，定时拉取渲染。
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog


class EventLog(Widget):
    """实时引擎事件日志（基于 RichLog）。

    Space 暂停/恢复自动滚动，Ctrl+L 清空。
    """

    paused: reactive[bool] = reactive(False)

    def __init__(self, *, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self._log: RichLog | None = None
        self._last_rendered_idx: int = 0  # 在缓冲中的渲染位置

    def compose(self):
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
        """定时拉取观察者的新事件并渲染。"""
        from heagent.gui.app import HeAgentApp

        app = HeAgentApp.get_current_app()
        if not isinstance(app, HeAgentApp):
            return
        observer = getattr(app, "_event_observer", None)
        if observer is None:
            return

        recent = observer.get_recent(limit=200)
        # 渲染新事件（新事件在列表前面）
        new_events = recent[: max(0, len(recent) - self._last_rendered_idx)]
        self._last_rendered_idx = len(recent)

        if not new_events or self.paused:
            return

        assert self._log is not None
        for ts, evt_type, details in reversed(new_events):
            tool = details.get("tool_name", "")
            run_id = details.get("run_id", "")[:8]
            error = details.get("error", "")
            color = {
                "tool_call_started": "green",
                "tool_call_completed": "bright_green",
                "tool_call_failed": "red",
                "tool_call_blocked": "yellow",
                "provider_call_started": "blue",
                "provider_call_completed": "bright_blue",
                "run_completed": "bright_cyan",
                "run_failed": "red",
                "iteration_started": "dim",
            }.get(evt_type, "dim")

            detail_str = f" tool={tool}" if tool else ""
            if error:
                detail_str += f" error={error[:50]}"
            if run_id:
                detail_str += f" run={run_id}"
            self._log.write(f"[{color}]{evt_type}[/] {detail_str}")

    def watch_paused(self, value: bool) -> None:
        if self._log and not value:
            self._log.write("[dim]— 自动滚动已恢复 —[/]")

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
        self._last_rendered_idx = 0
