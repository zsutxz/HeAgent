"""Async background cron scheduler."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from heagent.cron.expr import cron_matches
from heagent.engine import EngineContainer
from heagent.pub.task_shutdown import DEFAULT_STOP_TIMEOUT, await_task_stop, retrieve_task_exception

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from heagent.cron.jobs import CronJob, JobStore
    from heagent.engine.context import RunContext

logger = logging.getLogger(__name__)

# JobRunner: agent 层注入的 job 执行协议（prompt + run_context → awaitable）。
# cron 模块不再反向依赖 agent——runner 由 cli.py 实例化时注入。
JobRunner = Callable[[str, "RunContext"], "Awaitable[None]"]


class CronScheduler:
    """Periodic scheduler that runs due cron jobs through an injected JobRunner.

    C-3 修正：cron 不再反向依赖 agent。runner 由上层（cli.py）注入，cron 仅依赖
    engine / 协议类型，保持 DAG 方向一致。
    """

    def __init__(
        self,
        job_store: JobStore,
        *,
        tick_seconds: int = 60,
        engine: EngineContainer | None = None,
        stop_timeout: float = DEFAULT_STOP_TIMEOUT,
        job_runner: JobRunner | None = None,
    ) -> None:
        if stop_timeout <= 0:
            # 非正值会让 _await_stop 的 wait 立即返回（task 仍 pending）→ 不给 cancel 任何收尾
            # 机会即 ERROR 放弃（与 MCP shutdown_timeout<=0 同构误用）。fail-closed。
            raise ValueError(f"stop_timeout 必须为正数（got {stop_timeout}）")
        self._store = job_store
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
        done、wait 立即返回；挂死则 ``stop_timeout`` 后返回 pending → 记 ERROR 放弃（task 已 cancel），
        并挂 done callback（``_retrieve_task_exception``）取回孤儿 task 终态异常（避免「Task exception
        was never retrieved」），清 ``_task`` 释放引用；余下收尾交事件循环 / OS 进程退出兜底。

        cancel / bounded wait / 超时告警本身实现在 ``heagent.pub.task_shutdown.await_task_stop``
        （与 :class:`~heagent.memory.dream.DreamScheduler` 共用同一内核）。
        """
        if await await_task_stop(task, timeout=self._stop_timeout, owner="Cron scheduler"):
            # 孤儿 task：已 cancel 但窗口内未退出。挂 done callback 取回 exception（标记 retrieved），
            # 避免「Task exception was never retrieved」；清 _task 释放引用，余下收尾交事件循环/GC/OS 进程退出。
            task.add_done_callback(_retrieve_task_exception)
            self._task = None

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                await self._check_and_execute()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cron tick error")
            await asyncio.sleep(self._tick_seconds)

    async def _check_and_execute(self) -> None:
        """扫描到期 job 并执行；``list_jobs()`` 失败不穿透（仅记日志，等待下次 tick 重试）。

        P0-2 修复：对每条 job 的 ``_matches`` 做 per-job try/except——
        存储中一条坏 cron 表达式不再导致同 tick 后续正常 job 全部跳过。
        """
        now = datetime.now()
        try:
            # store 的读写是同步文件 I/O（含 Windows 替换退避 time.sleep），经 to_thread 卸载，
            # 不阻塞事件循环（对齐 273cb89 file/search 工具与 WorkflowCheckpointStore 先例）。
            jobs = await asyncio.to_thread(self._store.list_jobs)
        except Exception:
            logger.exception("Failed to load cron jobs; skipping this tick")
            return
        for job in jobs:
            if not job.enabled:
                continue
            # P0-2：per-job ValueError 保护 —— 非法 cron 表达式仅跳过当前 job
            try:
                if not self._matches(job.cron, now):
                    continue
            except ValueError:
                logger.warning(
                    "Invalid cron expression for job '%s': %s — skipping this tick",
                    job.id,
                    job.cron,
                )
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

        run_context = self._engine.create_run_context(
            metadata={"kind": "cron", "job_id": job.id},
            workspace_root=str(getattr(self._engine, "workspace_root", "") or ""),
        )
        try:
            await self._job_runner(job.prompt, run_context)
        except Exception as exc:
            await self._engine.ledger.fail(key, str(exc), metadata={"job_id": job.id, "cron": job.cron})
            self._engine.events.publish(
                "cron_job_failed",
                run_id=run_context.run_id,
                details={"job_id": job.id, "error": str(exc)},
            )
            # 失败路径也更新 last_run——防止每分钟无限重试（P1-11 修复）。
            # ledger.fail() 清除了 lease_expires_at，下一分钟新 key 的 acquire 会成功；
            # last_run 不更新会导致同一个逻辑分钟被无限重入。
            from heagent.cron.jobs import _iso_now

            await asyncio.to_thread(self._store.update, job.id, last_run=_iso_now())
            logger.exception("Cron job '%s' execution failed", job.id)
            return

        # 先写 ledger.complete（幂等标记），成功后再更新 last_run（P1-10 修复）。
        # 原顺序 store.update 在前：若 ledger.complete 抛异常，last_run 已更新但
        # 幂等未标记，下一分钟重复执行。
        await self._engine.ledger.complete(key, metadata={"job_id": job.id, "cron": job.cron})
        from heagent.cron.jobs import _iso_now

        await asyncio.to_thread(self._store.update, job.id, last_run=_iso_now())
        self._engine.events.publish(
            "cron_job_completed",
            run_id=run_context.run_id,
            details={"job_id": job.id},
        )
        if not job.recurring:
            await asyncio.to_thread(self._store.remove, job.id)
            logger.info("One-shot cron job '%s' removed after execution", job.id)

    @staticmethod
    def _matches(cron_expr: str, dt: datetime) -> bool:
        """Evaluate a 5-field cron expression（薄委托 :func:`heagent.cron.expr.cron_matches`）。

        实现已抽到纯叶子 :mod:`heagent.cron.expr`（解耦 ``memory/dream`` 横向 reach-through）。
        保留此静态方法以维持既有 API 面（``test_cron.py`` + 内部 ``self._matches`` 调用），
        零行为变更。
        """
        return cron_matches(cron_expr, dt)


def _retrieve_task_exception(task: asyncio.Task[None]) -> None:
    """done callback：取回关停超时后孤儿 task 的异常（实现见 ``heagent.pub.task_shutdown``）。

    保留本薄包装而非直接传 ``functools.partial``：``add_done_callback`` 因此拿到签名严格为
    ``(task) -> None`` 的可调用对象，同时保住 ``owner`` 日志前缀；两侧同名薄包装也让
    ``test_cron.py`` / ``test_dream.py`` 继续断言「cron 与 dream 对称」。
    """
    retrieve_task_exception(task, owner="Cron scheduler")
