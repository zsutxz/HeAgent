"""ChatScreen — 主聊天界面：消息列表 + ToolCard + 输入区 + 状态栏。

Story 26-1：ToolCard 流式插入与更新。
Story 26-2：斜杠命令路由 (/model /mcp-prompt /clear /help)。
Story 26-3：中断 (Ctrl+C)、清屏 (Ctrl+L)。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from textual.containers import Container, Vertical
from textual.message import Message
from textual.screen import Screen

from heagent.gui.widgets.input_area import InputArea
from heagent.gui.widgets.message_list import MessageList
from heagent.gui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from heagent.gui.bridge import AgentBridge
    from heagent.gui.state import GuiState
    from heagent.types import StreamEvent

logger = logging.getLogger(__name__)


class ChatScreen(Screen):
    """主聊天界面。

    布局：
      ┌─────────────────────────────┐
      │         MessageList         │  (RichLog + ToolCard)
      │─────────────────────────────│
      │  StatusBar (模型|Token|轮)   │
      │─────────────────────────────│
      │  InputArea (输入+发送+斜杠)  │
      └─────────────────────────────┘
    """

    BINDINGS = [
        ("ctrl+l", "clear_screen", "清屏"),
    ]

    CSS = """
    ChatScreen {
        layout: vertical;
    }
    #chat-container {
        height: 1fr;
        border-bottom: solid $primary;
    }
    #status-container {
        height: auto;
        background: $panel;
        padding: 0 1;
    }
    #input-container {
        height: auto;
        padding: 1;
    }
    """

    def __init__(
        self,
        bridge: AgentBridge,
        state: GuiState,
        *,
        name: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id)
        self._bridge = bridge
        self._state = state
        # 最近一张 ToolCard 引用（用于 stream_event 即时更新）
        self._current_tool_card = None

    def compose(self):
        with Vertical(id="chat-container"):
            yield MessageList(id="message-list")
        with Container(id="status-container"):
            yield StatusBar(id="status-bar")
        with Container(id="input-container"):
            yield InputArea(
                on_submit=self._on_user_submit,
                on_slash_command=self._on_slash_command,
                id="input-area",
            )

    def on_mount(self) -> None:
        """绑定 state → widget 的数据流。"""
        self.watch(self._state, "model_name", self._on_state_change)
        self.watch(self._state, "iteration", self._on_state_change)
        self.watch(self._state, "max_iterations", self._on_state_change)
        self.watch(self._state, "token_usage", self._on_state_change)
        self.watch(self._state, "is_running", self._on_running_change)
        self.watch(self._state, "active_tool", self._on_state_change)
        self._sync_state_to_ui()
        self.query_one(InputArea).focus_input()

    # ── Message 处理 ────────────────────────────────────────

    def on_unexpected_message(self, message: Message) -> None:
        """接收 AgentBridge 投递的流式事件 / 中断 / 错误消息。"""
        msg_type = getattr(message, "type", "")
        payload = getattr(message, "payload", {})

        if msg_type == "gui.stream_event":
            self._handle_stream_event(payload.get("event"))
        elif msg_type == "gui.agent_interrupted":
            self._handle_interrupted()
        elif msg_type == "gui.agent_error":
            self._handle_error(payload.get("error", ""))
        else:
            super().on_unexpected_message(message)

    def _handle_stream_event(self, event: StreamEvent | None) -> None:
        if event is None:
            return
        ml = self.query_one("#message-list", MessageList)

        if event.type == "text":
            ml.append_text(event.text)
        elif event.type == "tool_call":
            # 插入 ToolCard（RichLog.mount 直接挂载 widget）
            self._current_tool_card = ml.insert_tool_card(event.tool_name)
        elif event.type == "tool_result":
            if self._current_tool_card is not None:
                self._current_tool_card.set_result(
                    event.tool_result_content,
                    is_error=False,
                    duration="",
                )
            ml.update_tool_result(event.tool_result_content, is_error=False)
        elif event.type == "done":
            ml.end_agent_message()
            self._finalize_state()

    def _handle_interrupted(self) -> None:
        ml = self.query_one("#message-list", MessageList)
        ml.append_system_message("[已中断]")

    def _handle_error(self, error: str) -> None:
        ml = self.query_one("#message-list", MessageList)
        ml.append_system_message(f"[错误] {error}")

    # ── 斜杠命令 ────────────────────────────────────────────

    def _on_slash_command(self, command: str, args: str) -> bool:
        """路由斜杠命令。返回 True 表示已处理（不发送给 Agent）。"""
        ml = self.query_one("#message-list", MessageList)

        if command == "/clear":
            ml.clear()
            return True

        if command == "/help":
            ml.append_system_message(
                "可用命令：\n"
                "  /model [name]  — 查看或切换 LLM 模型\n"
                "  /mcp-prompt [server] [name]  — MCP Prompt 交互\n"
                "  /clear  — 清空消息列表 (Ctrl+L)\n"
                "  /help  — 显示此帮助\n"
                "  Ctrl+C  — 中断 Agent 执行\n"
                "  Ctrl+Q  — 退出"
            )
            return True

        if command == "/model":
            self._handle_model_cmd(args)
            return True

        if command == "/mcp-prompt":
            ml.append_system_message("[dim]/mcp-prompt 功能将在后续版本中完整支持[/]")
            return True

        return False

    def _handle_model_cmd(self, args: str) -> None:
        """处理 /model 命令：无参数列出，带参数切换。"""
        ml = self.query_one("#message-list", MessageList)
        from heagent.gui.app import HeAgentApp

        app = HeAgentApp.get_current_app()
        if not isinstance(app, HeAgentApp) or not app._loop:
            ml.append_system_message("[dim]/model: 无法获取 AgentLoop 引用[/]")
            return

        provider = app._loop.provider
        from heagent.providers.switchable import SwitchableProvider

        if not isinstance(provider, SwitchableProvider):
            ml.append_system_message(f"[dim]当前模型: {provider.get_metadata().model} (无可切换的 Provider)[/]")
            return

        if not args:
            # 列出所有 Provider
            info = provider.info()
            lines = ["可用模型:"]
            for name, meta in info.items():
                marker = "[green]← 当前[/]" if meta["active"] else ""
                lines.append(f"  {name}  ({meta['model']})  {marker}")
            ml.append_system_message("\n".join(lines))
            return

        # 切换 Provider
        target = args.strip()
        try:

            async def _switch():
                await provider.switch(target)
                meta = provider.get_metadata()
                self._state.model_name = meta.model

            asyncio.create_task(_switch())
            ml.append_system_message(f"[dim]已切换到 [bold]{target}[/][/]")
        except Exception as exc:
            ml.append_system_message(f"[red]切换失败: {exc}[/]")

    # ── 用户输入 ────────────────────────────────────────────

    async def _on_user_submit(self, text: str) -> None:
        """用户提交一条消息（非斜杠命令路由后到达）。"""
        ml = self.query_one("#message-list", MessageList)
        ml.append_user_message(text)
        ml.begin_agent_message()
        self._current_tool_card = None
        asyncio.create_task(self._bridge.submit(text))

    # ── 快捷键 ──────────────────────────────────────────────

    def action_clear_screen(self) -> None:
        """Ctrl+L 清空消息列表。"""
        self.query_one("#message-list", MessageList).clear()

    # ── 状态同步 ────────────────────────────────────────────

    def _finalize_state(self) -> None:
        """Agent 完成后从 AgentLoop.last_* 刷新状态。"""
        from heagent.gui.app import HeAgentApp

        app = HeAgentApp.get_current_app()
        if isinstance(app, HeAgentApp) and app._loop:
            loop = app._loop
            if loop.last_usage:
                self._state.token_usage = loop.last_usage
            if loop.last_iteration is not None:
                self._state.iteration = loop.last_iteration
            if loop.provider:
                meta = loop.provider.get_metadata()
                self._state.model_name = meta.model

    def _sync_state_to_ui(self) -> None:
        """把 GuiState 字段刷新到 widgets。"""
        sb = self.query_one("#status-bar", StatusBar)
        sb.model_name = self._state.model_name
        sb.iteration = self._state.iteration
        sb.max_iterations = self._state.max_iterations
        sb.total_tokens = self._state.token_usage.total_tokens
        sb.is_running = self._state.is_running
        sb.active_tool = self._state.active_tool

    async def _on_running_change(self, value: bool) -> None:
        """Agent 执行状态变更 → 禁用/启用输入。"""
        inp = self.query_one(InputArea)
        inp.disabled = value
        self._on_state_change(None)

    def _on_state_change(self, _value: object) -> None:
        """任意状态字段变更 → 刷新状态栏。"""
        self._sync_state_to_ui()
