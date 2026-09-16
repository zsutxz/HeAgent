"""Tests for command runner sandbox backends (``tools/sandbox.py``)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import time
from pathlib import Path

import pytest

from heagent.tools.sandbox import (
    FirejailBackend,
    PassthroughRunner,
    SandboxSession,
    SandboxTier,
    WinJobBackend,
    _format_result,
    _kill_and_reap,
    bind_command_runner,
    bind_sandbox_profile,
    bind_sandbox_workspace,
    configure_command_runner,
    get_command_runner,
    get_sandbox_profile,
    get_sandbox_workspace,
    reset_command_runner,
    reset_sandbox_profile,
    reset_sandbox_workspace,
    sandbox_session_dir,
    sandbox_sessions_root,
)

_PY = f'"{sys.executable}"'


class _FakeProcBase:
    """所有 _FakeProc 的公共基类：提供 ``pid``（_kill_and_reap Linux 分支读取）。

    os.killpg 已由 ``_isolate_command_runner`` mock，pid 值仅作占位、永不作为真实信号目标。
    """

    pid = 1


@pytest.fixture(autouse=True)
def _isolate_command_runner(monkeypatch: pytest.MonkeyPatch):
    """每测试前后清进程级 fallback，防 ``configure`` 串扰；并 mock ``os.killpg``（永不发真实信号）。

    ⚠ 这里**刻意不钉** ``sys.platform``：那改的是**进程全局** ``sys``（``heagent.tools.sandbox.sys``
    就是全局 ``sys``），会让本模块所有测试在 POSIX 上误走 Windows 分支——CI 上已真实炸过两次：
    ① ``SandboxSession`` 误用 Windows cmd 包装喂给 ``/bin/sh``（``cd: can't cd to /d``）；
    ② Python 3.12+ 的 ``shutil.which`` 自带 ``sys.platform == "win32"`` 分支，钉住后走 ``_winapi``
    （POSIX 上为 None）→ ``AttributeError: 'NoneType' object has no attribute
    'NeedCurrentDirectoryForExePath'``。**默认即真实平台**，只有确实需要「伪 Windows 进程语义」的
    fake-进程测试才显式请求 :func:`fake_process_platform`。
    """
    monkeypatch.setattr("os.killpg", lambda *args, **kwargs: None, raising=False)


@pytest.fixture
def fake_process_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """把进程全局 ``sys.platform`` 钉成 win32——**仅供 fake-进程测试按需请求**。

    为什么需要：这些测试用假 subprocess 对象替代真实子进程，而 fake 无法承载真实进程组语义
    （``run`` 签名不接受 ``start_new_session`` 等额外 kwarg），统一走 else 分支最稳。
    Linux ``os.killpg`` 分支由 ``test_kill_and_reap_linux_uses_proc_pid_directly`` 专门覆盖。

    为什么必须 opt-in：钉子改的是进程全局 ``sys``，autouse 会让同模块「依赖真实平台」的测试
    （真实 shell 包装、平台敏感的 ``shutil.which`` 等）在 POSIX 上走错分支（见 autouse fixture 的说明）。
    """
    monkeypatch.setattr("heagent.tools.sandbox.sys.platform", "win32")
    reset_command_runner()
    reset_sandbox_profile()
    reset_sandbox_workspace()
    yield
    reset_command_runner()
    reset_sandbox_profile()
    reset_sandbox_workspace()


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

        async def fake_shell(command: str, stdout=None, stderr=None, env=None):
            raise AssertionError("timeout<=0 不应 spawn 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        with pytest.raises(ValueError, match=r"got 0$"):
            await PassthroughRunner().run("echo hi", timeout=0)

    @pytest.mark.asyncio
    async def test_timeout_negative_raises_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D3：负 timeout 同样在 spawn 前抛 ``ValueError``（消息含传入值）。"""

        async def fake_shell(command: str, stdout=None, stderr=None, env=None):
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

        async def fake_shell(command: str, stdout=None, stderr=None, env=None):
            raise AssertionError(f"非正整数 timeout 不应 spawn 子进程（got {bad_timeout!r}）")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        with pytest.raises(ValueError, match="timeout"):
            await PassthroughRunner().run("echo hi", timeout=bad_timeout)  # type: ignore[arg-type]

    @pytest.mark.usefixtures("fake_process_platform")
    @pytest.mark.asyncio
    async def test_cancel_kill_and_reap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """外层取消（CancelledError）也须 kill+wait 子进程，不泄漏（D1 回归）。"""

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.returncode = 0
                self.killed = False
                self.communicate_calls = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                self.communicate_calls += 1
                if self.communicate_calls > 1:
                    return b"", b""
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                self.waited = True
                return 0

        proc = _FakeProc()

        async def fake_create(command: str, stdout=None, stderr=None, env=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create)

        task = asyncio.create_task(PassthroughRunner().run("blocker", timeout=120))
        await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert proc.killed, "CancelledError 路径未 kill 子进程"
        assert proc.communicate_calls == 2, "CancelledError 路径未再次 communicate 回收管道"

    @pytest.mark.usefixtures("fake_process_platform")
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

        async def fake_create(command: str, stdout=None, stderr=None, env=None) -> _FakeProc:
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

    @pytest.mark.usefixtures("fake_process_platform")
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

        async def fake_create(command: str, stdout=None, stderr=None, env=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create)

        with caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"):
            result = await PassthroughRunner().run("blocker", timeout=1)
        assert "timed out" in result, "reap 失败应仍返回超时串（item 1），而非上抛 RuntimeError"
        assert any(rec.levelno == logging.DEBUG and "timeout cleanup" in rec.getMessage() for rec in caplog.records), (
            "reap 失败应记 timeout cleanup debug 日志（item 1 observability）"
        )

    @pytest.mark.usefixtures("fake_process_platform")
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

        async def fake_create(command: str, stdout=None, stderr=None, env=None) -> _FakeProc:
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

    @pytest.mark.usefixtures("fake_process_platform")
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
                self.communicate_calls = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                self.communicate_calls += 1
                if self.communicate_calls > 1:
                    return b"", b""
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                raise PermissionError("simulated kill failure")  # 逃出 suppress(PLE)

        proc = _FakeProc()

        async def fake_create(command: str, stdout=None, stderr=None, env=None) -> _FakeProc:
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
        assert proc.communicate_calls == 2, "kill 失败后仍应 communicate 回收管道"
        assert any(rec.levelno == logging.WARNING and "kill failed" in rec.getMessage() for rec in caplog.records), (
            "kill 失败应记 warning 日志（item 3 observability ~ 需人工关注非预期 kill 失败）"
        )

    @pytest.mark.usefixtures("fake_process_platform")
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
            async def communicate(self) -> tuple[bytes, bytes]:
                return b"", b""

            async def wait(self) -> int:
                return 0

        proc = _FakeProc()
        await _kill_and_reap(proc)
        assert not getpgid_calls, "不得调用 os.getpgid（PID 复用竞态源）"
        assert killpg_calls == [(proc.pid, fake_sigkill)], "须直接对 proc.pid（= 组长 pid）发 SIGKILL，不经 getpgid"


