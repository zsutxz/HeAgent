"""HTTP listener 生命周期：绑定、就绪探测、有界关闭（Story 62.1 自 ``network/http_server.py`` 拆出）。

API 形状是 ``start`` / ``serve_forever`` / ``close`` 三件套（AD-5）：入口层的装配代码只依赖这三个方法。

``__all__`` 显式列出包内公开名：包级再导出（``__init__.py``）与 exception 快照
（``scripts/contract_snapshot.py``）都以「定义模块的 ``__all__``」为收录依据。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from typing import TYPE_CHECKING, Any

from heagent.network.exposure import exposure_warning

# 别名导入保住 monkeypatch 缝：缺依赖路径经 ``HttpServer.start`` 的 ``_require_module("uvicorn")``
# 先触发（在 ``self.app`` → ``build_http_app`` 之前），测试 patch
# ``heagent.network.http_server.listener._require_module``。
from heagent.network.optional_deps import require_module as _require_module
from heagent.network.origin import probe_host
from heagent.pub.safe_logging import safe_log

from .app import _HEALTH_PATH, build_http_app
from .config import HttpStartupError

if TYPE_CHECKING:
    from starlette.types import ASGIApp

    from heagent.network.http_console_protocol import ConsoleHandler

    from .config import HttpServerConfig
    from .service import HttpRunService

__all__ = ["HttpServer"]

logger = logging.getLogger("heagent.network.http_server")

# 就绪探测与关闭排空的预算（秒）。探测是进程内回环请求，正常在毫秒级返回。
_PROBE_TIMEOUT = 5.0
_SHUTDOWN_GRACE_MARGIN = 1.0

# Uvicorn 的 ``limit_concurrency`` 计的是**已建立的连接**，而 ``start()`` 的就绪探测自己也要占
# 一条（见 :meth:`HttpServer._probe_health`）。若把限额直接设为配置值，``HTTP_MAX_CONNECTIONS=1``
# 会让探测自己撞上限额（Uvicorn 直接回裸 503）→ 判为「未就绪」→ 入口永远起不来。预留一条。
_CONCURRENCY_PROBE_RESERVE = 1


class HttpServer:
    """一个 HTTP listener 的所有者：绑定、服务、有界关闭。

    API 形状是 ``start`` / ``serve_forever`` / ``close`` 三件套：入口层的装配代码只依赖这三个方法。
    """

    def __init__(
        self,
        config: HttpServerConfig,
        *,
        version: str,
        run_service: HttpRunService | None = None,
        console: ConsoleHandler | None = None,
    ) -> None:
        self.config = config
        self.version = version
        self.run_service = run_service
        self.console = console
        self._app: ASGIApp | None = None
        self._server: Any = None
        # 生命周期锁与「已关闭」标记：``close()`` 必须**等到**收尾真正完成才返回。只用一个布尔
        # 标记的话，并发/重复调用会拿到「已关闭」的假成功，而 listener 仍在接受并服务请求
        # （生命周期锁 + 布尔标记是本项目入口服务的既有形态）。
        self._lifecycle_lock = asyncio.Lock()
        self._closed = False

    @property
    def app(self) -> ASGIApp:
        """ASGI 应用（延迟构造一次；测试可用 ASGI transport 直接打，无需真实 listener）。"""
        if self._app is None:
            self._app = build_http_app(
                self.config,
                version=self.version,
                run_service=self.run_service,
                console=self.console,
            )
        return self._app

    @property
    def port(self) -> int:
        """实际监听端口：``port=0``（随机端口）时只有绑定后才能读出来。"""
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
        """绑定地址并确认 ``/api/health`` **真的可服务**，否则抛 :class:`HttpStartupError`。

        Uvicorn 在绑定失败时不是抛 ``OSError`` 而是 ``sys.exit(STARTUP_FAILURE)``（见其
        ``Server.startup`` 的 standard-case 分支），所以这里同时接住 ``SystemExit`` 与
        ``OSError``，并统一转成可诊断错误——**绝不能**让「端口被占用」变成进程静默退出或
        「看似在监听」的半启动状态。
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
                # log_config=None：**不**调用 dictConfig —— Uvicorn 默认配置会重写整个 logging
                # 配置并禁用既有 logger，把 HeAgent 的日志通道一起关掉。
                log_config=None,
                # access 日志由本模块的结构化日志取代：Uvicorn 的 access 行会带上完整路径与
                # 查询串，日志只应含不透明的 request/run id、状态与耗时。
                access_log=False,
                server_header=False,
                # 绝不信任 forwarded-* 头：同源判定必须基于真实 listener 地址。
                proxy_headers=False,
                limit_concurrency=self.config.max_connections + _CONCURRENCY_PROBE_RESERVE,
                # 关闭时连接排空的硬上界（Uvicorn 默认 None = 无限等待）。
                timeout_graceful_shutdown=max(1, math.ceil(self.config.shutdown_timeout)),
            )
        )
        try:
            # uvicorn 的 ``Server.startup()`` 假定 ``lifespan`` 已由 ``Server._serve()`` 建好，而我们
            # 刻意绕过 ``serve()``（它会把绑定错误转成 ``sys.exit``，还会抢进程信号——信号归 CLI
            # 所有），因此照它的顺序把这两步补齐。``Config.load()`` 对「传进来的 ASGI
            # 对象」只是打标记，不会重新 import。
            if not server.config.loaded:
                server.config.load()
            server.lifespan = server.config.lifespan_class(server.config)
            await server.startup()
        except SystemExit as exc:
            raise HttpStartupError(f"HTTP server could not bind {self.address}: address unavailable") from exc
        except OSError as exc:
            raise HttpStartupError(f"HTTP server could not bind {self.address}: {exc}") from exc
        self._server = server
        safe_log(logger, logging.INFO, "http event=started address=%s", self.address)
        warning = exposure_warning(self.config.host)
        if warning is not None:
            safe_log(logger, logging.WARNING, "http event=exposed host=%s %s", self.config.host, warning)
        if not await self._probe_health():
            # 绑定成功但应用不可服务 ⇒ 回滚，绝不对外宣称「已启动」。
            self._server = None
            await self._stop_listener(server)
            raise HttpStartupError(f"HTTP server started but {_HEALTH_PATH} is not servable")
        if self.run_service is not None:
            # 重新武装运行入口：``close()`` 会把「停止接收」标记置上且不可逆，于是
            # ``close()`` → ``start()`` 之后健康检查照常 200，而每次 ``POST /api/runs`` 都被
            # 409 ``run_conflict``（`server is shutting down`）拒绝——避免「看起来正常但不可用」。
            self.run_service.reopen()

    async def serve_forever(self) -> None:
        """阻塞式服务循环；Uvicorn 主循环退出（``should_exit``）或异常时返回/抛出。"""
        server = self._server
        if server is None:
            raise RuntimeError("HTTP server is not started")
        await server.main_loop()

    async def close(self) -> None:
        """停止接收新请求、终结在途运行、关闭 listener，全程有界；幂等。

        关闭顺序按 AD-5：**停止接收（service 拒绝新 run）→ 使在途运行进入终态并发出终态事件 →
        关闭订阅 → 关闭 listener → 有界等待**。Uvicorn 的 ``shutdown()`` 负责最后两步（关闭监听、
        请求既有连接收尾，受 ``timeout_graceful_shutdown`` 约束），本方法另加一层 ``wait_for`` 兜底，
        保证即使框架内部出现无界等待也不会把 CLI 退出卡死。

        幂等指「重复/并发调用都等到**同一次**收尾完成」：后到者持锁排队，不会在本方法仍在等待
        在途运行时提前返回一个「已关闭」的假成功。收尾中途被取消（如 Ctrl+C 二次打断）时不置
        ``_closed``，让下一次调用可以接着收尾。
        """
        async with self._lifecycle_lock:
            if self._closed:
                return
            service = self.run_service
            if service is not None:
                # WS 连接的收尾（close_websockets / cli_hub）归 WS server 所有；
                # 本方法只排空运行到终态并停 HTTP listener（SSE 订阅随之终结）。
                await service.close()
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
            safe_log(logger, logging.WARNING, "http event=shutdown_timeout phase=listener")
            server.force_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.shutdown(), timeout=budget)
        except asyncio.CancelledError:
            raise
        except Exception:
            safe_log(logger, logging.WARNING, "http event=shutdown_failed", exc_info=True)

    async def _probe_health(self) -> bool:
        """用**真实 TCP 连接**打通一次 ``/api/health``（AD-5 的就绪判据）。

        刻意用标准库而不是 HTTP 客户端：``network/`` 的依赖面里没有 httpx，而「listener 是否
        真的能服务」这件事用一次手写 `GET` 就能验证——返回 200 即通过，其余（连接失败、超时、
        5xx、畸形响应行）一律视为未就绪。
        """
        host = probe_host(self.config.host)
        port = self.port
        started_at = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=_PROBE_TIMEOUT)
        except (OSError, TimeoutError) as exc:
            safe_log(logger, logging.WARNING, "http event=probe_failed phase=connect error=%r", exc)
            return False
        try:
            # IPv6 字面量的 authority 必须带方括号：``::1:8766`` 会被拆成 host ``::1`` +
            # port 8766（恰好侥幸通过），而 ``[::1]:8766`` 才是浏览器与校验两侧都认的写法。
            authority = f"[{host}]" if ":" in host else host
            request = (f"GET {_HEALTH_PATH} HTTP/1.1\r\nhost: {authority}:{port}\r\nconnection: close\r\n\r\n").encode()
            writer.write(request)
            await writer.drain()
            status_line = await asyncio.wait_for(reader.readline(), timeout=_PROBE_TIMEOUT)
        except (OSError, TimeoutError) as exc:
            safe_log(logger, logging.WARNING, "http event=probe_failed phase=request error=%r", exc)
            return False
        finally:
            writer.close()
            # 关连接**必须有界**：对端只收不关（或黑洞）时 `wait_closed()`
            # 会一直等下去，把就绪门禁拖成无界等待；超时即放弃收尾，按已拿到的状态行判定。
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), timeout=_PROBE_TIMEOUT)
        ok = b" 200 " in status_line
        if not ok:
            safe_log(logger, logging.WARNING, "http event=probe_failed phase=status status=%r", status_line[:32])
        else:
            safe_log(
                logger,
                logging.DEBUG,
                "http event=probe_ok elapsed_ms=%d",
                int((time.perf_counter() - started_at) * 1000),
            )
        return ok
