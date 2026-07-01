"""MCPClientManager — MCP server 连接 + 工具桥接生命周期（FR-1~5）。

async ctx mgr：``__aenter__`` 并发连接所有 server（stdio / Streamable HTTP）+
发现工具 + 注册进 ``ToolRegistry`` 单例（eager，LLM 首轮即见）；``__aexit__``
unregister 全部 MCP 工具 + 优雅关闭所有 session / 子进程。

**生命周期架构（per-server task）：** 每个 server 由专属 asyncio task 持有其
transport + session context（``_transport_and_session`` @asynccontextmanager，
在同 task 内 enter/exit）。``__aenter__`` 并发启动各 task 并等待就绪；
``__aexit__`` 触发各 task 的停止事件、await 其在同 task 内干净退出。
→ 避免 ``streamable_http_client`` 的 anyio cancel scope 跨 task（旧实现用
``AsyncExitStack`` 在 ``asyncio.gather`` 子 task 内 enter、主 task 退出，会抛
``RuntimeError: Attempted to exit cancel scope in a different task``）。

- 单 server 连接失败 / 超时隔离（工具不注入，NFR-6，FR-3 建立失败路径）；
- 运行时断连主动 unregister：持有期 ``send_ping`` 健康探测，ping 失败/超时即注销该 server
  全部工具（FR-3 收紧，工具不再滞留 LLM 工具列表）；
- 握手 / transport 封装内部（NFR-3，为 stateless 迁移留接口）；
- DAG：仅从 types / exceptions / registry / config / mapping 导入，禁从 agent 导入。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
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
    from collections.abc import AsyncIterator, Callable
    from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONNECT_TIMEOUT: float = 10.0
_DEFAULT_HEALTH_CHECK_INTERVAL: float = 5.0  # 运行时健康探测周期（FR-3 收紧：断连即注销）


class MCPClientManager:
    """MCP server 连接 + 工具桥接生命周期管理（async ctx mgr）。

    用法::

        async with MCPClientManager(config) as m:   # 并发连接 + 发现 + 注册
            loop = AgentLoop(provider, ...)
            await loop.run(prompt)
        # __aexit__: unregister 全部 MCP 工具 + 各 server task 同 task 退出
    """

    def __init__(
        self,
        config: MCPConfig,
        *,
        registry: ToolRegistry | None = None,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
        health_check_interval: float = _DEFAULT_HEALTH_CHECK_INTERVAL,
    ) -> None:
        if health_check_interval <= 0:
            # 非正值会让 _watch 把 interval 直接当 wait_for timeout，首轮 ping 即超时 →
            # 误判健康 server 断连并注销其全部工具（Review patch F1）。
            raise ValueError(
                f"health_check_interval 必须为正数（got {health_check_interval}）"
            )
        self._config = config
        self._registry = registry or ToolRegistry.get()
        self._connect_timeout = connect_timeout
        self._health_check_interval = health_check_interval
        self._server_tasks: list[asyncio.Task[None]] = []
        self._stops: list[asyncio.Event] = []
        # server 原始名 → 其已注册的 namespaced 工具名（断连时按 server 精确摘除，FR-3 收紧）
        self._registered: dict[str, list[str]] = {}

    async def __aenter__(self) -> MCPClientManager:
        await self._connect_all()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._unregister_all()
        for stop in self._stops:
            stop.set()
        if self._server_tasks:
            # 各 _server_loop 在自己的 task 内退出 transport context（同 task，不跨 task）
            await asyncio.gather(*self._server_tasks, return_exceptions=True)
        self._server_tasks.clear()
        self._stops.clear()

    async def _connect_all(self) -> None:
        """并发连接所有 server；单 server 失败 / 超时隔离（NFR-6）。"""
        if self._config.is_empty:
            logger.info("MCPClientManager: 无配置 server → 纯内置工具模式")
            return
        readies: list[asyncio.Event] = []
        stops: list[asyncio.Event] = []
        tasks: list[asyncio.Task[None]] = []
        for name, cfg in self._config.servers.items():
            ready = asyncio.Event()
            stop = asyncio.Event()
            readies.append(ready)
            stops.append(stop)
            tasks.append(asyncio.create_task(self._server_loop(name, cfg, ready, stop)))
        self._server_tasks = tasks
        self._stops = stops
        # 并发等待全部就绪（成功 / 失败 / 超时都会 set ready，故不会 hang）
        await asyncio.gather(*[r.wait() for r in readies], return_exceptions=True)

    async def _server_loop(
        self,
        name: str,
        cfg: ServerConfig,
        ready: asyncio.Event,
        stop: asyncio.Event,
    ) -> None:
        """单 server 完整生命周期：连接+发现（带超时，就绪通知）→ 持有 → 同 task 退出。

        transport + session context 由 ``_transport_and_session`` 提供，在本 task
        内 enter/exit（避免 anyio cancel scope 跨 task）。连接 / 发现失败或超时
        仅 set ready（隔离），其工具不注入。
        """
        cm = self._transport_and_session(name, cfg)
        entered = False
        try:
            async with asyncio.timeout(self._connect_timeout):
                session: ClientSession = await cm.__aenter__()
                entered = True
                await self._discover_and_register(name, session)
            # 连接 + 发现成功（timeout 正常结束，不限制后续持有时间）
            ready.set()
            # 持有直到 __aexit__（stop）或健康探测发现运行时断连（FR-3 收紧）
            await self._watch(name, session, stop)
        except TimeoutError:
            logger.warning("MCP server '%s' 连接/发现超时（%ss），已隔离", name, self._connect_timeout)
            ready.set()
        except Exception as exc:  # noqa: BLE001 - 隔离任意连接 / 发现失败，不崩溃 agent
            logger.warning("MCP server '%s' 连接/发现失败，已隔离：%s", name, exc)
            ready.set()
        finally:
            if entered:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001 - 退出清理异常不向上传播
                    logger.warning("MCP server '%s' 关闭时异常，已忽略", name)

    @asynccontextmanager
    async def _transport_and_session(
        self,
        name: str,
        cfg: ServerConfig,
    ) -> AsyncIterator[ClientSession]:
        """建立 transport + ClientSession（同 task enter/exit，yield 已 initialize 的 session）。

        transport 细节（stdio 子进程 / Streamable HTTP / 握手）封装于此，
        为 2026-07-28 stateless 迁移留接口（NFR-3）。
        """
        if isinstance(cfg, StdioServerConfig):
            params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                logger.info("MCP server '%s' 已连接（StdioServerConfig）", name)
                yield session
        elif isinstance(cfg, HttpServerConfig):
            # streamable_http_client 无 headers 形参；鉴权 header 经自定义 http_client 注入。
            # 多 context with：顺序 enter，后置 context 可引用前置产物（transport[0]/[1]）。
            async with (
                httpx.AsyncClient(headers=cfg.headers) as http_client,
                streamable_http_client(cfg.url, http_client=http_client) as transport,
                ClientSession(transport[0], transport[1]) as session,
            ):
                await session.initialize()
                logger.info("MCP server '%s' 已连接（HttpServerConfig）", name)
                yield session
        else:  # pragma: no cover - ServerConfig union 仅两型
            raise TypeError(f"未知 MCP server 配置类型：{type(cfg).__name__}")

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
            self._registered.setdefault(name, []).append(schema.name)
            registered += 1
        logger.info("MCP server '%s'：发现 %d 个工具，注册 %d 个", name, len(result.tools), registered)

    def _make_handler(self, session: ClientSession, tool_name: str) -> Callable[..., Any]:
        """构造 MCP 工具闭包 handler：call_tool → bridge_result（isError → raise ToolError）。

        handler 契约契合 AgentLoop._invoke（async + **arguments）；返回 str 作为
        ToolResult.content，抛 ToolError 被 _execute_one 转 is_error=True（FR-5）。
        session 由对应 server task 持有，handler 在调用方 task 跨 task await call_tool。
        """

        async def handler(**kwargs: Any) -> str:
            result = await session.call_tool(tool_name, kwargs or None)
            return bridge_result(result)

        return handler

    def _unregister_server(self, name: str) -> None:
        """注销单个 server 的全部工具（运行时断连用）。``registry.unregister`` 幂等。"""
        for tool_name in self._registered.pop(name, ()):
            self._registry.unregister(tool_name)

    def _unregister_all(self) -> None:
        """从 ToolRegistry 摘除全部 MCP 工具（还原纯内置状态，利于测试隔离）。"""
        # 委托 _unregister_server：其 ``pop(name, ())`` 会清键，遍历完后 _registered 自然为空。
        for name in list(self._registered):
            self._unregister_server(name)

    async def _watch(self, name: str, session: ClientSession, stop: asyncio.Event) -> None:
        """持有 session 直到 ``stop`` 或健康探测发现运行时断连（FR-3 收紧）。

        每 ``_health_check_interval`` 秒 race 一次 ``stop.wait()``；未 stop 则 ping。
        ping 失败或超时 → 该 server 已不可达 → 注销其全部工具 + WARNING，随后返回
        （``_server_loop`` 在 ``finally`` 同 task 退出 transport context）。

        ping 与 session 同 task，沿用既有的「transport 同 task enter/exit」架构，
        避免 anyio cancel scope 跨 task 回归。``stop`` 优先：``__aexit__`` 触发时
        立即返回，不再 ping。
        """
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._health_check_interval)
                return  # stop 已 set（__aexit__ 触发）→ 立即退出，不再 ping
            except TimeoutError:
                pass
            try:
                await asyncio.wait_for(session.send_ping(), timeout=self._health_check_interval)
            except Exception as exc:  # noqa: BLE001 - 任意 ping 失败/超时 = 断连
                logger.warning("MCP server '%s' 运行时断连（ping 失败），已注销其工具：%s", name, exc)
                self._unregister_server(name)
                return
