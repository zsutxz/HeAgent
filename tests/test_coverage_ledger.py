"""ExecutionLedger 边界/分支覆盖率补充测试：complete/fail edge, heartbeat edge,
list_records 空目录、_is_lease_active() 边界（原 _is_expired，P1-23 重命名+反逻辑）、
prune() 过期清理。

全部测试使用 ``tmp_path``（pytest fixture）隔离 ledger 目录，避免残留文件污染。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from heagent.engine.ledger import ExecutionLedger, ExecutionRecord, ExecutionStatus


# ── complete() 边界 ─────────────────────────────────────────────


class TestCompleteEdgeCases:
    @pytest.mark.asyncio
    async def test_complete_nonexistent_key_raises_value_error(self, tmp_path) -> None:
        """complete('no-such-key') → ValueError（P1-8 修复：防凭空创建）。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        with pytest.raises(ValueError, match="Cannot complete non-existent key"):
            await ledger.complete("no-such-key")

    @pytest.mark.asyncio
    async def test_complete_non_running_raises_runtime_error(self, tmp_path) -> None:
        """complete 已 COMPLETED 的 key → RuntimeError。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        await ledger.acquire("key:non-running")
        await ledger.complete("key:non-running")
        with pytest.raises(RuntimeError, match="Cannot complete key"):
            await ledger.complete("key:non-running")


# ── fail() 边界 ─────────────────────────────────────────────────


class TestFailEdgeCases:
    @pytest.mark.asyncio
    async def test_fail_nonexistent_key_raises_value_error(self, tmp_path) -> None:
        """fail('no-such-key') → ValueError（P1-8 修复：防凭空创建）。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        with pytest.raises(ValueError, match="Cannot fail non-existent key"):
            await ledger.fail("no-such-key", "reason")


# ── heartbeat() 边界 ────────────────────────────────────────────


