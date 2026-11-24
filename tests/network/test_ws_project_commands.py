"""E75-S02 · ``projects`` 命令：集合级端点回帧、其余三端点拒绝，以及响应帧的封闭形状。

判据分四组：

① 集合级端点装配了项目端口 ⇒ 收到 ``projects`` 帧（键集恰 ``{type, projects, registry_state}``，
每条恰 ``{id, name, available}``），端口异常仍走错误帧且 ``code`` 逐字透传；
② 未装配（``project_service=None``）⇒ ``project_channel_unavailable`` 且**不断连**（随后 ``ping``
   照常 ack；与「帧写错」的 ``invalid_request`` + 断连可分辨，Epic 77 D2），
不静默回空表；
③ 单 run 端点 / CLI 旁路 / 通知流收到 ``projects`` 一律 ``invalid_request`` 且不断连——它们是
「观众席」，项目视角属于集合级连接；
④ 帧与命令面的封闭性：``projects`` 只带 ``command``（带 ``project_id`` 即 ``malformed``）、
响应帧两值 ``registry_state``、``ProjectChannelService.list_projects`` 无参数。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from typing import Any

import pytest
from pydantic import ValidationError

from heagent.network.http_protocol import HttpErrorCode, HttpRunConflictError, RunStatus
from heagent.network.ws_commands import _handle_commands
from heagent.network.ws_protocol import (
    WS_CLOSE_POLICY,
    ProjectChannelEntry,
    ProjectChannelService,
    WsCommand,
    WsFrameError,
    WsFrameErrorKind,
    WsFrameType,
    WsProjectsFrame,
    parse_command_frame,
)
from heagent.network.ws_server import (
    _cli_handle_commands,
    _notification_handle_commands,
    build_runs_collection_endpoint,
)

_ORIGIN_OK = lambda _scope: None  # noqa: E731 - OriginCheck 替身，同步口径


class WebSocketDisconnect(Exception):
    """与 Starlette 同名：``_next_command`` 按类型名判「对端断开」。"""


class _QueueWebSocket:
    """按队列返回入站帧的 ``WebSocketLike`` 替身，队列空后抛断开。"""

    def __init__(self, frames: list[str]) -> None:
        self.scope: dict[str, Any] = {}
        self.path_params: dict[str, Any] = {}
        self.query_params: dict[str, Any] = {}
        self._frames = list(frames)
        self.sent: list[str] = []
        self.accepted = False
        self.closed_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    async def receive_text(self) -> str:
        if not self._frames:
            raise WebSocketDisconnect()
        return self._frames.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


class _HangingWebSocket(_QueueWebSocket):
    """队列空后**阻塞**而不是抛断开：用来观察「错误帧之后命令循环还活着、连接没被关」。"""

    def __init__(self, frames: list[str]) -> None:
        super().__init__(frames)
        self.drained = asyncio.Event()
        self._release = asyncio.Event()

    async def receive_text(self) -> str:
        if self._frames:
            return self._frames.pop(0)
        self.drained.set()
        await self._release.wait()
        raise WebSocketDisconnect()


async def _run_until_idle(ws: _HangingWebSocket, loop: Any) -> list[dict[str, Any]]:
    """驱动命令循环直到它再次等帧（此刻连接仍开着），返回已发出的全部帧。"""
    task = asyncio.create_task(loop(ws))
    await asyncio.wait_for(ws.drained.wait(), timeout=5)
    assert ws.closed_code is None, "错误帧不该关闭连接"
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return [json.loads(frame) for frame in ws.sent]


class _RunRecord:
    """run 记录的最小形状（端点只读 ``run_id`` / ``status``）。"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.status = RunStatus.RUNNING


