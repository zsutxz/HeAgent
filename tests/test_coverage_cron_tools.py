"""补 tools/builtins/cron.py 未覆盖行：缺参数 TypeError、空列表、无 store 错误、
非法 schedule 校验、cron_remove 未找到 job 等路径。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

import pytest

from heagent.cron.jobs import JobStore
from heagent.tools.builtins.cron import (
    configure_cron_tools,
    cron_add,
    cron_list,
    cron_remove,
    reset_cron_tools,
)


@pytest.fixture(autouse=True)
def _reset_cron_tools() -> Iterator[None]:
    """原 6 个用例类各自的 setup/teardown_method 收敛为模块级 autouse（前后归零）。"""
    reset_cron_tools()
    yield
    reset_cron_tools()


@pytest.fixture()
def cron_store(tmp_path: Path) -> JobStore:
    """已接线到 handler 的空 JobStore（原 7 处「JobStore + configure」两行样板收敛）。"""
    store = JobStore(str(tmp_path / "jobs.json"))
    configure_cron_tools(store)
    return store


class TestCronToolsMissingArgs:
    """cron_add / cron_remove 缺必填参数 → TypeError。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invoke",
        [
            pytest.param(lambda: cron_add(), id="cron_add-no-args"),
            pytest.param(lambda: cron_add(schedule="0 9 * * *"), id="cron_add-missing-prompt"),
            pytest.param(lambda: cron_add("test only"), id="cron_add-missing-schedule"),
            pytest.param(lambda: cron_remove(), id="cron_remove-no-args"),
        ],
    )
    async def test_missing_required_args_raises_type_error(self, invoke: Callable[[], Awaitable[str]]) -> None:
        """缺必填参数 ⇒ TypeError（missing.*required）——四个调用形态共用同一判据。"""
        with pytest.raises(TypeError, match="missing.*required"):
            await invoke()


@pytest.mark.asyncio
async def test_cron_remove_no_store() -> None:
    """cron_remove 在 store 未配置时返回 Error（覆盖 cron_remove 的 store is None 分支）。"""
    result = await cron_remove("any-job-id")
    assert "Error" in result
    assert "not configured" in result


@pytest.mark.asyncio
async def test_cron_list_empty(cron_store: JobStore) -> None:
    """store 已配置但无 job 时返回 'No cron jobs scheduled.'"""
    result = await cron_list()
    assert result == "No cron jobs scheduled."


@pytest.mark.asyncio
async def test_cron_remove_not_found(cron_store: JobStore) -> None:
    """store 已配置但 job_id 不存在时返回 'not found' Error。"""
    result = await cron_remove("nonexistent-job-id")
    assert "Error" in result
    assert "not found" in result


class TestCronAddInvalidSchedule:
    """cron_add 非法 schedule → _validate_schedule 校验。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("schedule", "fragments"),
        [
            pytest.param("0 9 *", ("expected 5 fields",), id="wrong-field-count"),
            pytest.param("* * *", ("expected 5 fields", "got 3"), id="only-3-fields"),
            pytest.param("abc * * * *", ("Invalid cron field",), id="alpha-field"),
            pytest.param("a-b * * * *", ("Invalid cron field",), id="alpha-range"),
            # V2 能力对齐回归锚：步进语义与运行期 _parse_field 同判（沿革见 git log V2 周期）。
            pytest.param("5/10 * * * *", ("Invalid cron field",), id="value-with-step"),
            pytest.param("*/0 * * * *", ("Invalid cron field",), id="zero-step"),
        ],
    )
    async def test_rejected_schedules(self, cron_store: JobStore, schedule: str, fragments: tuple[str, ...]) -> None:
        """非法 schedule ⇒ 'Error' + 逐片段断言（V2 锚点语义由 id 与表内注释承载）。"""
        result = await cron_add("test", schedule)
        assert "Error" in result
        for fragment in fragments:
            assert fragment in result

    @pytest.mark.asyncio
    async def test_range_with_step_is_accepted(self, cron_store: JobStore) -> None:
        """范围+步进（1-30/10）运行期解析器支持 ⇒ 校验层必须放行（V2 能力对齐，回归锚）。"""
        result = await cron_add("test", "1-30/10 * * * *")
        assert "Cron job created" in result
