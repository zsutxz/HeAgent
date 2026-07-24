"""AgentBridge — AgentLoop ↔ Textual App 异步数据桥。

职责：
1. submit(prompt) — 提交用户输入，在后台 Worker 中消费 ``AgentLoop.run_stream()``
2. 把 ``StreamEvent`` 转为 Textual Message 投递给 ChatScreen
3. cancel() — 取消当前 Agent 运行
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from textual.message import Message as TextualMessage

if TYPE_CHECKING:
    from textual.app import App as TextualApp

    from heagent.agent.loop import AgentLoop
    from heagent.gui.state import GuiState
    from heagent.types import StreamEvent

from heagent.config import get_settings

logger = logging.getLogger(__name__)

# ── Bridge 消息类型常量 ──────────────────────────────────
MSG_STREAM_EVENT = "gui.stream_event"
MSG_AGENT_INTERRUPTED = "gui.agent_interrupted"
MSG_AGENT_ERROR = "gui.agent_error"


class BridgeMessage(TextualMessage):
    """AgentBridge → Textual UI 的消息（显式类，可被路由）。

    消息类型 (msg_type):
        gui.stream_event      — StreamEvent 子事件
        gui.agent_interrupted — Agent 被用户中断
        gui.agent_error       — Agent 运行异常

    Textual 会按类名自动查找 ``on_bridge_message(self, message: BridgeMessage)`` 处理器。
    """

    def __init__(self, msg_type: str, payload: dict[str, Any]) -> None:
        super().__init__()
        self.msg_type = msg_type
        self.payload = payload


class AgentBridge:
    """桥接 AgentLoop 和 Textual App。

    post() 向 Textual App 投递 BridgeMessage；App 在 on_bridge_message 中
    转发给当前活动 Screen（Screen 再在自己的 on_bridge_message 中处理）。

    .. note::
        Textual 1.0 没有 ``App.get_current_app()``（2.x API），因此通过
        ``set_app()`` 注入实例引用——由 ``HeAgentApp.__init__`` 在构造时调用。
    """

    def __init__(self, loop: AgentLoop, state: GuiState) -> None:
        self._loop = loop
        self._state = state
        self._current_task: asyncio.Task[None] | None = None
        self._app: TextualApp | None = None  # 由 HeAgentApp.__init__ 注入

    def set_app(self, app: TextualApp) -> None:
        """注入 Textual App 实例引用（供 post 投递消息）。"""
        self._app = app

    def post(self, message_type: str, **payload: Any) -> None:
        """向 Textual App 投递消息（协程安全）。"""
        if self._app is not None:
            self._app.post_message(BridgeMessage(message_type, dict(payload)))

    async def submit(self, prompt: str) -> None:
        """提交用户提示词，在后台消费 ``AgentLoop.run_stream()``。"""
        self._state.is_running = True
        self._state.last_error = None
        self._state.active_tool = ""
        s = get_settings()
        self._state.max_context_tokens = s.max_context_tokens
        self._state.compression_threshold = s.compression_threshold
        self._current_task = asyncio.current_task()

        try:
            async for event in self._loop.run_stream(prompt):
                self.post(MSG_STREAM_EVENT, event=event)
                self._update_state(event)
        except asyncio.CancelledError:
            self.post(MSG_AGENT_INTERRUPTED)
        except Exception as exc:
            logger.exception("AgentBridge: Agent execution failed")
            self._state.last_error = str(exc)
            self.post(MSG_AGENT_ERROR, error=str(exc))
        finally:
            self._state.is_running = False
            self._current_task = None

    def cancel(self) -> None:
        """中断当前 Agent 运行。"""
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

    def _update_state(self, event: StreamEvent) -> None:
        if event.type == "tool_call":
            self._state.active_tool = event.tool_name
        elif event.type == "tool_result":
            self._state.active_tool = ""
