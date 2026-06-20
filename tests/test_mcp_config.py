"""Story 1.2 — .mcp.json 配置加载与 ${ENV} 插值（FR-7/8）。

覆盖：stdio/http 解析、${ENV} 插值、未设变量 fail-fast、
缺文件 / 空配置纯内置模式、非法结构拒绝。全程无网络。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from heagent.exceptions import ToolError
from heagent.tools.mcp import HttpServerConfig, MCPConfig, StdioServerConfig, load_mcp_config

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- 纯内置模式（FR-7）---


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """无 .mcp.json → 空配置（纯内置模式）。"""
    cfg = load_mcp_config(tmp_path / "nonexistent.json")
    assert cfg.is_empty
    assert cfg.servers == {}


def test_empty_mcp_servers_returns_empty(tmp_path: Path) -> None:
    """mcpServers 为空 → 空配置。"""
    p = _write(tmp_path / ".mcp.json", {"mcpServers": {}})
    cfg = load_mcp_config(p)
    assert cfg.is_empty


def test_no_mcp_servers_key_returns_empty(tmp_path: Path) -> None:
    """无 mcpServers 键 → 空配置。"""
    p = _write(tmp_path / ".mcp.json", {"other": 1})
    cfg = load_mcp_config(p)
    assert cfg.is_empty


# --- stdio / http 解析 ---


def test_stdio_server_parsed(tmp_path: Path) -> None:
    p = _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"local": {"command": "python", "args": ["-m", "srv"], "env": {"FOO": "bar"}}}},
    )
    cfg = load_mcp_config(p)
    srv = cfg.servers["local"]
    assert isinstance(srv, StdioServerConfig)
    assert srv.command == "python"
    assert srv.args == ["-m", "srv"]
    assert srv.env == {"FOO": "bar"}


def test_http_server_parsed(tmp_path: Path) -> None:
    p = _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"github": {"url": "https://api.github.example/mcp", "headers": {"X": "y"}}}},
    )
    cfg = load_mcp_config(p)
    srv = cfg.servers["github"]
    assert isinstance(srv, HttpServerConfig)
    assert srv.url == "https://api.github.example/mcp"
    assert srv.headers == {"X": "y"}


def test_multiple_servers(tmp_path: Path) -> None:
    p = _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"local": {"command": "x"}, "remote": {"url": "u"}}},
    )
    cfg = load_mcp_config(p)
    assert set(cfg.servers) == {"local", "remote"}
    assert not cfg.is_empty


# --- ${ENV} 插值（FR-8）---


def test_env_interpolation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """${ENV} 插值成功，token 从 env 注入。"""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret123")
    p = _write(
        tmp_path / ".mcp.json",
        {
            "mcpServers": {
                "github": {
                    "url": "https://api.example/mcp",
                    "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"},
                }
            }
        },
    )
    cfg = load_mcp_config(p)
    assert cfg.servers["github"].headers["Authorization"] == "Bearer ghp_secret123"


def test_token_not_written_to_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """插值后 token 不落配置明文（文件仍是 ${...}）。"""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret123")
    p = _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"github": {"url": "u", "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}}}},
    )
    load_mcp_config(p)
    text = p.read_text(encoding="utf-8")
    assert "ghp_secret123" not in text
    assert "${GITHUB_TOKEN}" in text


def test_env_interpolation_in_stdio_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """stdio entry 的 env 值也插值。"""
    monkeypatch.setenv("API_KEY", "k1")
    p = _write(
        tmp_path / ".mcp.json",
        {"mcpServers": {"s": {"command": "c", "env": {"KEY": "${API_KEY}"}}}},
    )
    cfg = load_mcp_config(p)
    assert cfg.servers["s"].env["KEY"] == "k1"


def test_missing_env_var_fail_fast(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """引用未设变量 → fail-fast（ToolError）。"""
    monkeypatch.delenv("MISSING_VAR", raising=False)
    p = _write(tmp_path / ".mcp.json", {"mcpServers": {"s": {"url": "${MISSING_VAR}"}}})
    with pytest.raises(ToolError):
        load_mcp_config(p)


# --- 非法结构拒绝 ---


def test_invalid_server_no_command_no_url(tmp_path: Path) -> None:
    p = _write(tmp_path / ".mcp.json", {"mcpServers": {"s": {"args": ["x"]}}})
    with pytest.raises(ToolError):
        load_mcp_config(p)


def test_invalid_top_level(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(ToolError):
        load_mcp_config(p)


def test_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text("{not valid", encoding="utf-8")
    with pytest.raises(ToolError):
        load_mcp_config(p)


def test_mcp_servers_not_object(tmp_path: Path) -> None:
    p = _write(tmp_path / ".mcp.json", {"mcpServers": ["not", "a", "dict"]})
    with pytest.raises(ToolError):
        load_mcp_config(p)


def test_server_entry_not_object(tmp_path: Path) -> None:
    p = _write(tmp_path / ".mcp.json", {"mcpServers": {"s": "not-an-object"}})
    with pytest.raises(ToolError):
        load_mcp_config(p)


def test_mcp_config_is_empty_property() -> None:
    assert MCPConfig().is_empty
    assert not MCPConfig(servers={"s": StdioServerConfig(command="c")}).is_empty
