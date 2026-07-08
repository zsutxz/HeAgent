"""Tests for shell tool."""

from __future__ import annotations

import sys

import pytest

from heagent.tools.builtins.shell import shell
from heagent.tools.registry import ToolRegistry

_PY = f'"{sys.executable}"'


class TestShellRegistration:
    def test_shell_registered(self) -> None:
        assert "shell" in ToolRegistry.get().list_names()
        schema = ToolRegistry.get().get_schema("shell")
        assert schema is not None
        assert "command" in str(schema.parameters)

    def test_shell_has_timeout_default(self) -> None:
        schema = ToolRegistry.get().get_schema("shell")
        assert schema is not None
        props = schema.parameters["properties"]
        assert isinstance(props, dict)
        assert props["timeout"]["default"] == 120


@pytest.mark.asyncio
class TestShellExecution:
    async def test_echo(self) -> None:
        result = await shell("echo hello")
        assert "exit_code=0" in result
        assert "hello" in result

    async def test_exit_code(self) -> None:
        result = await shell(f'{_PY} -c "exit(42)"')
        assert "exit_code=42" in result

    async def test_stderr(self) -> None:
        result = await shell(
            f"{_PY} -c \"import sys; print('err', file=sys.stderr)\"",
        )
        assert "exit_code=0" in result
        assert "err" in result

    async def test_timeout(self) -> None:
        result = await shell(
            f'{_PY} -c "import time; time.sleep(10)"',
            timeout=1,
        )
        assert "exit_code=-1" in result
        assert "timed out" in result

    async def test_shell_delegates_to_bound_runner(self) -> None:
        """shell 经 get_command_runner 取后端；bind 覆盖时走覆盖后端而非默认 Passthrough。"""
        from heagent.tools.sandbox import bind_command_runner

        calls: list[str] = []

        class _RecordingRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                calls.append(command)
                return "exit_code=0\nstdout:\nrecorded"

        with bind_command_runner(_RecordingRunner()):
            result = await shell("echo hi")
        assert calls == ["echo hi"]
        assert "recorded" in result
