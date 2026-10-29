"""Epic 56 Story 56-1：WS server 宿主（ws_host）纯逻辑面 + 分离判据。

与 e2e（``test_ws_e2e.py`` / ``test_cli_ws_e2e.py``）的分工：这里用替身与真实 listener 钉住
**配置契约、路由注册矩阵、双 server 分离判据与生命周期**；端到端语义（订阅/续传/cancel/ping/
限额/关停）随 56-1 迁入 e2e 文件（原 ``test_http_ws_e2e`` / ``test_http_cli_ws``，HttpServer
驱动 → WsServer 驱动）。
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from heagent.config import Settings
from heagent.config.catalog import RESOURCE_CEILINGS, classify, whitelist
from heagent.network.cli_event_hub import CliEventHub
from heagent.network.http_protocol import MAX_REQUEST_BYTES_FOR_MAX_PROMPT, RunOutcome
from heagent.network.http_server import HttpRunService, HttpServerConfig, _RunRecord
from heagent.network.ws_host import (
    RUNS_WS_PATH,
    WsServer,
    WsServerConfig,
    WsStartupError,
    build_ws_app,
)
from heagent.network.ws_protocol import WS_MAX_FRAME_BYTES, WS_PING_INTERVAL_SECONDS, WS_PING_TIMEOUT_SECONDS

websockets = pytest.importorskip("websockets")


class _BlockingExecutor:
    """先发三帧事件再挂起等待释放的替身运行器（供生命周期用例）。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = 0

    async def __call__(self, prompt: str, publisher: Any) -> RunOutcome:
        publisher.text("hello")
        publisher.tool_call("shell", "echo hello")
        publisher.tool_result("shell", "hello", is_error=False)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return RunOutcome(answer=prompt)


# ---- 配置契约（自 test_http_ws_config.py 迁入并按 D1 更名）----


def test_ws_config_defaults_are_synced_with_settings() -> None:
    """``WS_MAX_CONNECTIONS`` 设置与 ``WsServerConfig`` 默认值同源同校验（迁移自 54-2 契约）。"""
    settings_field = Settings.model_fields["ws_max_connections"]
    config_field = WsServerConfig.model_fields["ws_max_connections"]

    assert settings_field.default == config_field.default == 16
    assert Settings().ws_max_connections == 16
    assert WsServerConfig().ws_max_connections == 16
    for value in (0, -1):
        with pytest.raises(ValidationError):
            Settings(ws_max_connections=value)
        with pytest.raises(ValidationError):
            WsServerConfig(ws_max_connections=value)


def test_ws_server_config_defaults_pin_d1_topology() -> None:
    """默认 127.0.0.1:9901 是 D1 冻结值；port=0（随机端口）仅测试用。"""
    config = WsServerConfig()
    assert (config.host, config.port, config.ws_max_connections, config.shutdown_timeout) == (
        "127.0.0.1",
        9901,
        16,
        5.0,
    )
    with pytest.raises(ValidationError):
        WsServerConfig(port=0 - 1)
    with pytest.raises(ValidationError):
        WsServerConfig(shutdown_timeout=0)


def test_ws_limit_is_classified_as_read_only_listening_surface() -> None:
    result = classify("WS_MAX_CONNECTIONS")
    assert result.reason == "listening_surface"
    assert not result.writable
    assert "WS_MAX_CONNECTIONS" not in whitelist()
    assert "WS_MAX_CONNECTIONS" not in RESOURCE_CEILINGS
    assert classify("WS_HOST").reason == "listening_surface"
    assert classify("WS_PORT").reason == "listening_surface"


def test_ws_config_documented_in_env_example() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "WS_MAX_CONNECTIONS=16" in example
    assert "HTTP_WS_MAX_CONNECTIONS" not in example


