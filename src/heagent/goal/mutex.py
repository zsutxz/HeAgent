"""goal 域互斥的公共端口（台账 A32②：单推进者不变量自 CLI 下沉内核）。

竞态是「读 current 指针 → 读状态 → 推进 → 写 checkpoint / workflow.json /
brief.md」的整段读改写，per-file 锁防不了「两进程从同一状态各自推进后互相覆盖」，
故 goal 域一把域级锁。锁文件随 cwd 锚定，落在 ``.heagent/`` 运行时状态区。

复合互斥（原 ``cli/goal._goal_mutex`` 的语义逐字承接）：

- **进程内** ``asyncio.Lock`` 快速路径——同进程两协程不排队文件锁；
- **跨进程** ``.heagent/goal.lock`` 文件锁（:func:`heagent.pub.persist.file_lock`，
  POSIX ``flock`` / Windows ``msvcrt.locking``，获取/释放经 ``asyncio.to_thread``
  卸载）——双 CLI / CLI×GUI / cron×手动互斥。超时抛 ``OSError``——显性失败，
  由入口层收口为用户可见提示（cron 跳过本 tick 下一 tick 自动重试）。锁文件刻意
  保留不删（同 ``atomic_write_text`` 的 unlink 竞态论证；advisory 锁随进程退出
  自动释放，crash 不留死锁）。

**可重入**（下沉后新增）：变更内核 :mod:`heagent.goal.application` 的三个写方法
（``advance`` / ``pause_resume`` / ``record_decision``）自持本锁，而 CLI 等入口层
仍在外层整段持锁组合调用——重入按 ``asyncio.Task`` 属主判别：同一 task 再次进入
只增计数（文件锁只在 0→1 取一次），嵌套退出不减到 0 以下。属主判别以 task 为界
意味着**跨 task 的调用链不享重入**（入口把工作派给别的 task 时须自己持锁包裹整段）。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.pub.persist import file_lock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

GOAL_LOCK_PATH = Path(".heagent/goal.lock")
GOAL_LOCK_TIMEOUT = 5.0  # 并发方快速失败；cron 下一 tick 自动重试，手动方收到明确提示

_auto_lock = asyncio.Lock()
_owner: asyncio.Task[None] | None = None
_depth = 0


@asynccontextmanager
async def goal_mutex() -> AsyncIterator[None]:
    """goal 域变更互斥：进程内快速路径 + 跨进程文件锁，同一 task 内可重入。"""
    global _owner, _depth
    task = asyncio.current_task()
    if task is not None and _owner is task:
        _depth += 1
        try:
            yield
        finally:
            _depth -= 1
        return
    async with _auto_lock, file_lock(GOAL_LOCK_PATH, timeout=GOAL_LOCK_TIMEOUT):
        _owner, _depth = task, 1
        try:
            yield
        finally:
            _owner, _depth = None, 0
