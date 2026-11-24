"""内置工具的上下文局部运行时绑定。"""

from __future__ import annotations

from contextlib import contextmanager, suppress
from contextvars import ContextVar
from typing import TYPE_CHECKING, Generic, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

T = TypeVar("T")
_UNSET = object()


class RuntimeSlot(Generic[T]):
    """保存一个默认绑定与一个上下文局部覆盖。"""

    def __init__(self, name: str) -> None:
        self._default: T | None = None
        self._current: ContextVar[object | T | None] = ContextVar(name, default=_UNSET)

    def configure(self, value: T | None) -> None:
        """设置进程级兜底绑定。"""
        self._default = value

    def reset(self) -> None:
        """清空进程级兜底绑定。"""
        self._default = None

    def get(self) -> T | None:
        """返回当前覆盖（若已设置），否则返回兜底绑定。"""
        current = self._current.get()
        if current is _UNSET:
            return self._default
        return cast("T | None", current)

    @contextmanager
    def bind(self, value: T | None) -> Iterator[None]:
        """在当前上下文内临时覆盖绑定。"""
        token = self._current.set(value)
        try:
            yield
        finally:
            # 中断时 token 可能在不同的 asyncio Context 中创建，此时 reset 会抛 ValueError
            # （进程即将退出）——静默忽略，但只忽略这一种。
            with suppress(ValueError):
                self._current.reset(token)
