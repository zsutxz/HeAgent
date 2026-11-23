"""74.3 · ``cancel_run`` 帧：按 id 取消、只读口径，以及「错误帧不断连」的语义。

六个用例覆盖 entry 的 ``verify`` 全部判据：① 集合级端点按 id 取消时**只**动目标 run；
② 目标已终止 ⇒ ack 携带终态 status（幂等）、连接保留；③ 未知 id ⇒ ``unknown_run`` 错误帧后
连接仍能处理下一帧；④ 单 run 端点只接受「等于本连接绑定的 run」的目标；⑤ 只读 listener 上
``cancel_run`` 回 ``invalid_request`` 且不断连；⑥ ``cancel`` 与 ``cancel_run`` 走**同一个**
``service.cancel_run(run_id)`` 端口（取消实现只有一份）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import pytest

from heagent.network.http_protocol import HttpErrorCode, RunStatus
from heagent.network.ws_protocol import WS_CLOSE_POLICY
from heagent.network.ws_commands import _handle_commands
from heagent.network.ws_server import build_runs_collection_endpoint

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

    def __init__(self, run_id: str, status: RunStatus = RunStatus.RUNNING) -> None:
        self.run_id = run_id
        self.status = status


class _RunServiceStub:
    """``RunWebSocketService`` 替身：``cancel_run`` 幂等，且只动被点到的那条记录。"""

    _closing = False

    def __init__(self, *run_ids: str) -> None:
        self.records = {run_id: _RunRecord(run_id) for run_id in run_ids}
        self.cancel_calls: list[str] = []
        self.start_run_calls = 0

    async def cancel_run(self, run_id: str) -> _RunRecord | None:
        self.cancel_calls.append(run_id)
        record = self.records.get(run_id)
        if record is not None and record.status is RunStatus.RUNNING:
            record.status = RunStatus.CANCELLED
        return record

    async def start_run(self, prompt: str) -> _RunRecord:  # pragma: no cover - 本文件的帧不含 run
        self.start_run_calls += 1
        raise AssertionError("cancel_run 用例不该走到提交路径")

    def run(self, run_id: str) -> _RunRecord | None:
        return self.records.get(run_id)

    def needs_resync(self, record: Any, last_event_id: int | None) -> bool:
        return False

    def register_ws(self, *args: Any, **kwargs: Any) -> None:
        return None

    def unregister_ws(self, *args: Any, **kwargs: Any) -> None:
        return None


def _cancel_run_frame(run_id: str) -> str:
    return json.dumps({"command": "cancel_run", "run_id": run_id})


def _collection_endpoint(service: Any) -> Any:
    return build_runs_collection_endpoint(service, origin_violation=_ORIGIN_OK, max_connections=4, version="v74-test")


def _bound_run_loop(service: Any, run_id: str, *, readonly: bool = False) -> Any:
    """单 run 端点命令循环本体（端点按绑定 run_id + readonly 调它，见 ``build_ws_endpoint``）。"""
    return lambda ws: _handle_commands(ws, service, run_id, readonly=readonly)


@pytest.mark.asyncio
async def test_cancel_run_targets_only_the_named_run_on_the_collection_endpoint() -> None:
    """集合级端点按 id 取消：目标到终态，同连接上另一条 run 仍活、未被误杀。"""
    service = _RunServiceStub("run-a", "run-b")
    ws = _QueueWebSocket([_cancel_run_frame("run-a")])

    await _collection_endpoint(service)(ws)

    frames = [json.loads(frame) for frame in ws.sent]
    assert [frame["type"] for frame in frames] == ["hello", "ack"]
    assert frames[1] == {"type": "ack", "command": "cancel_run", "run_id": "run-a", "status": "cancelled"}
    assert service.records["run-a"].status is RunStatus.CANCELLED
    assert service.records["run-b"].status is RunStatus.RUNNING
    assert service.cancel_calls == ["run-a"]


@pytest.mark.asyncio
async def test_cancel_run_on_a_terminal_run_acks_its_status_and_keeps_the_connection() -> None:
    """目标已终止不算错误：幂等 ack 携带终态 status，连接保留（错的不是这条连接）。"""
    service = _RunServiceStub("run-a")
    service.records["run-a"].status = RunStatus.CANCELLED
    ws = _HangingWebSocket([_cancel_run_frame("run-a")])

    frames = await _run_until_idle(ws, _collection_endpoint(service))

    assert frames[1]["type"] == "ack"
    assert frames[1]["status"] == RunStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_cancel_run_with_an_unknown_id_returns_unknown_run_and_keeps_the_connection() -> None:
    """未知 id ⇒ ``unknown_run`` 错误帧，**不断连**：随后一条 ping 仍拿到 ack。"""
    service = _RunServiceStub("run-a")
    ws = _HangingWebSocket([_cancel_run_frame("run-ghost"), json.dumps({"command": "ping"})])

    frames = await _run_until_idle(ws, _collection_endpoint(service))

    assert frames[1]["type"] == "error"
    assert frames[1]["error"]["error"]["code"] == HttpErrorCode.UNKNOWN_RUN.value
    assert frames[2]["type"] == "ack"
    assert frames[2]["command"] == "ping"


@pytest.mark.asyncio
async def test_cancel_run_must_match_the_run_bound_to_the_connection() -> None:
    """单 run 端点：``run_id`` ≠ 绑定 run ⇒ ``invalid_request``，不取消、不断连。"""
    service = _RunServiceStub("run-a", "run-other")
    ws = _HangingWebSocket([_cancel_run_frame("run-other"), json.dumps({"command": "ping"})])

    frames = await _run_until_idle(ws, _bound_run_loop(service, "run-a"))

    assert frames[0]["type"] == "error"
    assert frames[0]["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
    assert service.cancel_calls == []
    assert service.records["run-other"].status is RunStatus.RUNNING
    # 循环仍活着：下一条 ping 按绑定 run 回 ack。
    assert frames[1]["type"] == "ack"
    assert frames[1]["run_id"] == "run-a"


@pytest.mark.asyncio
async def test_cancel_run_is_rejected_on_a_readonly_listener() -> None:
    """只读 listener：``cancel_run`` 回 ``invalid_request`` 且**不断连**（观众席仍收事件）。"""
    service = _RunServiceStub("run-a")
    ws = _HangingWebSocket([_cancel_run_frame("run-a"), json.dumps({"command": "ping"})])

    frames = await _run_until_idle(ws, _bound_run_loop(service, "run-a", readonly=True))

    assert frames[0]["type"] == "error"
    assert frames[0]["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
    assert service.cancel_calls == []
    assert service.records["run-a"].status is RunStatus.RUNNING
    assert frames[1]["type"] == "ack"


@pytest.mark.asyncio
async def test_cancel_and_cancel_run_share_one_cancel_port() -> None:
    """``cancel`` 与 ``cancel_run`` 是同一个端口的两种目标来源：各自恰好一次调用。"""
    service = _RunServiceStub("run-a")

    for frame in (json.dumps({"command": "cancel"}), _cancel_run_frame("run-a")):
        ws = _QueueWebSocket([frame])
        await _bound_run_loop(service, "run-a")(ws)
        ack = json.loads(ws.sent[0])
        assert ack["type"] == "ack"
        assert ack["run_id"] == "run-a"
        assert ack["status"] == RunStatus.CANCELLED.value

    assert service.cancel_calls == ["run-a", "run-a"]
    assert service.start_run_calls == 0


class _VanishingRunServiceStub(_RunServiceStub):
    """``cancel_run`` 恒返回 ``None``：模拟「绑定记录已被清理」。"""

    async def cancel_run(self, run_id: str) -> None:  # type: ignore[override]
        self.cancel_calls.append(run_id)
        return None


class _IgnoringCancelServiceStub(_RunServiceStub):
    """取消被忽略：端口如实返回**仍在** ``running`` 的记录（真实端口的超时分支）。"""

    async def cancel_run(self, run_id: str) -> _RunRecord | None:
        self.cancel_calls.append(run_id)
        return self.records.get(run_id)


@pytest.mark.asyncio
async def test_single_run_endpoint_closes_when_the_bound_record_is_gone() -> None:
    """单 run 端点：绑定记录已消失 ⇒ ``unknown_run`` 后**断连**（与集合级的分层差异，刻意行为）。

    这条连接的唯一目标都不存在了，留着它没有意义——plan 74.3 显式登记的口径，本用例是它的钉子。
    """
    service = _VanishingRunServiceStub("run-a")
    ws = _QueueWebSocket([json.dumps({"command": "cancel"})])

    await _bound_run_loop(service, "run-a")(ws)

    frames = [json.loads(frame) for frame in ws.sent]
    assert frames[-1]["type"] == "error"
    assert frames[-1]["error"]["error"]["code"] == HttpErrorCode.UNKNOWN_RUN.value
    assert ws.closed_code == WS_CLOSE_POLICY


@pytest.mark.asyncio
async def test_cancel_ack_reports_the_status_the_port_returned() -> None:
    """取消不保证立即生效：ack 的 ``status`` 是端口**当时**返回的状态，``running`` 也如实回执。"""
    service = _IgnoringCancelServiceStub("run-a")
    ws = _QueueWebSocket([_cancel_run_frame("run-a")])

    await _collection_endpoint(service)(ws)

    ack = json.loads(ws.sent[1])
    assert ack == {"type": "ack", "command": "cancel_run", "run_id": "run-a", "status": "running"}
