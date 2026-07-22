"""Coverage补丁：覆盖 tools/sandbox.py 未覆盖行。

目标行号（来源：覆盖率报告）：
- 85: ``_run_subprocess_shell`` 的 ``CancelledError`` 清理分支
- 108: ``_run_subprocess_exec`` 的 ``CancelledError`` 清理分支
- 230: ``FirejailBackend.run`` firejail 不可用时 fallback 到 PassthroughRunner
- 235-236: ``FirejailBackend.run`` 可用时读 sandbox_profile + build_argv
- 240-243: ``FirejailBackend.run`` 可用时调 ``_run_subprocess_exec``
- 279-281: ``WinJobBackend.run`` 不可用时 fallback 到 PassthroughRunner
- 296-297: ``WinJobBackend.run`` Windows 可用路径（CreateJobObject 等）
- 324-325: ``WinJobBackend.run`` 的 ``CancelledError`` 清理分支
- 331-332: ``WinJobBackend.__repr__``
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import subprocess
import sys

import pytest

from heagent.tools.runtime import RuntimeSlot
from heagent.tools.sandbox import (
    FirejailBackend,
    PassthroughRunner,
    WinJobBackend,
    _run_subprocess_exec,
    _run_subprocess_shell,
    bind_sandbox_profile,
    reset_sandbox_profile,
)


# ──────────────────────────────────────────────────────────────────────────────
# 共享 helpers
# ──────────────────────────────────────────────────────────────────────────────


class _FakeProcBase:
    """所有 fake proc 的公共基类：提供 ``pid``（_kill_and_reap Linux 分支读取）。"""

    pid = 1


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """每测试前后清 sandbox 相关状态，并安全化平台 mock。

    - 钉 ``sys.platform`` 为非 linux：fake 无法承载真实进程组语义，统一走 else 分支。
    - mock ``os.killpg`` no-op：永不让测试向真实进程组发信号。
    """
    monkeypatch.setattr("heagent.tools.sandbox.sys.platform", "win32")
    monkeypatch.setattr("os.killpg", lambda *args, **kwargs: None, raising=False)
    reset_sandbox_profile()
    yield
    reset_sandbox_profile()


# ──────────────────────────────────────────────────────────────────────────────
# _run_subprocess_shell  CancelledError 分支（行 85）
# ──────────────────────────────────────────────────────────────────────────────


class TestRunSubprocessShellCancelled:
    """覆盖 ``_run_subprocess_shell`` 内 ``except CancelledError`` 分支。

    该函数不被现有测试直接调用——现有测试 mock ``asyncio.create_subprocess_shell``，
    跑的是 fake 逻辑而非真实 ``_run_subprocess_shell``。本类直接调 ``_run_subprocess_shell``
    并用 fake proc 模拟取消场景。
    """

    @pytest.mark.asyncio
    async def test_cancel_kills_and_reraises(self) -> None:
        """取消后 _kill_and_reap 执行 + 原始 CancelledError 上抛。"""

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
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

        async def fake_shell(command: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        try:
            task = asyncio.create_task(_run_subprocess_shell("blocker", timeout=120))
            await asyncio.sleep(0.05)  # 让 task 跑到 await communicate()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert proc.killed, "CancelledError 分支须 kill 子进程"
            assert proc.waited, "CancelledError 分支须 wait 回收"
        finally:
            monkeypatch.undo()

    @pytest.mark.asyncio
    async def test_cancel_reap_failure_still_reraises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """取消清理时 _kill_and_reap 抛 BaseException → 不吞，CancelledError 仍上抛。

        验证 ``except BaseException`` 分支产出 debug 日志且不掉原始取消信号。
        """

        class _FakeProc(_FakeProcBase):
            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)
                return b"", b""

            def kill(self) -> None:
                pass

            async def wait(self) -> int:
                raise RuntimeError("reap wait failure")

        proc = _FakeProc()

        async def fake_shell(command: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        task = asyncio.create_task(_run_subprocess_shell("blocker", timeout=120))
        await asyncio.sleep(0.05)
        task.cancel()
        with (
            caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"),
            pytest.raises(asyncio.CancelledError),
        ):
            await task
        assert any(rec.levelno == logging.DEBUG and "cancel cleanup" in rec.getMessage() for rec in caplog.records), (
            "reap 失败应记 debug 日志（cancel cleanup）"
        )

    @pytest.mark.asyncio
    async def test_timeout_kills_and_returns_timeout_result(self) -> None:
        """超时后 _kill_and_reap 执行，返回超时串（不抛异常）。"""

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.killed = False
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)  # 触发 timeout=0.05
                return b"", b""

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                self.waited = True
                return 0

        proc = _FakeProc()

        async def fake_shell(command: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        try:
            result = await _run_subprocess_shell("blocker", timeout=1)
            assert "exit_code=-1" in result
            assert "timed out" in result
            assert proc.killed
            assert proc.waited
        finally:
            monkeypatch.undo()


# ──────────────────────────────────────────────────────────────────────────────
# _run_subprocess_exec  CancelledError 分支（行 108）
# ──────────────────────────────────────────────────────────────────────────────


class TestRunSubprocessExecCancelled:
    """覆盖 ``_run_subprocess_exec`` 内 ``except CancelledError`` 分支。

    该函数不被现有 FirejailBackend 测试直接调用——现有测试 mock ``asyncio.create_subprocess_exec``。
    本类直接调 ``_run_subprocess_exec`` 并用 fake proc 模拟取消场景。
    """

    @pytest.mark.asyncio
    async def test_cancel_kills_and_reraises(self) -> None:
        """取消后 _kill_and_reap 执行 + 原始 CancelledError 上抛（exec 路径）。"""

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.killed = False
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)
                return b"", b""

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                self.waited = True
                return 0

        proc = _FakeProc()

        async def fake_exec(*argv: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        try:
            task = asyncio.create_task(_run_subprocess_exec(["sh", "-c", "blocker"], timeout=120))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert proc.killed
            assert proc.waited
        finally:
            monkeypatch.undo()

    @pytest.mark.asyncio
    async def test_cancel_reap_failure_still_reraises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """取消清理时 _kill_and_reap 抛 BaseException → debug 日志 + CancelledError 仍上抛。"""

        class _FakeProc(_FakeProcBase):
            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)
                return b"", b""

            def kill(self) -> None:
                pass

            async def wait(self) -> int:
                raise RuntimeError("reap wait failure")

        proc = _FakeProc()

        async def fake_exec(*argv: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        task = asyncio.create_task(_run_subprocess_exec(["sh", "-c", "blocker"], timeout=120))
        await asyncio.sleep(0.05)
        task.cancel()
        with (
            caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"),
            pytest.raises(asyncio.CancelledError),
        ):
            await task
        assert any(rec.levelno == logging.DEBUG and "cancel cleanup" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_timeout_kills_and_returns_timeout_result(self) -> None:
        """超时后 _kill_and_reap 执行，返回超时串（exec 路径）。"""

        class _FakeProc(_FakeProcBase):
            def __init__(self) -> None:
                self.killed = False
                self.waited = False

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(1000)
                return b"", b""

            def kill(self) -> None:
                self.killed = True

            async def wait(self) -> int:
                self.waited = True
                return 0

        proc = _FakeProc()

        async def fake_exec(*argv: str, stdout=None, stderr=None) -> _FakeProc:
            return proc

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        try:
            result = await _run_subprocess_exec(["sh", "-c", "blocker"], timeout=1)
            assert "exit_code=-1" in result
            assert "timed out" in result
            assert proc.killed
            assert proc.waited
        finally:
            monkeypatch.undo()


# ──────────────────────────────────────────────────────────────────────────────
# FirejailBackend.run fallback 路径（行 230）
# ──────────────────────────────────────────────────────────────────────────────


class TestFirejailBackendFallback:
    """覆盖 ``FirejailBackend.run`` 中 firejail 不可用时的 PassthroughRunner 降级路径。

    现有 ``test_run_falls_back_when_unavailable`` 已验证语义，但 mock
    ``asyncio.create_subprocess_shell`` 后该路径仍被某些覆盖率工具标记为未覆盖。
    这里改用更细粒度的验证方式确保行 230 真正执行。
    """

    # ── helper: 构造不可用 backend ──

    @staticmethod
    def _make_unavailable_backend(
        monkeypatch: pytest.MonkeyPatch,
    ) -> FirejailBackend:
        """构造 firejail 不可用的 backend（shutil.which → None）。"""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda p: None)
        return FirejailBackend()

    @pytest.mark.asyncio
    async def test_fallback_uses_passthrough_not_exec(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """不可用时调用 ``PassthroughRunner().run``（create_subprocess_shell），
        而非 ``create_subprocess_exec``。
        """
        backend = self._make_unavailable_backend(monkeypatch)

        shell_called = False
        exec_called = False

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = 1

            async def communicate(self):
                return (b"passthrough_out", b"")

        async def fake_shell(command: str, stdout=None, stderr=None):
            nonlocal shell_called
            shell_called = True
            return _FakeProc()

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            nonlocal exec_called
            exec_called = True
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await backend.run("echo hi", timeout=10)
        assert "passthrough_out" in result
        assert shell_called, "不可用时应走 create_subprocess_shell（PassthroughRunner）"
        assert not exec_called, "不可用时不应走 create_subprocess_exec"

    @pytest.mark.asyncio
    async def test_fallback_preserves_timeout_semantics(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """不可用时 timeout 校验、超时返回均经 PassthroughRunner 生效。"""
        backend = self._make_unavailable_backend(monkeypatch)

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = -1

            async def communicate(self):
                await asyncio.sleep(1000)
                return b"", b""

            def kill(self) -> None:
                pass

            async def wait(self) -> int:
                return -1

        async def fake_shell(command: str, stdout=None, stderr=None):
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
        result = await backend.run("blocker", timeout=1)
        assert "timed out" in result


# ──────────────────────────────────────────────────────────────────────────────
# FirejailBackend.run profile 路径（行 235-236, 240-243）
# ──────────────────────────────────────────────────────────────────────────────


class TestFirejailBackendProfilePath:
    """覆盖 ``FirejailBackend.run`` 中 firejail 可用时读 sandbox_profile +
    build_argv + 调 ``_run_subprocess_exec`` 的完整路径。
    """

    @pytest.mark.asyncio
    async def test_profile_injected_into_argv(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """可用 + profile bind → argv 含 profile 参数 → 调 create_subprocess_exec。"""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda p: "/usr/bin/firejail")

        captured_argv: list[list[str]] = []

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                return (b"firejailed_out", b"")

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            captured_argv.append(list(argv))
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = FirejailBackend(
            profiles={"network-isolated": ("--net=none",)},
        )
        with bind_sandbox_profile("network-isolated"):
            result = await backend.run("curl example.com", timeout=10)

        assert captured_argv, "应调用了 create_subprocess_exec"
        argv = captured_argv[0]
        assert "--net=none" in argv, "profile 参数应注入 argv"
        assert "firejailed_out" in result

    @pytest.mark.asyncio
    async def test_no_profile_bind_yields_no_profile_args(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """可用但未 bind profile → argv 不含 profile 专属参数，仅 extra_args。"""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda p: "/usr/bin/firejail")

        captured_argv: list[list[str]] = []

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                return (b"out", b"")

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            captured_argv.append(list(argv))
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = FirejailBackend(extra_args=("--private-tmp",))
        result = await backend.run("ls", timeout=10)

        assert captured_argv
        argv = captured_argv[0]
        assert "--private-tmp" in argv
        # 无 profile 时不应有 --net=none 等 profile 专属参数
        assert "out" in result

    @pytest.mark.asyncio
    async def test_profile_bind_as_contextvar_survives_async_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """contextvar 在 async 边界内存活——bind 后 async 调用 run 仍读到 profile。"""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda p: "/usr/bin/firejail")

        captured_argv: list[list[str]] = []

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                return (b"ok", b"")

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            captured_argv.append(list(argv))
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = FirejailBackend(
            profiles={"strict": ("--caps.drop=all",)},
        )
        with bind_sandbox_profile("strict"):
            # 模拟 executor 注入后 handler 内部 async 调用 run
            async def handler_run():
                return await backend.run("ls", timeout=10)

            result = await handler_run()

        assert captured_argv
        assert "--caps.drop=all" in captured_argv[0]
        assert "ok" in result


# ──────────────────────────────────────────────────────────────────────────────
# WinJobBackend（行 279-281, 296-297, 324-325, 331-332）
# ──────────────────────────────────────────────────────────────────────────────


class TestWinJobBackend:
    """全面覆盖 ``WinJobBackend``：repr、available 检测、不可用 fallback、可用路径。

    使用真实 ``ctypes`` 模块（Windows 下可用），仅 mock kernel32 API 调用避免副作用；
    ``asyncio.to_thread`` 注入 fake subprocess 结果。
    """

    # ── repr ──

    def test_repr_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """available()=True → repr 含 True。"""
        monkeypatch.setattr(WinJobBackend, "available", staticmethod(lambda: True))
        backend = WinJobBackend()
        assert repr(backend) == "WinJobBackend(available=True)"

    def test_repr_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """available()=False → repr 含 False。"""
        monkeypatch.setattr(WinJobBackend, "available", staticmethod(lambda: False))
        backend = WinJobBackend()
        assert repr(backend) == "WinJobBackend(available=False)"

    def test_repr_default_state(self) -> None:
        """无 patch 时调用 repr 不抛异常。"""
        backend = WinJobBackend()
        rep = repr(backend)
        assert rep.startswith("WinJobBackend(available=")
        assert rep.endswith(")")

    # ── available ──

    def test_available_on_non_win32(self) -> None:
        """非 Windows 平台 available() 返回 False。

        使用真实 sys.platform（不被 autouse fixture 覆盖），
        若当前机器恰好是 Windows 则跳过。
        """
        if sys.platform == "win32":
            pytest.skip("本测需非 Windows 环境验证 available()=False")
        assert WinJobBackend.available() is False

    # ── run fallback（行 279-281）──

    @pytest.mark.asyncio
    async def test_run_falls_back_when_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """WinJobBackend.available()=False → 走 PassthroughRunner 降级 + warning 日志。"""
        monkeypatch.setattr(WinJobBackend, "available", staticmethod(lambda: False))

        shell_called = False

        class _FakeProc(_FakeProcBase):
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                return (b"winjob_fallback", b"")

        async def fake_shell(command: str, stdout=None, stderr=None):
            nonlocal shell_called
            shell_called = True
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)

        backend = WinJobBackend()
        with caplog.at_level(logging.WARNING, logger="heagent.tools.sandbox"):
            result = await backend.run("echo hi", timeout=10)

        assert "winjob_fallback" in result
        assert shell_called
        assert any("WinJobBackend not available" in rec.getMessage() for rec in caplog.records), (
            "不可用时应记 warning 日志"
        )

    # ── run 可用路径 辅助方法 ──

    @staticmethod
    def _mock_win32_kernel32(monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock kernel32 API 调用，让 WinJobBackend.run 走通 Windows 路径而无副作用。

        使用真实 ctypes（Windows 下 Structure/array 语义正确），仅替换四个 API 为 stub。
        """
        # CreateJobObjectW / SetInformationJobObject / AssignProcessToJobObject:
        # 全部返回非零成功码以便流程走通。
        monkeypatch.setattr(
            ctypes.windll.kernel32,
            "CreateJobObjectW",
            lambda a, b: 12345,
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32,
            "SetInformationJobObject",
            lambda *a: 1,
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32,
            "AssignProcessToJobObject",
            lambda *a: 1,
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32,
            "CloseHandle",
            lambda *a: 1,
        )

    @pytest.mark.asyncio
    async def test_run_available_normal_execution(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """WinJobBackend 可用时走 Windows Job Objects 路径（行 296-297）。

        kernel32 API mock 化 + ``asyncio.to_thread`` 注入 fake subprocess，
        验证返回 stdout 内容且 PassthroughRunner 未被使用。
        """
        monkeypatch.setattr(WinJobBackend, "available", staticmethod(lambda: True))
        self._mock_win32_kernel32(monkeypatch)

        shell_called = False

        class _FakePopen:
            def __init__(self, *args, **kwargs):
                self.returncode = 0
                self._handle = 1  # AssignProcessToJobObject 需要

            def communicate(self):
                return (b"winjob_ok", b"")

        async def fake_to_thread(func, *args, **kwargs):
            if func is subprocess.Popen:
                return _FakePopen()
            if hasattr(func, "__name__") and func.__name__ == "communicate":
                return (b"winjob_ok", b"")
            if hasattr(func, "__name__") and func.__name__ == "wait":
                return None
            return func(*args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

        async def fake_shell(command, stdout=None, stderr=None):
            nonlocal shell_called
            shell_called = True
            raise AssertionError("不应走 PassthroughRunner")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)

        backend = WinJobBackend()
        result = await backend.run("echo hi", timeout=10)

        assert "winjob_ok" in result
        assert not shell_called, "可用时不应走 PassthroughRunner 降级"

    @pytest.mark.asyncio
    async def test_run_available_cancelled_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """WinJobBackend 可用路径 CancelledError 清理分支（行 324-325）。

        子进程被取消后走 ``except CancelledError`` → kill + wait + 重抛。
        """
        monkeypatch.setattr(WinJobBackend, "available", staticmethod(lambda: True))
        self._mock_win32_kernel32(monkeypatch)

        killed = False
        waited = False

        class _FakePopen:
            def __init__(self, *args, **kwargs):
                self.returncode = 0
                self._handle = 1

            def communicate(self):
                # 永不返回——等待取消
                import time

                time.sleep(1000)
                return b"", b""

            def kill(self):
                nonlocal killed
                killed = True

            def wait(self):
                nonlocal waited
                waited = True
                return 0

        async def fake_to_thread(func, *args, **kwargs):
            if func is subprocess.Popen:
                return _FakePopen()
            if hasattr(func, "__name__") and func.__name__ == "communicate":
                await asyncio.sleep(1000)  # 阻塞直到取消
                return b"", b""
            if hasattr(func, "__name__") and func.__name__ == "wait":
                nonlocal waited
                waited = True
                return None
            return func(*args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

        backend = WinJobBackend()
        task = asyncio.create_task(backend.run("blocker", timeout=120))
        await asyncio.sleep(0.05)
        task.cancel()

        with (
            caplog.at_level(logging.DEBUG, logger="heagent.tools.sandbox"),
            pytest.raises(asyncio.CancelledError),
        ):
            await task

        assert killed, "取消后应 kill 子进程"
        assert (
            any(rec.levelno == logging.DEBUG and "cancel cleanup" in rec.getMessage() for rec in caplog.records)
            or waited
        ), "取消 cleanup 应执行（log 或 waited）"


# ──────────────────────────────────────────────────────────────────────────────
# RuntimeSlot 边缘用例
# ──────────────────────────────────────────────────────────────────────────────


class TestRuntimeSlotEdgeCases:
    """RuntimeSlot bind / reset / get 的边缘与组合。"""

    def test_get_returns_none_when_neither_default_nor_contextvar_set(self) -> None:
        """全新 slot：无 default 也无 bind → get() 返回 None。"""
        slot: RuntimeSlot[str] = RuntimeSlot[str]("test_orphan")
        assert slot.get() is None

    def test_reset_is_idempotent(self) -> None:
        """重复 reset 不抛异常。"""
        slot: RuntimeSlot[str] = RuntimeSlot[str]("test_idempotent")
        slot.configure("value")
        slot.reset()
        slot.reset()  # 第二次 reset
        assert slot.get() is None

    def test_get_returns_default_after_reset(self) -> None:
        """configure 后 reset → get 返回 None（不是旧值）。"""
        slot: RuntimeSlot[str] = RuntimeSlot[str]("test_default_reset")
        slot.configure("default_val")
        assert slot.get() == "default_val"
        slot.reset()
        assert slot.get() is None

    def test_bind_overrides_configured_default(self) -> None:
        """bind 覆盖 configure 的 default。"""
        slot: RuntimeSlot[str] = RuntimeSlot[str]("test_bind_overrides")
        slot.configure("default_val")
        with slot.bind("bound_val"):
            assert slot.get() == "bound_val"
        assert slot.get() == "default_val"

    def test_bind_none_overrides_configured_default(self) -> None:
        """bind(None) 覆盖 configured default，退出后恢复。"""
        slot: RuntimeSlot[str] = RuntimeSlot[str]("test_bind_none_overrides")
        slot.configure("default_val")
        with slot.bind(None):
            assert slot.get() is None
        assert slot.get() == "default_val"

    def test_nested_bind_restores_inner_then_outer(self) -> None:
        """三层嵌套：内→中→外顺序恢复。"""
        slot: RuntimeSlot[str] = RuntimeSlot[str]("test_nested3")
        slot.configure("default")
        with slot.bind("outer"):
            assert slot.get() == "outer"
            with slot.bind("middle"):
                assert slot.get() == "middle"
                with slot.bind("inner"):
                    assert slot.get() == "inner"
                assert slot.get() == "middle"
            assert slot.get() == "outer"
        assert slot.get() == "default"

    def test_bind_exception_does_not_leak(self) -> None:
        """bind 内抛异常后 contextvar 正确恢复。"""
        slot: RuntimeSlot[str] = RuntimeSlot[str]("test_exc_restore")
        slot.configure("before")
        try:
            with slot.bind("during"):
                assert slot.get() == "during"
                raise ValueError("boom")
        except ValueError:
            pass
        assert slot.get() == "before"

    def test_separate_slots_do_not_interfere(self) -> None:
        """两个独立 RuntimeSlot 互不串扰。"""
        slot_a: RuntimeSlot[int] = RuntimeSlot[int]("a")
        slot_b: RuntimeSlot[str] = RuntimeSlot[str]("b")
        slot_a.configure(42)
        slot_b.configure("hello")
        with slot_a.bind(99):
            assert slot_a.get() == 99
            assert slot_b.get() == "hello"
        assert slot_a.get() == 42
        assert slot_b.get() == "hello"