class TestFirejailBackend:
    @pytest.mark.usefixtures("fake_process_platform")
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

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None):
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

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None):
            raise AssertionError("timeout<=0 不应 spawn firejail 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        backend = FirejailBackend()
        with pytest.raises(ValueError, match=r"got 0$"):
            await backend.run("ls", timeout=0)

    @pytest.mark.asyncio
    async def test_timeout_negative_raises_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D3：负 timeout 在 exec 前同样抛 ``ValueError``（spec 要求 Passthrough + exec 两路径）。"""
        monkeypatch.setattr(shutil, "which", lambda p: "firejail")

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None):
            raise AssertionError("负 timeout 不应 spawn firejail 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        backend = FirejailBackend()
        with pytest.raises(ValueError, match=r"got -5$"):
            await backend.run("ls", timeout=-5)

    @pytest.mark.usefixtures("fake_process_platform")
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

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = FirejailBackend()
        task = asyncio.create_task(backend.run("ls", timeout=120))
        await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):  # 非 RuntimeError——取消信号须存活
            await task

    @pytest.mark.usefixtures("fake_process_platform")
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

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        with caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"):
            result = await FirejailBackend().run("ls", timeout=1)
        assert "timed out" in result, "reap 失败应仍返回超时串（item 1），而非上抛 RuntimeError"
        assert any(rec.levelno == logging.DEBUG and "timeout cleanup" in rec.getMessage() for rec in caplog.records), (
            "reap 失败应记 timeout cleanup debug 日志（item 1 observability）"
        )

    @pytest.mark.usefixtures("fake_process_platform")
    @pytest.mark.asyncio
    async def test_kill_failure_still_waits(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """item 3（exec 路径对称）：``proc.kill()`` 权限失败不阻断后续 ``wait()``。"""
        monkeypatch.setattr(shutil, "which", lambda p: "firejail")

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.communicate_calls = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                self.communicate_calls += 1
                if self.communicate_calls > 1:
                    return b"", b""
                await asyncio.sleep(1000)  # 阻塞到被取消
                return b"", b""

            def kill(self) -> None:
                raise PermissionError("simulated kill failure")  # 逃出 suppress(PLE)

        proc = _FakeProc()

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None) -> _FakeProc:
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
        assert proc.communicate_calls == 2, "kill 失败后仍应 communicate 回收管道"
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
        backend = FirejailBackend(
            profiles={
                "default": ["--private-tmp"],
                "network-isolated": ["--net=none", "--private-tmp"],
            }
        )
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
            "firejail",
            "--private-tmp",
            "--net=none",
            "--caps.drop=all",
            "--",
            "sh",
            "-c",
            "ls",
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
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda p: None)
        with caplog.at_level(logging.WARNING, logger="heagent.tools.sandbox"):
            backend = FirejailBackend()
        assert backend.available is False
        assert backend._resolved_path is None
        assert any("firejail not found" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.usefixtures("fake_process_platform")
    @pytest.mark.asyncio
    async def test_run_falls_back_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda p: None)

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                return (b"hello", b"")

        async def fake_shell(command: str, stdout=None, stderr=None, env=None):
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        backend = FirejailBackend()
        result = await backend.run("echo hi", timeout=10)
        assert "exit_code=0" in result
        assert "hello" in result

    @pytest.mark.usefixtures("fake_process_platform")
    @pytest.mark.asyncio
    async def test_run_uses_resolved_path_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda p: "/usr/bin/firejail")

        captured_argv: list[list[str]] = []

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None):
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


# ── FR-1: sandbox session workspace ─────────────────────────────────────────


class TestSandboxSessionDir:
    """FR-1: ``sandbox_session_dir`` 纯函数——幂等创建 / base 注入 / 规范路径。"""

    def test_creates_dir_under_default_root(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """默认根 ``Path.cwd()/.heagent/sandboxes``：返回 ``<root>/<run_id>/`` 且目录已存在。"""
        monkeypatch.chdir(tmp_path)
        path = sandbox_session_dir("runabc")
        assert path == tmp_path / ".heagent" / "sandboxes" / "runabc"
        assert path.is_dir()

    def test_idempotent_same_run_id(self, tmp_path: Path) -> None:
        """同一 run_id 两次调用 → 同一路径、不抛异常（幂等）。"""
        first = sandbox_session_dir("same-run", base=tmp_path)
        second = sandbox_session_dir("same-run", base=tmp_path)
        assert first == second
        assert first.is_dir()

    def test_base_injection_replaces_default_root(self, tmp_path: Path) -> None:
        """``base`` 显式传入时替代整个默认根（测试注入通道）。"""
        path = sandbox_session_dir("r1", base=tmp_path / "custom-root")
        assert path == tmp_path / "custom-root" / "r1"
        assert path.is_dir()

    def test_returns_absolute_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """默认根基于 ``Path.cwd()``——返回值始终为绝对路径（可直传后端 argv / cwd）。"""
        monkeypatch.chdir(tmp_path)
        assert sandbox_session_dir("abs-run").is_absolute()

    def test_independent_of_executor_instances(self, tmp_path: Path) -> None:
        """不依赖任何执行器实例状态——不构造 backend 也返回已创建目录。"""
        assert sandbox_session_dir("pure-run", base=tmp_path).is_dir()

    def test_default_root_matches_convention_root(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """约定根不变量（E40-D1）：创建方与回收方必须看同一个根。"""
        monkeypatch.chdir(tmp_path)
        assert sandbox_session_dir("run-1").parent == sandbox_sessions_root()
        assert sandbox_sessions_root(tmp_path) == tmp_path / ".heagent" / "sandboxes"

    @pytest.mark.parametrize(
        "bad_run_id",
        ["", "a/b", "a\\b", "..", ".", "/abs/run"],
        ids=["empty", "slash", "backslash", "dotdot", "dot", "absolute"],
    )
    def test_invalid_run_id_raises_value_error(self, tmp_path: Path, bad_run_id: str) -> None:
        """非法 run_id（空串/含分隔符/.././绝对路径）→ ValueError，且不建任何目录。"""
        with pytest.raises(ValueError, match="invalid run_id"):
            sandbox_session_dir(bad_run_id, base=tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestSandboxWorkspaceSlot:
    """FR-1: sandbox workspace contextvar（仿 profile slot）。"""

    def test_default_is_none(self) -> None:
        assert get_sandbox_workspace() is None

    def test_bind_sets_and_restores(self, tmp_path: Path) -> None:
        assert get_sandbox_workspace() is None
        with bind_sandbox_workspace(tmp_path):
            assert get_sandbox_workspace() == tmp_path
        assert get_sandbox_workspace() is None

    def test_bind_none_is_transparent(self) -> None:
        with bind_sandbox_workspace(None):
            assert get_sandbox_workspace() is None

    def test_nested_bind_restores_outer(self, tmp_path: Path) -> None:
        outer, inner = tmp_path / "outer", tmp_path / "inner"
        with bind_sandbox_workspace(outer):
            assert get_sandbox_workspace() == outer
            with bind_sandbox_workspace(inner):
                assert get_sandbox_workspace() == inner
            assert get_sandbox_workspace() == outer
        assert get_sandbox_workspace() is None


@pytest.mark.usefixtures("fake_process_platform")
class TestFirejailSessionWorkspace:
    """FR-1: FirejailBackend 以 per-run 会话目录优先作 ``--private`` 根。"""

    @staticmethod
    def _capture_exec(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        """钉 firejail 可用 + 捕获 argv 的公共 setup，返回捕获列表。"""
        monkeypatch.setattr(shutil, "which", lambda p: "/usr/bin/firejail")
        captured: list[list[str]] = []

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None):
            captured.append(list(argv))

            class _FakeProc(_FakeProcBase):
                def __init__(self):
                    self.returncode = 0

                async def communicate(self):
                    return (b"out", b"")

            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        return captured

    @pytest.mark.asyncio
    async def test_session_workspace_overrides_constructor_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """bind per-run 目录 → argv 含 ``--private=<该目录>``，优先于构造期 workspace_root。"""
        captured = self._capture_exec(monkeypatch)
        backend = FirejailBackend(workspace_root="/constructor-root")
        session = tmp_path / "session-run"
        with bind_sandbox_workspace(session):
            await backend.run("ls", timeout=10)
        assert f"--private={session}" in captured[0]
        assert "--private=/constructor-root" not in captured[0]

    @pytest.mark.asyncio
    async def test_no_bind_uses_constructor_root_regression(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 bind（开关关）→ argv 与现状逐字节一致：构造期 root，无会话目录痕迹。"""
        captured = self._capture_exec(monkeypatch)
        backend = FirejailBackend(workspace_root="/constructor-root")
        await backend.run("ls", timeout=10)
        assert captured[0] == ["/usr/bin/firejail", "--private=/constructor-root", "--", "sh", "-c", "ls"]

    @pytest.mark.asyncio
    async def test_no_bind_no_root_no_private(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 bind 且无构造期 root → 不出现任何 --private（回归锁定）。"""
        captured = self._capture_exec(monkeypatch)
        await FirejailBackend().run("ls", timeout=10)
        assert captured[0] == ["/usr/bin/firejail", "--", "sh", "-c", "ls"]

    @pytest.mark.asyncio
    async def test_unavailable_with_bind_still_passthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """firejail 不可用 + 会话目录已解析 → 维持 warn + Passthrough 降级，无新增失败路径。"""
        monkeypatch.setattr(shutil, "which", lambda p: None)

        async def fake_exec(*argv: str, stdout=None, stderr=None, env=None):
            raise AssertionError("不可用时不应走 create_subprocess_exec")

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                return (b"pw_out", b"")

        async def fake_shell(command: str, stdout=None, stderr=None, env=None):
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        with bind_sandbox_workspace(Path("/resolved-session")):
            result = await FirejailBackend().run("echo hi", timeout=10)
        assert "pw_out" in result


# ── FR-2: sandbox backend strength tiering ──────────────────────────────────


class TestSandboxTier:
    """FR-2: SandboxTier 分级枚举 + 后端档位声明 + 审批降级锁定。"""

    def test_all_four_tiers_exist(self) -> None:
        assert {t.value for t in SandboxTier} == {"passthrough", "job", "firejail", "container"}

    def test_rank_is_strictly_increasing(self) -> None:
        tiers = [SandboxTier.PASSTHROUGH, SandboxTier.JOB, SandboxTier.FIREJAIL, SandboxTier.CONTAINER]
        assert [t.rank for t in tiers] == [0, 1, 2, 3]

    def test_backend_tier_declarations(self) -> None:
        assert PassthroughRunner.tier is SandboxTier.PASSTHROUGH
        assert WinJobBackend.tier is SandboxTier.JOB
        assert FirejailBackend.tier is SandboxTier.FIREJAIL

    def test_weak_tiers_cannot_relax_approval(self) -> None:
        """弱后端（passthrough/job/firejail）一律不降审批（NFR-2 测试锁定）。"""
        for tier in (SandboxTier.PASSTHROUGH, SandboxTier.JOB, SandboxTier.FIREJAIL):
            assert tier.can_relax_approval is False

    def test_container_tier_reserved_can_relax(self) -> None:
        """container 档（预留，无实现后端）才允许审批降级。"""
        assert SandboxTier.CONTAINER.can_relax_approval is True


# ── FR-4: SandboxSession 会话作用域 ──────────────────────────────────────────


class TestSandboxSession:
    """FR-4: SandboxSession 会话作用域 + cwd 跨命令保持 + teardown。"""

    def test_initial_cwd_is_workspace(self, tmp_path: Path) -> None:
        s = SandboxSession(tmp_path)
        assert s.cwd == tmp_path
        assert s.workspace == tmp_path

    def test_wrap_posix(self, tmp_path: Path) -> None:
        s = SandboxSession(tmp_path)
        wrapped = s._wrap("pwd", cmd_shell=False)
        assert str(tmp_path) in wrapped
        assert "HEAGENT_CWD" in wrapped
        assert "$PWD" in wrapped

    def test_wrap_cmd(self, tmp_path: Path) -> None:
        s = SandboxSession(tmp_path)
        wrapped = s._wrap("pwd", cmd_shell=True)
        assert str(tmp_path) in wrapped
        assert "HEAGENT_CWD" in wrapped

    def test_extract_cwd(self) -> None:
        out = "exit_code=0\nstdout:\nHEAGENT_CWD\n/tmp/run/sub\nstderr:\n"
        assert SandboxSession._extract_cwd(out) == Path("/tmp/run/sub")

    def test_extract_cwd_missing(self) -> None:
        assert SandboxSession._extract_cwd("exit_code=0\nstdout:\nhello\n") is None

    def test_strip_marker(self) -> None:
        out = "exit_code=0\nstdout:\nhello\nHEAGENT_CWD\n/tmp/x\nstderr:\n"
        stripped = SandboxSession._strip_marker(out)
        assert "HEAGENT_CWD" not in stripped
        assert "hello" in stripped

    @pytest.mark.asyncio
    async def test_run_wraps_updates_cwd_strips(self, tmp_path: Path) -> None:
        """run() 用 mock runner：命令被包装（cd 前缀 + marker）、cwd 回填、marker 去除。"""
        captured: list[str] = []

        class _Runner:
            tier = SandboxTier.FIREJAIL

            async def run(self, command, *, timeout):
                captured.append(command)
                return "exit_code=0\nstdout:\nhello\nHEAGENT_CWD\n/fake/sub\nstderr:\n"

        s = SandboxSession(tmp_path)
        with bind_command_runner(_Runner()):
            result = await s.run("echo hi", timeout=10)
        assert str(tmp_path) in captured[0]
        assert "HEAGENT_CWD" in captured[0]
        assert s.cwd == Path("/fake/sub")
        assert "HEAGENT_CWD" not in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_cwd_persists_across_commands(self, tmp_path: Path) -> None:
        """真实 shell：cd sub 后 session.cwd 正确更新，文件落在 sub 下（cwd 跨命令保持核心）。

        跨平台命令（mkdir/cd/echo 为 cmd 与 sh 通用）；不依赖 pwd/ls（POSIX-only）。
        """
        s = SandboxSession(tmp_path)
        with bind_command_runner(PassthroughRunner()):
            await s.run("mkdir sub && cd sub && echo hi > a", timeout=15)
        assert s.cwd == tmp_path / "sub"
        assert (tmp_path / "sub" / "a").exists()

    @pytest.mark.asyncio
    async def test_close_removes_workspace(self, tmp_path: Path) -> None:
        s = SandboxSession(tmp_path)
        (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
        await s.close(keep=False)
        assert not tmp_path.exists()

    # ---- 退出码保持（bugfix：包装链尾命令会重置进程退出码）----

    def test_extract_cwd_with_rc_marker(self) -> None:
        """marker 行携带 rc（Windows 形态 ``HEAGENT_CWD 3``）时 cwd 解析不受影响。"""
        out = "exit_code=0\nstdout:\nHEAGENT_CWD 3\n/tmp/run/sub\nstderr:\n"
        assert SandboxSession._extract_cwd(out) == Path("/tmp/run/sub")

    def test_extract_rc(self) -> None:
        out = "exit_code=0\nstdout:\nHEAGENT_CWD 3\n/tmp/x\nstderr:\n"
        assert SandboxSession._extract_rc(out) == 3

    def test_extract_rc_missing(self) -> None:
        """POSIX marker 不带 rc（进程级退出码已复原）→ None，不触发回填。"""
        assert SandboxSession._extract_rc("exit_code=0\nstdout:\nHEAGENT_CWD\n/tmp\n") is None

    def test_strip_marker_with_rc(self) -> None:
        out = "exit_code=0\nstdout:\nhello\nHEAGENT_CWD 3\n/tmp/x\nstderr:\n"
        stripped = SandboxSession._strip_marker(out)
        assert "HEAGENT_CWD" not in stripped
        assert "hello" in stripped

    @pytest.mark.asyncio
    async def test_run_rewrites_exit_code_from_marker(self, tmp_path: Path) -> None:
        """Windows 形态：进程级 exit_code=0（链尾 cd 重置 ERRORLEVEL），marker 带回真实 rc → 回填。"""

        class _Runner:
            tier = SandboxTier.FIREJAIL

            async def run(self, command, *, timeout):
                return "exit_code=0\nstdout:\nhello\nHEAGENT_CWD 7\n/fake/sub\nstderr:\n"

        s = SandboxSession(tmp_path)
        with bind_command_runner(_Runner()):
            result = await s.run("anything", timeout=10)
        assert result.startswith("exit_code=7")
        assert "HEAGENT_CWD" not in result
        assert s.cwd == Path("/fake/sub")

    @pytest.mark.asyncio
    async def test_run_failure_exit_code_preserved(self, tmp_path: Path) -> None:
        """失败命令退出码必须透传（真实 shell，LLM 靠 exit_code 判断失败；回归：包装后恒 0）。"""
        s = SandboxSession(tmp_path)
        with bind_command_runner(PassthroughRunner()):
            result = await s.run('python -c "import sys; sys.exit(3)"', timeout=30)
        assert result.startswith("exit_code=3")

    @pytest.mark.asyncio
    async def test_run_success_exit_code_zero(self, tmp_path: Path) -> None:
        """成功命令退出码保持 0（修复不引入反向回归）。"""
        s = SandboxSession(tmp_path)
        with bind_command_runner(PassthroughRunner()):
            result = await s.run("echo ok_session", timeout=15)
        assert result.startswith("exit_code=0")

    @pytest.mark.asyncio
    async def test_close_keeps_workspace(self, tmp_path: Path) -> None:
        s = SandboxSession(tmp_path)
        await s.close(keep=True)
        assert tmp_path.exists()


def test_format_result_caps_oversized_stdout_and_keeps_the_tail() -> None:
    """A megabyte-scale result is capped, still marked, and its tail survives."""
    tail_marker = "HEAGENT_CWD=E:\\tmp"
    stdout = b"x" * (600 * 1024) + tail_marker.encode()
    result = _format_result(0, stdout, b"")
    assert result.startswith("exit_code=0\nstdout:\n")
    assert "[truncated]" in result
    assert result.endswith(tail_marker)
    assert len(result) < len(stdout)
    channel = result.split("stdout:\n", 1)[1]
    assert len(channel.encode("utf-8")) <= 512 * 1024


def test_format_result_caps_stderr_independently() -> None:
    result = _format_result(2, b"small", b"e" * (600 * 1024))
    assert "stdout:\nsmall" in result
    assert "stderr:\n" in result
    assert "[truncated]" in result
    channel = result.split("stderr:\n", 1)[1]
    assert len(channel.encode("utf-8")) <= 512 * 1024


@pytest.mark.asyncio
async def test_session_preserves_tail_marker_after_stdout_truncation(tmp_path: Path) -> None:
    """SandboxSession must still recover cwd and rc from a capped stdout tail."""
    marker_path = tmp_path / "nested"
    raw_stdout = b"x" * (600 * 1024) + f"\nHEAGENT_CWD 7\n{marker_path}\n".encode()

    class _Runner:
        tier = SandboxTier.PASSTHROUGH

        async def run(self, command: str, *, timeout: int) -> str:
            return _format_result(0, raw_stdout, b"")

    session = SandboxSession(tmp_path)
    with bind_command_runner(_Runner()):
        result = await session.run("echo oversized", timeout=10)

    assert session.cwd == marker_path
    assert result.startswith("exit_code=7")
    assert "HEAGENT_CWD" not in result
    assert "[truncated]" in result


def test_format_result_leaves_small_output_untouched() -> None:
    assert _format_result(1, b"ok", b"warn\n") == "exit_code=1\nstdout:\nokstderr:\nwarn\n"
    assert _format_result(None, b"", b"") == "exit_code=None\n"