def test_external_listener_keys_are_classified_as_read_only_listening_surface() -> None:
    """期二 D8/约束 6：新增的 WS_EXTERNAL_* 落在既有的 `WS_*` 模式组里，无需改分类规则。"""
    for key in (
        "WS_EXTERNAL_HOST",
        "WS_EXTERNAL_PORT",
        "WS_EXTERNAL_TLS_CERT_FILE",
        "WS_EXTERNAL_TLS_KEY_FILE",
        "WS_EXTERNAL_READONLY",
    ):
        result = classify(key)
        assert result.reason == "listening_surface", key
        assert not result.writable, key
        assert key not in whitelist(), key

    example = Path(".env.example").read_text(encoding="utf-8")
    for key in (
        "WS_EXTERNAL_HOST=",
        "WS_EXTERNAL_PORT=9002",
        "WS_EXTERNAL_TLS_CERT_FILE=",
        "WS_EXTERNAL_TLS_KEY_FILE=",
        "WS_EXTERNAL_READONLY=",
    ):
        assert key in example, key


def test_uvicorn_ws_options_moved_to_ws_host() -> None:
    """uvicorn WS 参数随 D1 迁移：ws_host 有、http_server 无（既有 54-2 契约换宿主）。"""
    ws_source = Path("src/heagent/network/ws_host.py").read_text(encoding="utf-8")
    http_source = Path("src/heagent/network/http_server.py").read_text(encoding="utf-8")
    assert "ws_max_size=WS_MAX_FRAME_BYTES" in ws_source
    assert "ws_ping_interval=WS_PING_INTERVAL_SECONDS" in ws_source
    assert "ws_ping_timeout=WS_PING_TIMEOUT_SECONDS" in ws_source
    assert WS_PING_INTERVAL_SECONDS == 15.0
    assert WS_PING_TIMEOUT_SECONDS == 20.0
    # 帧上限随 56-3 抬高到「装得下最大 prompt」（与 HTTP 请求体上限同源），不再是 64 KiB。
    assert WS_MAX_FRAME_BYTES == MAX_REQUEST_BYTES_FOR_MAX_PROMPT
    assert "ws_max_size=" not in http_source
    assert "ws_ping_interval=" not in http_source


# ---- CLI 旁路开关（自 54-2/55 契约迁入并按 D7 更名）----


def test_cli_bypass_is_off_by_default_and_documented() -> None:
    """默认关是契约：无认证的本机通道不该因为拆分就自己打开。"""
    assert Settings().ws_cli_bypass_enabled is False
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "WS_CLI_BYPASS_ENABLED=false" in example
    assert "HTTP_CLI_WS_ENABLED" not in example


def test_cli_bypass_switch_is_classified_as_read_only_listening_surface() -> None:
    result = classify("WS_CLI_BYPASS_ENABLED")
    assert result.reason == "listening_surface"
    assert not result.writable
    assert "WS_CLI_BYPASS_ENABLED" not in whitelist()


@pytest.mark.embedded_http_service
def test_embedded_service_only_attaches_a_hub_when_the_switch_is_on() -> None:
    """embedded_http_service 标记：要断言真实的 build_http_service（conftest 默认打桩）。"""
    from heagent.cli.http import build_http_service

    assert build_http_service(Settings(), executor=None).cli_hub is None
    hub = build_http_service(Settings(ws_cli_bypass_enabled=True), executor=None).cli_hub
    assert hub is not None
    # 额度取自同一个监听面旋钮：旁路只有一条流，故按 hub 计（与每 run 的 WS 额度是不同口径）。
    assert hub.max_connections == Settings().ws_max_connections


# ---- 路由注册矩阵与分离判据（D1 可执行判据）----


def _ws_config(**kwargs: Any) -> WsServerConfig:
    return WsServerConfig(port=0, shutdown_timeout=1, **kwargs)


def _http_config(**kwargs: Any) -> HttpServerConfig:
    return HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0, **kwargs)


