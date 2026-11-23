"""HTTP/WS listener 配置装配：把 ``Settings`` 与 CLI 覆盖合并成 ``HttpServerConfig`` / ``WsServerConfig``。

与 :mod:`heagent.cli.http` 的分界：本模块只做**纯配置推导**（不启动服务、不写 Click 命令），
``http`` 侧负责把配置交给服务单元与命令层。搬出原因：``cli/http.py`` 超过 NFR3 单文件
1000 行红线（Story 62.8），派生逻辑与运行期编排同居一文件。
"""

import logging
import math
from datetime import UTC, datetime
from typing import Any

import click
from pydantic import SecretStr, ValidationError

from heagent.cli.display import _current_version
from heagent.config import Settings
from heagent.network.cli_event_hub import CliEventHub
from heagent.network.exposure import unbracket_host
from heagent.network.http_server import (
    HttpServerConfig,
)
from heagent.network.notification_hub import NotificationHub
from heagent.network.tls_identity import TlsIdentityError, certificate_info, san_covers
from heagent.network.ws_host import WsConfigError, WsServer, WsServerConfig
from heagent.pub.safe_logging import safe_log

logger = logging.getLogger(__name__)

#: 叶证书到期告警阈值（天）：余量小于它就在启动期 WARNING、在 doctor 里升为 WARNING。
#: **唯一真源**——启动自检与 doctor 共用，别在别处再写这个字面量。
TLS_EXPIRY_WARNING_DAYS = 7

#: 通配绑定：客户端实际连的是某个具体地址，SAN 覆盖与否在这个地址上无从判定。
_WILDCARD_BINDS = frozenset({"0.0.0.0", "::"})  # nosec B104 - 仅识别通配绑定，本模块不在此绑定 # noqa: S104

_SECONDS_PER_DAY = 86400.0


def binds_every_interface(host: str) -> bool:
    """绑定地址是否「所有网卡」（``0.0.0.0`` / ``::``，含方括号写法）。"""
    return unbracket_host(host).lower() in _WILDCARD_BINDS


def format_not_after(moment: datetime) -> str:
    """证书时刻的紧凑人读形态（``2026-12-19T21:03:00Z``）；日志与 doctor 文案共用。"""
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def tls_remaining_days(not_after: datetime, *, now: datetime | None = None) -> float:
    """叶证书余量（天，可为负 = 已过期）。``now`` 可注入，测试据此造余量而不现签短期证书。"""
    return (not_after - (now or datetime.now(UTC))).total_seconds() / _SECONDS_PER_DAY


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
        lan_no_auth=settings.ws_lan_no_auth,
        tls_cert_file=settings.ws_tls_cert_file,
        tls_key_file=settings.ws_tls_key_file,
    )


def _clean_path(value: str | None) -> str | None:
    """把可选路径配置归一化：空串 / 纯空白视为未配置（``.env`` 里写 ``KEY=`` 的常见形态）。"""
    if value is None:
        return None
    text = value.strip()
    return text or None


