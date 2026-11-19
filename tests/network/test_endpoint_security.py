"""Story 67.7：每条对外端点都必须有「拒绝」判据（覆盖表 == 契约基线路由集合）。

真源：``tests/fixtures/contract_baselines/transport_routes.json`` 的 ``routes`` 数组
（``scripts/contract_snapshot.py`` 生成，与代码的同源性由 ``tests/test_contract_baselines.py`` 负责）。
本文件只回答一个问题：**这条路由有没有被安全用例覆盖**——覆盖表用集合相等断言钉住，
新增路由漏测即红，而不是靠「记得去补一条」。

三类用例的口径（本地模式**没有 HTTP 认证**，所以第一类落在外层防线上，而不是伪造一个 401）：

1. ``untrusted``：Host 伪装（DNS rebinding / 跨站）⇒ 403 ``origin_forbidden``。探针由路由 key
   **自动生成**（方法 + 路径 + 占位符填充），保证它确实打在 key 指定的那条路由上。
2. ``boundary``：越权与只读方法面——写路由的闸门（``loopback_required`` / ``confirm_required``），
   或只读路由上未注册的写方法（405 ``method_not_allowed``：「只读」是靠方法面收紧的）。
3. ``malformed``：畸形输入——坏 JSON / 超长字段 / 空 prompt / 畸形请求目标。拒绝必须发生在
   触碰注入 handler **之前**（另有断言：被拒请求不产生 handler 调用）。

WS 侧同理但有两点不同：认证门在对外 / 本地强制认证模式下真实存在（失败 = ``accept`` 之前的
close(1008)，不发错误信封），而「只读」在 WS 上是**路由可见性**（只读 listener 上提交端点压根
不注册，不是「注册了但拒绝」）。

边界口径：本文件只测传输层，不改端点实现；不引 fuzz 框架、不真开网络端口（ASGI 层直打）。
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.network.cli_event_hub import CliEventHub
from heagent.network.http_console_protocol import ConsoleOperationError
from heagent.network.http_protocol import HttpErrorCode, StatusResponse
from heagent.network.http_server import HttpRunService, HttpServerConfig, build_http_app
from heagent.network.notification_hub import NotificationHub
from heagent.network.ws_auth import AUTH_CLOSE_CODE
from heagent.network.ws_host import WsServerConfig, build_ws_app
from heagent.network.ws_protocol import (
    WS_CLOSE_POLICY,
    WS_CLOSE_TOO_LARGE,
    WS_MAX_INBOUND_CHARS,
)

_BASELINE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "contract_baselines" / "transport_routes.json"
_VERSION = "9.9.9"
_PORT = 9101
_WS_PORT = 9201
_LOOPBACK_CLIENT = ("127.0.0.1", 51000)
_FOREIGN_CLIENT = ("10.1.2.3", 51000)  # 非回环来源：写类端点的回环门判据
_FOREIGN_HOST = "evil.example"
_PROJECT_NAME_MAX = 64  # 镜像 MAX_PROJECT_NAME_CHARS；此处只需「超一截」的长字段
_SESSION_TITLE_MAX = 120  # 镜像 MAX_SESSION_TITLE_CHARS

_RouteKey = tuple[str, tuple[str, ...], str]


def _baseline_route_keys() -> set[_RouteKey]:
    """契约基线里的路由集合：``(listener, 排序后的方法, 路径)``。"""
    payload = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    return {(entry["listener"], tuple(sorted(entry["methods"])), entry["path"]) for entry in payload["routes"]}


# ── HTTP：探针与覆盖表 ──────────────────────────────────────────────


@dataclass(frozen=True)
class _Probe:
    """一条 HTTP 探针：怎么发 + 期望什么被拒。

    ``code=None`` 表示只钉状态码（当前无此形态；保留字段是为了将来「状态码正确但码未定」的过渡）。
    """

    method: str
    path: str
    status: int
    code: HttpErrorCode | None = None
    json: Any = None
    content: bytes | None = None
    client: tuple[str, int] = _LOOPBACK_CLIENT
    max_request_bytes: int | None = None


@dataclass(frozen=True)
class _HttpRouteCase:
    """一条 HTTP 路由的两类手写探针（``untrusted`` 由 key 自动生成，见 :func:`_untrusted_probe`）。"""

    boundary: _Probe
    malformed: _Probe


_PROJECT = "/api/projects/p1"
_SESSIONS = f"{_PROJECT}/sessions"
_SESSION = f"{_SESSIONS}/s1"
_NOT_ALLOWED = HttpErrorCode.METHOD_NOT_ALLOWED
_NO_SUCH_ENDPOINT = HttpErrorCode.NOT_FOUND

_HTTP_CASES: dict[_RouteKey, _HttpRouteCase] = {
    # 静态面：索引页与资源（资源名是**白名单查表**，不是路径拼接）。
    ("http", ("GET",), "/"): _HttpRouteCase(
        boundary=_Probe("POST", "/", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", "/missing-asset.js", 404, _NO_SUCH_ENDPOINT),
    ),
    # 原生目录选择：非项目作用域、在本机弹窗 ⇒ 必须回环来源。
    ("http", ("POST",), "/api/dialogs/pick-directory"): _HttpRouteCase(
        boundary=_Probe(
            "POST", "/api/dialogs/pick-directory", 403, HttpErrorCode.LOOPBACK_REQUIRED, client=_FOREIGN_CLIENT
        ),
        malformed=_Probe("POST", "/api/dialogs/pick-directory/extra", 404, _NO_SUCH_ENDPOINT),
    ),
    ("http", ("GET",), "/api/health"): _HttpRouteCase(
        boundary=_Probe("POST", "/api/health", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", "/api/health/extra", 404, _NO_SUCH_ENDPOINT),
    ),
    # 项目注册表：列表只读（写方法未注册），登记是本机变更（回环门）。
    ("http", ("GET",), "/api/projects"): _HttpRouteCase(
        boundary=_Probe("DELETE", "/api/projects", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", f"{_PROJECT}/extra", 404, _NO_SUCH_ENDPOINT),
    ),
    ("http", ("POST",), "/api/projects"): _HttpRouteCase(
        boundary=_Probe("POST", "/api/projects", 403, HttpErrorCode.LOOPBACK_REQUIRED, client=_FOREIGN_CLIENT),
        malformed=_Probe("POST", "/api/projects", 400, HttpErrorCode.INVALID_REQUEST, content=b"{not json"),
    ),
    # 移除项目：服务端确认闸门先于回环门（两者都要）。
    ("http", ("DELETE",), "/api/projects/{project_id}"): _HttpRouteCase(
        boundary=_Probe("DELETE", _PROJECT, 400, HttpErrorCode.CONFIRM_REQUIRED),
        # 确认闸门之后仍有回环门与未知 id：畸形（不存在的）id 只得到 404，不触碰文件系统。
        malformed=_Probe("DELETE", f"{_PROJECT}?confirm=true", 404, HttpErrorCode.UNKNOWN_PROJECT),
    ),
    # 重命名：**刻意没有**回环门（frame.md 已知缺口有裁定）⇒ 越权面只剩「能调什么方法」。
    ("http", ("PATCH",), "/api/projects/{project_id}"): _HttpRouteCase(
        boundary=_Probe("GET", _PROJECT, 405, _NOT_ALLOWED),
        malformed=_Probe(
            "PATCH", _PROJECT, 400, HttpErrorCode.INVALID_REQUEST, json={"name": "x" * (_PROJECT_NAME_MAX + 1)}
        ),
    ),
    ("http", ("GET",), "/api/projects/{project_id}/config"): _HttpRouteCase(
        boundary=_Probe("POST", f"{_PROJECT}/config", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", f"{_PROJECT}/config/extra", 404, _NO_SUCH_ENDPOINT),
    ),
    # 配置写入：改动落在服务机文件上 ⇒ 回环门 + fail-closed 写入。
    ("http", ("PUT",), "/api/projects/{project_id}/config"): _HttpRouteCase(
        boundary=_Probe(
            "PUT", f"{_PROJECT}/config", 403, HttpErrorCode.LOOPBACK_REQUIRED, json={}, client=_FOREIGN_CLIENT
        ),
        malformed=_Probe("PUT", f"{_PROJECT}/config", 400, HttpErrorCode.INVALID_REQUEST, content=b"{not json"),
    ),
    ("http", ("POST",), "/api/projects/{project_id}/runs"): _HttpRouteCase(
        boundary=_Probe("GET", f"{_PROJECT}/runs", 405, _NOT_ALLOWED),
        malformed=_Probe("POST", f"{_PROJECT}/runs", 400, HttpErrorCode.EMPTY_PROMPT, json={"prompt": "   "}),
    ),
    ("http", ("POST",), "/api/projects/{project_id}/sessions"): _HttpRouteCase(
        boundary=_Probe("PUT", _SESSIONS, 405, _NOT_ALLOWED),
        malformed=_Probe(
            "POST", _SESSIONS, 400, HttpErrorCode.INVALID_REQUEST, json={"title": "t" * (_SESSION_TITLE_MAX + 1)}
        ),
    ),
    # 列表：路径里的项目 id 是不透明串（未校验），未知 id 只能得到 404，不触碰文件系统。
    ("http", ("GET",), "/api/projects/{project_id}/sessions"): _HttpRouteCase(
        boundary=_Probe("DELETE", _SESSIONS, 405, _NOT_ALLOWED),
        malformed=_Probe("GET", _SESSIONS, 404, HttpErrorCode.UNKNOWN_PROJECT),
    ),
    # 删除会话：确认闸门（危险操作的服务端确认）。
    ("http", ("DELETE",), "/api/projects/{project_id}/sessions/{session_id}"): _HttpRouteCase(
        boundary=_Probe("DELETE", _SESSION, 400, HttpErrorCode.CONFIRM_REQUIRED),
        malformed=_Probe("DELETE", f"{_SESSIONS}/bad.id?confirm=true", 400, HttpErrorCode.INVALID_SESSION_ID),
    ),
    ("http", ("GET",), "/api/projects/{project_id}/sessions/{session_id}"): _HttpRouteCase(
        boundary=_Probe("PUT", _SESSION, 405, _NOT_ALLOWED),
        malformed=_Probe("GET", f"{_SESSIONS}/bad.id", 400, HttpErrorCode.INVALID_SESSION_ID),
    ),
    ("http", ("PATCH",), "/api/projects/{project_id}/sessions/{session_id}"): _HttpRouteCase(
        boundary=_Probe("PUT", _SESSION, 405, _NOT_ALLOWED),
        malformed=_Probe("PATCH", f"{_SESSIONS}/bad.id", 400, HttpErrorCode.INVALID_SESSION_ID, json={"title": "t"}),
    ),
    # 会话路径下多出来的段（``%2F`` 在路由前被解码）⇒ 兜底回稳定码，不暴露「路由存不存在」。
    (
        "http",
        ("DELETE", "GET", "PATCH", "POST"),
        "/api/projects/{project_id}/sessions/{session_id}/{extra:path}",
    ): _HttpRouteCase(
        boundary=_Probe("PUT", f"{_SESSION}/extra", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", f"{_SESSION}/extra", 400, HttpErrorCode.INVALID_SESSION_ID),
    ),
    # 运行 API：提交体是封闭模型（多一个字段就 400），取消/订阅只认已存在的 run。
    ("http", ("POST",), "/api/runs"): _HttpRouteCase(
        boundary=_Probe("GET", "/api/runs", 405, _NOT_ALLOWED),
        malformed=_Probe("POST", "/api/runs", 400, HttpErrorCode.EMPTY_PROMPT, json={"prompt": " "}),
    ),
    ("http", ("DELETE",), "/api/runs/{run_id}"): _HttpRouteCase(
        boundary=_Probe("GET", "/api/runs/run-1", 405, _NOT_ALLOWED),
        malformed=_Probe("DELETE", "/api/runs/unknown-run", 404, HttpErrorCode.UNKNOWN_RUN),
    ),
    ("http", ("GET",), "/api/runs/{run_id}/events"): _HttpRouteCase(
        boundary=_Probe("POST", "/api/runs/run-1/events", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", "/api/runs/unknown-run/events", 404, HttpErrorCode.UNKNOWN_RUN),
    ),
    ("http", ("GET",), "/api/session"): _HttpRouteCase(
        boundary=_Probe("POST", "/api/session", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", "/api/session/extra", 404, _NO_SUCH_ENDPOINT),
    ),
    # 进程状态：只读聚合，写方法未注册；多出来的段不落在任何路由上。
    ("http", ("GET",), "/api/status"): _HttpRouteCase(
        boundary=_Probe("POST", "/api/status", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", "/api/status/extra", 404, _NO_SUCH_ENDPOINT),
    ),
    ("http", ("GET",), "/api/tasks"): _HttpRouteCase(
        boundary=_Probe("POST", "/api/tasks", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", "/api/tasks/a/b", 404, _NO_SUCH_ENDPOINT),
    ),
    ("http", ("GET",), "/api/tasks/{task_id}"): _HttpRouteCase(
        boundary=_Probe("POST", "/api/tasks/task-1", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", "/api/tasks/unknown-task", 404, HttpErrorCode.NOT_FOUND),
    ),
    ("http", ("GET",), "/{asset}"): _HttpRouteCase(
        boundary=_Probe("POST", "/app.js", 405, _NOT_ALLOWED),
        malformed=_Probe("GET", "/unknown.js", 404, _NO_SUCH_ENDPOINT),
    ),
}

_PATH_FILLERS = (
    ("{project_id}", "p1"),
    ("{session_id}", "s1"),
    ("{run_id}", "run-1"),
    ("{task_id}", "task-1"),
    ("{extra:path}", "extra"),
    ("{asset}", "app.js"),
)


def _concrete_path(path: str) -> str:
    for placeholder, value in _PATH_FILLERS:
        path = path.replace(placeholder, value)
    return path


def _untrusted_probe(key: _RouteKey) -> _Probe:
    """由路由 key 生成的 Host 伪装探针（方法取该路由注册的第一个方法）。

    自动生成而不是手写：手写一份路径就等于多一处会与基线漂移的副本，而「探针打错路由」
    会让整张覆盖表变成空断言。
    """
    _listener, methods, path = key
    return _Probe(methods[0], _concrete_path(path), 403, HttpErrorCode.ORIGIN_FORBIDDEN)


class _TripwireConsole:
    """控制台 handler 替身：任何方法都回 ``unknown_project`` 并记录调用。

    Story 的作用是「拒绝发生在触碰 handler 之前」，所以替身不该伪造成功路径——一旦某条探针
    意外走到真实逻辑，它会显性变成 404 而不是静默 200；``calls`` 则用来断言 403/405 那些
    拒绝**没有任何副作用**。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _deny(self, name: str) -> None:
        self.calls.append(name)
        raise ConsoleOperationError(HttpErrorCode.UNKNOWN_PROJECT, "no such project")

    async def list_projects(self) -> Any:
        self._deny("list_projects")

    async def register_project(self, request: Any) -> Any:
        self._deny("register_project")

    async def rename_project(self, project_id: str, request: Any) -> Any:
        self._deny("rename_project")

    async def remove_project(self, project_id: str) -> None:
        self._deny("remove_project")

    async def project_has_inflight_run(self, project_id: str) -> bool:
        return False

    async def list_sessions(self, project_id: str) -> Any:
        self._deny("list_sessions")

    async def create_session(self, project_id: str, request: Any) -> Any:
        self._deny("create_session")

    async def get_session(self, project_id: str, session_id: str) -> Any:
        self._deny("get_session")

    async def rename_session(self, project_id: str, session_id: str, request: Any) -> Any:
        self._deny("rename_session")

    async def delete_session(self, project_id: str, session_id: str) -> None:
        self._deny("delete_session")

    async def start_project_run(self, project_id: str, request: Any) -> Any:
        self._deny("start_project_run")

    async def get_project_config(self, project_id: str) -> Any:
        self._deny("get_project_config")

    async def update_project_config(self, project_id: str, request: Any) -> Any:
        self._deny("update_project_config")

    async def pick_directory(self) -> Any:
        self._deny("pick_directory")


