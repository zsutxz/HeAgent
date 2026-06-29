"""运行时事件总线与轻量观察者（observability）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``EventBus`` 在进程内
发布结构化的 :class:`EngineEvent`（工具执行 started / completed / failed / blocked、迭代
事件等），并以有界 ``deque`` 保留近期事件供查询。``LoggingObserver`` 是默认观察者，把事件
镜像到标准日志。

设计：观察者异常被捕获并记录（``logger.exception``），**不影响**总线对其他观察者的派发，
也不打断主循环——可观测性故障不得中断 agent 运行。
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from heagent.engine.context import iso_now

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


class EngineEvent(BaseModel):
    """loop engine 发出的结构化运行时事件。"""

    event_type: str
    timestamp: str = Field(default_factory=iso_now)
    # 关联 run_id（顶层无则留空）。
    run_id: str = ""
    # 关联迭代轮次。
    iteration: int = 0
    # 关联工具名（非工具事件留空）。
    tool_name: str = ""
    # 自由扩展字段（如 mode / sandbox_profile / content_length / error）。
    details: dict[str, Any] = Field(default_factory=dict)


class EventObserver(Protocol):
    """引擎事件的观察者接口（结构化鸭子类型）。"""

    def handle(self, event: EngineEvent) -> None:
        """消费一个事件。"""


class LoggingObserver:
    """默认观察者：把事件镜像到 logger（默认 INFO 级）。"""

    def __init__(self, *, level: int = logging.INFO) -> None:
        self._level = level

    def handle(self, event: EngineEvent) -> None:
        logger.log(
            self._level,
            "engine event=%s run=%s iteration=%s tool=%s details=%s",
            event.event_type,
            event.run_id or "-",
            event.iteration,
            event.tool_name or "-",
            event.details,
        )


class EventBus:
    """进程内事件总线，带界保留近期事件。"""

    def __init__(
        self,
        observers: Iterable[EventObserver] | None = None,
        *,
        retain: int = 200,
    ) -> None:
        # 观察者列表；emit 时按序同步派发。
        self._observers = list(observers or [])
        # 有界缓冲：仅保留最近 retain 条事件，避免内存无限增长。
        self._events: deque[EngineEvent] = deque(maxlen=retain)

    def subscribe(self, observer: EventObserver) -> None:
        """为后续事件注册一个观察者。"""
        self._observers.append(observer)

    def emit(self, event: EngineEvent) -> None:
        """把一个已构建的事件发布给全部观察者。

        观察者抛出的异常被捕获并记录，不影响其他观察者，也不向调用方传播。
        """
        self._events.append(event)
        for observer in self._observers:
            try:
                observer.handle(event)
            except Exception:
                logger.exception("Event observer failed for event '%s'", event.event_type)

    def publish(
        self,
        event_type: str,
        *,
        run_id: str = "",
        iteration: int = 0,
        tool_name: str = "",
        details: dict[str, Any] | None = None,
    ) -> EngineEvent:
        """一步构建并发送一个事件（EngineContainer.events.publish 的常用入口）。"""
        event = EngineEvent(
            event_type=event_type,
            run_id=run_id,
            iteration=iteration,
            tool_name=tool_name,
            details=details or {},
        )
        self.emit(event)
        return event

    @property
    def recent_events(self) -> list[EngineEvent]:
        """返回内存中保留的近期事件列表（拷贝）。"""
        return list(self._events)