async def _raw_status(port: int, path: str) -> int:
    """异步裸 HTTP GET 的状态行（异步用例禁同步 urllib：会阻塞事件循环自身造成假超时）。"""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        request = ("GET " + path + " HTTP/1.1\r\n" + "host: 127.0.0.1:%d\r\n" + "connection: close\r\n\r\n") % port
        writer.write(request.encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=3)
        return int(line.split()[1])
    finally:
        writer.close()


def _run_app_matrix(app: Any) -> tuple[int, int]:
    """对 app 各打一个 HTTP GET 与一次 WS 升级（ASGI 层），返回 (http_status, ws_close_code)。"""
    from starlette.testclient import TestClient

    client = TestClient(app)
    response = client.get("/api/health")
    try:
        with client.websocket_connect(RUNS_WS_PATH.replace("{run_id}", "nope")) as ws:
            ws.receive_json()
            close_code = -1
    except Exception as exc:  # TestClient 把「未 accept 即关」收敛为异常
        close_code = getattr(exc, "code", -1)
    return response.status_code, close_code


def test_ws_app_has_zero_http_surface() -> None:
    """D1 判据之 9901 侧：REST / 控制台页 / 健康检查全 404（Starlette 默认 404 文本）。"""
    config = _ws_config()
    for app in (
        build_ws_app(config),
        build_ws_app(config, run_service=HttpRunService(_http_config(), None)),
        build_ws_app(config, cli_hub=CliEventHub()),
    ):
        from starlette.testclient import TestClient

        client = TestClient(app)
        for path in ("/", "/api/health", "/api/runs", "/api/projects", "/api/session"):
            response = client.get(path)
            assert response.status_code == 404, path
            assert response.headers["content-type"].startswith("text/plain")


