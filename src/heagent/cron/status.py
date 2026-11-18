"""Cron 任务状态快照与下一次触发时刻计算。

时间口径（唯一真源，展示侧不得混用）：

- ``cron`` 表达式按**宿主本地时**求值——``CronScheduler._check_and_execute`` 用
  ``datetime.now()``（naive 本地时）；因此 :func:`next_fire` 收发都是本地 naive ``datetime``。
- ``CronJob.last_run`` / ``last_started`` / ``last_success`` 由 :func:`heagent.cron.jobs._iso_now`
  写入，是 **UTC** naive ISO 字符串——**无时区后缀**，字符串形态与本地时完全一致、无法从格式分辨。

状态真源：``CronScheduler._execute_job`` 在开始 / 成功 / 失败三处各写一次 ``last_status``
（值域 :class:`~heagent.cron.jobs.CronRunStatus`），并配 ``last_started`` / ``last_success`` /
``last_error``；``last_run`` 语义不变——只记一次执行**结束**的时刻。两个时间戳分工：
``last_started`` 判「卡住的 running」，``last_run`` 判「上次何时跑过」。

本模块只做纯计算（读 job 字段 + 本地时钟），不读写文件、不依赖 engine。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel

from heagent.cron.expr import parse_field
from heagent.cron.jobs import CronJob, CronRunStatus

logger = logging.getLogger(__name__)

#: cron 五字段的合法区间（与 ``cron/expr.py`` 的执行器同口径，逐字段对齐）。
_FIELD_RANGES: tuple[tuple[int, int], ...] = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_CRON_FIELD_COUNT = 5
_SUNDAY_ALIAS = 7

#: 下一次触发时刻的搜索上界（天）。超过仍无匹配即判「无触发时刻」（如 ``0 0 30 2 *``）。
NEXT_RUN_HORIZON_DAYS = 366

#: ``last_error`` 的保留长度上限：单行展示，异常消息再长也不该把终端刷屏。
ERROR_MAX_CHARS = 200

#: ``running`` 滞留多久判为 interrupted。活进程每轮执行都会重写 ``last_started``，超过该时长
#: 仍是 running ⇒ 记为「进程已退出、未收尾」（与 ``engine/store.close_stale_running`` 同为 6 小时）。
RUNNING_STALE_AFTER = timedelta(hours=6)


class CronJobState(StrEnum):
    """展示用状态——三个落盘值 + 由时间戳派生、**不落盘**的三种。

    ``NEVER``：从未有执行记录；``UNKNOWN``：旧版 ``jobs.json`` 有 ``last_run`` 但没记结果；
    ``INTERRUPTED``：``running`` 滞留超过 :data:`RUNNING_STALE_AFTER`（进程未收尾）。
    """

    NEVER = "never"
    UNKNOWN = "unknown"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class CronJobStatus(BaseModel):
    """单条 job 的状态快照（``--json`` 的数组元素就是它）。

    ``last_*`` 三个时间戳是 ``jobs.json`` 的 **UTC** 原值（不改写、不换算）；``next_run`` 是
    **宿主本地时**，``next_run_utc`` 是同一时刻的 UTC 口径——两者成对给出，避免读者跨时区对读。
    """

    id: str
    prompt: str
    cron: str
    recurring: bool
    enabled: bool
    status: CronJobState
    last_run: str | None = None  # UTC naive ISO（jobs.json 原值）
    last_started: str | None = None  # UTC naive ISO
    last_success: str | None = None  # UTC naive ISO
    last_error: str | None = None
    next_run: str | None = None  # 宿主本地时 naive ISO
    next_run_utc: str | None = None  # 同一时刻的 UTC naive ISO
    seconds_until_next: int | None = None
    next_run_note: str | None = None  # 算不出 next_run 时的原因（非法表达式 / 窗口内无匹配）


def parse_utc(raw: str | None) -> datetime | None:
    """解析 ``jobs.json`` 里的 UTC naive ISO 字符串；空值或格式不符返回 ``None``。

    格式不符只影响状态推导（降级成 unknown），不当成损坏数据——手改文件不该让整条 job 消失。
    """
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Unparsable UTC timestamp in cron job record: %r", raw)
        return None


def format_failure(exc: BaseException, *, limit: int = ERROR_MAX_CHARS) -> str:
    """把一次失败压成 ``异常类型: 首行消息`` 的单行串，超长截断。

    只要首行：异常消息常带多行堆栈片段或完整响应体，``jobs.json`` 不该被一条错误撑大，
    终端也需要单行可扫。
    """
    text = str(exc).strip()
    first_line = text.splitlines()[0].strip() if text else ""
    message = f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
    if len(message) > limit:
        return message[: max(limit - 1, 0)] + "…"
    return message


def next_fire(
    cron_expr: str,
    *,
    now: datetime | None = None,
    horizon_days: int = NEXT_RUN_HORIZON_DAYS,
) -> datetime | None:
    """下一次触发时刻（**宿主本地时** naive），严格晚于 ``now``（默认取当前本地时）。

    返回 ``None`` 表示 ``horizon_days`` 窗口内没有匹配；表达式非法（字段数不对、值越界、
    语法不认识）抛 ``ValueError``——让调用方区分「永不触发」与「写错了」。

    语义与执行器（:func:`heagent.cron.expr.cron_matches`）**逐字段 AND**，不采用 Vixie cron
    的「日与周同时受限时取 OR」约定：展示必须等于调度器真正会触发的时刻，而不是 POSIX 口径。
    日 / 月 / 周字段先做整日筛选，命中日再按小时 / 分钟集合取最小候选，避免逐分钟空转。
    """
    minutes, hours, days, months, weekdays = _parse_fields(cron_expr)
    start = (now or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    day = start.date()
    horizon_end = day + timedelta(days=horizon_days)
    while day <= horizon_end:
        if day.month in months and day.day in days and _cron_weekday(day) in weekdays:
            for hour in hours:
                for minute in minutes:
                    candidate = datetime(day.year, day.month, day.day, hour, minute)
                    if candidate >= start:
                        return candidate
        day += timedelta(days=1)
    return None


def _parse_fields(cron_expr: str) -> tuple[list[int], ...]:
    """把 5 字段表达式展开成 (分, 时, 日, 月, 周) 五个升序取值列表。

    复用 ``cron/expr.py`` 的字段解析器：语法与取值区间必须和真正调度时用的是同一份实现，
    否则「展示的下次触发」会与「实际触发」漂移。
    """
    parts = cron_expr.strip().split()
    if len(parts) != _CRON_FIELD_COUNT:
        raise ValueError(f"expected {_CRON_FIELD_COUNT} fields, got {len(parts)}")
    parsed: list[list[int]] = []
    for raw, (low, high) in zip(parts, _FIELD_RANGES, strict=True):
        values = parse_field(raw, min_val=low, max_val=high)
        if high == _SUNDAY_ALIAS:  # 周字段 7 与 0 同为周日（与 cron_matches 的归一化一致）
            values = sorted({0 if value == _SUNDAY_ALIAS else value for value in values})
        parsed.append(values)
    return tuple(parsed)


def _cron_weekday(day: date) -> int:
    """date → cron 周字段取值（Sun=0 … Sat=6），与 ``cron_matches`` 的换算一致。"""
    return (day.weekday() + 1) % 7


def resolve_state(
    job_status: str | None,
    *,
    last_run: str | None,
    last_started: str | None,
    utc_now: datetime,
) -> CronJobState:
    """由落盘的 ``last_status`` 与时间戳派生展示状态。

    ``running`` 但 ``last_started`` 早于 ``utc_now - RUNNING_STALE_AFTER`` ⇒ ``interrupted``
    （进程已退出、不会再有终态写入）；无 ``last_started`` 时退回 ``last_run`` 判龄，
    两者都缺则只能报 ``running``（没有依据判死）。
    """
    raw = (job_status or "").strip()
    if raw == CronRunStatus.RUNNING.value:
        started = parse_utc(last_started) or parse_utc(last_run)
        if started is not None and utc_now - started > RUNNING_STALE_AFTER:
            return CronJobState.INTERRUPTED
        return CronJobState.RUNNING
    if raw == CronRunStatus.SUCCESS.value:
        return CronJobState.SUCCESS
    if raw == CronRunStatus.FAILED.value:
        return CronJobState.FAILED
    if raw:
        logger.warning("Unknown cron run status recorded: %r", raw)
    return CronJobState.UNKNOWN if last_run else CronJobState.NEVER


def build_status(job: CronJob, *, now: datetime | None = None) -> CronJobStatus:
    """把一条 ``CronJob`` 整理成状态快照（``now`` 缺省取当前**本地**时）。"""
    local_now = now or datetime.now()
    utc_now = local_now.astimezone(UTC).replace(tzinfo=None)
    state = resolve_state(
        job.last_status,
        last_run=job.last_run,
        last_started=job.last_started,
        utc_now=utc_now,
    )

    upcoming: datetime | None = None
    note: str | None = None
    try:
        upcoming = next_fire(job.cron, now=local_now)
    except ValueError as exc:
        note = f"invalid cron expression: {exc}"
    else:
        if upcoming is None:
            note = f"no fire time within {NEXT_RUN_HORIZON_DAYS} days"

    return CronJobStatus(
        id=job.id,
        prompt=job.prompt,
        cron=job.cron,
        recurring=job.recurring,
        enabled=job.enabled,
        status=state,
        last_run=job.last_run,
        last_started=job.last_started,
        last_success=job.last_success,
        last_error=job.last_error,
        next_run=upcoming.strftime("%Y-%m-%dT%H:%M:%S") if upcoming is not None else None,
        next_run_utc=upcoming.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if upcoming is not None else None,
        seconds_until_next=int((upcoming - local_now).total_seconds()) if upcoming is not None else None,
        next_run_note=note,
    )


def build_statuses(jobs: list[CronJob], *, now: datetime | None = None) -> list[CronJobStatus]:
    """批量构造状态快照（保持入参顺序 = ``jobs.json`` 顺序）。"""
    return [build_status(job, now=now) for job in jobs]
