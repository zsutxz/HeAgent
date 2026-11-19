"""进程状态聚合的来源适配（``GET /api/status`` 的入口层实现）。

传输层只认注入的 :class:`~heagent.network.http_server.StatusSource` 契约；本模块是**唯一**能同时
看到运行服务、WS 中枢与后台任务注册表的地方，因此三处计数在这里聚合成协议模型
（``StatusResponse``）。网络层因此不必认识运行栈，依赖边界保持不变。

WS 连接数是**晚绑定**的：装配顺序上 ``HttpServer`` 先于 ``build_ws_servers`` 构造（HTTP 先起、
失败即整体回滚），所以只能「先注入 source、后 ``bind_ws``」。source 对象在装配期不变，因此 app
即使已被构造，读到的也是绑定后的中枢。

通知中枢**全局一份**（同一实例挂在每个 listener 上）：计数必须取那一份，按 listener 逐个相加会
把同一批连接重复计。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from heagent.network.http_protocol import RunStatusCounts, StatusResponse, WsConnectionCounts

if TYPE_CHECKING:
    from collections.abc import Sequence

    from heagent.network.http_server import HttpRunService

# 后台任务计数的读取窗口：注册表只为**终态**条目设保留上限（默认 32 条），在途条目是个位数，
# 取一个明显大于两者之和的窗口 ⇒ 计数即整表。窗口满了只会少算多出来的那些，不会让端点失败。
_BACKGROUND_TASK_WINDOW = 256


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


class HttpStatusSource:
    """把运行服务 / WS 中枢 / 后台任务注册表聚合成 :class:`StatusResponse`。

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
    ) -> None:
        self._version = version
        self._max_inflight_runs = max_inflight_runs
        self._run_service = run_service
        self._task_registry = task_registry
        self._cli_hub: Any | None = None
        self._notification_hub: Any | None = None

    def bind_ws(
        self,
        servers: Sequence[Any] = (),
        *,
        cli_hub: Any | None = None,
        notification_hub: Any | None = None,
    ) -> None:
        """绑定 WS 侧连接数的来源（必须在 ``build_ws_servers`` 之后调用）。

        ``cli_hub`` 是 CLI 旁路中枢（旁路未启用 / 因 listener 身份被跳过时为 ``None``，
        两种情况对 status 等价）；通知中枢显式传入优先，否则取 listener 上那一份。
        """
        self._cli_hub = cli_hub
        self._notification_hub = notification_hub if notification_hub is not None else _notification_hub_of(servers)

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
    )


def bind_status_source(
    source: HttpStatusSource | None,
    servers: Sequence[Any] = (),
    *,
    cli_hub: Any | None = None,
    notification_hub: Any | None = None,
) -> None:
    """把 WS 侧来源绑到状态来源上（``None`` 来源即空操作）。

    必须在 ``build_ws_servers`` **之后**调用：``HttpServer`` 先于 WS listener 构造，注入的是同一个
    source 对象，因此晚绑定对已建好的 app 同样可见。
    """
    if source is not None:
        source.bind_ws(servers, cli_hub=cli_hub, notification_hub=notification_hub)


__all__ = ["HttpStatusSource", "bind_status_source", "build_status_source"]
