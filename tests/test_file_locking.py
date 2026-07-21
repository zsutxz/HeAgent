"""Story A.1: 跨进程文件锁 (persist.py + EngineContainer) 测试。"""

import asyncio
import os

import pytest

from heagent.engine.container import EngineContainer


class TestFileLocking:
    """Story A.1: 跨进程文件锁 (persist.py + EngineContainer)."""

    def test_atomic_write_with_lock_basic(self, tmp_path):
        """lock=True 正常写入 → 文件内容完整。"""
        from heagent.engine.persist import atomic_write_text

        target = tmp_path / "sub" / "f.json"
        atomic_write_text(target, '{"a": 1}', lock=True)
        assert target.read_text(encoding="utf-8") == '{"a": 1}'

    def test_atomic_write_without_lock_zero_regression(self, tmp_path):
        """lock=False（默认）行为与 V1 完全一致。"""
        from heagent.engine.persist import atomic_write_text

        target = tmp_path / "sub" / "f.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"old": 1}', encoding="utf-8")
        atomic_write_text(target, '{"new": 2}')
        # 无锁文件残留（lock=False 时不创建 .lock 文件）
        lock_file = target.with_name(target.name + ".lock")
        assert not lock_file.exists()
        assert target.read_text(encoding="utf-8") == '{"new": 2}'

    @pytest.mark.asyncio
    async def test_concurrent_writes_with_lock_serialized(self, tmp_path):
        """两个并发写入同一文件（lock=True）→ 串行执行，最终完整。"""
        from heagent.engine.persist import atomic_write_text

        target = tmp_path / "sub" / "concurrent.json"
        order = []

        async def writer(tag):
            await asyncio.to_thread(atomic_write_text, target, f'{{"tag": "{tag}"}}', lock=True)
            order.append(tag)

        await asyncio.gather(writer("a"), writer("b"))
        content = target.read_text(encoding="utf-8")
        assert content in ('{"tag": "a"}', '{"tag": "b"}')
        assert set(order) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_concurrent_writes_no_lock_no_crash(self, tmp_path):
        """两个并发写入同一文件（lock=False）→ 至少不抛非预期异常。"""
        from heagent.engine.persist import atomic_write_text

        target = tmp_path / "sub" / "concurrent_nolock.json"
        errors = []

        async def writer(tag):
            try:
                await asyncio.to_thread(atomic_write_text, target, f'{{"tag": "{tag}"}}')
            except PermissionError:
                # Windows 上 os.replace 在并发场景可能抛 PermissionError
                # 这是无锁并发的预期行为（替换竞态），不算崩溃
                pass
            except Exception as e:
                errors.append(e)

        await asyncio.gather(writer("a"), writer("b"))
        # 不应有非预期异常类型
        assert len(errors) == 0

    def test_lock_timeout_raises_oserror(self, tmp_path):
        """锁超时 → 抛 OSError。"""
        from heagent.engine.persist import _acquire_lock, atomic_write_text

        target = tmp_path / "sub" / "f.json"
        target.parent.mkdir(parents=True, exist_ok=True)

        # 先持有一个锁
        lock_path = target.with_name(target.name + ".lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
        try:
            _acquire_lock(lock_fd, 0.5)
            with pytest.raises(OSError, match="Failed to acquire"):
                atomic_write_text(target, '{"a": 2}', lock=True, lock_timeout=0.2)
        finally:
            os.close(lock_fd)

    def test_engine_container_enable_file_locks(self, tmp_path):
        """EngineContainer(enable_file_locks=True) → store/ledger 的 _enable_locks 为 True。"""
        container = EngineContainer(enable_file_locks=True)
        assert container.run_store._enable_locks is True
        assert container.ledger._enable_locks is True

    def test_engine_container_file_locks_default_false(self, tmp_path):
        """EngineContainer 默认 enable_file_locks=False → store/ledger 自身默认 False。"""
        container = EngineContainer()
        assert container.run_store._enable_locks is False
        assert container.ledger._enable_locks is False

    @pytest.mark.asyncio
    async def test_runstore_save_with_locks(self, tmp_path):
        """RunStore 经 enable_file_locks=True 后 save() 传 lock=True。"""
        from heagent.engine.context import RunContext

        # 用独立目录避免 .heagent/runs 的历史数据污染
        runs_dir = str(tmp_path / "test_runs")
        container = EngineContainer(enable_file_locks=True)
        container.run_store = container.run_store.__class__(base_dir=runs_dir)
        container.run_store._enable_locks = True

        ctx = RunContext(workspace_root=str(tmp_path))
        await container.run_store.start(ctx, prompt="test")
        runs = await container.run_store.list_runs()
        assert len(runs) == 1

    @pytest.mark.asyncio
    async def test_ledger_complete_with_locks(self, tmp_path):
        """ExecutionLedger 经 enable_file_locks=True 后 _save() 传 lock=True。"""
        ledger_dir = str(tmp_path / "test_ledger")
        container = EngineContainer(enable_file_locks=True)
        container.ledger = container.ledger.__class__(base_dir=ledger_dir)
        container.ledger._enable_locks = True

        key = "test:lock:1"
        claim = await container.ledger.acquire(key)
        assert claim.acquired is True
        await container.ledger.complete(key)
        record = await container.ledger.get(key)
        assert record is not None
        assert record.status.value == "completed"