def test_http_app_no_longer_hosts_websocket_routes() -> None:
    from starlette.testclient import WebSocketDisconnect

    """D1 判据之 8766 侧（ASGI 层）：HTTP app 对任意 WS 升级路径不再 accept。"""
    from starlette.testclient import TestClient

    from heagent.network.http_server import HttpServer

    server = HttpServer(_http_config(), version="test")
    client = TestClient(server.app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/runs/nope/ws"):
        pass


@pytest.mark.asyncio
async def test_http_listener_rejects_ws_upgrade_over_real_tcp() -> None:
    """D1 判据之 8766 侧（真实 TCP）：升级被拒、未 accept。

    裁定①A：钉实测「非 101、未 accept」（Starlette 1.3.1 在真实 Uvicorn 下回 HTTP 403），
    不钉 brief 验收措辞的字面 404——判据本质是「8766 上 WS 不可达」。
    """
    service = HttpRunService(_http_config(), _BlockingExecutor())
    from heagent.network.http_server import HttpServer

    server = HttpServer(_http_config(), version="test", run_service=service)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
            async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/x/ws"):
                pass
        assert rejected.value.response.status_code == 403
        # 同一 listener 的 HTTP 面零改动：健康检查照常 200。
        assert await _raw_status(server.port, "/api/health") == 200
    finally:
        await server.close()
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_ws_listener_serves_no_http_api_over_real_tcp() -> None:
    """D1 判据之 9901 侧（真实 TCP）：REST/静态页/健康检查全 404，WS 端点可达。"""
    service = HttpRunService(_http_config(), _BlockingExecutor())
    hub = CliEventHub()
    server = WsServer(_ws_config(), run_service=service, cli_hub=hub)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    try:
        for path in ("/", "/api/health", "/api/runs", "/api/projects", "/web/app.js"):
            assert await _raw_status(server.port, path) == 404, path
        # 端点本体可达：无 run 记录时订阅被端点拒绝（unknown_run），而非路由 403。
        async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/x/ws") as ws:
            frame = json.loads(await ws.recv())
        assert frame["type"] == "error"
        assert frame["error"]["error"]["code"] == "unknown_run"
    finally:
        await server.close()
        await asyncio.wait_for(task, timeout=5)


# ---- WsServer 生命周期 ----


@pytest.mark.asyncio
async def test_ws_server_start_serves_and_closes_idempotently() -> None:
    server = WsServer(_ws_config(), run_service=HttpRunService(_http_config(), _BlockingExecutor()))
    await server.start()
    # 让 serve 协程先进入 main_loop 再 close：否则协程体在 _server 已置空后才首次被调度，
    # 会抛 RuntimeError（test_http_cli_ws 时代的同一坑）。
    task = asyncio.create_task(server.serve_forever())
    await asyncio.sleep(0)
    try:
        assert server.port > 0
        assert server.address == f"127.0.0.1:{server.port}"
        await server.close()
        await server.close()  # 幂等
    finally:
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_ws_server_close_alone_never_cancels_runs() -> None:
    """断线语义（D1 拆分后归属 WS 侧）：关 WS listener 只注销连接，绝不取消运行。

    运行的终结归 HTTP 侧的 service.close()（入口层编排 HTTP 先、WS 后）。
    """
    executor = _BlockingExecutor()
    service = HttpRunService(_http_config(), executor)
    server = WsServer(_ws_config(), run_service=service)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    record = await service.start_run("answer")
    try:
        await executor.started.wait()
        uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
        async with websockets.connect(uri):
            while service.ws_connection_count(record) == 0:
                await asyncio.sleep(0)
        await asyncio.sleep(0.1)
        await server.close()
        await asyncio.wait_for(task, timeout=5)
        assert record.status.value == "running"
        assert service.ws_connection_count(record) == 0
    finally:
        executor.release.set()
        await service.close()
        if not task.done():
            await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_ws_server_with_unreadable_tls_files_fails_loud() -> None:
    """TLS 配齐但文件读不到 ⇒ 启动显性失败（绝不静默降级成明文）。"""
    server = WsServer(
        _ws_config(
            tls_cert_file="tests/fixtures/ws_tls/does-not-exist.pem",
            tls_key_file="tests/fixtures/ws_tls/does-not-exist.key",
        )
    )
    with pytest.raises(WsStartupError):
        await server.start()


@pytest.mark.asyncio
async def test_ws_server_start_fails_loud_when_port_explicitly_taken() -> None:
    """显式端口被占 ⇒ WsStartupError（fail-loud，不静默换端口）。"""
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        taken = blocker.getsockname()[1]
        server = WsServer(WsServerConfig(host="127.0.0.1", port=taken, shutdown_timeout=1))
        with pytest.raises(WsStartupError):
            await server.start()


def test_ws_unavailable_diagnostic_is_logged_once(monkeypatch: pytest.MonkeyPatch, caplog: Any) -> None:
    """缺 websockets（ws_protocol_class=None）⇒ 安装诊断一条、且只记一次（spec I/O 矩阵行）。"""
    import logging

    server = WsServer(_ws_config())
    fake = type("FakeServer", (), {"config": type("FakeConfig", (), {"ws_protocol_class": None})()})()
    with caplog.at_level(logging.WARNING, logger="heagent.network.ws_host"):
        server._log_ws_unavailable_once(fake)
        server._log_ws_unavailable_once(fake)
    hints = [rec for rec in caplog.records if "ws_unavailable" in rec.getMessage()]
    assert len(hints) == 1
    assert "heagent[http]" in hints[0].getMessage()


# ---- 组合根装配（build_ws_server_config / 双 server 编排）----


def test_ws_app_registers_the_submit_route_only_with_a_run_service() -> None:
    """56-3：集合级端点 `/api/runs/ws` 与订阅端点同生同灭（都随 `run_service` 注入）。"""
    from starlette.routing import WebSocketRoute

    from heagent.network.ws_host import RUNS_SUBMIT_PATH, RUNS_WS_PATH

    def _paths(**kwargs: Any) -> list[str]:
        app = build_ws_app(_ws_config(), **kwargs)
        return [item.path for item in app.routes if isinstance(item, WebSocketRoute)]

    assert _paths() == []
    assert _paths(run_service=HttpRunService(_http_config(), None)) == [RUNS_SUBMIT_PATH, RUNS_WS_PATH]
    assert sorted(_paths(cli_hub=CliEventHub())) == ["/api/cli/ws"]
    # 集合级端点路径与订阅端点不冲突：段数不同，按 id 订阅仍走原路由。
    assert RUNS_SUBMIT_PATH == "/api/runs/ws"
    assert RUNS_WS_PATH == "/api/runs/{run_id}/ws"


def test_external_mode_app_never_registers_the_cli_bypass_route() -> None:
    """D9：即便调用方把 hub 传给对外 listener，`/api/cli/ws` 也不会注册（defense-in-depth）。"""
    from starlette.routing import WebSocketRoute

    app = build_ws_app(
        _ws_config(host="0.0.0.0", auth_token="s3cret"),
        run_service=HttpRunService(_http_config(), None),
        cli_hub=CliEventHub(),
    )
    paths = [item.path for item in app.routes if isinstance(item, WebSocketRoute)]
    assert paths == ["/api/runs/ws", "/api/runs/{run_id}/ws"]


def test_readonly_app_registers_only_the_subscription_route() -> None:
    """P2-A3：只读 listener 只有订阅路由——提交端点在路由表里就不存在（不是「注册了但拒绝」）。"""
    from starlette.routing import WebSocketRoute

    app = build_ws_app(
        _ws_config(host="0.0.0.0", auth_token="s3cret", readonly=True),
        run_service=HttpRunService(_http_config(), None),
        cli_hub=CliEventHub(),
    )
    paths = [item.path for item in app.routes if isinstance(item, WebSocketRoute)]
    assert paths == ["/api/runs/{run_id}/ws"]


def test_readonly_flag_reaches_the_external_listener_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """P2-A3：`WS_EXTERNAL_READONLY` / `external_readonly` 覆盖落到对外 listener，默认关。"""
    from heagent.cli.http import build_ws_servers

    monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
    default_servers, _ = build_ws_servers(_fixed_settings(ws_external_host="0.0.0.0"), cli_bypass=False)
    assert default_servers[1].config.readonly is False

    readonly_servers, _ = build_ws_servers(
        _fixed_settings(ws_external_host="0.0.0.0", ws_external_readonly=True), cli_bypass=False
    )
    assert readonly_servers[1].config.readonly is True

    # CLI 覆盖是三态（None = 用设置值），可把设置里的 True 显式关掉。
    override, _ = build_ws_servers(
        _fixed_settings(ws_external_host="0.0.0.0", ws_external_readonly=True),
        cli_bypass=False,
        external_readonly=False,
    )
    assert override[1].config.readonly is False


def test_local_mode_app_exposes_all_three_routes() -> None:
    from starlette.routing import WebSocketRoute

    app = build_ws_app(_ws_config(), run_service=HttpRunService(_http_config(), None), cli_hub=CliEventHub())
    paths = [item.path for item in app.routes if isinstance(item, WebSocketRoute)]
    assert paths == ["/api/runs/ws", "/api/runs/{run_id}/ws", "/api/cli/ws"]


def test_build_ws_server_config_maps_settings_and_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from heagent.cli.http import build_ws_server_config
    from heagent.network.ws_host import WsConfigError

    assert build_ws_server_config(Settings()).port == 9901
    assert build_ws_server_config(Settings(ws_port=9100)).port == 9100
    assert build_ws_server_config(Settings(), port=9200).port == 9200
    assert build_ws_server_config(Settings(), max_connections=7).ws_max_connections == 7
    assert build_ws_server_config(Settings(), shutdown_timeout=9).shutdown_timeout == 9.0
    # 56-2 D5：非回环绑定缺 token ⇒ fail-closed（不再静默产出一个「无认证对外」的配置）。
    with pytest.raises(WsConfigError):
        build_ws_server_config(Settings(), host="0.0.0.0")
    setting = tmp_path / "setting.md"
    setting.write_text("---\nWS_AUTH_TOKEN: s3cret\n---\n", encoding="utf-8")
    monkeypatch.setattr(Settings, "_user_setting_file", setting)
    external = build_ws_server_config(Settings(), host="0.0.0.0")
    assert external.host == "0.0.0.0"
    assert external.requires_auth is True


def test_build_ws_server_config_autofind_starts_from_ws_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """自动顺延的基准 = WS 端口（9901），不是 HTTP 端口——两条 listener 独立漂移。"""
    from heagent.cli.http import build_ws_server_config

    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        taken = blocker.getsockname()[1]
        monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "5")
        config = build_ws_server_config(Settings(ws_port=taken))
        assert config.port == taken + 1


