"""``heagent cron``：定时任务状态查询（只读，不启调度器）。

子命令：

- ``status``：逐条 job 的详细状态（状态、最后/下次执行时间、失败错误信息）；
- ``list``：一行一条的紧凑视图（找 ID 用）；同样支持 ``--json``。

**只读**：只读 ``jobs.json``（``--jobs-file`` 可改路径，默认取当前项目根
``WorkspacePaths.cron_file``），不修改文件、不启动 ``CronScheduler``、不调模型。

时间口径（与本模块输出里的标注一一对应，不得混用）：

- ``cron`` 表达式按**宿主本地时**求值 ⇒ ``next run`` 是本地时（另给同一时刻的 UTC 便于对日志）；
- ``last_run`` / ``last_started`` / ``last_success`` 在 ``jobs.json`` 里存 **UTC**（naive ISO，
  无时区后缀）⇒ 输出一律带 ``Z`` 后缀并附本地时换算。

退出码（两种子命令一致，便于脚本/CI 消费）：

- ``0``：查询成功，且没有 job 的最近一次执行是 ``failed``；
- ``1``：查询成功，但有 job 最近一次执行 ``failed``；
- ``2``：``jobs.json`` 整体不可解析（损坏 / 不是列表）——没有任何可报告的内容。

分层：入口层（``heagent/cli/``），只依赖 click + 标准库 + ``heagent.cron`` / ``heagent.pub``；
不导入 ``agent`` / ``engine``——查状态不需要运行栈。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import click

from heagent.cron.jobs import JobStore
from heagent.cron.status import CronJobState, CronJobStatus, build_statuses, parse_utc
from heagent.pub.workspace import WorkspacePaths

#: 退出码（见模块 docstring）。
EXIT_OK = 0
EXIT_JOB_FAILED = 1
EXIT_JOBS_UNREADABLE = 2

#: 人类可读视图里 prompt 的截断宽度（与 ``cron_list`` 工具同口径）。
PROMPT_WIDTH = 40

#: 时区口径说明——``status`` 人读输出必带（``--json`` 不带，JSON 必须是裸数组）。
TIME_NOTE = (
    "cron fields are evaluated in host local time; last_run/last_started/last_success are stored in UTC "
    "(printed with a Z suffix plus the local equivalent); next run is local time"
)


@click.group("cron")
def cron_cmd() -> None:
    """Inspect scheduled cron jobs (read-only; does not start the scheduler)."""


@cron_cmd.command("status")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit a JSON array instead of the report")
@click.option(
    "--jobs-file",
    "jobs_file",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Jobs file to read (default: <cwd>/.heagent/cron/jobs.json)",
)
def status_cmd(as_json: bool, jobs_file: Path | None) -> None:
    """Show per-job state: last/last-success runs, last error, next run.

    Exit code: 0 = no job's last run failed; 1 = at least one failed; 2 = jobs file unreadable.
    """
    _run(as_json=as_json, jobs_file=jobs_file, detailed=True)


@cron_cmd.command("list")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit a JSON array instead of the table")
@click.option(
    "--jobs-file",
    "jobs_file",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Jobs file to read (default: <cwd>/.heagent/cron/jobs.json)",
)
def list_cmd(as_json: bool, jobs_file: Path | None) -> None:
    """List jobs in one line each (same exit codes as ``status``)."""
    _run(as_json=as_json, jobs_file=jobs_file, detailed=False)


def _run(*, as_json: bool, jobs_file: Path | None, detailed: bool) -> None:
    """加载 → 渲染 → 按 job 状态决定退出码（两个子命令共用同一条管线）。"""
    path = jobs_file or _default_jobs_file()
    store = JobStore(str(path))
    jobs = store.list_jobs()
    corrupted = store.corruption_count
    if corrupted == -1:
        # 整个文件不是合法 jobs 列表：没有任何可报告内容，脚本消费方必须知道（不能回空数组装成功）。
        if as_json:
            click.echo(json.dumps({"error": "jobs file is corrupted or not a list", "jobs_file": str(path)}))
        else:
            click.echo(f"[cron] jobs file is corrupted or not a list: {path}", err=True)
        raise SystemExit(EXIT_JOBS_UNREADABLE)

    statuses = build_statuses(jobs)
    if as_json:
        click.echo(json.dumps([item.model_dump(mode="json") for item in statuses], ensure_ascii=False))
    else:
        if corrupted > 0:
            click.echo(f"[cron] warning: {corrupted} job(s) skipped (corrupted or invalid fields)", err=True)
        _render(statuses, path=path, detailed=detailed)

    raise SystemExit(EXIT_JOB_FAILED if any(item.status is CronJobState.FAILED for item in statuses) else EXIT_OK)


def _default_jobs_file() -> Path:
    """默认 jobs 文件 = 当前工作目录所属项目的状态根（与 CLI 启动口径一致：在项目根运行）。"""
    return WorkspacePaths.from_root(Path.cwd()).cron_file


def _render(statuses: list[CronJobStatus], *, path: Path, detailed: bool) -> None:
    """人读视图（stdout：这是本命令的主产物，需要可重定向/可管道）。"""
    click.echo(f"[cron] jobs file: {path}")
    if not statuses:
        click.echo("[cron] no jobs scheduled — create one in a session with the cron_add tool")
        return
    click.echo(f"[cron] {len(statuses)} job(s): {_counts(statuses)}")
    click.echo(f"[time] {TIME_NOTE}")
    for item in statuses:
        click.echo("")
        if not detailed:
            click.echo(_compact_line(item))
            continue
        click.echo(_header(item))
        for line in _detail_lines(item):
            click.echo(line)


def _counts(statuses: list[CronJobStatus]) -> str:
    """按展示状态计数（只列出现过的状态，顺序固定）。"""
    tally = {state: 0 for state in CronJobState}
    for item in statuses:
        tally[item.status] += 1
    return ", ".join(f"{count} {state.value}" for state, count in tally.items() if count)


def _prompt_text(item: CronJobStatus) -> str:
    suffix = "…" if len(item.prompt) > PROMPT_WIDTH else ""
    return item.prompt[:PROMPT_WIDTH] + suffix


def _schedule_text(item: CronJobStatus) -> str:
    recurrence = "recurring" if item.recurring else "one-shot"
    return f"{item.cron} | {recurrence} | {'enabled' if item.enabled else 'disabled'}"


def _header(item: CronJobStatus) -> str:
    return f"[job {item.id}] '{_prompt_text(item)}' | {_schedule_text(item)}"


def _compact_line(item: CronJobStatus) -> str:
    """``list`` 的一行视图：状态与下次执行时间必须在这一行里看到。"""
    next_run = datetime.fromisoformat(item.next_run).strftime("%Y-%m-%d %H:%M local") if item.next_run else "n/a"
    return f"[job {item.id}] {item.status.value:<11} | next {next_run:<24} | '{_prompt_text(item)}' | {_schedule_text(item)}"


def _detail_lines(item: CronJobStatus) -> list[str]:
    """``status`` 的逐字段明细；缺什么就明说什么（不静默留白）。"""
    lines = [f"  status:    {item.status.value}{_status_suffix(item)}"]
    if item.last_error:
        lines.append(f"  error:     {item.last_error}")
    if item.last_success:
        lines.append(f"  last ok:   {_dual(item.last_success)}")
    lines.append(f"  next run:  {_next_run_text(item)}")
    return lines


def _status_suffix(item: CronJobStatus) -> str:
    """状态行后缀：把「什么时候跑的」贴着状态说清楚（never 没有时刻可说）。"""
    if item.status is CronJobState.RUNNING:
        return f" — started {_dual(item.last_started or item.last_run)}"
    if item.status is CronJobState.INTERRUPTED:
        return f" — started {_dual(item.last_started or item.last_run)} and never finished"
    if item.status is CronJobState.NEVER:
        return ""
    return f" — last run {_dual(item.last_run)}"


def _dual(raw: str | None) -> str:
    """UTC naive ISO → ``<原值>Z (= <本地时> local)``；解析不了就原样回显。"""
    stamp = parse_utc(raw)
    if stamp is None:
        return raw or "never"
    local = stamp.replace(tzinfo=UTC).astimezone()  # naive UTC → 本机时区
    return f"{stamp.strftime('%Y-%m-%dT%H:%M:%SZ')} (= {local.strftime('%Y-%m-%d %H:%M')} local)"


def _next_run_text(item: CronJobStatus) -> str:
    """``next run`` 行：本地时 + 同一时刻 UTC + 相对剩余；算不出时给原因。"""
    if item.next_run is None:
        return f"n/a ({item.next_run_note or 'unknown'})"
    local = datetime.fromisoformat(item.next_run)
    text = local.strftime("%Y-%m-%d %H:%M local")
    if item.next_run_utc:
        text += f" (= {item.next_run_utc}Z)"
    return f"{text}, {_humanize(item.seconds_until_next)}"


def _humanize(seconds: int | None) -> str:
    """秒 → ``in 2h 05m`` 形态的相对时间（已到期或未给值回退成 ``now``）。"""
    if seconds is None or seconds <= 0:
        return "now"
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"in {days}d {hours}h"
    if hours:
        return f"in {hours}h {minutes:02d}m"
    if minutes:
        return f"in {minutes}m {remainder:02d}s"
    return f"in {remainder}s"
