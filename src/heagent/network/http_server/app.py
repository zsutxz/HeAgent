"""ASGI 应用装配：健康检查 + 运行/控制台路由 + 包内静态页 + 安全头（Story 62.1 自 ``network/http_server.py`` 拆出）。

路由注册与路径常量**同模块**：``scripts/contract_snapshot.py`` 的路由快照按模块级字符串赋值
解析 ``Route(<常量>)``，两者分开会让快照里的 ``path_expr`` 解析失效。

``__all__`` 显式列出包内公开名：包级再导出（``__init__.py``）与 exception 快照
（``scripts/contract_snapshot.py``）都以「定义模块的 ``__all__``」为收录依据。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from heagent.network.http_protocol import HealthResponse, HttpErrorCode

# 别名导入保住 monkeypatch 缝（原单文件的缝导入随 ``build_http_app`` 搬入本模块）：
# ``/`` 与 ``/{asset}`` 静态资源响应经 :func:`read_web_asset` 读包内资源，
# 测试 patch ``heagent.network.http_server.app.read_web_asset``。
from heagent.network.optional_deps import require_module as _require_module
from heagent.network.origin import allowed_hosts, allowed_ports
from heagent.pub.safe_logging import safe_log

from .assets import _INDEX_ASSET, _WEB_ASSETS, read_web_asset
from .endpoints_console import (
    _build_config_endpoint,
    _build_dialog_endpoint,
    _build_project_endpoints,
    _build_session_endpoints,
)
from .endpoints_run import _build_run_endpoints
from .endpoints_status import _build_status_endpoint
from .endpoints_tasks import _build_task_endpoints
from .metrics import RequestMetrics
from .middleware import (
    _SECURITY_HEADERS,
    _AccessLogMiddleware,
    _OriginGuardMiddleware,
    _SecurityHeadersMiddleware,
)
from .pipeline import _json_error

if TYPE_CHECKING:
    from starlette.types import ASGIApp

    from heagent.network.http_console_protocol import ConsoleHandler

    from .config import HttpServerConfig
    from .endpoints_run import RunHistorySource
    from .endpoints_status import StatusSource
    from .endpoints_tasks import TaskProgressSource
    from .service import HttpRunService

__all__ = ["build_http_app"]

logger = logging.getLogger("heagent.network.http_server")

_HEALTH_PATH = "/api/health"
_RUNS_PATH = "/api/runs"
_RUN_DETAIL_PATH = "/api/runs/{run_id}"
_RUN_EVENTS_PATH = "/api/runs/{run_id}/events"
_SESSION_PATH = "/api/session"
_PROJECTS_PATH = "/api/projects"
_PROJECT_PATH = "/api/projects/{project_id}"
_PROJECT_SESSIONS_PATH = "/api/projects/{project_id}/sessions"
_PROJECT_SESSION_PATH = "/api/projects/{project_id}/sessions/{session_id}"
# 会话路径下**多出来的段**（``%2F`` 在路由前被解码 ⇒ ``../`` 之类会落成多段）：兜底回
# ``invalid_session_id``（AC7），而不是让「路由存不存在」的差异变成 404。
_PROJECT_SESSION_EXTRA_PATH = "/api/projects/{project_id}/sessions/{session_id}/{extra:path}"
_PROJECT_RUNS_PATH = "/api/projects/{project_id}/runs"
_PROJECT_CONFIG_PATH = "/api/projects/{project_id}/config"
# 非项目作用域的控制台端点：在**服务端所在机器**弹原生目录选择窗口。
_DIALOG_PICK_PATH = "/api/dialogs/pick-directory"
# 后台任务进度：进程内注册表的只读投影（列表 + 单条），数据由入口层注入。
_TASKS_PATH = "/api/tasks"
_TASK_DETAIL_PATH = "/api/tasks/{task_id}"
# 进程状态聚合：运行态 / 连接数 / 后台任务条数的只读投影，数据由入口层注入。
_STATUS_PATH = "/api/status"


def _attach_metrics(source: Any | None) -> RequestMetrics:
    """新建本 app 的请求计数载体，并在来源支持时挂上去（鸭子契约，不加必填 Protocol 方法）。"""
    metrics = RequestMetrics()
    attach = getattr(source, "attach_metrics", None)
    if attach is not None:
        attach(metrics)
    return metrics


def build_http_app(
    config: HttpServerConfig,
    *,
    version: str,
    run_service: HttpRunService | None = None,
    console: ConsoleHandler | None = None,
    tasks: TaskProgressSource | None = None,
    history: RunHistorySource | None = None,
    status: StatusSource | None = None,
) -> ASGIApp:
    """构造网页入口的 ASGI 应用（健康检查 + 运行 API/SSE + 包内静态页 + 安全头）。

    ``version`` 由入口层注入（来自 ``heagent.__version__``）：传输层因此不需要知道版本从哪来，
    也不需要在导入期触碰包元数据。``run_service`` 是**注入的运行服务**（AD-1 的接缝）——为 ``None``
    时不注册 ``/api/runs*``、``/api/session`` 或 ``/api/projects*``（那些路径回 404），Story 49-1 的用法因此保持不变。
    ``tasks`` 是**注入的任务进度来源**（同一条接缝）：为 ``None`` 时不注册 ``/api/tasks*``
    （那些路径回 404），生产者侧注册表由入口层持有并注入。
    ``history`` 是**注入的历史回放来源**（A35）：进程内没有该 run 的记录时（重启后），
    ``GET /api/runs/<id>/events`` 用它回放 rollout 里的事件；``None`` = 维持 404。
    ``status`` 是**注入的状态来源**（同一族接缝）：为 ``None`` 时不注册 ``/api/status``（回 404），
    进程内运行态由入口层聚合成封闭模型后交进来。
    错误响应一律走 :func:`_json_error`，异常细节只进服务端日志。
    Epic 56 D1：WS 路由已全部迁出本 app（宿主 = ``network/ws_host.py``），本 app 只剩纯 HTTP+SSE。
    """
    applications = _require_module("starlette.applications")
    responses = _require_module("starlette.responses")
    routing = _require_module("starlette.routing")
    starlette_exceptions = _require_module("starlette.exceptions")

    async def health(request: Any) -> Any:  # noqa: ARG001 - 端点的固定签名
        return responses.JSONResponse(
            HealthResponse(version=version).model_dump(mode="json"),
        )

    def asset_response(name: str) -> Any:
        """读包内资源并回响应；资源缺失（如 wheel 漏打）时回稳定 500，不吐 traceback。"""
        try:
            payload = read_web_asset(name)
        except (KeyError, OSError, ModuleNotFoundError):
            safe_log(logger, logging.ERROR, "http event=asset_unavailable asset=%s", name)
            return _json_error(
                responses,
                HttpErrorCode.SERVER_ERROR,
                "built-in page resource is unavailable",
                status_code=500,
            )
        return responses.Response(
            payload,
            media_type=_WEB_ASSETS[name],
            headers={"cache-control": "no-cache"},
        )

    async def index(request: Any) -> Any:  # noqa: ARG001 - 端点的固定签名
        return asset_response(_INDEX_ASSET)

    async def asset(request: Any) -> Any:
        name = str(request.path_params.get("asset", ""))
        if name not in _WEB_ASSETS:
            return _json_error(responses, HttpErrorCode.NOT_FOUND, "no such resource", status_code=404)
        return asset_response(name)

    async def http_exception(request: Any, exc: Any) -> Any:  # noqa: ARG001
        status = getattr(exc, "status_code", 500)
        # 状态码保持**字面量**：契约基线（transport_errors.json）按调用点字面量采集
        # status_source=call_site_literal，抽常量会让静态扫描失去来源（Story 62.7 实测）。
        if status == 405:  # noqa: PLR2004
            return _json_error(
                responses,
                HttpErrorCode.METHOD_NOT_ALLOWED,
                "method not allowed for this endpoint",
                status_code=405,
            )
        if status == 404:  # noqa: PLR2004
            return _json_error(responses, HttpErrorCode.NOT_FOUND, "no such endpoint", status_code=404)
        return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=int(status))

    async def server_error(request: Any, exc: Any) -> Any:  # noqa: ARG001
        # 详细 traceback 只进服务端 error 日志；客户端拿固定文案。
        safe_log(logger, logging.ERROR, "http event=request_error", exc_info=True)
        return _json_error(responses, HttpErrorCode.SERVER_ERROR, "internal server error", status_code=500)

    routes = [
        routing.Route(_HEALTH_PATH, endpoint=health, methods=["GET"]),
        routing.Route("/", endpoint=index, methods=["GET"]),
    ]
    if run_service is not None:
        create_run, run_events, cancel_run, session_endpoint = _build_run_endpoints(
            responses, config, run_service, history
        )
        routes.extend(
            [
                routing.Route(_RUNS_PATH, endpoint=create_run, methods=["POST"]),
                routing.Route(_RUN_EVENTS_PATH, endpoint=run_events, methods=["GET"]),
                routing.Route(_RUN_DETAIL_PATH, endpoint=cancel_run, methods=["DELETE"]),
                routing.Route(_SESSION_PATH, endpoint=session_endpoint, methods=["GET"]),
            ]
        )
    if console is not None:
        list_projects, register_project, rename_project, remove_project = _build_project_endpoints(
            responses, console, config
        )
        (
            list_sessions,
            create_session,
            get_session,
            rename_session,
            delete_session,
            create_project_run,
            session_malformed,
        ) = _build_session_endpoints(responses, console, config)
        project_config, project_config_write = _build_config_endpoint(responses, console, config)
        pick_directory = _build_dialog_endpoint(responses, console)
        routes.extend(
            [
                routing.Route(_PROJECTS_PATH, endpoint=list_projects, methods=["GET"]),
                routing.Route(_PROJECTS_PATH, endpoint=register_project, methods=["POST"]),
                routing.Route(_PROJECT_PATH, endpoint=rename_project, methods=["PATCH"]),
                routing.Route(_PROJECT_PATH, endpoint=remove_project, methods=["DELETE"]),
                routing.Route(_PROJECT_SESSIONS_PATH, endpoint=list_sessions, methods=["GET"]),
                routing.Route(_PROJECT_SESSIONS_PATH, endpoint=create_session, methods=["POST"]),
                routing.Route(_PROJECT_SESSION_PATH, endpoint=get_session, methods=["GET"]),
                routing.Route(_PROJECT_SESSION_PATH, endpoint=rename_session, methods=["PATCH"]),
                routing.Route(_PROJECT_SESSION_PATH, endpoint=delete_session, methods=["DELETE"]),
                # 兜底路由**必须在具体会话路由之后**注册：先匹配到具体的单段 id 语义。
                routing.Route(
                    _PROJECT_SESSION_EXTRA_PATH,
                    endpoint=session_malformed,
                    methods=["GET", "POST", "PATCH", "DELETE"],
                ),
                routing.Route(_PROJECT_RUNS_PATH, endpoint=create_project_run, methods=["POST"]),
                routing.Route(_PROJECT_CONFIG_PATH, endpoint=project_config, methods=["GET"]),
                # 写入通道：与 GET 同一路径、不同方法（Starlette 按 method 匹配）。
                routing.Route(_PROJECT_CONFIG_PATH, endpoint=project_config_write, methods=["PUT"]),
                # 原生目录选择：非项目作用域 + 回环门 + 单在途（入口层持有）。
                routing.Route(_DIALOG_PICK_PATH, endpoint=pick_directory, methods=["POST"]),
            ]
        )
    if tasks is not None:
        list_tasks, get_task = _build_task_endpoints(responses, tasks)
        routes.extend(
            [
                routing.Route(_TASKS_PATH, endpoint=list_tasks, methods=["GET"]),
                routing.Route(_TASK_DETAIL_PATH, endpoint=get_task, methods=["GET"]),
            ]
        )
    if status is not None:
        get_status = _build_status_endpoint(responses, status)
        routes.append(routing.Route(_STATUS_PATH, endpoint=get_status, methods=["GET"]))
    routes.append(routing.Route("/{asset}", endpoint=asset, methods=["GET"]))
    app = applications.Starlette(
        routes=routes,
        exception_handlers={
            starlette_exceptions.HTTPException: http_exception,
            Exception: server_error,
        },
    )
    # 包装顺序（由外到内）：安全头（保证连被拒的响应也带）→ 请求观测 → 同源防线 → 应用路由。
    guarded = _OriginGuardMiddleware(app, hosts=allowed_hosts(config), ports=allowed_ports(config))
    logged = _AccessLogMiddleware(guarded, _attach_metrics(status))
    return _SecurityHeadersMiddleware(logged, _SECURITY_HEADERS)
