"""HeAgent MCP client 适配层（tools/ 层，与 builtins/ 平级）。

连接外部 MCP server、动态发现其 Tools 原语、桥接进既有 ToolRegistry，
使 LLM 能像调用内置工具一样调用外部工具。

后续 story 填充：
- ``config.py``：``MCPConfig`` / ``StdioServerConfig`` / ``HttpServerConfig`` + ``load_mcp_config()``
- ``mapping.py``：MCP tool → ``ToolSchema``；``CallToolResult`` → str + is_error
- ``manager.py``：``MCPClientManager``（async ctx mgr）

**可选依赖**：``mcp`` SDK 装在 ``[mcp]`` extra 里（核心安装不含它）。本包在 import 期不触碰 SDK
——取用一律经 :mod:`.sdk`（惰性导入 + 缺失时的安装诊断 ``INSTALL_HINT``），因此缺 SDK 时
``import heagent`` 与普通 CLI 照常，只有真正构造连接时才 fail loud。

DAG 约束：本层仅从 ``types`` / ``exceptions`` / ``tools.registry`` 导入，
**禁止**从 ``agent/`` 导入（MCP 属 tools/ 层，非模型 provider）。
"""

from __future__ import annotations

from heagent.tools.mcp.config import (
    HttpServerConfig,
    MCPConfig,
    StdioServerConfig,
    load_mcp_config,
)
from heagent.tools.mcp.manager import MCPClientManager, MCPServerFailure
from heagent.tools.mcp.sdk import INSTALL_HINT, McpSdkMissingError, require_sdk
from heagent.tools.mcp.stdio_sandbox import StdioSandboxSpec

__all__ = [
    "INSTALL_HINT",
    "HttpServerConfig",
    "MCPClientManager",
    "MCPConfig",
    "MCPServerFailure",
    "McpSdkMissingError",
    "StdioSandboxSpec",
    "StdioServerConfig",
    "load_mcp_config",
    "require_sdk",
]