class _EmptyTaskSource:
    """任务进度来源替身：空注册表（只读投影，未知 id 就是 ``not_found``）。"""

    def list_tasks(self) -> list[Any]:
        return []

    def task(self, task_id: str) -> Any:
        return None


class _EmptyStatusSource:
    """状态来源替身：进程状态全零（只读投影，不依赖任何运行时对象）。"""

    def status(self) -> StatusResponse:
        return StatusResponse(version=_VERSION)


def _build_http_app(max_request_bytes: int | None = None) -> tuple[Any, _TripwireConsole]:
    """装齐四种注入（运行服务 / 控制台 / 任务来源 / 状态来源）的 HTTP app + 记录调用的 handler 替身。"""
    overrides: dict[str, Any] = {} if max_request_bytes is None else {"max_request_bytes": max_request_bytes}
    config = HttpServerConfig(port=_PORT, **overrides)
    console = _TripwireConsole()
    app = build_http_app(
        config,
        version=_VERSION,
        run_service=HttpRunService(config, None),
        console=console,
        tasks=_EmptyTaskSource(),
        status=_EmptyStatusSource(),
    )
    return app, console


@contextlib.asynccontextmanager
async def _http_client(
    max_request_bytes: int | None = None,
    *,
    source: tuple[str, int] = _LOOPBACK_CLIENT,
) -> AsyncIterator[tuple[httpx.AsyncClient, _TripwireConsole]]:
    """经 ASGI 层直打 HTTP app（不绑端口）；``source`` 是服务端看到的来源地址。"""
    app, console = _build_http_app(max_request_bytes)
    transport = httpx.ASGITransport(app=app, client=source)
    async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{_PORT}") as client:
        yield client, console