class _RunServiceStub:
    """``RunWebSocketService`` 替身：本文件的帧都不含 ``run``，任何提交都算违约。"""

    _closing = False

    def __init__(self) -> None:
        self.start_run_calls = 0
        self.cancel_calls: list[str] = []

    async def start_run(self, prompt: str) -> _RunRecord:  # pragma: no cover - projects 用例不提交
        self.start_run_calls += 1
        raise AssertionError("the projects command must not start a run")

    async def cancel_run(self, run_id: str) -> _RunRecord | None:
        self.cancel_calls.append(run_id)
        return _RunRecord(run_id)

    def run(self, run_id: str) -> _RunRecord | None:
        return _RunRecord(run_id)

    def needs_resync(self, record: Any, last_event_id: int | None) -> bool:
        return False

    def register_ws(self, *args: Any, **kwargs: Any) -> None:
        return None

    def unregister_ws(self, *args: Any, **kwargs: Any) -> None:
        return None


class _ProjectChannelStub:
    """``ProjectChannelService`` 替身：只实现 ``list_projects``（本文件不测提交）。"""

    def __init__(
        self,
        frame: WsProjectsFrame | None = None,
        *,
        error: HttpRunConflictError | None = None,
    ) -> None:
        self._frame = frame if frame is not None else _sample_frame()
        self._error = error
        self.list_calls = 0

    async def ensure_available(self, project_id: str) -> str:  # pragma: no cover - projects 用例不提交
        raise AssertionError("the projects command must not ensure availability")

    async def start_project_run(
        self,
        project_id: str,
        prompt: str,
        request_id: str | None = None,  # noqa: ARG002 - 端口签名的一部分，本文件不测提交
    ) -> Any:  # pragma: no cover
        raise AssertionError("the projects command must not start a run")

    async def list_projects(self) -> WsProjectsFrame:
        self.list_calls += 1
        if self._error is not None:
            raise self._error
        return self._frame


def _sample_frame(registry_state: str = "ok") -> WsProjectsFrame:
    return WsProjectsFrame(
        projects=[
            ProjectChannelEntry(id="default", name="默认项目", available=True),
            ProjectChannelEntry(id="p1234abcd", name="heagent", available=False),
        ],
        registry_state=registry_state,  # type: ignore[arg-type] - 参数化用字面量，合法值由模型校验
    )


def _collection_endpoint(project_service: Any = None) -> Any:
    return build_runs_collection_endpoint(
        _RunServiceStub(),
        origin_violation=_ORIGIN_OK,
        max_connections=4,
        version="v75-test",
        project_service=project_service,
    )


def _bound_run_loop(service: Any, run_id: str) -> Any:
    return lambda ws: _handle_commands(ws, service, run_id)


class _CliHubStub:
    """CLI 旁路 hub 的最小形状：``projects`` 分支只走到错误帧，ping 才读 ``active_run_id``。"""

    active_run_id = "run-terminal"


_PROJECTS_FRAME = json.dumps({"command": "projects"})
_PING_FRAME = json.dumps({"command": "ping"})


@pytest.mark.asyncio
async def test_projects_command_returns_the_frame_on_the_collection_endpoint() -> None:
    """装配了项目端口：集合级端点把帧原样发出，键集恰三项（不含 ``run_id`` / ``session_id``）。"""
    project_service = _ProjectChannelStub()
    ws = _QueueWebSocket([_PROJECTS_FRAME])

    await _collection_endpoint(project_service)(ws)

    assert [json.loads(frame)["type"] for frame in ws.sent] == ["hello", "projects"]
    frame = json.loads(ws.sent[1])
    assert set(frame) == {"type", "projects", "registry_state"}
    assert frame["registry_state"] == "ok"
    assert [entry["id"] for entry in frame["projects"]] == ["default", "p1234abcd"]
    assert all(set(entry) == {"id", "name", "available"} for entry in frame["projects"])
    assert project_service.list_calls == 1