class TestHeartbeatEdgeCases:
    @pytest.mark.asyncio
    async def test_heartbeat_nonexistent_key_returns_none(self, tmp_path) -> None:
        """heartbeat 不存在的 key → None。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        assert await ledger.heartbeat("no-such-key") is None

    @pytest.mark.asyncio
    async def test_heartbeat_non_running_completed_returns_none(self, tmp_path) -> None:
        """heartbeat 已 COMPLETED 的 key → None。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        await ledger.acquire("key:hb-completed")
        await ledger.complete("key:hb-completed")
        assert await ledger.heartbeat("key:hb-completed") is None

    @pytest.mark.asyncio
    async def test_heartbeat_non_running_failed_returns_none(self, tmp_path) -> None:
        """heartbeat 已 FAILED 的 key → None。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        await ledger.acquire("key:hb-failed")
        await ledger.fail("key:hb-failed", "reason")
        assert await ledger.heartbeat("key:hb-failed") is None


# ── list_records() 边界 ─────────────────────────────────────────


class TestListRecordsEdgeCases:
    @pytest.mark.asyncio
    async def test_list_records_empty_dir_returns_empty_list(self) -> None:
        """list_records() 目录不存在时返回 []。"""
        ledger = ExecutionLedger(base_dir=".heagent/nonexistent_ledger_dir_for_test")
        assert await ledger.list_records() == []


# ── _is_lease_active() 边界（原 _is_expired，P1-23 重命名+反逻辑）─


class TestIsLeaseActive:
    """P1-23: _is_expired → _is_lease_active（语义反转：active=未过期／无租约）。"""

    def test_no_lease_returns_true(self) -> None:
        """无租约（lease_expires_at=None）→ 租约有效（永久）。"""
        record = ExecutionRecord(key="test:no_lease", lease_expires_at=None)
        assert ExecutionLedger._is_lease_active(record) is True

    def test_expired_lease_returns_false(self) -> None:
        """已过期租约 → 租约失效。"""
        past = (datetime.now(tz=UTC) - timedelta(seconds=10)).isoformat()
        record = ExecutionRecord(key="test:expired", lease_expires_at=past)
        assert ExecutionLedger._is_lease_active(record) is False

    def test_future_lease_returns_true(self) -> None:
        """未过期租约 → 租约仍有效。"""
        future = (datetime.now(tz=UTC) + timedelta(seconds=60)).isoformat()
        record = ExecutionRecord(key="test:future", lease_expires_at=future)
        assert ExecutionLedger._is_lease_active(record) is True


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
        await ledger._save(_make_record("recent:done", status=ExecutionStatus.COMPLETED, finished_at=recent))

        assert await ledger.prune(retention_days=7) == 1
        assert await ledger.get("old:done") is None
        assert await ledger.get("recent:done") is not None

    @pytest.mark.asyncio
    async def test_prune_removes_old_failed(self, tmp_path) -> None:
        """prune 删 FAILED 且 finished_at 过期的记录。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        old = (datetime.now(tz=UTC) - timedelta(days=10)).isoformat()

        await ledger._save(_make_record("old:fail", status=ExecutionStatus.FAILED, finished_at=old))
        assert await ledger.prune(retention_days=7) == 1
        assert await ledger.get("old:fail") is None

    @pytest.mark.asyncio
    async def test_prune_removes_orphan_running_keeps_inflight(self, tmp_path) -> None:
        """prune 删过期 RUNNING 孤儿（租约过期），保留租约未过期的在途。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        past = (datetime.now(tz=UTC) - timedelta(hours=3)).isoformat()
        future = (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat()

        await ledger._save(_make_record("orphan", status=ExecutionStatus.RUNNING, lease_expires_at=past))
        await ledger._save(_make_record("inflight", status=ExecutionStatus.RUNNING, lease_expires_at=future))

        assert await ledger.prune(retention_days=7) == 1
        assert await ledger.get("orphan") is None
        assert await ledger.get("inflight") is not None

    @pytest.mark.asyncio
    async def test_prune_zero_retention_noop(self, tmp_path) -> None:
        """retention_days=0 → 不执行、返回 0。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        assert await ledger.prune(retention_days=0) == 0

    @pytest.mark.asyncio
    async def test_prune_skips_corrupt_file(self, tmp_path) -> None:
        """JSON 损坏的文件跳过不中断整批；有效文件仍正常删。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        old = (datetime.now(tz=UTC) - timedelta(days=10)).isoformat()

        await ledger._save(_make_record("stale", status=ExecutionStatus.COMPLETED, finished_at=old))

        # 写一个损坏的 JSON（无效 UTF-8）——prune 应跳过它。
        corrupt = ledger._path("corrupt")
        corrupt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.write_bytes(b"\x80\x81\x82\xff\xfe")

        assert await ledger.prune(retention_days=7) == 1  # 只删 stale

    @pytest.mark.asyncio
    async def test_complete_distinguishes_corrupt_record_from_missing(self, tmp_path) -> None:
        """记录文件存在但读不出来时，错误文案如实说明「损坏」而非「键不存在」。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        corrupt = ledger._path("k1")
        corrupt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.write_bytes(b"\x80\x81\x82")

        with pytest.raises(ValueError, match="record exists but is unreadable"):
            await ledger.complete("k1")
        with pytest.raises(ValueError, match="record exists but is unreadable"):
            await ledger.fail("k1", "boom")

        with pytest.raises(ValueError, match="Cannot complete non-existent key"):
            await ledger.complete("never-acquired")

    @pytest.mark.asyncio
    async def test_complete_recreate_if_missing_restores_idempotency_cache(self, tmp_path) -> None:
        """``recreate_if_missing=True``：记录被清后重建为 COMPLETED，重复 acquire 仍命中缓存。

        这是工具调用链路的容错档（记录在途被 prune 清掉时不丢幂等）。默认（不开该档）
        仍是严格语义——见上面两条断言。
        """
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))

        record = await ledger.complete("k:gone", metadata={"result": "out"}, recreate_if_missing=True)

        assert record.status == ExecutionStatus.COMPLETED
        assert record.finished_at is not None
        loaded = await ledger.get("k:gone")
        assert loaded is not None and loaded.status == ExecutionStatus.COMPLETED
        assert loaded.metadata == {"result": "out"}

        claim = await ledger.acquire("k:gone", run_id="r1")
        assert claim.acquired is False  # 幂等缓存已恢复：重发不会重跑

    @pytest.mark.asyncio
    async def test_complete_recreate_if_missing_is_idempotent_on_completed(self, tmp_path) -> None:
        """已经是 COMPLETED 时不算错误（并发/重发场景），返回原记录。"""
        ledger = ExecutionLedger(base_dir=str(tmp_path / "ledger"))
        await ledger.acquire("k:done", run_id="r1")
        first = await ledger.complete("k:done")

        again = await ledger.complete("k:done", recreate_if_missing=True)

        assert again.finished_at == first.finished_at
        # 不开容错档时仍按既有契约报错（防回归）
        with pytest.raises(RuntimeError, match="current status is completed"):
            await ledger.complete("k:done")
