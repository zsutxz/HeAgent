"""``GET /api/status`` 的传输层测试：进程自身状态的只读聚合投影。

覆盖 Story 71.1 的 I/O 与边界矩阵：happy path / 在途 run / 终态 run / 三条 WS 流计数增减 /
来源抛错收敛 / 来源缺失不注册。全部经 ASGI 层直打 ``build_http_app``（不绑端口），在途 run 用
阻塞 executor 制造。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("starlette")

import httpx
from pydantic import ValidationError

from heagent.cli.http_status import HttpStatusSource
from heagent.network.cli_event_hub import CliEventHub
from heagent.network.http_protocol import (
    HTTP_SCHEMA_VERSION,
    HTTP_SERVICE_NAME,
    HttpErrorCode,
    RunOutcome,
    RunStatus,
    RunStatusCounts,
    StatusResponse,
    WsConnectionCounts,
)
from heagent.network.http_server import HttpRunService, HttpServerConfig, build_http_app
from heagent.network.notification_hub import NotificationHub

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_VERSION = "9.9.9"
_BASE_URL = "http://127.0.0.1:8766"


def _config(**overrides: Any) -> HttpServerConfig:
    return HttpServerConfig(**{"port": 0, **overrides})


def _blocking_executor(gate: asyncio.Event):
    """阻塞在 ``gate`` 上的 executor（模拟「跑到一半的运行」）。"""

    async def run(prompt: str, publisher: Any) -> RunOutcome:  # noqa: ARG001 - executor 的固定签名
        await gate.wait()
        return RunOutcome(answer="late")

    return run


async def _drain(service: HttpRunService, *, budget: float = 5.0) -> None:
    """等在途运行自己结束（避免测试结束时留悬挂任务 / 未归还名额）。"""
    deadline = asyncio.get_running_loop().time() + budget
    while service.active_runs and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)


class _CountingTaskRegistry:
    """任务注册表替身：``snapshot(limit=...)`` 返回 ``count`` 个占位条目（只读计数用）。"""

    def __init__(self, count: int = 0) -> None:
        self.count = count

    def snapshot(self, *, limit: int) -> list[Any]:
        return [object()] * min(self.count, limit)


class _BrokenSource:
    """抛异常的来源替身：异常文本里刻意带内部细节（响应体绝不该回吐它们）。"""

    def status(self) -> StatusResponse:
        raise RuntimeError("C:/internal/secret/workspace")


@contextlib.asynccontextmanager
async def _client(source: Any, *, run_service: HttpRunService | None = None) -> AsyncIterator[httpx.AsyncClient]:
    app = build_http_app(_config(), version=_VERSION, run_service=run_service, status=source)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=_BASE_URL) as client:
        yield client


def _source(
    *,
    run_service: HttpRunService | None = None,
    task_registry: Any | None = None,
    max_inflight_runs: int = 1,
) -> HttpStatusSource:
    return HttpStatusSource(
        version=_VERSION,
        max_inflight_runs=max_inflight_runs,
        run_service=run_service,
        task_registry=task_registry,
    )


# ═══════════════════════════════════════════════════════════════════
# HAPPY_PATH：字段集合与取值
# ═══════════════════════════════════════════════════════════════════


class TestStatusShape:
    async def test_happy_path_returns_the_closed_field_set(self) -> None:
        service = HttpRunService(_config(), None)
        async with _client(_source(run_service=service), run_service=service) as client:
            response = await client.get("/api/status")

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == set(StatusResponse.model_fields)
        assert payload["service"] == HTTP_SERVICE_NAME == "heagent-http"
        assert payload["schema_version"] == HTTP_SCHEMA_VERSION == "1"
        assert payload["version"] == _VERSION
        assert payload["active_runs"] == 0
        assert payload["max_inflight_runs"] == 1
        assert payload["run_records"] == 0
        # 分布字段名与 ``RunStatus`` 取值逐字一致（漏一档就是这里红）。
        assert payload["run_status"] == dict.fromkeys((status.value for status in RunStatus), 0)
        assert set(payload["run_status"]) == set(RunStatusCounts.model_fields)
        assert payload["ws_connections"] == dict.fromkeys(WsConnectionCounts.model_fields, 0)
        assert payload["background_tasks"] == 0

    async def test_response_and_counts_are_field_closed(self) -> None:
        """多一个字段即失败：状态响应不接受任何计划外的键（不泄露内部信息）。"""
        base = StatusResponse(version=_VERSION).model_dump(mode="json")
        with pytest.raises(ValidationError):
            StatusResponse.model_validate({**base, "workspace": "C:/secret"})
        with pytest.raises(ValidationError):
            RunStatusCounts.model_validate({"running": 0, "aborted": 1})
        with pytest.raises(ValidationError):
            WsConnectionCounts.model_validate({"runs": -1})

    async def test_counts_cover_the_polled_registry(self) -> None:
        async with _client(_source(task_registry=_CountingTaskRegistry(count=3))) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["background_tasks"] == 3

    async def test_runs_are_zero_without_a_run_service(self) -> None:
        """没有注入运行服务时（健康检查 + 静态页形态）运行态报 0：没有服务就不可能有 run。"""
        async with _client(_source()) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["active_runs"] == 0
        assert payload["run_records"] == 0
        assert payload["run_status"] == dict.fromkeys((status.value for status in RunStatus), 0)
        assert payload["ws_connections"]["runs"] == 0
        # 名额也报 0：`/api/runs` 未注册时不存在「还有几个空位」这回事。
        assert payload["max_inflight_runs"] == 0


# ═══════════════════════════════════════════════════════════════════
# RUNNING_RUN / TERMINAL_RUN：在途与终态分布
# ═══════════════════════════════════════════════════════════════════


class TestRunCounts:
    async def test_inflight_run_then_terminal_run(self) -> None:
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        try:
            async with _client(_source(run_service=service), run_service=service) as client:
                await service.start_run("hello")
                running = (await client.get("/api/status")).json()
                gate.set()
                await _drain(service)
                finished = (await client.get("/api/status")).json()
        finally:
            gate.set()
            await service.close()

        assert running["active_runs"] == 1
        assert running["run_records"] == 1
        assert running["run_status"]["running"] == 1
        assert sum(running["run_status"].values()) == running["run_records"]

        assert finished["active_runs"] == 0
        assert finished["run_status"]["running"] == 0
        assert finished["run_status"]["completed"] == 1
        assert sum(finished["run_status"].values()) == finished["run_records"]

    async def test_cancelled_run_lands_in_the_cancelled_bucket(self) -> None:
        """取消的运行必须落进 ``cancelled`` 桶——桶间错配时 ``sum(...)`` 断言天然看不出来。"""
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        try:
            record = await service.start_run("slow")
            async with _client(_source(run_service=service), run_service=service) as client:
                assert (await client.get("/api/status")).json()["run_status"]["running"] == 1
                await service.cancel_run(record.run_id)
                await _drain(service)
                payload = (await client.get("/api/status")).json()
        finally:
            gate.set()
            await service.close()

        assert payload["run_status"] == {
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 1,
            "timed_out": 0,
        }
        assert sum(payload["run_status"].values()) == payload["run_records"] == 1


# ═══════════════════════════════════════════════════════════════════
# 装配级：listener 透传与入口层接线（漏了就静默 404 / 计数恒 0）
# ═══════════════════════════════════════════════════════════════════


class TestAssembly:
    async def test_listener_passes_the_source_through(self) -> None:
        """``HttpServer(status=...)`` 必须把来源透传给 app（否则路由静默缺失）。"""
        from heagent.network.http_server import HttpServer

        server = HttpServer(_config(), version=_VERSION, status=_source())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url=_BASE_URL) as client:
            response = await client.get("/api/status")

        assert response.status_code == 200
        assert response.json()["version"] == _VERSION

    @pytest.mark.embedded_http_service
    async def test_embedded_service_wires_the_source_and_late_binds_ws(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """内嵌入口：端点必须真的注册，且 ``build_ws_servers`` 之后的 WS 计数要能读到。

        两处接线各防一件事：``HttpServer(... status=…)`` 漏传 ⇒ 恒 404；``bind_status_source``
        漏调 ⇒ ``ws_connections.cli`` 恒 0。
        """
        from heagent.cli.http import build_http_service
        from heagent.config import Settings

        monkeypatch.chdir(tmp_path)
        settings = Settings(_env_file=None, http_enabled=True, ws_enabled=True, ws_cli_bypass_enabled=True)

        async def _never_runs(prompt: str, publisher: Any, *, session_id: str | None = None) -> RunOutcome:  # noqa: ARG001
            raise AssertionError("本用例不发起运行")

        # 给一个 executor 才有运行服务：否则 `/api/runs` 与名额都不注册（那是另一种合法形态）。
        service = build_http_service(settings, executor=_never_runs, http_enabled=True, ws_enabled=True)
        http_server = service._http
        assert http_server is not None
        cli_hub = service.cli_hub
        assert cli_hub is not None, "旁路开启时中枢必须存在（否则测不到晚绑定）"

        transport = httpx.ASGITransport(app=http_server.app)
        base_url = f"http://127.0.0.1:{http_server.config.port}"
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            wired = await client.get("/api/status")
            assert wired.status_code == 200
            assert wired.json()["max_inflight_runs"] >= 1

            cli_hub.register_ws("c1", "run-1", object())
            try:
                bound = (await client.get("/api/status")).json()
            finally:
                cli_hub.unregister_ws("c1")

        assert bound["ws_connections"]["cli"] == 1


# ═══════════════════════════════════════════════════════════════════
# WS_SUBSCRIBED：三条流各自计数、断开各自回 0
# ═══════════════════════════════════════════════════════════════════


class TestWsConnectionCounts:
    async def test_each_stream_counts_and_releases_its_connections(self) -> None:
        service = HttpRunService(_config(), None)
        cli_hub = CliEventHub()
        notification_hub = NotificationHub()
        source = _source(run_service=service)
        source.bind_ws((), cli_hub=cli_hub, notification_hub=notification_hub)

        service.register_ws("c1", "run-1", object())
        cli_hub.register_ws("c1", "run-1", object())
        notification_hub.register_ws("c1", "stream-1", object())
        async with _client(source, run_service=service) as client:
            connected = (await client.get("/api/status")).json()

        service.unregister_ws("c1")
        cli_hub.unregister_ws("c1")
        notification_hub.unregister_ws("c1")
        async with _client(source, run_service=service) as client:
            released = (await client.get("/api/status")).json()

        assert connected["ws_connections"] == {"runs": 1, "cli": 1, "notifications": 1}
        assert released["ws_connections"] == {"runs": 0, "cli": 0, "notifications": 0}

    async def test_notification_hub_is_taken_from_the_listeners_once(self) -> None:
        """同一份通知中枢挂在每个 listener 上：按 listener 逐个相加会把同一批连接重复计。"""
        hub = NotificationHub()
        servers = (SimpleNamespace(notification_hub=hub), SimpleNamespace(notification_hub=hub))
        source = _source()
        source.bind_ws(servers)

        hub.register_ws("c1", "stream-1", object())

        assert source.status().ws_connections.notifications == 1

    async def test_explicit_notification_hub_wins_over_the_listeners(self) -> None:
        explicit = NotificationHub()
        other = NotificationHub()
        other.register_ws("c1", "stream-1", object())
        source = _source()
        source.bind_ws((SimpleNamespace(notification_hub=other),), notification_hub=explicit)

        explicit.register_ws("c2", "stream-2", object())

        assert source.status().ws_connections.notifications == 1


# ═══════════════════════════════════════════════════════════════════
# SOURCE_RAISES / SOURCE_ABSENT
# ═══════════════════════════════════════════════════════════════════


class TestSourceFailure:
    async def test_source_exception_becomes_a_fixed_500(self, caplog: pytest.LogCaptureFixture) -> None:
        async with _client(_BrokenSource()) as client:
            with caplog.at_level(logging.ERROR, logger="heagent.network.http_server"):
                response = await client.get("/api/status")

        assert response.status_code == 500
        assert response.json() == {
            "error": {"code": HttpErrorCode.SERVER_ERROR, "message": "request failed"},
        }
        # 异常类名与内部路径绝不回吐（诊断只进服务端日志）。
        assert "RuntimeError" not in response.text
        assert "secret" not in response.text
        failed = [record for record in caplog.records if "event=status_failed" in record.getMessage()]
        assert failed, caplog.text


class TestSourceAbsent:
    async def test_route_is_not_registered_without_a_source(self) -> None:
        app = build_http_app(_config(), version=_VERSION)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=_BASE_URL) as client:
            response = await client.get("/api/status")

        assert response.status_code == 404
        assert response.json()["error"] == {"code": HttpErrorCode.NOT_FOUND, "message": "no such endpoint"}

    async def test_route_is_registered_when_a_source_is_injected(self) -> None:
        async with _client(_source()) as client:
            assert (await client.get("/api/status")).status_code == 200
