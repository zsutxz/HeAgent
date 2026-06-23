"""Context-local runtime bindings for builtin tools."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Generic, TypeVar

T = TypeVar("T")
_UNSET = object()


class RuntimeSlot(Generic[T]):
    """Store one default binding plus one context-local override."""

    def __init__(self, name: str) -> None:
        self._default: T | None = None
        self._current: ContextVar[object | T | None] = ContextVar(name, default=_UNSET)

    def configure(self, value: T | None) -> None:
        """Set the process-wide fallback binding."""
        self._default = value

    def reset(self) -> None:
        """Clear the process-wide fallback binding."""
        self._default = None

    def get(self) -> T | None:
        """Return the current override if set, otherwise the fallback binding."""
        current = self._current.get()
        if current is _UNSET:
            return self._default
        return current

    @contextmanager
    def bind(self, value: T | None):
        """Temporarily override the binding for the current context."""
        token = self._current.set(value)
        try:
            yield
        finally:
            self._current.reset(token)
