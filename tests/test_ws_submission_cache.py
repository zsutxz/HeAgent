"""WS 提交幂等窗口的直接判据（Epic 77 三审 R2 补）。

适配器侧（`tests/test_ws_project_adapter.py`）只验「接线后的六种结果」；本文件钉住窗口自己的
四条语义边界——它们都不可能从适配器用例反推出来：

- **过期只清已完成项**：在途项不因 TTL 被踢（踢掉 = 允许同键第二次真提交，合流静默失效）；
- **TTL 从提交开始计时**：完成后 60s 的重放窗口是真的「从提交那一刻算起」；
- **容量满时优先淘汰已完成项**：256 条上限先牺牲历史重放能力，不牺牲在途合流；
- **全是在途才退化为最旧一条**：内存有界优先于合流，属显式边界（模块 docstring 已写明）。

`_clock` 是实例属性（`time.monotonic`），用例直接替换它来推进单调时钟——不 sleep、不依赖真实时间。
"""

from __future__ import annotations

import asyncio

import pytest

from heagent.cli.ws_submission_cache import SubmissionCache
from heagent.network.ws_protocol import RunStatus, SubmittedRun

_KEY = ("p1234abc", "req-1")


def _result(run_id: str = "run-0001") -> SubmittedRun:
    return SubmittedRun(run_id=run_id, status=RunStatus.RUNNING)


async def _cache(**kwargs: float | int) -> tuple[SubmissionCache, list[float]]:
    """建一个用可控单调时钟的窗口；返回 `(cache, clock)`，`clock[0]` 即当前时刻。"""
    cache = SubmissionCache(**kwargs)  # type: ignore[arg-type]
    now = [1000.0]
    cache._clock = lambda: now[0]  # type: ignore[attr-defined] - 判据要控制单调时钟
    return cache, now


@pytest.mark.asyncio
async def test_expired_in_flight_entry_is_never_evicted() -> None:
    """在途项跨过 TTL 仍是同一个 ``Future``：同键第二次调用只能合流，不能变成第二次真提交。"""
    cache, now = await _cache()

    future, owner = cache.reserve(_KEY)
    assert owner
    now[0] += 61.0

    same, owner_again = cache.reserve(_KEY)

    assert owner_again is False
    assert same is future


@pytest.mark.asyncio
async def test_completed_entry_expires_after_the_ttl() -> None:
    """已完成项过期后同键重新成为 owner：TTL 是重放窗口，不是永久去重。"""
    cache, now = await _cache()

    future, _ = cache.reserve(_KEY)
    future.set_result(_result())
    now[0] += 59.0
    replay, owner_in_window = cache.reserve(_KEY)
    assert owner_in_window is False and replay is future

    now[0] += 2.0
    fresh, owner_after_window = cache.reserve(_KEY)

    assert owner_after_window is True
    assert fresh is not future


@pytest.mark.asyncio
async def test_capacity_prefers_evicting_completed_entries() -> None:
    """容量满时先牺牲已完成项：在途合流不被历史重放能力挤掉。"""
    cache, _ = await _cache(max_entries=2)

    done_future, _ = cache.reserve(("p1234abc", "old"))
    done_future.set_result(_result("run-old"))
    in_flight, _ = cache.reserve(("p1234abc", "live"))

    cache.reserve(("p1234abc", "new"))

    assert cache.reserve(("p1234abc", "live"))[0] is in_flight  # 在途项还在
    assert cache.reserve(("p1234abc", "old"))[1] is True  # 已完成项已被淘汰


@pytest.mark.asyncio
async def test_capacity_falls_back_to_the_oldest_in_flight_entry() -> None:
    """全是在途时按插入序淘汰最旧一条：内存有界优先于合流（显式边界，不是漏写）。"""
    cache, _ = await _cache(max_entries=2)

    cache.reserve(("p1234abc", "first"))
    second, _ = cache.reserve(("p1234abc", "second"))

    cache.reserve(("p1234abc", "third"))

    # 先查「后一条仍在」（查表不写入，不会触发下一轮淘汰），再查最旧那条已被淘汰——顺序反了的话
    # 第一次 `reserve("first")` 会重新插入并挤掉 `second`，断言就会误报。
    same, owner_again = cache.reserve(("p1234abc", "second"))
    assert same is second and owner_again is False  # 后一条仍在
    assert cache.reserve(("p1234abc", "first"))[1] is True  # 最旧在途被淘汰


@pytest.mark.asyncio
async def test_drop_is_idempotent_and_frees_the_key() -> None:
    """失败路径的 ``drop`` 幂等：重复调用不抛，之后同键可以重新成为 owner。"""
    cache, _ = await _cache()

    cache.reserve(_KEY)
    cache.drop(_KEY)
    cache.drop(_KEY)  # 幂等：没有该键也不抛

    assert cache.reserve(_KEY)[1] is True
