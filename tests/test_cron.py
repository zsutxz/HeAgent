"""Cron 定时调度测试 — jobs.py、scheduler.py、cron 工具。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from heagent.cron.jobs import JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.tools.builtins.cron import (
    configure_cron_tools,
    cron_add,
    cron_list,
    cron_remove,
    reset_cron_tools,
)

# ---- JobStore 测试 ----


class TestJobStore:
    """JobStore CRUD 持久化测试。"""

    def test_empty_store(self, tmp_path: Path) -> None:
        """空存储返回空列表。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        assert store.list_jobs() == []

    def test_add_and_list(self, tmp_path: Path) -> None:
        """添加任务后能列出。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        job = store.create_job("test task", "*/5 * * * *")
        store.add(job)
        jobs = store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].prompt == "test task"
        assert jobs[0].cron == "*/5 * * * *"

    def test_get_by_id(self, tmp_path: Path) -> None:
        """按 ID 查找任务。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        job = store.create_job("find me", "0 9 * * *")
        store.add(job)
        found = store.get(job.id)
        assert found is not None
        assert found.prompt == "find me"

    def test_get_not_found(self, tmp_path: Path) -> None:
        """查找不存在的 ID 返回 None。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        assert store.get("nonexistent") is None

    def test_remove(self, tmp_path: Path) -> None:
        """删除任务。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        job = store.create_job("to remove", "* * * * *")
        store.add(job)
        assert store.remove(job.id) is True
        assert store.list_jobs() == []

    def test_remove_not_found(self, tmp_path: Path) -> None:
        """删除不存在的任务返回 False。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        assert store.remove("ghost") is False

    def test_update(self, tmp_path: Path) -> None:
        """更新任务字段。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        job = store.create_job("original", "* * * * *")
        store.add(job)
        store.update(job.id, last_run="2026-01-01T00:00:00", enabled=False)
        updated = store.get(job.id)
        assert updated is not None
        assert updated.last_run == "2026-01-01T00:00:00"
        assert updated.enabled is False

    def test_persistence(self, tmp_path: Path) -> None:
        """数据持久化到 JSON 文件。"""
        path = str(tmp_path / "jobs.json")
        store1 = JobStore(path)
        job = store1.create_job("persist test", "0 * * * *")
        store1.add(job)

        # 新实例加载同一文件
        store2 = JobStore(path)
        assert len(store2.list_jobs()) == 1
        assert store2.list_jobs()[0].prompt == "persist test"


# ---- Cron 表达式解析器测试 ----


class TestCronParser:
    """CronScheduler._matches 测试。"""

    def test_star_matches_anything(self) -> None:
        """* 匹配任意时间。"""
        dt = datetime(2026, 6, 8, 14, 30, 0)  # Mon
        assert CronScheduler._matches("* * * * *", dt) is True

    def test_specific_minute(self) -> None:
        """具体分钟值匹配。"""
        dt = datetime(2026, 6, 8, 14, 30, 0)
        assert CronScheduler._matches("30 * * * *", dt) is True
        assert CronScheduler._matches("31 * * * *", dt) is False

    def test_step(self) -> None:
        """*/N 每隔 N 匹配。"""
        dt = datetime(2026, 6, 8, 14, 30, 0)
        assert CronScheduler._matches("*/5 * * * *", dt) is True  # 30 % 5 == 0
        assert CronScheduler._matches("*/7 * * * *", dt) is False  # 30 % 7 != 0

    def test_comma_separated(self) -> None:
        """逗号分隔匹配。"""
        dt = datetime(2026, 6, 8, 9, 0, 0)
        assert CronScheduler._matches("0 9 * * *", dt) is True
        assert CronScheduler._matches("0 8,9,10 * * *", dt) is True
        assert CronScheduler._matches("0 7,8,10 * * *", dt) is False

    def test_wrong_field_count(self) -> None:
        """字段数量不对返回 False。"""
        dt = datetime(2026, 6, 8, 14, 30, 0)
        assert CronScheduler._matches("* * *", dt) is False

    def test_all_fields_combined(self) -> None:
        """所有字段组合匹配。"""
        dt = datetime(2026, 6, 8, 14, 30, 0)  # Mon = weekday 1 in cron
        assert CronScheduler._matches("30 14 8 6 *", dt) is True
        assert CronScheduler._matches("30 14 8 6 1", dt) is True  # cron Mon=1
        assert CronScheduler._matches("30 14 8 6 0", dt) is False  # cron Sun=0


# ---- Cron 工具测试 ----


class TestCronTools:
    """cron_add / cron_list / cron_remove 工具测试。"""

    def setup_method(self) -> None:
        """每个测试前重置工具模块。"""
        reset_cron_tools()

    def teardown_method(self) -> None:
        """每个测试后清理。"""
        reset_cron_tools()

    @pytest.mark.asyncio
    async def test_add_and_list(self, tmp_path: Path) -> None:
        """创建并列出任务。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        configure_cron_tools(store)

        result = await cron_add("daily report", "0 9 * * *")
        assert "created" in result

        result = await cron_list()
        assert "daily report" in result

    @pytest.mark.asyncio
    async def test_remove(self, tmp_path: Path) -> None:
        """删除任务。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        configure_cron_tools(store)

        await cron_add("to delete", "*/5 * * * *")
        jobs = store.list_jobs()
        job_id = jobs[0].id

        result = await cron_remove(job_id)
        assert "removed" in result
        assert store.list_jobs() == []

    @pytest.mark.asyncio
    async def test_no_store_error(self) -> None:
        """未配置时返回错误。"""
        result = await cron_add("test", "* * * * *")
        assert "Error" in result

        result = await cron_list()
        assert "Error" in result
