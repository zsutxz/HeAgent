"""Coverage 补丁：ExecutionLedger 未覆盖分支测试。

独立异步测试用例，使用 tmp_path fixture 创建临时 ledger 目录。
覆盖行：complete() ValueError/RuntimeError、fail() ValueError、
heartbeat() None、list_records() []、_is_expired() 边界。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from heagent.engine.ledger import ExecutionLedger, ExecutionRecord


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