def _check_tls_identity(settings: Settings, host: str, *, now: datetime | None = None) -> list[str]:
    """启动期 TLS 身份自检：返回**应当 WARNING 的结论**（未启用 TLS 时返回空表）。

    为什么住在入口层：``network/`` 不得 import ``config/``，而「读哪两个键、要不要喊」是配置面与
    呈现面的判断；材料解析仍全部走 :mod:`heagent.network.tls_identity`（纯 stdlib，无子进程、无网络
    请求，符合「启动期不做网络 IO」）。

    三条结论的处置刻意不同：

    - 到期余量 < :data:`TLS_EXPIRY_WARNING_DAYS` / SAN 不含绑定地址 ⇒ **只告警，不拒绝启动**
      （内网地址漂移是常态，拒绝启动会让人无从自愈；两条文案都点名可执行命令）；
    - 材料读不出来 ⇒ :class:`WsConfigError`（此时问题不是「还能用多久」，而是「根本用不了」）。

    cert / key 配对与否不在这里判：那是 :class:`WsServerConfig` 构造期的 fail-loud 事实。
    """
    cert = _clean_path(settings.ws_tls_cert_file)
    key = _clean_path(settings.ws_tls_key_file)
    if cert is None or key is None:
        # 未启用 TLS（含半配）⇒ 三条检查全跳过；半配由 WsServerConfig 与 doctor 的既有语义报。
        return []
    moment = now or datetime.now(UTC)
    try:
        info = certificate_info(cert)
    except TlsIdentityError as exc:
        raise WsConfigError(
            f"WS TLS materials are unreadable ({exc}); startup is refused rather than serving a listener "
            "clients cannot handshake with. Fix WS_TLS_CERT_FILE / WS_TLS_KEY_FILE (re-issue with "
            "`heagent tls issue`, or point them at an existing cert.pem + key.pem pair)"
        ) from exc
    warnings: list[str] = []
    remaining = tls_remaining_days(info.not_after, now=moment)
    if remaining < TLS_EXPIRY_WARNING_DAYS:
        state = f"expired {abs(remaining):.1f} days ago" if remaining <= 0 else f"expires in {remaining:.1f} days"
        warnings.append(
            f"WS TLS certificate {state} (not_after {format_not_after(info.not_after)}); clients start "
            "failing the handshake the moment it lapses. Re-sign the leaf with the same identity key: "
            "`heagent tls issue` (the client pin does not change)"
        )
    if not binds_every_interface(host) and not san_covers(cert, host):
        warnings.append(
            f"WS TLS certificate SAN does not cover the bind address {host!r} "
            f"(SAN: {', '.join(info.san) or 'none'}); clients connecting to that address fail the "
            f"handshake. Re-sign with `heagent tls issue --san {host}` and restart heagent"
        )
    return warnings


#: 沙箱档位名：只有它能让远端提交的 run 跑在容器里（其余档位都落到宿主进程）。
_DOCKER_BACKEND = "docker"


