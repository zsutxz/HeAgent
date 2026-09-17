"""Cron 定时调度测试 — jobs.py、scheduler.py、cron 工具。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from heagent.cron.jobs import CronJob, JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.engine import EngineContainer
from heagent.tools.builtins.cron import (
    configure_cron_tools,
    cron_add,
    cron_list,
    cron_remove,
    reset_cron_tools,
)

if TYPE_CHECKING:
    from pathlib import Path

    from heagent.engine.context import RunContext


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


# ---- CronScheduler.stop 关停硬上界测试（task 挂死兜底，与 MCP __aexit__ 同构）----


class TestCronSchedulerTickPath:
    """tick 路径集成回归（2026-09-17 B1）：store 调用经 to_thread 卸载后，到期 job 仍被
    正常执行且 last_run / one-shot 移除语义不变。"""

    @staticmethod
    def _store_with_job(tmp_path: Path, *, job_id: str, recurring: bool) -> JobStore:
        store = JobStore(str(tmp_path / "jobs.json"))
        store.add(
            CronJob(
                id=job_id,
                prompt="hello",
                cron="* * * * *",
                recurring=recurring,
                created=datetime.now().isoformat(),
            )
        )
        return store

    @pytest.mark.asyncio
    async def test_due_job_executes_and_records_last_run(self, tmp_path: Path) -> None:
        store = self._store_with_job(tmp_path, job_id="j-recurring", recurring=True)
        executed: list[str] = []

        async def runner(prompt: str, run_context: RunContext) -> None:
            executed.append(prompt)

        scheduler = CronScheduler(store, tick_seconds=60, engine=EngineContainer(), job_runner=runner)
        await scheduler._check_and_execute()

        assert executed == ["hello"]
        jobs = store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].last_run is not None

    @pytest.mark.asyncio
    async def test_one_shot_job_removed_after_execution(self, tmp_path: Path) -> None:
        # job_id 与上一测不同：ledger key 含分钟级时间戳且 EngineContainer() 共享默认 ledger
        # 路径，同分钟内重复 id 会被幂等 lease 跳过（避免测试间伪共享）。
        store = self._store_with_job(tmp_path, job_id="j-one-shot", recurring=False)

        async def runner(prompt: str, run_context: RunContext) -> None:
            pass

        scheduler = CronScheduler(store, tick_seconds=60, engine=EngineContainer(), job_runner=runner)
        await scheduler._check_and_execute()

        assert store.list_jobs() == []


class TestCronSchedulerStop:
    """CronScheduler.stop() 硬上界：task 不响应 cancel 时 bounded 放弃，不无限阻塞。"""

    def test_stop_timeout_must_be_positive(self, tmp_path: Path) -> None:
        """stop_timeout<=0 会让 _await_stop 的 wait 立即返回（task 仍 pending）→ 不给 cancel
        任何收尾机会即 ERROR 放弃（与 MCP shutdown_timeout<=0 同构误用）；构造期拒绝。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        with pytest.raises(ValueError):
            CronScheduler(store, stop_timeout=0)
        with pytest.raises(ValueError):
            CronScheduler(store, stop_timeout=-1)

    @pytest.mark.asyncio
    async def test_stop_bounded_when_tick_hangs(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """_tick_loop 卡在不可中断 await（cancel 被吞）时 stop() 仍有硬上界。

        未修：stop() 裸 await self._task 无限阻塞 → 外层 wait_for(2.0) 超时 raise TimeoutError → 失败。
        已修：stop() 在 stop_timeout 后记 ERROR 放弃 → ~stop_timeout 返回。
        """
        store = JobStore(str(tmp_path / "jobs.json"))
        scheduler = CronScheduler(store, tick_seconds=60, stop_timeout=0.05)

        # 模拟 _check_and_execute 挂死且吞 CancelledError（不响应取消）——AgentLoop.run 内不可中断
        # await 的最小复现：except 捕取消后 await 永不返回的 future（asyncio 进入 except/finally 后
        # cancel 信号已被消费，后续 await 不再自动抛 CancelledError → task 不响应取消）。
        hang = asyncio.Event()

        async def hanging_check() -> None:
            try:
                await hang.wait()
            except asyncio.CancelledError:
                await hang.wait()

        scheduler._check_and_execute = hanging_check  # type: ignore[method-assign]
        await scheduler.start()
        await asyncio.sleep(0.05)  # 让 _tick_loop 进入 hanging_check

        caplog.set_level(logging.ERROR)
        await asyncio.wait_for(scheduler.stop(), timeout=2.0)  # 未修则挂死→TimeoutError

        assert any("关停超时" in r.message for r in caplog.records), "挂死时应发出关停超时 ERROR"

    @pytest.mark.asyncio
    async def test_stop_clean_no_error_on_sleep(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """正常关停（task 在 sleep）不被误判超时（零回归：happy path 不受硬上界影响）。

        stop_timeout 给宽裕值；_tick_loop 在 asyncio.sleep 被 cancel 后一个 tick 内 done →
        wait 立即返回、无「关停超时」ERROR。
        """
        store = JobStore(str(tmp_path / "jobs.json"))
        scheduler = CronScheduler(store, tick_seconds=60, stop_timeout=1.0)
        await scheduler.start()
        await asyncio.sleep(0.05)  # 让 _tick_loop 进入 asyncio.sleep(60)

        caplog.set_level(logging.ERROR)
        await scheduler.stop()

        assert scheduler._task is not None
        assert scheduler._task.done()
        assert not any("关停超时" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_stop_timeout_clears_task_and_attaches_callback(self, tmp_path: Path) -> None:
        """AC4: 超时分支清 _task + 挂 _retrieve_task_exception（dream+cron 对称，此为 cron 侧）。"""
        from heagent.cron.scheduler import _retrieve_task_exception

        store = JobStore(str(tmp_path / "jobs.json"))
        scheduler = CronScheduler(store, tick_seconds=60, stop_timeout=0.05)

        async def hanging_check() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.Event().wait()  # 吞取消 → task 不响应

        scheduler._check_and_execute = hanging_check  # type: ignore[method-assign]
        await scheduler.start()
        await asyncio.sleep(0.05)
        orphan = scheduler._task
        await asyncio.wait_for(scheduler.stop(), timeout=2.0)

        # 超时分支：清 _task（仅在 pending 分支发生——clean 路径保留 _task，见上一测试）
        assert scheduler._task is None
        # 孤儿 task 挂了 _retrieve_task_exception done callback（待终态取回异常）
        cb_funcs = [cb[0] if isinstance(cb, tuple) else cb for cb in orphan._callbacks]
        assert _retrieve_task_exception in cb_funcs
        # 清理挂死 task：吞了首 cancel 后再 hang；二次 cancel 经第二 Event（未被 except 保护）→ 终止
        orphan.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await orphan

    @pytest.mark.asyncio
    async def test_retrieve_task_exception_contract(self) -> None:
        """AC4: _retrieve_task_exception 守卫 cancelled + 取非 None 异常（避免 'never retrieved'）。"""
        from heagent.cron.scheduler import _retrieve_task_exception

        # 异常 task：callback 取回（标记 retrieved），不抛
        async def _raise() -> None:
            raise RuntimeError("orphan boom")

        t1 = asyncio.create_task(_raise())
        await asyncio.sleep(0.01)
        _retrieve_task_exception(t1)  # 不抛，标记 retrieved

        # 干净 task：exc 为 None → noop
        t2 = asyncio.create_task(asyncio.sleep(0))
        await asyncio.sleep(0.01)
        _retrieve_task_exception(t2)

        # cancelled task：守卫 return（不调 .exception()，避免 CancelledError）
        t3 = asyncio.create_task(asyncio.Event().wait())
        t3.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t3
        assert t3.cancelled()
        _retrieve_task_exception(t3)  # 守卫：cancelled → return，不抛
