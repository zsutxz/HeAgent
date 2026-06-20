"""MCPClientManager 真实 streamable_http 路径回归测试。

本地起 in-process FastMCP + uvicorn server，用真实 ``streamable_http_client`` 连，
覆盖 Stub（``test_mcp_manager.py``）无法触及的 anyio cancel scope 跨 task 路径。

**回归防护对象**：旧 ``AsyncExitStack`` 实现在 ``_connect_all`` 的 ``asyncio.gather``
子 task 内 enter ``streamable_http_client`` 的 cancel scope，``__aexit__`` 在主 task
退出 → ``RuntimeError: Attempted to exit cancel scope in a different task than it was
entered in``。per-server task 重构后每个 server 的 transport context 在专属 task
内 enter/exit（同 task），本测试验证 exit 不再抛 RuntimeError。
"""

from __future__ import annotations

import asyncio
import socket

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

from heagent.tools.mcp import MCPClientManager
from heagent.tools.mcp.config import HttpServerConfig, MCPConfig
from heagent.tools.registry import ToolRegistry


def _free_port() -> int:
    """获取一个当前可用的本地端口（bind 0 后释放；best-effort，极小 race 窗口）。"""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _make_echo_server() -> FastMCP:
    """单工具 echo 的 FastMCP server（echo(text) → "echo:{text}"）。"""
    mcp = FastMCP("heagent-test")

    @mcp.tool()
    def echo(text: str) -> str:
        """Echo the input text back with a prefix."""
        return f"echo:{text}"

    return mcp


@pytest.fixture
async def http_mcp_server() -> int:
    """启动本地 FastMCP（streamable HTTP）server，yield 端口号，退出时关闭。

    环境问题（uvicorn 起不来）→ skip 而非 fail（本测试不验证 uvicorn 本身）。
    """
    port = _free_port()
    app = _make_echo_server().streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    # 轮询等待 server 就绪（最多 ~3s）
    for _ in range(60):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:
        serve_task.cancel()
        pytest.skip("本地 uvicorn MCP server 未能在限内启动")

    try:
        yield port
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            serve_task.cancel()


async def test_real_http_enter_discover_call_exit(http_mcp_server: int) -> None:
    """真实 streamable_http 全流程：连接→发现 namespace 化→跨 task 调用→退出。

    旧实现会在 ``__aexit__`` 抛 ``RuntimeError``（cancel scope 跨 task）→ 本测试 error。
    修复后退出干净；handler 在调用方 task 跨 task await ``session.call_tool``。
    """
    port = http_mcp_server
    cfg = MCPConfig(servers={"test": HttpServerConfig(url=f"http://127.0.0.1:{port}/mcp")})
    reg = ToolRegistry()
    async with MCPClientManager(cfg, registry=reg, connect_timeout=10) as mgr:  # noqa: F841
        # 发现 + namespace 化（FR-4/6）
        assert "test__echo" in reg.list_names(), f"应发现 test__echo，实际 {reg.list_names()}"
        # 跨 task 调用：handler 在测试 task，session 在 _server_loop task
        handler = reg.get_handler("test__echo")
        assert handler is not None
        result = await handler(text="hello")
        assert result == "echo:hello"
    # 若 __aexit__ 抛 RuntimeError，async with 退出时本测试即 error


async def test_real_http_unregister_on_exit(http_mcp_server: int) -> None:
    """真实 server 退出后 MCP 工具从 registry 卸载（还原纯内置状态，FR-2）。"""
    port = http_mcp_server
    cfg = MCPConfig(servers={"test": HttpServerConfig(url=f"http://127.0.0.1:{port}/mcp")})
    reg = ToolRegistry()
    async with MCPClientManager(cfg, registry=reg, connect_timeout=10):
        assert "test__echo" in reg.list_names()
    assert "test__echo" not in reg.list_names()
