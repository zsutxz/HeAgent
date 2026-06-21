"""Story 1.3 — MCP tool ↔ ToolSchema/ToolResult 映射（FR-4/5/6）。Stub，无网络。"""

from __future__ import annotations

from typing import Any

import pytest
from mcp.types import (
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    TextContent,
    TextResourceContents,
    Tool,
)

from heagent.exceptions import ToolError
from heagent.tools.mcp.mapping import (
    bridge_result,
    call_result_to_text,
    mcp_tool_to_schema,
    namespaced_tool_name,
    normalize_server_name,
)

# --- namespace 规整（FR-6） ---


def test_normalize_server_name() -> None:
    assert normalize_server_name("GitHub-MCP") == "github_mcp"
    assert normalize_server_name("My Server 1") == "my_server_1"
    assert normalize_server_name("github") == "github"


def test_namespaced_tool_name() -> None:
    assert namespaced_tool_name("GitHub-MCP", "list_issues") == "github_mcp__list_issues"


def test_normalize_collision_basis() -> None:
    """两个不同 server 名规整后产生相同前缀（FR-6 冲突检测基础）。"""
    assert normalize_server_name("GitHub MCP") == normalize_server_name("github-mcp") == "github_mcp"


# --- Tool → ToolSchema（FR-4） ---


def test_mcp_tool_to_schema_namespace_and_passthrough() -> None:
    tool = Tool(
        name="list_issues",
        description="List issues",
        inputSchema={"type": "object", "properties": {"owner": {"type": "string"}}},
    )
    schema = mcp_tool_to_schema("github", tool)
    assert schema.name == "github__list_issues"
    assert schema.description == "List issues"
    assert schema.parameters == {"type": "object", "properties": {"owner": {"type": "string"}}}


def test_mcp_tool_to_schema_missing_description_fallback() -> None:
    tool = Tool(name="search", description=None, inputSchema={"type": "object"})
    schema = mcp_tool_to_schema("github", tool)
    assert "search" in schema.description


# --- CallToolResult → str（FR-5） ---


def _result(content: list[Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=content, isError=is_error)


def test_text_content_blocks_joined() -> None:
    r = _result([TextContent(type="text", text="line1"), TextContent(type="text", text="line2")])
    assert call_result_to_text(r) == "line1\nline2"


def test_image_content_placeholder() -> None:
    r = _result([ImageContent(type="image", data="abc", mimeType="image/png")])
    assert call_result_to_text(r) == "[image]"


def test_embedded_resource_placeholder() -> None:
    res = EmbeddedResource(
        type="resource",
        resource=TextResourceContents(uri="file:///x", mimeType="text/plain", text="contents"),
    )
    r = _result([res])
    assert "[resource: file:///x]" in call_result_to_text(r)


def test_mixed_blocks() -> None:
    r = _result([TextContent(type="text", text="t"), ImageContent(type="image", data="d", mimeType="image/png")])
    assert call_result_to_text(r) == "t\n[image]"


def test_empty_content_returns_empty_string() -> None:
    assert call_result_to_text(_result([])) == ""


# --- bridge_result：isError → ToolError（FR-5 错误语义） ---


def test_bridge_result_returns_text() -> None:
    r = _result([TextContent(type="text", text="ok")])
    assert bridge_result(r) == "ok"


def test_bridge_result_iserror_raises_toolerror() -> None:
    r = _result([TextContent(type="text", text="boom")], is_error=True)
    with pytest.raises(ToolError):
        bridge_result(r)
