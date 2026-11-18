"""``heagent cron status`` / ``heagent cron list`` 与 cron 执行状态持久化的测试。

钉住四件契约：

1. **状态真源**：``CronScheduler._execute_job`` 在开始 / 成功 / 失败三处写 ``last_status``，
   失败信息 = 「异常类型: 首行」（截断），成功清空上一次的错误；
2. **展示状态派生**：never / unknown（旧格式） / running / success / failed / interrupted；
3. **下次触发时刻**与执行器（``cron_matches``）**逐字段一致**——展示不得与真实触发漂移；
4. **CLI 只读面**：人读输出与 ``--json``、空列表可读、旧 ``jobs.json`` 向后兼容、退出码三档。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from click.testing import CliRunner

from heagent.cli.cron_cmd import cron_cmd, list_cmd, status_cmd
from heagent.cron.expr import cron_matches
from heagent.cron.jobs import CronJob, JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.cron.status import (
    ERROR_MAX_CHARS,
    NEXT_RUN_HORIZON_DAYS,
    RUNNING_STALE_AFTER,
    CronJobState,
    build_status,
    format_failure,
    next_fire,
    parse_utc,
    resolve_state,
)
from heagent.engine import EngineContainer

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from heagent.engine.context import RunContext

# 固定「现在」：本地时 naive（与 CronScheduler / next_fire 同一口径）。
NOW = datetime(2026, 11, 18, 12, 0, 0)


def _iso_utc(moment: datetime) -> str:
    """本地 naive → jobs.json 里的 UTC naive ISO 字符串。"""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _job(**overrides: object) -> CronJob:
    fields: dict[str, object] = {
        "id": "job00001",
        "prompt": "daily report",
        "cron": "0 9 * * *",
        "created": "2026-11-01T00:00:00",
    }
    fields.update(overrides)
    return CronJob(**fields)  # type: ignore[arg-type]


def _write_jobs(path: Path, entries: list[dict[str, object]]) -> Path:
    """直接写原始 JSON——模拟旧版 heagent 或手改的文件（不经 JobStore 序列化）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _deny_open(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    """让 ``path`` 的 ``open`` 抛 ``PermissionError``（模拟权限/IO 不可读，其余路径直通）。

    同时接管 ``builtins.open`` 与 ``io.open``——后者是 ``Path.read_text`` 的实际入口，
    这样「命令自判可读性」与「存储层读文件」两条路都被拒，才等价于真实的权限错误。
    """
    real_open = open
    denied = {str(path)}

    def fake_open(file: object, *args: object, **kwargs: object):
        if str(file) in denied:
            raise PermissionError(13, "Permission denied")
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr("io.open", fake_open)


def _legacy_entry(job_id: str, *, last_run: str | None = None) -> dict[str, object]:
    """旧版 ``jobs.json`` 条目：只有 CronJob 的原始七字段，没有任何执行状态字段。"""
    entry: dict[str, object] = {
        "id": job_id,
        "prompt": f"task {job_id}",
        "cron": "*/5 * * * *",
        "recurring": True,
        "created": "2026-11-01T00:00:00",
        "enabled": True,
    }
    if last_run is not None:
        entry["last_run"] = last_run
    return entry


# ---- 下一次触发时刻 ----


class TestNextFire:
    """``next_fire``：本地时求值、严格晚于 now、与 ``cron_matches`` 语义一致。"""

    def test_every_minute_moves_to_next_minute(self) -> None:
        now = datetime(2026, 11, 18, 10, 0, 30)
        assert next_fire("* * * * *", now=now) == datetime(2026, 11, 18, 10, 1, 0)

    def test_daily_schedule_rolls_to_tomorrow(self) -> None:
        now = datetime(2026, 11, 18, 10, 0, 0)
        assert next_fire("0 9 * * *", now=now) == datetime(2026, 11, 19, 9, 0, 0)

    def test_current_minute_is_excluded(self) -> None:
        # now 正好落在触发分钟（09:00:00）⇒ 下一次必须是次日，不是自己
        now = datetime(2026, 11, 18, 9, 0, 0)
        assert next_fire("0 9 * * *", now=now) == datetime(2026, 11, 19, 9, 0, 0)

    def test_step_expression(self) -> None:
        now = datetime(2026, 11, 18, 10, 7, 0)
        assert next_fire("*/15 * * * *", now=now) == datetime(2026, 11, 18, 10, 15, 0)

    def test_weekday_field_uses_sunday_zero(self) -> None:
        # 2026-11-18 是周三；周日 09:00 ⇒ 2026-11-22
        now = datetime(2026, 11, 18, 12, 0, 0)
        expected = datetime(2026, 11, 22, 9, 0, 0)
        assert next_fire("0 9 * * 0", now=now) == expected
        assert next_fire("0 9 * * 7", now=now) == expected  # 7 是周日的别名

    def test_no_fire_time_within_horizon(self) -> None:
        # 2 月 30 日永不存在 ⇒ 窗口内无匹配（走完整个上界也不能误报一个时刻）
        assert next_fire("0 0 30 2 *", now=datetime(2026, 11, 18, 12, 0, 0)) is None

    def test_horizon_is_bounded(self) -> None:
        # 上界 0 天 ⇒ 连明天都不看，必须回 None 而不是无限搜
        assert next_fire("0 9 * * *", now=NOW, horizon_days=0) is None
        assert NEXT_RUN_HORIZON_DAYS > 0

    def test_invalid_expression_raises(self) -> None:
        for expr in ("0 9 * *", "99 * * * *", "0 9 * * * *", "0 9 L * *"):
            try:
                next_fire(expr, now=NOW)
            except ValueError:
                continue
            raise AssertionError(f"非法表达式未抛 ValueError: {expr!r}")

    @staticmethod
    def _brute_force(expr: str, start: datetime, *, limit_minutes: int) -> datetime | None:
        """逐分钟暴力扫描（执行器语义的唯一判据）。"""
        cursor = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(limit_minutes):
            if cron_matches(expr, cursor):
                return cursor
            cursor += timedelta(minutes=1)
        return None

    def test_matches_executor_semantics(self) -> None:
        """与执行器逐分钟暴力扫描对拍——展示的「下次触发」必须等于真实会触发的时刻。"""
        cases = (
            ("*/15 * * * *", 180),
            ("0 9 * * *", 2880),
            ("30 2 * * 1", 20_160),
            ("5-10 * * * *", 120),
            ("0 0 1 * *", 24 * 60 * 40),
        )
        for expr, limit in cases:
            expected = self._brute_force(expr, NOW, limit_minutes=limit)
            assert next_fire(expr, now=NOW) == expected, expr


# ---- 展示状态派生 ----


class TestStateResolution:
    def test_never_run(self) -> None:
        assert build_status(_job(), now=NOW).status is CronJobState.NEVER

    def test_success(self) -> None:
        job = _job(last_status="success", last_run=_iso_utc(NOW - timedelta(hours=1)))
        assert build_status(job, now=NOW).status is CronJobState.SUCCESS

    def test_failed(self) -> None:
        job = _job(last_status="failed", last_run=_iso_utc(NOW - timedelta(hours=1)), last_error="RuntimeError: boom")
        status = build_status(job, now=NOW)
        assert status.status is CronJobState.FAILED
        assert status.last_error == "RuntimeError: boom"

    def test_legacy_entry_without_status_is_unknown(self) -> None:
        """旧版 jobs.json 只有 last_run、没有 last_status ⇒ unknown（有记录但没结果）。"""
        job = _job(last_run=_iso_utc(NOW - timedelta(hours=2)))
        assert build_status(job, now=NOW).status is CronJobState.UNKNOWN

    def test_unrecognised_status_value_degrades(self) -> None:
        """手改/未来版本写入未知取值 ⇒ 降级 unknown，不得当成损坏数据。"""
        job = _job(last_status="whatever", last_run=_iso_utc(NOW - timedelta(hours=2)))
        assert build_status(job, now=NOW).status is CronJobState.UNKNOWN

    def test_running_is_live(self) -> None:
        job = _job(last_status="running", last_started=_iso_utc(NOW - timedelta(minutes=3)))
        assert build_status(job, now=NOW).status is CronJobState.RUNNING

    def test_running_stale_becomes_interrupted(self) -> None:
        stale = NOW - RUNNING_STALE_AFTER - timedelta(minutes=1)
        job = _job(last_status="running", last_started=_iso_utc(stale))
        assert build_status(job, now=NOW).status is CronJobState.INTERRUPTED

    def test_running_without_timestamps_stays_running(self) -> None:
        assert resolve_state("running", last_run=None, last_started=None, utc_now=NOW) is CronJobState.RUNNING

    def test_next_run_and_note(self) -> None:
        status = build_status(_job(cron="0 9 * * *"), now=NOW)
        assert status.next_run == "2026-11-19T09:00:00"
        assert status.next_run_utc == _iso_utc(datetime(2026, 11, 19, 9, 0, 0))
        assert status.seconds_until_next == int((datetime(2026, 11, 19, 9, 0, 0) - NOW).total_seconds())
        assert status.next_run_note is None

    def test_invalid_cron_is_reported_not_raised(self) -> None:
        status = build_status(_job(cron="0 9 * *"), now=NOW)
        assert status.next_run is None
        assert status.next_run_note is not None
        assert status.next_run_note.startswith("invalid cron expression")

    def test_no_fire_time_is_reported(self) -> None:
        status = build_status(_job(cron="0 0 30 2 *"), now=NOW)
        assert status.next_run is None
        assert status.next_run_note is not None
        assert "no fire time" in status.next_run_note

    def test_parse_utc_rejects_garbage(self) -> None:
        assert parse_utc("not-a-time") is None
        assert parse_utc(None) is None
        assert parse_utc("2026-11-18T01:02:03") == datetime(2026, 11, 18, 1, 2, 3)


class TestFormatFailure:
    def test_keeps_type_and_first_line(self) -> None:
        assert format_failure(RuntimeError("boom\nsecond line")) == "RuntimeError: boom"

    def test_empty_message_keeps_type_only(self) -> None:
        assert format_failure(RuntimeError("")) == "RuntimeError"

    def test_truncates_long_message(self) -> None:
        text = format_failure(RuntimeError("x" * 500))
        assert len(text) == ERROR_MAX_CHARS
        assert text.endswith("…")


# ---- 调度器持久化执行结果 ----


def _scheduler(tmp_path: Path, store: JobStore, runner: object) -> CronScheduler:
    """独立 ledger 的调度器（engine 落在 tmp_path，测试不写仓库工作区）。"""
    engine = EngineContainer.default(workspace_root=str(tmp_path))
    return CronScheduler(store, engine=engine, job_runner=runner)  # type: ignore[arg-type]


class TestSchedulerPersistsOutcome:
    """``_execute_job`` 三处写入：running → success / failed。"""

    async def test_success_records_status_and_clears_previous_error(self, tmp_path: Path) -> None:
        store = JobStore(str(tmp_path / "jobs.json"))
        job = store.create_job("say hi", "* * * * *")
        store.add(job)
        store.update(job.id, last_status="failed", last_error="RuntimeError: old boom")

        async def runner(prompt: str, run_context: RunContext) -> None:
            return None

        await _scheduler(tmp_path, store, runner)._execute_job(job, now=datetime(2026, 11, 18, 10, 15, 0))

        saved = store.get(job.id)
        assert saved is not None
        assert saved.last_status == "success"
        assert saved.last_success is not None
        assert saved.last_run == saved.last_success
        assert saved.last_error is None  # 成功即清空「最近一次失败」

    async def test_failure_records_error_with_type_and_first_line(self, tmp_path: Path) -> None:
        store = JobStore(str(tmp_path / "jobs.json"))
        job = store.create_job("boom", "* * * * *")
        store.add(job)

        async def runner(prompt: str, run_context: RunContext) -> None:
            raise RuntimeError("boom\nstack line that must not be stored")

        await _scheduler(tmp_path, store, runner)._execute_job(job, now=datetime(2026, 11, 18, 10, 16, 0))

        saved = store.get(job.id)
        assert saved is not None
        assert saved.last_status == "failed"
        assert saved.last_error == "RuntimeError: boom"
        assert saved.last_run is not None
        assert saved.last_success is None

    async def test_running_marker_is_visible_during_execution(self, tmp_path: Path) -> None:
        """执行中 jobs.json 必须是 running + last_started（崩溃后 status 才有依据判 interrupted）。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        job = store.create_job("slow", "* * * * *")
        store.add(job)
        seen: list[CronJob | None] = []

        async def runner(prompt: str, run_context: RunContext) -> None:
            seen.append(store.get(job.id))

        await _scheduler(tmp_path, store, runner)._execute_job(job, now=datetime(2026, 11, 18, 10, 17, 0))

        assert len(seen) == 1
        in_flight = seen[0]
        assert in_flight is not None
        assert in_flight.last_status == "running"
        assert in_flight.last_started is not None
        assert in_flight.last_run is None  # last_run 只在执行**结束**时写

    async def test_legacy_record_roundtrip_keeps_extra_free_json(self, tmp_path: Path) -> None:
        """旧格式文件经调度器写状态后仍可被读回（旧条目没有的字段补默认值，不报错）。"""
        path = _write_jobs(tmp_path / "jobs.json", [_legacy_entry("legacy01")])
        store = JobStore(str(path))

        async def runner(prompt: str, run_context: RunContext) -> None:
            return None

        jobs = store.list_jobs()
        assert len(jobs) == 1
        await _scheduler(tmp_path, store, runner)._execute_job(jobs[0], now=datetime(2026, 11, 18, 10, 18, 0))

        saved = store.get("legacy01")
        assert saved is not None
        assert saved.last_status == "success"


# ---- CLI ----


class TestCronStatusCli:
    def _three_jobs(self, tmp_path: Path) -> Path:
        """成功 / 失败 / 从未执行 各一条（写原始 JSON，顺带覆盖字段组合）。"""
        return _write_jobs(
            tmp_path / "cron" / "jobs.json",
            [
                {
                    "id": "ok000001",
                    "prompt": "ok job",
                    "cron": "0 9 * * *",
                    "recurring": True,
                    "created": "2026-11-01T00:00:00",
                    "enabled": True,
                    "last_run": "2026-11-18T01:00:00",
                    "last_started": "2026-11-18T01:00:00",
                    "last_status": "success",
                    "last_success": "2026-11-18T01:00:00",
                },
                {
                    "id": "bad00001",
                    "prompt": "failing job",
                    "cron": "*/5 * * * *",
                    "recurring": True,
                    "created": "2026-11-01T00:00:00",
                    "enabled": True,
                    "last_run": "2026-11-18T02:30:00",
                    "last_started": "2026-11-18T02:29:00",
                    "last_status": "failed",
                    "last_error": "RuntimeError: boom",
                },
                {
                    "id": "new00001",
                    "prompt": "never run",
                    "cron": "0 3 * * *",
                    "recurring": False,
                    "created": "2026-11-17T00:00:00",
                    "enabled": False,
                },
            ],
        )

    def test_status_human_report_covers_all_three_states(self, tmp_path: Path) -> None:
        path = self._three_jobs(tmp_path)
        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path)])

        assert result.exit_code == 1  # 有一条 failed ⇒ 非零（脚本可据此告警）
        out = result.output
        assert "3 job(s): 1 never, 1 success, 1 failed" in out
        assert "status:    success" in out
        assert "status:    failed" in out
        assert "error:     RuntimeError: boom" in out
        assert "status:    never" in out
        assert "next run:" in out
        assert "local time" in out and "UTC" in out  # 时区口径必须打印出来
        assert "[job ok000001]" in out and "[job bad00001]" in out and "[job new00001]" in out

    def test_status_renders_lasting_timestamps_with_explicit_zones(self, tmp_path: Path) -> None:
        path = self._three_jobs(tmp_path)
        out = CliRunner().invoke(status_cmd, ["--jobs-file", str(path)]).output
        assert "2026-11-18T01:00:00Z (= " in out  # UTC 原值带 Z
        assert " local)" in out  # 同一时刻的本地换算

    def test_list_is_compact_one_line_per_job(self, tmp_path: Path) -> None:
        path = self._three_jobs(tmp_path)
        result = CliRunner().invoke(list_cmd, ["--jobs-file", str(path)])

        assert result.exit_code == 1
        job_lines = [line for line in result.output.splitlines() if line.startswith("[job ")]
        assert len(job_lines) == 3
        assert all("status:" not in line for line in job_lines)  # list 不含逐字段明细
        assert "success" in job_lines[0]
        assert "failed" in job_lines[1]
        assert "never" in job_lines[2]
        assert all("next " in line for line in job_lines)  # 下次执行时间必须在这一行里

    def test_json_output_is_a_parseable_array(self, tmp_path: Path) -> None:
        path = self._three_jobs(tmp_path)
        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path), "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert isinstance(payload, list)
        assert [item["id"] for item in payload] == ["ok000001", "bad00001", "new00001"]
        assert [item["status"] for item in payload] == ["success", "failed", "never"]
        failed = payload[1]
        assert failed["last_error"] == "RuntimeError: boom"
        assert failed["next_run"] is not None
        assert failed["next_run_utc"] is not None
        assert failed["seconds_until_next"] is not None
        assert payload[2]["next_run_note"] is None

    def test_group_level_registration_works(self, tmp_path: Path) -> None:
        path = self._three_jobs(tmp_path)
        result = CliRunner().invoke(cron_cmd, ["status", "--jobs-file", str(path), "--json"])
        assert result.exit_code == 1
        assert len(json.loads(result.output)) == 3

    def test_empty_store_is_readable_not_blank(self, tmp_path: Path) -> None:
        path = tmp_path / "cron" / "jobs.json"
        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path)])

        assert result.exit_code == 0
        assert "no jobs scheduled" in result.output
        assert str(path) in result.output

    def test_empty_store_json_is_an_empty_array(self, tmp_path: Path) -> None:
        path = tmp_path / "cron" / "jobs.json"
        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path), "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_legacy_jobs_file_is_backward_compatible(self, tmp_path: Path) -> None:
        """旧格式（无任何状态字段）：有 last_run 的报 unknown、没跑过的报 never，退出码 0。"""
        path = _write_jobs(
            tmp_path / "jobs.json",
            [_legacy_entry("legacy01", last_run="2026-11-18T01:00:00"), _legacy_entry("legacy02")],
        )
        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path), "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert [item["status"] for item in payload] == ["unknown", "never"]
        assert payload[0]["last_error"] is None
        assert payload[1]["last_success"] is None

    def test_corrupted_file_exits_two(self, tmp_path: Path) -> None:
        path = tmp_path / "cron" / "jobs.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ this is not json", encoding="utf-8")

        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path)])

        assert result.exit_code == 2
        assert "corrupted" in result.output

    def test_not_a_list_json_reports_error_envelope(self, tmp_path: Path) -> None:
        """顶层不是列表 ⇒ 没有任何可报告内容，`--json` 给错误信封而不是空数组（不能装成功）。"""
        path = tmp_path / "cron" / "jobs.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"jobs": []}', encoding="utf-8")

        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path), "--json"])

        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["jobs_file"] == str(path)
        assert "corrupted" in payload["error"]

    def test_non_object_entries_count_as_corruption(self, tmp_path: Path) -> None:
        """列表元素不是对象 ⇒ 逐条跳过并计数（曾经 TypeError 直接把读状态打崩）。"""
        path = tmp_path / "cron" / "jobs.json"
        path.parent.mkdir(parents=True)
        path.write_text("[1, 2, 3]", encoding="utf-8")

        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path)])

        assert result.exit_code == 0
        assert "3 job(s) skipped" in result.output
        assert "no jobs scheduled" in result.output

    def test_partially_invalid_entries_are_warned_but_listed(self, tmp_path: Path) -> None:
        """一条坏条目被跳过时给出计数提示，其余 job 照常展示（不静默吞）。"""
        path = _write_jobs(
            tmp_path / "jobs.json",
            [_legacy_entry("legacy01"), {"id": "broken", "prompt": "no cron field"}],
        )
        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path)])

        assert result.exit_code == 0
        assert "1 job(s) skipped" in result.output
        assert "[job legacy01]" in result.output

    def test_json_warns_on_skipped_entries_on_stderr(self, tmp_path: Path) -> None:
        """``--json`` 也要报跳过计数：告警走 stderr，stdout 仍是纯净 JSON 数组。"""
        path = _write_jobs(
            tmp_path / "jobs.json",
            [_legacy_entry("legacy01"), {"id": "broken", "prompt": "no cron field"}],
        )
        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path), "--json"])

        assert result.exit_code == 0
        assert [item["id"] for item in json.loads(result.stdout)] == ["legacy01"]
        assert "1 job(s) skipped" in result.stderr
        assert "skipped" not in result.stdout

    def test_unreadable_file_exits_two_with_exception_type(self, tmp_path: Path, monkeypatch) -> None:
        """文件存在但打不开（权限/IO）⇒ 退出码 2 且消息带异常类型（不得装成「没有任务」）。"""
        path = _write_jobs(tmp_path / "jobs.json", [_legacy_entry("legacy01")])
        _deny_open(monkeypatch, path)

        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path)])

        assert result.exit_code == 2
        assert "unreadable" in result.stderr
        assert "PermissionError" in result.stderr
        assert "no jobs scheduled" not in result.output

    def test_unreadable_file_json_reports_error_envelope(self, tmp_path: Path, monkeypatch) -> None:
        """``--json`` 不可读时给错误信封（与 corrupted 同形），不回空数组装成功。"""
        path = _write_jobs(tmp_path / "jobs.json", [_legacy_entry("legacy01")])
        _deny_open(monkeypatch, path)

        result = CliRunner().invoke(status_cmd, ["--jobs-file", str(path), "--json"])

        assert result.exit_code == 2
        payload = json.loads(result.stdout)
        assert payload["jobs_file"] == str(path)
        assert "unreadable" in payload["error"]
        assert "PermissionError" in payload["error"]

    def test_default_jobs_path_that_is_a_directory_exits_two(self, tmp_path: Path, monkeypatch) -> None:
        """默认路径落在目录上（open 抛 IsADirectoryError）同样不可读——click 的 dir_okay 拦不到默认路径。"""
        (tmp_path / ".heagent" / "cron" / "jobs.json").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(status_cmd, [])

        assert result.exit_code == 2
        assert "unreadable" in result.stderr
        assert "IsADirectoryError" in result.stderr
        assert "no jobs scheduled" not in result.output

    def test_command_is_read_only(self, tmp_path: Path) -> None:
        """查状态不得改写 jobs.json（只读契约）。"""
        path = self._three_jobs(tmp_path)
        before = path.read_bytes()
        CliRunner().invoke(status_cmd, ["--jobs-file", str(path)])
        CliRunner().invoke(list_cmd, ["--jobs-file", str(path)])
        CliRunner().invoke(status_cmd, ["--jobs-file", str(path), "--json"])
        assert path.read_bytes() == before
