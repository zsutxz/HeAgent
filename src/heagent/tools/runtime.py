"""Context-local runtime bindings for builtin tools."""

from __future__ import annotations

from contextlib import contextmanager, suppress
from contextvars import ContextVar
from typing import TYPE_CHECKING, Generic, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

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
        return cast("T | None", current)

    @contextmanager
    def bind(self, value: T | None) -> Iterator[None]:
        """Temporarily override the binding for the current context."""
        token = self._current.set(value)
        try:
            yield
        finally:
            # 中断时 token 可能在不同的 asyncio Context 中创建，此时 reset 会抛 ValueError
            # （进程即将退出）——静默忽略，但只忽略这一种。
            with suppress(ValueError):
                self._current.reset(token)
