"""75.3 · 项目通道适配器：帧投影与错误码转译单源（E75-S03，cover R1 / R2 / R7）。

钉住四件事：① 项目帧每条**恰三键**（`path` / `last_opened_at` / `is_default` 不出入口层）且顺序
沿用控制台给定顺序；② 提交结果收窄成 `SubmittedRun`（`session_id` 出了入口层就被丢掉）；③
`ConsoleOperationError.code` 与 `ProjectRegistryError.code` 逐字落进 `HttpRunConflictError.code`
（未登记的码不折叠，`ValueError` 冒出）；④ 适配器源码里没有任何文件系统 / 注册表逻辑——它是
「传输层不认识项目目录」的实现侧一半。

第五件事（Epic 77 D1）：`request_id` 幂等窗口——同键在途合流（控制台只被调一次、两路拿到同一个
`run_id`）、成功结果 60s 内可重放、失败不缓存、TTL 过期后可再次提交。

替身是 `ConsoleHandler` 项目面的最小鸭子类型（只实现被适配器调用的三个方法），不用真控制台：
本 story 的判据是**翻译**，控制台侧行为另有用例覆盖。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import logging
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
from heagent.pub.projects import MAX_PROJECTS, ProjectRegistry, ProjectRegistryError

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
        self.probe_error: ConsoleOperationError | ProjectRegistryError | None = None
        self.calls: list[tuple[str, object]] = []

    async def list_projects(self) -> ProjectListResponse:
        self.calls.append(("list_projects", None))
        return ProjectListResponse(projects=self.entries)

    async def start_project_run(self, project_id: str, request: ProjectRunRequest) -> ProjectRunResponse:
        self.calls.append(("start_project_run", (project_id, request)))
        if self.run_error is not None:
            raise self.run_error
        return ProjectRunResponse(run_id="run-0001", session_id="sess-0001", status=RunStatus.RUNNING)

    async def check_project(self, project_id: str) -> None:
        self.calls.append(("check_project", project_id))
        if self.probe_error is not None:
            raise self.probe_error


def _adapter(console: _FakeConsole, state: str = "ok", **kwargs: float) -> ProjectChannelAdapter:
    return ProjectChannelAdapter(console, lambda: state, **kwargs)  # type: ignore[arg-type]


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


async def test_ensure_available_returns_the_id_after_the_lightweight_probe() -> None:
    console = _FakeConsole()

    assert await _adapter(console).ensure_available(_PROJECT_ID) == _PROJECT_ID
    # 只有轻量探测读径被调用：不求解配置、不建 run、不占名额。
    assert [name for name, _ in console.calls] == ["check_project"]


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
    console.probe_error = error  # type: ignore[assignment]

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


# ── 注册表健康守卫（R5 提交径） ──


class _RegistryConsole:
    """真注册表的只读投影（与 `HttpProjectConsole.list_projects` 同形态），供顺序与上限判据。"""

    def __init__(self, registry: ProjectRegistry) -> None:
        self.registry = registry

    async def list_projects(self) -> ProjectListResponse:
        return ProjectListResponse(
            projects=[ProjectEntryResponse(**entry.model_dump()) for entry in self.registry.list()]
        )


def _write_registry(path: Path, entries: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("method", ["start_project_run", "ensure_available"])
async def test_submit_path_rejects_an_unreadable_registry_with_the_named_code(tmp_path: Path, method: str) -> None:
    """注册表坏了 ⇒ 提交径回 `project_registry_unreadable`，绝不当成「这个项目不存在」。"""
    registry_file = tmp_path / "projects.json"
    registry_file.write_text("{not json", encoding="utf-8")
    registry = ProjectRegistry(registry_file, default_path=tmp_path)
    console = _FakeConsole()
    adapter = ProjectChannelAdapter(console, lambda: registry.health().code)  # type: ignore[arg-type]

    with pytest.raises(HttpRunConflictError) as raised:
        if method == "ensure_available":
            await adapter.ensure_available(_PROJECT_ID)
        else:
            await adapter.start_project_run(_PROJECT_ID, "写个快排")

    assert raised.value.code is HttpErrorCode.PROJECT_REGISTRY_UNREADABLE
    assert str(raised.value.code) == "project_registry_unreadable"
    # 不进控制台 ⇒ 下游没有机会把它译成 `unknown_project`；文案不含路径。
    assert console.calls == []
    assert str(tmp_path) not in str(raised.value)


async def test_readable_registry_keeps_the_submit_path_working(tmp_path: Path) -> None:
    """守卫只拦「不可读」：健康注册表照常走到控制台（否则等于给提交加了第二道门）。"""
    registry_file = tmp_path / "projects.json"
    _write_registry(registry_file, [])
    registry = ProjectRegistry(registry_file, default_path=tmp_path)
    console = _FakeConsole()
    adapter = ProjectChannelAdapter(console, lambda: registry.health().code)  # type: ignore[arg-type]

    result = await adapter.start_project_run(_PROJECT_ID, "写个快排")

    assert result.run_id == "run-0001"
    assert [name for name, _ in console.calls] == ["start_project_run"]


async def test_frame_order_matches_the_registry_listing(tmp_path: Path) -> None:
    """R1 的顺序判据：已登记项按 `last_opened_at` 倒序、`default` 末位，与 `list()` 逐位一致。"""
    registry_file = tmp_path / "projects.json"
    _write_registry(
        registry_file,
        [
            {"id": "pold00001", "name": "旧", "path": str(tmp_path / "old"), "last_opened_at": "2026-11-20T09:00:00Z"},
            {"id": "pnew00001", "name": "新", "path": str(tmp_path / "new"), "last_opened_at": "2026-11-23T09:00:00Z"},
            {"id": "pnever01", "name": "未用", "path": str(tmp_path / "never")},
        ],
    )
    registry = ProjectRegistry(registry_file, default_path=tmp_path)
    adapter = ProjectChannelAdapter(  # type: ignore[arg-type]
        _RegistryConsole(registry), lambda: registry.health().code
    )

    frame = await adapter.list_projects()

    assert [item.id for item in frame.projects] == [item.id for item in registry.list()]
    assert [item.id for item in frame.projects] == ["pnew00001", "pold00001", "pnever01", "default"]
    assert frame.registry_state == "ok"


async def test_all_thirty_two_projects_are_visible(tmp_path: Path) -> None:
    """R1 的 32 上限判据：31 条登记 + `default` 全量可见（上限不是「不可读」）。"""
    registry_file = tmp_path / "projects.json"
    _write_registry(
        registry_file,
        [
            {"id": f"p{index:08d}", "name": f"项目 {index}", "path": str(tmp_path / f"p{index}")}
            for index in range(MAX_PROJECTS - 1)
        ],
    )
    registry = ProjectRegistry(registry_file, default_path=tmp_path)
    adapter = ProjectChannelAdapter(  # type: ignore[arg-type]
        _RegistryConsole(registry), lambda: registry.health().code
    )

    frame = await adapter.list_projects()

    assert len(frame.projects) == MAX_PROJECTS == 32
    assert frame.projects[-1].id == "default"
    assert frame.registry_state == "ok"


@pytest.mark.parametrize("method", ["start_project_run", "ensure_available"])
async def test_default_project_stays_usable_when_the_registry_is_unreadable(tmp_path: Path, method: str) -> None:
    """`default` 由注册表句柄的启动工作区直接合成、不读注册表 ⇒ 登记表坏了也能提交。

    否则「登记表被改坏」会升级成「整个服务不可用」，而同一条帧里 `default` 仍是 `available=true`。
    """
    registry_file = tmp_path / "projects.json"
    registry_file.write_text("{not json", encoding="utf-8")
    registry = ProjectRegistry(registry_file, default_path=tmp_path)
    console = _FakeConsole()
    adapter = ProjectChannelAdapter(console, lambda: registry.health().code)  # type: ignore[arg-type]

    if method == "ensure_available":
        assert await adapter.ensure_available("default") == "default"
    else:
        assert (await adapter.start_project_run("default", "写个快排")).run_id == "run-0001"
    assert [name for name, _ in console.calls]  # 确实走到了控制台


# ── 提交幂等窗口（Epic 77 D1） ──


class _GatedConsole(_FakeConsole):
    """把提交停在闸门上，用来造「同键在途」的确定性窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def start_project_run(self, project_id: str, request: ProjectRunRequest) -> ProjectRunResponse:
        self.calls.append(("start_project_run", (project_id, request)))
        self.entered.set()
        await self.gate.wait()
        return ProjectRunResponse(run_id="run-0001", session_id="sess-0001", status=RunStatus.RUNNING)

    async def check_project(self, project_id: str) -> None:
        self.calls.append(("check_project", project_id))
        self.entered.set()
        await self.gate.wait()


