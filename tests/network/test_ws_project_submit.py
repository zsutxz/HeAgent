"""74.2 · 带 ``project_id`` 的 WS 提交：项目通道端口的接线与错误转译。

五个用例全部经 ``build_runs_collection_endpoint`` 走真实端点（不直调内部 helper），钉住：
① 无 ``project_id`` 时旧路径逐字不变（只调 ``start_run``）；
② 带 ``project_id`` 时次序恰为「先 ``ensure_available`` 后 ``start_project_run``」，ack 来自
``SubmittedRun`` 且不含 ``session_id``；③ 前置校验失败的 ``code`` 逐字落进错误帧、连接不关、
零启动副作用；④ 提交失败的 ``code`` 同样逐字透传；⑤ 端口的参数名集合就是「不透明 id + prompt」。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from typing import Any

import pytest

from heagent.network.http_protocol import HttpErrorCode, HttpRunConflictError, RunStatus
from heagent.network.ws_protocol import WS_CLOSE_INTERNAL
from heagent.network.ws_server import (
    ProjectChannelService,
    SubmittedRun,
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


async def _run_until_idle(ws: _HangingWebSocket, endpoint: Any) -> list[dict[str, Any]]:
    """驱动端点直到它再次等帧（此刻连接仍开着），返回已发出的全部帧。"""
    task = asyncio.create_task(endpoint(ws))
    await asyncio.wait_for(ws.drained.wait(), timeout=5)
    assert ws.closed_code is None, "错误帧不该关闭连接"
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return [json.loads(frame) for frame in ws.sent]


class _RunRecord:
    """``HttpRunService.start_run`` 返回值的最小形状（端点只读 ``run_id`` / ``status``）。"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.status = RunStatus.RUNNING


class _RunWebSocketServiceStub:
    """``RunWebSocketService`` 替身：只实现端点用到的那几个成员。"""

    _closing = False

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.start_run_calls = 0

    async def start_run(self, prompt: str) -> _RunRecord:
        self.start_run_calls += 1
        self._calls.append(f"start_run:{prompt}")
        return _RunRecord("run-from-service")

    def register_ws(self, *args: Any, **kwargs: Any) -> None:
        return None

    def unregister_ws(self, *args: Any, **kwargs: Any) -> None:
        return None

    def run(self, run_id: str) -> None:
        return None


class _HttpProjectConsoleStub:
    """``ProjectChannelService`` 替身，对应 ``heagent.cli.http_console.HttpProjectConsole.start_project_run``。

    真实实现住在入口层（将来的 E75 适配器把它暴露成 :class:`ProjectChannelService`）；网络层只按
    端口调用，因此这里只做两件事：把调用次序记进共享 ``calls``、按需注入一次
    ``HttpRunConflictError``。
    """

    def __init__(
        self,
        calls: list[str],
        *,
        ensure_error: HttpRunConflictError | None = None,
        start_error: HttpRunConflictError | None = None,
    ) -> None:
        self._calls = calls
        self._ensure_error = ensure_error
        self._start_error = start_error
        self.ensure_calls = 0
        self.start_project_run_calls = 0

    async def ensure_available(self, project_id: str) -> str:
        self.ensure_calls += 1
        self._calls.append(f"ensure_available:{project_id}")
        if self._ensure_error is not None:
            raise self._ensure_error
        return project_id

    async def start_project_run(self, project_id: str, prompt: str) -> SubmittedRun:
        self.start_project_run_calls += 1
        self._calls.append(f"start_project_run:{project_id}")
        if self._start_error is not None:
            raise self._start_error
        return SubmittedRun(run_id=f"run-{project_id}", status=RunStatus.RUNNING)


def _endpoint(service: Any, project_service: Any = None) -> Any:
    return build_runs_collection_endpoint(
        service,
        origin_violation=_ORIGIN_OK,
        max_connections=4,
        version="v74-test",
        project_service=project_service,
    )


def _run_frame(prompt: str = "hi", project_id: str | None = None) -> str:
    payload: dict[str, Any] = {"command": "run", "prompt": prompt}
    if project_id is not None:
        payload["project_id"] = project_id
    return json.dumps(payload)


@pytest.mark.asyncio
async def test_submit_without_project_id_keeps_the_startup_workspace_path() -> None:
    """无 ``project_id``：项目端口一次都不触达，ack 的 ``run_id`` / ``status`` 来自 run 记录。"""
    calls: list[str] = []
    service = _RunWebSocketServiceStub(calls)
    project_service = _HttpProjectConsoleStub(calls)
    ws = _QueueWebSocket([_run_frame()])

    await _endpoint(service, project_service)(ws)

    ack = json.loads(ws.sent[1])
    assert [json.loads(frame)["type"] for frame in ws.sent] == ["hello", "ack"]
    assert ack["command"] == "run"
    assert ack["run_id"] == "run-from-service"
    assert ack["status"] == RunStatus.RUNNING.value
    assert service.start_run_calls == 1
    assert project_service.start_project_run_calls == 0
    assert project_service.ensure_calls == 0


