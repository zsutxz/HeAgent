"""CronAddModal — 添加 Cron 任务的弹窗。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Switch, Static


class CronAddModal(ModalScreen[None]):
    """新建 Cron 任务弹窗。"""

    def __init__(self, store, refresh_cb) -> None:
        super().__init__()
        self._store = store
        self._refresh = refresh_cb

    CSS = """
    CronAddModal {
        align: center middle;
    }
    #add-dialog {
        width: 50;
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="add-dialog"):
            yield Static("[bold]添加 Cron 任务[/]", id="add-title")
            yield Label("Prompt (任务描述)")
            yield Input(placeholder="如: 获取 AI 新闻", id="add-prompt")
            yield Label("Cron 表达式")
            yield Input(placeholder="如: 0 9 * * *", id="add-schedule")
            yield Label("循环执行")
            yield Switch(value=True, id="add-recurring")
            yield Button("创建", id="btn-create", variant="primary")
            yield Button("取消", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss()
        elif event.button.id == "btn-create":
            self._do_create()

    def _do_create(self) -> None:
        prompt = self.query_one("#add-prompt", Input).value.strip()
        schedule = self.query_one("#add-schedule", Input).value.strip()
        recurring = self.query_one("#add-recurring", Switch).value
        if not prompt or not schedule:
            return
        if self._store:
            job = self._store.create_job(prompt, schedule, recurring=recurring)
            self._store.add(job)
        self._refresh()
        self.dismiss()
