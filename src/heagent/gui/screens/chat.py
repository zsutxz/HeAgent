"""ChatScreen — 主聊天界面（简化版）。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Input, RichLog, Static

if TYPE_CHECKING:
    from heagent.gui.bridge import AgentBridge
    from heagent.gui.state import GuiState
    from heagent.types import StreamEvent

logger = logging.getLogger(__name__)

WELCOME = "[bold green]HeAgent[/]\n输入消息开始对话。[dim]/help 查看命令[/]"


class ChatScreen(Screen):
    """主聊天界面。"""

    BINDINGS = [("ctrl+l", "clear_screen", "清屏")]

    CSS = """
    ChatScreen { layout: vertical; }
    #chat-log { height: 1fr; border-bottom: solid $primary; }
    #status-line { height: 1; background: $panel; padding: 0 1; }
    #input-row { height: auto; padding: 1; }
    """

    def __init__(self, bridge: AgentBridge, state: GuiState,
                 *, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self._bridge = bridge
        self._state = state

    def compose(self):
        yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
        yield Static("", id="status-line")
        with Horizontal(id="input-row"):
            yield Input(placeholder="输入消息...", id="user-input")
            yield Button("发送", id="send-btn", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#chat-log", RichLog).write(WELCOME)
        self.set_interval(0.25, self._tick)
        self.query_one("#user-input", Input).focus()

    def _tick(self) -> None:
        """轮询状态 + 输入禁用。"""
        inp = self.query_one("#user-input", Input)
        btn = self.query_one("#send-btn", Button)
        running = self._state.is_running
        if inp.disabled != running:
            inp.disabled = running
            btn.disabled = running
            inp.placeholder = "Agent 运行中..." if running else "输入消息..."
        self.query_one("#status-line", Static).update(
            f"{self._state.model_name} │ Token: {self._state.token_usage.total_tokens} │ "
            f"轮: {self._state.iteration}/{self._state.max_iterations}"
            + (f" │ 🔧 {self._state.active_tool}" if self._state.active_tool else "")
            + (" │ ⏳" if running else "")
        )

    def on_unexpected_message(self, message: Message) -> None:
        msg_type = getattr(message, "type", "")
        payload = getattr(message, "payload", {})
        log = self.query_one("#chat-log", RichLog)
        if msg_type == "gui.stream_event":
            evt = payload.get("event")
            if evt is None:
                return
            if evt.type == "text":
                log.write(evt.text)
            elif evt.type == "tool_call":
                log.write(f"[dim]🔧 {evt.tool_name}...[/]")
            elif evt.type == "tool_result":
                result = evt.tool_result_content[:300]
                log.write(f"  [green]✓[/] {result}")
            elif evt.type == "done":
                self._finalize_state()
        elif msg_type == "gui.agent_interrupted":
            log.write("[dim italic][已中断][/]")
        elif msg_type == "gui.agent_error":
            log.write(f"[red][错误] {payload.get('error', '')}[/]")

    def _finalize_state(self) -> None:
        from heagent.gui.app import HeAgentApp
        app = HeAgentApp.get_current_app()
        if isinstance(app, HeAgentApp) and app._loop:
            loop = app._loop
            if loop.last_usage:
                self._state.token_usage = loop.last_usage
            if loop.last_iteration is not None:
                self._state.iteration = loop.last_iteration

    # ── input ──

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        inp = self.query_one("#user-input", Input)
        text = inp.value.strip()
        if not text:
            return
        inp.value = ""

        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0]
            if self._handle_slash(cmd, parts[1] if len(parts) > 1 else ""):
                return

        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold cyan]>[/] {text}")
        log.write("[bold green]🤖[/] ")
        asyncio.create_task(self._bridge.submit(text))

    def _handle_slash(self, cmd: str, args: str) -> bool:
        log = self.query_one("#chat-log", RichLog)
        if cmd == "/clear":
            log.clear()
            log.write(WELCOME)
            return True
        if cmd == "/help":
            log.write("[dim]/model /clear /help | Ctrl+L 清屏 | Ctrl+Q 退出[/]")
            return True
        if cmd == "/model":
            self._model_cmd(args)
            return True
        return False

    def _model_cmd(self, args: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        from heagent.gui.app import HeAgentApp
        app = HeAgentApp.get_current_app()
        if not isinstance(app, HeAgentApp) or not app._loop:
            return
        provider = app._loop.provider
        from heagent.providers.switchable import SwitchableProvider
        if not isinstance(provider, SwitchableProvider):
            log.write(f"[dim]当前: {provider.get_metadata().model}[/]")
            return
        if not args:
            info = provider.info()
            lines = ["[bold]可用模型:[/]"]
            for name, meta in info.items():
                marker = "[green]←[/]" if meta["active"] else ""
                lines.append(f"  {name} ({meta['model']}) {marker}")
            log.write("\n".join(lines))
            return
        target = args.strip()
        async def _switch():
            await provider.switch(target)
            self._state.model_name = provider.get_metadata().model
        asyncio.create_task(_switch())
        log.write(f"[dim]已切换到 {target}[/]")

    def action_clear_screen(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(WELCOME)
