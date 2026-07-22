"""Coverage 补丁：ExecutionLedger 未覆盖分支测试。

独立异步测试用例，使用 tmp_path fixture 创建临时 ledger 目录。
覆盖行：complete() ValueError/RuntimeError、fail() ValueError、
heartbeat() None、list_records() []、_is_expired() 边界。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from heagent.engine.ledger import ExecutionLedger, ExecutionRecord, ExecutionStatus

# ── complete() 边界 ──────────────────────────────────────────────


class TestCompleteEdgeCases:
    @pytest.mark.asyncio
    async def test_complete_nonexistent_key_raises_value_error(self, tmp_path) -> None:
        """complete() 对不存在的 key 抛 ValueError（行 136）。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        with pytest.raises(ValueError, match="Cannot complete non-existent key"):
            await ledger.complete("nonexistent:key")

    @pytest.mark.asyncio
    async def test_complete_non_running_raises_runtime_error(self, tmp_path) -> None:
        """complete() 对非 RUNNING 状态抛 RuntimeError（行 138）。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        key = "test:complete:twice"
        await ledger.acquire(key)
        await ledger.complete(key)
        # 第二次 complete → status 已为 COMPLETED，非 RUNNING
        with pytest.raises(RuntimeError, match="current status is completed"):
            await ledger.complete(key)


# ── fail() 边界 ──────────────────────────────────────────────────


class TestFailEdgeCases:
    @pytest.mark.asyncio
    async def test_fail_nonexistent_key_raises_value_error(self, tmp_path) -> None:
        """fail() 对不存在的 key 抛 ValueError（行 157）。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        with pytest.raises(ValueError, match="Cannot fail non-existent key"):
            await ledger.fail("nonexistent:key", error="test error")


# ── heartbeat() 边界 ─────────────────────────────────────────────


class TestHeartbeatEdgeCases:
    @pytest.mark.asyncio
    async def test_heartbeat_nonexistent_key_returns_none(self, tmp_path) -> None:
        """heartbeat() 对不存在的 key 返回 None。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        result = await ledger.heartbeat("nonexistent:key")
        assert result is None

    @pytest.mark.asyncio
    async def test_heartbeat_non_running_completed_returns_none(self, tmp_path) -> None:
        """heartbeat() 对非 RUNNING 状态（已 COMPLETED）返回 None。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        key = "test:heartbeat:completed"
        await ledger.acquire(key)
        await ledger.complete(key)
        result = await ledger.heartbeat(key)
        assert result is None

    @pytest.mark.asyncio
    async def test_heartbeat_non_running_failed_returns_none(self, tmp_path) -> None:
        """heartbeat() 对非 RUNNING 状态（已 FAILED）返回 None。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        key = "test:heartbeat:failed"
        await ledger.acquire(key)
        await ledger.fail(key, error="some error")
        result = await ledger.heartbeat(key)
        assert result is None


# ── list_records() 边界 ──────────────────────────────────────────


class TestListRecordsEdgeCases:
    @pytest.mark.asyncio
    async def test_list_records_empty_dir_returns_empty_list(self, tmp_path) -> None:
        """list_records() 空目录返回 []。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        # 目录尚不存在 → 返回空列表
        result = await ledger.list_records()
        assert result == []
        assert isinstance(result, list)


# ── _is_expired() 边界 ───────────────────────────────────────────


class TestIsExpired:
    def test_is_expired_no_lease_returns_false(self) -> None:
        """_is_expired() 无租约（lease_expires_at=None）返回 False。"""
        record = ExecutionRecord(key="test:no_lease", lease_expires_at=None)
        assert ExecutionLedger._is_expired(record) is False

    def test_is_expired_expired_returns_true(self) -> None:
        """_is_expired() 已过期租约返回 True。"""
        past = (datetime.now(tz=UTC) - timedelta(seconds=10)).isoformat()
        record = ExecutionRecord(key="test:expired", lease_expires_at=past)
        assert ExecutionLedger._is_expired(record) is True

    def test_is_expired_future_lease_returns_false(self) -> None:
        """_is_expired() 未过期租约返回 False。"""
        future = (datetime.now(tz=UTC) + timedelta(seconds=60)).isoformat()
        record = ExecutionRecord(key="test:future", lease_expires_at=future)
        assert ExecutionLedger._is_expired(record) is False


