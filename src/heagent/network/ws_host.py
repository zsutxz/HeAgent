"""WS server 宿主（Epic 56 D1）：所有 WS 能力的唯一宿主——独立 ASGI app、独立配置、独立监听器。

与 HTTP server（``http_server.py``）**完全分离**：本 app 零 HTTP 路由（控制台页 / 静态资源 /
REST / 健康检查一律 404），HTTP app 亦不再挂任何 WS 路由。两条既有 WS 端点（run 订阅
``/api/runs/{run_id}/ws`` 与 CLI 旁路 ``/api/cli/ws``）自 HTTP app 迁入：路径不变、端口迁移
（8766 → 9001，唯一 breaking change）。端点逻辑复用 ``ws_server.py`` 不重写，本模块只负责
装配、监听器生命周期与 uvicorn WS 参数。

9001 没有健康端点可打，就绪判据改为**真实 TCP 连通**（D1 接缝事实：共享的只有注入的进程内
状态 ``HttpRunService`` / ``CliEventHub`` 与 ``network/`` 同层协议模型）。本机模式语义
（Origin 防线、无认证）与 ``exposure`` 告警逐字沿用；认证与 TLS 是 56-2 的范围。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from heagent.network.http_server import _require_module
from heagent.network.origin import (
    allowed_hosts,
    allowed_ports,
    probe_host,
    request_origin_violation,
)
from heagent.network.ws_protocol import (
    WS_MAX_FRAME_BYTES,
    WS_PING_INTERVAL_SECONDS,
    WS_PING_TIMEOUT_SECONDS,
)
from heagent.pub.safe_logging import safe_log

if TYPE_CHECKING:
    from starlette.types import ASGIApp


logger = logging.getLogger(__name__)

# 两条 WS 路径（公开常量：入口层公告与测试共用同一字面量，别处各写一份迟早漂移）。
RUNS_WS_PATH = "/api/runs/{run_id}/ws"
CLI_WS_PATH = "/api/cli/ws"

# 就绪探测与关闭排空的预算（秒）。探测是进程内回环 TCP 连接，正常毫秒级返回。
_PROBE_TIMEOUT = 5.0
_SHUTDOWN_GRACE_MARGIN = 1.0


def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """记一条日志，绝不让观测故障影响协议行为（网络传输层的既有立场）。"""
    safe_log(logger, level, message, *args, exc_info=exc_info)


class WsStartupError(RuntimeError):
    """WS server 未能绑定或未通过就绪探测。"""


class WsServerConfig(BaseModel):
    """单个 WS server 实例的有界配置（默认值与 ``WS_*`` 设置一致，Epic 56 D1）。

    ``port=0`` 允许（操作系统分配随机端口，仅程序化/测试用法）——CLI 与设置层限定 1..65535。
    超时禁 ``inf``/``nan``：``Inf`` 会让「有界关闭」静默变成无界等待（同 ``HttpServerConfig`` 口径）。
    """

    model_config = ConfigDict(frozen=True)

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=9001, ge=0, le=65535)
    # WS 连接额度（迁移自 HttpServerConfig.ws_max_connections）：既是每个 run 的订阅额度
    # （run 端点经 max_connections 参数注入），也是 CLI 旁路 hub 的连接总额。
    ws_max_connections: int = Field(default=16, ge=1)
    shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)


def build_ws_app(
    config: WsServerConfig,
    *,
    run_service: Any | None = None,
    cli_hub: Any | None = None,
) -> ASGIApp:
    """构造 WS server 的 ASGI 应用：只挂两条 WebSocketRoute，零 HTTP 路由（D1/D2）。

    ``run_service`` / ``cli_hub`` 是注入的进程内状态（D1 接缝事实）：为 None 时对应端点
    不注册（升级直接被 Starlette 拒掉）。同源防线经 ``origin_violation`` 回调注入端点——两条
    端点在 accept 前执行校验（http_server 时代的同一口径）；访问日志由端点自身的结构化
    ``ws_open``/``ws_close`` 事件承担，无需 ASGI 中间件。
    """
    applications = _require_module("starlette.applications")
    routing = _require_module("starlette.routing")

    def _origin_violation(scope: Any) -> str | None:
        return request_origin_violation(
            scope,
            hosts=allowed_hosts(config),
            ports=allowed_ports(config),
        )

    routes: list[Any] = []
    if run_service is not None:
        from heagent.network.ws_server import build_ws_endpoint

        routes.append(
            routing.WebSocketRoute(
                RUNS_WS_PATH,
                endpoint=build_ws_endpoint(
                    run_service,
                    origin_violation=_origin_violation,
                    max_connections=config.ws_max_connections,
                ),
            )
        )
    if cli_hub is not None:
        from heagent.network.ws_server import build_cli_ws_endpoint

        routes.append(
            routing.WebSocketRoute(
                CLI_WS_PATH,
                endpoint=build_cli_ws_endpoint(cli_hub, origin_violation=_origin_violation),
            )
        )
    # Starlette() 无类型标注，直返会触发 no-any-return；经类型化局部变量收敛。
    app: ASGIApp = applications.Starlette(routes=routes)
    return app


class WsServer:
    """一个 WS listener 的所有者：绑定、服务、有界关闭（三件套口径对齐 HttpServer）。"""

    def __init__(
        self,
        config: WsServerConfig,
        *,
        run_service: Any | None = None,
        cli_hub: Any | None = None,
    ) -> None:
        self.config = config
        self.run_service = run_service
        self.cli_hub = cli_hub
        self._app: ASGIApp | None = None
        self._server: Any = None
        # 生命周期锁 + 布尔标记：close() 等同一次收尾完成（HttpServer 既有口径）。
        self._lifecycle_lock = asyncio.Lock()
        self._closed = False
        self._ws_unavailable_logged = False

    @property
    def app(self) -> ASGIApp:
        """ASGI 应用（延迟构造一次；测试可用 ASGI transport 直接打，无需真实 listener）。"""
        if self._app is None:
            self._app = build_ws_app(
                self.config,
                run_service=self.run_service,
                cli_hub=self.cli_hub,
            )
        return self._app

    @property
    def port(self) -> int:
        """实际监听端口：port=0（随机端口）时只有绑定后才能读出来。"""
        for listener in getattr(self._server, "servers", None) or ():
            for sock in getattr(listener, "sockets", None) or ():
                with contextlib.suppress(OSError):
                    return int(sock.getsockname()[1])
        return self.config.port

    @property
    def address(self) -> str:
        """人类可读的监听地址（stderr 公告与诊断用）。"""
        return f"{self.config.host}:{self.port}"

    async def start(self) -> None:
        """绑定并确认 listener 真的可连，否则抛 WsStartupError。

        就绪判据是真实 TCP 连通（本 server 无 HTTP 健康端点可打，D1 接缝事实）。
        Uvicorn 绑定失败走 sys.exit 而非 OSError（同 HttpServer.start 的注释），因此
        同时接住 SystemExit 与 OSError 并统一转成可诊断错误。
        """
        if self._server is not None:
            return
        uvicorn = _require_module("uvicorn")
        self._closed = False
        server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=self.config.host,
                port=self.config.port,
                lifespan="on",
                # 与 HttpServer 同口径：不动 dictConfig / 不要 access 行 / 不带 server 头 / 不信 forwarded-*。
                log_config=None,
                access_log=False,
                server_header=False,
                proxy_headers=False,
                # WS 限额不经 limit_concurrency（Epic 54 口径）：额度在 ASGI 层原子检查+登记。
                ws_max_size=WS_MAX_FRAME_BYTES,
                ws_ping_interval=WS_PING_INTERVAL_SECONDS,
                ws_ping_timeout=WS_PING_TIMEOUT_SECONDS,
                timeout_graceful_shutdown=max(1, math.ceil(self.config.shutdown_timeout)),
            )
        )
        try:
            if not server.config.loaded:
                server.config.load()
            server.lifespan = server.config.lifespan_class(server.config)
            await server.startup()
        except SystemExit as exc:
            raise WsStartupError(f"WS server could not bind {self.address}: address unavailable") from exc
        except OSError as exc:
            raise WsStartupError(f"WS server could not bind {self.address}: {exc}") from exc
        self._server = server
        self._log_ws_unavailable_once(server)
        _safe_log(logging.INFO, "ws event=started address=%s", self.address)
        from heagent.network.exposure import exposure_warning

        warning = exposure_warning(self.config.host)
        if warning is not None:
            _safe_log(logging.WARNING, "ws event=exposed host=%s %s", self.config.host, warning)
        if not await self._probe_ready():
            # 绑定成功但 listener 不可连 ⇒ 回滚，绝不对外宣称「已启动」。
            self._server = None
            await self._stop_listener(server)
            raise WsStartupError(f"WS server started but {self.address} is not servable")
        if self.cli_hub is not None:
            # close() 置上的「停止接收」标记不可逆：重新 start() 后必须重开，否则新连接一律收
            # shutting_down——AD-5 禁止的「看着在运行、其实不可用」（同 HttpServer.start 口径）。
            self.cli_hub.reopen()

    async def serve_forever(self) -> None:
        """阻塞式服务循环；Uvicorn 主循环退出（should_exit）或异常时返回/抛出。"""
        server = self._server
        if server is None:
            raise RuntimeError("WS server is not started")
        await server.main_loop()

    async def close(self) -> None:
        """停止接收、关闭既有 WS 连接与 CLI 旁路、停 listener；全程有界、幂等。

        只做 WS 侧的收尾（D1 拆分）：在途运行的排空（service.close()）归 HTTP server 的
        close() 所有——编排顺序由入口层保证 HTTP 先、WS 后，等运行到终态后才关残余连接。
        单独调用本方法（无 HTTP server 的测试/装配形态）也安全：close_websockets 只注销
        登记并关连接，不取消任何运行（断线不取消运行，既有立场）。
        """
        async with self._lifecycle_lock:
            if self._closed:
                return
            if self.run_service is not None:
                await self.run_service.close_websockets()
            if self.cli_hub is not None:
                # 先置「停止接收」（新连接立刻收 shutting_down），再关既有连接。
                self.cli_hub.close()
                await self.cli_hub.close_websockets(timeout=self.config.shutdown_timeout)
            server, self._server = self._server, None
            if server is None:
                self._closed = True
                return
            server.should_exit = True
            await self._stop_listener(server)
            self._closed = True

    async def _stop_listener(self, server: Any) -> None:
        budget = self.config.shutdown_timeout + _SHUTDOWN_GRACE_MARGIN
        try:
            await asyncio.wait_for(server.shutdown(), timeout=budget)
        except TimeoutError:
            _safe_log(logging.WARNING, "ws event=shutdown_timeout phase=listener")
            server.force_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.shutdown(), timeout=budget)
        except asyncio.CancelledError:
            raise
        except Exception:
            _safe_log(logging.WARNING, "ws event=shutdown_failed", exc_info=True)

    async def _probe_ready(self) -> bool:
        """用真实 TCP 连接验证 listener 可连（本 server 无 HTTP 健康端点，D1 接缝事实）。"""
        host = probe_host(self.config.host)
        port = self.port
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=_PROBE_TIMEOUT)
        except (OSError, TimeoutError) as exc:
            _safe_log(logging.WARNING, "ws event=probe_failed phase=connect error=%r", exc)
            return False
        writer.close()
        return True

    def _log_ws_unavailable_once(self, server: Any) -> None:
        """缺 websockets 时给安装诊断（非致命：HTTP 不受影响，见 spec I/O 矩阵）。"""
        ws_protocol_class = getattr(server.config, "ws_protocol_class", None)
        if ws_protocol_class is None and not self._ws_unavailable_logged:
            self._ws_unavailable_logged = True
            _safe_log(
                logging.WARNING,
                "ws event=ws_unavailable install_hint=%s",
                "pip install 'heagent[http]' (WebSocket support requires websockets)",
            )


__all__ = [
    "CLI_WS_PATH",
    "RUNS_WS_PATH",
    "WsServer",
    "WsServerConfig",
    "WsStartupError",
    "build_ws_app",
]
