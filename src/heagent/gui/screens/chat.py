"""ChatScreen — 主聊天界面：消息列表 + 输入区 + 状态栏。"""

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
      │         MessageList         │  (chat-log, 可滚动)
      │─────────────────────────────│
      │  StatusBar (模型|Token|轮)   │
      │─────────────────────────────│
      │  InputArea (输入框+发送)     │
      └─────────────────────────────┘
    """

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

    def compose(self):
        with Vertical(id="chat-container"):
            yield MessageList(id="message-list")
        with Container(id="status-container"):
            yield StatusBar(id="status-bar")
        with Container(id="input-container"):
            yield InputArea(on_submit=self._on_user_submit, id="input-area")

    def on_mount(self) -> None:
        """绑定 state → widget 的数据流 + 定时刷新。"""
        # 绑定 GuiState 字段到 widgets
        self.watch(self._state, "model_name", self._on_state_change)
        self.watch(self._state, "iteration", self._on_state_change)
        self.watch(self._state, "max_iterations", self._on_state_change)
        self.watch(self._state, "token_usage", self._on_state_change)
        self.watch(self._state, "is_running", self._on_running_change)
        self.watch(self._state, "active_tool", self._on_state_change)

        # 初始同步
        self._sync_state_to_ui()

        # 输入框聚焦
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
            ml.append_tool_card(event.tool_name, "")
        elif event.type == "tool_result":
            ml.update_tool_result(
                "",  # tool_call_id 暂不追踪（MVP 简化：更新最近卡片）
                event.tool_result_content,
                is_error=False,
            )
        elif event.type == "done":
            ml.end_agent_message()
            # 刷新最终 token / 迭代状态
            self._finalize_state()

    def _handle_interrupted(self) -> None:
        ml = self.query_one("#message-list", MessageList)
        ml.append_system_message("[已中断]")

    def _handle_error(self, error: str) -> None:
        ml = self.query_one("#message-list", MessageList)
        ml.append_system_message(f"[错误] {error}")

    # ── 用户输入 ────────────────────────────────────────────

    async def _on_user_submit(self, text: str) -> None:
        """用户提交一条消息。"""
        ml = self.query_one("#message-list", MessageList)

        # 显示用户消息
        ml.append_user_message(text)

        # 开始 agent 消息
        ml.begin_agent_message()

        # 后台启动 Agent
        asyncio.create_task(self._bridge.submit(text))

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
        self._sync_state_to_ui()

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
