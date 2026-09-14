"""Tests for sandbox permission modes, network switch and enforcement wiring (P0-2).

三组契约：

1. **档位** —— ``read-only`` 只放行只读工具（未知工具 fail-closed）、``danger-full-access``
   跳过路径围栏但保留黑名单、``workspace-write`` 维持现状；
2. **网络开关** —— ``sandbox_network=False`` 映射为 firejail ``--net=none``；
3. **接线** —— ``auto`` 后端探测、仅在真实后端在位时强制 shell 走沙箱并授权该 run。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

# 显式 import 以触发 @tool 注册（护栏测试需要完整注册表）
import heagent.tools.builtins.cron  # noqa: F401
import heagent.tools.builtins.file  # noqa: F401
import heagent.tools.builtins.git  # noqa: F401
import heagent.tools.builtins.search  # noqa: F401
import heagent.tools.builtins.skills  # noqa: F401
import heagent.tools.builtins.subagent  # noqa: F401
import heagent.tools.builtins.web  # noqa: F401
from heagent.config import Settings, reset_settings
from heagent.engine.container import EngineContainer
from heagent.engine.policy import PolicyEngine, ToolExecutionMode
from heagent.tools.registry import ToolRegistry
from heagent.tools.sandbox import FirejailBackend
from heagent.types import ToolAnnotations, ToolCall, ToolSchema

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


def _call(name: str, **args: object) -> ToolCall:
    return ToolCall(id="t1", name=name, arguments=dict(args))


def _verdict(engine: PolicyEngine, name: str, **args: object) -> ToolExecutionMode:
    return engine.evaluate_tool_call(_call(name, **args)).mode


@pytest.fixture(autouse=True)
def _reset() -> Generator[None, None, None]:
    reset_settings()
    yield
    reset_settings()


class TestSandboxSettings:
    def test_defaults(self, tmp_path: Path) -> None:
        s = Settings(_env_file=tmp_path / ".env")
        assert s.sandbox_mode == "workspace-write"
        assert s.sandbox_mode_resolved == "workspace-write"
        assert s.sandbox_network is False
        assert s.sandbox_enforce is True

    def test_mode_and_switches_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_MODE", "read-only")
        monkeypatch.setenv("SANDBOX_NETWORK", "true")
        monkeypatch.setenv("SANDBOX_ENFORCE", "false")
        s = Settings(_env_file=tmp_path / ".env")
        assert s.sandbox_mode_resolved == "read-only"
        assert s.sandbox_network is True
        assert s.sandbox_enforce is False

    def test_invalid_mode_falls_back_with_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """非法档位回退到现状语义（workspace-write）并告警——不阻断启动，也不放宽权限。"""
        monkeypatch.setenv("SANDBOX_MODE", "yolo")
        s = Settings(_env_file=tmp_path / ".env")
        with caplog.at_level(logging.WARNING, logger="heagent.config"):
            assert s.sandbox_mode_resolved == "workspace-write"
        assert any("SANDBOX_MODE" in record.message for record in caplog.records)

    def test_mode_is_case_insensitive(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_MODE", "READ-ONLY")
        assert Settings(_env_file=tmp_path / ".env").sandbox_mode_resolved == "read-only"


class TestReadOnlyMode:
    @pytest.mark.parametrize("tool", ["file_read", "file_search", "content_search", "git_status", "web_fetch"])
    def test_read_only_tools_allowed(self, tool: str) -> None:
        engine = PolicyEngine(sandbox_mode="read-only")
        assert _verdict(engine, tool) is not ToolExecutionMode.BLOCKED

    @pytest.mark.parametrize("tool", ["file_write", "file_edit", "shell", "skill_create", "fact_add"])
    def test_mutating_tools_blocked(self, tool: str) -> None:
        engine = PolicyEngine(sandbox_mode="read-only")
        assert _verdict(engine, tool) is ToolExecutionMode.BLOCKED

    def test_unknown_tool_blocked_fail_closed(self) -> None:
        """名字不认识的工具在只读档下必须拒绝——「没登记就放行」正是权限放大。"""
        engine = PolicyEngine(sandbox_mode="read-only")
        assert _verdict(engine, "some_future_tool") is ToolExecutionMode.BLOCKED

    def test_schema_read_only_hint_allows_unknown_tool(self) -> None:
        """MCP / 显式 schema 的 readOnlyHint=true 优先于内置白名单（只读即放行）。"""
        engine = PolicyEngine(sandbox_mode="read-only")
        schema = ToolSchema(
            name="github__list_issues",
            description="list",
            parameters={"type": "object", "properties": {}},
            annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
        )
        verdict = engine.evaluate_tool_call(_call("github__list_issues"), schema=schema)
        assert verdict.mode is not ToolExecutionMode.BLOCKED

    def test_gate_precedes_allowlist(self) -> None:
        """档位是上限：即便工具在 allowlist 里，写操作在只读档下仍被拒。"""
        engine = PolicyEngine(sandbox_mode="read-only", allowed_tools=["file_write"])
        assert _verdict(engine, "file_write") is ToolExecutionMode.BLOCKED

    def test_blocking_reason_names_the_mode(self) -> None:
        engine = PolicyEngine(sandbox_mode="read-only")
        verdict = engine.evaluate_tool_call(_call("file_write", path="a.txt"))
        assert "read-only" in verdict.reason


class TestWorkspaceWriteMode:
    def test_path_escape_blocked(self) -> None:
        engine = PolicyEngine(workspace_root="C:/ws", sandbox_mode="workspace-write")
        assert _verdict(engine, "file_write", path="../escape.txt") is ToolExecutionMode.BLOCKED

    def test_shell_stays_direct(self) -> None:
        engine = PolicyEngine(sandbox_mode="workspace-write")
        assert _verdict(engine, "shell", command="dir") is ToolExecutionMode.DIRECT


class TestDangerFullAccess:
    def test_path_escape_allowed(self) -> None:
        engine = PolicyEngine(workspace_root="C:/ws", sandbox_mode="danger-full-access")
        assert _verdict(engine, "file_write", path="../escape.txt") is ToolExecutionMode.DIRECT

    def test_credential_deny_skipped(self) -> None:
        """该档显式放弃围栏与凭证 deny 预检——语义即「不受工作区约束」。"""
        engine = PolicyEngine(workspace_root="C:/ws", sandbox_mode="danger-full-access")
        assert _verdict(engine, "file_write", path="C:/Users/x/.ssh/id_rsa") is ToolExecutionMode.DIRECT

    def test_blocklist_still_applies(self) -> None:
        engine = PolicyEngine(sandbox_mode="danger-full-access", blocked_tools=["shell"])
        assert _verdict(engine, "shell", command="dir") is ToolExecutionMode.BLOCKED


class TestReadOnlySetConsistency:
    def test_matches_registered_annotations(self) -> None:
        """``_READ_ONLY_TOOLS`` 必须与 registry 里 read_only=True 的工具完全一致。

        少登记 → 只读工具在只读档被误拒（fail-closed，可发现）；多登记 → 会写的工具
        在只读档被放行（权限放大，不可接受）。两个方向都由本测试拦住。
        """
        registered = {
            schema.name
            for schema in ToolRegistry.get().all_schemas()
            if schema.annotations is not None and schema.annotations.readOnlyHint
        }
        assert registered == set(PolicyEngine._READ_ONLY_TOOLS)


class TestFirejailNetworkSwitch:
    def test_network_disabled_adds_net_none(self) -> None:
        backend = FirejailBackend(network=False)
        argv = backend._build_argv("echo hi", None)
        assert "--net=none" in argv
        assert argv.index("--net=none") < argv.index("--")

    def test_network_enabled_omits_net_none(self) -> None:
        backend = FirejailBackend(network=True)
        assert "--net=none" not in backend._build_argv("echo hi", None)

    def test_net_none_precedes_private_root(self) -> None:
        backend = FirejailBackend(network=False, workspace_root="/ws")
        argv = backend._build_argv("echo hi", None)
        assert argv.index("--net=none") < argv.index("--private=/ws")


class TestContainerWiring:
    def test_auto_without_firejail_is_passthrough(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """无 firejail 的机器上 auto 回退 passthrough：零行为变更，也不谎称已隔离。"""
        monkeypatch.setenv("SANDBOX_BACKEND", "auto")
        monkeypatch.setattr("shutil.which", lambda _name: None)
        container = EngineContainer.default(workspace_root=str(tmp_path))
        assert container.executor.sandbox_runner is None
        assert container.policy.sandbox_tools == set()

    def test_auto_with_firejail_enforces_shell(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """探测到真实后端时才自动强制 shell 走沙箱（默认开启的落点）。"""
        monkeypatch.setenv("SANDBOX_BACKEND", "auto")
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/firejail")
        container = EngineContainer.default(workspace_root=str(tmp_path))
        assert isinstance(container.executor.sandbox_runner, FirejailBackend)
        assert "shell" in container.policy.sandbox_tools

    def test_enforce_can_be_disabled(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SANDBOX_BACKEND", "auto")
        monkeypatch.setenv("SANDBOX_ENFORCE", "false")
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/firejail")
        container = EngineContainer.default(workspace_root=str(tmp_path))
        assert isinstance(container.executor.sandbox_runner, FirejailBackend)
        assert container.policy.sandbox_tools == set()

    def test_mode_is_injected_into_policy(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SANDBOX_MODE", "read-only")
        container = EngineContainer.default(workspace_root=str(tmp_path))
        assert container.policy.sandbox_mode == "read-only"

    def test_run_context_grants_only_with_backend(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """授权与后端在位同条件：无后端时不写授权键，保持「未授权即拒绝」的 fail-safe。"""
        monkeypatch.setenv("SANDBOX_BACKEND", "auto")
        monkeypatch.setattr("shutil.which", lambda _name: None)
        container = EngineContainer.default(workspace_root=str(tmp_path))
        container.policy.sandbox_tools.add("shell")
        assert "sandboxed_tools" not in container.create_run_context().metadata

    def test_run_context_grants_with_backend(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SANDBOX_BACKEND", "auto")
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/firejail")
        container = EngineContainer.default(workspace_root=str(tmp_path))
        metadata = container.create_run_context().metadata
        assert metadata["sandboxed_tools"] == ["shell"]