def _warn_external_without_sandbox(config: WsServerConfig, sandbox_backend: str | None) -> str | None:
    """对外 listener + 非容器沙箱 ⇒ 返回**一条**启动 WARNING 的正文（其余情况 ``None``）。

    **提示不是闸门**：``external`` 档（非回环 + token）意味着任何持 token 的对端都能提交 run，而
    ``docker`` 以外的后端（``passthrough`` / 降级后的 ``auto``）会让这些 run 直接跑在宿主进程里。
    这层的真实边界是 OS 级容器（``docs/framework.md`` §4.18 的三层非边界），所以只喊不改行为：
    拒绝启动会把「内网临时开放」变成不可用，而风险等级并没有到那一步。

    判据取**启动期实际生效**的后端（``--sandbox`` / ``SANDBOX_BACKEND`` 只是请求值：``auto`` 或
    daemon 不可用时引擎会降级），由入口层经 ``sandbox_backend`` 注入；取不到时回落到配置值。
    """
    if config.mode != "external":
        return None
    backend = (sandbox_backend or "").strip() or "unknown"
    if backend == _DOCKER_BACKEND:
        return None
    return (
        f"listener=external sandbox={backend} host={config.host}: the WS listener is reachable from other "
        "machines and runs submitted over it execute on the HOST (sandbox backend is not docker); "
        "start with --sandbox docker to fence remote runs inside a container"
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
    push_enabled: bool | None = None,
    project_service: Any | None = None,
    sandbox_backend: str | None = None,
) -> tuple[tuple[WsServer, ...], CliEventHub | None]:
    """构造 WS listener（恒 1 条）与**实际挂载**的 CLI 旁路中枢（D9/D12）。

    返回 ``(servers, hub)``：``servers[0]`` 是唯一的 listener，``hub`` 为 ``None`` 表示旁路未启用
    **或**因 listener 身份被跳过——两种情况对入口层等价（没有可发布的通道）。
    对外第二监听器已随 Epic 72 退役：非回环入口只剩主 listener 一条，
    走 ``lan``（内网免认证）或 ``external``（强制 Bearer）。

    ``enabled`` 缺省取 ``settings.ws_enabled``；默认 CLI 的 ``--no-ws`` 传 ``False``
    （只关本次进程的 WS 监听，不改配置文件、不改 Settings 单例）。

    ``cli_bypass`` 缺省取 ``settings.ws_cli_bypass_enabled``；``http-server`` 命令显式传 ``False``
    （它没有终端轮次可看，期一行为照旧）。

    D9 的边界不变且更严格：旁路只在**回环** listener 上挂载。``lan`` / ``external`` 绑定一律跳过并
    WARNING（旁路内容包含终端里从未提交过的输入）。

    ``push_enabled``（Epic 58）缺省取 ``settings.cron_push_enabled``：为真时建一个
    :class:`NotificationHub` 挂到 listener（``WsServer.notification_hub``），经
    ``servers[0].notification_hub`` 取出交给服务单元；``lan`` listener 上它同样可见（客户端
    「三处对账」要求 ``PUSH_CONNECTED``），代价由 ``ws_host`` 的启动 WARNING 写明。

    ``project_service``（Epic 75）是 WS 项目通道的注入点，原样交给 ``WsServer`` ⇒ 同一条 listener 的
    集合级端点与单 run 端点拿到**同一个实例**；缺省 ``None`` 时行为与未注入前逐字相同（两个端点回
    ``invalid_request``，不静默按启动工作区执行）。

    TLS 启用时（cert 与 key 都非空）顺带跑一次身份自检（``_check_tls_identity``）：到期余量不足、
    SAN 不含绑定地址各记一条 WARNING（不阻断启动）；材料读不出来是 :class:`WsConfigError`。

    ``sandbox_backend``（Epic 76）是**启动期实际生效**的沙箱档位（入口层注入；缺省回落到
    ``settings.sandbox_backend``）：``external`` 档且它不是 ``docker`` 时记**一条** WARNING
    （:func:`_warn_external_without_sandbox`），不改变启动成败。
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
    # TLS 身份自检在装配点跑**一次**（不随 listener 数量或多次读配置叠加），逐条 WARNING。
    for message in _check_tls_identity(settings, primary.host):
        safe_log(
            logger,
            logging.WARNING,
            "ws event=tls_identity address=%s listener=%s %s",
            primary.host,
            primary.mode,
            message,
        )
    effective_backend = sandbox_backend if sandbox_backend is not None else settings.sandbox_backend
    sandbox_warning = _warn_external_without_sandbox(primary, effective_backend)
    if sandbox_warning is not None:
        # 恰一条：装配点每进程只走一次（内嵌 / http-server 两条入口互斥）。
        safe_log(logger, logging.WARNING, "ws event=external_without_sandbox %s", sandbox_warning)
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
                "ws event=cli_bypass_skipped reason=non_loopback_listener host=%s listener=%s "
                "hint=the CLI event stream is served only on a loopback listener (its content includes "
                "terminal input that was never submitted)",
                primary.host,
                primary.mode,
            )
    # `CRON_PUSH_ENABLED=true` 才建中枢 ⇒ 否则 `/api/notifications/ws` 连路由都不注册
    # （客户端拿 403，而不是「连上了但永远没帧」这种假可用）。
    push = settings.cron_push_enabled if push_enabled is None else push_enabled
    notification_hub: NotificationHub | None = (
        NotificationHub(max_connections=primary.ws_max_connections) if push else None
    )
    servers = [
        WsServer(
            primary,
            run_service=run_service,
            cli_hub=hub,
            notification_hub=notification_hub,
            version=_current_version(),
            project_service=project_service,
        )
    ]
    return tuple(servers), hub


def _first_validation_message(exc: ValidationError) -> str:
    """取 Pydantic 校验的首条错误文案（不带 ``Value error, `` 前缀，便于直接给用户看）。"""
    errors = exc.errors()
    if not errors:
        return "invalid WS server configuration"
    message = str(errors[0].get("msg", "")).strip()
    prefix = "Value error, "
    return message[len(prefix) :] if message.startswith(prefix) else message
