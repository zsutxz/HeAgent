"""MCP session API 隔离层 — 收敛 v2-sensitive 调用点（AD-1，FR-2）。

Adapter 函数式收敛模块：把 ``MCPClientManager`` 对 ``ClientSession`` 的 4 个
v2-sensitive 方法调用（``initialize`` / ``send_ping`` / ``list_tools`` /
``call_tool``）与 ``mcp.types`` 类型/字段访问（``inputSchema`` / ``isError``）
收敛到一套稳定内部接口。

v2 stable（目标 2026-07-27：stateless + 删 ``initialize`` 握手 + ``send_ping``
deprecated + camelCase→snake_case + types 包拆分）落地时，**只改本模块内部**
即可完成切换——``manager.py`` / ``mapping.py`` 对外调用签名不变（NFR-2 切换
前后 diff 为空），改动限于 ``MCPClientManager`` 内部、不波及 ``AgentLoop``
（兑现 mcp-client NFR-3）。本周期在 v1 SDK 上实现（NFR-4 纯 v1）。

DAG（AD-6）：仅依赖 mcp SDK（+ 按需 ``heagent.types`` / ``exceptions``），
**禁从 ``agent`` 导入，禁从 ``mapping`` 导入**（``mapping`` 反向从本模块取类型
别名，单向防循环）。全 async，passthrough SDK 原生类型，不新造 Pydantic 模型。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from mcp.types import (
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    TextContent,
    Tool,
)

if TYPE_CHECKING:
    from mcp import ClientSession

logger = logging.getLogger(__name__)

# inputSchema 非 dict 时的兜底（空 JSON Schema，与 v1 既有行为一致，NFR-1 零回归）。
_EMPTY_SCHEMA: dict[str, object] = {"type": "object", "properties": {}}

__all__ = [
    "CallToolResult",
    "EmbeddedResource",
    "ImageContent",
    "TextContent",
    "Tool",
    "call_tool",
    "handshake",
    "input_schema_of",
    "list_tools",
    "ping",
    "result_is_error",
]


async def handshake(session: ClientSession) -> None:
    """MCP 握手（v1：``session.initialize()``）。

    v2 删除 ``initialize`` 握手（stateless）——届时本函数变 no-op，只改本处。
    失败 raise（连接期失败由 ``MCPClientManager._server_loop`` 既有 ``except`` 隔离）。
    """
    await session.initialize()


async def ping(session: ClientSession, timeout: float) -> None:
    """健康探测（v1：``session.send_ping()``，带 ``timeout``；失败/超时 raise）。

    v2 ``send_ping`` deprecated、stateless 下无持久 session——本函数为 FR-3 v1 占位
    （AD-3 候选 C，v2 切换时改实现）。失败/超时由 ``_watch`` 既有 ``except Exception``
    兜底→``_unregister_server``（FR-3 v1 行为不变）。
    """
    await asyncio.wait_for(session.send_ping(), timeout=timeout)


async def list_tools(session: ClientSession) -> list[Tool]:
    """工具发现（v1：``session.list_tools()``，返回 ``.tools``）。

    v2 签名变（``params=PaginatedRequestParams``）+ 返回 snake_case——届时只改本处。
    """
    result = await session.list_tools()
    return result.tools


async def call_tool(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None,
) -> CallToolResult:
    """工具调用（v1：``session.call_tool(name, arguments)``）。

    v2 返回 snake_case（``CallToolResult`` 字段名变）——届时只改本处/类型别名。
    """
    return await session.call_tool(name, arguments)


def input_schema_of(tool: Tool) -> dict[str, Any]:
    """取 tool 输入 schema（v1：``tool.inputSchema``；v2：``tool.input_schema``）。

    非 dict 兜底为空 JSON Schema（与 v1 既有行为一致，NFR-1 零回归）。
    """
    schema = tool.inputSchema
    return schema if isinstance(schema, dict) else _EMPTY_SCHEMA


def result_is_error(result: CallToolResult) -> bool:
    """取调用结果错误标记（v1：``result.isError``；v2：``result.is_error``）。"""
    return bool(result.isError)
