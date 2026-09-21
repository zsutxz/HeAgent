"""MCPClientManager — MCP server 连接 + 工具桥接生命周期（FR-1~5）。

manager 是**生命周期 façade**（2026-09-21 Phase 4 C2 分层，沿 AgentLoop façade 先例）：
transport/session 开启委托 :mod:`.client`（:class:`~heagent.tools.mcp.client.TransportOpener`
端口可注入），registry 注册/注销委托 :mod:`.registry_bridge`（单一入口）；本模块只承载
per-server task 生命周期与健康探测。

async ctx mgr：``__aenter__`` 并发连接所有 server（stdio / Streamable HTTP）+
发现工具 + 注册进 ``ToolRegistry``（eager，LLM 首轮即见）；``__aexit__``
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
  失败结构化记录进 :attr:`discovery_failures`（不隐藏发现错误，入口层渲染呈报）；
- 运行时断连主动 unregister：持有期 ``send_ping`` 健康探测，ping 失败/超时即注销该 server
  全部工具（FR-3 收紧，工具不再滞留 LLM 工具列表）；
- ``__aexit__`` 关停带硬上界：transport close（stdio 忽略 SIGTERM / HTTP 不 FIN）挂死时，
  ``shutdown_timeout`` 后 force-cancel 未退出 task，不无限阻塞进程退出；
- 握手 / transport 封装内部（NFR-3，为 stateless 迁移留接口）；
- DAG：仅从 types / exceptions / registry / config / mapping / client / registry_bridge 导入，禁从 agent 导入。
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from mcp.types import BlobResourceContents, TextContent, TextResourceContents
from pydantic import BaseModel

from heagent.exceptions import ToolError
from heagent.tools.mcp.client import TransportOpener, default_transport_opener
from heagent.tools.mcp.mapping import bridge_result, guard_content, mcp_tool_to_schema
from heagent.tools.mcp.registry_bridge import RegistryBridge
from heagent.tools.mcp.session_api import call_tool, list_tools, ping
from heagent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from typing import Any

    from mcp import ClientSession

    from heagent.tools.mcp.config import MCPConfig, ServerConfig

logger = logging.getLogger(__name__)

_DEFAULT_CONNECT_TIMEOUT: float = 10.0
_DEFAULT_HEALTH_CHECK_INTERVAL: float = 5.0  # 运行时健康探测周期（FR-3 收紧：断连即注销）
_DEFAULT_SHUTDOWN_TIMEOUT: float = 5.0  # __aexit__ 关停硬上界（transport close 挂死兜底）


class MCPServerFailure(BaseModel):
    """单 server 连接/发现失败的结构化记录（入口层渲染呈报，不隐藏发现错误）。"""

    server: str
    reason: str


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
        transport_opener: TransportOpener | None = None,
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
        # registry 写入单一入口（server 工具 + 桥接工具的注册/注销与冲突策略收敛于此）
        self._bridge = RegistryBridge(self._registry)
        self._connect_timeout = connect_timeout
        self._health_check_interval = health_check_interval
        self._shutdown_timeout = shutdown_timeout
        # transport 开启端口：缺省 SDK 实现；注入点供测试/替换（无需 class-patch 缝）。
        self._transport_opener = transport_opener
        self._server_tasks: list[asyncio.Task[None]] = []
        self._stops: list[asyncio.Event] = []
        # 已连 session 查找表：server 原始名 → ClientSession
        # 供 bridge 工具（list_resources / read_resource）跨 task 访问；连接失败 / 断连时 pop。
        self._sessions: dict[str, ClientSession] = {}
        # 连接/发现失败的结构化记录（不隐藏发现错误；入口层经 discovery_failures 读取呈报）
        self._discovery_failures: list[MCPServerFailure] = []

    @property
    def discovery_failures(self) -> list[MCPServerFailure]:
        """连接/发现阶段失败的 server 清单（单 server 隔离后仍可见，快照副本）。"""
        return list(self._discovery_failures)

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
        # （幂等守卫在 RegistryBridge.register_bridge_tools 内部。）
        if self._sessions:
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
            self._discovery_failures.append(
                MCPServerFailure(server=name, reason=f"连接/发现超时（{self._connect_timeout}s）")
            )
            self._sessions.pop(name, None)  # 发现失败→清除 session，避免桥接注册虚假工具
            ready.set()
        except Exception as exc:  # noqa: BLE001 - 隔离任意连接 / 发现失败，不崩溃 agent
            logger.warning("MCP server '%s' 连接/发现失败，已隔离：%s", name, exc)
            self._discovery_failures.append(MCPServerFailure(server=name, reason=str(exc)))
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

        开启逻辑委托注入的 ``transport_opener``（缺省 SDK 实现，见 :mod:`.client`）；
        本方法保留为**monkeypatch 缝宿主**（测试 class-patch 此方法注入 fake transport）
        并负责连接成功日志（带 server 名，属生命周期编排侧信息）。
        """
        opener = self._transport_opener or default_transport_opener
        async with opener(cfg) as session:
            logger.info("MCP server '%s' 已连接（%s）", name, type(cfg).__name__)
            yield session

    async def _discover_and_register(self, name: str, session: ClientSession) -> None:
        """发现 server 工具并经 RegistryBridge 注册（namespace 冲突跳过 + 告警，FR-6）。"""
        tools = await list_tools(session)
        registered = 0
        for tool in tools:
            schema = mcp_tool_to_schema(name, tool)
            handler = self._make_handler(session, tool.name, name)
            if self._bridge.register_server_tool(server_name=name, schema=schema, handler=handler):
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
        """注销单个 server 的全部工具（运行时断连用）。委托 RegistryBridge 单一入口。"""
        self._bridge.unregister_server(name)
        self._sessions.pop(name, None)

    def _unregister_all(self) -> None:
        """从 ToolRegistry 摘除全部 MCP 工具（还原纯内置状态，利于测试隔离）。"""
        self._bridge.unregister_all()
        # 兜底清理 _sessions（bridge 已不持有 session；此处清 manager 侧查找表）
        self._sessions.clear()

    def _register_bridge_tool(self) -> None:
        """注册 mcp__list_resources + mcp__read_resource 桥接工具（_connect_all 内惰性注册，幂等）。"""
        self._bridge.register_bridge_tools(self._handle_list_resources, self._handle_read_resource)

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

    async def _stop_requested(self, stop: asyncio.Event) -> bool:
        """等 ``stop`` 至多 ``_health_check_interval`` 秒；True = 收到关停信号。

        与 ping 的超时**分义**（deferred-work 2026-07-01）：本 helper 吞掉自身的 ``TimeoutError``
        并返回 False，使 ``_watch`` 循环体内 ``TimeoutError`` 只剩「ping 超时 = 断连」一种含义。
        原实现两个 ``wait_for`` 的 ``TimeoutError`` 同名异义、仅靠 try 块物理位置区分——未来
        合并 try 块的重构会把「关停等待超时」误判为「断连」→ 误注销健康 server。
        """
        try:
            await asyncio.wait_for(stop.wait(), timeout=self._health_check_interval)
        except TimeoutError:
            return False
        return True

    async def _watch(self, name: str, session: ClientSession, stop: asyncio.Event) -> None:
        """持有 session 直到 ``stop`` 或健康探测发现运行时断连（FR-3 收紧）。

        每 ``_health_check_interval`` 秒经 ``_stop_requested`` 问一次关停信号；未 stop 则 ping。
        ping 失败或超时 → 该 server 已不可达 → 注销其全部工具 + WARNING，随后返回
        （``_server_loop`` 在 ``finally`` 同 task 退出 transport context）。

        ping 与 session 同 task，沿用既有的「transport 同 task enter/exit」架构，
        避免 anyio cancel scope 跨 task 回归。``stop`` 优先：``__aexit__`` 触发时
        立即返回，不再 ping。
        """
        while not stop.is_set():
            if await self._stop_requested(stop):
                return  # stop 已 set（__aexit__ 触发）→ 立即退出，不再 ping
            try:
                await ping(session, self._health_check_interval)
            except Exception as exc:  # noqa: BLE001 - 任意 ping 失败/超时 = 断连
                logger.warning("MCP server '%s' 运行时断连（ping 失败），已注销其工具：%s", name, exc)
                self._unregister_server(name)
                return
