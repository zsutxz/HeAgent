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

logger = logging.getLogger(__name__)

# stop() 关停硬上界（task 挂死兜底）——对齐 MCP _DEFAULT_SHUTDOWN_TIMEOUT / sandbox _REAP_WAIT_TIMEOUT
_DEFAULT_STOP_TIMEOUT: float = 5.0

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
        stop_timeout: float = _DEFAULT_STOP_TIMEOUT,
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
        """扫描到期 job 并执行；``list_jobs()`` 失败不穿透（仅记日志，等待下次 tick 重试）。

        P0-2 修复：对每条 job 的 ``_matches`` 做 per-job try/except——
        存储中一条坏 cron 表达式不再导致同 tick 后续正常 job 全部跳过。
        """
        now = datetime.now()
        try:
            jobs = self._store.list_jobs()
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

            self._store.update(job.id, last_run=_iso_now())
            logger.exception("Cron job '%s' execution failed", job.id)
            return

        # 先写 ledger.complete（幂等标记），成功后再更新 last_run（P1-10 修复）。
        # 原顺序 store.update 在前：若 ledger.complete 抛异常，last_run 已更新但
        # 幂等未标记，下一分钟重复执行。
        await self._engine.ledger.complete(key, metadata={"job_id": job.id, "cron": job.cron})
        from heagent.cron.jobs import _iso_now

        self._store.update(job.id, last_run=_iso_now())
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
        """Evaluate a 5-field cron expression with range/step support (V2)."""
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False

        # weekday：标准 cron 中 Sunday 同时用 0 和 7 表示，此处映射到 0；
        # _field_matches 内部对 weekday 字段 (max_val=7) 统一做 7→0 规范化。
        cron_weekday = (dt.weekday() + 1) % 7  # Monday=1...Sunday=0
        cron_values = (dt.minute, dt.hour, dt.day, dt.month, cron_weekday)
        # 每个字段的合法范围（用于解析范围表达式）
        field_ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
        return all(
            _field_matches(expr, value, min_val=rng[0], max_val=rng[1])
            for expr, value, rng in zip(parts, cron_values, field_ranges, strict=True)
        )


def _field_matches(expr: str, value: int, *, min_val: int = 0, max_val: int = 59) -> bool:
    """Return whether one cron field matches one numeric value.

    V2 扩展：支持范围表达式（``1-5``）和步进组合（``*/15`` / ``1-30/10``）。
    内部走 ``_parse_field`` 统一解析 → 查值是否在展开列表中。

    P1-12 扩展修复：对 weekday 字段 (max_val==7) 统一把 cron ``"7"``（周日）
    映射到内部值 0（周日），覆盖单值 ``"7"``、范围 ``"5-7"``、列表 ``"1,3,7"``
    等全部语法。原修复仅覆盖 ``expr=="7"`` 的精确匹配，范围/列表中的 7 会漏判周日。
    """
    values = _parse_field(expr, min_val=min_val, max_val=max_val)
    if max_val == 7:
        values = [0 if v == 7 else v for v in values]
    return value in values


def _parse_field(raw: str, *, min_val: int = 0, max_val: int = 59) -> list[int]:
    """统一解析 cron 字段为展开数值列表（V2 新增）。

    支持的语法：
    - ``*`` → [min_val, ..., max_val]
    - 单个数值 ``"5"`` → [5]
    - 逗号列表 ``"1,3,5"`` → [1, 3, 5]
    - 范围 ``"1-5"`` → [1, 2, 3, 4, 5]
    - 步进 ``"*/15"`` → 从 min_val 开始每隔 step 的值
    - 范围+步进 ``"1-30/10"`` → [1, 11, 21]
    """
    raw = raw.strip()
    result: list[int] = []

    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue

        # 范围+步进: "1-30/10"
        if "/" in part and "-" in part:
            range_part, step_str = part.split("/", 1)
            start_str, end_str = range_part.split("-", 1)
            start, end, step = _validate_range_parts(start_str, end_str, step_str, min_val, max_val)
            result.extend(range(start, end + 1, step))

        # 纯步进: "*/15"
        elif part.startswith("*/"):
            step_str = part[2:]
            if not step_str or not step_str.isdigit():
                raise ValueError(f"Invalid step in cron field: {part!r}")
            step = int(step_str)
            if step <= 0:
                raise ValueError(f"Cron step must be positive: {step}")
            result.extend(range(min_val, max_val + 1, step))

        # 纯范围: "1-5"
        elif "-" in part:
            start_str, end_str = part.split("-", 1)
            start, end = _parse_range_bounds(start_str, end_str, min_val, max_val)
            result.extend(range(start, end + 1))

        # 通配符 "*"
        elif part == "*":
            result.extend(range(min_val, max_val + 1))

        # 单个数值 "5"
        elif part.isdigit():
            v = int(part)
            if v < min_val or v > max_val:
                raise ValueError(f"Cron value {v} out of range [{min_val}, {max_val}]")
            result.append(v)

        else:
            raise ValueError(f"Invalid cron field expression: {part!r}")

    return sorted(set(result))


def _parse_range_bounds(start_str: str, end_str: str, min_val: int, max_val: int) -> tuple[int, int]:
    """解析并校验范围边界。"""
    if not start_str.isdigit() or not end_str.isdigit():
        raise ValueError(f"Invalid cron range: {start_str}-{end_str}")
    start = int(start_str)
    end = int(end_str)
    if start < min_val or end > max_val:
        raise ValueError(f"Cron range {start}-{end} out of [{min_val}, {max_val}]")
    if start > end:
        raise ValueError(f"Cron range start {start} > end {end}")
    return start, end


def _validate_range_parts(
    start_str: str, end_str: str, step_str: str, min_val: int, max_val: int
) -> tuple[int, int, int]:
    """解析并校验范围+步进参数。"""
    start, end = _parse_range_bounds(start_str, end_str, min_val, max_val)
    if not step_str.isdigit():
        raise ValueError(f"Invalid cron step: {step_str!r}")
    step = int(step_str)
    if step <= 0:
        raise ValueError(f"Cron step must be positive: {step}")
    return start, end, step
