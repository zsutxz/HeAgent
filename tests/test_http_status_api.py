"""``GET /api/status`` 的传输层测试：进程自身状态的只读聚合投影。

覆盖 Story 71.1 的 I/O 与边界矩阵：happy path / 在途 run / 终态 run / 三条 WS 流计数增减 /
来源抛错收敛 / 来源缺失不注册。全部经 ASGI 层直打 ``build_http_app``（不绑端口），在途 run 用
阻塞 executor 制造。
"""

from __future__ import annotations

import asyncio
import time
import contextlib
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("starlette")

import httpx
from datetime import UTC, datetime

from pydantic import SecretStr, ValidationError

from heagent.cli.http_status import HttpStatusSource, bind_status_source
from heagent.config import Settings
from heagent.network.cli_event_hub import CliEventHub
from heagent.network.http_protocol import (
    HTTP_SCHEMA_VERSION,
    HTTP_SERVICE_NAME,
    CronJobInfo,
    ErrorCodeCount,
    HttpErrorCode,
    RequestMetricsSummary,
    RunOutcome,
    RunStatus,
    RunStatusCounts,
    StatusResponse,
    WsConnectionCounts,
)
from heagent.network.http_server import HttpRunService, HttpServerConfig, build_http_app
from heagent.network.ws_host import WsServerConfig
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


class _CountingStatusSource:
    """真实来源的最小替身：只实现计数挂载与空状态（供请求计数用例使用）。"""

    def __init__(self) -> None:
        self._metrics: Any | None = None

    def attach_metrics(self, metrics: Any) -> None:
        self._metrics = metrics

    def status(self) -> StatusResponse:
        summary = RequestMetricsSummary()
        if self._metrics is not None:
            summary = RequestMetricsSummary(
                total=self._metrics.total,
                status_2xx=self._metrics.status_class("2xx"),
                status_3xx=self._metrics.status_class("3xx"),
                status_4xx=self._metrics.status_class("4xx"),
                status_5xx=self._metrics.status_class("5xx"),
                latency_p50_ms=self._metrics.latency_p50_ms(),
                latency_max_ms=self._metrics.latency_max_ms(),
                error_codes=[ErrorCodeCount(code=code, count=count) for code, count in self._metrics.error_codes()],
            )
        return StatusResponse(version=_VERSION, requests=summary)


class _BrokenSource:
    """抛异常的来源替身：异常文本里刻意带内部细节（响应体绝不该回吐它们）。"""

    def status(self) -> StatusResponse:
        raise RuntimeError("C:/internal/secret/workspace")


class _NotStatusResponseSource:
    """``status()`` 正常返回、但不是协议模型：序列化失败同样要走固定 500 文案。"""

    def status(self) -> Any:
        return object()


@contextlib.asynccontextmanager
async def _client(source: Any, *, run_service: HttpRunService | None = None) -> AsyncIterator[httpx.AsyncClient]:
    app = build_http_app(_config(), version=_VERSION, run_service=run_service, status=source)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=_BASE_URL) as client:
        yield client


def _ws_server(*, host: str = "127.0.0.1", port: int = 9201, tls: bool = False, hub: Any = None) -> Any:
    """WS listener 替身：配置用**真实** ``WsServerConfig``（模式/TLS 判定不在这里复刻）。

    对外绑定是 fail-closed 的（缺 token 直接拒绝构造），所以替身一律带上 token —— 回环场景下
    它不被使用，对外场景下它满足构造前提。
    """
    extra: dict[str, Any] = {"tls_cert_file": "c.pem", "tls_key_file": "k.pem"} if tls else {}
    config = WsServerConfig(host=host, port=port, auth_token=SecretStr("token"), **extra)
    # 运行期端口刻意与配置值不同（真值是 ``port=0`` 绑定后才有的）：把两者写成同一个数会让
    # 「读运行中的 listener」与「抄配置」这对实现永远不可区分。
    return SimpleNamespace(config=config, port=port + 100, notification_hub=hub)


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

    async def test_failed_run_lands_in_the_failed_bucket(self) -> None:
        """执行体抛错的运行必须落进 ``failed`` 桶：``failed`` / ``timed_out`` 错接时 ``sum`` 看不出来。"""

        async def boom(prompt: str, publisher: Any) -> RunOutcome:  # noqa: ARG001 - executor 的固定签名
            raise RuntimeError("boom")

        service = HttpRunService(_config(), boom)
        try:
            async with _client(_source(run_service=service), run_service=service) as client:
                await service.start_run("boom")
                await _drain(service)
                payload = (await client.get("/api/status")).json()
        finally:
            await service.close()

        assert payload["run_status"] == {
            "running": 0,
            "completed": 0,
            "failed": 1,
            "cancelled": 0,
            "timed_out": 0,
        }
        assert sum(payload["run_status"].values()) == payload["run_records"] == 1


