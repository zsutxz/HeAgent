"""Cron 管理工具 — 供 LLM 创建、查看和删除定时任务。

通过 configure_cron_tools(store) 注入 JobStore 实例。
未配置时所有工具返回错误提示，不会抛异常。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.tools.decorator import tool

if TYPE_CHECKING:
    from heagent.cron.jobs import JobStore

_cron_store: JobStore | None = None


def configure_cron_tools(store: JobStore) -> None:
    """注入 JobStore 实例，激活 cron 管理工具。"""
    global _cron_store
    _cron_store = store


def reset_cron_tools() -> None:
    """重置模块级 JobStore（测试清理用）。"""
    global _cron_store
    _cron_store = None


@tool
async def cron_add(prompt: str, schedule: str, recurring: bool = True) -> str:
    """创建一个定时任务。schedule 为 cron 表达式（如 '*/5 * * * *' 表示每 5 分钟）。
    用于定期执行任务或设置一次性提醒。

    参数：
        prompt: 要执行的任务描述
        schedule: cron 表达式（5 字段：分 时 日 月 星期）
        recurring: 是否循环执行（默认 True），False 为一次性任务
    """
    if _cron_store is None:
        return "Error: cron tools not configured."
    job = _cron_store.create_job(prompt, schedule, recurring=recurring)
    _cron_store.add(job)
    return f"Cron job created: id={job.id}, schedule='{schedule}', recurring={job.recurring}"


@tool
async def cron_list() -> str:
    """列出所有已调度的定时任务。"""
    if _cron_store is None:
        return "Error: cron tools not configured."
    jobs = _cron_store.list_jobs()
    if not jobs:
        return "No cron jobs scheduled."
    lines: list[str] = []
    for job in jobs:
        status = "enabled" if job.enabled else "disabled"
        recur = "recurring" if job.recurring else "one-shot"
        lines.append(
            f"- [{job.id}] '{job.prompt[:40]}' | {job.cron} | {recur} | {status} | last: {job.last_run or 'never'}"
        )
    return "\n".join(lines)


@tool
async def cron_remove(job_id: str) -> str:
    """删除一个定时任务。

    参数：
        job_id: 要删除的任务 ID
    """
    if _cron_store is None:
        return "Error: cron tools not configured."
    if _cron_store.remove(job_id):
        return f"Cron job '{job_id}' removed."
    return f"Error: cron job '{job_id}' not found."