def _routes_of(app: Any) -> Any:
    """穿透安全头 / 访问日志 / 同源防线三层中间件，拿到 Starlette 实例的路由表。"""
    node = app
    while not hasattr(node, "routes"):
        node = getattr(node, "app", None)
        assert node is not None, "middleware chain has no Starlette app underneath"
    return node.routes


def _http_app_route_keys() -> set[_RouteKey]:
    """实测装配出来的 HTTP 路由集合（与基线对读，保证探针打的是文档里那 24 条）。"""
    from starlette.routing import Route

    app, _console = _build_http_app()
    keys: set[_RouteKey] = set()
    for route in _routes_of(app):
        if isinstance(route, Route):
            # Starlette 给 GET 自动挂 HEAD：那是实现细节，不是对外方法面。
            keys.add(("http", tuple(sorted(set(route.methods or ()) - {"HEAD"})), route.path))
    return keys


async def _call(client: httpx.AsyncClient, probe: _Probe) -> httpx.Response:
    headers = {"host": f"127.0.0.1:{_PORT}"}
    if probe.json is not None:
        return await client.request(probe.method, probe.path, json=probe.json, headers=headers)
    return await client.request(probe.method, probe.path, content=probe.content, headers=headers)


def _assert_rejected(response: httpx.Response, probe: _Probe) -> None:
    assert response.status_code == probe.status, f"{probe.method} {probe.path}: {response.text}"
    if probe.code is not None:
        assert response.json()["error"]["code"] == probe.code, response.text


