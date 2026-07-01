"""Async background cron scheduler."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from heagent.engine import EngineContainer

if TYPE_CHECKING:
    from heagent.cron.jobs import CronJob, JobStore
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class CronScheduler:
    """Periodic scheduler that runs due cron jobs through AgentLoop."""

    def __init__(
        self,
        job_store: JobStore,
        provider: BaseProvider,
        *,
        tick_seconds: int = 60,
        engine: EngineContainer | None = None,
        **loop_kwargs: object,
    ) -> None:
        self._store = job_store
        self._provider = provider
        self._tick_seconds = tick_seconds
        self._loop_kwargs = loop_kwargs
        self._engine = engine or EngineContainer.default()
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
        """Stop the background scheduler loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Cron scheduler stopped")

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
            from heagent.agent.loop import AgentLoop

            loop = AgentLoop(
                self._provider,
                engine=self._engine,
                run_context=run_context,
                **self._loop_kwargs,  # type: ignore[arg-type]
            )
            await loop.run(job.prompt)
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