def test_build_server_config_no_longer_carries_ws_knob() -> None:
    """D1：HTTP 配置面不再有 ws_max_connections（旋钮迁 WS 配置面）。"""
    from heagent.cli.http import build_server_config

    config = build_server_config(Settings())
    assert not hasattr(config, "ws_max_connections")


# ---- Epic 56 Story 56-4：WS 慢消费者判据（Epic 54 retro F5 的「判据 10」缺口）----


@pytest.mark.asyncio
async def test_ws_slow_consumer_is_dropped_with_a_sentinel_not_silently_skipped() -> None:
    """订阅者不消费 ⇒ 队列满时**结束该流**（哨兵入队 + 连接注销），绝不静默丢事件。

    端到端语义：客户端把事件读走的速度跟不上生产者的速度时，服务端不能无限堆积也不能静默跳过——
    它会结束那条流（``None`` 哨兵），客户端据 ``close`` 重连并带 ``?last_event_id=N`` 从 ring buffer
    补齐（越过窗口则收 ``resync_required``）。这条判据钉的是**服务端这一半**（WS 队列与 SSE 同语义）。
    """
    from heagent.network.http_protocol import RunEventKind

    record = _RunRecord("slow", "prompt", buffer_size=2)
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=record.subscriber_queue_size)
    assert record.try_add_ws_subscriber(queue, limit=4)

    record.append(RunEventKind.TEXT, text="a")
    record.append(RunEventKind.TEXT, text="b")
    assert queue.full()  # 队列与事件窗口同界（2）
    assert len(record.ws_subscribers) == 1  # 还没满到越界，订阅仍在

    # 第 3 条越过窗口 ⇒ 该订阅者被踢出并以哨兵结束其流。
    record.append(RunEventKind.TEXT, text="c")
    assert record.ws_subscribers == set()
    drained = [queue.get_nowait() for _ in range(queue.qsize())]
    assert drained[-1] is None  # 哨兵：消费端据此结束，而不是干等心跳
    assert all(item is None or item.seq <= 2 for item in drained)  # 不塞半截新事件
    # ring buffer 仍完整保留窗口内的事件：客户端重连可续传（游标 < 最老 → resync_required）。
    assert [event.seq for event in record.events] == [2, 3]
    assert record.oldest_seq == 2


