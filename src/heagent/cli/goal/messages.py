"""/goal 用户可见输出漏斗：sink ContextVar 与 _echo 单点出口。"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from collections.abc import Callable

#: ``/goal`` 用户可见输出的**消息 sink**（GUI 用）。
#: 默认 ``None`` ⇒ 仍走 ``click.echo(..., err=True)``，CLI 行为逐字不变。
#: 为什么需要它：GUI 原先靠 ``contextlib.redirect_stderr`` 截获这些文案，但那会把**整个 stderr**
#: 一起吞掉——包括 ``logging`` 记录与第三方库输出，全部倒进对话区。
_MESSAGE_SINK: ContextVar[Callable[[str], None] | None] = ContextVar("goal_message_sink", default=None)


def _echo(message: str, *, err: bool = True) -> None:
    """``/goal`` 全部用户可见输出的**唯一出口**（历史 40+ 处 ``click.echo`` 收敛于此）。

    有 sink（GUI）时逐条投递；否则与历史行为逐字一致地写 stderr。``err`` 只为保持调用点原样
    （``click.echo(..., err=True)``）而保留，sink 路径忽略它。
    """
    sink = _MESSAGE_SINK.get()
    if sink is not None:
        sink(message)
        return
    click.echo(message, err=err)
