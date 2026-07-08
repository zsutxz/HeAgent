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


class TestFirejailBackend:
    @pytest.mark.asyncio
    async def test_run_invokes_firejail_with_expected_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """断言 FirejailBackend 用 create_subprocess_exec 启动
        [firejail, *extra, '--', 'sh', '-c', cmd]（不真跑 firejail）。"""
        captured: dict[str, list[str]] = {}

        async def fake_exec(*argv: str, stdout=None, stderr=None):
            captured["argv"] = list(argv)

            class _FakeProc:
                returncode = 0

                async def communicate(self) -> tuple[bytes, bytes]:
                    return (b"out", b"err")

            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        backend = FirejailBackend(firejail_path="firejail", extra_args=("--private-tmp",))
        result = await backend.run("ls -la", timeout=10)

        assert captured["argv"] == ["firejail", "--private-tmp", "--", "sh", "-c", "ls -la"]
        assert "exit_code=0" in result
        assert "out" in result


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
