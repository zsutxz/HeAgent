"""CronAddModal — 添加 Cron 任务的弹窗。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, Switch

if TYPE_CHECKING:
    from textual.app import ComposeResult


class CronAddModal(ModalScreen[None]):
    """添加 Cron 任务弹窗。"""

    CSS = """
    CronAddModal {
        align: center middle;
    }
    #add-box {
        width: 50;
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 1 2;
    }
    """

    def __init__(self, store, refresh_cb) -> None:
        super().__init__()
        self._store = store
        self._refresh = refresh_cb

    def compose(self) -> ComposeResult:
        with Vertical(id="add-box"):
            yield Static("[bold]添加 Cron 任务[/]")
            yield Label("提示词")
            yield Input(placeholder="Agent 要执行的提示词", id="input-prompt")
            yield Label("Cron 表达式")
            yield Input(placeholder="如: 0 9 * * *", id="input-schedule")
            yield Label("启用")
            yield Switch(value=True, id="switch-enabled")
            yield Button("创建", id="btn-create", variant="primary")
            yield Button("取消", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss()
        elif event.button.id == "btn-create":
            self._do_create()

    def _do_create(self) -> None:
        prompt = self.query_one("#input-prompt", Input).value.strip()
        schedule = self.query_one("#input-schedule", Input).value.strip()
        enabled = self.query_one("#switch-enabled", Switch).value
        if not prompt or not schedule:
            return
        if self._store:
            self._store.add(prompt, schedule, enabled)
        self._refresh()
        self.dismiss()
