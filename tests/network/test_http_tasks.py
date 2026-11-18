"""后台任务进度查询端点（``/api/tasks*``）的传输层契约测试。

四条要钉住的契约：

- **只读内存**：端点只消费注入来源，不 await I/O、不做磁盘扫描 ⇒ 单次响应有界（耗时断言）；
- **404 语义**：未知 / 已淘汰的 ``task_id`` 回稳定码 ``not_found``；
- **注入门**：未注入来源时不注册路由（回 404），注入后仅 ``GET`` 可用；
- **依赖边界**：``endpoints_tasks`` 不导入运行栈（网络层的可执行断言，不依赖
  ``tests/test_architecture_contracts.py`` 的既有镜头）。
"""

from __future__ import annotations

import ast
import inspect
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.engine import tasks as engine_tasks
from heagent.network.http_protocol import HttpErrorCode
from heagent.network.http_server import (
    HttpServerConfig,
    RegistryTaskSource,
    TaskProgressView,
    build_http_app,
)
from heagent.network.http_server import endpoints_tasks

_ENDPOINTS_MODULE = Path(endpoints_tasks.__file__)


def _config() -> HttpServerConfig:
    return HttpServerConfig(port=0)


def _view(task_id: str, *, percent: int = 40, status: str = "running") -> TaskProgressView:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return TaskProgressView.model_validate(
        {
            "task_id": task_id,
            "kind": "context_compression",
            "status": status,
            "percent": percent,
            "message": "summarizing 2/4 messages",
            "started_at": now,
            "updated_at": now,
        }
    )


class _StaticSource:
    """固定快照的注入来源（记录调用次数，证明端点只读注入对象）。"""

    def __init__(self, views: list[TaskProgressView], *, error: Exception | None = None) -> None:
        self.views = views
        self.error = error
        self.list_calls = 0
        self.get_calls = 0

    def list_tasks(self) -> list[TaskProgressView]:
        self.list_calls += 1
        if self.error is not None:
            raise self.error
        return self.views

    def task(self, task_id: str) -> TaskProgressView | None:
        self.get_calls += 1
        if self.error is not None:
            raise self.error
        return next((view for view in self.views if view.task_id == task_id), None)


def _client(source: Any | None) -> httpx.AsyncClient:
    app = build_http_app(_config(), version="9.9.9", tasks=source)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:9101")


class TestTaskEndpoints:
    """两条只读端点的状态码与响应形状。"""

    async def test_list_returns_tasks_with_percent_and_status(self) -> None:
        source = _StaticSource([_view("a"), _view("b", percent=100, status="completed")])
        async with _client(source) as client:
            response = await client.get("/api/tasks")

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"tasks"}
        assert [item["task_id"] for item in payload["tasks"]] == ["a", "b"]
        first = payload["tasks"][0]
        assert set(first) == {"task_id", "kind", "status", "percent", "message", "started_at", "updated_at"}
        assert first["percent"] == 40
        assert first["status"] == "running"
        # 时间戳是 ISO 8601（带时区），客户端可直接比较先后
        assert first["started_at"].endswith("Z") or "+00:00" in first["started_at"]
        assert source.list_calls == 1

    async def test_single_task_returns_full_progress(self) -> None:
        source = _StaticSource([_view("a", percent=70)])
        async with _client(source) as client:
            response = await client.get("/api/tasks/a")

        assert response.status_code == 200
        payload = response.json()
        assert payload["task_id"] == "a"
        assert payload["percent"] == 70
        assert payload["status"] == "running"
        assert source.get_calls == 1

    async def test_unknown_task_is_not_found_with_stable_code(self) -> None:
        async with _client(_StaticSource([_view("a")])) as client:
            response = await client.get("/api/tasks/missing")

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == HttpErrorCode.NOT_FOUND.value
        assert body["error"]["message"] == "no such task"

    async def test_empty_registry_lists_nothing(self) -> None:
        async with _client(_StaticSource([])) as client:
            response = await client.get("/api/tasks")

        assert response.status_code == 200
        assert response.json() == {"tasks": []}

    async def test_list_is_truncated_to_the_response_bound(self) -> None:
        source = _StaticSource([_view(f"t{index:03d}") for index in range(endpoints_tasks.MAX_TASK_LIST_ENTRIES + 5)])
        async with _client(source) as client:
            response = await client.get("/api/tasks")

        assert response.status_code == 200
        assert len(response.json()["tasks"]) == endpoints_tasks.MAX_TASK_LIST_ENTRIES

    async def test_source_failure_is_a_redacted_500(self) -> None:
        source = _StaticSource([], error=RuntimeError("secret path /etc/passwd"))
        async with _client(source) as client:
            listed = await client.get("/api/tasks")
            single = await client.get("/api/tasks/a")

        for response in (listed, single):
            assert response.status_code == 500
            body = response.json()
            assert body["error"]["code"] == HttpErrorCode.SERVER_ERROR.value
            # 异常细节不出口（诊断只进服务端日志）
            assert "/etc/passwd" not in response.text
            assert "RuntimeError" not in response.text