@pytest.mark.asyncio
async def test_ws_and_sse_subscriber_pools_stay_independent_under_backpressure() -> None:
    """WS 被踢不影响同 run 的 SSE 订阅者（两套队列、两套额度、两条背压路径）。"""
    from heagent.network.http_protocol import RunEventKind

    record = _RunRecord("mixed", "prompt", buffer_size=2)
    sse_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=record.subscriber_queue_size)
    ws_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=record.subscriber_queue_size)
    assert record.try_add_subscriber(sse_queue, limit=4)
    assert record.try_add_ws_subscriber(ws_queue, limit=4)

    for text in ("a", "b", "c"):
        record.append(RunEventKind.TEXT, text=text)
        if text == "b":
            # SSE 侧持续消费，WS 侧停读：只有 WS 会被踢。
            sse_queue.get_nowait()
    assert record.subscribers == {sse_queue}
    assert record.ws_subscribers == set()
    assert sse_queue.qsize() > 0


# ---- 期二（Epic 56 D8/D10/D12）：双 listener 装配 ----


def _user_setting(tmp_path: Path, token: str = "s3cret") -> Path:
    """写一份带 token 的用户级 setting.md（对外 listener 的凭证真源）。"""
    path = tmp_path / "setting.md"
    path.write_text(f"---\nWS_AUTH_TOKEN: {token}\n---\n", encoding="utf-8")
    return path


