"""HeAgent MCP client 适配层（tools/ 层，与 builtins/ 平级）。

连接外部 MCP server、动态发现其 Tools 原语、桥接进既有 ToolRegistry，
使 LLM 能像调用内置工具一样调用外部工具。

后续 story 填充：
- ``config.py``：``MCPConfig`` / ``StdioServerConfig`` / ``HttpServerConfig`` + ``load_mcp_config()``
- ``mapping.py``：MCP tool → ``ToolSchema``；``CallToolResult`` → str + is_error
- ``manager.py``：``MCPClientManager``（async ctx mgr）

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
from heagent.tools.mcp.manager import MCPClientManager

__all__ = [
    "HttpServerConfig",
    "MCPClientManager",
    "MCPConfig",
    "StdioServerConfig",
    "load_mcp_config",
]
