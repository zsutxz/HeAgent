"""进程状态聚合的来源适配（``GET /api/status`` 的入口层实现）。

传输层只认注入的 :class:`~heagent.network.http_server.StatusSource` 契约；本模块是**唯一**能同时
看到运行服务、WS 中枢、listener 与配置面的地方，因此这些事实在这里聚合成协议模型
（``StatusResponse``）。网络层因此不必认识运行栈，依赖边界保持不变。

两处**晚绑定**（装配顺序决定，不是设计喜好）：

- ``HttpServer`` 先于 ``build_ws_servers`` 构造 ⇒ WS 计数与 listener 列表只能「先注入 source、后
  ``bind_status_source``」；
- listener 的**实际端口**（``port=0`` 或端口顺延时）只有绑定完成才知道 ⇒ ``status()`` 在请求时读
  ``server.port``，而不是在构造期抄下配置值。

通知中枢**全局一份**（同一实例挂在每个 listener 上）：计数必须取那一份，按 listener 逐个相加会
把同一批连接重复计。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from heagent.network.http_protocol import (
    ListenerInfo,
    ListenerMode,
    RoutingPoolInfo,
    RunStatusCounts,
    StatusResponse,
    WsConnectionCounts,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from heagent.config import Settings
    from heagent.network.http_server import HttpRunService

# 后台任务计数的读取窗口：注册表只为**终态**条目设保留上限（默认 32 条），在途条目是个位数，
# 取一个明显大于两者之和的窗口 ⇒ 计数即整表。窗口满了只会少算多出来的那些，不会让端点失败。
_BACKGROUND_TASK_WINDOW = 256

# 协议字段的字符/条数上限（与 ``http_protocol`` 的模型同界）。状态面是**展示用途**：超长或超量
# 就截断/取前 N 条，绝不因为一条异常配置把整条响应变成 500。
_MAX_HOST_CHARS = 255
_MAX_BACKEND_CHARS = 32
_MAX_PROVIDER_CHARS = 64
_MAX_POOL_NAME_CHARS = 64
_MAX_TIER_CHARS = 64
_MAX_TIERS = 64


def _clip(value: object, limit: int) -> str:
    """把任意配置值收敛成不超过协议上限的字符串（``None`` → 空串）。"""
    return str(value or "")[:limit]


def _connection_count(hub: Any | None) -> int:
    """中枢当前的连接数；未注册（``None``）即 0。"""
    return 0 if hub is None else int(hub.connection_count)


def _notification_hub_of(servers: Sequence[Any]) -> Any | None:
    """取第一个 listener 上挂着的通知中枢（同一实例按设计挂在每个 listener 上）。"""
    for server in servers:
        hub = getattr(server, "notification_hub", None)
        if hub is not None:
            return hub
    return None


def _provider_name(provider: Any | None) -> str:
    """当前生效的 provider 条目名（可切换/组合 provider 暴露 ``active``）；取不到即空串。"""
    return _clip(getattr(provider, "active", None), _MAX_PROVIDER_CHARS)


def _deployment(
    settings: Settings,
    *,
    sandbox_backend: str | None = None,
    provider: Any | None = None,
) -> tuple[str, bool, str, list[RoutingPoolInfo]]:
    """装配期就能确定的部署标量：沙箱后端、写入闸门、生效 provider、路由池档位名。

    ``sandbox_backend`` 必须是**本进程实际使用的档位**（``--sandbox`` 是命令行覆盖，配置里可能仍是
    ``auto``）；``provider`` 同理取运行中的 provider 实例，而不是配置里钉的那个名字。

    池只取 ``tiers`` 的**键**（池内名，即 ``/model`` 接受的名字）：模型名与 ``base_url`` 属供应商
    细节，状态面不回答「档位指向谁」。所有字符串按协议上限截断——状态面宁可截断，也不能因为一条
    超长配置让整个端点 500。
    """
    pools = [
        RoutingPoolInfo(
            pool=_clip(name, _MAX_POOL_NAME_CHARS),
            tiers=[_clip(tier, _MAX_TIER_CHARS) for tier in list(spec.tiers)[:_MAX_TIERS]],
        )
        for name, spec in sorted(settings.routing_pool_map.items())
    ]
    backend = sandbox_backend or settings.sandbox_backend
    active = _provider_name(provider) or str(settings.active_provider or "")
    return (
        _clip(backend, _MAX_BACKEND_CHARS),
        bool(settings.http_console_write_enabled),
        _clip(active, _MAX_PROVIDER_CHARS),
        pools,
    )


def _listener_infos(http_server: Any | None, ws_servers: Sequence[Any]) -> list[ListenerInfo]:
    """已装配 listener 的事实列表：http 在前，ws 按装配顺序（主 listener 是第一条）。

    端口读**运行中的** listener（``port=0`` / 端口顺延后配置值不等于真实值）；HTTP listener 在本
    产品里恒为明文（无 TLS 配置项），``tls`` 只对 WS 有意义。
    """
    infos: list[ListenerInfo] = []
    if http_server is not None:
        config = http_server.config
        infos.append(
            ListenerInfo(
                kind="http",
                label="http",
                host=_clip(config.host, _MAX_HOST_CHARS),
                port=int(http_server.port),
                mode=ListenerMode(config.mode),
                tls=False,
            )
        )
    for index, server in enumerate(ws_servers):
        config = server.config
        infos.append(
            ListenerInfo(
                kind="ws",
                label="ws-primary" if index == 0 else "ws-external",
                host=_clip(config.host, _MAX_HOST_CHARS),
                port=int(server.port),
                mode=ListenerMode(config.mode),
                tls=bool(config.tls_enabled),
            )
        )
    return infos


class HttpStatusSource:
    """把运行服务 / WS 中枢 / listener / 配置面聚合成 :class:`StatusResponse`。

    ``run_service`` 为 ``None`` 时（HTTP 只提供健康检查与静态页的形态）运行态报 0——没有运行服务
    就不可能有 run，也不可能挂着运行订阅连接，这是事实而不是缺项。
    """

    def __init__(
        self,
        *,
        version: str,
        max_inflight_runs: int,
        run_service: HttpRunService | None = None,
        task_registry: Any | None = None,
        settings: Settings | None = None,
        sandbox_backend: str | None = None,
        provider: Any | None = None,
    ) -> None:
        self._version = version
        self._max_inflight_runs = max_inflight_runs
        self._run_service = run_service
        self._task_registry = task_registry
        self._cli_hub: Any | None = None
        self._notification_hub: Any | None = None
        self._http_server: Any | None = None
        self._ws_servers: tuple[Any, ...] = ()
        deployment = (
            _deployment(settings, sandbox_backend=sandbox_backend, provider=provider)
            if settings is not None
            else ("", False, "", [])
        )
        self._sandbox_backend, self._config_write_enabled, self._active_provider, self._routing_pools = deployment

    def bind_ws(
        self,
        servers: Sequence[Any] = (),
        *,
        cli_hub: Any | None = None,
        notification_hub: Any | None = None,
    ) -> None:
        """绑定 WS 侧来源（必须在 ``build_ws_servers`` 之后调用）。

        ``cli_hub`` 是 CLI 旁路中枢（旁路未启用 / 因 listener 身份被跳过时为 ``None``，
        两种情况对 status 等价）；通知中枢显式传入优先，否则取 listener 上那一份。
        """
        self._ws_servers = tuple(servers)
        self._cli_hub = cli_hub
        self._notification_hub = notification_hub if notification_hub is not None else _notification_hub_of(servers)

    def bind_listeners(self, http_server: Any | None = None) -> None:
        """绑定 HTTP listener（``None`` 表示本次进程没有装配它）。"""
        self._http_server = http_server

    def status(self) -> StatusResponse:
        """进程状态的只读快照（同步：只读内存计数，不扫盘、不采样）。"""
        service = self._run_service
        return StatusResponse(
            version=self._version,
            active_runs=service.active_runs if service is not None else 0,
            # 没有运行服务就没有名额可谈（``/api/runs`` 也未注册）：报 0 而不是配置里的每项目上限。
            max_inflight_runs=self._max_inflight_runs if service is not None else 0,
            run_records=service.run_records if service is not None else 0,
            run_status=service.run_status_counts() if service is not None else RunStatusCounts(),
            ws_connections=WsConnectionCounts(
                runs=service.ws_connections if service is not None else 0,
                cli=_connection_count(self._cli_hub),
                notifications=_connection_count(self._notification_hub),
            ),
            background_tasks=self._background_tasks(),
            listeners=_listener_infos(self._http_server, self._ws_servers),
            sandbox_backend=self._sandbox_backend,
            config_write_enabled=self._config_write_enabled,
            active_provider=self._active_provider,
            routing_pools=list(self._routing_pools),
        )

    def _background_tasks(self) -> int:
        """后台任务注册表里当前可见的条目数（注册表未注入即 0）。"""
        if self._task_registry is None:
            return 0
        return len(self._task_registry.snapshot(limit=_BACKGROUND_TASK_WINDOW))


def build_status_source(
    *,
    version: str,
    max_inflight_runs: int,
    run_service: HttpRunService | None,
    task_registry: Any | None,
    settings: Settings | None,
    sandbox_backend: str | None = None,
    provider: Any | None = None,
    enabled: bool,
) -> HttpStatusSource | None:
    """按「HTTP listener 是否启用」构造状态来源；未启用即 ``None``（路由随之不注册）。

    判定与构造放在同一次调用里：调用方因此不必再写分支——``cli/http.py`` 的两个入口函数已在
    复杂度上限边缘，多一个 ``if`` 就会撞 C901。
    """
    if not enabled:
        return None
    return HttpStatusSource(
        version=version,
        max_inflight_runs=max_inflight_runs,
        run_service=run_service,
        task_registry=task_registry,
        settings=settings,
        sandbox_backend=sandbox_backend,
        provider=provider,
    )


def bind_status_source(
    source: HttpStatusSource | None,
    servers: Sequence[Any] = (),
    *,
    http_server: Any | None = None,
    cli_hub: Any | None = None,
    notification_hub: Any | None = None,
) -> None:
    """把 listener 与 WS 侧来源绑到状态来源上（``None`` 来源即空操作）。

    必须在 ``HttpServer`` 与 ``build_ws_servers`` **之后**调用：注入的是同一个 source 对象，
    因此晚绑定对已经构造好的 app 同样可见。
    """
    if source is None:
        return
    source.bind_listeners(http_server)
    source.bind_ws(servers, cli_hub=cli_hub, notification_hub=notification_hub)


__all__ = ["HttpStatusSource", "bind_status_source", "build_status_source"]
