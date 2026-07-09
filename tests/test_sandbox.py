"""Tests for command runner sandbox backends (``tools/sandbox.py``)."""

from __future__ import annotations

import asyncio
import sys

import pytest

from heagent.tools.sandbox import (
    FirejailBackend,
    PassthroughRunner,
    bind_command_runner,
    configure_command_runner,
    get_command_runner,
    reset_command_runner,
)

_PY = f'"{sys.executable}"'


@pytest.fixture(autouse=True)
def _isolate_command_runner():
    """每测试前后清进程级 fallback，防 ``configure`` 串扰。"""
    reset_command_runner()
    yield
    reset_command_runner()


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

        class _FakeProc:
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
        captured: dict[str, list[str]] = {}

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            captured["argv"] = list(argv)

            class _FakeProc:
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

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            raise AssertionError("timeout<=0 不应 spawn firejail 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        backend = FirejailBackend()
        with pytest.raises(ValueError, match=r"got 0$"):
            await backend.run("ls", timeout=0)

    @pytest.mark.asyncio
    async def test_timeout_negative_raises_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D3：负 timeout 在 exec 前同样抛 ``ValueError``（spec 要求 Passthrough + exec 两路径）。"""

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            raise AssertionError("负 timeout 不应 spawn firejail 子进程")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        backend = FirejailBackend()
        with pytest.raises(ValueError, match=r"got -5$"):
            await backend.run("ls", timeout=-5)


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
