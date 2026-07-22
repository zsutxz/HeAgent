"""Story A.3: Windows Job Objects sandbox backend 测试。"""

import asyncio
import sys

import pytest


class TestWinJobBackend:
    """WinJobBackend 基本功能测试。"""

    def test_available_on_windows(self):
        """Windows 上 available() 返回 True。"""
        from heagent.tools.sandbox import WinJobBackend

        if sys.platform == "win32":
            assert WinJobBackend.available() is True
        else:
            assert WinJobBackend.available() is False

    def test_available_class_method(self):
        """available() 为静态方法，无需实例化。"""
        from heagent.tools.sandbox import WinJobBackend

        result = WinJobBackend.available()
        assert isinstance(result, bool)

    def test_instantiation(self):
        """WinJobBackend 可实例化。"""
        from heagent.tools.sandbox import WinJobBackend

        backend = WinJobBackend()
        assert backend is not None
        assert repr(backend).startswith("WinJobBackend")

    @pytest.mark.asyncio
    async def test_run_echo_basic(self):
        """WinJobBackend.run("echo hello") → 含 hello 输出。"""
        from heagent.tools.sandbox import WinJobBackend

        backend = WinJobBackend()
        if not backend.available():
            pytest.skip("WinJobBackend not available on this platform")

        result = await backend.run("echo hello", timeout=10)
        assert "hello" in result
        assert "exit_code=0" in result

    @pytest.mark.asyncio
    async def test_run_nonzero_exit(self):
        """命令失败 → exit_code 非 0。"""
        from heagent.tools.sandbox import WinJobBackend

        backend = WinJobBackend()
        if not backend.available():
            pytest.skip("WinJobBackend not available on this platform")

        result = await backend.run("exit /b 42", timeout=10)
        assert "exit_code=42" in result

    @pytest.mark.asyncio
    async def test_run_timeout(self):
        """超时 → 返回 TIMEOUT 结果。"""
        from heagent.tools.sandbox import _TIMEOUT_RESULT, WinJobBackend

        backend = WinJobBackend()
        if not backend.available():
            pytest.skip("WinJobBackend not available on this platform")

        result = await backend.run("ping -n 30 127.0.0.1 > nul", timeout=1)
        timeout_str = _TIMEOUT_RESULT.format(timeout=1)
        assert timeout_str[:20] in result  # 超时消息前缀

    @pytest.mark.asyncio
    async def test_run_fallback_on_unavailable(self):
        """不可用平台 → fallback Passthrough（正常执行）。"""
        from heagent.tools.sandbox import WinJobBackend

        backend = WinJobBackend()
        # 即使标记 'available' 为 False 也不影响——需要 mock
        # 实际上在非 Windows 上 available() 返回 False，run 会 fallback
        if backend.available():
            pytest.skip("Test requires non-Windows or mocked unavailable")

        # 非 Windows 上 fallback 到 PassthroughRunner
        result = await backend.run("echo test", timeout=10)
        assert "test" in result

    @pytest.mark.asyncio
    async def test_cancel_kills_process(self):
        """取消 task → 子进程被 kill。"""
        from heagent.tools.sandbox import WinJobBackend

        backend = WinJobBackend()
        if not backend.available():
            pytest.skip("WinJobBackend not available on this platform")

        async def long_run():
            return await backend.run("ping -n 60 127.0.0.1 > nul", timeout=120)

        task = asyncio.create_task(long_run())
        await asyncio.sleep(0.5)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        # 不挂死即成功

    def test_command_runner_protocol(self):
        """WinJobBackend 满足 CommandRunner protocol。"""
        from heagent.tools.sandbox import WinJobBackend

        backend = WinJobBackend()
        # 结构类型检查：有 async run(command, *, timeout) 方法
        assert hasattr(backend, "run")
        assert callable(backend.run)
        import inspect

        assert inspect.iscoroutinefunction(backend.run)

    def test_repr_contains_available(self):
        """__repr__ 反映可用性。"""
        from heagent.tools.sandbox import WinJobBackend

        backend = WinJobBackend()
        r = repr(backend)
        assert "WinJobBackend" in r
        assert "available" in r
