"""Story 1.5 — CLI 装配 MCPClientManager 生命周期（FR-2/7 门控 + FR-8 fail-fast）。

聚焦门控逻辑（``_mcp_lifecycle``）与 ``main`` 集成：无网络、无真实 provider 调用。

- ``mcp_enabled=False`` → 完全跳过（不加载配置）；
- ``mcp_enabled=True`` + 无 ``.mcp.json`` / 空 mcpServers → 纯内置 no-op；
- ``mcp_enabled=True`` + 有效配置 → 返回 ``MCPClientManager``；
- 配置错误（未设 ``${ENV}``）→ fail-fast ``ToolError``。
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from heagent.cli.console import _mcp_lifecycle, main
from heagent.exceptions import ToolError
from heagent.tools.mcp import MCPClientManager


@pytest.fixture()
def clean_settings():
    """Reset settings singleton for tests that need it."""
    from heagent.config import reset_settings

    reset_settings()
    yield
    reset_settings()


def _write_mcp_json(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestMCPLifecycle:
    """门控构建 MCP 上下文（纯单元，无网络）。"""

    def test_disabled_returns_noop(self, clean_settings, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from heagent.config import Settings

        ctx = _mcp_lifecycle(Settings(mcp_enabled=False))
        assert not isinstance(ctx, MCPClientManager)

    def test_enabled_no_config_file_returns_noop(self, clean_settings, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # tmp_path 无 .mcp.json
        from heagent.config import Settings

        ctx = _mcp_lifecycle(Settings(mcp_enabled=True))
        assert not isinstance(ctx, MCPClientManager)

    def test_enabled_empty_mcp_servers_returns_noop(self, clean_settings, tmp_path, monkeypatch):
        _write_mcp_json(tmp_path / ".mcp.json", {"mcpServers": {}})
        monkeypatch.chdir(tmp_path)
        from heagent.config import Settings

        ctx = _mcp_lifecycle(Settings(mcp_enabled=True))
        assert not isinstance(ctx, MCPClientManager)

    def test_enabled_with_config_returns_manager(self, clean_settings, tmp_path, monkeypatch):
        _write_mcp_json(tmp_path / ".mcp.json", {"mcpServers": {"s": {"command": "x"}}})
        monkeypatch.chdir(tmp_path)
        from heagent.config import Settings

        ctx = _mcp_lifecycle(Settings(mcp_enabled=True))
        assert isinstance(ctx, MCPClientManager)

    def test_bad_config_raises_toolerror(self, clean_settings, tmp_path, monkeypatch):
        monkeypatch.delenv("MISSING_TOKEN", raising=False)
        _write_mcp_json(
            tmp_path / ".mcp.json",
            {"mcpServers": {"s": {"url": "https://x", "headers": {"Authorization": "Bearer ${MISSING_TOKEN}"}}}},
        )
        monkeypatch.chdir(tmp_path)
        from heagent.config import Settings

        with pytest.raises(ToolError):
            _mcp_lifecycle(Settings(mcp_enabled=True))


class TestCLIMCPIntegration:
    """CLI 层 MCP 门控集成（CliRunner，无真实 provider/连接）。"""

    def test_disabled_skips_config_load(self, monkeypatch, clean_settings, tmp_path):
        """mcp_enabled=False → load_mcp_config 完全不被调用（门控生效）。"""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("MCP_ENABLED", "false")
        monkeypatch.chdir(tmp_path)

        import heagent.cli.console as cli_mod

        calls: list[str] = []
        original = cli_mod.load_mcp_config

        def spy(path):  # noqa: ANN001 - 仅记录调用
            calls.append(str(path))
            return original(path)

        monkeypatch.setattr(cli_mod, "load_mcp_config", spy)

        result = CliRunner().invoke(main, input="\n")  # chat 空输入立即退出
        assert result.exit_code == 0
        assert calls == []

    def test_enabled_no_config_pure_builtin_no_error(self, monkeypatch, clean_settings, tmp_path):
        """mcp_enabled=True 但无 .mcp.json → 纯内置模式不报错不阻断（FR-7）。"""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.chdir(tmp_path)  # 无 .mcp.json

        result = CliRunner().invoke(main, input="\n")
        assert result.exit_code == 0

    def test_bad_config_reports_error(self, monkeypatch, clean_settings, tmp_path):
        """坏配置（未设 ${ENV}）→ fail-fast 友好报告，非 traceback（FR-8）。"""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("MISSING_TOKEN", raising=False)
        _write_mcp_json(
            tmp_path / ".mcp.json",
            {"mcpServers": {"s": {"url": "https://x", "headers": {"Authorization": "Bearer ${MISSING_TOKEN}"}}}},
        )
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(main, input="\n")
        assert result.exit_code != 0
        assert "mcp config error" in result.output.lower()

    def test_enabled_with_config_enters_and_exits_manager(self, monkeypatch, clean_settings, tmp_path):
        """有效配置 → MCPClientManager 在会话期进入、退出时回收（FR-2 生命周期）。"""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        _write_mcp_json(tmp_path / ".mcp.json", {"mcpServers": {"s": {"command": "x"}}})
        monkeypatch.chdir(tmp_path)

        from heagent.tools.mcp.manager import MCPClientManager

        events: list[str] = []

        async def fake_connect_all(self) -> None:  # noqa: ANN001 - stub
            events.append("enter")

        async def fake_aexit(self, *exc):  # noqa: ANN001 - stub
            events.append("exit")

        monkeypatch.setattr(MCPClientManager, "_connect_all", fake_connect_all)
        monkeypatch.setattr(MCPClientManager, "__aexit__", fake_aexit)

        result = CliRunner().invoke(main, input="\n")
        assert result.exit_code == 0
        assert events == ["enter", "exit"]


# --- 发现阶段失败呈报（Phase 4 C2：不隐藏发现错误）---


def test_report_mcp_discovery_failures_renders_stderr(clean_settings, capsys):
    """manager 携带失败记录 → 逐条渲染到 stderr（server 名 + 原因）。"""
    from heagent.cli.interactive import _report_mcp_discovery_failures
    from heagent.tools.mcp import MCPServerFailure

    manager = MCPClientManager.__new__(MCPClientManager)  # 不触发连接，仅承载记录
    manager._discovery_failures = [
        MCPServerFailure(server="bad", reason="conn refused"),
        MCPServerFailure(server="slow", reason="连接/发现超时（10.0s）"),
    ]
    _report_mcp_discovery_failures(manager)
    err = capsys.readouterr().err
    assert "[mcp] server 'bad' 连接/发现失败，已隔离：conn refused" in err
    assert "[mcp] server 'slow' 连接/发现失败，已隔离：连接/发现超时（10.0s）" in err


def test_report_mcp_discovery_failures_noop_without_manager(capsys):
    """nullcontext 场景（None）与无失败 manager 均零输出。"""
    from heagent.cli.interactive import _report_mcp_discovery_failures

    _report_mcp_discovery_failures(None)
    _report_mcp_discovery_failures(object())
    assert capsys.readouterr().err == ""
