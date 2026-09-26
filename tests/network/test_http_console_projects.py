from __future__ import annotations

import pytest

pytest.importorskip("starlette")

import httpx
from pydantic import ValidationError

from heagent.network.http_console_protocol import (
    ConsoleOperationError,
    ProjectEntryResponse,
    ProjectListResponse,
)
from heagent.network.http_protocol import HttpErrorCode
from heagent.network.http_server import HttpServerConfig, build_http_app


class FakeConsole:
    def __init__(self) -> None:
        self.projects: list[ProjectEntryResponse] = []
        self.busy = False
        self.removed: list[str] = []

    async def list_projects(self) -> ProjectListResponse:
        return ProjectListResponse(projects=self.projects)

    async def register_project(self, request):
        if request.path.endswith("missing"):
            raise ConsoleOperationError(HttpErrorCode.INVALID_PROJECT_PATH, "project directory is unavailable")
        entry = ProjectEntryResponse(
            id="p12345678",
            name=request.name or "project",
            path=request.path,
            available=True,
            last_opened_at=None,
            is_default=False,
        )
        self.projects.append(entry)
        return entry

    async def rename_project(self, project_id: str, request):
        for index, entry in enumerate(self.projects):
            if entry.id == project_id:
                updated = entry.model_copy(update={"name": request.name})
                self.projects[index] = updated
                return updated
        raise ConsoleOperationError(HttpErrorCode.UNKNOWN_PROJECT, "no such project")

    async def project_has_inflight_run(self, project_id: str) -> bool:
        return self.busy

    async def remove_project(self, project_id: str) -> None:
        if project_id == "default":
            raise ConsoleOperationError(HttpErrorCode.PROJECT_NOT_REMOVABLE, "default project cannot be removed")
        if not any(entry.id == project_id for entry in self.projects):
            raise ConsoleOperationError(HttpErrorCode.UNKNOWN_PROJECT, "no such project")
        self.removed.append(project_id)


def _app(console=None, *, host="127.0.0.1"):
    return build_http_app(HttpServerConfig(port=0, host=host), version="test", console=console)


def _error(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


async def test_console_routes_are_absent_without_injected_handler() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://127.0.0.1") as client:
        response = await client.get("/api/projects")
    assert response.status_code == 404
    assert _error(response) == HttpErrorCode.NOT_FOUND


async def test_project_limit_is_reported_with_a_stable_code_over_http(tmp_path) -> None:
    """AC9 的真实链路：上限后再登记 ⇒ 409 ``project_limit_reached``（不是 400 / 500）。

    评审发现·镜头三②：网络层项目用例此前全部注入假 console，真实 ``HttpProjectConsole`` 的注册表
    方法没有任何 HTTP 级证据 ⇒ 该码只活在闭集清单里（``registry.code → ConsoleOperationError →
    HTTP`` 这段无断言）。
    """
    from heagent.cli.http import HttpProjectConsole
    from heagent.projects import MAX_PROJECTS

    workspace = tmp_path / "ws"
    workspace.mkdir()
    console = HttpProjectConsole(workspace)
    for index in range(MAX_PROJECTS - 1):  # 上限含隐式 default ⇒ 可登记 MAX_PROJECTS - 1 条
        target = tmp_path / f"p{index}"
        target.mkdir()
        console.registry.register(str(target))
    overflow = tmp_path / "overflow"
    overflow.mkdir()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(console)), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post("/api/projects", json={"path": str(overflow)})

    assert response.status_code == 409
    assert _error(response) == HttpErrorCode.PROJECT_LIMIT_REACHED


async def test_project_routes_list_register_rename_and_remove() -> None:
    console = FakeConsole()
    transport = httpx.ASGITransport(app=_app(console))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        listed = await client.get("/api/projects")
        created = await client.post("/api/projects", json={"path": "/tmp/project", "name": "Project"})
        renamed = await client.patch("/api/projects/p12345678", json={"name": "Renamed"})
        not_confirmed = await client.delete("/api/projects/p12345678")
        removed = await client.delete("/api/projects/p12345678?confirm=true")
    assert listed.status_code == 200
    assert created.status_code == 201
    assert renamed.json()["name"] == "Renamed"
    assert _error(not_confirmed) == HttpErrorCode.CONFIRM_REQUIRED
    assert removed.status_code == 204
    assert console.removed == ["p12345678"]


async def test_register_rejects_invalid_path_and_non_loopback_origin() -> None:
    console = FakeConsole()
    transport = httpx.ASGITransport(app=_app(console, host="10.0.0.4"), client=("10.0.0.2", 9000))
    async with httpx.AsyncClient(transport=transport, base_url="http://10.0.0.4") as client:
        denied = await client.post("/api/projects", json={"path": "/tmp/project"})
    assert _error(denied) == HttpErrorCode.LOOPBACK_REQUIRED
    transport = httpx.ASGITransport(app=_app(console))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        invalid = await client.post("/api/projects", json={"path": "/tmp/missing"})
    assert _error(invalid) == HttpErrorCode.INVALID_PROJECT_PATH


async def test_remove_rejects_busy_and_default_projects() -> None:
    console = FakeConsole()
    console.projects.append(
        ProjectEntryResponse(id="p12345678", name="p", path="/tmp/p", available=True, is_default=False)
    )
    console.busy = True
    transport = httpx.ASGITransport(app=_app(console))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        busy = await client.delete("/api/projects/p12345678?confirm=true")
        default = await client.delete("/api/projects/default?confirm=true")
    assert _error(busy) == HttpErrorCode.PROJECT_BUSY
    assert _error(default) == HttpErrorCode.PROJECT_NOT_REMOVABLE


def test_console_models_reject_extra_fields_and_bound_names() -> None:
    from heagent.network.http_console_protocol import ProjectRegisterRequest, ProjectRenameRequest

    with pytest.raises(ValidationError):
        ProjectRegisterRequest(path="/tmp/project", unexpected=True)
    with pytest.raises(ValidationError):
        ProjectRenameRequest(name="x" * 65)
