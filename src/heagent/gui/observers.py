"""GUI 引擎事件观察者 — 把 EventBus 事件转为 GuiState 更新。

订阅 EventBus 后，引擎工具调用 / 迭代 / 运行状态变更等事件自动
刷新 GuiState，widgets 通过 reactive 机制自动响应。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heagent.gui.state import GuiState

logger = logging.getLogger(__name__)


class GuiEventObserver:
    """EventBus 订阅者——把引擎事件同步到 GuiState。

    当前实现极简：仅在 tool_call_started/completed 时更新 active_tool；
    后续可扩展迭代/Token 等的实时更新。
    """

    def __init__(self, state: GuiState) -> None:
        self._state = state

    def handle(self, event_type: str, *, details: dict | None = None, **kwargs: object) -> None:
        """EventBus 回调入口。"""
        _ = kwargs  # run_id / tool_name / iteration 暂未使用
        details = details or {}

        if event_type == "tool_call_started":
            self._state.active_tool = details.get("tool_name", "")
        elif event_type in ("tool_call_completed", "tool_call_failed", "tool_call_blocked"):
            self._state.active_tool = ""
