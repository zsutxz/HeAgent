"""Builtin tools for cron job management."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from heagent.tools.decorator import tool
from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from heagent.cron.jobs import JobStore


@dataclass(slots=True)
class CronToolRuntime:
    """Runtime dependencies for cron tools."""

    store: JobStore | None


_cron_runtime = RuntimeSlot[CronToolRuntime]("heagent_cron_tools")


def configure_cron_tools(store: JobStore | None) -> None:
    """Set the fallback job store used outside an agent run."""
    _cron_runtime.configure(CronToolRuntime(store=store))


def reset_cron_tools() -> None:
    """Clear the fallback job store."""
    _cron_runtime.reset()


@contextmanager
def bind_cron_tools(store: JobStore | None) -> Iterator[None]:
    """Bind a job store for the current run context."""
    with _cron_runtime.bind(CronToolRuntime(store=store)):
        yield


def _store() -> JobStore | None:
    runtime = _cron_runtime.get()
    return runtime.store if runtime is not None else None


def _validate_schedule(schedule: str) -> str | None:
    """快速校验 cron 表达式合法性；非法返回错误消息，合法返回 None。

    仅做基本格式检查（5 字段、每字段仅含数字/`*`/`,`/`-`/`/`），
    不覆盖全部 cron 语义，但可拦截明显错误的输入。
    对齐运行期解析器（cron/expr.py V2）：范围+步进（``1-30/10``）与 ``*/step`` 合法，
    ``5/10``（纯值带步进）与步进 0 运行期同拒——校验层不得比执行层更严，也不替它放行。
    """
    parts = schedule.strip().split()
    if len(parts) != 5:
        return f"Invalid cron schedule: expected 5 fields, got {len(parts)} — example: '0 9 * * *'"
    for i, part in enumerate(parts):
        if part == "*":
            continue
        for sub in part.split(","):
            base, _, step = sub.partition("/")
            if step:
                if not step.isdigit() or int(step) == 0:
                    return f"Invalid cron field {i + 1}: {part!r}"
                if base != "*" and "-" not in base:
                    return f"Invalid cron field {i + 1}: {part!r}"
            if base == "*":
                continue
            if "-" in base:
                start, end = base.split("-", 1)
                if not (start.isdigit() and end.isdigit()):
                    return f"Invalid cron field {i + 1}: {part!r}"
            elif not base.isdigit():
                return f"Invalid cron field {i + 1}: {part!r}"
    return None


@tool
async def cron_add(prompt: str, schedule: str, recurring: bool = True) -> str:
    """Create one scheduled cron job."""
    store = _store()
    if store is None:
        return "Error: cron tools not configured."
    # P1-13 修复：预校验 schedule，阻止非法 cron 表达式静默入库
    err = _validate_schedule(schedule)
    if err is not None:
        return f"Error: {err}"
    job = store.create_job(prompt, schedule, recurring=recurring)
    # store.add 是同步文件 I/O（含 Windows 替换退避）⇒ 卸载到线程，不卡事件循环（对齐 cron/scheduler.py 同一批 store 方法的先例）
    await asyncio.to_thread(store.add, job)
    return f"Cron job created: id={job.id}, schedule='{schedule}', recurring={job.recurring}"


@tool(read_only=True)
async def cron_list() -> str:
    """List all scheduled cron jobs."""
    store = _store()
    if store is None:
        return "Error: cron tools not configured."
    jobs = await asyncio.to_thread(store.list_jobs)
    parts: list[str] = []

    # P0-3：展示因损坏/非法而被跳过的条目数（静默消失→用户可感知）
    corrupted = store.corruption_count
    if corrupted == -1:
        parts.append("⚠️  Cron jobs file is corrupted or not a valid list — all entries skipped.")
    elif corrupted > 0:
        parts.append(f"⚠️  {corrupted} job(s) skipped due to corruption or invalid fields.")

    if not jobs:
        parts.append("No cron jobs scheduled.")
        return "\n".join(parts)

    lines: list[str] = []
    for job in jobs:
        status = "enabled" if job.enabled else "disabled"
        recurrence = "recurring" if job.recurring else "one-shot"
        lines.append(
            f"- [{job.id}] '{job.prompt[:40]}' | {job.cron} | {recurrence} | {status} | last: {job.last_run or 'never'}"
        )
    parts.append("\n".join(lines))
    return "\n".join(parts)


@tool
async def cron_remove(job_id: str) -> str:
    """Delete one scheduled cron job."""
    store = _store()
    if store is None:
        return "Error: cron tools not configured."
    removed = await asyncio.to_thread(store.remove, job_id)
    if removed:
        return f"Cron job '{job_id}' removed."
    return f"Error: cron job '{job_id}' not found."
