"""WS server 宿主（Epic 56 D1）：所有 WS 能力的唯一宿主——独立 ASGI app、独立配置、独立监听器。

与 HTTP server（``http_server.py``）**完全分离**：本 app 零 HTTP 路由（控制台页 / 静态资源 /
REST / 健康检查一律 404），HTTP app 亦不再挂任何 WS 路由。三条 WS 端点共用这一个 listener：
run 订阅 ``/api/runs/{run_id}/ws`` 与 CLI 旁路 ``/api/cli/ws`` 自 HTTP app 迁入（路径不变、
端口迁移 8766 → 9001，唯一 breaking change），提交 run 的集合级端点 ``/api/runs/ws`` 是本周期
新增（Epic 56 D2）。端点逻辑复用 ``ws_server.py`` 不重写，本模块只负责装配、监听器生命周期与
uvicorn WS 参数。

9001 没有健康端点可打，就绪判据改为**真实 TCP 连通**（D1 接缝事实：共享的只有注入的进程内
状态 ``HttpRunService`` / ``CliEventHub`` 与 ``network/`` 同层协议模型）。监听模式按绑定地址切
（D5）：回环 = 本地模式（Origin 防线、无认证，Epic 54/55 语义逐字保持）；非回环 = 对外模式
（Bearer token 强制、token 缺失拒绝启动、Origin 不适用），TLS 可选（cert/key 配齐即 wss）。
认证的纯逻辑面在 ``ws_auth.py``，本模块只负责装配与生命周期。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from heagent.network.exposure import is_loopback_host
from heagent.network.http_server import _require_module
from heagent.network.origin import (
    allowed_hosts,
    allowed_ports,
    probe_host,
    request_origin_violation,
)
from heagent.network.ws_auth import AuthThrottle, make_authorizer
from heagent.network.ws_protocol import (
    WS_MAX_FRAME_BYTES,
    WS_PING_INTERVAL_SECONDS,
    WS_PING_TIMEOUT_SECONDS,
)
from heagent.pub.safe_logging import safe_log

if TYPE_CHECKING:
    from starlette.types import ASGIApp


logger = logging.getLogger(__name__)

# 三条 WS 路径（公开常量：入口层公告与测试共用同一字面量，别处各写一份迟早漂移）。
RUNS_WS_PATH = "/api/runs/{run_id}/ws"
RUNS_SUBMIT_PATH = "/api/runs/ws"
CLI_WS_PATH = "/api/cli/ws"

# 就绪探测与关闭排空的预算（秒）。探测是进程内回环 TCP 连接，正常毫秒级返回。
_PROBE_TIMEOUT = 5.0
_SHUTDOWN_GRACE_MARGIN = 1.0


def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """记一条日志，绝不让观测故障影响协议行为（网络传输层的既有立场）。"""
    safe_log(logger, level, message, *args, exc_info=exc_info)


class WsStartupError(RuntimeError):
    """WS server 未能绑定或未通过就绪探测。"""


class WsConfigError(RuntimeError):
    """WS 配置不满足启动前提（对外模式缺 token / TLS 半配）。

    与 :class:`WsStartupError` 分开：一个是「配置不成立，压根不该尝试绑定」，一个是「绑定/探测
    失败」。入口层对前者给「怎么改配置」，对后者给「端口/依赖」诊断——混成一个异常会把两种修复
    路径混成一句无用的报错。
    """


class WsServerConfig(BaseModel):
    """单个 WS server 实例的有界配置（默认值与 ``WS_*`` 设置一致，Epic 56 D1）。

    ``port=0`` 允许（操作系统分配随机端口，仅程序化/测试用法）——CLI 与设置层限定 1..65535。
    超时禁 ``inf``/``nan``：``Inf`` 会让「有界关闭」静默变成无界等待（同 ``HttpServerConfig`` 口径）。

    **监听模式由绑定地址决定**（D5）：回环 = 本地模式（Origin/Host 防线，无认证）；
    非回环 = 对外模式（``auth_token`` 必填，缺失即 ``ValidationError``——fail-closed，绝不降级成
    「无认证对外」）。``auth_token`` 用 :class:`~pydantic.SecretStr` 承载：repr / 序列化一律掩码。

    TLS（D4）可选：``tls_cert_file`` 与 ``tls_key_file`` **要么都给要么都不给**（配齐即 wss）。
    """

    model_config = ConfigDict(frozen=True)

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=9001, ge=0, le=65535)
    # WS 连接额度（迁移自 HttpServerConfig.ws_max_connections）：既是每个 run 的订阅额度
    # （run 端点经 max_connections 参数注入），也是 CLI 旁路 hub 的连接总额。
    ws_max_connections: int = Field(default=16, ge=1)
    shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    # 对外模式的静态 token（D3）：真源是用户级 setting.md，**不**来自项目 .env / 系统环境。
    # 本地模式下即使配置了也不启用认证（D5：单监听器按绑定地址切模式）。
    auth_token: SecretStr | None = None
    # TLS 证书 / 私钥路径（PEM）；二者同时给出才启用 wss。
    tls_cert_file: str | None = None
    tls_key_file: str | None = None
    # **只读旁观**（Epic 56 期二 P2-A3）：True 时这条 listener 不注册提交端点（`/api/runs/ws`），
    # 已订阅连接上的 `cancel` 回 `invalid_request`（不断连）——只能看，不能下命令。
    # 与 listener 模式正交：本地/对外都可设，但入口层只为对外 listener 暴露配置键
    # （`WS_EXTERNAL_READONLY`）；本地 listener 的只读需求目前没有产品场景。
    readonly: bool = False

    @property
    def mode(self) -> str:
        """``"local"``（回环绑定）或 ``"external"``（非回环绑定，认证强制，D5）。"""
        return "local" if is_loopback_host(self.host) else "external"

    @property
    def requires_auth(self) -> bool:
        """是否需要 Bearer 认证（= 对外模式）。"""
        return self.mode == "external"

    @property
    def auth_secret(self) -> str:
        """展开后的 token 文本（**只**给比较路径用：调用方不得记录或回显它）。"""
        if self.auth_token is None:
            return ""
        return self.auth_token.get_secret_value().strip()

    @property
    def tls_enabled(self) -> bool:
        """是否走 wss（cert + key 均已配置）。"""
        return bool(self.tls_cert_file and self.tls_key_file)

    @model_validator(mode="after")
    def _validate_external_mode(self) -> WsServerConfig:
        """对外模式缺 token 直接拒绝构造（D5 fail-closed）；TLS 半配同样拒绝（D4）。"""
        if self.requires_auth and not self.auth_secret:
            raise ValueError(
                "binding the WS listener to a non-loopback host requires WS_AUTH_TOKEN in "
                "~/.heagent/setting.md (external mode is fail-closed; use a loopback address for local mode)"
            )
        if bool(self.tls_cert_file) != bool(self.tls_key_file):
            raise ValueError("WS TLS requires both WS_TLS_CERT_FILE and WS_TLS_KEY_FILE")
        return self


def build_ws_app(
    config: WsServerConfig,
    *,
    run_service: Any | None = None,
    cli_hub: Any | None = None,
) -> ASGIApp:
    """构造 WS server 的 ASGI 应用：只挂 WebSocketRoute，零 HTTP 路由（D1/D2/D9）。

    ``run_service`` / ``cli_hub`` 是注入的进程内状态（D1 接缝事实）：为 None 时对应端点
    不注册（升级直接被 Starlette 拒掉）。**端点可见性由 listener 身份决定**（期二 D9）：
    `mode == "local"` 才注册 CLI 旁路，对外 listener 恒不注册（终端内容不外溢）；提交与订阅
    两个端点两条 listener 都注册。同源防线经 ``origin_violation`` 回调注入端点——两条
    端点在 accept 前执行校验（http_server 时代的同一口径）；访问日志由端点自身的结构化
    ``ws_open``/``ws_close`` 事件承担，无需 ASGI 中间件。

    对外模式（D5）两处行为切换：① 同源/Host 防线**不适用**（客户端用任意主机名连本 listener，
    Host 白名单会把它全拒掉；防线地位由 token 认证取代）；② 认证门注入两个端点，在 accept 之前
    执行（失败 close(1008)）。限速状态挂在 app 上（一个 app = 一个 listener = 一份限速窗口）。
    """
    applications = _require_module("starlette.applications")
    routing = _require_module("starlette.routing")

    external = config.requires_auth
    authorize = make_authorizer(config.auth_secret, AuthThrottle()) if external else None

    def _origin_violation(scope: Any) -> str | None:
        if external:
            # 对外模式：Host/Origin 不再是防线（连接来自任意网段），认证是唯一防线。
            return None
        return request_origin_violation(
            scope,
            hosts=allowed_hosts(config),
            ports=allowed_ports(config),
        )

    routes: list[Any] = []
    if run_service is not None:
        from heagent.network.ws_server import build_runs_collection_endpoint, build_ws_endpoint

        if not config.readonly:
            # 集合级端点先注册（`/api/runs/ws` 与 `/api/runs/{run_id}/ws` 段数不同，不会互相遮蔽；
            # 顺序只是让「提交通道」在路由表里排在订阅通道之前，便于阅读）。
            # 只读 listener 上**不注册**它：提交能力不给，连「试一下拿 run_conflict」的机会都没有。
            routes.append(
                routing.WebSocketRoute(
                    RUNS_SUBMIT_PATH,
                    endpoint=build_runs_collection_endpoint(
                        run_service,
                        origin_violation=_origin_violation,
                        max_connections=config.ws_max_connections,
                        authorize=authorize,
                    ),
                )
            )
        routes.append(
            routing.WebSocketRoute(
                RUNS_WS_PATH,
                endpoint=build_ws_endpoint(
                    run_service,
                    origin_violation=_origin_violation,
                    max_connections=config.ws_max_connections,
                    authorize=authorize,
                    readonly=config.readonly,
                ),
            )
        )
    if cli_hub is not None and config.mode == "local":
        # D9：终端观众席**只**挂本地 listener。装配层（`build_ws_servers`）本来就不会把 hub
        # 传给对外 listener，这里再判一次 mode 是 defense-in-depth——「某个调用方直接构造了
        # 对外 WsServer(cli_hub=...)」也不该把终端事件流投递到网络。
        from heagent.network.ws_server import build_cli_ws_endpoint

        routes.append(
            routing.WebSocketRoute(
                CLI_WS_PATH,
                endpoint=build_cli_ws_endpoint(
                    cli_hub,
                    origin_violation=_origin_violation,
                    authorize=authorize,
                ),
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
                # TLS（D4）：cert/key 配齐即 wss；半配在 WsServerConfig 构造期已 fail-loud。
                ssl_certfile=self.config.tls_cert_file,
                ssl_keyfile=self.config.tls_key_file,
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
        _safe_log(
            logging.INFO,
            "ws event=started address=%s listener=%s tls=%s",
            self.address,
            self.config.mode,
            "wss" if self.config.tls_enabled else "ws",
        )
        if self.config.requires_auth and not self.config.tls_enabled:
            # D4：对外明文跑必须日志可见（与 exposure 告警两条独立信息：一条说「谁能连」，一条说「没加密」）。
            _safe_log(
                logging.WARNING,
                "ws event=plaintext_external address=%s listener=external transport=ws "
                "hint=configure WS_TLS_CERT_FILE and WS_TLS_KEY_FILE to serve wss",
                self.address,
            )
        if not self.config.requires_auth and self.config.auth_secret:
            # 本地模式刻意不启用认证（D5）：token 配了也不生效，说清楚以免留下虚假安全感。
            _safe_log(
                logging.WARNING,
                "ws event=auth_token_ignored reason=loopback_bind hint=auth is enforced only for non-loopback binds",
            )
        from heagent.network.exposure import exposure_warning

        if self.config.requires_auth:
            # 对外模式：exposure 文案「no authentication」已不成立（认证强制），单列一条准确的暴露记录。
            _safe_log(
                logging.WARNING,
                "ws event=exposed host=%s listener=external auth=token tls=%s",
                self.config.host,
                "wss" if self.config.tls_enabled else "ws",
            )
        else:
            warning = exposure_warning(self.config.host)
            if warning is not None:
                _safe_log(logging.WARNING, "ws event=exposed host=%s listener=local %s", self.config.host, warning)
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
    "RUNS_SUBMIT_PATH",
    "RUNS_WS_PATH",
    "WsConfigError",
    "WsServer",
    "WsServerConfig",
    "WsStartupError",
    "build_ws_app",
]
