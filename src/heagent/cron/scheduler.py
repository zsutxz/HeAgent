"""Asyncio 后台调度器 — 定期检查并执行到期的 Cron 任务。

手写 5-field cron 解析器（无外部依赖），支持：
  * (任意值)、*/N (每隔 N)、具体值、逗号分隔列表
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from heagent.cron.jobs import CronJob, JobStore

if TYPE_CHECKING:
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class CronScheduler:
    """Asyncio 后台调度器，定期检查并执行到期任务。

    通过构造函数注入 provider 和 stores，执行任务时创建独立 AgentLoop。
    """

    def __init__(
        self,
        job_store: JobStore,
        provider: BaseProvider,
        *,
        tick_seconds: int = 60,
        **loop_kwargs: object,
    ) -> None:
        self._store = job_store
        self._provider = provider
        self._tick_seconds = tick_seconds
        self._loop_kwargs = loop_kwargs
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """启动后台调度循环。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._tick_loop())
        logger.info("Cron scheduler started (tick=%ds)", self._tick_seconds)

    async def stop(self) -> None:
        """优雅停止后台调度。"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Cron scheduler stopped")

    # ---- 内部方法 ----

    async def _tick_loop(self) -> None:
        """后台循环：每 tick_seconds 秒检查一次到期任务。"""
        while self._running:
            try:
                await self._check_and_execute()
            except Exception:
                logger.exception("Cron tick error")
            await asyncio.sleep(self._tick_seconds)

    async def _check_and_execute(self) -> None:
        """检查所有已启用任务，执行到期任务。"""
        now = datetime.now()
        jobs = self._store.list_jobs()
        for job in jobs:
            if not job.enabled:
                continue
            if not self._matches(job.cron, now):
                continue
            await self._execute_job(job)

    async def _execute_job(self, job: CronJob) -> None:
        """创建独立 AgentLoop 执行任务。"""
        logger.info("Executing cron job '%s': %s", job.id, job.prompt[:50])
        success = False
        try:
            from heagent.agent.loop import AgentLoop

            loop = AgentLoop(self._provider, **self._loop_kwargs)  # type: ignore[arg-type]
            await loop.run(job.prompt)
            success = True
        except Exception:
            logger.exception("Cron job '%s' execution failed", job.id)

        if success:
            # 仅成功时更新最后运行时间
            from heagent.cron.jobs import _iso_now
            self._store.update(job.id, last_run=_iso_now())

            # 一次性任务成功后删除
            if not job.recurring:
                self._store.remove(job.id)
                logger.info("One-shot cron job '%s' removed after execution", job.id)

    @staticmethod
    def _matches(cron_expr: str, dt: datetime) -> bool:
        """评估 5-field cron 表达式是否匹配给定时间。

        支持格式：* (任意)、*/N (每隔)、具体值、逗号分隔列表。
        字段顺序：分钟 小时 日 月 星期
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False

        # weekday: Python 0=Mon, cron 0=Sun — 转换
        cron_weekday = (dt.weekday() + 1) % 7
        cron_values = (dt.minute, dt.hour, dt.day, dt.month, cron_weekday)

        for field_expr, actual in zip(parts, cron_values, strict=True):
            if not _field_matches(field_expr, actual):
                return False
        return True


def _field_matches(expr: str, value: int) -> bool:
    """检查单个 cron 字段是否匹配给定值。"""
    for part in expr.split(","):
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            if step > 0 and value % step == 0:
                return True
        elif part.isdigit():
            if value == int(part):
                return True
        # 不支持的范围表达式（如 1-5）在 V1 跳过
    return False
