"""A56 判据：后台任务进度的**跨进程**可见性（落盘投影）。

两个 ``TaskRegistry`` 实例共享同一投影目录 = 两个进程共享同一 ``<状态根>/tasks/``：
一个进程上报的进度，另一个进程的 ``snapshot()`` / ``get()`` 必须看得到；未绑定投影时
行为与改造前逐字一致（只读内存、不碰磁盘）。
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from heagent.engine.tasks import TaskProjection, TaskRegistry, TaskStatus, configure_task_projection

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def _registry(root: Path, *, now: datetime = NOW) -> TaskRegistry:
    return TaskRegistry(projection=TaskProjection(root), clock=lambda: now)


def test_another_process_sees_a_task_written_here(tmp_path: Path) -> None:
    producer = _registry(tmp_path / "tasks")
    consumer = _registry(tmp_path / "tasks")

    task_id = producer.start("context_compression", message="auto compressing")
    producer.report(task_id, 40, message="summarizing")

    seen = consumer.snapshot()
    assert [progress.task_id for progress in seen] == [task_id]
    assert seen[0].status is TaskStatus.RUNNING
    assert seen[0].percent == 40
    assert seen[0].message == "summarizing"

    single = consumer.get(task_id)
    assert single is not None and single.percent == 40


def test_terminal_state_is_visible_then_hidden_after_retention(tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    producer = _registry(root)
    task_id = producer.start("context_compression")
    producer.finish(task_id)

    assert _registry(root).get(task_id) is not None

    later = NOW + timedelta(seconds=10_000)  # 超过默认 300s 保留期
    assert _registry(root, now=later).get(task_id) is None
    assert _registry(root, now=later).snapshot() == []


def test_running_task_is_never_hidden_by_retention(tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    producer = _registry(root)
    task_id = producer.start("context_compression")
    producer.report(task_id, 10)

    later = NOW + timedelta(days=2)
    seen = _registry(root, now=later).snapshot()
    assert [progress.task_id for progress in seen] == [task_id]


def test_newest_updated_at_wins_between_memory_and_projection(tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    writer = _registry(root)
    task_id = writer.start("context_compression")
    writer.report(task_id, 80)

    # 本合同进程内的旧快照（percent 低、updated_at 早）不应盖过磁盘上的新值。
    stale = TaskRegistry(projection=TaskProjection(root), clock=lambda: NOW - timedelta(seconds=60))
    merged = stale.get(task_id)
    assert merged is not None and merged.percent == 80


def test_discard_removes_the_projection_file(tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    producer = _registry(root)
    task_id = producer.start("context_compression")
    assert (root / f"{task_id}.json").is_file()

    assert producer.discard(task_id) is True
    assert not (root / f"{task_id}.json").exists()
    assert _registry(root).snapshot() == []


def test_without_projection_nothing_touches_the_disk(tmp_path: Path) -> None:
    registry = TaskRegistry(clock=lambda: NOW)
    task_id = registry.start("context_compression")
    registry.report(task_id, 50)

    assert [progress.task_id for progress in registry.snapshot()] == [task_id]
    assert list(tmp_path.iterdir()) == []


def test_configure_task_projection_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    first = configure_task_projection(root)
    second = configure_task_projection(root)
    assert first is second, "同一目录重复绑定不得重建注册表（会丢掉内存里的在途任务）"

    try:
        task_id = first.start("context_compression")
        assert (root / f"{task_id}.json").is_file()
    finally:
        configure_task_projection(None)  # 收尾：解绑，避免污染其它用例的默认注册表


def test_truncation_keeps_the_newest_writes_and_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """超界截断按 mtime 取最新 256 个并记 WARNING：在途条目不会被年长文件静默挤出快照（在途不隐藏）。

    曾经的字典序截断会让 task_id 排序靠后的**在途**任务从 snapshot 消失——按 mtime 取最新后，
    持续被写的在途任务永远在最新档，被丢的只会是早已停写的旧条目。
    """
    root = tmp_path / "tasks"
    producer = _registry(root)
    ids = [producer.start("context_compression") for _ in range(TaskProjection._MAX_PROJECTION_FILES + 1)]
    base = NOW.timestamp()
    for index, task_id in enumerate(ids):
        stamp = base - (len(ids) - index)  # 写入顺序 = mtime 新旧：ids[0] 最旧
        os.utime(root / f"{task_id}.json", (stamp, stamp))

    caplog.set_level(logging.WARNING, logger="heagent.engine.tasks")
    seen = _registry(root).snapshot(limit=TaskProjection._MAX_PROJECTION_FILES)
    seen_ids = {progress.task_id for progress in seen}

    assert len(seen) == TaskProjection._MAX_PROJECTION_FILES
    assert ids[0] not in seen_ids, "最旧写入被截断"
    assert ids[1] in seen_ids, "次旧仍在：截断只丢最旧档，不按字典序丢"
    warnings = [record.getMessage() for record in caplog.records if "Task projection" in record.getMessage()]
    assert len(warnings) == 1, warnings
    assert "257" in warnings[0] and "256" in warnings[0]


def _over_limit_warnings(caplog: pytest.LogCaptureFixture) -> int:
    return sum("Task projection directory has" in record.getMessage() for record in caplog.records)


def test_over_limit_warning_is_logged_once_per_overflow(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """目录持续超界时 WARNING 只记一条：轮询方每次查询都会调 ``load_all``，逐次重打会刷屏。
    回落到上限内之后守卫复位——再次超界要再记一次，不能一辈子只记一次。"""
    root = tmp_path / "tasks"
    registry = _registry(root)
    limit = TaskProjection._MAX_PROJECTION_FILES
    caplog.set_level(logging.WARNING, logger="heagent.engine.tasks")
    ids = [registry.start("context_compression") for _ in range(limit + 1)]

    for _ in range(3):
        registry.snapshot(limit=limit)
    assert _over_limit_warnings(caplog) == 1, "持续超界不得每次查询都重打"

    for task_id in ids[:2]:  # 回落到上限内
        (root / f"{task_id}.json").unlink()
    registry.snapshot(limit=limit)
    assert _over_limit_warnings(caplog) == 1, "回落到上限内不记"

    registry.start("context_compression")
    registry.start("context_compression")
    registry.snapshot(limit=limit)
    assert _over_limit_warnings(caplog) == 2, "再次超界要再记一次"
