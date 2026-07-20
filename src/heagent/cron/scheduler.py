"""Async background cron scheduler."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from heagent.engine import EngineContainer

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from heagent.cron.jobs import CronJob, JobStore
    from heagent.engine.context import RunContext
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# stop() 关停硬上界（task 挂死兜底）——对齐 MCP _DEFAULT_SHUTDOWN_TIMEOUT / sandbox _REAP_WAIT_TIMEOUT
_DEFAULT_STOP_TIMEOUT: float = 5.0

# JobRunner: agent 层注入的 job 执行协议（prompt + run_context → awaitable）。
# cron 模块不再反向依赖 agent——runner 由 cli.py 实例化时注入。
JobRunner = Callable[[str, "RunContext"], "Awaitable[None]"]


class CronScheduler:
    """Periodic scheduler that runs due cron jobs through an injected JobRunner.

    C-3 修正：cron 不再反向依赖 agent。runner 由上层（cli.py）注入，cron 仅依赖
    provider / engine / 协议类型，保持 DAG 方向一致。
    """

    def __init__(
        self,
        job_store: JobStore,
        provider: BaseProvider,
        *,
        tick_seconds: int = 60,
        engine: EngineContainer | None = None,
        stop_timeout: float = _DEFAULT_STOP_TIMEOUT,
        job_runner: JobRunner | None = None,
    ) -> None:
        if stop_timeout <= 0:
            # 非正值会让 _await_stop 的 wait 立即返回（task 仍 pending）→ 不给 cancel 任何收尾
            # 机会即 ERROR 放弃（与 MCP shutdown_timeout<=0 同构误用）。fail-closed。
            raise ValueError(f"stop_timeout 必须为正数（got {stop_timeout}）")
        self._store = job_store
        self._provider = provider
        self._tick_seconds = tick_seconds
        self._stop_timeout = stop_timeout
        self._engine = engine or EngineContainer.default()
        self._job_runner = job_runner
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._tick_loop())
        logger.info("Cron scheduler started (tick=%ds)", self._tick_seconds)

    async def stop(self) -> None:
        """Stop the background scheduler loop gracefully（带硬上界，task 挂死时记 ERROR 放弃）。

        ``_tick_loop`` 卡在 ``_check_and_execute``（``AgentLoop.run`` 内不可中断 await 点）时，
        ``task.cancel()`` 注入的 ``CancelledError`` 可被吞 → task 不退出 → 裸 ``await self._task``
        无限阻塞 ``stop()``（pre-existing LOW-MED，与 MCP ``__aexit__`` 同构；唯一调用方
        ``cli.py`` 交互模式 finally 是进程退出路径，挂死 = 进程退出挂死）。本方法给关停硬上界：
        立即 cancel 后单轮 bounded ``asyncio.wait`` 收尾，task 响应取消则一个 tick 内 done，
        挂死则 ``stop_timeout`` 后记 ERROR 放弃，绝不无限阻塞。
        """
        self._running = False
        if self._task and not self._task.done():
            await self._await_stop(self._task)
        logger.info("Cron scheduler stopped")

    async def _await_stop(self, task: asyncio.Task[None]) -> None:
        """带硬上界等待 scheduler task 退出；立即 cancel 后单轮 bounded 收尾，绝不无限阻塞。

        保留原「立即 cancel」语义（cron 后台调度停止求快，``_tick_loop`` 多在 ``asyncio.sleep``，
        graceful 窗口等不到自然退出反增延迟；与 MCP ``_await_shutdown`` 的 graceful 优先两轮不同——
        两者核心立场一致：关停必须有上界，解按场景适配）。``asyncio.wait({task}, timeout=)`` 超时
        不自动 cancel、不传播 task 内异常（含 ``CancelledError``），task 响应取消则一个 tick 内
        done、wait 立即返回；挂死则 ``stop_timeout`` 后返回 pending → 记 ERROR 放弃（task 已 cancel，
        余下收尾交 GC / OS 进程退出兜底）。
        """
        task.cancel()
        _, pending = await asyncio.wait({task}, timeout=self._stop_timeout)
        if pending:
            logger.error(
                "Cron scheduler 关停超时（%ss），task 未退出，放弃等待",
                self._stop_timeout,
            )

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                await self._check_and_execute()
            except Exception:
                logger.exception("Cron tick error")
            await asyncio.sleep(self._tick_seconds)

    async def _check_and_execute(self) -> None:
        now = datetime.now()
        jobs = self._store.list_jobs()
        for job in jobs:
            if not job.enabled:
                continue
            if not self._matches(job.cron, now):
                continue
            await self._execute_job(job, now=now)

    async def _execute_job(self, job: CronJob, *, now: datetime) -> None:
        """Execute one due job if the execution ledger grants the lease."""
        if self._job_runner is None:
            logger.warning("CronScheduler has no job_runner injected; skipping job '%s'", job.id)
            return

        key = f"cron:{job.id}:{now.strftime('%Y-%m-%dT%H:%M')}"
        claim = await self._engine.ledger.acquire(
            key,
            scope="cron",
            lease_seconds=max(self._tick_seconds * 2, 120),
            metadata={"job_id": job.id, "cron": job.cron},
        )
        if not claim.acquired:
            logger.debug("Skipping cron job '%s' (%s)", job.id, claim.reason)
            return

        self._engine.events.publish(
            "cron_job_started",
            details={"job_id": job.id, "schedule": job.cron},
        )

        success = False
        run_context = self._engine.create_run_context(
            metadata={"kind": "cron", "job_id": job.id},
            workspace_root=str(getattr(self._engine, "workspace_root", "") or ""),
        )
        try:
            await self._job_runner(job.prompt, run_context)
            success = True
        except Exception as exc:
            await self._engine.ledger.fail(key, str(exc), metadata={"job_id": job.id, "cron": job.cron})
            self._engine.events.publish(
                "cron_job_failed",
                run_id=run_context.run_id,
                details={"job_id": job.id, "error": str(exc)},
            )
            logger.exception("Cron job '%s' execution failed", job.id)

        if success:
            from heagent.cron.jobs import _iso_now

            self._store.update(job.id, last_run=_iso_now())
            await self._engine.ledger.complete(key, metadata={"job_id": job.id, "cron": job.cron})
            self._engine.events.publish(
                "cron_job_completed",
                run_id=run_context.run_id,
                details={"job_id": job.id},
            )
            if not job.recurring:
                self._store.remove(job.id)
                logger.info("One-shot cron job '%s' removed after execution", job.id)

    @staticmethod
    def _matches(cron_expr: str, dt: datetime) -> bool:
        """Evaluate a simple 5-field cron expression."""
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False

        cron_weekday = (dt.weekday() + 1) % 7
        cron_values = (dt.minute, dt.hour, dt.day, dt.month, cron_weekday)
        return all(_field_matches(field_expr, actual) for field_expr, actual in zip(parts, cron_values, strict=True))


def _field_matches(expr: str, value: int) -> bool:
    """Return whether one cron field matches one numeric value."""
    for part in expr.split(","):
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            if step > 0 and value % step == 0:
                return True
        elif part.isdigit() and value == int(part):
            return True
    return False