# ═══════════════════════════════════════════════════════════════════
# 部署面：listener 事实与配置标量（Story 71.2）
# ═══════════════════════════════════════════════════════════════════


def _deployed(
    *,
    settings: Any = None,
    http_port: int = 9101,
    http_host: str = "127.0.0.1",
    ws_servers: tuple[Any, ...] = (),
) -> HttpStatusSource:
    """装配形态的来源：http listener 用真实 ``HttpServerConfig``，端口按运行值给。"""
    server = SimpleNamespace(config=HttpServerConfig(host=http_host, port=0), port=0)
    source = HttpStatusSource(version=_VERSION, max_inflight_runs=1, settings=settings)
    bind_status_source(source, ws_servers, http_server=server)
    # 绑定之后端口才确定（``port=0``）：此后改运行期属性，读到的值必须跟着变。
    server.port = http_port
    return source


class TestDeployment:
    async def test_loopback_listeners_report_local_mode(self) -> None:
        source = _deployed(ws_servers=(_ws_server(),))
        async with _client(source) as client:
            payload = (await client.get("/api/status")).json()

        assert [(item["kind"], item["mode"]) for item in payload["listeners"]] == [
            ("http", "local"),
            ("ws", "local"),
        ]
        assert [item["label"] for item in payload["listeners"]] == ["http", "ws-primary"]

    async def test_external_listener_reports_mode_and_tls(self) -> None:
        source = _deployed(ws_servers=(_ws_server(), _ws_server(host="0.0.0.0", port=9301, tls=True)))
        async with _client(source) as client:
            payload = (await client.get("/api/status")).json()

        external = payload["listeners"][2]
        assert (external["label"], external["mode"], external["tls"]) == ("ws-external", "external", True)
        assert payload["listeners"][1]["tls"] is False

    async def test_http_listener_on_a_non_loopback_host_reports_external(self) -> None:
        """HTTP 侧也要有真实模式判定：写死 `local` 时这条红。

        通配绑定意味着「任何能连上该地址的人都能用这个无认证入口」，状态面必须如实标成 external。
        """
        async with _client(_deployed(http_host="0.0.0.0")) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["listeners"][0]["mode"] == "external"

    async def test_without_ws_only_the_http_listener_is_reported(self) -> None:
        async with _client(_deployed()) as client:
            payload = (await client.get("/api/status")).json()

        assert [item["kind"] for item in payload["listeners"]] == ["http"]

    async def test_ports_come_from_the_running_listeners_not_the_config(self) -> None:
        """``port=0`` 的部署里配置值恒为 0：真实端口只能在绑定之后从 listener 上读。"""
        async with _client(_deployed(http_port=9123, ws_servers=(_ws_server(),))) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["listeners"][0]["port"] == 9123
        assert payload["listeners"][0]["port"] != 0
        # ws 替身的配置端口是 9201、运行期是 9301：读到 9201 就说明是抄配置而不是读 listener。
        assert payload["listeners"][1]["port"] == 9301

    async def test_deployment_scalars_come_from_settings(self) -> None:
        settings = Settings(
            _env_file=None,
            sandbox_backend="docker",
            active_provider="openai",
            http_console_write_enabled=True,
            routing_pools='{"openai": {"tiers": {"fast": "sentinel-model-a", "pro": "sentinel-model-b"}}}',
        )
        async with _client(_deployed(settings=settings)) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["sandbox_backend"] == "docker"
        assert payload["active_provider"] == "openai"
        assert payload["config_write_enabled"] is True
        assert payload["routing_pools"] == [{"pool": "openai", "tiers": ["fast", "pro"]}]

    async def test_no_secret_or_model_name_leaks_into_the_status_body(self) -> None:
        settings = Settings(
            _env_file=None,
            active_provider="openai",
            openai_api_key="sk-sentinel-value",
            routing_pools='{"openai": {"tiers": {"fast": "sentinel-model-a"}, "base_url": "http://sentinel.host"}}',
        )
        async with _client(_deployed(settings=settings, ws_servers=(_ws_server(),))) as client:
            response = await client.get("/api/status")

        assert "sk-sentinel-value" not in response.text
        assert "sentinel-model-a" not in response.text
        assert "sentinel.host" not in response.text
        # 绝对路径形态（宿主目录结构）同样不该出现在状态面里。
        assert "C:\\" not in response.text and "/home/" not in response.text

    async def test_a_pool_with_more_tiers_than_the_field_cap_does_not_break_status(self) -> None:
        """超量档位只截断，绝不因为一条配置让整条状态 500。"""
        tiers = {f"tier{index:02d}": f"model-{index}" for index in range(100)}
        settings = Settings(
            _env_file=None,
            routing_pools='{"openai": {"tiers": ' + __import__("json").dumps(tiers) + "}}",
        )
        async with _client(_deployed(settings=settings)) as client:
            response = await client.get("/api/status")

        assert response.status_code == 200
        assert response.json()["routing_pools"] == [{"pool": "openai", "tiers": list(tiers)[:64]}]

    async def test_effective_sandbox_backend_wins_over_the_configured_one(self) -> None:
        """``--sandbox docker`` 这类命令行覆盖必须体现在状态里（配置里可能仍是 ``auto``）。"""
        settings = Settings(_env_file=None, sandbox_backend="auto")
        source = HttpStatusSource(
            version=_VERSION,
            max_inflight_runs=1,
            settings=settings,
            sandbox_backend="docker",
        )

        assert source.status().sandbox_backend == "docker"

    def test_protocol_caps_clip_overlong_deployment_values(self) -> None:
        """超长配置只截断不 500：host 255 / 沙箱档位 32 / provider 名 64（协议上限，逐字钉死）。"""
        from heagent.cli.http_status import _MAX_BACKEND_CHARS, _MAX_HOST_CHARS, _MAX_PROVIDER_CHARS

        settings = Settings(_env_file=None, sandbox_backend="b" * 300, active_provider="p" * 300)
        source = HttpStatusSource(version=_VERSION, max_inflight_runs=1, settings=settings)
        long_ws = SimpleNamespace(config=SimpleNamespace(host="h" * 300, mode="local", tls_enabled=False), port=9201)
        bind_status_source(source, (long_ws,))
        snapshot = source.status()

        assert (_MAX_HOST_CHARS, _MAX_BACKEND_CHARS, _MAX_PROVIDER_CHARS) == (255, 32, 64)
        assert snapshot.listeners[0].host == "h" * 255
        assert snapshot.sandbox_backend == "b" * 32
        assert snapshot.active_provider == "p" * 64

    def test_effective_sandbox_backend_is_read_from_the_engine_decision(self) -> None:
        """``SANDBOX_BACKEND=auto`` / daemon 不可用时引擎降级成 ``passthrough``：状态必须报生效档位。"""
        from heagent.cli.http_status import _effective_sandbox_backend

        owner = SimpleNamespace(
            engine=SimpleNamespace(sandbox_decision=SimpleNamespace(effective_backend="passthrough")),
            sandbox_backend="auto",
        )
        assert _effective_sandbox_backend(owner) == "passthrough"
        # 没建引擎（测试替身 / 只读形态）：返回 None，由装配点回落到请求档位。
        assert _effective_sandbox_backend(SimpleNamespace(sandbox_backend="docker")) is None

    def test_active_provider_is_the_live_instance_not_a_snapshot(self) -> None:
        """``/provider`` 运行期切换后状态必须跟着变：装配期抄成字符串会一直报启动时那个名字。"""
        provider = SimpleNamespace(active="claude")
        source = HttpStatusSource(
            version=_VERSION,
            max_inflight_runs=1,
            settings=Settings(_env_file=None, active_provider="openai"),
            provider=provider,
        )

        assert source.status().active_provider == "claude"  # 实例优先于配置值
        provider.active = "openai"
        assert source.status().active_provider == "openai"

    async def test_pools_default_to_an_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未配置池时是空列表而不是 null；宿主机环境变量必须先摘掉，否则用例随机器变红。"""
        for key in ("ACTIVE_PROVIDER", "ROUTING_POOLS", "SANDBOX_BACKEND", "HTTP_CONSOLE_WRITE_ENABLED"):
            monkeypatch.delenv(key, raising=False)
        async with _client(_deployed(settings=Settings(_env_file=None))) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["routing_pools"] == []
        assert payload["sandbox_backend"] == "auto"
        assert payload["active_provider"] == ""
        assert payload["config_write_enabled"] is False


# ═══════════════════════════════════════════════════════════════════
# 依赖态：uptime / cron 作业 / 技能与记忆计数（Story 71.3）
# ═══════════════════════════════════════════════════════════════════


def _workspace(tmp_path: Any, *, jobs: str | None = None, skills: tuple[str, ...] = (), facts: int = 0) -> Any:
    """造一个最小工作区：cron jobs.json / 技能目录 / MEMORY.md。"""
    heagent = tmp_path / ".heagent"
    (heagent / "cron").mkdir(parents=True, exist_ok=True)
    (heagent / "memory").mkdir(parents=True, exist_ok=True)
    if jobs is not None:
        (heagent / "cron" / "jobs.json").write_text(jobs, encoding="utf-8")
    if facts:
        (heagent / "memory" / "MEMORY.md").write_text(
            "".join(f"- fact {index}\n" for index in range(facts)), encoding="utf-8"
        )
    for name in skills:
        skill_dir = heagent / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n\nbody\n", encoding="utf-8")
    return tmp_path


_JOBS = """[
  {
    "id": "job-1",
    "prompt": "say hi",
    "cron": "0 20 * * *",
    "recurring": true,
    "created": "2026-11-17T12:00:00+00:00",
    "last_run": "2026-11-17T12:02:59+00:00",
    "last_status": "success"
  }
]"""


class TestDependencyState:
    def _source(self, root: Any, **kwargs: Any) -> HttpStatusSource:
        return HttpStatusSource(version=_VERSION, max_inflight_runs=1, workspace_root=str(root), **kwargs)

    async def test_uptime_and_started_at_come_from_the_bound_listener(self) -> None:
        started = datetime(2026, 11, 19, 5, 0, tzinfo=UTC)
        server = SimpleNamespace(
            config=HttpServerConfig(port=9101), port=9101, started_at=started, uptime_seconds=125.5
        )
        source = HttpStatusSource(version=_VERSION, max_inflight_runs=1)
        bind_status_source(source, (), http_server=server)
        async with _client(source) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["uptime_seconds"] == 125.5
        assert payload["started_at"].startswith("2026-11-19T05:00:00")

    async def test_uptime_is_null_before_the_listener_started(self) -> None:
        """未启动报 ``null`` 而不是 0：0 会被读成「刚启动」。"""
        server = SimpleNamespace(config=HttpServerConfig(port=9101), port=9101, started_at=None, uptime_seconds=None)
        source = HttpStatusSource(version=_VERSION, max_inflight_runs=1)
        bind_status_source(source, (), http_server=server)

        snapshot = source.status()

        assert snapshot.uptime_seconds is None
        assert snapshot.started_at is None

    async def test_real_listener_records_its_own_start_time(self) -> None:
        """真实 ``HttpServer.start()`` 必须记下启动时刻（否则 uptime 永远是 null）。"""
        from heagent.network.http_server import HttpServer

        server = HttpServer(HttpServerConfig(port=0), version=_VERSION)
        await server.start()
        try:
            first = server.uptime_seconds
            await asyncio.sleep(0.02)
            second = server.uptime_seconds
            assert first is not None and second is not None
            # 只断言「非 None 且 >= 0」的话，恒返回 0.0 的实现也能过。
            assert 0 <= first < second
            assert server.started_at is not None
            assert server.started_at.tzinfo is not None
        finally:
            await server.close()

    async def test_uptime_is_reported_as_absent_after_the_listener_closed(self) -> None:
        """关闭后 uptime / started_at 归 ``None``：留着起点会让状态面报一个仍在增长的服务时长。"""
        from heagent.network.http_server import HttpServer

        server = HttpServer(HttpServerConfig(port=0), version=_VERSION)
        await server.start()
        assert server.uptime_seconds is not None
        await server.close()

        assert server.uptime_seconds is None
        assert server.started_at is None
        source = HttpStatusSource(version=_VERSION, max_inflight_runs=1)
        bind_status_source(source, (), http_server=server)
        assert source.status().uptime_seconds is None
        assert source.status().started_at is None

    async def test_uptime_restarts_from_zero_after_the_listener_restarted(self) -> None:
        """``close()`` → ``start()`` 之后 uptime 从新起点算：旧起点必须被丢弃，而不是接着累加。"""
        from heagent.network.http_server import HttpServer

        server = HttpServer(HttpServerConfig(port=0), version=_VERSION)
        await server.start()
        try:
            await asyncio.sleep(0.02)
            before = server.uptime_seconds
        finally:
            await server.close()
        await server.start()
        try:
            restarted = server.uptime_seconds
            assert before is not None and before > 0
            assert restarted is not None and restarted < before
        finally:
            await server.close()

    async def test_cron_jobs_come_from_the_workspace_jobs_file(self, tmp_path: Any) -> None:
        root = _workspace(tmp_path, jobs=_JOBS)
        async with _client(self._source(root)) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["cron_jobs"] == [
            {
                "job_id": "job-1",
                "cron": "0 20 * * *",
                "last_run": "2026-11-17T12:02:59Z",
                "last_status": "success",
            }
        ]

    async def test_missing_jobs_file_is_an_empty_list_not_an_error(self, tmp_path: Any) -> None:
        root = _workspace(tmp_path)
        async with _client(self._source(root)) as client:
            response = await client.get("/api/status")

        assert response.status_code == 200
        assert response.json()["cron_jobs"] == []

    async def test_corrupt_jobs_file_is_an_empty_list_not_an_error(self, tmp_path: Any) -> None:
        """半截 / 改形的 ``jobs.json`` 只该让 cron 一栏为空，不许把整条状态拖成 500。"""
        root = _workspace(tmp_path, jobs='[{"id": "job-1", "cron": "0 3 * * *"')
        async with _client(self._source(root)) as client:
            response = await client.get("/api/status")

        assert response.status_code == 200
        assert response.json()["cron_jobs"] == []

    async def test_naive_utc_last_run_is_reported_as_utc(self, tmp_path: Any) -> None:
        """``cron/jobs.py`` 落盘的时间戳是 naive UTC：原样下发会被客户端按本地时解释（差 8 小时）。"""
        root = _workspace(tmp_path, jobs=_JOBS.replace("2026-11-17T12:02:59+00:00", "2026-11-18T01:00:00"))
        async with _client(self._source(root)) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["cron_jobs"][0]["last_run"] == "2026-11-18T01:00:00Z"

    async def test_a_malformed_entry_is_dropped_instead_of_failing_the_whole_status(self, tmp_path: Any) -> None:
        """空 id 的条目能被 ``JobStore`` 加载：只该丢那一条，好条目必须照常出现（整条状态不许 500）。"""
        jobs = (
            '[{"id": "", "prompt": "p", "cron": "* * * * *", "created": "2026-11-17T12:00:00"},'
            ' {"id": "good", "prompt": "p2", "cron": "0 3 * * *", "created": "2026-11-17T12:00:00"}]'
        )
        root = _workspace(tmp_path, jobs=jobs)
        async with _client(self._source(root)) as client:
            response = await client.get("/api/status")

        assert response.status_code == 200
        assert [job["job_id"] for job in response.json()["cron_jobs"]] == ["good"]

    async def test_no_next_run_field_is_ever_reported(self) -> None:
        """网页进程不启动调度器 ⇒ 没有「下次触发」这回事，模型里也不许有该字段。"""
        assert "next_run" not in CronJobInfo.model_fields

    async def test_skill_and_memory_counts_come_from_the_workspace(self, tmp_path: Any) -> None:
        root = _workspace(tmp_path, skills=("alpha", "beta"), facts=3)
        async with _client(self._source(root)) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["skill_count"] == 2
        assert payload["memory_facts"] == 3

    def test_skill_count_failure_degrades_to_zero_without_taking_the_rest_down(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """技能库读失败只把技能数降级为 0：不能整条状态变 500，也不能把记忆条目一起清零。"""
        from heagent.cli import http_status

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise OSError("skills root unreadable")

        monkeypatch.setattr(http_status, "SkillStore", _boom)
        root = _workspace(tmp_path, facts=2)
        with caplog.at_level(logging.WARNING, logger="heagent.cli.http_status"):
            snapshot = self._source(root).status()

        assert snapshot.skill_count == 0
        assert snapshot.memory_facts == 2
        assert any("skill_count_failed" in record.getMessage() for record in caplog.records)

    def test_memory_fact_failure_degrades_to_zero_without_taking_the_rest_down(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """记忆文件读失败只把条数降级为 0：技能数照常给出，且失败不静默（有 WARNING）。"""
        from heagent.cli import http_status

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise OSError("memory file unreadable")

        monkeypatch.setattr(http_status, "FactStore", _boom)
        root = _workspace(tmp_path, skills=("alpha",))
        with caplog.at_level(logging.WARNING, logger="heagent.cli.http_status"):
            snapshot = self._source(root).status()

        assert snapshot.memory_facts == 0
        assert snapshot.skill_count == 1
        assert any("memory_count_failed" in record.getMessage() for record in caplog.records)

    async def test_dependency_reads_are_cached_for_a_short_window(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """轮询不该每次都读盘：窗口内盘上变化不反映，窗口**过后**才重新读（推进假时钟，不 sleep）。"""
        from heagent.cli import http_status

        clock = [1000.0]
        monkeypatch.setattr(http_status.time, "monotonic", lambda: clock[0])
        root = _workspace(tmp_path, facts=1)
        source = self._source(root)
        first = source.status().memory_facts

        (root / ".heagent" / "memory" / "MEMORY.md").write_text("- a\n- b\n- c\n", encoding="utf-8")
        clock[0] += 1.0  # 窗口内
        cached = source.status().memory_facts
        clock[0] += http_status._DEPENDENCY_CACHE_SECONDS  # 越过有效窗
        refreshed = source.status().memory_facts

        assert (first, cached, refreshed) == (1, 1, 3)


# ═══════════════════════════════════════════════════════════════════
# 资源采样：本进程 RSS / 线程 / CPU（Story 71.4）
# ═══════════════════════════════════════════════════════════════════


class TestProcessResources:
    async def test_status_carries_the_process_resources(self) -> None:
        async with _client(_source()) as client:
            payload = (await client.get("/api/status")).json()

        assert payload["resource_source"] in {"procfs", "ctypes", "unavailable"}
        assert set(["rss_bytes", "threads", "cpu_seconds"]).issubset(payload)
        if payload["resource_source"] != "unavailable":
            # 采样通路可用时数值必须真的送达状态面（映射处填 0 或漏传都该红）。
            assert payload["rss_bytes"] is not None and payload["rss_bytes"] > 0
            assert payload["cpu_seconds"] is not None and payload["cpu_seconds"] >= 0
            # 线程数同样必须是**送达的数**：漏传（恒 null）与填 0 都该红。
            assert payload["threads"] is not None and payload["threads"] > 0

    def test_sampler_reports_real_numbers(self) -> None:
        from heagent.network.proc_stats import read_process_stats

        stats = read_process_stats()

        if stats.source == "unavailable":  # 不支持的平台：三个值必须是 None，不能是 0
            assert (stats.rss_bytes, stats.threads, stats.cpu_seconds) == (None, None, None)
            return
        assert stats.rss_bytes is not None and 0 < stats.rss_bytes < 1 << 40
        assert stats.cpu_seconds is not None and stats.cpu_seconds >= 0

    def test_unsupported_platform_degrades_to_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from heagent.network import proc_stats

        monkeypatch.setattr(proc_stats.sys, "platform", "plan9")
        stats = proc_stats.read_process_stats()

        assert stats.source == "unavailable"
        assert (stats.rss_bytes, stats.threads, stats.cpu_seconds) == (None, None, None)

    def test_sampling_is_cheap_enough_for_a_polled_endpoint(self) -> None:
        from heagent.network.proc_stats import read_process_stats

        start = time.perf_counter()
        for _ in range(1000):
            read_process_stats()
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"1000 次采样耗时 {elapsed:.3f}s，超出可轮询的量级"


# ═══════════════════════════════════════════════════════════════════
# 请求计数与延迟（Story 71.5）
# ═══════════════════════════════════════════════════════════════════


class TestRequestMetrics:
    def test_counters_bucket_by_status_class(self) -> None:
        from heagent.network.http_server.metrics import RequestMetrics

        metrics = RequestMetrics()
        for status in (200, 200, 200, 404):
            metrics.record(status=status, elapsed_ms=1.0)

        assert metrics.total == 4
        assert metrics.status_class("2xx") == 3
        assert metrics.status_class("4xx") == 1
        assert metrics.status_class("5xx") == 0

    async def test_aborted_request_is_counted_without_making_the_middleware_raise(self) -> None:
        """应用在 ``response.start`` 之前抛错（status=0）只计总数与延迟：中间件自己不许再抛。"""
        from heagent.network.http_server.middleware import _AccessLogMiddleware
        from heagent.network.http_server.metrics import RequestMetrics

        async def boom(scope: Any, receive: Any, send: Any) -> None:  # noqa: ARG001 - ASGI 固定签名
            raise RuntimeError("boom")

        metrics = RequestMetrics()
        middleware = _AccessLogMiddleware(boom, metrics)
        with pytest.raises(RuntimeError):
            await middleware({"type": "http", "method": "GET", "path": "/api/x"}, None, None)

        # 原异常照旧穿透；计数只落总数（四个对外分桶不含 status=0）。
        assert metrics.total == 1
        assert sum(metrics.status_class(name) for name in ("2xx", "3xx", "4xx", "5xx")) == 0

    async def test_streaming_response_is_counted_but_kept_out_of_the_latency_window(self) -> None:
        """SSE 的耗时是连接寿命：只进总数与错误码，不进延迟窗口（否则一条长订阅独占 max）。"""
        from heagent.network.http_server.middleware import _AccessLogMiddleware
        from heagent.network.http_server.metrics import RequestMetrics

        async def sse(scope: Any, receive: Any, send: Any) -> None:  # noqa: ARG001 - ASGI 固定签名
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream; charset=utf-8")],
                }
            )
            await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
            await send({"type": "http.response.body", "body": b"data: 2\n\n", "more_body": False})

        async def sink(message: Any) -> None:  # 外层 send：真实 ASGI 由服务器提供，这里只收不发
            return None

        metrics = RequestMetrics()
        middleware = _AccessLogMiddleware(sse, metrics)
        await middleware({"type": "http", "method": "GET", "path": "/api/runs/r1/events"}, None, sink)

        assert metrics.total == 1
        assert metrics.status_class("2xx") == 1
        assert metrics.latency_p50_ms() == 0.0
        assert metrics.latency_max_ms() == 0.0

    def test_latency_window_is_bounded_and_percentile_computable(self) -> None:
        from heagent.network.http_server.metrics import LATENCY_WINDOW, RequestMetrics

        metrics = RequestMetrics()
        for index in range(LATENCY_WINDOW * 10):
            metrics.record(status=200, elapsed_ms=float(index))

        assert len(metrics._latencies) == LATENCY_WINDOW
        assert metrics.latency_max_ms() > metrics.latency_p50_ms() > 0

    def test_percentile_is_the_window_median_not_the_minimum(self) -> None:
        """p50 必须是中位数：取 ``ordered[0]``（窗口最小值）也能满足上面的「max > p50 > 0」。"""
        from heagent.network.http_server.metrics import RequestMetrics

        metrics = RequestMetrics()
        for value in (1.0, 2.0, 3.0):
            metrics.record(status=200, elapsed_ms=value)
        assert metrics.latency_p50_ms() == 2.0

        metrics.record(status=200, elapsed_ms=40.0)
        # 4 个样本时取上中位（``ordered[2]``）——偶数样本的口径钉在这里，改口径即红。
        assert metrics.latency_p50_ms() == 3.0

        single = RequestMetrics()
        single.record(status=200, elapsed_ms=40.0)
        assert single.latency_p50_ms() == single.latency_max_ms() == 40.0

        assert RequestMetrics().latency_p50_ms() == 0.0

    def test_error_codes_are_truncated_with_the_loudest_kept(self) -> None:
        """超过 16 个错误码时按次数排序后截断：不截断会让整条 ``/api/status`` 校验失败变 500。"""
        from heagent.cli.http_status import HttpStatusSource
        from heagent.network.http_server.metrics import RequestMetrics

        metrics = RequestMetrics()
        for code in (f"code-{index:02d}" for index in range(20)):
            metrics.record(status=400, elapsed_ms=1.0, error_code=code)
        for _ in range(3):
            metrics.record(status=400, elapsed_ms=1.0, error_code="run_conflict")

        source = HttpStatusSource(version=_VERSION, max_inflight_runs=1)
        source.attach_metrics(metrics)
        codes = source.status().requests.error_codes

        assert len(codes) == 16
        assert codes[0].code == "run_conflict" and codes[0].count == 3

    def test_error_code_is_read_only_from_small_json_envelopes(self) -> None:
        from heagent.network.http_server.metrics import error_code_from_body

        headers = [(b"content-type", b"application/json")]
        assert error_code_from_body(b'{"error": {"code": "run_conflict", "message": "x"}}', headers) == "run_conflict"
        # 非 JSON / 过大 / 无 error 信封一律不认（正常响应不进这条路径）
        assert error_code_from_body(b"plain text", headers) is None
        assert error_code_from_body(b"{" + b'"a": 1,' * 500 + b"}", headers) is None
        assert error_code_from_body(b'{"ok": true}', headers) is None

    def test_real_source_maps_real_metrics_without_a_replica(self) -> None:
        """映射由**真实** ``HttpStatusSource._request_metrics`` 完成：复刻映射的替身证明不了它。"""
        from heagent.network.http_server.metrics import RequestMetrics

        metrics = RequestMetrics()
        metrics.record(status=200, elapsed_ms=10.0)
        metrics.record(status=200, elapsed_ms=30.0)
        metrics.record(status=304, elapsed_ms=20.0)
        metrics.record(status=404, elapsed_ms=40.0, error_code="not_found")
        metrics.record(status=502, elapsed_ms=50.0, error_code="bad_gateway")
        metrics.record(status=503, elapsed_ms=60.0, error_code="unavailable")
        metrics.record(status=500, elapsed_ms=70.0, error_code="internal_error")
        metrics.record(status=500, elapsed_ms=80.0, error_code="internal_error")

        source = _source()
        source.attach_metrics(metrics)
        requests = source.status().requests

        assert requests.total == 8
        # 每个分桶都要真的搬到另一端：漏搬一个桶就会恒 0 而不报错。
        assert (requests.status_2xx, requests.status_3xx, requests.status_4xx, requests.status_5xx) == (2, 1, 1, 4)
        # 8 个样本的中位数取有序后下标 4（不是两端平均）：10/20/30/40/**50**/60/70/80。
        assert requests.latency_p50_ms == metrics.latency_p50_ms() == 50.0
        assert requests.latency_max_ms == 80.0
        assert [(item.code, item.count) for item in requests.error_codes] == [
            ("internal_error", 2),
            ("bad_gateway", 1),
            ("not_found", 1),
            ("unavailable", 1),
        ]

    def test_error_codes_are_capped_at_sixteen_keeping_the_loudest(self) -> None:
        """错误码最多 16 条：超出的丢弃，但按频次排序后最吵的必须留下。"""
        from heagent.network.http_server.metrics import RequestMetrics

        metrics = RequestMetrics()
        for index in range(20):
            metrics.record(status=500, elapsed_ms=1.0, error_code=f"code_{index:02d}")
        for _ in range(3):
            metrics.record(status=500, elapsed_ms=1.0, error_code="code_19")

        source = _source()
        source.attach_metrics(metrics)
        codes = source.status().requests.error_codes

        assert len(codes) == 16
        assert (codes[0].code, codes[0].count) == ("code_19", 4)
        assert "code_19" not in [item.code for item in codes[1:]]

    def test_metrics_stay_zero_until_the_app_attaches_them(self) -> None:
        """载体没挂上时全 0（而不是 ``None`` 或异常）：没有 HTTP app 就没有请求可计数。"""
        requests = _source().status().requests

        assert (requests.total, requests.status_2xx, requests.latency_p50_ms, requests.latency_max_ms) == (
            0,
            0,
            0.0,
            0.0,
        )
        assert requests.error_codes == []

    async def test_endpoint_counts_its_own_requests_and_error_codes(self) -> None:
        console = _CountingStatusSource()
        app = build_http_app(_config(), version=_VERSION, status=console)
        transport = httpx.ASGITransport(app=app)
        base_url = f"http://127.0.0.1:{_config().port}"
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            await client.get("/api/status")
            await client.get("/api/status")
            await client.post("/api/status")  # 405 → method_not_allowed
            payload = (await client.get("/api/status")).json()

        requests = payload["requests"]
        # 本次请求在响应发出**之后**才计入（finally 里记账）⇒ 快照看到的是此前 3 条。
        assert requests["total"] >= 3
        assert requests["status_2xx"] >= 2
        assert requests["status_4xx"] >= 1
        assert {"code": "method_not_allowed", "count": 1} in requests["error_codes"]
        assert requests["latency_max_ms"] >= requests["latency_p50_ms"] > 0

    async def test_reading_status_does_not_change_the_counters(self) -> None:
        console = _CountingStatusSource()
        app = build_http_app(_config(), version=_VERSION, status=console)
        transport = httpx.ASGITransport(app=app)
        base_url = f"http://127.0.0.1:{_config().port}"
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            first = (await client.get("/api/status")).json()["requests"]
            # 再读一次：计数只增本次请求这一条，不会因为「读快照」而重复计量
            second = (await client.get("/api/status")).json()["requests"]

        assert second["total"] == first["total"] + 1


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
    def test_embedded_wiring_prefers_the_engine_effective_backend(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """内嵌入口同样报**生效**档位：``executor.engine.sandbox_decision`` 优先于请求档位。"""
        from heagent.cli.http import build_http_service

        monkeypatch.chdir(tmp_path)
        settings = Settings(_env_file=None, sandbox_backend="auto")

        async def executor(prompt: str, publisher: Any, *, session_id: str | None = None) -> RunOutcome:  # noqa: ARG001
            raise AssertionError("本用例不发起运行")

        executor.engine = SimpleNamespace(  # type: ignore[attr-defined]
            sandbox_decision=SimpleNamespace(effective_backend="passthrough")
        )
        executor.sandbox_backend = "docker"  # type: ignore[attr-defined]

        service = build_http_service(settings, executor=executor, http_enabled=True, ws_enabled=False)

        assert service._http is not None and service._http.status is not None
        assert service._http.status.status().sandbox_backend == "passthrough"

    @pytest.mark.embedded_http_service
    async def test_embedded_service_wires_the_source_and_late_binds_ws(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """内嵌入口：端点必须真的注册，且 ``build_ws_servers`` 之后的 WS 计数要能读到。

        两处接线各防一件事：``HttpServer(... status=…)`` 漏传 ⇒ 恒 404；``bind_status_source``
        漏调 ⇒ ``ws_connections.cli`` 恒 0。
        """
        from heagent.cli.http import build_http_service

        _workspace(tmp_path, jobs=_JOBS, facts=2)
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
            deployed = wired.json()
            assert deployed["max_inflight_runs"] >= 1
            # 部署面同样要经装配送达：漏传 http_server ⇒ listeners 为空；漏传 settings ⇒ 标量为空串。
            assert [item["kind"] for item in deployed["listeners"]] == ["http", "ws"]
            assert deployed["sandbox_backend"] == settings.sandbox_backend
            assert deployed["routing_pools"] == []
            # 依赖态同样要经装配送达：漏传 workspace_root ⇒ 三项恒为 0/空，而响应仍 200。
            assert deployed["memory_facts"] == 2
            assert [job["job_id"] for job in deployed["cron_jobs"]] == ["job-1"]

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
        servers = (_ws_server(hub=hub), _ws_server(host="0.0.0.0", port=9301, hub=hub))
        source = _source()
        source.bind_ws(servers)

        hub.register_ws("c1", "stream-1", object())

        assert source.status().ws_connections.notifications == 1

    async def test_explicit_notification_hub_wins_over_the_listeners(self) -> None:
        explicit = NotificationHub()
        other = NotificationHub()
        other.register_ws("c1", "stream-1", object())
        source = _source()
        source.bind_ws((_ws_server(hub=other),), notification_hub=explicit)

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

    async def test_serialization_failure_takes_the_same_fixed_500(self, caplog: pytest.LogCaptureFixture) -> None:
        """来源返回非协议模型时，``model_dump`` 抛错也必须收敛成同一条固定文案。

        ``StatusSource`` 是结构化 Protocol，运行期拦不住手写适配器返回任意对象；这条用例钉住
        「序列化失败与取数失败走同一出口」——否则它会穿透到全局异常处理、丢掉 ``event=status_failed``。
        """
        async with _client(_NotStatusResponseSource()) as client:
            with caplog.at_level(logging.ERROR, logger="heagent.network.http_server"):
                response = await client.get("/api/status")

        assert response.status_code == 500
        assert response.json() == {
            "error": {"code": HttpErrorCode.SERVER_ERROR, "message": "request failed"},
        }
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
