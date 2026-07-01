"""Story 1.4 — MCPClientManager 连接生命周期（FR-1~5）。Stub，无网络。

``_transport_and_session`` 被 monkeypatch 为 yield 预设 StubSession 的
@asynccontextmanager，避免真实 transport / 子进程；
每个测试用独立的 ``ToolRegistry()`` 实例（不碰进程单例，零回归）。
覆盖并发连接 / 单 server 隔离 / 超时 / 发现注册 / namespace 冲突 / handler 桥接 / 卸载。

真实 transport 路径（含 anyio cancel scope 跨 task 回归防护）见
``test_mcp_manager_http.py``（本地 in-process MCP server）。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from heagent.exceptions import ToolError
from heagent.tools.mcp.config import (
    HttpServerConfig,
    MCPConfig,
    StdioServerConfig,
)
from heagent.tools.mcp.manager import MCPClientManager
from heagent.tools.registry import ToolRegistry


class StubSession:
    """模拟 ClientSession（initialize / list_tools / call_tool）。"""

    def __init__(
        self,
        tools: list[Tool],
        call_result: CallToolResult | None = None,
        *,
        list_raises: Exception | None = None,
    ) -> None:
        self._tools = tools
        self._call_result = call_result or CallToolResult(content=[TextContent(type="text", text="ok")], isError=False)
        self.list_raises = list_raises
        self.initialized = False
        self.disconnected = False  # 运行时断连标志：置 True 后 send_ping 抛错（模拟 server 崩溃 / 网络断）

    async def initialize(self) -> None:
        self.initialized = True

    async def send_ping(self, **_: Any) -> None:
        """模拟 ClientSession.send_ping：disconnected 时抛错，否则成功（健康探测用）。"""
        if self.disconnected:
            raise RuntimeError("stub session disconnected")

    async def list_tools(self, **_: Any) -> Any:
        if self.list_raises is not None:
            raise self.list_raises

        class _Result:
            tools = self._tools

        return _Result()

    async def call_tool(self, name: str, arguments: Any = None, **_: Any) -> CallToolResult:
        self._last_call = (name, arguments)
        return self._call_result


def _tool(name: str, desc: str = "d") -> Tool:
    return Tool(name=name, description=desc, inputSchema={"type": "object"})


def _patch_transport(monkeypatch: pytest.MonkeyPatch, sessions: dict[str, StubSession]) -> None:
    """让 _transport_and_session yield 预设 StubSession（按 server 原始名分派）。"""

    @asynccontextmanager
    async def fake_transport(self: MCPClientManager, name: str, cfg: Any) -> Any:
        s = sessions[name]
        await s.initialize()
        yield s

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", fake_transport)


# --- 连接 + 发现 + 注册（FR-1/2/4）---


async def test_connect_discovers_and_registers_stdio_and_http(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MCPConfig(
        servers={
            "local": StdioServerConfig(command="x"),
            "github": HttpServerConfig(url="https://api.example/mcp", headers={"Authorization": "Bearer t"}),
        }
    )
    sessions = {
        "local": StubSession([_tool("run"), _tool("build")]),
        "github": StubSession([_tool("list_issues")]),
    }
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(cfg, registry=reg):
        names = reg.list_names()
    assert {"local__run", "local__build", "github__list_issues"} <= set(names)


async def test_empty_config_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    @asynccontextmanager
    async def spy(self: MCPClientManager, name: str, cfg: Any) -> Any:
        opened.append(name)
        yield StubSession([])

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", spy)
    reg = ToolRegistry()
    async with MCPClientManager(MCPConfig(), registry=reg):
        pass
    assert opened == []
    assert reg.list_names() == []


# --- 失败 / 超时隔离（FR-3 / NFR-4 / NFR-6）---


async def test_single_server_failure_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = {
        "bad": StubSession([], list_raises=RuntimeError("conn refused")),
        "good": StubSession([_tool("run")]),
    }
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(
            servers={
                "bad": StdioServerConfig(command="x"),
                "good": StdioServerConfig(command="y"),
            }
        ),
        registry=reg,
    ):
        names = reg.list_names()
    assert "good__run" in names
    assert not any(n.startswith("bad__") for n in names)


async def test_connect_timeout_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def slow_transport(self: MCPClientManager, name: str, cfg: Any) -> Any:
        await asyncio.sleep(0.3)
        yield StubSession([])

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", slow_transport)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(servers={"s": StdioServerConfig(command="x")}),
        registry=reg,
        connect_timeout=0.05,
    ):
        assert reg.list_names() == []


# --- namespace 冲突（FR-6）---


async def test_namespace_collision_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = {
        "GitHub MCP": StubSession([_tool("list")]),
        "github-mcp": StubSession([_tool("list")]),
    }
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(
            servers={
                "GitHub MCP": StdioServerConfig(command="a"),
                "github-mcp": StdioServerConfig(command="b"),
            }
        ),
        registry=reg,
    ):
        names = reg.list_names()
    assert names.count("github_mcp__list") == 1


# --- handler 桥接（FR-5）---


async def test_handler_returns_bridged_text(monkeypatch: pytest.MonkeyPatch) -> None:
    result = CallToolResult(content=[TextContent(type="text", text="done")], isError=False)
    sessions = {"s": StubSession([_tool("run")], call_result=result)}
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(MCPConfig(servers={"s": StdioServerConfig(command="x")}), registry=reg):
        handler = reg.get_handler("s__run")
        assert handler is not None
        out = await handler(arg="v")  # type: ignore[operator]
    assert out == "done"


async def test_handler_iserror_raises_toolerror(monkeypatch: pytest.MonkeyPatch) -> None:
    result = CallToolResult(content=[TextContent(type="text", text="boom")], isError=True)
    sessions = {"s": StubSession([_tool("run")], call_result=result)}
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(MCPConfig(servers={"s": StdioServerConfig(command="x")}), registry=reg):
        handler = reg.get_handler("s__run")
        assert handler is not None
        with pytest.raises(ToolError):
            await handler()  # type: ignore[operator]


# --- 卸载（FR-2 生命周期）---


async def test_unregister_all_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = {"s": StubSession([_tool("run")])}
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(MCPConfig(servers={"s": StdioServerConfig(command="x")}), registry=reg):
        assert "s__run" in reg.list_names()
    assert "s__run" not in reg.list_names()


# --- 运行时断连主动 unregister（FR-3 收紧）---


def test_health_check_interval_must_be_positive() -> None:
    """health_check_interval<=0 会让 _watch 首个 ping 立即 TimeoutError → 误注销健康 server；构造期拒绝。

    Review patch F1：非正值把 interval 直接当 wait_for timeout，首轮即超时判死。
    """
    with pytest.raises(ValueError):
        MCPClientManager(MCPConfig(), health_check_interval=0)
    with pytest.raises(ValueError):
        MCPClientManager(MCPConfig(), health_check_interval=-1)


async def _wait_removed(reg: ToolRegistry, name: str, *, timeout_s: float = 1.0) -> bool:
    """轮询至工具从 registry 消失（抗 CI 抖动，最多等 timeout_s 秒）。"""
    for _ in range(int(timeout_s / 0.01)):
        if name not in reg.list_names():
            return True
        await asyncio.sleep(0.01)
    return name not in reg.list_names()


async def test_disconnect_auto_unregisters(monkeypatch: pytest.MonkeyPatch) -> None:
    """运行时断连 → _watch 探测 ping 失败 → 该 server 工具主动注销（无需调用触发）。"""
    sessions = {"s": StubSession([_tool("run")])}
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(servers={"s": StdioServerConfig(command="x")}),
        registry=reg,
        health_check_interval=0.01,
    ):
        assert "s__run" in reg.list_names()
        sessions["s"].disconnected = True  # 模拟 server 崩溃 / 网络断
        removed = await _wait_removed(reg, "s__run")
    assert removed, "断连后该 server 工具未在探测周期内注销"


async def test_disconnect_isolated_to_one_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """单 server 断连只注销它自己的工具，另一 server + 内置工具零影响（NFR-6）。"""
    sessions = {
        "a": StubSession([_tool("run")]),
        "b": StubSession([_tool("build")]),
    }
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(
            servers={
                "a": StdioServerConfig(command="x"),
                "b": StdioServerConfig(command="y"),
            }
        ),
        registry=reg,
        health_check_interval=0.01,
    ):
        sessions["a"].disconnected = True
        removed = await _wait_removed(reg, "a__run")
        assert removed, "断连 server 工具未注销"
        assert "b__build" in reg.list_names()  # 另一 server 不受影响
