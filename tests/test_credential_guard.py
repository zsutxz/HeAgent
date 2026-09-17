"""Tests for credential deny + env scrubbing (file-safety-hardening 周期)."""

from __future__ import annotations

import logging
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

    def test_allowlist_keeps_exempted_sensitive(self) -> None:
        """FR-3: allowlist 命中的敏感变量保留，其余仍剥离。"""
        env = {"GITHUB_TOKEN": "ghp_xxx", "OPENAI_API_KEY": "sk-yyy"}
        result = scrub_sensitive_env(env, allowlist=["GITHUB_TOKEN"])
        assert result["GITHUB_TOKEN"] == env["GITHUB_TOKEN"]
        assert "OPENAI_API_KEY" not in result

    def test_allowlist_empty_identical_to_default(self) -> None:
        """FR-3: allowlist 空/None → 与现状逐字节一致（全剥离）。"""
        env = {"OPENAI_API_KEY": "sk-yyy", "PATH": "/usr/bin"}
        assert scrub_sensitive_env(env, allowlist=[]) == scrub_sensitive_env(env)
        assert scrub_sensitive_env(env, allowlist=None) == scrub_sensitive_env(env)

    def test_allowlist_case_insensitive(self) -> None:
        """FR-3: allowlist 大小写不敏感精确匹配。"""
        env = {"GITHUB_TOKEN": "ghp_xxx", "OPENAI_API_KEY": "sk-yyy"}
        result = scrub_sensitive_env(env, allowlist=["github_token"])
        assert result["GITHUB_TOKEN"] == env["GITHUB_TOKEN"]
        assert "OPENAI_API_KEY" not in result

    def test_allowlist_nonsensitive_noop(self) -> None:
        """FR-3: allowlist 含非敏感变量不影响其保留（本就保留）。"""
        env = {"PATH": "/usr/bin", "OPENAI_API_KEY": "sk-yyy"}
        result = scrub_sensitive_env(env, allowlist=["PATH"])
        assert result["PATH"] == "/usr/bin"
        assert "OPENAI_API_KEY" not in result


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


# ── 2026-09-17：项目级 deny 规则配置入口（.heagent/path_deny.json）──────────


