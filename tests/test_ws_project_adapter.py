"""75.3 · 项目通道适配器：帧投影与错误码转译单源（E75-S03，cover R1 / R2 / R7）。

钉住四件事：① 项目帧每条**恰三键**（`path` / `last_opened_at` / `is_default` 不出入口层）且顺序
沿用控制台给定顺序；② 提交结果收窄成 `SubmittedRun`（`session_id` 出了入口层就被丢掉）；③
`ConsoleOperationError.code` 与 `ProjectRegistryError.code` 逐字落进 `HttpRunConflictError.code`
（未登记的码不折叠，`ValueError` 冒出）；④ 适配器源码里没有任何文件系统 / 注册表逻辑——它是
「传输层不认识项目目录」的实现侧一半。

替身是 `ConsoleHandler` 项目面的最小鸭子类型（只实现被适配器调用的三个方法），不用真控制台：
本 story 的判据是**翻译**，控制台侧行为另有用例覆盖。
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from heagent.cli import ws_project_adapter
from heagent.cli.ws_project_adapter import ProjectChannelAdapter
from heagent.network.http_console_protocol import (
    ConsoleOperationError,
    ProjectEntryResponse,
    ProjectListResponse,
    ProjectRunRequest,
    ProjectRunResponse,
)
from heagent.network.http_protocol import HttpErrorCode, HttpRunConflictError, RunStatus
from heagent.network.ws_protocol import (
    ProjectChannelService,
    SubmittedRun,
    WsFrameType,
    WsProjectsFrame,
)
from heagent.pub.projects import ProjectRegistryError

_PROJECT_ID = "p1234abcd"
_FRAME_KEYS = {"id", "name", "available"}


def _entry(project_id: str, name: str = "demo", *, available: bool = True, is_default: bool = False):
    """一条完整控制台条目（带适配器必须丢弃的三个字段）。"""
    return ProjectEntryResponse(
        id=project_id,
        name=name,
        path=f"/home/u/{name}",
        available=available,
        last_opened_at="2026-11-23T10:00:00Z",
        is_default=is_default,
    )


class _FakeConsole:
    """`ConsoleHandler` 项目面替身：记录调用次序与入参，可注入失败。"""

    def __init__(self) -> None:
        self.entries: list[ProjectEntryResponse] = []
        self.run_error: ConsoleOperationError | ProjectRegistryError | None = None
        self.config_error: ConsoleOperationError | ProjectRegistryError | None = None
        self.calls: list[tuple[str, object]] = []

    async def list_projects(self) -> ProjectListResponse:
        self.calls.append(("list_projects", None))
        return ProjectListResponse(projects=self.entries)

    async def start_project_run(self, project_id: str, request: ProjectRunRequest) -> ProjectRunResponse:
        self.calls.append(("start_project_run", (project_id, request)))
        if self.run_error is not None:
            raise self.run_error
        return ProjectRunResponse(run_id="run-0001", session_id="sess-0001", status=RunStatus.RUNNING)

    async def get_project_config(self, project_id: str) -> object:
        self.calls.append(("get_project_config", project_id))
        if self.config_error is not None:
            raise self.config_error
        return object()


def _adapter(console: _FakeConsole, state: str = "ok") -> ProjectChannelAdapter:
    return ProjectChannelAdapter(console, lambda: state)  # type: ignore[arg-type]


# ── 项目列表投影 ──


async def test_projects_frame_entry_has_exactly_three_keys_and_no_path() -> None:
    console = _FakeConsole()
    console.entries = [_entry(_PROJECT_ID), _entry("default", "默认", is_default=True)]

    frame = await _adapter(console).list_projects()

    assert isinstance(frame, WsProjectsFrame)
    assert frame.type is WsFrameType.PROJECTS
    payload = json.loads(frame.model_dump_json())
    for item in payload["projects"]:
        assert set(item) == _FRAME_KEYS
    assert "path" not in frame.model_dump_json()
    assert payload["projects"][0]["id"] == _PROJECT_ID


async def test_projects_frame_keeps_the_console_order_and_availability() -> None:
    console = _FakeConsole()
    console.entries = [
        _entry("p00000001", "甲"),
        _entry("p00000002", "乙", available=False),
        _entry("default", "默认", is_default=True),
    ]

    frame = await _adapter(console).list_projects()

    assert [item.id for item in frame.projects] == ["p00000001", "p00000002", "default"]
    # 不可用不等于不存在：条目保留、只是 available=False（客户端据此置灰而不是删掉）。
    assert frame.projects[1].available is False


@pytest.mark.parametrize("state", ["ok", "unreadable"])
async def test_projects_frame_carries_the_registry_health_state(state: str) -> None:
    console = _FakeConsole()
    console.entries = [_entry("default", "默认", is_default=True)]

    frame = await _adapter(console, state).list_projects()

    assert frame.registry_state == state


# ── 提交收窄 ──


async def test_start_project_run_narrows_to_submitted_run_without_session_id() -> None:
    console = _FakeConsole()

    result = await _adapter(console).start_project_run(_PROJECT_ID, "写个快排")

    assert isinstance(result, SubmittedRun)
    assert (result.run_id, result.status) == ("run-0001", RunStatus.RUNNING)
    assert set(result.model_dump()) == {"run_id", "status"}
    assert "session_id" not in SubmittedRun.model_fields


async def test_start_project_run_sends_one_request_carrying_only_the_prompt() -> None:
    console = _FakeConsole()

    await _adapter(console).start_project_run(_PROJECT_ID, "写个快排")

    assert [name for name, _ in console.calls] == ["start_project_run"]
    project_id, request = console.calls[0][1]  # type: ignore[misc]
    assert project_id == _PROJECT_ID
    assert isinstance(request, ProjectRunRequest)
    assert request.prompt == "写个快排"
    assert request.session_id is None


# ── 错误码逐字转译 ──


@pytest.mark.parametrize(
    "code",
    [
        "project_busy",
        "unknown_project",
        "project_unavailable",
        "run_conflict",
        "total_inflight_limit",
        "project_registry_unreadable",
    ],
)
async def test_console_operation_error_code_passes_through_verbatim(code: str) -> None:
    console = _FakeConsole()
    console.run_error = ConsoleOperationError(code, "boom")

    with pytest.raises(HttpRunConflictError) as raised:
        await _adapter(console).start_project_run(_PROJECT_ID, "写个快排")

    assert raised.value.code == code
    assert str(raised.value.code) == code
    assert str(raised.value) == "boom"


async def test_project_registry_error_code_passes_through_verbatim() -> None:
    console = _FakeConsole()
    console.run_error = ProjectRegistryError("project_registry_unreadable", "registry is unreadable")

    with pytest.raises(HttpRunConflictError) as raised:
        await _adapter(console).start_project_run(_PROJECT_ID, "写个快排")

    assert raised.value.code == HttpErrorCode.PROJECT_REGISTRY_UNREADABLE
    assert str(raised.value) == "registry is unreadable"


async def test_unmapped_code_is_not_folded_into_a_generic_one() -> None:
    """漏译必须显性：未登记进 `HttpErrorCode` 的码不兜底成 `server_error`。"""
    console = _FakeConsole()
    console.run_error = ConsoleOperationError("not_a_registered_code", "boom")

    with pytest.raises(ValueError):
        await _adapter(console).start_project_run(_PROJECT_ID, "写个快排")


# ── 前置校验 ──


async def test_ensure_available_returns_the_id_after_a_read_only_resolve() -> None:
    console = _FakeConsole()

    assert await _adapter(console).ensure_available(_PROJECT_ID) == _PROJECT_ID
    # 只有解析读径被调用：不建 run、不占名额。
    assert [name for name, _ in console.calls] == ["get_project_config"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConsoleOperationError("unknown_project", "no project"), "unknown_project"),
        (ConsoleOperationError("project_unavailable", "gone"), "project_unavailable"),
        (ProjectRegistryError("project_registry_unreadable", "bad"), "project_registry_unreadable"),
    ],
)
async def test_ensure_available_translates_the_console_code(error: Exception, expected: str) -> None:
    console = _FakeConsole()
    console.config_error = error  # type: ignore[assignment]

    with pytest.raises(HttpRunConflictError) as raised:
        await _adapter(console).ensure_available(_PROJECT_ID)

    assert raised.value.code == expected


# ── 端口与源码边界 ──


def test_adapter_signatures_match_the_injected_port() -> None:
    for method in ("list_projects", "start_project_run", "ensure_available"):
        port = set(inspect.signature(getattr(ProjectChannelService, method)).parameters) - {"self"}
        impl = set(inspect.signature(getattr(ProjectChannelAdapter, method)).parameters) - {"self"}
        assert impl == port


def test_adapter_source_has_no_filesystem_or_registry_logic() -> None:
    source = Path(ws_project_adapter.__file__).read_text(encoding="utf-8")

    for forbidden in ("Path", "is_dir", "import os", "listdir"):
        assert forbidden not in source
    # 属性级断言：注册表方法调用与盘探测只在控制台 / 注册表侧，适配器一个都不许碰。
    attributes = {node.attr for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Attribute)}
    assert attributes & {"registry", "find", "load", "exists", "is_dir", "is_file"} == set()


def test_adapter_stays_inside_its_line_budget() -> None:
    source = Path(ws_project_adapter.__file__).read_text(encoding="utf-8")

    assert len(source.splitlines()) <= 150
