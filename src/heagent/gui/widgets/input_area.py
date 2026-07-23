"""InputArea — 用户输入区域（Input + 发送 + 斜杠命令补全）。

Story 26-2：支持 /model、/mcp-prompt、/clear、/help 斜杠命令。
Tab 补全斜杠命令名称；Enter 发送或执行斜杠命令。
"""

from __future__ import annotations

from textual import events
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Input

# 支持的斜杠命令列表（供 Tab 补全）
_SLASH_COMMANDS = ["/model", "/mcp-prompt", "/clear", "/help"]


class InputArea(Widget):
    """底部输入区域：单行 Input + 发送按钮。

    Enter 发送消息或执行斜杠命令；Tab 补全斜杠命令；
    Escape 清空；Agent 执行期间自动禁用。
    """

    disabled: reactive[bool] = reactive(False)

    def __init__(
        self,
        *,
        on_submit,
        on_slash_command=None,
        name: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id)
        self._on_submit = on_submit  # callback(prompt: str)
        self._on_slash_command = on_slash_command  # callback(command: str, args: str) -> bool

    def compose(self):
        with Horizontal(id="input-row"):
            yield Input(
                placeholder="输入消息... (Enter 发送, / 斜杠命令)",
                id="user-input",
            )
            yield Button("发送", id="send-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            self._do_submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_submit()

    def _on_key(self, event: events.Key) -> None:
        """Escape 清空输入框；Tab 补全斜杠命令。"""
        inp = self.query_one("#user-input", Input)
        if event.key == "escape":
            inp.value = ""
            inp.focus()
        elif event.key == "tab":
            self._try_autocomplete()

    def _try_autocomplete(self) -> None:
        """Tab 键：若当前输入以 / 开头，尝试补全斜杠命令名。"""
        inp = self.query_one("#user-input", Input)
        text = inp.value.strip()
        if not text.startswith("/"):
            return
        # 找匹配的斜杠命令
        matches = [cmd for cmd in _SLASH_COMMANDS if cmd.startswith(text.split()[0])]
        if len(matches) == 1:
            # 保留空格后的参数
            parts = text.split(maxsplit=1)
            suffix = f" {parts[1]}" if len(parts) > 1 else ""
            inp.value = f"{matches[0]}{suffix}"
            inp.cursor_position = len(inp.value)

    def watch_disabled(self, value: bool) -> None:
        """执行期间禁用输入框和按钮。"""
        inp = self.query_one("#user-input", Input)
        btn = self.query_one("#send-btn", Button)
        inp.disabled = value
        btn.disabled = value
        if value:
            inp.placeholder = "Agent 运行中..."
        else:
            inp.placeholder = "输入消息... (Enter 发送, / 斜杠命令)"

    def focus_input(self) -> None:
        """将焦点设到输入框。"""
        self.query_one("#user-input", Input).focus()

    def _do_submit(self) -> None:
        inp = self.query_one("#user-input", Input)
        text = inp.value.strip()
        if not text:
            return
        inp.value = ""

        # 斜杠命令路由
        if text.startswith("/") and self._on_slash_command is not None:
            parts = text.split(maxsplit=1)
            command = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            handled = self._on_slash_command(command, args)
            if handled:
                return
            # 未识别的斜杠命令 → 当作普通文本发送

        self._on_submit(text)
