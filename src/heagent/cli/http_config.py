"""HTTP/WS listener 配置装配：把 ``Settings`` 与 CLI 覆盖合并成 ``HttpServerConfig`` / ``WsServerConfig``。

与 :mod:`heagent.cli.http` 的分界：本模块只做**纯配置推导**（不启动服务、不写 Click 命令），
``http`` 侧负责把配置交给服务单元与命令层。搬出原因：``cli/http.py`` 超过 NFR3 单文件
1000 行红线（Story 62.8），派生逻辑与运行期编排同居一文件。
"""

import logging
import math
from typing import Any

import click
from pydantic import SecretStr, ValidationError

from heagent.cli.display import _current_version
from heagent.config import Settings
from heagent.network.cli_event_hub import CliEventHub
from heagent.network.exposure import is_loopback_host
from heagent.network.http_server import (
    HttpServerConfig,
)
from heagent.network.notification_hub import NotificationHub
from heagent.network.ws_host import WsConfigError, WsServer, WsServerConfig
from heagent.pub.safe_logging import safe_log

logger = logging.getLogger(__name__)


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


def _ws_config(**kw: Any) -> WsServerConfig:
    """构造 ``WsServerConfig``；校验失败转 :class:`WsConfigError`（取首条消息）。"""
    try:
        return WsServerConfig(**kw)
    except ValidationError as exc:
        raise WsConfigError(_first_validation_message(exc)) from exc


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
    （HTTP 自 9101、WS 自 9201），实际端口以启动公告为准。

    **对外模式的三件接线**（Epic 56 D3/D4/D5）：

    - ``auth_token`` 来自 :attr:`Settings.user_ws_auth_token`（只读用户级 ``setting.md``；项目
      ``.env`` / 系统环境变量一律不参与）；
    - 非回环绑定缺 token ⇒ :class:`WsConfigError`（fail-closed，绝不降级成无认证对外）；
    - TLS cert/key 来自 ``WS_TLS_CERT_FILE`` / ``WS_TLS_KEY_FILE``，半配同样 fail-loud。
    """
    resolved_host = settings.ws_host if host is None else host
    token = settings.user_ws_auth_token
    return _ws_config(
        host=resolved_host,
        port=_resolve_listener_port(settings, resolved_host, port, default_port=settings.ws_port),
        ws_max_connections=settings.ws_max_connections if max_connections is None else max_connections,
        shutdown_timeout=settings.ws_shutdown_timeout if shutdown_timeout is None else shutdown_timeout,
        auth_token=SecretStr(token) if token else None,
        local_auth=settings.ws_local_auth_enabled,
        tls_cert_file=settings.ws_tls_cert_file,
        tls_key_file=settings.ws_tls_key_file,
    )


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

    - 绑定地址**非回环**：回环客户端已由主 listener 服务（免 token，除非 `WS_LOCAL_AUTH_ENABLED=true`——
      2026-11-04 D5 修订），再配一个回环对外 listener 只会让同一个本机客户端有两个入口；
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
            "the primary listener already serves loopback clients"
        )
    if primary.mode != "local":
        raise WsConfigError(
            f"WS_EXTERNAL_HOST requires a loopback primary listener (WS_HOST={primary.host!r} is already "
            "external); drop one of the two to keep a single external entry point"
        )
    token = settings.user_ws_auth_token
    cert, key = _external_tls_files(settings)
    return _ws_config(
        host=resolved_host,
        port=_resolve_listener_port(settings, resolved_host, port, default_port=settings.ws_external_port),
        ws_max_connections=settings.ws_max_connections if max_connections is None else max_connections,
        shutdown_timeout=settings.ws_shutdown_timeout if shutdown_timeout is None else shutdown_timeout,
        auth_token=SecretStr(token) if token else None,
        tls_cert_file=cert,
        tls_key_file=key,
        readonly=settings.ws_external_readonly if readonly is None else readonly,
    )


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
            safe_log(
                logger,
                logging.WARNING,
                "ws event=cli_bypass_skipped reason=external_listener host=%s "
                "hint=the CLI event stream is served only on a loopback listener",
                primary.host,
            )
    # `CRON_PUSH_ENABLED=true` 才建中枢 ⇒ 否则 `/api/notifications/ws` 连路由都不注册
    # （客户端拿 403，而不是「连上了但永远没帧」这种假可用）。中枢按 listener 数共用一份：
    # seq / 环形缓冲 / 订阅者都是进程级状态，两条 listener 各建一份会把游标语义拆散。
    push = settings.cron_push_enabled if push_enabled is None else push_enabled
    notification_hub: NotificationHub | None = (
        NotificationHub(max_connections=primary.ws_max_connections) if push else None
    )
    if notification_hub is not None and external is not None:
        # 这个代价已接受，但必须可见：对外 listener 上送的是宿主 cron 的 LLM 输出。
        safe_log(
            logger,
            logging.WARNING,
            "ws event=cron_push_exposed host=%s hint=cron results are served on the external "
            "listener too; keep CRON_PUSH_ENABLED=false or narrow WS_EXTERNAL_HOST to avoid it",
            external.host,
        )
    servers = [
        WsServer(
            primary,
            run_service=run_service,
            cli_hub=hub,
            notification_hub=notification_hub,
            version=_current_version(),
        )
    ]
    if external is not None:
        # 对外 listener 永不带 CLI 旁路：即使主 listener 那条被跳过也一样。
        # 通知中枢则相反——**每个** listener 都挂（对外已有 token 认证，不再叠模式判据）。
        servers.append(
            WsServer(
                external,
                run_service=run_service,
                notification_hub=notification_hub,
                version=_current_version(),
            )
        )
    return tuple(servers), hub


def _first_validation_message(exc: ValidationError) -> str:
    """取 Pydantic 校验的首条错误文案（不带 ``Value error, `` 前缀，便于直接给用户看）。"""
    errors = exc.errors()
    if not errors:
        return "invalid WS server configuration"
    message = str(errors[0].get("msg", "")).strip()
    prefix = "Value error, "
    return message[len(prefix) :] if message.startswith(prefix) else message