@pytest.mark.asyncio
async def test_projects_without_project_service_is_rejected_and_keeps_the_connection() -> None:
    """未装配项目端口：``project_channel_unavailable`` 且不静默回空表；随后 ``ping`` 照常 ack。"""
    service = _RunServiceStub()
    ws = _HangingWebSocket([_PROJECTS_FRAME, _PING_FRAME])

    frames = await _run_until_idle(ws, _collection_endpoint(None))

    assert frames[1]["type"] == "error"
    assert frames[1]["error"]["error"]["code"] == HttpErrorCode.PROJECT_CHANNEL_UNAVAILABLE.value
    assert frames[2]["type"] == "ack"
    assert frames[2]["command"] == "ping"
    assert service.start_run_calls == 0
    assert ws.closed_code is None


@pytest.mark.asyncio
async def test_malformed_frame_is_still_invalid_request_and_closes_the_connection() -> None:
    """对照用例（Epic 77 D2）：帧字段拼错仍是 ``invalid_request`` 且按口径断连。

    两条信号因此都能分流「未装配」与「帧写错」：``code`` 不同，**连接状态**也不同（前者保留、
    后者关闭）——客户端不必读文案，更不该依赖「是否断连」这种脆弱信号单独判错。
    """
    service = _RunServiceStub()
    ws = _QueueWebSocket([json.dumps({"command": "projects", "project_id": "p1234abcd"})])

    await _collection_endpoint(_ProjectChannelStub())(ws)

    frames = [json.loads(frame) for frame in ws.sent]
    assert frames[-1]["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
    # 替身只记住**最后一次** close：协议层先以 ``WS_CLOSE_POLICY``（1008）关，骨架收尾再补一次默认
    # 1000。判据因此只取「连接确实关了」（未装配那例反过来断言 ``closed_code is None``）。
    assert ws.closed_code is not None
    assert WS_CLOSE_POLICY != 1000  # 断言本身不放宽：两档 code 确实不同
    assert service.start_run_calls == 0


@pytest.mark.asyncio
async def test_projects_port_failure_code_is_translated_verbatim() -> None:
    """端口抛 ``HttpRunConflictError`` ⇒ ``code`` 逐字进错误帧，连接保留（R7 口径同提交分支）。"""
    project_service = _ProjectChannelStub(
        error=HttpRunConflictError("registry unreadable", code=HttpErrorCode.PROJECT_REGISTRY_UNREADABLE)
    )
    ws = _HangingWebSocket([_PROJECTS_FRAME, _PING_FRAME])

    frames = await _run_until_idle(ws, _collection_endpoint(project_service))

    assert frames[1]["error"]["error"]["code"] == HttpErrorCode.PROJECT_REGISTRY_UNREADABLE.value
    assert frames[2]["command"] == "ping"
    assert ws.closed_code is None


@pytest.mark.asyncio
async def test_projects_on_the_single_run_endpoint_is_rejected_without_closing() -> None:
    """单 run 端点：``projects`` 回 ``invalid_request``（不是 ping 那类 ack），连接不关。"""
    service = _RunServiceStub()
    ws = _HangingWebSocket([_PROJECTS_FRAME, _PING_FRAME])

    frames = await _run_until_idle(ws, _bound_run_loop(service, "run-1"))

    assert frames[0]["type"] == "error"
    assert frames[0]["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
    assert "run collection endpoint" in frames[0]["error"]["error"]["message"]
    assert frames[1]["type"] == "ack"
    assert frames[1]["command"] == "ping"
    assert ws.closed_code is None


@pytest.mark.asyncio
async def test_projects_on_the_cli_bypass_is_rejected() -> None:
    """CLI 旁路：``projects`` 回 ``invalid_request``，不当成 ping 回 ack。"""
    ws = _QueueWebSocket([_PROJECTS_FRAME, _PING_FRAME])

    await _cli_handle_commands(ws, _CliHubStub())  # type: ignore[arg-type] - 只用到 active_run_id

    frames = [json.loads(frame) for frame in ws.sent]
    assert frames[0]["type"] == "error"
    assert frames[0]["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
    assert frames[1]["type"] == "ack"
    assert frames[1]["command"] == "ping"


@pytest.mark.asyncio
async def test_projects_on_the_notification_stream_is_rejected() -> None:
    """通知流：``projects`` 同样 ``invalid_request``（只读流不提供项目视角）。"""
    ws = _QueueWebSocket([_PROJECTS_FRAME, _PING_FRAME])

    await _notification_handle_commands(ws)

    frames = [json.loads(frame) for frame in ws.sent]
    assert frames[0]["type"] == "error"
    assert frames[0]["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
    assert frames[1]["type"] == "ack"
    assert frames[1]["command"] == "ping"


def test_projects_command_frame_carries_only_the_command_key() -> None:
    """命令面封闭：``projects`` 只带 ``command``；多带 ``project_id`` 即 ``malformed``。"""
    frame = parse_command_frame(_PROJECTS_FRAME)

    assert frame.command is WsCommand.PROJECTS
    with pytest.raises(WsFrameError) as excinfo:
        parse_command_frame(json.dumps({"command": "projects", "project_id": "p1234abcd"}))
    assert excinfo.value.kind is WsFrameErrorKind.MALFORMED


def test_projects_frame_is_closed_and_two_valued() -> None:
    """响应帧封闭：``registry_state`` 只两值、条目与帧都 ``extra="forbid"``、类型是 ``projects``。"""
    assert WsProjectsFrame.model_fields["type"].default is WsFrameType.PROJECTS
    assert WsFrameType.PROJECTS is not WsFrameType.EVENT
    assert set(ProjectChannelEntry.model_fields) == {"id", "name", "available"}

    with pytest.raises(ValidationError):
        WsProjectsFrame(projects=[], registry_state="degraded")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        WsProjectsFrame(projects=[], registry_state="ok", run_id="run-1")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ProjectChannelEntry(id="p1", name="x", available=True, path="/tmp")  # type: ignore[call-arg]


def test_projects_frame_carries_the_architecture_bounds() -> None:
    """帧面自带上下界，不靠上游「恰好有界」：条目 32 上限 / 名字 1–64 / `registry_state` 默认 `ok`。"""
    entry = {"id": "p1", "name": "x", "available": True}
    assert WsProjectsFrame(projects=[]).registry_state == "ok"  # 缺省两值里的 ok
    assert len(WsProjectsFrame(projects=[ProjectChannelEntry(**entry)] * 32).projects) == 32

    with pytest.raises(ValidationError):
        WsProjectsFrame(projects=[ProjectChannelEntry(**entry)] * 33)  # 33 > MAX_PROJECTS
    with pytest.raises(ValidationError):
        ProjectChannelEntry(id="p1", name="", available=True)  # 空名
    with pytest.raises(ValidationError):
        ProjectChannelEntry(id="p1", name="x" * 65, available=True)  # 超 MAX_PROJECT_NAME_CHARS


def test_projects_port_takes_no_arguments() -> None:
    """端口签名：``list_projects`` 不带参数（项目集合由实现方决定，客户端不能指定过滤条件）。"""
    params = set(inspect.signature(ProjectChannelService.list_projects).parameters) - {"self"}

    assert params == set()


def test_project_channel_port_documents_its_three_obligations() -> None:
    """契约文本可 grep：端口 docstring 写明三条义务，且签名里没有 ``timeout`` 兜底参数。

    这三条是**跨层**约定（网络层不实现 超时 / 去重 / 脱敏，实现方必须做），只写在 docstring 里
    最容易腐烂，所以用判据钉住：改文案时这条会红，改签名加 ``timeout`` 同样会红。
    """
    doc = inspect.getdoc(ProjectChannelService) or ""

    assert "超时是实现方义务" in doc
    assert "幂等键只覆盖成功提交" in doc
    assert "错误消息不含路径" in doc
    for method in (ProjectChannelService.ensure_available, ProjectChannelService.start_project_run):
        assert "timeout" not in inspect.signature(method).parameters
