"""Runtime event bus and lightweight observers."""

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
    """Structured runtime event emitted by the loop engine."""

    event_type: str
    timestamp: str = Field(default_factory=iso_now)
    run_id: str = ""
    iteration: int = 0
    tool_name: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class EventObserver(Protocol):
    """Observer interface for engine events."""

    def handle(self, event: EngineEvent) -> None:
        """Consume one event."""


class LoggingObserver:
    """Default observer that mirrors events into the logger."""

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
    """In-process event bus with bounded event retention."""

    def __init__(
        self,
        observers: Iterable[EventObserver] | None = None,
        *,
        retain: int = 200,
    ) -> None:
        self._observers = list(observers or [])
        self._events: deque[EngineEvent] = deque(maxlen=retain)

    def subscribe(self, observer: EventObserver) -> None:
        """Register an observer for future events."""
        self._observers.append(observer)

    def emit(self, event: EngineEvent) -> None:
        """Publish a pre-built event to all observers."""
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
        """Build and emit one event in a single call."""
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
        """Return the retained in-memory event buffer."""
        return list(self._events)
