"""Tests for safety guardrails."""

from __future__ import annotations

import logging

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
            "echo x | dd if=/dev/zero of=/dev/sda",
            "sudo dd if=/dev/zero of=/dev/sda",
            "cd /tmp; dd if=/dev/zero of=/dev/sda",
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
            # 回归（2026-09-21）：'yyyy/MM/dd' 中的 dd 不再命中 \bdd\b 误伤只读 powershell 命令
            "powershell -NoProfile -Command \"Get-Date -Format 'yyyy/MM/dd HH:mm:ss'; "
            "Get-ChildItem 'E:\\proj\\Temp' -Force | Out-String\"",
        ],
    )
    def test_allows_safe_commands(self, cmd: str) -> None:
        guard = SafetyGuard()
        guard.check(_shell_call(cmd))  # should not raise


class TestInlineInterpreterCommands:
    """内联解释器（python -c / perl -e 等）不再整条禁（P1-15 修订 2026-09-19）：
    良性载荷放行；危险载荷无需专门机制——payload 是整条命令的子串，仍被第一层
    整条命令扫描命中拦截。"""

    @pytest.mark.parametrize(
        "cmd",
        [
            # 运行时误拦的原始三条（2026-09-19 日志回归）
            'cmd /c "date /t & time /t"; python -c "import datetime;print(datetime.datetime.now().isoformat())" 2>&1',
            "python -c \"import datetime;print('NOW', datetime.datetime.now().isoformat())\"",
            "python -c \"import urllib.request,json;d=json.load(urllib.request.urlopen('https://api.github.com'))\"",
            # 解释器变体
            'python3 -c "import datetime;print(datetime.date.today())"',
            "perl -e 'print 42'",
            "php -r 'echo json_encode([1]);'",
        ],
    )
    def test_allows_benign_inline_code(self, cmd: str) -> None:
        guard = SafetyGuard()
        guard.check(_shell_call(cmd))  # no raise

    @pytest.mark.parametrize(
        "cmd",
        [
            "python -c \"import os;os.system('shutdown now')\"",
            "python3 -c \"import os;os.system('rm -rf /tmp/x')\"",
            "perl -e \"system('reboot')\"",
            "ruby -e \"exec 'mkfs.ext4 /dev/sda1'\"",
            "php -r \"shell_exec('chmod 777 /etc');\"",
            "python -c \"os.system('mv id_rsa /tmp/x')\"",  # 凭证路径破坏经由内联代码
            "python -c shutdown",  # 裸载荷（无引号）同样命中
            'echo hi; python -c "print(1)"; python -c "import os;os.system(\'halt\')"',
        ],
    )
    def test_blocks_dangerous_inline_code(self, cmd: str) -> None:
        guard = SafetyGuard()
        # 第一层危险模式或第一层半凭证层任一命中即拦
        with pytest.raises(SafetyViolation, match="Blocked (dangerous|credential-path destructive) command"):
            guard.check(_shell_call(cmd))

    def test_block_message_contains_payload(self) -> None:
        guard = SafetyGuard()
        with pytest.raises(SafetyViolation, match="shutdown now"):
            guard.check(_shell_call("python -c \"import os;os.system('shutdown now')\""))


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

    def test_block_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """拦截轨迹可观测：全部拦截分支经 _block 单点收口同步落 warning。"""
        guard = SafetyGuard()
        with caplog.at_level(logging.WARNING, logger="heagent.tools.safety"), pytest.raises(SafetyViolation):
            guard.check(_shell_call("rm -rf /"))
        assert any("SafetyGuard blocked" in rec.getMessage() for rec in caplog.records)
