"""Tests for command runner sandbox backends (``tools/sandbox.py``)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import time

import pytest

from heagent.tools.sandbox import (
    FirejailBackend,
    PassthroughRunner,
    _kill_and_reap,
    bind_command_runner,
    bind_sandbox_profile,
    configure_command_runner,
    get_command_runner,
    get_sandbox_profile,
    reset_command_runner,
    reset_sandbox_profile,
)

_PY = f'"{sys.executable}"'


class _FakeProcBase:
    """所有 _FakeProc 的公共基类：提供 ``pid``（_kill_and_reap Linux 分支读取）。

    os.killpg 已由 ``_isolate_command_runner`` mock，pid 值仅作占位、永不作为真实信号目标。
    """

    pid = 1


@pytest.fixture(autouse=True)
def _isolate_command_runner(monkeypatch: pytest.MonkeyPatch):
    """每测试前后清进程级 fallback，防 ``configure`` 串扰。

    另两道安全网（让 fake-based 测试在所有平台确定性、且不发真实信号）：
    - 钉 ``sys.platform`` 为非 linux：fake 无法承载真实进程组语义，统一走 else 分支
      （``proc.kill()``、不加 ``start_new_session``，避免 fake_exec 因多余 kwarg 报错）。
      Linux ``os.killpg`` 分支由 ``test_kill_and_reap_linux_uses_proc_pid_directly`` 专门覆盖。
    - mock ``os.killpg`` 为 no-op：永不让测试向真实进程组发信号。
    """
    monkeypatch.setattr("heagent.tools.sandbox.sys.platform", "win32")
    monkeypatch.setattr("os.killpg", lambda *args, **kwargs: None, raising=False)
    reset_command_runner()
    reset_sandbox_profile()
    yield
    reset_command_runner()
    reset_sandbox_profile()


class TestPassthroughRunner:
    @pytest.mark.asyncio
    async def test_echo_and_exit_code(self) -> None:
        result = await PassthroughRunner().run("echo hello", timeout=10)
        assert "exit_code=0" in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_nonzero_exit(self) -> None:
        result = await PassthroughRunner().run(f'{_PY} -c "exit(42)"', timeout=10)
        assert "exit_code=42" in result

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        result = await PassthroughRunner().run(f'{_PY} -c "import time; time.sleep(10)"', timeout=1)
        assert "exit_code=-1" in result
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_timeout_zero_raises_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D3：``timeout<=0`` 在 spawn 前抛 ``ValueError``（消息含传入值），不拉起子进程。"""

        async def fake_shell(command: str, stdout=None, stderr=None):
            raise AssertionError("timeout<=0 不应 spawn 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        with pytest.raises(ValueError, match=r"got 0$"):
            await PassthroughRunner().run("echo hi", timeout=0)

    @pytest.mark.asyncio
    async def test_timeout_negative_raises_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D3：负 timeout 同样在 spawn 前抛 ``ValueError``（消息含传入值）。"""

        async def fake_shell(command: str, stdout=None, stderr=None):
            raise AssertionError("负 timeout 不应 spawn 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        with pytest.raises(ValueError, match=r"got -5$"):
            await PassthroughRunner().run("echo hi", timeout=-5)

    @pytest.mark.parametrize(
        "bad_timeout",
        [None, "120", 0.5, True, float("nan")],
        ids=["none", "str", "float", "bool", "nan"],
    )
    @pytest.mark.asyncio
    async def test_timeout_non_int_raises_before_spawn(
        self, monkeypatch: pytest.MonkeyPatch, bad_timeout: object
    ) -> None:
        """D-A：非正整数 timeout（None/str/float/bool/nan）一律在 spawn 前抛 ``ValueError``。

        ``nan`` 关键：``nan <= 0`` 恒 False 会绕过纯 ``<=`` 守卫、破坏 asyncio timer 堆全序，
        故须在类型层（``not isinstance(int)``）拦下。
        """

        async def fake_shell(command: str, stdout=None, stderr=None):
            raise AssertionError(f"非正整数 timeout 不应 spawn 子进程（got {bad_timeout!r}）")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        with pytest.raises(ValueError, match="timeout"):
            await PassthroughRunner().run("echo hi", timeout=bad_timeout)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_cancel_kill_and_reap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """外层取消（CancelledError）也须 kill+wait 子进程，不泄漏（D1 回归）。"""

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.returncode = 0
                self.killed = False
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                self.waited = True
                return 0

        proc = _FakeProc()

        async def fake_create(command: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create)

        task = asyncio.create_task(PassthroughRunner().run("blocker", timeout=120))
        await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert proc.killed, "CancelledError 路径未 kill 子进程"
        assert proc.waited, "CancelledError 路径未 wait 回收"

    @pytest.mark.asyncio
    async def test_cancel_survives_reap_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """D-1+D-1-A：取消清理时若 _kill_and_reap 抛错，原始 CancelledError 仍须上抛（不被 reap
        异常替换），且该 reap 失败记 debug 日志暴露诊断线索（observability）。

        fake proc 的 ``wait()`` 抛 ``RuntimeError`` → ``_kill_and_reap`` 经 ``wait_for`` 逸出该异常。
        （载体经 reap-robustness spec 迁移：原用 ``kill()`` 抛 ``PermissionError``，但 item 3 后 kill
        权限失败被 ``_kill_and_reap`` 内部吞掉、不再逸出 caller；改用 wait 侧抛错更贴近 D-1 真正关注
        的 reap 异常场景。）buggy 写法 ``except CancelledError: await _kill_and_reap(proc); raise`` 中
        裸 ``raise`` 永不执行 → task 抛 ``RuntimeError``（取消信号丢失）；修复后须抛 ``CancelledError``，
        且 ``except BaseException`` 分支记一条 debug 日志。
        """

        class _FakeProc(_FakeProcBase):
            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                pass  # item 3 后 kill 权限失败被 _kill_and_reap 内部吞掉、不逸出 caller

            async def wait(self) -> int:
                # reap 逸出 caller 的失败改由 wait 侧触发（RuntimeError）
                raise RuntimeError("simulated reap wait failure")

        proc = _FakeProc()

        async def fake_create(command: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create)

        task = asyncio.create_task(PassthroughRunner().run("blocker", timeout=120))
        await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
        task.cancel()
        with (
            caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"),
            pytest.raises(asyncio.CancelledError),  # 非 PermissionError——取消信号须存活
        ):
            await task
        assert any(rec.levelno == logging.DEBUG and "cancel cleanup" in rec.getMessage() for rec in caplog.records), (
            "reap 失败应记 debug 日志（D-1-A observability）"
        )

    @pytest.mark.asyncio
    async def test_timeout_reap_failure_returns_timeout_result(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """item 1：TimeoutError 路径 reap 抛非取消异常时，仍返回超时串（不上抛 reap 异常）。

        ``communicate()`` 超时 → 进入 ``except TimeoutError``；reap 的 ``wait()`` 抛
        ``RuntimeError`` → ``_kill_and_reap`` 经 ``wait_for`` 逸出 → ``except Exception`` 兜底 →
        返回超时串 + 记 ``timeout cleanup`` debug 日志。buggy 写法（无保护）会让 ``RuntimeError``
        替换超时串上抛（调用方收到错误消息而非「Command timed out」）。
        """

        class _FakeProc(_FakeProcBase):
            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 触发外层 timeout=1
                return b"", b""

            def kill(self) -> None:
                pass

            async def wait(self) -> int:
                raise RuntimeError("simulated reap wait failure")  # reap 逸出非取消异常

        proc = _FakeProc()

        async def fake_create(command: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create)

        with caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"):
            result = await PassthroughRunner().run("blocker", timeout=1)
        assert "timed out" in result, "reap 失败应仍返回超时串（item 1），而非上抛 RuntimeError"
        assert any(rec.levelno == logging.DEBUG and "timeout cleanup" in rec.getMessage() for rec in caplog.records), (
            "reap 失败应记 timeout cleanup debug 日志（item 1 observability）"
        )

    @pytest.mark.asyncio
    async def test_reap_wait_is_bounded(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """item 2：reap 的 ``wait()`` 有硬上界——D-state（wait 永不返回）不阻塞取消信号。

        fake ``wait()`` sleep 1000s 模拟 D-state；``_REAP_WAIT_TIMEOUT`` monkeypatch 为 0.05s。
        取消后 reap 的 ``wait_for`` 在 0.05s 超时逸出 ``TimeoutError`` → D-1 ``except BaseException``
        兜底 → 裸 ``raise`` 恢复原始 ``CancelledError``。关键不变量：task 在界内结束（非 hang 1000s），
        且 reap 逸出失败记 ``cancel cleanup`` debug 日志（无论 TimeoutError 还是 re-entrant cancel）。
        """

        monkeypatch.setattr("heagent.tools.sandbox._REAP_WAIT_TIMEOUT", 0.05)

        class _FakeProc(_FakeProcBase):
            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                pass

            async def wait(self) -> int:
                await asyncio.sleep(1000)  # D-state：永不返回

        proc = _FakeProc()

        async def fake_create(command: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create)

        start = time.monotonic()
        task = asyncio.create_task(PassthroughRunner().run("blocker", timeout=120))
        await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
        task.cancel()
        with (
            caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"),
            pytest.raises(asyncio.CancelledError),
        ):
            await task
        elapsed = time.monotonic() - start
        # reap wait_for 0.05s + 取消前 0.05s，远小于 wait 的 1000s sleep——证明硬上界兜住了 hang
        assert elapsed < 2.0, f"reap wait 未被硬上界兜住，疑似 hang（elapsed={elapsed:.2f}s）"
        assert any(rec.levelno == logging.DEBUG and "cancel cleanup" in rec.getMessage() for rec in caplog.records), (
            "reap 逸出失败应记 debug 日志（证明 wait_for 兜住 D-state 后放弃 reap）"
        )

    @pytest.mark.asyncio
    async def test_kill_failure_still_waits(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """item 3：``proc.kill()`` 权限失败不阻断后续 ``wait()``（kill/wait 解耦）。

        fake ``kill()`` 抛 ``PermissionError``（逃出 ``suppress(ProcessLookupError)``）；
        ``_kill_and_reap`` 的 item 3 ``except OSError`` 吞掉该失败、记 ``kill failed`` warning 日志后
        **仍执行** ``wait()``。断言 ``proc.waited`` 为 True（wait 跑过）+ 日志产出。buggy 写法
        （kill 抛错即跳出 _kill_and_reap）会让 ``wait()`` 不执行、pipe transport 泄漏。
        """

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                raise PermissionError("simulated kill failure")  # 逃出 suppress(PLE)

            async def wait(self) -> int:
                self.waited = True
                return 0

        proc = _FakeProc()

        async def fake_create(command: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create)

        task = asyncio.create_task(PassthroughRunner().run("blocker", timeout=120))
        await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
        task.cancel()
        with (
            caplog.at_level(logging.WARNING, logger="heagent.tools.sandbox"),
            pytest.raises(asyncio.CancelledError),
        ):
            await task
        assert proc.waited, "kill 失败后 wait() 仍应执行回收 pipe FD（item 3 解耦）"
        assert any(rec.levelno == logging.WARNING and "kill failed" in rec.getMessage() for rec in caplog.records), (
            "kill 失败应记 warning 日志（item 3 observability ~ 需人工关注非预期 kill 失败）"
        )

    @pytest.mark.asyncio
    async def test_kill_block_does_not_swallow_keyboardinterrupt(self) -> None:
        """code review patch：kill 块用 ``except Exception``（非 BaseException）——KeyboardInterrupt
        不被吞、立即逸出（不被 5s reap wait 延迟）。

        ``_kill_and_reap`` 的 kill 块若用 ``except BaseException``（buggy），``KeyboardInterrupt`` 被
        吞后落到 ``await wait_for(..., _REAP_WAIT_TIMEOUT)`` → shutdown 信号丢失 + 延迟最多 5s。
        修复后 ``except Exception`` 仅 catch kill 权限失败（``PermissionError``/``OSError``），
        ``KeyboardInterrupt``（BaseException）立即逸出、wait 不执行。直接测 ``_kill_and_reap``。
        """

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.waited = False

            def kill(self) -> None:
                raise KeyboardInterrupt()  # BaseException——kill 块 except 须为 Exception 才不吞

            async def wait(self) -> int:
                self.waited = True
                return 0

        proc = _FakeProc()
        with pytest.raises(KeyboardInterrupt):
            await _kill_and_reap(proc)
        assert not proc.waited, "KeyboardInterrupt 应立即逸出，不落到 wait（kill 块 except 须为 Exception）"

    @pytest.mark.asyncio
    async def test_kill_and_reap_linux_uses_proc_pid_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HIGH-1 回归：Linux 分支须直接 ``os.killpg(proc.pid, SIGKILL)``，不经 ``os.getpgid``。

        ``start_new_session=True`` 保证 ``proc.pid`` 即进程组长 pid，直接对其组发 SIGKILL 即可。
        ``os.getpgid(proc.pid)`` 在子进程已退出且 PID 被 OS 回收时会返回别的进程的 pgid，导致
        ``killpg`` 误杀无关进程组（PID 复用竞态）。本测钉 platform=linux 并断言：``getpgid``
        从未被调用、``killpg`` 以 ``(proc.pid, SIGKILL)`` 恰好调用一次。
        """
        monkeypatch.setattr("heagent.tools.sandbox.sys.platform", "linux")
        # signal.SIGKILL / os.killpg / os.getpgid 均为 Unix-only，Windows 下不存在——
        # 既然已钉 platform=linux 强制走 Linux 分支，须一并注入这些符号（raising=False）。
        fake_sigkill = 9
        monkeypatch.setattr("heagent.tools.sandbox.signal.SIGKILL", fake_sigkill, raising=False)

        getpgid_calls: list[int] = []
        killpg_calls: list[tuple[int, int]] = []
        monkeypatch.setattr("os.getpgid", lambda pid: getpgid_calls.append(pid) or pid, raising=False)
        monkeypatch.setattr("os.killpg", lambda pid, sig: killpg_calls.append((pid, sig)), raising=False)

        class _FakeProc(_FakeProcBase):
            async def wait(self) -> int:
                return 0

        proc = _FakeProc()
        await _kill_and_reap(proc)
        assert not getpgid_calls, "不得调用 os.getpgid（PID 复用竞态源）"
        assert killpg_calls == [(proc.pid, fake_sigkill)], (
            "须直接对 proc.pid（= 组长 pid）发 SIGKILL，不经 getpgid"
        )


class TestFirejailBackend:
    @pytest.mark.asyncio
    async def test_run_invokes_firejail_with_expected_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """断言 FirejailBackend 用 create_subprocess_exec 启动
        [firejail, *extra, '--', 'sh', '-c', cmd]（不真跑 firejail）。

        ``_FakeProc.returncode`` 为 per-instance、初值 ``None``，由 ``communicate``
        置非零值——断言 ``exit_code=<非0>`` 验证 ``_run_subprocess_exec`` 在
        ``communicate`` **完成后**才读 ``proc.returncode``（D4 保真度：原断言对
        类属性 ``returncode=0`` 同义反复，不验证读取时序）。
        """
        monkeypatch.setattr(shutil, "which", lambda p: "firejail")  # firejail 可用
        captured: dict[str, list[str]] = {}

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            captured["argv"] = list(argv)

            class _FakeProc(_FakeProcBase):
                def __init__(self) -> None:
                    self.returncode = None  # communicate 完成后才置位

                async def communicate(self) -> tuple[bytes, bytes]:
                    self.returncode = 42  # 模拟子进程退出码
                    return (b"out", b"err")

            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = FirejailBackend(firejail_path="firejail", extra_args=("--private-tmp",))
        result = await backend.run("ls -la", timeout=10)

        assert captured["argv"] == ["firejail", "--private-tmp", "--", "sh", "-c", "ls -la"]
        assert "exit_code=42" in result
        assert "out" in result

    @pytest.mark.asyncio
    async def test_timeout_zero_raises_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D3：``timeout<=0`` 在 exec 前抛 ``ValueError``（消息含传入值），不拉起 firejail 子进程。"""
        monkeypatch.setattr(shutil, "which", lambda p: "firejail")

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            raise AssertionError("timeout<=0 不应 spawn firejail 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        backend = FirejailBackend()
        with pytest.raises(ValueError, match=r"got 0$"):
            await backend.run("ls", timeout=0)

    @pytest.mark.asyncio
    async def test_timeout_negative_raises_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D3：负 timeout 在 exec 前同样抛 ``ValueError``（spec 要求 Passthrough + exec 两路径）。"""
        monkeypatch.setattr(shutil, "which", lambda p: "firejail")

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            raise AssertionError("负 timeout 不应 spawn firejail 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        backend = FirejailBackend()
        with pytest.raises(ValueError, match=r"got -5$"):
            await backend.run("ls", timeout=-5)

    @pytest.mark.asyncio
    async def test_cancel_survives_reap_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D-1（exec 路径对称）：取消清理时 _kill_and_reap 抛错，CancelledError 仍须上抛。

        经 ``_run_subprocess_exec``（与 shell helper 同构的 ``except CancelledError`` 块），
        断言取消后 task 抛 ``CancelledError`` 而非 reap 异常。载体经 reap-robustness spec 迁移：
        原用 ``kill()`` 抛 ``PermissionError``，但 item 3 后 kill 权限失败被 ``_kill_and_reap`` 内部
        吞掉、不再逸出 caller；改用 ``wait()`` 抛 ``RuntimeError``（wait 侧逸出）。
        """
        monkeypatch.setattr(shutil, "which", lambda p: "firejail")

        class _FakeProc(_FakeProcBase):
            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                pass  # item 3 后 kill 权限失败被 _kill_and_reap 内部吞掉、不逸出 caller

            async def wait(self) -> int:
                raise RuntimeError("simulated reap wait failure")  # reap 逸出非取消异常

        proc = _FakeProc()

        async def fake_exec(*argv: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = FirejailBackend()
        task = asyncio.create_task(backend.run("ls", timeout=120))
        await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):  # 非 RuntimeError——取消信号须存活
            await task

    @pytest.mark.asyncio
    async def test_timeout_reap_failure_returns_timeout_result(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """item 1（exec 路径对称）：TimeoutError 路径 reap 抛非取消异常仍返回超时串。"""
        monkeypatch.setattr(shutil, "which", lambda p: "firejail")

        class _FakeProc(_FakeProcBase):
            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 触发外层 timeout=1
                return b"", b""

            def kill(self) -> None:
                pass

            async def wait(self) -> int:
                raise RuntimeError("simulated reap wait failure")  # reap 逸出非取消异常

        proc = _FakeProc()

        async def fake_exec(*argv: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        with caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"):
            result = await FirejailBackend().run("ls", timeout=1)
        assert "timed out" in result, "reap 失败应仍返回超时串（item 1），而非上抛 RuntimeError"
        assert any(rec.levelno == logging.DEBUG and "timeout cleanup" in rec.getMessage() for rec in caplog.records), (
            "reap 失败应记 timeout cleanup debug 日志（item 1 observability）"
        )

    @pytest.mark.asyncio
    async def test_kill_failure_still_waits(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """item 3（exec 路径对称）：``proc.kill()`` 权限失败不阻断后续 ``wait()``。"""
        monkeypatch.setattr(shutil, "which", lambda p: "firejail")

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                raise PermissionError("simulated kill failure")  # 逃出 suppress(PLE)

            async def wait(self) -> int:
                self.waited = True
                return 0

        proc = _FakeProc()

        async def fake_exec(*argv: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = FirejailBackend()
        task = asyncio.create_task(backend.run("ls", timeout=120))
        await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
        task.cancel()
        with (
            caplog.at_level(logging.WARNING, logger="heagent.tools.sandbox"),
            pytest.raises(asyncio.CancelledError),
        ):
            await task
        assert proc.waited, "kill 失败后 wait() 仍应执行回收 pipe FD（item 3 解耦）"
        assert any(rec.levelno == logging.WARNING and "kill failed" in rec.getMessage() for rec in caplog.records), (
            "kill 失败应记 warning 日志（item 3 observability ~ 需人工关注非预期 kill 失败）"
        )


# ── S1-1: profiles dict + _build_argv ────────────────────────────────────────

class TestFirejailProfiles:
    """S1-1: profiles dict + _build_argv 纯函数。"""

    def test_profiles_empty_by_default(self) -> None:
        backend = FirejailBackend()
        assert backend._profiles == {}

    def test_profiles_stored_as_tuples(self) -> None:
        backend = FirejailBackend(profiles={
            "default": ["--private-tmp"],
            "network-isolated": ["--net=none", "--private-tmp"],
        })
        assert backend._profiles == {
            "default": ("--private-tmp",),
            "network-isolated": ("--net=none", "--private-tmp"),
        }

    def test_build_argv_no_profile(self) -> None:
        backend = FirejailBackend(extra_args=("--private-tmp",))
        argv = backend._build_argv("ls", profile=None)
        assert argv == ["firejail", "--private-tmp", "--", "sh", "-c", "ls"]

    def test_build_argv_with_profile(self) -> None:
        backend = FirejailBackend(profiles={"network-isolated": ("--net=none",)})
        argv = backend._build_argv("curl evil.com", profile="network-isolated")
        assert argv == ["firejail", "--net=none", "--", "sh", "-c", "curl evil.com"]

    def test_build_argv_unknown_profile_only_extra_args(self) -> None:
        backend = FirejailBackend(
            extra_args=("--private-tmp",),
            profiles={"default": ("--private-dev",)},
        )
        argv = backend._build_argv("ls", profile="nonexistent")
        assert argv == ["firejail", "--private-tmp", "--", "sh", "-c", "ls"]

    def test_build_argv_extra_and_profile_merged(self) -> None:
        backend = FirejailBackend(
            extra_args=("--private-tmp",),
            profiles={"strict": ("--net=none", "--caps.drop=all")},
        )
        argv = backend._build_argv("ls", profile="strict")
        assert argv == [
            "firejail", "--private-tmp", "--net=none", "--caps.drop=all",
            "--", "sh", "-c", "ls",
        ]

    def test_build_argv_pure_function_same_input_same_output(self) -> None:
        backend = FirejailBackend(profiles={"x": ("-a",)})
        a = backend._build_argv("cmd", profile="x")
        b = backend._build_argv("cmd", profile="x")
        assert a == b

    def test_build_argv_custom_firejail_path(self) -> None:
        backend = FirejailBackend(firejail_path="/usr/local/bin/firejail")
        argv = backend._build_argv("ls", profile=None)
        assert argv[0] == "/usr/local/bin/firejail"

    def test_build_argv_with_workspace_root(self) -> None:
        backend = FirejailBackend(workspace_root="/home/user/project")
        argv = backend._build_argv("ls", profile=None)
        assert "--private=/home/user/project" in argv
        private_idx = argv.index("--private=/home/user/project")
        dash_idx = argv.index("--")
        assert private_idx < dash_idx

    def test_build_argv_without_workspace_root(self) -> None:
        backend = FirejailBackend()
        argv = backend._build_argv("ls", profile=None)
        assert not any(a.startswith("--private=") for a in argv)

    def test_build_argv_workspace_and_profile_ordering(self) -> None:
        backend = FirejailBackend(
            extra_args=("--tmpfs=/tmp",),
            profiles={"strict": ("--net=none",)},
            workspace_root="/ws",
        )
        argv = backend._build_argv("ls", profile="strict")
        extra_idx = argv.index("--tmpfs=/tmp")
        private_idx = argv.index("--private=/ws")
        net_idx = argv.index("--net=none")
        dash_idx = argv.index("--")
        assert extra_idx < private_idx < net_idx < dash_idx


# ── S1-2: sandbox profile contextvar ────────────────────────────────────────

class TestSandboxProfileSlot:
    """S1-2: sandbox profile contextvar。"""

    def test_default_is_none(self) -> None:
        assert get_sandbox_profile() is None

    def test_bind_sets_and_restores(self) -> None:
        assert get_sandbox_profile() is None
        with bind_sandbox_profile("network-isolated"):
            assert get_sandbox_profile() == "network-isolated"
        assert get_sandbox_profile() is None

    def test_bind_none_is_transparent(self) -> None:
        with bind_sandbox_profile(None):
            assert get_sandbox_profile() is None

    def test_nested_bind_restores_outer(self) -> None:
        with bind_sandbox_profile("outer"):
            assert get_sandbox_profile() == "outer"
            with bind_sandbox_profile("inner"):
                assert get_sandbox_profile() == "inner"
            assert get_sandbox_profile() == "outer"

    def test_bind_no_leak(self) -> None:
        with bind_sandbox_profile("network-isolated"):
            pass
        assert get_sandbox_profile() is None


# ── S1-2: executor profile injection ────────────────────────────────────────

class TestExecutorProfileInjection:
    """S1-2: executor execute_in_sandbox 注入 profile。"""

    @pytest.mark.asyncio
    async def test_executor_binds_profile_in_handler(self) -> None:
        """executor 的 execute_in_sandbox 把 profile 注入 handler context。"""
        from heagent.engine.executor import ToolExecutor
        from heagent.tools.sandbox import FirejailBackend

        captured_profile: list[str | None] = []

        async def handler(call):
            captured_profile.append(get_sandbox_profile())
            return "ok"

        executor = ToolExecutor(sandbox_runner=FirejailBackend())
        await executor.execute_in_sandbox(
            call=type("Call", (), {"name": "shell", "arguments": {"command": "echo hi"}})(),
            profile="network-isolated",
            handler=handler,
        )
        assert captured_profile == ["network-isolated"]

    @pytest.mark.asyncio
    async def test_executor_null_runner_no_profile_bind(self) -> None:
        """sandbox_runner=None 时不经过 profile bind（快速路径）。"""
        from heagent.engine.executor import ToolExecutor

        captured: list[str | None] = []

        async def handler(call):
            captured.append(get_sandbox_profile())
            return "ok"

        executor = ToolExecutor()  # sandbox_runner=None
        await executor.execute_in_sandbox(
            call=type("Call", (), {"name": "shell", "arguments": {"command": "echo hi"}})(),
            profile="network-isolated",
            handler=handler,
        )
        # None runner paths do NOT bind profile — profile is meaningless without a runner
        assert captured == [None]

    @pytest.mark.asyncio
    async def test_passthrough_runner_ignores_profile_in_handler(self) -> None:
        """PassthroughRunner.run 无视 profile——行为完全不变。"""
        from heagent.engine.executor import ToolExecutor

        async def handler(call):
            runner = get_command_runner()
            assert isinstance(runner, PassthroughRunner)
            p = get_sandbox_profile()
            return f"profile={p}"

        executor = ToolExecutor(sandbox_runner=PassthroughRunner())
        result = await executor.execute_in_sandbox(
            call=type("Call", (), {"name": "shell", "arguments": {"command": "echo hi"}})(),
            profile="network-isolated",
            handler=handler,
        )
        assert result == "profile=network-isolated"


# ── S2-1: firejail availability detection ───────────────────────────────────

class TestFirejailAvailability:
    """S2-1: firejail 可用性检测 + 优雅降级。"""

    def test_available_true_when_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda p: "/usr/bin/firejail")
        backend = FirejailBackend()
        assert backend.available is True
        assert backend._resolved_path == "/usr/bin/firejail"

    def test_available_false_when_not_found(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda p: None)
        with caplog.at_level(logging.WARNING, logger="heagent.tools.sandbox"):
            backend = FirejailBackend()
        assert backend.available is False
        assert backend._resolved_path is None
        assert any("firejail not found" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_run_falls_back_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda p: None)

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                return (b"hello", b"")

        async def fake_shell(command: str, stdout=None, stderr=None):
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        backend = FirejailBackend()
        result = await backend.run("echo hi", timeout=10)
        assert "exit_code=0" in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_run_uses_resolved_path_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda p: "/usr/bin/firejail")

        captured_argv: list[list[str]] = []

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            captured_argv.append(list(argv))

            class _P:
                def __init__(self):
                    self.returncode = None

                async def communicate(self):
                    self.returncode = 0
                    return (b"out", b"")

            return _P()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        backend = FirejailBackend()
        await backend.run("ls", timeout=10)
        assert captured_argv[0][0] == "/usr/bin/firejail"


# ── S3-2: workspace_root --private mapping ──────────────────────────────────

class TestFirejailWorkspaceRoot:
    """S3-2: workspace_root 自动映射 --private。"""

    def test_workspace_root_default_none(self) -> None:
        backend = FirejailBackend()
        assert backend._workspace_root is None


class TestRuntimeSlot:
    def test_default_is_passthrough(self) -> None:
        assert isinstance(get_command_runner(), PassthroughRunner)

    def test_configure_overrides_default(self) -> None:
        backend = FirejailBackend()
        configure_command_runner(backend)
        assert get_command_runner() is backend

    def test_reset_restores_default(self) -> None:
        configure_command_runner(FirejailBackend())
        reset_command_runner()
        assert isinstance(get_command_runner(), PassthroughRunner)

    @pytest.mark.asyncio
    async def test_bind_is_temporary(self) -> None:
        backend = FirejailBackend()
        assert isinstance(get_command_runner(), PassthroughRunner)
        with bind_command_runner(backend):
            assert get_command_runner() is backend
        assert isinstance(get_command_runner(), PassthroughRunner)


class TestExecutorIntegration:
    """AC5：runner 的 timeout 校验经 ``ToolExecutor`` 转成错误 ``ToolResult`` 回喂 LLM，不中断循环。"""

    @pytest.mark.asyncio
    async def test_invalid_timeout_becomes_error_toolresult(self) -> None:
        """shell 调 ``timeout=0`` → runner ``ValueError`` → executor 捕获 → ``is_error`` ToolResult。"""
        from heagent.engine.executor import ToolExecutor
        from heagent.engine.policy import PolicyEngine, ToolExecutionMode
        from heagent.tools.builtins.shell import shell
        from heagent.types import ToolCall

        async def handler(call: ToolCall) -> str:
            return await shell(**call.arguments)

        call = ToolCall(id="1", name="shell", arguments={"command": "echo hi", "timeout": 0})
        verdict = PolicyEngine().evaluate_tool_call(call)
        assert verdict.mode is ToolExecutionMode.DIRECT

        result = await ToolExecutor().execute(
            call=call,
            verdict=verdict,
            guard=type("Guard", (), {"check": lambda self, call: None})(),
            handler=handler,
        )
        assert result.is_error is True
        assert "timeout" in result.content