# ── prune() 过期清理 ────────────────────────────────────────────


def _make_record(
    key: str,
    *,
    status: ExecutionStatus,
    finished_at: str | None = None,
    lease_expires_at: str | None = None,
) -> ExecutionRecord:
    """构造一条记录（绕过 acquire/complete 的 now 赋值，直接控制时间戳）。"""
    return ExecutionRecord(key=key, status=status, finished_at=finished_at, lease_expires_at=lease_expires_at)


class TestPrune:
    @pytest.mark.asyncio
    async def test_prune_removes_old_completed_keeps_recent(self, tmp_path) -> None:
        """prune 删 finished_at 过期的 COMPLETED，保留近期的。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        old = (datetime.now(tz=UTC) - timedelta(days=10)).isoformat()
        recent = (datetime.now(tz=UTC) - timedelta(days=1)).isoformat()
        await ledger._save(_make_record("old:done", status=ExecutionStatus.COMPLETED, finished_at=old))
        await ledger._save(_make_record("new:done", status=ExecutionStatus.COMPLETED, finished_at=recent))
        assert await ledger.prune(retention_days=7) == 1
        assert await ledger.get("old:done") is None
        assert await ledger.get("new:done") is not None

    @pytest.mark.asyncio
    async def test_prune_removes_old_failed(self, tmp_path) -> None:
        """prune 删过期的 FAILED。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        old = (datetime.now(tz=UTC) - timedelta(days=30)).isoformat()
        await ledger._save(_make_record("old:fail", status=ExecutionStatus.FAILED, finished_at=old))
        assert await ledger.prune(retention_days=7) == 1
        assert await ledger.get("old:fail") is None

    @pytest.mark.asyncio
    async def test_prune_removes_orphan_running_keeps_inflight(self, tmp_path) -> None:
        """prune 删租约过期的孤儿 RUNNING，保留未过期（在途）的。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        expired_lease = (datetime.now(tz=UTC) - timedelta(seconds=60)).isoformat()
        future_lease = (datetime.now(tz=UTC) + timedelta(seconds=60)).isoformat()
        await ledger._save(_make_record("orphan", status=ExecutionStatus.RUNNING, lease_expires_at=expired_lease))
        await ledger._save(_make_record("inflight", status=ExecutionStatus.RUNNING, lease_expires_at=future_lease))
        assert await ledger.prune(retention_days=7) == 1
        assert await ledger.get("orphan") is None
        assert await ledger.get("inflight") is not None

    @pytest.mark.asyncio
    async def test_prune_zero_retention_noop(self, tmp_path) -> None:
        """retention_days=0 禁用，不删任何记录。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        old = (datetime.now(tz=UTC) - timedelta(days=99)).isoformat()
        await ledger._save(_make_record("old:done", status=ExecutionStatus.COMPLETED, finished_at=old))
        assert await ledger.prune(retention_days=0) == 0
        assert await ledger.get("old:done") is not None

    @pytest.mark.asyncio
    async def test_prune_skips_corrupt_file(self, tmp_path) -> None:
        """损坏 JSON 不中断 prune（list_records 容错跳过），正常删其他过期记录。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        bad_path = ledger._path("corrupt:key")
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("{not valid json", encoding="utf-8")
        old = (datetime.now(tz=UTC) - timedelta(days=10)).isoformat()
        await ledger._save(_make_record("old:done", status=ExecutionStatus.COMPLETED, finished_at=old))
        assert await ledger.prune(retention_days=7) == 1