def _start_calls(console: _FakeConsole) -> int:
    return sum(1 for name, _ in console.calls if name == "start_project_run")


async def test_same_request_id_in_flight_reuses_the_first_submission() -> None:
    """同键在途：第二路合流，控制台只被调一次，两路拿到同一个 ``run_id``。"""
    console = _GatedConsole()
    adapter = _adapter(console)

    first = asyncio.create_task(adapter.start_project_run(_PROJECT_ID, "hi", "req-1"))
    await console.entered.wait()
    second = asyncio.create_task(adapter.start_project_run(_PROJECT_ID, "hi", "req-1"))
    await asyncio.sleep(0)
    console.gate.set()

    outcomes = [await first, await second]

    assert [item.run_id for item in outcomes] == ["run-0001", "run-0001"]
    assert _start_calls(console) == 1


async def test_same_request_id_after_success_replays_the_cached_result() -> None:
    """同键串行（第一次已完成）：60s 内直接重放，控制台仍只被调一次。"""
    console = _FakeConsole()
    adapter = _adapter(console)

    first = await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")
    second = await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")

    assert (first.run_id, second.run_id) == ("run-0001", "run-0001")
    assert _start_calls(console) == 1


async def test_different_request_id_starts_two_runs() -> None:
    """不同键（或键含不同项目）互不干扰：两次都是真提交。"""
    console = _FakeConsole()
    adapter = _adapter(console)

    await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")
    await adapter.start_project_run(_PROJECT_ID, "hi", "req-2")
    await adapter.start_project_run("default", "hi", "req-1")

    assert _start_calls(console) == 3


