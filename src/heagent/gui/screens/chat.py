"""ChatScreen — 主聊天界面（流式对话 + 工具调用可视化）。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, RichLog, Static

from heagent.config import get_settings
from heagent.gui.bridge import MSG_AGENT_ERROR, MSG_AGENT_INTERRUPTED, MSG_STREAM_EVENT, BridgeMessage

if TYPE_CHECKING:
    from heagent.gui.bridge import AgentBridge
    from heagent.gui.state import GuiState
    from heagent.types import StreamEvent

logger = logging.getLogger(__name__)

WELCOME = "[bold green]HeAgent[/]\n输入消息开始对话。[dim]/help 查看命令[/]"


def _format_tokens_k(n: int) -> str:
    """Format token count with K/M suffix."""
    if n < 1000:
        return str(n)
    if n >= 1_000_000:
        m = n / 1_000_000
        if m == int(m):
            return f"{int(m)}M"
        return f"{m:.1f}M"
    k = n / 1000
    if k == int(k):
        return f"{int(k)}K"
    return f"{k:.1f}K"


class ChatScreen(Screen):
    """主聊天界面。

    BridgeMessage 处理链：
        AgentBridge.post() → App.on_bridge_message() → ChatScreen.on_bridge_message()
    """

    BINDINGS = [("ctrl+l", "clear_screen", "清屏")]

    CSS = """
    ChatScreen { layout: vertical; }
    #chat-log { height: 1fr; border-bottom: solid $primary; }
    #status-line { height: 1; background: $panel; padding: 0 1; }
    #input-row { height: auto; padding: 1; }
    """

    def __init__(self, bridge: AgentBridge, state: GuiState, *, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self._bridge = bridge
        self._state = state
        self._pending_submit: asyncio.Task[None] | None = None
        self._pending_switch: asyncio.Task[None] | None = None

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
        s = get_settings()
        self._state.max_context_tokens = s.max_context_tokens
        self._state.compression_threshold = s.compression_threshold

    def _tick(self) -> None:
        """轮询状态 + 输入禁用。"""
        inp = self.query_one("#user-input", Input)
        btn = self.query_one("#send-btn", Button)
        running = self._state.is_running
        if inp.disabled != running:
            inp.disabled = running
            btn.disabled = running
            inp.placeholder = "Agent 运行中..." if running else "输入消息..."

        max_ctx = self._state.max_context_tokens
        tok_str = (
            f"{self._state.token_usage.total_tokens}/{max_ctx} tok"
            if max_ctx > 0
            else f"Tok: {self._state.token_usage.total_tokens}"
        )
        cumul = self._state.cumulative_tokens
        cumul_str = f"累计: {_format_tokens_k(cumul)} tok" if cumul > 0 else ""
        cmp_pct = int(self._state.compression_threshold * 100)
        parts = [
            self._state.model_name,
            tok_str,
            f"cmp@{cmp_pct}%",
            f"轮: {self._state.iteration}/{self._state.max_iterations}",
        ]
        if cumul_str:
            parts.append(cumul_str)
        if self._state.active_tool:
            parts.append(f"🔧 {self._state.active_tool}")
        if running:
            parts.append("⏳")
        self.query_one("#status-line", Static).update(" │ ".join(parts))

    # ── BridgeMessage 处理 ──────────────────────────────────

    def on_bridge_message(self, message: BridgeMessage) -> None:
        """处理来自 AgentBridge 的消息（由 App 转发到此）。"""
        log = self.query_one("#chat-log", RichLog)
        msg_type = message.msg_type
        payload = message.payload

        if msg_type == MSG_STREAM_EVENT:
            evt = payload.get("event")
            if evt is None:
                return
            evt_typed: StreamEvent = evt  # type: ignore[assignment]
            if evt_typed.type == "text":
                log.write(evt_typed.text)
            elif evt_typed.type == "tool_call":
                log.write(f"[dim]🔧 {evt_typed.tool_name}...[/]")
            elif evt_typed.type == "tool_result":
                result = evt_typed.tool_result_content[:300]
                log.write(f"  [green]✓[/] {result}")
            elif evt_typed.type == "done":
                self._finalize_state()
        elif msg_type == MSG_AGENT_INTERRUPTED:
            log.write("[dim italic][已中断][/]")
        elif msg_type == MSG_AGENT_ERROR:
            log.write(f"[red][错误] {payload.get('error', '')}[/]")

    def _finalize_state(self) -> None:
        from heagent.gui.app import HeAgentApp

        app = HeAgentApp.get_current_app()
        if isinstance(app, HeAgentApp) and app.agent_loop:
            loop = app.agent_loop
            if loop.last_usage:
                self._state.token_usage = loop.last_usage
            if loop.last_iteration is not None:
                self._state.iteration = loop.last_iteration
            self._state.cumulative_tokens = loop.cumulative_tokens

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
        self._pending_submit = asyncio.create_task(self._bridge.submit(text))

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
        if not isinstance(app, HeAgentApp) or not app.agent_loop:
            return
        provider = app.agent_loop.provider
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
            try:
                await provider.switch(target)
                s = get_settings()
                self._state.model_name = provider.get_metadata().model
                self._state.max_context_tokens = s.max_context_tokens
                self._state.compression_threshold = s.compression_threshold
                log.write(f"[dim]已切换到 {target}[/]")
            except ValueError as exc:
                log.write(f"[red]切换失败: {exc}[/]")

        self._pending_switch = asyncio.create_task(_switch())

    def action_clear_screen(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(WELCOME)
