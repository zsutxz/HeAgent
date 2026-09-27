"""Story A.1: 跨进程文件锁 (persist.py + EngineContainer) 测试。"""

import asyncio
import os
import time

import pytest

from heagent.engine.container import EngineContainer


class TestFileLocking:
    """Story A.1: 跨进程文件锁 (persist.py + EngineContainer)."""

    def test_atomic_write_with_lock_basic(self, tmp_path):
        """lock=True 正常写入 → 文件内容完整。"""
        from heagent.pub.persist import atomic_write_text

        target = tmp_path / "sub" / "f.json"
        atomic_write_text(target, '{"a": 1}', lock=True)
        assert target.read_text(encoding="utf-8") == '{"a": 1}'

    def test_atomic_write_without_lock_zero_regression(self, tmp_path):
        """lock=False（默认）行为与 V1 完全一致。"""
        from heagent.pub.persist import atomic_write_text

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
        from heagent.pub.persist import atomic_write_text

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
        from heagent.pub.persist import atomic_write_text

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
        from heagent.pub.persist import _acquire_lock, atomic_write_text

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


class TestReapDanglingLocks:
    """孤儿锁回收（台账「`.json.lock` 无回收方」条目，2026-09-27 闭合）。

    三条判据必须**同时**满足才回收：同名记录不存在 / 锁年龄超限 / 非阻塞加锁证明无人持有。
    本类逐条钉住，缺一条都会被某个用例抓到。
    """

    @staticmethod
    def _age(path, seconds: float) -> None:
        stamp = time.time() - seconds
        os.utime(path, (stamp, stamp))

    def test_reaps_only_old_orphans(self, tmp_path):
        from heagent.pub.persist import reap_dangling_locks

        old_orphan = tmp_path / "gone.json.lock"
        old_orphan.write_bytes(b"\n")
        self._age(old_orphan, 10 * 86400)
        fresh_orphan = tmp_path / "fresh.json.lock"
        fresh_orphan.write_bytes(b"\n")
        live_lock = tmp_path / "live.json.lock"
        live_lock.write_bytes(b"\n")
        (tmp_path / "live.json").write_text("{}", encoding="utf-8")
        self._age(live_lock, 10 * 86400)
        unrelated = tmp_path / "notes.txt"
        unrelated.write_text("x", encoding="utf-8")
        self._age(unrelated, 10 * 86400)

        reaped = reap_dangling_locks(tmp_path, min_age_seconds=86400)

        assert reaped == 1
        assert not old_orphan.exists(), "孤儿 + 超龄 ⇒ 回收"
        assert fresh_orphan.exists(), "年龄门槛：新锁一律不动"
        assert live_lock.exists(), "同名记录仍在 ⇒ 不是孤儿"
        assert unrelated.exists(), "非锁文件不参与回收"

    def test_never_reaps_a_held_lock(self, tmp_path, monkeypatch):
        """「无人持有」必须由加锁**证明**（且是**非阻塞**尝试），不能靠 mtime 猜。

        Windows 上「持有句柄的文件本就 unlink 不掉」，故仅断言「文件仍在」无法区分「有证明」与
        「没证明」——这里额外 spy 加锁调用：没有这一步，判据被系统行为遮住（实测 M3 变异体不红）。
        """
        import heagent.pub.persist as persist_mod
        from heagent.pub.persist import _acquire_lock, reap_dangling_locks

        held = tmp_path / "held.json.lock"
        held.write_bytes(b"\n")
        self._age(held, 10 * 86400)

        attempts: list[float] = []
        real_acquire = persist_mod._acquire_lock

        def spy(fd: int, timeout: float) -> None:
            attempts.append(timeout)
            real_acquire(fd, timeout)

        monkeypatch.setattr(persist_mod, "_acquire_lock", spy)
        fd = os.open(str(held), os.O_RDWR)
        try:
            _acquire_lock(fd, 0.0)
            assert reap_dangling_locks(tmp_path, min_age_seconds=0) == 0
            assert held.exists(), "持有中的锁绝不能被删"
            assert attempts, "回收前必须先尝试加锁证明「无人持有」"
            assert all(timeout == 0 for timeout in attempts), "必须是非阻塞尝试（timeout=0）"
        finally:
            os.close(fd)
        # 释放后再跑：这次才允许回收（证明判据而非年龄门槛在起作用）
        attempts.clear()
        assert reap_dangling_locks(tmp_path, min_age_seconds=0) == 1
        assert attempts, "回收仍须走加锁证明"

    def test_missing_directory_and_empty_dir_are_zero(self, tmp_path):
        from heagent.pub.persist import reap_dangling_locks

        assert reap_dangling_locks(tmp_path / "nope") == 0
        assert reap_dangling_locks(tmp_path) == 0


class TestReapDanglingLocksSymlinkGuard:
    """孤儿锁回收的符号链接护栏（2026-09-27 复审发现）。"""

    def test_symlinked_lock_is_never_reaped(self, tmp_path, monkeypatch):
        """符号链接一律不动（与沙箱会话目录 / 编辑快照的 GC 同立场）。

        本机无法创建真实符号链接（WinError 1314），故用 `Path.is_symlink` 桩把这条判据钉在
        **代码动作**上，而不是依赖平台能力。
        """
        from pathlib import Path as _Path

        from heagent.pub.persist import reap_dangling_locks

        link_like = tmp_path / "someone-else.json.lock"
        link_like.write_bytes(b"\n")
        stamp = time.time() - 40 * 86400
        os.utime(link_like, (stamp, stamp))
        real_is_symlink = _Path.is_symlink

        def fake_is_symlink(self):
            if self.name == "someone-else.json.lock":
                return True
            return real_is_symlink(self)

        monkeypatch.setattr(_Path, "is_symlink", fake_is_symlink)

        assert reap_dangling_locks(tmp_path, min_age_seconds=86400) == 0
        assert link_like.exists(), "符号链接（即使超龄且无同名记录）也必须跳过"
