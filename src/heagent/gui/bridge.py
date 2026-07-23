"""AgentBridge — AgentLoop ↔ Textual App 异步数据桥。

职责：
1. submit(prompt) — 提交用户输入，在后台 Worker 中消费 ``AgentLoop.run_stream()``
2. 把 ``StreamEvent`` 转为 Textual Message 投递给 ChatScreen
3. cancel() — 取消当前 Agent 运行
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from heagent.types import StreamEvent

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.gui.state import GuiState

logger = logging.getLogger(__name__)

MSG_STREAM_EVENT = "gui.stream_event"
MSG_AGENT_INTERRUPTED = "gui.agent_interrupted"
MSG_AGENT_ERROR = "gui.agent_error"


class AgentBridge:
    """桥接 AgentLoop 和 Textual App。"""

    def __init__(self, loop: AgentLoop, state: GuiState) -> None:
        self._loop = loop
        self._state = state
        self._current_task: asyncio.Task[None] | None = None

    def post(self, message_type: str, **payload: object) -> None:
        """向 Textual App 投递消息（协程安全）。"""
        from textual.app import App as _App

        app = _App.get_current_app()
        if app is not None:
            app.post_message(self._make_message(message_type, payload))

    async def submit(self, prompt: str) -> None:
        """提交用户提示词，在后台消费 ``AgentLoop.run_stream()``。"""
        self._state.is_running = True
        self._state.last_error = None
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

    @staticmethod
    def _make_message(message_type: str, payload: dict[str, object]) -> object:
        from textual.message import Message as TextualMessage

        class _BridgeMsg(TextualMessage):
            def __init__(self) -> None:
                super().__init__()
                self.type = message_type
                self.payload = payload

        return _BridgeMsg()

    def _update_state(self, event: StreamEvent) -> None:
        if event.type == "tool_call":
            self._state.active_tool = event.tool_name
        elif event.type == "tool_result":
            self._state.active_tool = ""
