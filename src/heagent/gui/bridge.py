"""AgentBridge — AgentLoop ↔ Textual App 异步数据桥。

职责：
1. submit(prompt) — 提交用户输入，在后台 Worker 中消费 ``AgentLoop.run_stream()``
2. 把 ``StreamEvent`` 转为 Textual Message 投递给 ChatScreen
3. cancel() — 取消当前 Agent 运行
4. 通过 ``GuiEventObserver`` 订阅引擎事件播发到 UI

设计要点：
- submit() 在 ``asyncio.create_task()`` 中运行（Textual Worker），不阻塞 UI 主循环
- post_message() 是 Textual 的协程安全投递接口——Worker → 主循环 → Widget
- CancelledError 经 AgentLoop.run_stream() 的 finally 块做 session 保存后传播，bridge 捕获并通知 UI
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from heagent.types import StreamEvent

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.engine.observability import EventBus
    from heagent.gui.state import GuiState

logger = logging.getLogger(__name__)

# Textual message 命名空间常量——避免字符串拼写错误
MSG_STREAM_EVENT = "gui.stream_event"
MSG_AGENT_INTERRUPTED = "gui.agent_interrupted"
MSG_AGENT_ERROR = "gui.agent_error"


class AgentBridge:
    """桥接 AgentLoop 和 Textual App。"""

    def __init__(
        self,
        loop: AgentLoop,
        state: GuiState,
        event_bus: EventBus | None = None,
    ) -> None:
        self._loop = loop
        self._state = state
        self._current_task: asyncio.Task[None] | None = None

        # 订阅引擎事件 → UI
        if event_bus is not None:
            from heagent.gui.observers import GuiEventObserver

            event_bus.subscribe(GuiEventObserver(state))

    def post(self, message_type: str, **payload: object) -> None:
        """向 Textual App 投递消息（协程安全）。"""
        # deferred import —— 避免在未进 Textual 上下文时导入 App
        from textual.app import App as _App

        app = _App.get_current_app()
        if app is not None:
            app.post_message(self._make_message(message_type, payload))

    async def submit(self, prompt: str) -> None:
        """提交用户提示词，在后台消费 ``AgentLoop.run_stream()``。

        在 ``asyncio.create_task()`` 中调用本方法，不阻塞 Textual 主循环。
        """
        self._state.is_running = True
        self._state.last_error = None
        self._current_task = asyncio.current_task()

        try:
            async for event in self._loop.run_stream(prompt):
                self.post(MSG_STREAM_EVENT, event=event)
                self._update_state(event)
        except asyncio.CancelledError:
            self.post(MSG_AGENT_INTERRUPTED)
        except Exception as exc:  # noqa: BLE001 — 所有异常都转为 UI 消息，不崩溃 TUI
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
        """构造一条 Textual Message（轻量、仅携带类型+数据）。"""
        from textual.message import Message as TextualMessage

        class _BridgeMsg(TextualMessage):
            def __init__(self) -> None:
                super().__init__()
                self.type = message_type
                self.payload = payload

        return _BridgeMsg()

    def _update_state(self, event: StreamEvent) -> None:
        """从 StreamEvent 同步更新 GuiState 字段。"""
        if event.type == "tool_call":
            self._state.active_tool = event.tool_name
        elif event.type == "tool_result":
            self._state.active_tool = ""
        # iteration / token 由 AgentLoop.last_* 在 submit() 结束后统一刷新；
        # 此处仅更新「正在执行中」的工具名。
