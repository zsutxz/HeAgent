"""Story 14-3 — session_api 隔离层单测（AD-5）。Stub session，无网络。

覆盖 ``session_api`` 各 v1 实现（handshake / ping / list_tools / call_tool）与
字段访问兼容函数（``input_schema_of`` / ``result_is_error``），与既有
``tests/test_mcp_*.py`` 共同构成 v1→v2 切换前后零回归基线（AD-5）。

pytest-asyncio ``auto`` 模式——``async def`` 测试自动收集，无需 marker。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from heagent.tools.mcp.session_api import (
    call_tool,
    handshake,
    input_schema_of,
    list_tools,
    ping,
    result_is_error,
)


class _StubSession:
    """模拟 ClientSession（duck-typed）：记录调用 + 受控失败，供隔离层单测。

    ``session_api`` 的 ``ClientSession`` 注解是 ``TYPE_CHECKING`` 惰性字符串，
    运行时接受任何具备 ``initialize`` / ``send_ping`` / ``list_tools`` /
    ``call_tool`` 的对象——故无需真实 SDK session 即可测隔离层适配正确性。
    """

    def __init__(
        self,
        tools: list[Tool] | None = None,
        call_result: CallToolResult | None = None,
    ) -> None:
        self._tools = tools or []
        self._call_result = call_result or CallToolResult(content=[TextContent(type="text", text="ok")], isError=False)
        self.initialized = False
        self.calls: list[tuple[Any, ...]] = []

    async def initialize(self) -> None:
        self.initialized = True
        self.calls.append(("initialize",))

    async def send_ping(self, **_: Any) -> None:
        self.calls.append(("send_ping",))

    async def list_tools(self, **_: Any) -> Any:
        self.calls.append(("list_tools",))
        tools = self._tools

        class _Result:
            pass

        _Result.tools = tools
        return _Result()

    async def call_tool(self, name: str, arguments: Any = None, **_: Any) -> CallToolResult:
        self.calls.append(("call_tool", name, arguments))
        return self._call_result


def _tool(name: str, schema: dict[str, Any] | None = None) -> Tool:
    return Tool(name=name, description=f"d-{name}", inputSchema=schema or {"type": "object"})


# --- handshake（v1：session.initialize） ---


async def test_handshake_calls_initialize() -> None:
    session = _StubSession()
    await handshake(session)
    assert session.initialized
    assert session.calls == [("initialize",)]


async def test_handshake_propagates_failure() -> None:
    """handshake 失败 raise（连接期失败由 MCPClientManager._server_loop except 隔离）。"""

    class _Boom(_StubSession):
        async def initialize(self) -> None:
            raise RuntimeError("connect failed")

    with pytest.raises(RuntimeError, match="connect failed"):
        await handshake(_Boom())


# --- ping（v1：session.send_ping，带 timeout；失败/超时 raise） ---


async def test_ping_calls_send_ping() -> None:
    session = _StubSession()
    await ping(session, timeout=1.0)
    assert ("send_ping",) in session.calls


async def test_ping_timeout_raises() -> None:
    """ping 超时 → TimeoutError（_watch 既有 except 兜底→_unregister_server）。"""

    class _Slow(_StubSession):
        async def send_ping(self, **_: Any) -> None:
            await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        await ping(_Slow(), timeout=0.01)


async def test_ping_failure_raises() -> None:
    """ping 失败 raise（_watch 既有 except 兜底→_unregister_server，FR-3 v1 不变）。"""

    class _Dead(_StubSession):
        async def send_ping(self, **_: Any) -> None:
            raise RuntimeError("server gone")

    with pytest.raises(RuntimeError, match="server gone"):
        await ping(_Dead(), timeout=1.0)


# --- list_tools（v1：session.list_tools → .tools） ---


async def test_list_tools_returns_tools_list() -> None:
    tools = [_tool("a"), _tool("b")]
    result = await list_tools(_StubSession(tools=tools))
    assert result == tools
    assert isinstance(result, list)


async def test_list_tools_empty() -> None:
    assert await list_tools(_StubSession(tools=[])) == []


# --- call_tool（v1：session.call_tool） ---


async def test_call_tool_returns_result_and_forwards_args() -> None:
    res = CallToolResult(content=[TextContent(type="text", text="hi")], isError=False)
    session = _StubSession(call_result=res)
    out = await call_tool(session, "tool_x", {"k": 1})
    assert out is res
    assert session.calls[-1] == ("call_tool", "tool_x", {"k": 1})


async def test_call_tool_none_arguments_passthrough() -> None:
    """call_tool 透传 None arguments（manager handler 传 ``kwargs or None``）。"""
    session = _StubSession()
    await call_tool(session, "t", None)
    assert session.calls[-1] == ("call_tool", "t", None)


# --- input_schema_of（v1：tool.inputSchema + 非 dict 兜底） ---
#
# 注：mcp SDK 的 Tool 模型对 inputSchema 做归一化（补 ``type``、重建 dict 对象），
# 故真实 Tool 的 inputSchema 必为 dict——用 SimpleNamespace（duck-typed）精确测
# input_schema_of 自身逻辑（passthrough identity + 非 dict 兜底），另用真实 Tool
# 测与 SDK 归一化后的集成。defensive isinstance 兜底防非 conforming tool。


def test_input_schema_of_passthrough_dict() -> None:
    """dict inputSchema → 原样 passthrough 原对象（v1：tool.inputSchema，不复制）。"""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    tool = SimpleNamespace(inputSchema=schema)
    assert input_schema_of(tool) is schema


def test_input_schema_of_non_dict_none_fallback() -> None:
    """inputSchema=None（缺失/畸形）→ 兜底空 JSON Schema（NFR-1 零回归）。"""
    assert input_schema_of(SimpleNamespace(inputSchema=None)) == {"type": "object", "properties": {}}


def test_input_schema_of_non_dict_string_fallback() -> None:
    """inputSchema 非 dict 类型（str 等）→ 兜底。"""
    assert input_schema_of(SimpleNamespace(inputSchema="not-a-dict")) == {"type": "object", "properties": {}}


def test_input_schema_of_real_tool_dict_passthrough() -> None:
    """真实 Tool（inputSchema 经 SDK 归一化为 dict）→ 按 dict passthrough 返回。"""
    tool = Tool(
        name="t",
        description="d",
        inputSchema={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    result = input_schema_of(tool)
    assert isinstance(result, dict)
    assert result.get("properties") == {"x": {"type": "string"}}


# --- result_is_error（v1：result.isError） ---


def test_result_is_error_true() -> None:
    r = CallToolResult(content=[TextContent(type="text", text="x")], isError=True)
    assert result_is_error(r) is True


def test_result_is_error_false() -> None:
    r = CallToolResult(content=[TextContent(type="text", text="x")], isError=False)
    assert result_is_error(r) is False
