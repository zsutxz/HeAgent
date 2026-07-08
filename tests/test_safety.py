"""Tests for safety guardrails."""

from __future__ import annotations

import pytest

from heagent.exceptions import SafetyViolation
from heagent.tools.safety import SafetyGuard, SafetyMode
from heagent.types import ToolCall


def _shell_call(command: str) -> ToolCall:
    return ToolCall(id="1", name="shell", arguments={"command": command})


def _other_call() -> ToolCall:
    return ToolCall(id="2", name="file_read", arguments={"path": "/etc/hosts"})


class TestDangerousPatterns:
    @pytest.mark.parametrize(
        "cmd",
        [
            "rm -rf /",
            "rm -fr /home",
            "format C:",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda1",
            "shutdown now",
            "reboot",
            "del /s /q C:\\Windows",
            "rmdir /s /q C:\\temp",
            "chmod 000 /etc/passwd",
            "chmod -R 000 /",
            "chown root /etc/shadow",
            "chown -R root /",
        ],
    )
    def test_blocks_dangerous_commands(self, cmd: str) -> None:
        guard = SafetyGuard()
        with pytest.raises(SafetyViolation):
            guard.check(_shell_call(cmd))

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hello",
            "ls -la",
            "cat file.txt",
            "git status",
            "python script.py",
        ],
    )
    def test_allows_safe_commands(self, cmd: str) -> None:
        guard = SafetyGuard()
        guard.check(_shell_call(cmd))  # should not raise


class TestBlacklist:
    def test_blocks_blacklisted(self) -> None:
        guard = SafetyGuard(mode=SafetyMode.BLACKLIST, blocked_commands=[r"curl.*"])
        with pytest.raises(SafetyViolation):
            guard.check(_shell_call("curl http://example.com"))

    def test_allows_non_blacklisted(self) -> None:
        guard = SafetyGuard(mode=SafetyMode.BLACKLIST, blocked_commands=[r"curl.*"])
        guard.check(_shell_call("wget http://example.com"))  # no raise


class TestWhitelist:
    def test_blocks_non_whitelisted(self) -> None:
        guard = SafetyGuard(mode=SafetyMode.WHITELIST, allowed_commands=[r"git.*"])
        with pytest.raises(SafetyViolation):
            guard.check(_shell_call("npm install"))

    def test_allows_whitelisted(self) -> None:
        guard = SafetyGuard(mode=SafetyMode.WHITELIST, allowed_commands=[r"git.*"])
        guard.check(_shell_call("git status"))  # no raise

    def test_empty_whitelist_allows_all(self) -> None:
        guard = SafetyGuard(mode=SafetyMode.WHITELIST, allowed_commands=[])
        guard.check(_shell_call("anything goes"))  # no raise


class TestNonShellTools:
    def test_non_shell_always_passes(self) -> None:
        guard = SafetyGuard(mode=SafetyMode.BLACKLIST, blocked_commands=[r".*"])
        guard.check(_other_call())  # no raise — only shell is checked


class TestBlockedTools:
    """工具名 blacklist：对所有工具生效（MCP/内置/shell），spec DP-4。"""

    def test_default_empty_zero_regression(self) -> None:
        # 默认 blocked_tools=[]，MCP 工具不抛——与改动前行为逐字节一致
        guard = SafetyGuard()
        guard.check(ToolCall(id="1", name="github__list_issues", arguments={}))

    def test_blocks_matching_mcp_tool(self) -> None:
        guard = SafetyGuard(blocked_tools=[r"github__delete_.*"])
        with pytest.raises(SafetyViolation):
            guard.check(ToolCall(id="1", name="github__delete_issue", arguments={"n": 1}))

    def test_allows_non_matching_mcp_tool(self) -> None:
        guard = SafetyGuard(blocked_tools=[r"github__delete_.*"])
        guard.check(ToolCall(id="1", name="github__list_issues", arguments={}))  # no raise

    def test_tool_name_block_covers_shell(self) -> None:
        # blocked_tools=["shell"] 命中 shell 工具名，先于 command 危险模式检查
        guard = SafetyGuard(blocked_tools=[r"shell"])
        with pytest.raises(SafetyViolation):
            guard.check(_shell_call("echo safe"))

    def test_block_message_names_tool(self) -> None:
        guard = SafetyGuard(blocked_tools=[r"github__delete_.*"])
        with pytest.raises(SafetyViolation, match="Blocked tool by name"):
            guard.check(ToolCall(id="1", name="github__delete_issue", arguments={}))


class TestViolationLog:
    def test_violations_recorded(self) -> None:
        guard = SafetyGuard()
        with pytest.raises(SafetyViolation):
            guard.check(_shell_call("rm -rf /"))
        assert len(guard.violations) == 1
        assert "rm -rf /" in guard.violations[0]
