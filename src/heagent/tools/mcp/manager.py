"""MCPClientManager — MCP server 连接 + 工具桥接生命周期（FR-1~5）。

async ctx mgr：``__aenter__`` 并发连接所有 server（stdio / Streamable HTTP）+
发现工具 + 注册进 ``ToolRegistry`` 单例（eager，LLM 首轮即见）；``__aexit__``
unregister 全部 MCP 工具 + 关闭所有 session / 子进程（``AsyncExitStack`` 托管）。

- 单 server 连接失败 / 超时隔离（工具不注入，NFR-6，FR-3 建立失败路径）；
- 握手 / transport 封装内部（NFR-3，为 stateless 迁移留接口）；
- DAG：仅从 types / exceptions / registry / config / mapping 导入，禁从 agent 导入。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from heagent.tools.mcp.config import (
    HttpServerConfig,
    MCPConfig,
    ServerConfig,
    StdioServerConfig,
)
from heagent.tools.mcp.mapping import bridge_result, mcp_tool_to_schema
from heagent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONNECT_TIMEOUT: float = 10.0


class MCPClientManager:
    """MCP server 连接 + 工具桥接生命周期管理（async ctx mgr）。

    用法::

        async with MCPClientManager(config) as m:   # 并发连接 + 发现 + 注册
            loop = AgentLoop(provider, ...)
            await loop.run(prompt)
        # __aexit__: unregister 全部 MCP 工具 + 关闭 session / 子进程
    """

    def __init__(
        self,
        config: MCPConfig,
        *,
        registry: ToolRegistry | None = None,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        self._config = config
        self._registry = registry or ToolRegistry.get()
        self._connect_timeout = connect_timeout
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._registered: list[str] = []  # 已注册的 namespaced 工具名（unregister 用）

    async def __aenter__(self) -> MCPClientManager:
        await self._connect_all()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._unregister_all()
        await self._stack.aclose()

    async def _connect_all(self) -> None:
        """并发连接所有 server；单 server 失败 / 超时隔离（return_exceptions，NFR-6）。"""
        if self._config.is_empty:
            logger.info("MCPClientManager: 无配置 server → 纯内置工具模式")
            return
        tasks = [self._connect(name, cfg) for name, cfg in self._config.servers.items()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _connect(self, name: str, cfg: ServerConfig) -> None:
        """连接单个 server + 发现 + 注册；超时 / 失败隔离（工具不注入）。"""
        try:
            async with asyncio.timeout(self._connect_timeout):
                session = await self._open_session(name, cfg)
                await self._discover_and_register(name, session)
        except TimeoutError:
            logger.warning("MCP server '%s' 连接/发现超时（%ss），已隔离", name, self._connect_timeout)
        except Exception as exc:  # noqa: BLE001 - 隔离任意连接 / 发现失败，不崩溃 agent
            logger.warning("MCP server '%s' 连接/发现失败，已隔离：%s", name, exc)

    async def _open_session(self, name: str, cfg: ServerConfig) -> ClientSession:
        """建立 transport + ClientSession（注册到 stack 托管），返回已 initialize 的 session。

        transport 细节（stdio 子进程 / Streamable HTTP / 握手）封装于此，
        为 2026-07-28 stateless 迁移留接口（NFR-3）。
        """
        if isinstance(cfg, StdioServerConfig):
            params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif isinstance(cfg, HttpServerConfig):
            # streamable_http_client 无 headers 形参；鉴权 header 经自定义 http_client 注入。
            http_client = httpx.AsyncClient(headers=cfg.headers)
            await self._stack.enter_async_context(http_client)  # 托管生命周期（aclose 幂等）
            transport_ctx = streamable_http_client(cfg.url, http_client=http_client)
            entered = await self._stack.enter_async_context(transport_ctx)
            read, write = entered[0], entered[1]
        else:  # pragma: no cover - ServerConfig union 仅两型
            raise TypeError(f"未知 MCP server 配置类型：{type(cfg).__name__}")
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[name] = session
        logger.info("MCP server '%s' 已连接（%s）", name, type(cfg).__name__)
        return session

    async def _discover_and_register(self, name: str, session: ClientSession) -> None:
        """发现 server 工具并注册到 ToolRegistry（namespace 冲突跳过 + 告警，FR-6）。"""
        result = await session.list_tools()
        registered = 0
        for tool in result.tools:
            schema = mcp_tool_to_schema(name, tool)
            if self._registry.get_schema(schema.name) is not None:
                logger.warning("MCP 工具 '%s' 命名冲突（已注册），跳过", schema.name)
                continue
            handler = self._make_handler(session, tool.name)
            self._registry.register(schema, handler)
            self._registered.append(schema.name)
            registered += 1
        logger.info("MCP server '%s'：发现 %d 个工具，注册 %d 个", name, len(result.tools), registered)

    def _make_handler(self, session: ClientSession, tool_name: str) -> Callable[..., Any]:
        """构造 MCP 工具闭包 handler：call_tool → bridge_result（isError → raise ToolError）。

        handler 契约契合 AgentLoop._invoke（async + **arguments）；返回 str 作为
        ToolResult.content，抛 ToolError 被 _execute_one 转 is_error=True（FR-5）。
        """

        async def handler(**kwargs: Any) -> str:
            result = await session.call_tool(tool_name, kwargs or None)
            return bridge_result(result)

        return handler

    def _unregister_all(self) -> None:
        """从 ToolRegistry 摘除全部 MCP 工具（还原纯内置状态，利于测试隔离）。"""
        for tool_name in self._registered:
            self._registry.unregister(tool_name)
        self._registered.clear()
        self._sessions.clear()
