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
from typing import TYPE_CHECKING, Any

from heagent.tools.call_summary import activity_label

if TYPE_CHECKING:
    from heagent.engine.observability import EngineEvent
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
        self._buffer: deque[tuple[float, str, dict[str, Any]]] = deque(maxlen=_MAX_EVENTS)
        #: 单调递增的事件总数（**不随缓冲淘汰回退**）——展示层的差分必须用它，
        #: 用「缓冲窗口长度」做差会在窗口满时恒为 0，让事件日志永久冻结（台账 A24）。
        self._total = 0

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
            # 带上作用对象：状态栏显示 `file_read → src/a.py`，与 CLI 提示 / 聊天日志同一口径。
            # 拼接走 activity_label——本文件与 bridge.py 曾各写一套（一处带 target、一处不带），
            # 同一次 run 中两条路径互相覆盖，状态栏会在两种格式间抖动。
            self._state.active_tool = activity_label(event.tool_name or "unknown", event.target)
        elif etype in ("tool_call_completed", "tool_call_failed", "tool_call_blocked"):
            self._state.active_tool = ""

        # 追加到缓冲
        entry_details = dict(details)
        # ``tool_name`` 此前**没有**进展示字典（旧事件日志读 ``details["tool_name"]`` 恒为空 ⇒
        # 工具名从未显示过）；这里与 target / run_id / iteration 一起补齐为展示字段。
        if event.tool_name:
            entry_details["tool_name"] = event.tool_name
        if event.target:
            entry_details["target"] = event.target
        if event.run_id:
            entry_details["run_id"] = event.run_id
        if event.iteration:
            entry_details["iteration"] = event.iteration
        self._buffer.append((now, etype, entry_details))
        self._total += 1

    @property
    def total(self) -> int:
        """自创建（或上次 :meth:`clear`）以来追加过的事件总数——单调递增，不随淘汰回退。"""
        return self._total

    def snapshot(self) -> tuple[list[tuple[float, str, dict[str, Any]]], int]:
        """返回 ``(缓冲内事件（时间正序）, 单调总数)``——供 :class:`~heagent.pub.event_lines.EventCursor` 差分。"""
        return list(self._buffer), self._total

    def get_recent(self, limit: int = 100) -> list[tuple[float, str, dict[str, Any]]]:
        """返回最近 N 条事件（最新在前）。"""
        items = list(self._buffer)
        items.reverse()
        return items[:limit]

    def clear(self) -> None:
        """清空事件缓冲与总数（游标据此判「从头重来」，见 EventCursor.take）。"""
        self._buffer.clear()
        self._total = 0