async def test_without_request_id_every_call_is_a_new_submission() -> None:
    """旧帧逐字等价：不带幂等键就是每次新提交。"""
    console = _FakeConsole()
    adapter = _adapter(console)

    await adapter.start_project_run(_PROJECT_ID, "hi")
    await adapter.start_project_run(_PROJECT_ID, "hi")

    assert _start_calls(console) == 2


async def test_failure_is_not_cached_so_the_retry_can_start_again() -> None:
    """失败不进窗口：同键重试必须再次触达控制台（与「失败不做原子性保证」并存）。"""
    console = _FakeConsole()
    console.run_error = ConsoleOperationError("run_conflict", "a run is already in flight")
    adapter = _adapter(console)

    with pytest.raises(HttpRunConflictError):
        await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")

    console.run_error = None
    result = await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")

    assert result.run_id == "run-0001"
    assert _start_calls(console) == 2


async def test_expired_window_starts_a_new_submission() -> None:
    """窗口按单调时钟计时：过期后同键重新提交（不假装持久、也不无限去重）。"""
    console = _FakeConsole()
    adapter = _adapter(console)
    now = [1000.0]
    adapter._submissions._clock = lambda: now[0]  # type: ignore[attr-defined] - 判据要控制单调时钟

    await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")
    now[0] += 61.0
    await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")

    assert _start_calls(console) == 2


