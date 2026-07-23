"""GUI 引擎事件观察者 — EventBus → GuiState + 事件环形缓冲。

Epic 28：增强为同时维护一个事件环形缓冲，供 EventLogScreen 消费。

.. note::
    ``EventBus.emit()`` 会传入 ``EngineEvent`` **对象**（见 ``engine/observability.py``
    ``EventObserver`` 协议），不是字符串。本观察者从 ``EngineEvent.event_type`` 提取
    事件类型字段。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import TYPE_CHECKING

from heagent.engine.observability import EngineEvent

if TYPE_CHECKING:
    from heagent.gui.state import GuiState

logger = logging.getLogger(__name__)

# 环形缓冲最大容量
_MAX_EVENTS = 500


class GuiEventObserver:
    """EventBus 订阅者 → GuiState + 事件环形缓冲。

    ``handle(event: EngineEvent)`` 由 ``EventBus.emit()`` 同步回调；
    不得在此方法中做阻塞 I/O 或耗时 CPU 计算（Protocol 约束）。
    """

    def __init__(self, state: GuiState) -> None:
        self._state = state
        # 环形缓冲：deque[(timestamp, event_type_str, details_dict)]
        self._buffer: deque[tuple[float, str, dict]] = deque(maxlen=_MAX_EVENTS)

    def handle(self, event: EngineEvent) -> None:
        """EventBus 回调入口。

        参数 ``event`` 是 ``EngineEvent`` Pydantic 模型（不是字符串）。
        事件类型通过 ``event.event_type`` 访问。
        """
        details = event.details or {}
        now = time.monotonic()

        # 更新 state
        etype = event.event_type
        if etype == "tool_call_started":
            self._state.active_tool = event.tool_name or "unknown"
        elif etype in ("tool_call_completed", "tool_call_failed", "tool_call_blocked"):
            self._state.active_tool = ""

        # 追加到缓冲
        entry_details = dict(details)
        if event.run_id:
            entry_details["run_id"] = event.run_id
        if event.iteration:
            entry_details["iteration"] = event.iteration
        self._buffer.append((now, etype, entry_details))

    def get_recent(self, limit: int = 100) -> list[tuple[float, str, dict]]:
        """返回最近 N 条事件（最新在前）。"""
        items = list(self._buffer)
        items.reverse()
        return items[:limit]

    def clear(self) -> None:
        """清空事件缓冲。"""
        self._buffer.clear()