def test_coverage_table_equals_the_transport_route_baseline() -> None:
    """覆盖表与基线路由集合**相等**：新增路由不补用例即红（缺一即红，多一也红）。"""
    covered = set(_HTTP_CASES) | set(_WS_CASES)
    assert covered == _baseline_route_keys()


def test_assembled_http_app_registers_the_baseline_routes() -> None:
    """装配面 == 基线：探针打的是文档化路由，而不是「碰巧存在的另一套」。"""
    assert _http_app_route_keys() == {key for key in _baseline_route_keys() if key[0] == "http"}


# ═══════════════════════════════════════════════════════════════════
# HTTP：三类拒绝用例（逐路由参数化）
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("route_key", sorted(_HTTP_CASES))
async def test_http_route_rejects_a_disguised_host(route_key: _RouteKey) -> None:
    """Host 伪装（DNS rebinding / 跨站）：403 且**不触碰** handler（无副作用）。"""
    probe = _untrusted_probe(route_key)
    async with _http_client() as (client, console):
        response = await client.request(
            probe.method,
            probe.path,
            headers={"host": _FOREIGN_HOST},
            json=probe.json if probe.method in {"POST", "PUT", "PATCH"} else None,
        )

    _assert_rejected(response, probe)
    assert console.calls == []


@pytest.mark.parametrize("route_key", sorted(_HTTP_CASES))
async def test_http_route_enforces_its_authorization_boundary(route_key: _RouteKey) -> None:
    """越权面：写路由的回环/确认闸门，或只读路由上未注册的写方法（405）。"""
    probe = _HTTP_CASES[route_key].boundary
    async with _http_client(source=probe.client) as (client, console):
        response = await _call(client, probe)

    _assert_rejected(response, probe)
    assert console.calls == []


