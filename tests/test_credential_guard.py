"""Tests for credential deny + env scrubbing (file-safety-hardening 周期)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from heagent.engine.policy import PolicyEngine, ToolExecutionMode
from heagent.tools.builtins.file import file_read, file_write
from heagent.tools.path_safety import (
    build_internal_state_dirs,
    build_read_denied_basenames,
    build_write_denied_paths,
    build_write_denied_prefixes,
    check_read_denied,
    check_write_denied,
    reset_workspace_root,
    set_workspace_root,
)
from heagent.tools.sandbox import scrub_sensitive_env
from heagent.exceptions import SafetyViolation
from heagent.tools.safety import SafetyGuard
from heagent.types import ToolCall

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path) -> Generator[None, None, None]:
    set_workspace_root(tmp_path.resolve())
    yield
    reset_workspace_root()


# ── FR-F1 / FR-F2 / FR-F4：deny 规则纯函数 ──────────────────────────


class TestDenyRuleBuilders:
    def test_build_write_denied_paths_contains_ssh_keys(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        paths = build_write_denied_paths()
        assert str((tmp_path / ".ssh" / "id_rsa").resolve()) in paths
        assert str((tmp_path / ".ssh" / "authorized_keys").resolve()) in paths
        assert str((tmp_path / ".env").resolve()) in paths
        assert str((tmp_path / ".netrc").resolve()) in paths

    def test_build_write_denied_prefixes_contains_dirs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        prefixes = build_write_denied_prefixes()
        assert str((tmp_path / ".ssh").resolve()) + os.sep in prefixes
        assert str((tmp_path / ".aws").resolve()) + os.sep in prefixes
        assert str((tmp_path / ".kube").resolve()) + os.sep in prefixes

    def test_build_read_denied_basenames(self) -> None:
        names = build_read_denied_basenames()
        assert ".env" in names
        assert ".env.local" in names
        assert ".env.production" in names
        assert ".envrc" in names

    def test_build_internal_state_dirs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        dirs = build_internal_state_dirs()
        assert str(tmp_path / ".heagent" / "sessions") in dirs
        assert str(tmp_path / ".heagent" / "ledger") in dirs
        assert str(tmp_path / ".heagent" / "runs") in dirs
        assert str(tmp_path / ".heagent" / "memory") in dirs
        assert str(tmp_path / ".heagent" / "skills") in dirs


# ── FR-F1 / FR-F2 / FR-F4：check 函数 ──────────────────────────────


class TestCheckWriteDenied:
    def test_exact_match(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert check_write_denied(str(tmp_path / ".ssh" / "id_rsa")) is not None
        assert check_write_denied(str(tmp_path / ".env")) is not None

    def test_prefix_match(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert check_write_denied(str(tmp_path / ".aws" / "credentials")) is not None

    def test_not_denied(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert check_write_denied(str(tmp_path / "project" / "notes.txt")) is None


class TestCheckReadDenied:
    def test_env_basename(self) -> None:
        assert check_read_denied(".env") is not None
        assert check_read_denied("/some/where/.env.production") is not None
        assert check_read_denied(".envrc") is not None

    def test_internal_state_exact_and_subpath(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert check_read_denied(str(tmp_path / ".heagent" / "sessions")) is not None
        assert check_read_denied(str(tmp_path / ".heagent" / "sessions" / "abc.json")) is not None
        assert check_read_denied(str(tmp_path / ".heagent" / "ledger" / "x.json")) is not None

    def test_not_denied(self, tmp_path: Path) -> None:
        assert check_read_denied(str(tmp_path / "notes.txt")) is None


# ── FR-F3：env scrubbing ──────────────────────────────────────────


class TestScrubSensitiveEnv:
    def test_strips_sensitive_keys(self) -> None:
        env = {
            "DEEPSEEK_API_KEY": "sk-xxx",
            "OPENAI_API_KEY": "sk-yyy",
            "GH_TOKEN": "ghp_zzz",
            "DB_PASSWORD": "secret",
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "LANG": "en_US.UTF-8",
        }
        result = scrub_sensitive_env(env)
        assert "DEEPSEEK_API_KEY" not in result
        assert "OPENAI_API_KEY" not in result
        assert "GH_TOKEN" not in result
        assert "DB_PASSWORD" not in result
        assert result["PATH"] == "/usr/bin"
        assert result["HOME"] == "/home/user"
        assert result["LANG"] == "en_US.UTF-8"

    def test_case_insensitive(self) -> None:
        env = {"deepseek_api_key": "x", "PATH": "/usr/bin"}
        result = scrub_sensitive_env(env)
        assert "deepseek_api_key" not in result
        assert "PATH" in result

    def test_keeps_nonsensitive(self) -> None:
        env = {"EDITOR": "vim", "SHELL": "/bin/bash"}
        result = scrub_sensitive_env(env)
        assert result == {"EDITOR": "vim", "SHELL": "/bin/bash"}

    def test_empty(self) -> None:
        assert scrub_sensitive_env({}) == {}


# ── FR-F1 / FR-F2：file handler 守卫 ───────────────────────────────


@pytest.mark.asyncio
class TestFileHandlerDeny:
    async def test_file_read_denies_env(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=sk-xxx", encoding="utf-8")
        result = await file_read(".env")
        assert "Error" in result
        assert "secret-bearing" in result
        assert "sk-xxx" not in result

    async def test_file_read_allows_normal_file(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
        result = await file_read("notes.txt")
        assert result == "hello"

    async def test_file_write_denies_ssh_key(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        result = await file_write(str(tmp_path / ".ssh" / "id_rsa"), "malicious")
        assert "Error" in result
        assert "protected" in result
        assert not (tmp_path / ".ssh" / "id_rsa").exists()

    async def test_file_read_denies_internal_state(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        session_file = tmp_path / ".heagent" / "sessions" / "s.json"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text('{"secret": true}', encoding="utf-8")
        result = await file_read(str(session_file))
        assert "Error" in result
        assert "internal HeAgent state" in result


# ── FR-F1 / FR-F2：policy 预检 ─────────────────────────────────────


class TestPolicyDenyPrecheck:
    def test_policy_blocks_env_read(self, tmp_path: Path) -> None:
        policy = PolicyEngine(workspace_root=str(tmp_path))
        call = ToolCall(id="1", name="file_read", arguments={"path": ".env"})
        verdict = policy.evaluate_tool_call(call)
        assert verdict.mode is ToolExecutionMode.BLOCKED
        assert "secret-bearing" in verdict.reason

    def test_policy_blocks_ssh_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        policy = PolicyEngine(workspace_root=str(tmp_path))
        call = ToolCall(id="1", name="file_write", arguments={"path": str(tmp_path / ".ssh" / "id_rsa")})
        verdict = policy.evaluate_tool_call(call)
        assert verdict.mode is ToolExecutionMode.BLOCKED

    def test_policy_allows_normal_read(self, tmp_path: Path) -> None:
        policy = PolicyEngine(workspace_root=str(tmp_path))
        call = ToolCall(id="1", name="file_read", arguments={"path": "notes.txt"})
        verdict = policy.evaluate_tool_call(call)
        assert verdict.mode is ToolExecutionMode.DIRECT

    def test_policy_deny_independent_of_fence(self, tmp_path: Path) -> None:
        # .env 在 workspace 内（不越界），仍因 deny 而 BLOCKED —— deny 不依赖围栏
        policy = PolicyEngine(workspace_root=str(tmp_path))
        call = ToolCall(id="1", name="file_read", arguments={"path": ".env"})
        verdict = policy.evaluate_tool_call(call)
        assert verdict.mode is ToolExecutionMode.BLOCKED
        assert "secret-bearing" in verdict.reason


# ── SafetyGuard 凭证路径破坏性命令拦截（Epic 36 延伸）────────────────


def _shell_call(command: str) -> ToolCall:
    return ToolCall(id="s", name="shell", arguments={"command": command})


class TestCredentialDestructiveCommand:
    @pytest.mark.parametrize(
        "cmd",
        [
            "rm ~/.ssh/id_rsa",
            "rm /home/user/.ssh/authorized_keys",
            "rm ~/.aws/credentials",
            "mv ~/.ssh/id_rsa /tmp/steal",
            "mv /tmp/evil ~/.ssh/authorized_keys",
            "rmdir ~/.gnupg",
            "unlink ~/.netrc",
            "rm /project/.env",
            "rm /etc/sudoers",
        ],
    )
    def test_blocks_credential_destructive(self, cmd: str) -> None:
        guard = SafetyGuard()
        with pytest.raises(SafetyViolation):
            guard.check(_shell_call(cmd))

    def test_blocks_redirect_overwrite_credential(self) -> None:
        guard = SafetyGuard()
        with pytest.raises(SafetyViolation):
            guard.check(_shell_call("echo evil > ~/.ssh/authorized_keys"))

    @pytest.mark.parametrize(
        "cmd",
        [
            "rm report.txt",
            "mv report.txt /tmp/backup",
            "cp report.txt backup.txt",
            "echo hello > output.txt",
            "ls -la",
        ],
    )
    def test_allows_non_credential(self, cmd: str) -> None:
        guard = SafetyGuard()
        guard.check(_shell_call(cmd))  # 不应抛异常