@pytest.mark.asyncio
async def test_submit_with_project_id_calls_ensure_then_start_in_order() -> None:
    """带 ``project_id``：共享调用表证明次序恰为「先校验后提交」，ack 来自 ``SubmittedRun``。"""
    calls: list[str] = []
    service = _RunWebSocketServiceStub(calls)
    project_service = _HttpProjectConsoleStub(calls)
    ws = _QueueWebSocket([_run_frame(project_id="p1234abcd")])

    await _endpoint(service, project_service)(ws)

    ack = json.loads(ws.sent[1])
    assert calls == ["ensure_available:p1234abcd", "start_project_run:p1234abcd"]
    assert ack["type"] == "ack"
    assert ack["run_id"] == "run-p1234abcd"
    assert ack["status"] == RunStatus.RUNNING.value
    assert service.start_run_calls == 0
    assert "session_id" not in SubmittedRun.model_fields


@pytest.mark.asyncio
async def test_ensure_available_failure_is_translated_and_has_no_side_effect() -> None:
    """前置校验失败：``code`` 逐字进错误帧，两个启动路径均 0 次，连接保留。"""
    calls: list[str] = []
    service = _RunWebSocketServiceStub(calls)
    project_service = _HttpProjectConsoleStub(
        calls,
        ensure_error=HttpRunConflictError("no such project", code=HttpErrorCode.UNKNOWN_PROJECT),
    )
    ws = _HangingWebSocket([_run_frame(project_id="p1234abcd"), json.dumps({"command": "ping"})])

    frames = await _run_until_idle(ws, _endpoint(service, project_service))

    assert frames[1]["error"]["error"]["code"] == HttpErrorCode.UNKNOWN_PROJECT.value
    # 错误帧之后这条连接继续收命令（ping 拿到 ack），不是「先报错再断线」。
    assert frames[2]["type"] == "ack"
    assert frames[2]["command"] == "ping"
    assert service.start_run_calls == 0
    assert project_service.start_project_run_calls == 0
    assert ws.closed_code is None


@pytest.mark.asyncio
async def test_start_project_run_failure_is_translated_to_the_error_frame() -> None:
    """提交失败：``run_conflict`` 逐字进错误帧，``start_run`` 仍 0 次（提前失败不改走启动工作区）。"""
    calls: list[str] = []
    service = _RunWebSocketServiceStub(calls)
    project_service = _HttpProjectConsoleStub(
        calls,
        start_error=HttpRunConflictError("project busy", code=HttpErrorCode.RUN_CONFLICT),
    )
    ws = _HangingWebSocket([_run_frame(project_id="p1234abcd")])

    frames = await _run_until_idle(ws, _endpoint(service, project_service))

    assert frames[1]["error"]["error"]["code"] == HttpErrorCode.RUN_CONFLICT.value
    assert service.start_run_calls == 0
    assert project_service.start_project_run_calls == 1


def test_project_channel_port_takes_only_opaque_id_and_prompt() -> None:
    """端口签名里没有 path / workspace / session 类参数：传输层不认识项目目录。"""
    start_params = set(inspect.signature(ProjectChannelService.start_project_run).parameters) - {"self"}
    ensure_params = set(inspect.signature(ProjectChannelService.ensure_available).parameters) - {"self"}

    assert start_params == {"project_id", "prompt"}
    assert ensure_params == {"project_id"}


class _ExplodingProjectConsoleStub(_HttpProjectConsoleStub):
    """端口抛非 ``HttpRunConflictError``：适配器**漏译**时的形状（E75 适配器的义务判据）。"""

    async def start_project_run(self, project_id: str, prompt: str) -> SubmittedRun:
        raise RuntimeError("adapter blew up")


@pytest.mark.asyncio
async def test_untranslated_port_error_becomes_server_error_and_closes() -> None:
    """端口异常类型漏译时不静默：``server_error`` 错误帧 + ``1011`` 断连。

    现状是刻意保守的（不猜 code、不外泄异常文本）；本用例把「漏译」的后果钉成可观察行为，
    E75 的适配器因此有一条明确义务：把端口异常翻译成带 ``code`` 的 ``HttpRunConflictError``。
    """
    calls: list[str] = []
    service = _RunWebSocketServiceStub(calls)
    project_service = _ExplodingProjectConsoleStub(calls)
    ws = _QueueWebSocket([_run_frame(project_id="p1234abcd")])

    await _endpoint(service, project_service)(ws)

    frames = [json.loads(frame) for frame in ws.sent]
    assert frames[-1]["type"] == "error"
    assert frames[-1]["error"]["error"]["code"] == HttpErrorCode.SERVER_ERROR.value
    assert "blew up" not in frames[-1]["error"]["error"]["message"]
    assert ws.closed_code == WS_CLOSE_INTERNAL