@pytest.mark.parametrize("route_key", sorted(_HTTP_CASES))
async def test_http_route_rejects_malformed_input(route_key: _RouteKey) -> None:
    """畸形输入（坏 JSON / 超长字段 / 空 prompt / 畸形请求目标）必须被拒，绝不落到 handler。"""
    probe = _HTTP_CASES[route_key].malformed
    async with _http_client(max_request_bytes=probe.max_request_bytes) as (client, _console):
        response = await _call(client, probe)

    _assert_rejected(response, probe)


async def test_oversized_request_body_is_rejected_before_parsing() -> None:
    """请求体超限 ⇒ 413（有界读，未读完即拒）：不把「读多少」交给不可信客户端。"""
    async with _http_client(max_request_bytes=1024) as (client, console):
        response = await client.post(
            "/api/runs",
            content=b'{"prompt": "' + b"x" * 4096,
            headers={"host": f"127.0.0.1:{_PORT}"},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == HttpErrorCode.REQUEST_TOO_LARGE
    assert console.calls == []


# ── WS：探针与覆盖表 ────────────────────────────────────────────────


class WebSocketDisconnect(Exception):
    """连接结束信号。

    类名**是承重的**：``ws_server._next_command`` 按 ``type(exc).__name__ == "WebSocketDisconnect"``
    收敛对端断开（真实协议类来自 starlette，测试里不该为了这一条判据去拉它）。
    """


class _FakeWebSocket:
    """替身 WebSocket：记录 accept / 首个 close code / 出站帧，入站帧按脚本回放。"""

    def __init__(
        self,
        *,
        headers: list[tuple[bytes, bytes]] | None = None,
        client: tuple[str, int] = _LOOPBACK_CLIENT,
        path_params: dict[str, str] | None = None,
        inbound: list[str] | None = None,
    ) -> None:
        self.scope: dict[str, Any] = {
            "headers": headers if headers is not None else [(b"host", f"127.0.0.1:{_WS_PORT}".encode())],
            "client": client,
        }
        self.path_params = dict(path_params or {})
        self.query_params: dict[str, str] = {}
        self.accepted = False
        self.close_code: int | None = None
        self.sent: list[dict[str, Any]] = []
        self._inbound = list(inbound or [])

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        # 只记**首个** close code：端点拒绝时先 close(1008)，骨架收尾还会再 close() 一次，
        # 覆盖成 1000 就把「以什么理由被拒」抹掉了。
        if self.close_code is None:
            self.close_code = code

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def receive_text(self) -> str:
        if not self._inbound:
            raise WebSocketDisconnect
        return self._inbound.pop(0)


class _FakeRecord:
    """WS 订阅所需的 run 记录替身（无事件、非终态）。"""

    def __init__(self) -> None:
        self.events: tuple[Any, ...] = ()
        self.is_terminal = False
        self.subscriber_queue_size = 4
        self.ws_subscribers: set[Any] = set()

    def try_add_ws_subscriber(self, queue: Any, limit: int) -> bool:
        if len(self.ws_subscribers) >= limit:
            return False
        self.ws_subscribers.add(queue)
        return True


class _FakeRunService:
    """run 查询替身：只有 ``run-1`` 存在；关停标记恒 False。"""

    _closing = False

    def __init__(self) -> None:
        self.record = _FakeRecord()

    def run(self, run_id: str) -> Any:
        return self.record if run_id == "run-1" else None

    def needs_resync(self, record: Any, cursor: int | None) -> bool:  # noqa: ARG002 - 协议签名
        return False

    def register_ws(self, connection_id: str, run_id: str, websocket: Any) -> None:
        return None

    def unregister_ws(self, connection_id: str) -> None:
        return None

    async def cancel_run(self, run_id: str) -> Any:
        return None


@dataclass(frozen=True)
class _WsRouteCase:
    """WS 路由的可见性矩阵：只读 listener 与对外 listener 上是否注册。

    ``readonly`` / ``external`` 都为 True 的路由是「只读也得能看」的那两条（订阅与通知流）；
    提交端点只在非只读 listener 上存在；终端旁路只在本地 listener 上存在。
    """

    readonly_registered: bool
    external_registered: bool


_WS_CASES: dict[_RouteKey, _WsRouteCase] = {
    ("ws", (), "/api/cli/ws"): _WsRouteCase(readonly_registered=False, external_registered=False),
    ("ws", (), "/api/notifications/ws"): _WsRouteCase(readonly_registered=True, external_registered=True),
    ("ws", (), "/api/runs/ws"): _WsRouteCase(readonly_registered=False, external_registered=True),
    ("ws", (), "/api/runs/{run_id}/ws"): _WsRouteCase(readonly_registered=True, external_registered=True),
}


def _ws_app(*, external: bool = False, readonly: bool = False, auth_for_local: bool = False) -> Any:
    """装齐三个注入中枢的 WS app（本地 / 对外 / 只读三种身份）。"""
    if external:
        config = WsServerConfig(host="0.0.0.0", port=_WS_PORT, auth_token="s3cret", readonly=readonly)
    else:
        config = WsServerConfig(
            port=_WS_PORT,
            auth_token="s3cret" if auth_for_local else None,
            local_auth=auth_for_local,
            readonly=readonly,
        )
    return build_ws_app(
        config,
        run_service=_FakeRunService(),
        cli_hub=CliEventHub(),
        notification_hub=NotificationHub(),
    )


def _ws_endpoint(app: Any, path: str) -> Any:
    from starlette.routing import WebSocketRoute

    for route in app.routes:
        if isinstance(route, WebSocketRoute) and route.path == path:
            return route.endpoint
    raise AssertionError(f"route not registered: {path}")


def _ws_registered_paths(app: Any) -> set[str]:
    from starlette.routing import WebSocketRoute

    return {route.path for route in app.routes if isinstance(route, WebSocketRoute)}


def test_assembled_ws_apps_register_the_baseline_routes() -> None:
    """本地 listener 注册全部 4 条（与基线 ws 集合相等）。"""
    expected = {key[2] for key in _baseline_route_keys() if key[0] == "ws"}
    assert _ws_registered_paths(_ws_app()) == expected


@pytest.mark.parametrize("route_key", sorted(_WS_CASES))
def test_ws_route_visibility_matches_the_authorization_matrix(route_key: _RouteKey) -> None:
    """只读 / 对外 listener 的路由可见性：不给的能力是**不注册**，不是「注册了再拒绝」。"""
    case = _WS_CASES[route_key]
    path = route_key[2]
    assert (path in _ws_registered_paths(_ws_app(external=True, readonly=True))) is case.readonly_registered
    assert (path in _ws_registered_paths(_ws_app(external=True))) is case.external_registered


@pytest.mark.parametrize("route_key", sorted(_WS_CASES))
async def test_ws_route_rejects_a_missing_token_before_accept(route_key: _RouteKey) -> None:
    """缺 token ⇒ ``accept()`` 之前 close(1008) 且不发任何帧（不泄露错误信封）。

    正面控制用同一端点 + 正确 token 再打一次：否则「路由没注册」「端点崩了」也能骗过这条断言。
    """
    path = route_key[2]
    app = _ws_app(auth_for_local=True)
    endpoint = _ws_endpoint(app, path)

    rejected = _FakeWebSocket(path_params=_ws_path_params(path))
    await endpoint(rejected)
    assert rejected.accepted is False
    assert rejected.close_code == AUTH_CLOSE_CODE == WS_CLOSE_POLICY
    assert rejected.sent == []

    accepted = _FakeWebSocket(
        headers=[
            (b"host", f"127.0.0.1:{_WS_PORT}".encode()),
            (b"authorization", b"Bearer s3cret"),
        ],
        path_params=_ws_path_params(path),
    )
    await endpoint(accepted)
    assert accepted.accepted is True


@pytest.mark.parametrize("route_key", sorted(_WS_CASES))
async def test_ws_route_rejects_a_malformed_command_frame(route_key: _RouteKey) -> None:
    """非 JSON 命令帧 ⇒ ``invalid_request`` 错误帧 + close(1008)（不断言内部异常）。"""
    path = route_key[2]
    websocket = _FakeWebSocket(path_params=_ws_path_params(path), inbound=["not json"])
    await _ws_endpoint(_ws_app(), path)(websocket)

    assert websocket.accepted is True
    assert websocket.close_code == WS_CLOSE_POLICY
    assert [frame["type"] for frame in websocket.sent] == ["error"]
    assert websocket.sent[0]["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST


async def test_oversized_ws_frame_is_closed_without_parsing() -> None:
    """超长帧 ⇒ 1009 关闭、不发错误帧（长度检查先于 JSON 解析，不给解析器喂巨型串）。"""
    websocket = _FakeWebSocket(inbound=["x" * (WS_MAX_INBOUND_CHARS + 1)])
    await _ws_endpoint(_ws_app(), "/api/runs/ws")(websocket)

    assert websocket.accepted is True
    assert websocket.close_code == WS_CLOSE_TOO_LARGE
    assert websocket.sent == []


def _ws_path_params(path: str) -> dict[str, str]:
    return {"run_id": "run-1"} if "{run_id}" in path else {}
