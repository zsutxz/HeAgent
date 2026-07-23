"""CronScreen — Cron 任务管理面板（DataTable + 添加/删除）。

Story 27-3：列出定时任务，添加新任务，删除任务。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header

if TYPE_CHECKING:
    from heagent.cron.jobs import JobStore


class CronScreen(Screen):
    """Cron 任务管理面板。"""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
    ]

    CSS = """
    CronScreen {
        layout: vertical;
    }
    #cron-table {
        height: 1fr;
    }
    #cron-actions {
        height: auto;
        padding: 1;
    }
    """

    def __init__(self, store: JobStore | None = None) -> None:
        super().__init__()
        self._store = store

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="cron-table")
        with Container(id="cron-actions"):
            with Horizontal():
                yield Button("添加任务", id="btn-add", variant="primary")
                yield Button("删除任务", id="btn-delete", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#cron-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "Prompt", "Schedule", "状态", "上次执行")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#cron-table", DataTable)
        table.clear()
        if self._store is None:
            return
        corruption = self._store.corruption_count
        if corruption != 0:
            table.add_row("—", f"[yellow]⚠ 检测到 {corruption} 条损坏记录[/]", "—", "—", "—")
        for job in self._store.list_jobs():
            status = "✅" if job.enabled else "⏸"
            last = job.last_run[:16] if job.last_run else "从未"
            prompt = job.prompt[:40] + ("..." if len(job.prompt) > 40 else "")
            table.add_row(job.id[:8], prompt, job.cron, status, last)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-add":
            from heagent.gui.screens.cron_add import CronAddModal
            self.app.push_screen(CronAddModal(self._store, self._refresh_table))
        elif btn_id == "btn-delete":
            self._delete_selected()

    def _delete_selected(self) -> None:
        table = self.query_one("#cron-table", DataTable)
        row = table.cursor_row
        if row is None or self._store is None:
            return
        row_data = table.get_row_at(row)
        if row_data[0] == "—":  # 损坏记录提示行
            return
        job_id_prefix = str(row_data[0])
        for job in self._store.list_jobs():
            if job.id.startswith(job_id_prefix):
                self._store.remove(job.id)
                self._refresh_table()
                return