def _fixed_settings(**overrides: Any) -> Settings:
    """端口固定（关自动顺延）的设置替身：断言 9901/9002 时不希望被真实占用影响。"""
    return Settings(http_port_auto_find_attempts=0, **overrides)


def test_build_ws_servers_defaults_to_a_single_local_listener() -> None:
    """D8：不配 WS_EXTERNAL_HOST ⇒ 与期一逐字等价（一个本地 listener、无旁路中枢）。"""
    from heagent.cli.http import build_ws_servers

    servers, hub = build_ws_servers(_fixed_settings(), cli_bypass=False)

    assert len(servers) == 1
    assert servers[0].config.mode == "local"
    assert servers[0].config.port == 9901
    assert hub is None


def test_build_ws_servers_adds_a_second_external_listener(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """D8/D9：显式配对外地址 ⇒ 两个 listener，且对外那条**不挂** CLI 旁路。"""
    from heagent.cli.http import build_ws_servers

    monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
    servers, hub = build_ws_servers(_fixed_settings(ws_external_host="0.0.0.0", ws_cli_bypass_enabled=True))

    assert [server.config.mode for server in servers] == ["local", "external"]
    assert servers[0].config.port == 9901
    assert (servers[1].config.host, servers[1].config.port) == ("0.0.0.0", 9002)
    # 旁路只挂本地 listener；对外 listener 的 cli_hub 恒为 None（终端内容不外溢）。
    assert hub is not None
    assert servers[0].cli_hub is hub
    assert servers[1].cli_hub is None


def test_external_listener_rejects_a_loopback_address() -> None:
    """D8：回环地址已由主 listener 承担 ⇒ 对外键取回环值属配置错误。"""
    from heagent.cli.http import build_ws_servers
    from heagent.network.ws_host import WsConfigError

    with pytest.raises(WsConfigError, match="non-loopback"):
        build_ws_servers(_fixed_settings(ws_external_host="127.0.0.1"), cli_bypass=False)


def test_external_listener_rejects_an_already_external_primary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """D8：主 listener 已对外时再配对外 listener = 两个对外入口，显式拒绝。"""
    from heagent.cli.http import build_ws_servers
    from heagent.network.ws_host import WsConfigError

    monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
    with pytest.raises(WsConfigError, match="loopback primary"):
        build_ws_servers(_fixed_settings(ws_host="0.0.0.0", ws_external_host="0.0.0.0"), cli_bypass=False)


def test_external_listener_fails_closed_without_a_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """D5 沿用：对外 listener 缺 token ⇒ 构造期 fail-closed，绝不产出无认证对外配置。"""
    from heagent.cli.http import build_ws_servers
    from heagent.network.ws_host import WsConfigError

    monkeypatch.setattr(Settings, "_user_setting_file", tmp_path / "missing.md")
    with pytest.raises(WsConfigError, match="WS_AUTH_TOKEN"):
        build_ws_servers(_fixed_settings(ws_external_host="0.0.0.0"), cli_bypass=False)


def test_external_tls_files_must_be_set_as_a_pair(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """D10：只给 cert 不给 key ⇒ fail-loud（绝不 A 的证书配 B 的私钥）。"""
    from heagent.cli.http import build_ws_servers
    from heagent.network.ws_host import WsConfigError

    monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
    with pytest.raises(WsConfigError, match="set together"):
        build_ws_servers(
            _fixed_settings(ws_external_host="0.0.0.0", ws_external_tls_cert_file="only-cert.pem"),
            cli_bypass=False,
        )


def test_external_listener_inherits_primary_tls_as_a_pair(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """D10：对外 TLS 不设 ⇒ 整对继承主 listener 的 WS_TLS_*。"""
    from heagent.cli.http import build_ws_servers

    monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
    servers, _hub = build_ws_servers(
        _fixed_settings(
            ws_external_host="0.0.0.0",
            ws_tls_cert_file="primary-cert.pem",
            ws_tls_key_file="primary-key.pem",
        ),
        cli_bypass=False,
    )

    assert servers[1].config.tls_cert_file == "primary-cert.pem"
    assert servers[1].config.tls_key_file == "primary-key.pem"
    assert servers[1].config.tls_enabled is True


def test_external_tls_pair_overrides_the_primary_pair(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """D10：对外自己配了 cert+key ⇒ 用自己那对；本地 listener 仍是主 listener 的那对。"""
    from heagent.cli.http import build_ws_servers

    monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
    servers, _hub = build_ws_servers(
        _fixed_settings(
            ws_external_host="0.0.0.0",
            ws_tls_cert_file="primary-cert.pem",
            ws_tls_key_file="primary-key.pem",
            ws_external_tls_cert_file="external-cert.pem",
            ws_external_tls_key_file="external-key.pem",
        ),
        cli_bypass=False,
    )

    assert servers[0].config.tls_cert_file == "primary-cert.pem"
    assert servers[1].config.tls_cert_file == "external-cert.pem"
    assert servers[1].config.tls_key_file == "external-key.pem"


def test_cli_bypass_is_skipped_on_an_external_primary_listener(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """D9 连带收紧：期一允许「单对外 + 旁路开」把终端事件流推给网络；期二起跳过并告警。"""
    import logging

    from heagent.cli.http import build_ws_servers

    monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
    caplog.set_level(logging.WARNING)
    servers, hub = build_ws_servers(_fixed_settings(ws_host="0.0.0.0", ws_cli_bypass_enabled=True))

    assert len(servers) == 1
    assert servers[0].config.mode == "external"
    assert hub is None
    assert servers[0].cli_hub is None
    assert "ws event=cli_bypass_skipped" in caplog.text


def test_cli_bypass_stays_on_the_local_listener_when_both_are_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """双监听 + 旁路开：中枢挂本地 listener，公告据此指向 9901 而不是对外那条。"""
    from heagent.cli.http import build_ws_servers

    monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
    servers, hub = build_ws_servers(_fixed_settings(ws_external_host="0.0.0.0", ws_cli_bypass_enabled=True))

    assert hub is not None
    hosts = [server for server in servers if server.cli_hub is hub]
    assert len(hosts) == 1
    assert hosts[0].config.mode == "local"


async def test_embedded_service_rolls_back_every_listener_when_the_external_one_fails() -> None:
    """D12：对外 listener 起不来 ⇒ 已启动的 HTTP 与本地 WS 全部回滚，不留半启动状态。"""
    from heagent.cli.http import EmbeddedHttpService
    from heagent.network.http_server import HttpServer

    with socket.socket() as blocker:
        blocker.bind(("0.0.0.0", 0))
        blocker.listen(1)
        taken = blocker.getsockname()[1]

        local = WsServer(_ws_config(host="127.0.0.1"))
        external = WsServer(WsServerConfig(host="0.0.0.0", port=taken, auth_token="s3cret", shutdown_timeout=1))
        service = EmbeddedHttpService(
            HttpServer(_http_config(host="127.0.0.1"), version="test"),
            (local, external),
        )

        with pytest.raises(WsStartupError):
            await service.start()

        http_port = service._http.port
        local_port = local.port

    # 回滚后两个端口都可被重新绑定（listener 真的关掉了，而不只是标记为 closed）。
    for port in (http_port, local_port):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
            probe.listen(1)
    await service.close()