class TestTaskRoutesAreInjected:
    """未注入来源时不注册路由；注入后仅 ``GET``。"""

    async def test_routes_absent_without_source(self) -> None:
        async with _client(None) as client:
            response = await client.get("/api/tasks")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == HttpErrorCode.NOT_FOUND.value
        assert response.json()["error"]["message"] == "no such endpoint"

    async def test_only_get_is_allowed(self) -> None:
        async with _client(_StaticSource([])) as client:
            response = await client.post("/api/tasks")

        assert response.status_code == 405
        assert response.json()["error"]["code"] == HttpErrorCode.METHOD_NOT_ALLOWED.value

    async def test_listener_passes_the_source_through(self) -> None:
        """``HttpServer(tasks=...)`` 必须把来源透传给 app（否则路由静默缺失）。"""
        from heagent.network.http_server import HttpServer

        server = HttpServer(_config(), version="9.9.9", tasks=_StaticSource([_view("a")]))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://127.0.0.1:9101"
        ) as client:
            response = await client.get("/api/tasks/a")

        assert response.status_code == 200
        assert response.json()["task_id"] == "a"


class TestReadOnlyMemory:
    """只读内存：耗时与来源规模无关，且端点不做 I/O。"""

    async def test_response_stays_under_100ms(self) -> None:
        # 阈值刻意宽（100ms，远高于进程内 ASGI 实测的亚毫秒级）：这里只抓「端点开始做 I/O / 扫描」
        # 这类数量级退化，紧阈值在共享 CI 上只会制造 flaky——数量级判据才是本用例要钉的东西。
        source = _StaticSource([_view(f"t{index:03d}") for index in range(endpoints_tasks.MAX_TASK_LIST_ENTRIES)])
        async with _client(source) as client:
            await client.get("/api/tasks")  # 预热（首次请求含路由与模型构建）
            durations: list[float] = []
            for _ in range(20):
                started = time.monotonic()
                response = await client.get("/api/tasks")
                durations.append(time.monotonic() - started)
                assert response.status_code == 200

        assert max(durations) < 0.1, f"slowest /api/tasks took {max(durations) * 1000:.1f}ms"

    def test_endpoints_do_not_touch_the_filesystem(self) -> None:
        tree = ast.parse(_ENDPOINTS_MODULE.read_text(encoding="utf-8"))
        forbidden_calls = {"open", "read_text", "read_bytes", "mkdir", "exists", "iterdir", "glob"}
        called = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not (called & forbidden_calls)

    def test_source_protocol_is_synchronous(self) -> None:
        """同步是契约的一部分：异步来源会把端点变成 await I/O 的形状。"""
        assert not inspect.iscoroutinefunction(endpoints_tasks._build_task_endpoints)
        assert not inspect.iscoroutinefunction(RegistryTaskSource.list_tasks)
        assert not inspect.iscoroutinefunction(RegistryTaskSource.task)


class TestRegistrySourceAdapter:
    """``RegistryTaskSource`` 把引擎侧注册表映射为网络层视图。"""

    async def test_completed_registry_task_is_queryable_over_http(self) -> None:
        registry = engine_tasks.TaskRegistry()
        with registry.scope("context_compression", message="compacting") as task:
            task.report(55, "summarizing 1/2 messages")

        async with _client(RegistryTaskSource(registry)) as client:
            listed = await client.get("/api/tasks")
            single = await client.get(f"/api/tasks/{task.task_id}")

        assert listed.status_code == 200
        payload = listed.json()["tasks"]
        assert len(payload) == 1
        assert payload[0]["status"] == "completed"
        assert payload[0]["percent"] == 100
        assert single.status_code == 200
        assert single.json()["task_id"] == task.task_id

    def test_unknown_task_maps_to_none(self) -> None:
        assert RegistryTaskSource(engine_tasks.TaskRegistry()).task("missing") is None

    def test_adapter_respects_the_response_bound(self) -> None:
        registry = engine_tasks.TaskRegistry(max_finished=engine_tasks.DEFAULT_QUERY_LIMIT + 5)
        for index in range(endpoints_tasks.MAX_TASK_LIST_ENTRIES + 5):
            registry.finish(registry.start("kind", task_id=f"t{index:03d}"))

        views = RegistryTaskSource(registry).list_tasks()
        assert len(views) == endpoints_tasks.MAX_TASK_LIST_ENTRIES


class TestLayerBoundary:
    """网络层不导入运行栈（本模块自带断言，不动全局契约测试）。"""

    _FORBIDDEN_PREFIXES = (
        "heagent.agent",
        "heagent.engine",
        "heagent.providers",
        "heagent.tools",
        "heagent.memory",
        "heagent.skills",
        "heagent.context",
        "heagent.cron",
        "heagent.events",
        "heagent.config",
        "heagent.gui",
        "heagent.goal",
    )

    def test_endpoints_module_imports_no_runtime_layer(self) -> None:
        tree = ast.parse(_ENDPOINTS_MODULE.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module)

        offenders = sorted(
            name
            for name in imported
            if any(name == prefix or name.startswith(prefix + ".") for prefix in self._FORBIDDEN_PREFIXES)
        )
        assert offenders == []

    def test_status_enum_mirrors_the_engine_values(self) -> None:
        assert [member.value for member in endpoints_tasks.TaskStatusView] == [
            member.value for member in engine_tasks.TaskStatus
        ]

    def test_field_bounds_mirror_the_engine(self) -> None:
        assert endpoints_tasks.MAX_TASK_ID_CHARS == engine_tasks.MAX_TASK_ID_CHARS
        assert endpoints_tasks.MAX_TASK_KIND_CHARS == engine_tasks.MAX_TASK_KIND_CHARS
        assert endpoints_tasks.MAX_TASK_MESSAGE_CHARS == engine_tasks.MAX_TASK_MESSAGE_CHARS
        assert endpoints_tasks.MAX_TASK_LIST_ENTRIES == engine_tasks.DEFAULT_QUERY_LIMIT
