"""补 tools/builtins/cron.py 未覆盖行：缺参数 TypeError、空列表、无 store 错误、
非法 schedule 校验、cron_remove 未找到 job 等路径。"""

from __future__ import annotations

import pytest

from heagent.cron.jobs import JobStore
from heagent.tools.builtins.cron import (
    configure_cron_tools,
    cron_add,
    cron_list,
    cron_remove,
    reset_cron_tools,
)


class TestCronToolsMissingArgs:
    """cron_add / cron_remove 缺参数 → TypeError。"""

    def setup_method(self) -> None:
        reset_cron_tools()

    def teardown_method(self) -> None:
        reset_cron_tools()

    @pytest.mark.asyncio
    async def test_cron_add_no_args(self) -> None:
        """cron_add() 无参数 → TypeError（missing prompt + schedule）。"""
        with pytest.raises(TypeError, match="missing.*required"):
            await cron_add()  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_cron_add_missing_prompt(self) -> None:
        """cron_add(schedule=...) 缺 prompt → TypeError。"""
        with pytest.raises(TypeError, match="missing.*required"):
            await cron_add(schedule="0 9 * * *")  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_cron_add_missing_schedule(self) -> None:
        """cron_add(prompt=...) 缺 schedule → TypeError。"""
        with pytest.raises(TypeError, match="missing.*required"):
            await cron_add("test only")  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_cron_remove_no_args(self) -> None:
        """cron_remove() 无参数 → TypeError（missing job_id）。"""
        with pytest.raises(TypeError, match="missing.*required"):
            await cron_remove()  # type: ignore[call-arg]


class TestCronToolsNoStore:
    """handler 无 scheduler（store=None）错误路径。"""

    def setup_method(self) -> None:
        reset_cron_tools()

    def teardown_method(self) -> None:
        reset_cron_tools()

    @pytest.mark.asyncio
    async def test_cron_remove_no_store(self) -> None:
        """cron_remove 在 store 未配置时返回 Error（覆盖 cron_remove 的 store is None 分支）。"""
        result = await cron_remove("any-job-id")
        assert "Error" in result
        assert "not configured" in result


class TestCronListEmpty:
    """cron_list 空列表 → 'No cron jobs scheduled.'"""

    def setup_method(self) -> None:
        reset_cron_tools()

    def teardown_method(self) -> None:
        reset_cron_tools()

    @pytest.mark.asyncio
    async def test_cron_list_empty(self, tmp_path: pytest.TempPathFactory) -> None:
        """store 已配置但无 job 时返回 'No cron jobs scheduled.'"""
        store = JobStore(str(tmp_path / "jobs.json"))
        configure_cron_tools(store)
        result = await cron_list()
        assert result == "No cron jobs scheduled."


class TestCronRemoveNotFound:
    """cron_remove job 不存在 → Error 返回。"""

    def setup_method(self) -> None:
        reset_cron_tools()

    def teardown_method(self) -> None:
        reset_cron_tools()

    @pytest.mark.asyncio
    async def test_cron_remove_not_found(self, tmp_path: pytest.TempPathFactory) -> None:
        """store 已配置但 job_id 不存在时返回 'not found' Error。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        configure_cron_tools(store)
        result = await cron_remove("nonexistent-job-id")
        assert "Error" in result
        assert "not found" in result


class TestCronAddInvalidSchedule:
    """cron_add 非法 schedule → _validate_schedule 返回校验错误。"""

    def setup_method(self) -> None:
        reset_cron_tools()

    def teardown_method(self) -> None:
        reset_cron_tools()

    @pytest.mark.asyncio
    async def test_cron_add_schedule_wrong_field_count(self, tmp_path: pytest.TempPathFactory) -> None:
        """schedule 字段数 ≠ 5 → 校验错误。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        configure_cron_tools(store)
        result = await cron_add("test", "0 9 *")  # 4 字段
        assert "Error" in result
        assert "expected 5 fields" in result

    @pytest.mark.asyncio
    async def test_cron_add_schedule_only_3_fields(self, tmp_path: pytest.TempPathFactory) -> None:
        """schedule 只有 3 字段 → 校验错误。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        configure_cron_tools(store)
        result = await cron_add("test", "* * *")
        assert "Error" in result
        assert "expected 5 fields" in result
        assert "got 3" in result

    @pytest.mark.asyncio
    async def test_cron_add_schedule_invalid_char(self, tmp_path: pytest.TempPathFactory) -> None:
        """schedule 含非法字符（字母）→ 校验错误。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        configure_cron_tools(store)
        result = await cron_add("test", "abc * * * *")
        assert "Error" in result
        assert "Invalid cron field" in result

    @pytest.mark.asyncio
    async def test_cron_add_schedule_invalid_range(self, tmp_path: pytest.TempPathFactory) -> None:
        """schedule range 含非数字（a-b）→ 校验错误。"""
        store = JobStore(str(tmp_path / "jobs.json"))
        configure_cron_tools(store)
        result = await cron_add("test", "a-b * * * *")
        assert "Error" in result
        assert "Invalid cron field" in result
