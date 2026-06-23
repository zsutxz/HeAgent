"""Builtin tools for cron job management."""

from __future__ import annotations

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


@tool
async def cron_add(prompt: str, schedule: str, recurring: bool = True) -> str:
    """Create one scheduled cron job."""
    store = _store()
    if store is None:
        return "Error: cron tools not configured."
    job = store.create_job(prompt, schedule, recurring=recurring)
    store.add(job)
    return f"Cron job created: id={job.id}, schedule='{schedule}', recurring={job.recurring}"


@tool
async def cron_list() -> str:
    """List all scheduled cron jobs."""
    store = _store()
    if store is None:
        return "Error: cron tools not configured."
    jobs = store.list_jobs()
    if not jobs:
        return "No cron jobs scheduled."
    lines: list[str] = []
    for job in jobs:
        status = "enabled" if job.enabled else "disabled"
        recurrence = "recurring" if job.recurring else "one-shot"
        lines.append(
            f"- [{job.id}] '{job.prompt[:40]}' | {job.cron} | {recurrence} | {status} | last: {job.last_run or 'never'}"
        )
    return "\n".join(lines)


@tool
async def cron_remove(job_id: str) -> str:
    """Delete one scheduled cron job."""
    store = _store()
    if store is None:
        return "Error: cron tools not configured."
    if store.remove(job_id):
        return f"Cron job '{job_id}' removed."
    return f"Error: cron job '{job_id}' not found."
