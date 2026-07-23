"""MCPClientManager — MCP server 连接 + 工具桥接生命周期（FR-1~5）。

async ctx mgr：``__aenter__`` 并发连接所有 server（stdio / Streamable HTTP）+
发现工具 + 注册进 ``ToolRegistry`` 单例（eager，LLM 首轮即见）；``__aexit__``
unregister 全部 MCP 工具 + 优雅关闭所有 session / 子进程（``shutdown_timeout`` 硬上界
兜底，transport close 挂死时 force-cancel，不无限阻塞进程退出）。

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
- ``__aexit__`` 关停带硬上界：transport close（stdio 忽略 SIGTERM / HTTP 不 FIN）挂死时，
  ``shutdown_timeout`` 后 force-cancel 未退出 task，不无限阻塞进程退出；
- 握手 / transport 封装内部（NFR-3，为 stateless 迁移留接口）；
- DAG：仅从 types / exceptions / registry / config / mapping 导入，禁从 agent 导入。
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import BlobResourceContents, TextContent, TextResourceContents

from heagent.exceptions import ToolError
from heagent.tools.mcp.config import (
    HttpServerConfig,
    MCPConfig,
    ServerConfig,
    StdioServerConfig,
)
from heagent.tools.mcp.mapping import bridge_result, guard_content, mcp_tool_to_schema
from heagent.tools.mcp.session_api import call_tool, handshake, list_tools, ping
from heagent.tools.registry import ToolRegistry
from heagent.types import ToolAnnotations, ToolSchema

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONNECT_TIMEOUT: float = 10.0
_DEFAULT_HEALTH_CHECK_INTERVAL: float = 5.0  # 运行时健康探测周期（FR-3 收紧：断连即注销）
_DEFAULT_SHUTDOWN_TIMEOUT: float = 5.0  # __aexit__ 关停硬上界（transport close 挂死兜底）


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
        shutdown_timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        if health_check_interval <= 0:
            # 非正值会让 _watch 把 interval 直接当 wait_for timeout，首轮 ping 即超时 →
            # 误判健康 server 断连并注销其全部工具（Review patch F1）。
            raise ValueError(f"health_check_interval 必须为正数（got {health_check_interval}）")
        if shutdown_timeout <= 0:
            # 非正值会让 _await_shutdown 首轮 wait 立即返回（全部 pending）→ 不给任何 task
            # graceful 关停机会即 force-cancel（与 health_check_interval<=0 误判同构）。
            raise ValueError(f"shutdown_timeout 必须为正数（got {shutdown_timeout}）")
        self._config = config
        self._registry = registry or ToolRegistry.get()
        self._connect_timeout = connect_timeout
        self._health_check_interval = health_check_interval
        self._shutdown_timeout = shutdown_timeout
        self._server_tasks: list[asyncio.Task[None]] = []
        self._stops: list[asyncio.Event] = []
        # server 原始名 → 其已注册的 namespaced 工具名（断连时按 server 精确摘除，FR-3 收紧）
        self._registered: dict[str, list[str]] = {}
        # 已连 session 查找表：server 原始名 → ClientSession
        # 供 bridge 工具（list_resources / read_resource）跨 task 访问；连接失败 / 断连时 pop。
        self._sessions: dict[str, ClientSession] = {}
        # 桥接工具是否已注册（mcp__list_resources + mcp__read_resource 两者统一标记）
        self._bridge_registered = False

    async def __aenter__(self) -> MCPClientManager:
        await self._connect_all()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._unregister_all()
        for stop in self._stops:
            stop.set()
        if self._server_tasks:
            # 各 _server_loop 在自己的 task 内退出 transport context（同 task，不跨 task）；
            # 带硬上界等待（transport close 挂死时 force-cancel，不无限阻塞进程退出）。
            await self._await_shutdown(self._server_tasks)
        self._server_tasks.clear()
        self._stops.clear()

    async def _await_shutdown(self, tasks: list[asyncio.Task[None]]) -> None:
        """带硬上界等待所有 server task 退出；超时取消未完成者并短等一次，绝不无限阻塞。

        ``_server_loop`` finally 的 ``await cm.__aexit__``（transport 关闭）在 stdio 子进程
        忽略 SIGTERM / HTTP 远端不 FIN 时可无限阻塞 → ``__aexit__`` 无上界（pre-existing
        LOW-MED）。本方法给整体关停硬上界：首轮 ``asyncio.wait`` 超时则 cancel 未完成 task
        （cancel 经 asyncio 注入其 finally，中断挂死的 ``cm.__aexit__``），二轮短等让被取消
        task 的 finally 收尾；二轮仍超时则记 ERROR 放弃。最坏 ~2×``_shutdown_timeout`` 必返回。

        ``asyncio.wait`` 不传播 task 内异常（等同原 ``gather(..., return_exceptions=True)``）——
        某 server 关闭异常不影响其它 / 不逸出 ``__aexit__``。
        """
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=self._shutdown_timeout)
        if not pending:
            return
        logger.warning(
            "MCP 关停超时（%ss），取消 %d 个未退出的 server task",
            self._shutdown_timeout,
            len(pending),
        )
        for task in pending:
            task.cancel()
        # 被取消 task 的 finally（cm.__aexit__ 被 CancelledError 中断）需一个 await tick 收尾；
        # 同样 bounded——若 finally 内有不可中断段致二轮超时，记 ERROR 放弃（task 已 cancel）。
        # 只 wait pending 子集（刚 cancel 的那批）；首轮已 done 的 task 不必重复注册回调。
        _, still_pending = await asyncio.wait(pending, timeout=self._shutdown_timeout)
        if still_pending:
            logger.error(
                "MCP 关停二次超时（%ss），%d 个 task 仍未退出，放弃等待",
                self._shutdown_timeout,
                len(still_pending),
            )

    async def _connect_all(self) -> None:
        """并发连接所有 server；单 server 失败 / 超时隔离（NFR-6）。"""
        if self._config.is_empty:
            logger.debug("MCPClientManager: 无配置 server → 纯内置工具模式")
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
        # 有至少一个 server 成功连接 → 注册桥接工具。
        # 注意：_sessions 仅包含成功建立连接 + 完成工具发现的 server；
        # 连接/发现失败的 server 不会出现在 _sessions 中，其工具不会被注入。
        # 因此 bridge 注册天然跳过失败 server 的工具——这是设计意图而非 bug。
        if self._sessions and not self._bridge_registered:
            self._register_bridge_tool()

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
                # 登记 session 至查找表（bridge 工具跨 task 寻址用；断连 / finally 摘除）
                self._sessions[name] = session
                await self._discover_and_register(name, session)
            # 连接 + 发现成功（timeout 正常结束，不限制后续持有时间）
            ready.set()
            # 持有直到 __aexit__（stop）或健康探测发现运行时断连（FR-3 收紧）
            await self._watch(name, session, stop)
        except TimeoutError:
            logger.warning("MCP server '%s' 连接/发现超时（%ss），已隔离", name, self._connect_timeout)
            self._sessions.pop(name, None)  # 发现失败→清除 session，避免桥接注册虚假工具
            ready.set()
        except Exception as exc:  # noqa: BLE001 - 隔离任意连接 / 发现失败，不崩溃 agent
            logger.warning("MCP server '%s' 连接/发现失败，已隔离：%s", name, exc)
            self._sessions.pop(name, None)  # 发现失败→清除 session，避免桥接注册虚假工具
            ready.set()
        finally:
            if entered:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001 - 退出清理异常不向上传播
                    logger.warning("MCP server '%s' 关闭时异常，已忽略", name)
            # 无论 entered 与否，均清除 session 查找表（连接失败时 early cleanup）
            self._sessions.pop(name, None)

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
                await handshake(session)
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
                await handshake(session)
                logger.info("MCP server '%s' 已连接（HttpServerConfig）", name)
                yield session
        else:  # pragma: no cover - ServerConfig union 仅两型
            raise TypeError(f"未知 MCP server 配置类型：{type(cfg).__name__}")

    async def _discover_and_register(self, name: str, session: ClientSession) -> None:
        """发现 server 工具并注册到 ToolRegistry（namespace 冲突跳过 + 告警，FR-6）。"""
        tools = await list_tools(session)
        registered = 0
        for tool in tools:
            schema = mcp_tool_to_schema(name, tool)
            if self._registry.get_schema(schema.name) is not None:
                logger.warning("MCP 工具 '%s' 命名冲突（已注册），跳过", schema.name)
                continue
            handler = self._make_handler(session, tool.name, name)
            self._registry.register(schema, handler)
            self._registered.setdefault(name, []).append(schema.name)
            registered += 1
        logger.info("MCP server '%s'：发现 %d 个工具，注册 %d 个", name, len(tools), registered)

    def _make_handler(self, session: ClientSession, tool_name: str, server_name: str = "") -> Callable[..., Any]:
        """构造 MCP 工具闭包 handler：call_tool → bridge_result（isError → raise ToolError）。

        handler 契约契合 AgentLoop._invoke（async + **arguments）；返回 str 作为
        ToolResult.content，抛 ToolError 被 _execute_one 转 is_error=True（FR-5）。
        session 由对应 server task 持有，handler 在调用方 task 跨 task await call_tool。
        """

        async def handler(**kwargs: Any) -> str:
            # P1-17: session liveness check — if server disconnected, return semantic error
            if server_name and self._sessions.get(server_name) is not session:
                raise ToolError(f"MCP server '{server_name}' disconnected")
            result = await call_tool(session, tool_name, kwargs or None)
            return bridge_result(result)

        return handler

    def _get_session(self, name: str) -> ClientSession:
        """按 server 名查找已连 session；未连 / 断连时抛 ToolError（不裸 KeyError）。"""
        session = self._sessions.get(name)
        if session is None:
            raise ToolError(f"MCP server '{name}' disconnected")
        return session

    def _unregister_server(self, name: str) -> None:
        """注销单个 server 的全部工具（运行时断连用）。``registry.unregister`` 幂等。"""
        for tool_name in self._registered.pop(name, ()):
            self._registry.unregister(tool_name)
        self._sessions.pop(name, None)

    def _unregister_all(self) -> None:
        """从 ToolRegistry 摘除全部 MCP 工具（还原纯内置状态，利于测试隔离）。"""
        # 1. 摘除桥接工具（先于 server 工具，避免 server unregister 误判 bridge 存活）
        if self._bridge_registered:
            self._registry.unregister("mcp__list_resources")
            self._registry.unregister("mcp__read_resource")
            self._bridge_registered = False
        # 2. 委托 _unregister_server：其 ``pop(name, ())`` 会清键，遍历完后 _registered 自然为空。
        for name in list(self._registered):
            self._unregister_server(name)
        # 3. 兜底清理 _sessions（_unregister_server 已逐 server pop，此处作双重确认）
        self._sessions.clear()

    def _register_bridge_tool(self) -> None:
        """注册 mcp__list_resources + mcp__read_resource 桥接工具（_connect_all 内惰性注册，幂等）。"""
        if self._bridge_registered:
            return
        # --- mcp__list_resources ---
        if self._registry.get_schema("mcp__list_resources") is not None:
            # 命名冲突：server 名为 "mcp" 且其工具叫 "list_resources" 时，namespaced 名同为
            # mcp__list_resources（registry.register 重复注册会静默覆盖）。不覆盖 server 工具——
            # 告警跳过，保留 server 原工具（极端边缘情况，fail-safe 不静默丢工具）。
            logger.warning(
                "mcp__list_resources 命名冲突（registry 已有同名工具，疑似 server 'mcp' 注册），跳过桥接注册"
            )
            return
        list_schema = ToolSchema(
            name="mcp__list_resources",
            description="列出所有已连 MCP server 暴露的资源。返回 JSON 数组，每元素含 server/uri/name/description。",
            parameters={"type": "object", "properties": {}, "required": []},
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        self._registry.register(list_schema, self._handle_list_resources)

        # --- mcp__read_resource ---
        if self._registry.get_schema("mcp__read_resource") is not None:
            logger.warning("mcp__read_resource 命名冲突（registry 已有同名工具），跳过桥接注册")
            # 回滚已注册的 list_resources
            self._registry.unregister("mcp__list_resources")
            return
        read_schema = ToolSchema(
            name="mcp__read_resource",
            description="读取指定 MCP server 上某 URI 的资源内容。server 必填，uri 为完整资源 URI。返回文本内容。",
            parameters={
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "目标 MCP server 名"},
                    "uri": {"type": "string", "description": "资源 URI"},
                },
                "required": ["server", "uri"],
            },
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        self._registry.register(read_schema, self._handle_read_resource)

        self._bridge_registered = True
        logger.info("MCP 桥接工具 'mcp__list_resources' 和 'mcp__read_resource' 已注册")

    async def _handle_list_resources(self) -> str:
        """mcp__list_resources handler：聚合所有已连 session 的 resources。"""
        results: list[dict[str, object]] = []
        for name, session in list(self._sessions.items()):
            try:
                resp = await session.list_resources()
            except Exception as exc:  # noqa: BLE001 - 单 server 失败隔离，不崩溃整体
                logger.warning("MCP server '%s' list_resources 失败，跳过：%s", name, exc)
                continue
            for r in resp.resources:
                results.append(
                    {
                        "server": name,
                        "uri": str(r.uri),
                        "name": r.name,
                        "description": r.description or "",
                    }
                )
        return json.dumps(results, ensure_ascii=False)

    async def _handle_read_resource(self, server: str, uri: str) -> str:
        """mcp__read_resource handler：读取指定 server 上某 URI 的资源内容，经注入围栏标记后返回。"""
        session = self._get_session(server)
        try:
            resp = await session.read_resource(uri)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - 将任意 read_resource 失败转为 ToolError
            raise ToolError(f"Failed to read resource '{uri}' from server '{server}': {exc}") from exc
        # 转换资源内容为文本（类似 call_result_to_text 但作用于 ReadResourceResult.contents）
        parts: list[str] = []
        for content in resp.contents:
            if isinstance(content, TextResourceContents):
                parts.append(content.text)
            elif isinstance(content, BlobResourceContents):
                mime = content.mimeType or "application/octet-stream"
                parts.append(f"[binary: {mime}]")
            else:
                parts.append(f"[unknown: {type(content).__name__}]")
        text = "\n".join(parts)
        return guard_content(text)

    # ── Story 16-1: Prompts 读取入口（经 _sessions，非 LLM 工具）──

    async def list_prompts(self, server: str | None = None) -> str:
        """列出 MCP server 的 Prompts 模板清单（CLI slash 分发器用，非 LLM 工具）。

        指定 ``server`` 时仅返回该 server 的模板，否则聚合所有已连 server。
        返回 JSON 字符串，每项含 ``{server, name, description, arguments}``。
        无模板 / 无 server 连接时返回 ``[]``（不抛错），单 server 失败隔离。
        """
        results: list[dict[str, object]] = []
        if server is not None:
            session = self._get_session(server)
            try:
                resp = await session.list_prompts()
            except Exception as exc:  # noqa: BLE001 - 单 server 失败不向上传播
                logger.warning("MCP server '%s' list_prompts 失败：%s", server, exc)
                return "[]"
            for p in resp.prompts:
                args = [
                    {"name": a.name, "description": a.description or "", "required": a.required or False}
                    for a in (p.arguments or [])
                ]
                results.append(
                    {
                        "server": server,
                        "name": p.name,
                        "description": p.description or "",
                        "arguments": args,
                    }
                )
            return json.dumps(results, ensure_ascii=False)

        # 聚合所有 server
        for name in list(self._sessions):
            try:
                sub = json.loads(await self.list_prompts(name))
                results.extend(sub)
            except Exception as exc:  # noqa: BLE001 - 单 server 失败隔离
                logger.warning("MCP server '%s' list_prompts 聚合失败：%s", name, exc)
        return json.dumps(results, ensure_ascii=False)

    async def get_prompt(self, server: str, name: str, arguments: dict[str, str] | None = None) -> str:
        """渲染指定 MCP server 上的 Prompt 模板并返回文本内容（CLI slash 分发器用，非 LLM 工具）。

        经 ``_get_session(server)`` 取 session 后调 ``session.get_prompt()``。
        返回渲染文本（从返回的 PromptMessage 中提取 text content），
        模板不存在 / 参数缺失时抛 ``ToolError``。
        """
        session = self._get_session(server)
        try:
            resp = await session.get_prompt(name, arguments)
        except Exception as exc:  # noqa: BLE001 - 将任意 get_prompt 失败转为 ToolError
            raise ToolError(f"Failed to get prompt '{name}' from server '{server}': {exc}") from exc
        parts: list[str] = []
        for msg in resp.messages:
            if isinstance(msg.content, TextContent):
                parts.append(msg.content.text)
            else:
                parts.append(f"[{type(msg.content).__name__}]")
        return "\n".join(parts)

    # ── 持有期运行时 ──

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
                await ping(session, self._health_check_interval)
            except Exception as exc:  # noqa: BLE001 - 任意 ping 失败/超时 = 断连
                logger.warning("MCP server '%s' 运行时断连（ping 失败），已注销其工具：%s", name, exc)
                self._unregister_server(name)
                return
