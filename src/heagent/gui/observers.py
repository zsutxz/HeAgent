"""GUI 引擎事件观察者 — EventBus → GuiState + 事件环形缓冲。

Epic 28：增强为同时维护一个事件环形缓冲，供 EventLogScreen 消费。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heagent.gui.state import GuiState

logger = logging.getLogger(__name__)

# 环形缓冲最大容量
_MAX_EVENTS = 500


class GuiEventObserver:
    """EventBus 订阅者 → GuiState + 事件环形缓冲。

    handle() 由 EventBus 回调；get_recent() 供 EventLogScreen 拉取。
    """

    def __init__(self, state: GuiState) -> None:
        self._state = state
        # 环形缓冲：deque[(timestamp, event_type, details_dict)]
        self._buffer: deque[tuple[float, str, dict]] = deque(maxlen=_MAX_EVENTS)

    def handle(self, event_type: str, *, details: dict | None = None, **kwargs: object) -> None:
        """EventBus 回调入口。"""
        details = details or {}
        now = time.monotonic()

        # 更新 state
        if event_type == "tool_call_started":
            self._state.active_tool = str(kwargs.get("tool_name", ""))
        elif event_type in ("tool_call_completed", "tool_call_failed", "tool_call_blocked"):
            self._state.active_tool = ""

        # 追加到缓冲
        run_id = str(kwargs.get("run_id", ""))
        entry_details = dict(details)
        if run_id:
            entry_details["run_id"] = run_id
        self._buffer.append((now, event_type, entry_details))

    def get_recent(self, limit: int = 100) -> list[tuple[float, str, dict]]:
        """返回最近 N 条事件（最新在前）。"""
        items = list(self._buffer)
        items.reverse()
        return items[:limit]

    def clear(self) -> None:
        """清空事件缓冲。"""
        self._buffer.clear()
