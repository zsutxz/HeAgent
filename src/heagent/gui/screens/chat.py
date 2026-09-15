"""ChatScreen — 主聊天界面（流式对话 + 工具调用可视化）。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, RichLog, Static

from heagent.cli_display import format_tokens_k
from heagent.config import get_settings
from heagent.gui.bridge import MSG_AGENT_ERROR, MSG_AGENT_INTERRUPTED, MSG_STREAM_EVENT, BridgeMessage
from heagent.providers.router import active_model, annotate_route
from heagent.tools.call_summary import activity_label

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from heagent.gui.bridge import AgentBridge
    from heagent.gui.state import GuiState
    from heagent.types import StreamEvent

logger = logging.getLogger(__name__)

WELCOME = "[bold green]HeAgent[/]\n输入消息开始对话。[dim]/help 查看命令[/]"


def _render_tool_result(event: StreamEvent) -> str:
    """把 ``tool_result`` 事件渲染成 RichLog markup 行（失败归因红叉 / 成功绿勾）。

    内容与工具名经 ``markup.escape``——工具输出**不可信**，其中形如 ``[red]`` 的片段
    在 ``markup=True`` 的 RichLog（本 widget 即开启）里会被当标记解释。
    失败必须显式归因且**不得**沿用绿勾（与 CLI 的 ``[failed <tool>]`` 同一语义，
    2026-09-14 复核发现 GUI 侧原先无论成败一律画绿勾）。
    """
    result = escape(event.tool_result_content[:300])
    if event.tool_error:
        return f"  [red]✗ {escape(event.tool_name)}[/] {result}"
    return f"  [green]✓[/] {result}"


class ChatScreen(Screen[None]):
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

    def compose(self) -> ComposeResult:
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
        cumul_str = f"累计: {format_tokens_k(cumul)} tok" if cumul > 0 else ""
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
            evt_typed: StreamEvent = evt
            if evt_typed.type == "text":
                log.write(evt_typed.text)
            elif evt_typed.type == "tool_call":
                # 标签拼接走 activity_label（与 CLI 提示行 / 状态栏 / 活动台账同一口径）；
                # escape 防工具参数里的 `[...]` 被 RichLog 当 markup 解释（本 widget markup=True）。
                label = escape(activity_label(evt_typed.tool_name, evt_typed.tool_target))
                log.write(f"[dim]🔧 {label}...[/]")
            elif evt_typed.type == "tool_result":
                log.write(_render_tool_result(evt_typed))
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
        if cmd == "/goal":
            self._goal_cmd(args)
            return True
        return False

    def _goal_cmd(self, args: str) -> None:
        """Run goal commands through the shared CLI goal implementation."""
        log = self.query_one("#chat-log", RichLog)

        async def _run() -> None:
            from heagent.cli_goal import _goal_runner
            from heagent.gui.app import HeAgentApp

            app = HeAgentApp.get_current_app()
            if not isinstance(app, HeAgentApp) or app.agent_loop is None:
                log.write("[red]Goal runner unavailable[/]")
                return
            self._state.is_running = True
            try:
                await _goal_runner(app.agent_loop.provider, app.agent_loop.engine, args, cron_store=app.job_store)
                log.write("[dim]Goal command completed; use /goal status to inspect progress.[/]")
            except Exception as exc:
                log.write(f"[red]Goal command failed: {exc}[/]")
            finally:
                self._state.is_running = False

        self._pending_submit = asyncio.create_task(_run())

    def _model_cmd(self, args: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        from heagent.gui.app import HeAgentApp

        app = HeAgentApp.get_current_app()
        if not isinstance(app, HeAgentApp) or not app.agent_loop:
            return
        provider = app.agent_loop.provider
        from heagent.providers.switchable import SwitchableProvider

        if not isinstance(provider, SwitchableProvider):
            current = annotate_route(provider, active_model(provider) or provider.get_metadata().model)
            log.write(f"[dim]当前: {current}[/]")
            return
        if not args:
            info = provider.info()
            lines = ["[bold]可用模型:[/]"]
            for name, meta in info.items():
                marker = "[green]←[/]" if meta.active else ""
                # 智能路由条目（RoutingProvider）：只显示默认模型，而非池内全部模型列表。
                display_model = active_model(provider.providers[name]) or meta.model
                lines.append(f"  {name} ({display_model}) {marker}")
            log.write("\n".join(lines))
            return
        target = args.strip()

        async def _switch() -> None:
            try:
                await provider.switch(target)
                s = get_settings()
                self._state.model_name = annotate_route(
                    provider, active_model(provider) or provider.get_metadata().model
                )
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