async def test_cancelling_one_joiner_does_not_cancel_the_other() -> None:
    """合流者被取消不得连坐兄弟合流者——`asyncio.shield` 的唯一必要性，别把它当装饰去掉。

    实测口径（去掉 shield 即红）：取消其中一个合流者会把共享 `Future` 一起取消，另一个合流者因此
    收到 `CancelledError` 而不是结果；owner 侧照常返回（`if not future.done()` 守卫挡掉了
    `InvalidStateError`）。
    """
    console = _GatedConsole()
    adapter = _adapter(console)

    owner = asyncio.create_task(adapter.start_project_run(_PROJECT_ID, "hi", "req-1"))
    await console.entered.wait()
    doomed = asyncio.create_task(adapter.start_project_run(_PROJECT_ID, "hi", "req-1"))
    survivor = asyncio.create_task(adapter.start_project_run(_PROJECT_ID, "hi", "req-1"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # 让两个合流者都进到 `await shield(...)`
    doomed.cancel()
    console.gate.set()

    outcomes = await asyncio.gather(owner, survivor, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await doomed

    assert [getattr(item, "run_id", item) for item in outcomes] == ["run-0001", "run-0001"]
    assert _start_calls(console) == 1


async def test_failed_submission_is_marked_as_failed_in_the_window_log(caplog: pytest.LogCaptureFixture) -> None:
    """失败移出的 reason 由适配器给：``failed``（与取消可分辨，E78-S01）。"""
    console = _FakeConsole()
    console.run_error = ConsoleOperationError("run_conflict", "a run is already in flight")
    adapter = _adapter(console)

    with (
        caplog.at_level(logging.DEBUG, logger="heagent.cli.ws_submission_cache"),
        pytest.raises(HttpRunConflictError),
    ):
        await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")

    messages = [record.getMessage() for record in caplog.records if "idempotency_dropped" in record.getMessage()]
    assert len(messages) == 1 and "reason=failed" in messages[0]


async def test_cancelled_owner_is_marked_as_cancelled_in_the_window_log(caplog: pytest.LogCaptureFixture) -> None:
    """owner 被取消时 reason = ``cancelled``（≠ ``failed``）：日志能分清「没提交成」与「调用方撤了」。"""
    console = _GatedConsole()
    adapter = _adapter(console)
    task = asyncio.create_task(adapter.start_project_run(_PROJECT_ID, "hi", "req-1"))
    await console.entered.wait()

    with caplog.at_level(logging.DEBUG, logger="heagent.cli.ws_submission_cache"):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    messages = [record.getMessage() for record in caplog.records if "idempotency_dropped" in record.getMessage()]
    assert len(messages) == 1 and "reason=cancelled" in messages[0]


# ── 端口超时（实现方义务的行为判据，E75-R3 B9/V9 刻意延期项收口） ──


async def test_submit_timeout_fails_loud_with_the_named_timeout_code() -> None:
    """挂起的提交必须在上界内失败成**具名** ``timeout`` 码——契约只写义务，行为在这里承兑。"""
    console = _GatedConsole()
    adapter = _adapter(console, submit_timeout=0.05)

    with pytest.raises(HttpRunConflictError) as excinfo:
        await adapter.start_project_run(_PROJECT_ID, "hi")

    assert excinfo.value.code is HttpErrorCode.TIMEOUT
    assert _start_calls(console) == 1


async def test_ensure_available_timeout_fails_loud_with_the_named_timeout_code() -> None:
    """前置探测挂起同样要有上界：挂在 ``check_project`` 上 = 提交径第一段就卡死。"""
    console = _GatedConsole()
    adapter = _adapter(console, submit_timeout=0.05)

    with pytest.raises(HttpRunConflictError) as excinfo:
        await adapter.ensure_available(_PROJECT_ID)

    assert excinfo.value.code is HttpErrorCode.TIMEOUT


async def test_submit_timeout_shares_failure_with_joiners_and_frees_the_window() -> None:
    """超时失败与幂等窗口的联动：合流者共享同一个具名失败，窗口释放后重试是真提交。

    R3 M-3 的担忧「端口挂起占席位」在适配器层钉死：挂起不吞窗口、不静默成功，失败可重试。
    """
    console = _GatedConsole()
    adapter = _adapter(console, submit_timeout=0.05)

    owner = asyncio.create_task(adapter.start_project_run(_PROJECT_ID, "hi", "req-1"))
    await console.entered.wait()
    joiner = asyncio.create_task(adapter.start_project_run(_PROJECT_ID, "hi", "req-1"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    outcomes = await asyncio.gather(owner, joiner, return_exceptions=True)

    assert all(isinstance(item, HttpRunConflictError) and item.code is HttpErrorCode.TIMEOUT for item in outcomes), (
        "owner 与合流者都必须拿到同一个具名超时失败"
    )
    assert _start_calls(console) == 1, "合流者不得再次触达控制台"
    console.gate.set()
    retry = await adapter.start_project_run(_PROJECT_ID, "hi", "req-1")
    assert retry.run_id == "run-0001"
    assert _start_calls(console) == 2, "失败已移出窗口，同键重试是真提交"
