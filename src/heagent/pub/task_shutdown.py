"""后台调度 task 的关停内核（cron 调度与 dream 调度共用）。

两个后台调度器的关停立场完全一致：**立即 cancel + 单轮 bounded wait + 超时记 ERROR 放弃**，
绝不无限阻塞进程退出。``asyncio.wait({task}, timeout=)`` 超时不自动 cancel、也不传播 task 内
异常（含 ``CancelledError``）；task 响应取消则一个 tick 内 done、wait 立即返回；挂死则超时后
返回 pending，由调用方记 ERROR 放弃并取回孤儿 task 终态异常。

2026-09-15 之前 ``cron/scheduler.py`` 与 ``memory/dream.py`` 各持一份逐字同构的副本，仅靠两侧
docstring 互指「对齐」手工同步；此处合并为唯一实现点。

为什么不把这套内核放进其中一方：``cron`` 与 ``memory`` 在依赖 DAG 中是平级模块，任一方持有
内核都会给另一方引入一条**横向**依赖边；本模块只依赖 ``asyncio`` / ``logging``，两侧新增的
都是指向底层的边（与 ``engine/persist.py`` 被多层共享同构）。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# stop() 关停硬上界（task 挂死兜底）——与 MCP _DEFAULT_SHUTDOWN_TIMEOUT / sandbox _REAP_WAIT_TIMEOUT 同量级。
DEFAULT_STOP_TIMEOUT: float = 5.0


def retrieve_task_exception(task: asyncio.Task[None], *, owner: str) -> None:
    """done callback：取回关停超时后孤儿 task 的异常，避免 asyncio「Task exception was never retrieved」。

    超时分支放弃等待后，孤儿 task 仍在事件循环中收尾；若其终态带异常（调度循环 ``except Exception``
    之外的 ``BaseException`` 路径），未取回会触发警告。本 callback 在 task 终态被调用：cancelled task
    无需 retrieve（且 ``task.exception()`` 对 cancelled task 会抛 ``CancelledError``，须守卫），
    其余取非 None 异常记 ERROR 并标记 retrieved。

    ``owner`` 由调用方传入（如 ``"Cron scheduler"``），使日志仍能区分是哪个调度器的孤儿 task；
    调用方各自包一层 ``(task) -> None`` 薄包装后交给 ``add_done_callback``。
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("%s 关停后的孤儿 task 抛出未处理异常: %r", owner, exc)


async def await_task_stop(task: asyncio.Task[None], *, timeout: float, owner: str) -> bool:
    """立即 cancel 后单轮 bounded wait 收尾；返回 ``True`` 表示超时未退出（孤儿 task）。

    返回 ``True`` 时 task 已被 cancel 但窗口内未退出，调用方应挂
    :func:`retrieve_task_exception` 取回终态异常并释放自身引用（``self._task = None``），
    余下收尾交事件循环 / OS 进程退出兜底。
    """
    task.cancel()
    _, pending = await asyncio.wait({task}, timeout=timeout)
    if pending:
        logger.error("%s 关停超时（%ss），task 未退出，放弃等待", owner, timeout)
    return bool(pending)
