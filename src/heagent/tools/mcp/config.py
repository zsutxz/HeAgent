"""声明式 .mcp.json 配置加载（FR-7/8）。

独立于 pydantic-settings 的 ``Settings`` —— 多 server 结构化 JSON + ``${ENV}`` 插值。
对齐 Claude Code / Cursor 的 ``.mcp.json`` 文件名与位置。

- 无 ``.mcp.json`` 或 ``mcpServers`` 为空 → 空配置（纯内置模式，FR-7）；
- 引用的 ``${VAR}`` 未设 → 加载即 fail-fast（PAT 不落配置明文，FR-8）。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from heagent.exceptions import ToolError

logger = logging.getLogger(__name__)

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class StdioServerConfig(BaseModel):
    """stdio transport：本地子进程（command / args / env）。"""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class HttpServerConfig(BaseModel):
    """Streamable HTTP transport：远程 server（url / headers）。"""

    url: str
    headers: dict[str, str] = Field(default_factory=dict)


ServerConfig = StdioServerConfig | HttpServerConfig


class MCPConfig(BaseModel):
    """解析后的 MCP server 集合。"""

    servers: dict[str, ServerConfig] = Field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """无 server（纯内置模式）。"""
        return not self.servers


def _replace_env(match: re.Match[str]) -> str:
    var = match.group(1)
    if var not in os.environ:
        raise ToolError(f"环境变量 ${{{var}}} 未设置（.mcp.json 引用未定义变量）")
    return os.environ[var]


def _interpolate_env(value: Any) -> Any:
    """递归对 str 值做 ${ENV} 插值（引用未设变量即 raise，fail-fast）。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(_replace_env, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


def _parse_server(name: str, raw: dict[str, Any]) -> ServerConfig:
    """按 entry 字段分派 stdio / http（无显式 type 字段，对齐 Claude Code 格式）。"""
    if "command" in raw:
        return StdioServerConfig.model_validate(raw)
    if "url" in raw:
        return HttpServerConfig.model_validate(raw)
    raise ToolError(f"MCP server '{name}' 配置无效：缺少 command（stdio）或 url（http）")


def load_mcp_config(path: str | Path = ".mcp.json") -> MCPConfig:
    """加载 ``.mcp.json`` 并做 ``${ENV}`` 插值。

    - 无文件或 ``mcpServers`` 为空 → 空配置（纯内置模式，不报错，FR-7）；
    - 引用未设变量 / 非法结构 / 非法 JSON → 抛 ``ToolError``（fail-fast，FR-8）。
    """
    p = Path(path)
    if not p.is_file():
        logger.debug("无 .mcp.json（%s）→ 纯内置工具模式", p)
        return MCPConfig()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"加载 .mcp.json 失败（{p}）：{exc}") from exc
    if not isinstance(raw, dict):
        raise ToolError(f".mcp.json 顶层须为对象（{p}）")
    servers_raw = raw.get("mcpServers", {})
    if not isinstance(servers_raw, dict):
        raise ToolError(f".mcp.json 的 mcpServers 须为对象（{p}）")
    if not servers_raw:
        logger.debug(".mcp.json 的 mcpServers 为空 → 纯内置工具模式")
        return MCPConfig()
    interpolated = _interpolate_env(servers_raw)
    servers: dict[str, ServerConfig] = {}
    for name, entry in interpolated.items():
        if not isinstance(entry, dict):
            raise ToolError(f"MCP server '{name}' 配置须为对象")
        servers[name] = _parse_server(name, entry)
    logger.info("加载 .mcp.json：%d 个 MCP server", len(servers))
    return MCPConfig(servers=servers)
