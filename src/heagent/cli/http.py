"""``heagent http-server`` 子命令与 HTTP 服务装配（入口层组合根，Epic 49）。

本模块属**入口层**（``heagent/cli/`` 包内，与 ``console`` / ``init`` / ``goal`` 及顶层
``wiring`` 同级）：
它读设置、构造可选 HTTP 栈下的 :class:`~heagent.network.http_server.HttpServer`、注册 Click
命令；``network/`` 侧不反向依赖本模块（``tests/test_architecture_contracts.py`` 有可执行断言）。

Story 49-1 的职责只有「把服务拉起来、打得开网页、失败要显式」：

- 默认绑 ``127.0.0.1:8766``，并把**实际**监听地址打到 stderr；
- 非回环绑定复用 :mod:`heagent.network.exposure` 的判定与文案，启动前先告警；
- 缺 ``heagent[http]`` 可选依赖、端口被占用、健康探测失败都在命令层转成可读错误
  （``ClickException``），既不吐 traceback，也绝不打印「已监听」。

**默认 CLI 自启动（Story 49-2）、运行 API 与 SSE（49-3）、取消与限额（49-4）**都建立在本模块的
装配方式上；为了让那些 Story 不必重写这段编排，这里已经确定了两条边界：HTTP 服务与 CLI 共用
同一个 asyncio 生命周期（本模块只提供 ``_serve_http`` 这一种「跑到底」的形态），以及 CLI 覆盖
只作用于本次实例（``build_server_config`` 不写回 ``Settings`` 单例）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import re
from pathlib import Path
from typing import Any

import click
from pydantic import SecretStr, ValidationError

from heagent.cli.display import _current_version, echo_sandbox_hint, echo_web_entry_overrides
from heagent.cli.http_console import HttpAgentHandler, HttpProjectConsole
from heagent.cli.wiring import _build_provider
from heagent.config import WS_AUTH_TOKEN_KEY, Settings, get_settings
from heagent.network.cli_event_hub import CliEventHub
from heagent.network.exposure import exposure_warning, is_loopback_host
from heagent.network.http_server import (
    HttpDependencyError,
    HttpRunService,
    HttpServer,
    HttpServerConfig,
    HttpStartupError,
)
from heagent.network.notification_hub import NotificationHub
from heagent.network.ws_host import CLI_WS_PATH, WsConfigError, WsServer, WsServerConfig, WsStartupError
from heagent.pub.safe_logging import safe_log
from heagent.pub.workspace import WorkspacePaths

logger = logging.getLogger(__name__)


def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """记一条日志，**绝不让观测故障影响生命周期行为**（与网络传输层同一立场）。"""
    safe_log(logger, level, message, *args, exc_info=exc_info)


def _reject_non_finite(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    """拒绝 ``NaN`` / ``Inf`` 超时值（``click.FloatRange`` 本身会放行它们）。

    不拦的后果是显性的：``Inf`` 让「有界关闭」静默变成无界等待，``NaN`` 绕过范围比较后
    直到 Pydantic 才以 traceback 炸掉（与其它非法值的 usage error 语义不一致）。
    """
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("must be a finite number", ctx=ctx, param=param)
    return value


def _resolve_listener_port(settings: Settings, host: str, requested: int | None, *, default_port: int) -> int:
    """解析 listener 端口：显式指定是契约（冲突 fail-loud）；未指定时从 ``default_port`` 起顺延（HTTP/WS 共用）。"""
    target = default_port if requested is None else requested
    if requested is not None or settings.http_port_auto_find_attempts <= 0:
        return target
    from heagent.cli.port_finder import find_available_port

    try:
        return find_available_port(target, host=host, max_attempts=settings.http_port_auto_find_attempts)
    except RuntimeError:
        # 所有尝试都失败，使用原端口（让后续绑定失败并报错）
        return target


def build_server_config(
    settings: Settings,
    *,
    host: str | None = None,
    port: int | None = None,
    max_connections: int | None = None,
    max_subscribers: int | None = None,
    max_inflight_runs: int | None = None,
    max_total_inflight: int | None = None,
    max_request_bytes: int | None = None,
    event_buffer_size: int | None = None,
    run_history_size: int | None = None,
    request_timeout: float | None = None,
    idle_timeout: float | None = None,
    shutdown_timeout: float | None = None,
) -> HttpServerConfig:
    """把 CLI 覆盖（``None`` = 未覆盖）合并到 ``Settings`` 的 HTTP 配置。

    两个不变量：

    - **不写回 Settings**：覆盖只作用于本次服务实例，设置单例保持 env / 文件默认值；
    - **范围规则唯一**：CLI 侧先用 ``click`` 的 range 类型拦一道，最终仍由
      :class:`HttpServerConfig`（Pydantic）统一校验，避免 CLI 与 env 两套规则漂移。

    端口自动查找：当端口**不是调用方显式指定**（``port is None``）且被占用时，
    自动尝试后续端口（port+1, port+2...），默认 10 次（``http_port_auto_find_attempts``，
    2026-10-15 起默认开启）。显式 ``--port`` 是契约：冲突时保持原端口、交由绑定失败显性报错
    ——否则「启动失败」会静默变成「服务跑在另一个端口上」，脚本与状态行都无从知晓（NFR-10 无回归）。
    """
    target_host = settings.http_host if host is None else host

    return HttpServerConfig(
        host=target_host,
        port=_resolve_listener_port(settings, target_host, port, default_port=settings.http_port),
        max_connections=settings.http_max_connections if max_connections is None else max_connections,
        max_subscribers=settings.http_max_subscribers if max_subscribers is None else max_subscribers,
        max_inflight_runs=settings.http_max_inflight_runs if max_inflight_runs is None else max_inflight_runs,
        max_total_inflight=(settings.http_max_total_inflight if max_total_inflight is None else max_total_inflight),
        max_request_bytes=settings.http_max_request_bytes if max_request_bytes is None else max_request_bytes,
        event_buffer_size=settings.http_event_buffer_size if event_buffer_size is None else event_buffer_size,
        run_history_size=settings.http_run_history_size if run_history_size is None else run_history_size,
        request_timeout=settings.http_request_timeout if request_timeout is None else request_timeout,
        idle_timeout=settings.http_idle_timeout if idle_timeout is None else idle_timeout,
        tool_inflight_timeout=settings.http_tool_inflight_timeout,
        shutdown_timeout=settings.http_shutdown_timeout if shutdown_timeout is None else shutdown_timeout,
    )


def _ws_url(server: WsServer) -> str:
    """WS listener 的公告 URL（TLS 配齐即 ``wss``）。"""
    scheme = "wss" if server.config.tls_enabled else "ws"
    return f"{scheme}://{server.address}"


def _ws_access_note(config: WsServerConfig) -> str:
    """公告里的访问口径：本地模式无认证，对外模式「token required + 明文/wss」；只读另标。"""
    suffix = "; read-only" if config.readonly else ""
    if config.requires_auth:
        transport = "TLS" if config.tls_enabled else "PLAINTEXT"
        return f"(external mode; Bearer token required; {transport}{suffix})"
    return f"(run & CLI WebSocket entry; local only; no authentication{suffix})"


async def _serve_web(http_server: HttpServer | None, ws_servers: tuple[WsServer, ...]) -> None:
    """启动 HTTP + 1–2 个 WS listener 并运行到取消 / 关闭（Epic 56 D1 拆分、期二 D12 多 listener）。

    ``start()`` 在 try 之外：它失败时要么 listener 没建起来、要么内部已回滚，不需要再 close；
    一旦进入服务循环，任何退出路径都必须走 ``close()``，否则 Ctrl+C 会留下悬挂的 listener。
    任一 WS listener 起不来 ⇒ 回滚**已启动的全部**（含 HTTP），绝不留半启动状态。
    """
    if http_server is not None:
        await http_server.start()
    started: list[WsServer] = []
    try:
        for ws_server in ws_servers:
            await ws_server.start()
            started.append(ws_server)
    except BaseException:
        # 回滚：先关已起的 WS，再关 HTTP（此刻还没有 run 在跑，顺序只为与正常关停同构）。
        for ws_server in reversed(started):
            await ws_server.close()
        if http_server is not None:
            await http_server.close()
        raise
    if http_server is not None:
        click.echo(
            f"[http] listening on http://{http_server.address}  (open this URL in a browser; no authentication)",
            err=True,
        )
    for ws_server in ws_servers:
        click.echo(f"[ws] listening on {_ws_url(ws_server)}  {_ws_access_note(ws_server.config)}", err=True)
    http_serve = [] if http_server is None else [http_server.serve_forever()]
    try:
        await asyncio.gather(*http_serve, *(ws_server.serve_forever() for ws_server in ws_servers))
    finally:
        # D1 关停顺序：HTTP 先（排空运行到终态），WS 后（关残余订阅连接 + listener）。
        if http_server is not None:
            await http_server.close()
        await asyncio.gather(*(ws_server.close() for ws_server in ws_servers))


class EmbeddedHttpService:
    """默认 CLI **内嵌**网页入口的生命周期（同进程、同一 asyncio 生命周期）。

    Epic 56 D1 起入口 = **多 listener**：HTTP listener（8766，控制台 + REST/SSE）+ **1 或 2 个**
    WS listener（期一：9901；期二双监听：9901 本地 + 9002 对外）。名字保留 ``EmbeddedHttpService``：
    它仍是入口层那个「伴随 CLI 的网页服务」单元，只是自此拥有 N 条 listener、一个生命周期。

    - ``start()``：先 HTTP 后逐个 WS 绑定 + 就绪门禁（任一 WS 失败回滚已启动的全部）+ 后台 serve 任务 + stderr 公告；
    - ``close()``：幂等、全程有界，**HTTP 先**（排空运行到终态）**WS 后**（关订阅连接 + listener）；
    - ``failure``：任一 serve 循环**意外**结束时的首个异常。交互模式每轮检查它——任一 listener
      挂掉而 CLI 还在正常聊天，等于「页面/订阅打不开但看着一切正常」，正是 AD-5 要消除的假可用状态。
    """

    def __init__(
        self,
        http_server: HttpServer | None,
        ws_servers: WsServer | tuple[WsServer, ...],
        *,
        cli_hub: Any | None = None,
        notification_hub: Any | None = None,
    ) -> None:
        self._http = http_server
        # 单 listener（期一形态）与多 listener（期二双监听）同一入口：接受单个实例或元组，
        # 内部一律按元组处理（``servers[0]`` = 主 listener）。
        self._ws_servers: tuple[WsServer, ...] = (
            (ws_servers,) if isinstance(ws_servers, WsServer) else tuple(ws_servers)
        )
        # 双关（HTTP+WS 均禁用）= 休眠服务：交互模式显式全关时合法；`http-server` 命令在命令层 fail-fast。
        # CLI 旁路中枢（Epic 55，Epic 56 D7 起宿主 = WS listener）：``None`` = 未开启**或**
        # 因 listener 身份被跳过（D9：对外 listener 不提供终端观众席）。
        self._cli_hub = cli_hub
        # cron 结果通知中枢（Epic 58）：``None`` = CRON_PUSH_ENABLED=false（端点未注册）。它不是
        # listener 的私有状态——中枢由 `build_ws_servers` 建一份并挂到每个 listener，这里只是把它
        # 抬到「服务单元」这一层，供入口层构造的 cron notifier 发布。
        self._notification_hub = notification_hub
        self._tasks: list[asyncio.Task[None]] = []
        self._failure: BaseException | None = None
        self._closed = False

    @property
    def address(self) -> str:
        """HTTP listener 实际监听地址（stderr 公告与诊断用）；HTTP 禁用时无意义。"""
        if self._http is None:
            raise RuntimeError("HTTP listener is disabled (HTTP_ENABLED=false or --no-http)")
        return self._http.address

    @property
    def ws_servers(self) -> tuple[WsServer, ...]:
        """所有 WS listener（``[0]`` = 主 listener；双监听时 ``[1]`` = 对外 listener）。"""
        return self._ws_servers

    @property
    def ws_address(self) -> str:
        """**主** WS listener 实际监听地址（期一属性，语义不变）；WS 禁用时无意义。"""
        if not self._ws_servers:
            raise RuntimeError("WS listener is disabled (WS_ENABLED=false or --no-ws)")
        return self._ws_servers[0].address

    @property
    def ws_addresses(self) -> tuple[str, ...]:
        """全部 WS listener 的实际监听地址（双监听时含对外 listener）。"""
        return tuple(server.address for server in self._ws_servers)

    @property
    def cli_hub(self) -> Any | None:
        """CLI 旁路中枢（未开启时为 ``None``）；入口层据此把终端 run 的事件发出来。"""
        return self._cli_hub

    @property
    def notification_hub(self) -> Any | None:
        """cron 结果通知中枢（``CRON_PUSH_ENABLED=false`` 时为 ``None``）；入口层据此构造 notifier。"""
        return self._notification_hub

    @property
    def is_dormant(self) -> bool:
        """两条入口都没装配（休眠服务，零监听）。

        与「某一条被关」区分开：交互模式在休眠时显式提示一次，避免用户以为网页入口还在，
        而实际上本进程一个 listener 都没有。
        """
        return self._http is None and not self._ws_servers

    @property
    def failure(self) -> BaseException | None:
        """serve 循环意外结束时的首个异常；仍在服务或已被正常关闭时为 ``None``。"""
        return self._failure

    async def start(self) -> None:
        """启动 HTTP 与所有 WS listener 并进入后台服务循环；任一绑定 / 就绪失败时抛错且不留残留。"""
        if self._http is not None:
            await self._http.start()
        started: list[WsServer] = []
        try:
            # 任一 WS 起不来时回滚**已启动的全部**：半启动（HTTP 活着、某个 WS 缺席）是 AD-5 禁止的假可用。
            for ws_server in self._ws_servers:
                await ws_server.start()
                started.append(ws_server)
        except BaseException:
            for ws_server in reversed(started):
                await ws_server.close()
            if self._http is not None:
                await self._http.close()
            raise
        self._tasks = [
            *(
                [asyncio.create_task(self._http.serve_forever(), name="heagent-http-serve")]
                if self._http is not None
                else []
            ),
            *(
                asyncio.create_task(ws_server.serve_forever(), name=f"heagent-ws-serve-{index}")
                for index, ws_server in enumerate(self._ws_servers)
            ),
        ]
        for task in self._tasks:
            task.add_done_callback(self._on_serve_done)
        if self._http is not None:
            click.echo(
                f"[http] web UI: http://{self.address}  (local only; no authentication)",
                err=True,
            )
        for ws_server in self._ws_servers:
            click.echo(
                f"[ws] event stream: {_ws_url(ws_server)}  {_ws_access_note(ws_server.config)}",
                err=True,
            )
        if self._cli_hub is not None:
            # 开启即多暴露一条旁路通道：把地址打出来，别让用户「开了但不知道在哪」。
            # 旁路只挂在本地 listener 上（D9），公告因此必须指向**真正承载它**的那条。
            host_server = next(
                (server for server in self._ws_servers if server.cli_hub is not None),
                self._ws_servers[0],
            )
            scheme = "wss" if host_server.config.tls_enabled else "ws"
            click.echo(
                f"[ws] CLI event stream (read-only): {scheme}://{host_server.address}{CLI_WS_PATH}"
                f"  {_ws_access_note(host_server.config)}",
                err=True,
            )

    def _on_serve_done(self, task: asyncio.Task[None]) -> None:
        """serve 循环收尾回调：只有**意外**结束才记 ERROR 并暴露给所有者。"""
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        if self._closed:
            # 关闭期间 serve 循环因 listener 已关闭而报错属正常收尾，不该污染 `failure`。
            _safe_log(logging.WARNING, "%s ended during shutdown: %s", task.get_name(), error)
            return
        if self._failure is None:
            self._failure = error
        _safe_log(logging.ERROR, "%s stopped unexpectedly: %s", task.get_name(), error)

    async def close(self) -> None:
        """停止所有 listener 并回收 serve 任务（幂等、有界；HTTP 先 WS 后）。"""
        if self._closed:
            return
        self._closed = True
        # D1 关停顺序：HTTP 的 close() 排空在途运行到终态（SSE 随之终结），WS 的 close() 再关
        # 残余订阅连接与 listener——顺序颠倒会让订阅者错过终态事件。
        if self._http is not None:
            await self._http.close()
        await asyncio.gather(*(ws_server.close() for ws_server in self._ws_servers))
        tasks, self._tasks = self._tasks, []
        timeouts = [s.config.shutdown_timeout for s in self._ws_servers]
        if self._http is not None:
            timeouts.append(self._http.config.shutdown_timeout)
        budget = max(timeouts, default=5.0) + 1.0
        for task in tasks:
            if task is None or task is asyncio.current_task():
                continue
            try:
                await asyncio.wait_for(task, timeout=budget)
            except TimeoutError:
                _safe_log(logging.WARNING, "%s did not stop within %.1fs; cancelling", task.get_name(), budget)
                task.cancel()
                with contextlib.suppress(Exception):
                    await task
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 已在 done callback 记过 ERROR：此处既不重抛（会掩盖退出原因），也不静默（已记录）。
                _safe_log(logging.WARNING, "%s ended while closing: %s", task.get_name(), exc)

    async def __aenter__(self) -> EmbeddedHttpService:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()


def build_ws_server_config(
    settings: Settings,
    *,
    host: str | None = None,
    port: int | None = None,
    max_connections: int | None = None,
    shutdown_timeout: float | None = None,
) -> WsServerConfig:
    """把 CLI 覆盖（``None`` = 未覆盖）合并到 ``Settings`` 的 WS 配置（口径同 :func:`build_server_config`）。

    不写回 Settings；范围规则由 :class:`WsServerConfig`（Pydantic）统一校验。端口自动查找与
    HTTP listener 同一开关（``http_port_auto_find_attempts``）：两条 listener 独立顺延
    （HTTP 自 8766、WS 自 9901），实际端口以启动公告为准。

    **对外模式的三件接线**（Epic 56 D3/D4/D5）：

    - ``auth_token`` 来自 :attr:`Settings.user_ws_auth_token`（只读用户级 ``setting.md``；项目
      ``.env`` / 系统环境变量一律不参与）；
    - 非回环绑定缺 token ⇒ :class:`WsConfigError`（fail-closed，绝不降级成无认证对外）；
    - TLS cert/key 来自 ``WS_TLS_CERT_FILE`` / ``WS_TLS_KEY_FILE``，半配同样 fail-loud。
    """
    resolved_host = settings.ws_host if host is None else host
    token = settings.user_ws_auth_token
    try:
        return WsServerConfig(
            host=resolved_host,
            port=_resolve_listener_port(settings, resolved_host, port, default_port=settings.ws_port),
            ws_max_connections=settings.ws_max_connections if max_connections is None else max_connections,
            shutdown_timeout=settings.ws_shutdown_timeout if shutdown_timeout is None else shutdown_timeout,
            auth_token=SecretStr(token) if token else None,
            tls_cert_file=settings.ws_tls_cert_file,
            tls_key_file=settings.ws_tls_key_file,
        )
    except ValidationError as exc:
        raise WsConfigError(_first_validation_message(exc)) from exc


def _clean_path(value: str | None) -> str | None:
    """把可选路径配置归一化：空串 / 纯空白视为未配置（``.env`` 里写 ``KEY=`` 的常见形态）。"""
    if value is None:
        return None
    text = value.strip()
    return text or None


def _external_tls_files(settings: Settings) -> tuple[str | None, str | None]:
    """对外 listener 的 TLS 文件对（Epic 56 D10）：**成对**独配，否则整对继承主 listener。

    规则刻意只有两种合法形态：① 对外 cert/key 都不设 ⇒ 整对继承 ``WS_TLS_*``（期一单对外部署
    的配置照旧生效）；② 都设 ⇒ 用它们。只设一半直接 fail-loud——混搭会让 A 的证书配 B 的私钥，
    握手期才报一个难懂的错误。
    """
    cert = _clean_path(settings.ws_external_tls_cert_file)
    key = _clean_path(settings.ws_external_tls_key_file)
    if cert or key:
        if not (cert and key):
            raise WsConfigError(
                "WS_EXTERNAL_TLS_CERT_FILE and WS_EXTERNAL_TLS_KEY_FILE must be set together "
                "(set both to override the primary listener's TLS, or neither to inherit it)"
            )
        return cert, key
    return _clean_path(settings.ws_tls_cert_file), _clean_path(settings.ws_tls_key_file)


def build_external_ws_server_config(
    settings: Settings,
    *,
    primary: WsServerConfig,
    host: str | None = None,
    port: int | None = None,
    max_connections: int | None = None,
    shutdown_timeout: float | None = None,
    readonly: bool | None = None,
) -> WsServerConfig | None:
    """构造**对外** listener 的配置（Epic 56 期二 D8）；未启用返回 ``None``。

    ``None`` 是默认形态（不配 ``WS_EXTERNAL_HOST`` ⇒ 与期一逐字等价）。启用时必须满足三条：

    - 绑定地址**非回环**：回环客户端已由主 listener（免 token）服务，再配一个回环对外 listener
      只会让同一个本机客户端有两个入口；
    - **主 listener 必须是本地模式**：主 listener 已经对外时再配一个对外 listener，等于两个对外
      入口共享同一状态机，运维无从判断该连哪个 ⇒ 显式拒绝；
    - token 必须存在（沿用 D5 fail-closed），TLS 半配同样拒绝（:func:`_external_tls_files`）。
    """
    raw_host = settings.ws_external_host if host is None else host
    resolved_host = (raw_host or "").strip()
    if not resolved_host:
        if host is not None:
            raise WsConfigError("--ws-external-host must not be empty (omit it to disable the external listener)")
        return None
    if is_loopback_host(resolved_host):
        raise WsConfigError(
            f"WS_EXTERNAL_HOST must be a non-loopback address (got {resolved_host!r}); "
            "the primary listener already serves loopback clients without authentication"
        )
    if primary.mode != "local":
        raise WsConfigError(
            f"WS_EXTERNAL_HOST requires a loopback primary listener (WS_HOST={primary.host!r} is already "
            "external); drop one of the two to keep a single external entry point"
        )
    token = settings.user_ws_auth_token
    cert, key = _external_tls_files(settings)
    try:
        return WsServerConfig(
            host=resolved_host,
            port=_resolve_listener_port(settings, resolved_host, port, default_port=settings.ws_external_port),
            ws_max_connections=settings.ws_max_connections if max_connections is None else max_connections,
            shutdown_timeout=settings.ws_shutdown_timeout if shutdown_timeout is None else shutdown_timeout,
            auth_token=SecretStr(token) if token else None,
            tls_cert_file=cert,
            tls_key_file=key,
            readonly=settings.ws_external_readonly if readonly is None else readonly,
        )
    except ValidationError as exc:
        raise WsConfigError(_first_validation_message(exc)) from exc


def build_ws_servers(
    settings: Settings,
    *,
    run_service: Any | None = None,
    cli_bypass: bool | None = None,
    enabled: bool | None = None,
    host: str | None = None,
    port: int | None = None,
    max_connections: int | None = None,
    shutdown_timeout: float | None = None,
    external_host: str | None = None,
    external_port: int | None = None,
    external_readonly: bool | None = None,
    push_enabled: bool | None = None,
) -> tuple[tuple[WsServer, ...], CliEventHub | None]:
    """构造 1–2 个 WS listener 与**实际挂载**的 CLI 旁路中枢（Epic 56 期二 D8/D9/D12）。

    返回 ``(servers, hub)``：``servers[0]`` 是主 listener（期一语义逐字不变），``servers[1]``
    （若存在）是对外 listener。``hub`` 为 ``None`` 表示旁路未启用**或**因 listener 身份被跳过——
    两种情况对入口层等价（没有可发布的通道）。

    ``enabled`` 缺省取 ``settings.ws_enabled``；默认 CLI 的 ``--no-ws`` 传 ``False``
    （只关本次进程的 WS 监听，不改配置文件、不改 Settings 单例）。

    ``cli_bypass`` 缺省取 ``settings.ws_cli_bypass_enabled``；``http-server`` 命令显式传 ``False``
    （它没有终端轮次可看，期一行为照旧）。

    D9 连带收紧：旁路只在**本地模式**的主 listener 上挂载。期一允许「``WS_HOST=0.0.0.0`` +
    ``WS_CLI_BYPASS_ENABLED=true``」把终端事件流推到对外 listener，期二起改为跳过并 WARNING。

    ``push_enabled``（Epic 58）缺省取 ``settings.cron_push_enabled``：为真时建一个
    :class:`NotificationHub` 挂到**每个** listener（``WsServer.notification_hub``）——返回形状
    因此保持不变（中枢由调用方经 ``servers[i].notification_hub`` 取出再交给服务单元）。
    """
    if not (settings.ws_enabled if enabled is None else enabled):
        # WS_ENABLED=false（或 --no-ws）：不构造任何 WS listener（旁路中枢也无从挂载）。
        return (), None

    primary = build_ws_server_config(
        settings,
        host=host,
        port=port,
        max_connections=max_connections,
        shutdown_timeout=shutdown_timeout,
    )
    external = build_external_ws_server_config(
        settings,
        primary=primary,
        host=external_host,
        port=external_port,
        max_connections=max_connections,
        shutdown_timeout=shutdown_timeout,
        readonly=external_readonly,
    )
    bypass_enabled = settings.ws_cli_bypass_enabled if cli_bypass is None else cli_bypass
    hub: CliEventHub | None = None
    if bypass_enabled:
        if primary.mode == "local":
            hub = CliEventHub(max_connections=primary.ws_max_connections)
        else:
            # 不静默：用户打开了开关就必须能看到「为什么没有这条流」。
            _safe_log(
                logging.WARNING,
                "ws event=cli_bypass_skipped reason=external_listener host=%s "
                "hint=the CLI event stream is served only on a loopback listener",
                primary.host,
            )
    # Epic 58 D2/D4：`CRON_PUSH_ENABLED=true` 才建中枢 ⇒ 否则 `/api/notifications/ws` 连路由都不注册
    # （客户端拿 403，而不是「连上了但永远没帧」这种假可用）。中枢按 listener 数共用一份：
    # seq / 环形缓冲 / 订阅者都是进程级状态，两条 listener 各建一份会把游标语义拆散。
    push = settings.cron_push_enabled if push_enabled is None else push_enabled
    notification_hub: NotificationHub | None = (
        NotificationHub(max_connections=primary.ws_max_connections) if push else None
    )
    if notification_hub is not None and external is not None:
        # D2 已接受这个代价，但必须可见：对外 listener 上送的是宿主 cron 的 LLM 输出。
        _safe_log(
            logging.WARNING,
            "ws event=cron_push_exposed host=%s hint=cron results are served on the external "
            "listener too; keep CRON_PUSH_ENABLED=false or narrow WS_EXTERNAL_HOST to avoid it",
            external.host,
        )
    servers = [WsServer(primary, run_service=run_service, cli_hub=hub, notification_hub=notification_hub)]
    if external is not None:
        # 对外 listener 永不带 CLI 旁路（D9）：即使主 listener 那条被跳过也一样。
        # 通知中枢则相反——**每个** listener 都挂（Epic 58 D2：对外已有 token 认证，不再叠模式判据）。
        servers.append(WsServer(external, run_service=run_service, notification_hub=notification_hub))
    return tuple(servers), hub


def _first_validation_message(exc: ValidationError) -> str:
    """取 Pydantic 校验的首条错误文案（不带 ``Value error, `` 前缀，便于直接给用户看）。"""
    errors = exc.errors()
    if not errors:
        return "invalid WS server configuration"
    message = str(errors[0].get("msg", "")).strip()
    prefix = "Value error, "
    return message[len(prefix) :] if message.startswith(prefix) else message


def _project_env_declares(env_key: str) -> bool:
    """项目 ``.env`` 是否声明了该键（用于「写错位置」的显式告警，不作为取值路径）。

    只做行级文本匹配：值本身**不读**（读了也不能用——凭证只认用户级 ``setting.md``）。
    """
    path = Path(".env")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    pattern = re.compile(rf"^\s*{re.escape(env_key)}\s*=", re.IGNORECASE | re.MULTILINE)
    return pattern.search(text) is not None


def build_http_service(
    settings: Settings,
    *,
    executor: Any | None = None,
    http_enabled: bool | None = None,
    ws_enabled: bool | None = None,
) -> EmbeddedHttpService:
    """按 ``Settings`` 构造默认 CLI 的内嵌网页入口（HTTP 8766 + 1–2 个 WS listener，Epic 56 D1/期二）。

    ``HTTP_ENABLED`` / ``WS_ENABLED`` 为假时对应 listener 不装配；两者都为假 ⇒ 休眠服务（零监听）。
    ``http_enabled`` / ``ws_enabled`` 是**本次进程**的显式覆盖（``None`` = 照配置取值），供默认 CLI
    的 ``--no-http`` / ``--no-ws`` 使用：只影响本次装配，不写回配置文件、也不改 Settings 单例。

    默认 CLI **不提供** HTTP/WS 的绑定与限额选项（brief：不做含糊的参数透传），因此这里不带
    地址/端口覆盖参数——绑定地址与限额全部来自 ``HTTP_*`` / ``WS_*`` / ``WS_EXTERNAL_*`` 设置；
    需要覆盖时用显式 `heagent http-server`。

    ``executor`` 是运行入口（入口层的 :class:`HttpAgentHandler`）：为 ``None`` 时 HTTP 只提供健康
    检查与静态页（Story 49-1 的形态），``/api/runs*`` 与 ``/api/session`` 不注册；WS 侧的 run
    订阅端点同样不注册（端点随 ``run_service`` 注入）。

    ``settings.ws_cli_bypass_enabled`` 为真时**另建**一个 :class:`CliEventHub` 并在**本地模式的** WS
    listener 上注册 ``/api/cli/ws``（Epic 55 的 CLI 旁路，Epic 56 D7 起宿主 = WS server）：它与
    ``executor`` 无关——旁路订阅的是**终端自己那一轮** run，不是网页创建的 run。它**不会**挂到对外
    listener 上（期二 D9）：终端事件可能含文件内容，认证只降低风险、不消除风险。
    """
    config = build_server_config(settings)
    run_service = HttpRunService(config, executor) if executor is not None else None
    workspace = WorkspacePaths.from_root(getattr(settings, "workspace_root", None) or os.getcwd())
    http_on = settings.http_enabled if http_enabled is None else http_enabled
    ws_on = settings.ws_enabled if ws_enabled is None else ws_enabled
    http_server: HttpServer | None = None
    if http_on:
        console = HttpProjectConsole(
            workspace.root,
            projects_file=settings.http_console_projects_file,
            runs=run_service,
            # 只有入口层的真实 handler 知道怎么为「另一个项目根」派生运行时；注入的是别的可调用对象
            # （测试替身）时**不**假装能给项目起跑——会话 API 仍可用，项目内运行回 project_unavailable。
            handler_factory=executor.for_workspace if isinstance(executor, HttpAgentHandler) else None,
            write_enabled=settings.http_console_write_enabled,
        )
        http_server = HttpServer(
            config,
            version=_current_version(),
            run_service=run_service,
            console=console,
        )
    # 1–2 个 WS listener（期二双监听）+ 实际挂载的 CLI 旁路中枢：装配决策单一真源在 build_ws_servers。
    ws_servers, cli_hub = build_ws_servers(settings, run_service=run_service, enabled=ws_on)
    # 通知中枢的真源同样在 build_ws_servers（同一份挂到每个 listener）：这里只把它抬到服务单元，
    # 供入口层构造的 cron notifier 发布。没有任何 listener ⇒ 无中枢。
    notification_hub = ws_servers[0].notification_hub if ws_servers else None
    return EmbeddedHttpService(http_server, ws_servers, cli_hub=cli_hub, notification_hub=notification_hub)


def embedded_http_error_message(exc: BaseException) -> str | None:
    """把内嵌 HTTP 的启动失败转成一行命令级文案；其它异常返回 ``None``（由调用方原样传播）。

    绑定失败与「缺可选依赖」都必须让默认 CLI **显式失败**（story 49-2 AC）：静默降级成「没有网页
    入口但聊天照常」是明确禁止的行为。WS 配置不成立（对外模式缺 token / TLS 半配）同属显式失败。
    """
    if isinstance(exc, HttpStartupError):
        return f"HTTP server failed to start: {exc}"
    if isinstance(exc, WsConfigError):
        return f"WS server configuration is invalid: {exc}"
    if isinstance(exc, WsStartupError):
        return f"WS server failed to start: {exc}"
    if isinstance(exc, HttpDependencyError):
        return str(exc)
    return None


@click.command("http-server")
@click.option(
    "--no-http",
    "no_http",
    is_flag=True,
    default=False,
    help="Do not start the HTTP listener for this process (WS listeners unaffected)",
)
@click.option(
    "--no-ws",
    "no_ws",
    is_flag=True,
    default=False,
    help="Do not start the WebSocket listeners for this process (HTTP listener unaffected)",
)
@click.option(
    "--host",
    default=None,
    help="Bind address (default: HTTP_HOST / 127.0.0.1). This entry is experimental and unsupported on non-loopback networks.",
)
@click.option(
    "--port",
    type=click.IntRange(min=1, max=65535),
    default=None,
    help="Bind port (default: HTTP_PORT / 8766)",
)
@click.option(
    "--max-connections",
    type=click.IntRange(min=1),
    default=None,
    help="Max simultaneous client connections (default: HTTP_MAX_CONNECTIONS / 16)",
)
@click.option(
    "--max-subscribers",
    type=click.IntRange(min=1),
    default=None,
    help="Max SSE subscribers per run; extra ones get 429 rate_limited (default: HTTP_MAX_SUBSCRIBERS / 16)",
)
@click.option(
    "--ws-host",
    default=None,
    help="WS listener bind address (default: WS_HOST / 127.0.0.1)",
)
@click.option(
    "--ws-port",
    type=click.IntRange(min=1, max=65535),
    default=None,
    help="WS listener bind port (default: WS_PORT / 9901)",
)
@click.option(
    "--ws-max-connections",
    type=click.IntRange(min=1),
    default=None,
    help="Max WebSocket connections (per run and CLI hub total; applied to every WS listener; "
    "default: WS_MAX_CONNECTIONS / 16)",
)
@click.option(
    "--ws-external-host",
    default=None,
    help="Second WS listener for external clients (default: WS_EXTERNAL_HOST / disabled); must be "
    "non-loopback and requires WS_AUTH_TOKEN in ~/.heagent/setting.md",
)
@click.option(
    "--ws-external-port",
    type=click.IntRange(min=1, max=65535),
    default=None,
    help="External WS listener port (default: WS_EXTERNAL_PORT / 9002)",
)
@click.option(
    "--ws-external-readonly/--ws-external-writable",
    default=None,
    help="Make the external WS listener read-only (no run submission, cancel rejected); "
    "default: WS_EXTERNAL_READONLY / off",
)
@click.option(
    "--max-inflight-runs",
    type=click.IntRange(min=1),
    default=None,
    help="Max concurrent agent runs; extra submissions get run_conflict (default: HTTP_MAX_INFLIGHT_RUNS / 1)",
)
@click.option(
    "--max-total-inflight",
    type=click.IntRange(min=0),
    default=None,
    help="Max concurrent agent runs across ALL projects; 0 = unlimited (default: HTTP_MAX_TOTAL_INFLIGHT / 0)",
)
@click.option(
    "--max-request-bytes",
    type=click.IntRange(min=1),
    default=None,
    help="Max size of one JSON request body in bytes (default: HTTP_MAX_REQUEST_BYTES / 65536)",
)
@click.option(
    "--event-buffer-size",
    type=click.IntRange(min=1),
    default=None,
    help="Max buffered SSE events per run (default: HTTP_EVENT_BUFFER_SIZE / 512)",
)
@click.option(
    "--run-history-size",
    type=click.IntRange(min=1),
    default=None,
    help="Max finished run records kept for SSE replay (default: HTTP_RUN_HISTORY_SIZE / 64)",
)
@click.option(
    "--request-timeout",
    type=click.FloatRange(min=0),
    callback=_reject_non_finite,
    default=None,
    help="Hard ceiling in seconds for one agent run; 0 = unlimited (default: HTTP_REQUEST_TIMEOUT / 0)",
)
@click.option(
    "--idle-timeout",
    type=click.FloatRange(min=0),
    callback=_reject_non_finite,
    default=None,
    help="Seconds without events or an in-flight tool before a run is treated as stalled; 0 = off "
    "(default: HTTP_IDLE_TIMEOUT / 300)",
)
@click.option(
    "--shutdown-timeout",
    type=click.FloatRange(min=0, min_open=True),
    callback=_reject_non_finite,
    default=None,
    help="Seconds to drain in-flight work on shutdown (default: HTTP_SHUTDOWN_TIMEOUT / 5)",
)
@click.option("--model", default=None, help="Model name (default: per-provider setting)")
@click.option("--system", default=None, help="System prompt applied to every run")
@click.option("--max-iterations", type=int, default=None, help="Max agent loop iterations per run")
@click.option("--soul", default=None, help="Path to custom SOUL.md personality file")
@click.option(
    "--sandbox",
    type=click.Choice(["auto", "passthrough", "firejail", "winjob", "docker"]),
    default=None,
    help="Sandbox backend for shell execution (default: auto = probe firejail)",
)
@click.option(
    "--dialog-backend",
    type=click.Choice(["auto", "tkinter", "powershell", "none"]),
    default="none",
    help="Native folder picker for 'select directory' (default: none = disabled; "
    "use auto/tkinter/powershell to enable when needed)",
)
def http_server_cmd(
    no_http: bool,
    no_ws: bool,
    host: str | None,
    port: int | None,
    max_connections: int | None,
    max_subscribers: int | None,
    ws_host: str | None,
    ws_port: int | None,
    ws_max_connections: int | None,
    ws_external_host: str | None,
    ws_external_port: int | None,
    ws_external_readonly: bool | None,
    max_inflight_runs: int | None,
    max_total_inflight: int | None,
    max_request_bytes: int | None,
    event_buffer_size: int | None,
    run_history_size: int | None,
    request_timeout: float | None,
    idle_timeout: float | None,
    shutdown_timeout: float | None,
    model: str | None,
    system: str | None,
    max_iterations: int | None,
    soul: str | None,
    sandbox: str | None,
    dialog_backend: str,
) -> None:
    """Serve the built-in HeAgent web UI over HTTP (experimental; no authentication)."""
    # 函数内导入：``console`` 在模块尾部 import 本模块注册命令，模块级互相导入会成环。
    from heagent.cli.console import _prune_runtime_artifacts, _setup_logging  # noqa: PLC0415
    from heagent.pub.roles import load_agent_roles  # noqa: PLC0415

    _setup_logging()
    settings = get_settings()
    # 三态：配置层的 HTTP_ENABLED / WS_ENABLED 再叠加本次进程的 --no-http / --no-ws
    # （flag 只能**关**，不能开——避免「配置说关、命令行悄悄开」这种反向意外）。
    http_on = settings.http_enabled and not no_http
    ws_on = settings.ws_enabled and not no_ws
    if not http_on and not ws_on:
        raise click.ClickException(
            "Both HTTP and WS entries are disabled - nothing to serve "
            "(check HTTP_ENABLED / WS_ENABLED, or drop --no-http / --no-ws); "
            "interactive mode runs fine with both off."
        )
    # 公告放在 fail-fast 之后：「什么都不起」是错误，不该先打一行「已按你的要求关闭」。
    echo_web_entry_overrides(http_disabled=no_http, ws_disabled=no_ws)
    _prune_runtime_artifacts(settings)
    # 角色是 system prompt 的组成部分（技能匹配 / 子 Agent 委派都读它），与其它入口一致地加载。
    load_agent_roles()
    # 沙箱提示：与 CLI / GUI 同源（请求档 + CLI 存在性检查）。服务化入口尤其需要——
    # 没有这行，`http-server` 跑起来后「shell 到底有没有进容器」只能翻日志。
    echo_sandbox_hint(sandbox or settings.sandbox_backend, settings, install_hint=True)
    provider = _build_provider(settings, model)
    config = build_server_config(
        settings,
        host=host,
        port=port,
        max_connections=max_connections,
        max_subscribers=max_subscribers,
        max_inflight_runs=max_inflight_runs,
        max_total_inflight=max_total_inflight,
        max_request_bytes=max_request_bytes,
        event_buffer_size=event_buffer_size,
        run_history_size=run_history_size,
        request_timeout=request_timeout,
        idle_timeout=idle_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    handler = HttpAgentHandler(
        provider,
        settings,
        system=system,
        max_iterations=max_iterations,
        sandbox_backend=sandbox,
        soul_path=soul,
    )
    if _project_env_declares(WS_AUTH_TOKEN_KEY):
        # D3：凭证只认用户级 setting.md。项目 .env 写了也不生效——说清楚，否则用户会以为
        # 「仓库里配了 token 就是认证过的」，而实际对外模式会直接拒绝启动（或本地模式根本没认证）。
        click.echo(
            f"[ws] WARNING: {WS_AUTH_TOKEN_KEY.upper()} in the project .env is ignored"
            " (the WS token is read only from ~/.heagent/setting.md)",
            err=True,
        )
    workspace = WorkspacePaths.from_root(os.getcwd())

    run_service = HttpRunService(config, handler)
    server: HttpServer | None = None
    if http_on:
        console = HttpProjectConsole(
            workspace.root,
            projects_file=settings.http_console_projects_file,
            runs=run_service,
            handler_factory=handler.for_workspace,
            write_enabled=settings.http_console_write_enabled,
            dialog_backend=dialog_backend,
        )
        server = HttpServer(
            config,
            version=_current_version(),
            run_service=run_service,
            console=console,
        )
    try:
        # 期二 D8/D9/D12：主 listener + 可选对外 listener；`http-server` 没有终端轮次 ⇒ 不开旁路。
        # Epic 58：本进程**没有 cron**（`enable_cron=False`），中枢建了也永远不会有帧 ⇒ 显式不建，
        # 免得客户端连上一条永不投递的「假可用」流。
        ws_servers, _hub = build_ws_servers(
            settings,
            run_service=run_service,
            cli_bypass=False,
            enabled=ws_on,
            push_enabled=False,
            host=ws_host,
            port=ws_port,
            max_connections=ws_max_connections,
            external_host=ws_external_host,
            external_port=ws_external_port,
            external_readonly=ws_external_readonly,
        )
    except WsConfigError as exc:
        # 对外缺 token / 对外键取回环 / 主 listener 已对外 / TLS 半配：配置不成立，压根不该尝试绑定。
        raise click.ClickException(f"WS server configuration is invalid: {exc}") from None
    # 非回环绑定：启动前先向 stderr 打印一次明确告警。HTTP 侧固定「无认证」口径；WS 侧按 mode
    # 分流——对外模式是 token 认证，套用 exposure_warning 的「no authentication」文案会撒谎。
    if server is not None:
        warning = exposure_warning(config.host)
        if warning is not None:
            click.echo(f"[http] WARNING: {warning}", err=True)
    for ws in ws_servers:
        ws_config = ws.config
        if ws_config.requires_auth:
            transport = "TLS" if ws_config.tls_enabled else "PLAINTEXT"
            click.echo(
                f"[ws] WARNING: exposed on {ws_config.host}:{ws_config.port} "
                f"(external mode; Bearer token required; {transport})",
                err=True,
            )
        else:
            ws_warning = exposure_warning(ws_config.host)
            if ws_warning is not None:
                click.echo(f"[ws] WARNING: {ws_warning}", err=True)
    if any(ws.config.requires_auth and not ws.config.tls_enabled for ws in ws_servers):
        click.echo(
            "[ws] WARNING: external WS mode without TLS (plaintext); "
            "configure WS_TLS_CERT_FILE and WS_TLS_KEY_FILE (or the WS_EXTERNAL_TLS_* pair) to serve wss",
            err=True,
        )
    try:
        asyncio.run(_serve_web(server, ws_servers))
    except KeyboardInterrupt:
        # Ctrl+C：asyncio.run 先取消主任务、跑完 ``_serve_http`` 的 finally（有界 close），再把
        # KeyboardInterrupt 抛回来。用户主动停止不是错误——安静退出，不打印 traceback。
        click.echo("[http] stopped", err=True)
    except HttpStartupError as exc:
        # 绑定失败 / 就绪探测失败：只给一行可诊断文案，不打印任何「已监听」，也不吐 traceback。
        raise click.ClickException(f"HTTP server failed to start: {exc}") from None
    except WsStartupError as exc:
        raise click.ClickException(f"WS server failed to start: {exc}") from None
    except HttpDependencyError as exc:
        raise click.ClickException(str(exc)) from None


__all__ = [
    "EmbeddedHttpService",
    "HttpAgentHandler",
    "build_external_ws_server_config",
    "build_http_service",
    "build_server_config",
    "build_ws_server_config",
    "build_ws_servers",
    "embedded_http_error_message",
    "http_server_cmd",
]
