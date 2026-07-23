"""InputArea — 用户输入区域（多行 Input + 发送语义）。"""

from __future__ import annotations

from textual import events
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Input


class InputArea(Widget):
    """底部输入区域：单行 Input + 发送按钮。

    支持 Enter 发送、Escape 清空；Agent 执行期间自动禁用。
    """

    disabled: reactive[bool] = reactive(False)

    def __init__(self, *, on_submit, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self._on_submit = on_submit  # callback(prompt: str)

    def compose(self):
        with Horizontal(id="input-row"):
            yield Input(
                placeholder="输入消息... (Enter 发送)",
                id="user-input",
            )
            yield Button("发送", id="send-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            self._do_submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_submit()

    def _on_key(self, event: events.Key) -> None:
        """Escape 清空输入框。"""
        if event.key == "escape":
            inp = self.query_one("#user-input", Input)
            inp.value = ""
            inp.focus()

    def watch_disabled(self, value: bool) -> None:
        """执行期间禁用输入框和按钮。"""
        inp = self.query_one("#user-input", Input)
        btn = self.query_one("#send-btn", Button)
        inp.disabled = value
        btn.disabled = value
        if value:
            inp.placeholder = "Agent 运行中..."
        else:
            inp.placeholder = "输入消息... (Enter 发送)"

    def focus_input(self) -> None:
        """将焦点设到输入框。"""
        self.query_one("#user-input", Input).focus()

    def _do_submit(self) -> None:
        inp = self.query_one("#user-input", Input)
        text = inp.value.strip()
        if text:
            inp.value = ""
            self._on_submit(text)
