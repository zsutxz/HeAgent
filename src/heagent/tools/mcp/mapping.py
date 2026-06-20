"""MCP tool ↔ HeAgent ToolSchema/ToolResult 映射（FR-4/5/6）。

- 工具发现（FR-4）：mcp ``Tool`` → HeAgent ``ToolSchema``，namespaced 为 ``<server>__<tool>``，
  ``inputSchema`` 直接 passthrough 进 ``ToolSchema.parameters``（已是标准 JSON Schema）；
- namespace（FR-6）：server 名规整化（小写 + 非字母数字 → ``_``）；
- 结果桥接（FR-5）：``CallToolResult.content`` → str（V1 text-only）；``isError`` → 抛 ``ToolError``。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent, Tool

from heagent.exceptions import ToolError
from heagent.types import ToolSchema

logger = logging.getLogger(__name__)

_NAMESPACE_SEP = "__"
_EMPTY_SCHEMA: dict[str, object] = {"type": "object", "properties": {}}


def normalize_server_name(name: str) -> str:
    """规整化 server 名：小写 + 非字母数字 → ``_``（namespace 前缀基础，FR-6）。"""
    return re.sub(r"[^a-z0-9]", "_", name.lower())


def namespaced_tool_name(server_name: str, tool_name: str) -> str:
    """生成 LLM 可见的 namespaced 工具名：``<server>__<tool>``（FR-6）。"""
    return f"{normalize_server_name(server_name)}{_NAMESPACE_SEP}{tool_name}"


def mcp_tool_to_schema(server_name: str, tool: Tool) -> ToolSchema:
    """mcp ``Tool`` → HeAgent ``ToolSchema``（namespace 化，inputSchema passthrough，FR-4）。"""
    input_schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else _EMPTY_SCHEMA
    return ToolSchema(
        name=namespaced_tool_name(server_name, tool.name),
        description=tool.description or f"MCP tool {tool.name}",
        parameters=input_schema,
    )


def call_result_to_text(result: CallToolResult) -> str:
    """``CallToolResult.content`` → str（V1 text-only，FR-5）。

    ``TextContent`` → text；``ImageContent`` → ``[image]``；``EmbeddedResource`` → ``[resource: uri]``；
    其余块 → ``[unknown: <type>]``；多块用 ``\\n`` 连接。不判断 ``isError``（由 ``bridge_result`` 处理）。
    """
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            parts.append("[image]")
        elif isinstance(block, EmbeddedResource):
            uri: Any = getattr(block.resource, "uri", "?")
            parts.append(f"[resource: {uri}]")
        else:
            parts.append(f"[unknown: {type(block).__name__}]")
    return "\n".join(parts)


def bridge_result(result: CallToolResult) -> str:
    """桥接 ``CallToolResult``：``isError`` → 抛 ``ToolError``；否则返回文本（FR-5 错误语义）。"""
    text = call_result_to_text(result)
    if result.isError:
        raise ToolError(text)
    return text