class TestUserDenyRules:
    """项目级 path_deny.json：只允许收紧或放行显式列举项，无整体关闭入口（fail-safe 默认仍拒）。

    测试模式对齐 test_mcp_mapping 的用户签名用例：显式 path 加载 + monkeypatch 灌注
    进程级缓存（显式 path **不**写缓存是有意设计——缓存只走默认路径解析）。
    """

    @pytest.fixture(autouse=True)
    def _reset_cache(self) -> Generator[None, None, None]:
        from heagent.tools.path_safety import reset_user_deny_rules

        reset_user_deny_rules()
        yield
        reset_user_deny_rules()

    @staticmethod
    def _write_config(tmp_path: Path, payload: object) -> Path:
        import json

        config = tmp_path / "path_deny.json"
        config.write_text(json.dumps(payload), encoding="utf-8")
        return config

    @staticmethod
    def _prime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: object) -> None:
        """加载配置并灌注缓存，使 check_* 函数走用户规则。"""
        import heagent.tools.path_safety as ps

        config = TestUserDenyRules._write_config(tmp_path, payload)
        monkeypatch.setattr(ps, "_USER_DENY_RULES", ps.user_deny_rules(config))

    def test_missing_file_yields_builtin_only(self, tmp_path: Path) -> None:
        """无配置文件 → 静默空规则，内置表照常工作。"""
        from heagent.tools.path_safety import user_deny_rules

        assert check_write_denied("/etc/passwd") is not None  # 内置写 deny（绝对常量）
        assert check_read_denied(str(tmp_path / ".env")) is not None  # 内置读 deny
        rules = user_deny_rules(tmp_path / "nonexistent.json")
        assert rules.deny_write_paths == frozenset()
        assert rules.allow_write_paths == frozenset()

    def test_user_deny_entries_tighten(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """收紧：用户追加的精确路径与前缀参与 deny，未知路径不受影响。"""
        token = tmp_path / "project" / "secrets-token"
        prefix_dir = tmp_path / "vault"
        self._prime(
            monkeypatch,
            tmp_path,
            {
                "deny_write_paths": [str(token)],
                "deny_write_prefixes": [str(prefix_dir)],
            },
        )
        assert check_write_denied(str(token)) is not None
        assert check_write_denied(str(prefix_dir / "key.bin")) is not None
        assert check_write_denied(str(tmp_path / "notes.txt")) is None

    def test_user_read_basename_tightens(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._prime(monkeypatch, tmp_path, {"deny_read_basenames": ["secrets.yml"]})
        assert check_read_denied(str(tmp_path / "cfg" / "secrets.yml")) is not None
        assert check_read_denied(str(tmp_path / "cfg" / "notes.yml")) is None

    def test_allow_write_path_exempts_exact_builtin_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """放行：仅豁免显式列举的精确路径；内置前缀 deny 对其余路径照常生效。"""
        from pathlib import Path as _Path

        home = tmp_path / "home"
        monkeypatch.setattr(_Path, "home", classmethod(lambda cls: home))
        allowed = home / ".ssh" / "config"  # 内置 ~/.ssh/ 前缀 deny 内的显式放行项
        self._prime(monkeypatch, tmp_path, {"allow_write_paths": [str(allowed)]})
        assert check_write_denied(str(allowed)) is None
        # 同目录其余文件仍被前缀 deny 拦截
        assert check_write_denied(str(home / ".ssh" / "id_rsa")) is not None

    def test_allow_read_basename_exempts_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """放行显式列举的 basename（如测试夹具目录的 .env 样例文件）；未列举项仍拒。"""
        self._prime(monkeypatch, tmp_path, {"allow_read_basenames": [".env"]})
        assert check_read_denied(str(tmp_path / "fixtures" / ".env")) is None
        assert check_read_denied(str(tmp_path / "fixtures" / ".env.local")) is not None

    def test_allow_does_not_weaken_internal_state_deny(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """内部状态目录 deny 不接受豁免（另一保护类，不随用户配置放松）。"""
        self._prime(
            monkeypatch,
            tmp_path,
            {"allow_read_basenames": ["ledger.json"], "allow_write_paths": [str(tmp_path / "ledger")]},
        )
        state_file = Path.cwd().resolve() / ".heagent" / "ledger" / "ledger.json"
        assert check_read_denied(str(state_file)) is not None

    def test_bad_json_falls_back_to_builtin(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        config = tmp_path / "broken.json"
        config.write_text("{not json", encoding="utf-8")
        from heagent.tools.path_safety import user_deny_rules

        with caplog.at_level(logging.ERROR, logger="heagent.tools.path_safety"):
            rules = user_deny_rules(config)
        assert rules.deny_write_paths == frozenset()
        assert any("path deny rules" in r.getMessage() for r in caplog.records)
        assert check_read_denied(str(tmp_path / ".env")) is not None  # 内置表照常

    def test_invalid_entries_skipped_individually(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._prime(
            monkeypatch,
            tmp_path,
            {
                "deny_write_paths": [123, "", "  ", str(tmp_path / "valid-token")],
                "deny_read_basenames": [["nested"], "ok.yml"],
            },
        )
        from heagent.tools.path_safety import user_deny_rules

        # 直接验证解析结果（bad entries 已在 _prime 加载时跳过）
        config = self._write_config(
            tmp_path,
            {
                "deny_write_paths": [123, "", "  ", str(tmp_path / "valid-token")],
                "deny_read_basenames": [["nested"], "ok.yml"],
            },
        )
        rules = user_deny_rules(config)
        assert rules.deny_write_paths == frozenset({str((tmp_path / "valid-token").resolve())})
        assert rules.deny_read_basenames == frozenset({"ok.yml"})

    def test_lazy_cache_loads_once_via_default_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认路径加载 + 进程级懒缓存：第二次 check 命中缓存（运行中改文件不生效，有意）。"""
        import heagent.tools.path_safety as ps

        config_dir = tmp_path / ".heagent"
        config_dir.mkdir()
        config = config_dir / "path_deny.json"
        config.write_text('{"deny_read_basenames": ["one.yml"]}', encoding="utf-8")

        calls: list[int] = []
        original_read = Path.read_text

        def counting_read(self: Path, *a: object, **k: object) -> str:
            if self == config:
                calls.append(1)
            return original_read(self, *a, **k)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", counting_read)
        assert check_read_denied(str(tmp_path / "a" / "one.yml")) is not None
        assert check_read_denied(str(tmp_path / "b" / "one.yml")) is not None
        assert len(calls) == 1, "第二次 check 应命中缓存"
