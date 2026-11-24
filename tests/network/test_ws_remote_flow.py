"""76.5 · ADR-005 验收基线五步串跑（E76-S05，cover R1 / R3 / R4）。

ADR-005 的验收基线是「APK 列项目 → 两项目**同时**各提交一个 run → 各自收完整事件流 → 取消其一
→ 断线重连凭 cursor 续流不丢事件」。本文件把这条基线放进**同一条用例**里顺序跑完，任一步失败
即整体红：不跑真 provider（run 记录由 fake 控制台建、事件由用例显式写入），但走真实适配器
（``ProjectChannelAdapter``）、真实集合级端点与真实单 run 端点，记录用生产的 ``_RunRecord``
（有界 ring buffer + 终态抢占 + 订阅者广播）。

五步与各自的断言点：

① **列项目**：集合级连接发 ``projects`` ⇒ 帧键集恰 ``{type, projects, registry_state}``、
   ``registry_state == "ok"``、条目顺序 A / B 且每条恰 ``{id, name, available}``（不带 path）；
② **两项目各 1 run**：两条集合级连接分别提交 A、B ⇒ 两个 ack 的 ``run_id`` 互不相同、各自指向
   本次提交、控制台收到的 ``(project, prompt)`` 交叉计数 0；
③ **事件流不串味**：两条单 run 订阅连接同时在线，各自只收到**自己那条 run** 的事件；事件帧不带
   ``run_id``（AD-6：事件信封不扩），故交叉计数按「这一帧是否属于本 run 的记录」判定 —— 对端事件
   出现在本连接上的次数必须为 0，且各自 seq 从 1 连续无空洞；
④ **取消其一**：集合级连接发 ``cancel_run`` ⇒ ack 为 ``cancelled``；A 的流以自身 ``cancelled``
   终态收尾（完整到终态），而 B 仍在跑、此后写入的事件照常落到 B 的在线连接上，随后 B 收
   ``completed`` 终态 —— 两路各自完整到**自己的**终态；
⑤ **cursor 续流**：B 中途断开后凭最后收到的事件 id 重连 ⇒ 续流首帧 ``<= last_event_id + 1``、
   其后连续递增到终态，两段拼接为 ``1..终态`` 的无空洞序列。

③ 的「完整到终态」与 ④ 天然交错（A 的终态正是 ④ 取消给出的，B 的终态在其续流之前），所以
终态完整性在 ④/⑤ 断言、用例末尾再回看两路全集 —— 见 ``story-e76-s05-remote-flow-plan.md``
的 Design Notes 第 2 条。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from heagent.cli.ws_project_adapter import ProjectChannelAdapter
from heagent.network.http_console_protocol import (
    ConsoleOperationError,
    ProjectEntryResponse,
    ProjectListResponse,
    ProjectRunRequest,
    ProjectRunResponse,
)
from heagent.network.http_protocol import HttpErrorCode, RunEventKind, RunStatus, cursor_out_of_window
from heagent.network.http_server.records import _RunRecord
from heagent.network.ws_server import build_runs_collection_endpoint, build_ws_endpoint

_PROJECT_A = "pa0000001"
_PROJECT_B = "pb0000001"
_PROMPT_A = "把项目 A 的读径写清楚"
_PROMPT_B = "把项目 B 的写径写清楚"

#: 事件 ring buffer / 订阅队列同界：本用例事件总量远小于它，续流不会撞 ``resync_required``。
_BUFFER_SIZE = 32

#: 等订阅登记 / 等事件到达的自旋上限（每次只让出事件循环，不引入时长依赖）。
_SPIN_LIMIT = 500

#: 会话骨架在帧队列耗尽（对端断开）后走的正常关闭码。
_GRACEFUL_CLOSE = 1000

_ORIGIN_OK = lambda _scope: None  # noqa: E731 - OriginCheck 替身，同步口径


class WebSocketDisconnect(Exception):
    """与 Starlette 同名：``_next_command`` 按类型名判「对端断开」。"""


class _CommandWebSocket:
    """集合级连接替身：按队列返回入站帧，队列空后抛断开（与既有 WS 用例同形）。"""

    def __init__(self, frames: list[str]) -> None:
        self.scope: dict[str, Any] = {}
        self.path_params: dict[str, Any] = {}
        self.query_params: dict[str, Any] = {}
        self._frames = list(frames)
        self.sent: list[str] = []
        self.closed_code: int | None = None

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    async def receive_text(self) -> str:
        await asyncio.sleep(0)
        if not self._frames:
            raise WebSocketDisconnect()
        return self._frames.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


class _SubscriptionWebSocket:
    """单 run 订阅连接替身：事件照收，``receive_text`` 阻塞到 ``disconnect()``（模拟客户端断线）。

    与服务端事件推送并发跑，所以断线不是「帧队列耗尽」而是显式信号：客户端读循环什么时候结束由
    用例决定，不看时序。
    """

    def __init__(self, run_id: str, *, last_event_id: int | None = None) -> None:
        self.scope: dict[str, Any] = {}
        self.path_params: dict[str, Any] = {"run_id": run_id}
        self.query_params: dict[str, Any] = {} if last_event_id is None else {"last_event_id": str(last_event_id)}
        self.sent: list[str] = []
        # 端点可能 close 两次（错误帧的策略码 + 骨架收尾的默认码），故按序全记。
        self.close_codes: list[int] = []
        self._disconnected = asyncio.Event()

    def disconnect(self) -> None:
        """模拟客户端读循环结束（断线）。"""
        self._disconnected.set()

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000) -> None:
        self.close_codes.append(code)

    async def receive_text(self) -> str:
        await self._disconnected.wait()
        raise WebSocketDisconnect()

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


class _RunServiceStub:
    """``RunWebSocketService`` 替身：记录池 + 取消端口，取消语义与生产同形。

    取消 = 抢占终态（``claim_terminal``，第一个获胜者）→ 写唯一的终态事件 → ``close_subscribers``
    （终态事件先于流结束标记，AD-4）。这样「取消一条 run」在订阅侧就是一次正常的流结束，用例不必
    自己编排服务端收尾顺序。
    """

    _closing = False

    def __init__(self) -> None:
        self._runs: dict[str, _RunRecord] = {}
        self.cancel_calls: list[str] = []
        self.registrations: dict[str, str] = {}

    def create_record(self, run_id: str, prompt: str, project_id: str) -> _RunRecord:
        record = _RunRecord(run_id, prompt, buffer_size=_BUFFER_SIZE, project_id=project_id)
        self._runs[run_id] = record
        return record

    def run(self, run_id: str) -> _RunRecord | None:
        return self._runs.get(run_id)

    async def cancel_run(self, run_id: str) -> _RunRecord | None:
        self.cancel_calls.append(run_id)
        record = self._runs.get(run_id)
        if record is None:
            return None
        if record.claim_terminal(RunStatus.CANCELLED):
            record.append(RunEventKind.CANCELLED, text="cancelled by client")
            record.close_subscribers()
        return record

    def needs_resync(self, record: _RunRecord, last_event_id: int | None) -> bool:
        return cursor_out_of_window(last_event_id, record.oldest_seq)

    def register_ws(self, connection_id: str, run_id: str, websocket: Any) -> None:
        self.registrations[connection_id] = run_id

    def unregister_ws(self, connection_id: str) -> None:
        self.registrations.pop(connection_id, None)

    async def start_run(self, prompt: str) -> Any:  # pragma: no cover - 本用例全走 project_id 分支
        raise AssertionError("every submission in this flow carries a project_id")


class _FakeProjectConsole:
    """``ConsoleHandler`` 项目面替身：列项目 / 提交前置探测 / 建 run（建的是真实 ``_RunRecord``）。

    形状对齐 ``cli.http_console.HttpProjectConsole``：``check_project`` 是提交前的轻量探测，
    ``start_project_run`` 才建 run —— 与适配器 ``ensure_available`` → ``start_project_run`` 两步
    一一对应，因此「提交 1 次」在这条链上恒等于「记录 1 条」。
    """

    def __init__(self, service: _RunServiceStub) -> None:
        self._service = service
        self.calls: list[tuple[str, object]] = []
        self.submissions: list[tuple[str, str]] = []
        self._seq = 0

    async def list_projects(self) -> ProjectListResponse:
        self.calls.append(("list_projects", None))
        return ProjectListResponse(projects=[_entry(_PROJECT_A, "项目 A"), _entry(_PROJECT_B, "项目 B")])

    async def check_project(self, project_id: str) -> None:
        self.calls.append(("check_project", project_id))
        if project_id not in (_PROJECT_A, _PROJECT_B):
            raise ConsoleOperationError(HttpErrorCode.UNKNOWN_PROJECT, "unknown project")

    async def start_project_run(self, project_id: str, request: ProjectRunRequest) -> ProjectRunResponse:
        self.calls.append(("start_project_run", project_id))
        self.submissions.append((project_id, request.prompt))
        self._seq += 1
        run_id = f"run-{self._seq:04d}"
        self._service.create_record(run_id, request.prompt, project_id)
        return ProjectRunResponse(run_id=run_id, session_id=f"sess-{self._seq:04d}", status=RunStatus.RUNNING)


def _entry(project_id: str, name: str) -> ProjectEntryResponse:
    """注册表条目（``path`` 不出远程帧，这里给个占位绝对路径即可）。"""
    return ProjectEntryResponse(
        id=project_id,
        name=name,
        path=f"/repos/{project_id}",
        available=True,
        is_default=False,
    )


def _collection_endpoint(service: _RunServiceStub, console: _FakeProjectConsole) -> Any:
    adapter = ProjectChannelAdapter(console, lambda: "ok")  # type: ignore[arg-type]
    return build_runs_collection_endpoint(
        service,
        origin_violation=_ORIGIN_OK,
        max_connections=8,
        version="v76-test",
        project_service=adapter,
    )


def _run_endpoint(service: _RunServiceStub) -> Any:
    """单 run 订阅端点；``version=""`` ⇒ 无 hello 帧，``sent`` 里只有事件/错误帧。"""
    return build_ws_endpoint(service, origin_violation=_ORIGIN_OK, max_connections=8, version="")


def _projects_frame() -> str:
    return json.dumps({"command": "projects"})


def _run_frame(prompt: str, project_id: str) -> str:
    return json.dumps({"command": "run", "prompt": prompt, "project_id": project_id})


def _cancel_run_frame(run_id: str) -> str:
    return json.dumps({"command": "cancel_run", "run_id": run_id})


def _frames(websocket: Any) -> list[dict[str, Any]]:
    return [json.loads(frame) for frame in websocket.sent]


def _events(websocket: Any) -> list[dict[str, Any]]:
    """这条连接上收到的事件负载（顺序即到达顺序）。"""
    return [frame["event"] for frame in _frames(websocket) if frame["type"] == "event"]


def _seqs(websocket: Any) -> list[int]:
    return [event["seq"] for event in _events(websocket)]


def _cross_count(websocket: Any, record: _RunRecord) -> int:
    """本连接上收到、却**不属于** ``record`` 的事件帧数（期望恒 0）。

    事件帧不带 ``run_id``（AD-6：run 事件信封不扩），所以「串味」只能按归属判定：把 ``record``
    缓冲里每条事件的 ``(seq, kind, text)`` 当认领指纹，指纹不在其中的帧就是别人的事件。
    """
    owned = {(payload.seq, str(payload.kind), payload.text) for payload in record.events}
    return sum(1 for event in _events(websocket) if (event["seq"], event["kind"], event["text"]) not in owned)


async def _await_subscribed(record: _RunRecord, expected: int) -> None:
    """等到该 run 上登记了 ``expected`` 个 WS 订阅者（登记发生在端点内部，需让出事件循环）。"""
    for _ in range(_SPIN_LIMIT):
        if len(record.ws_subscribers) >= expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"ws subscriber never registered: {len(record.ws_subscribers)} < {expected}")


async def _await_events(websocket: Any, expected: int) -> None:
    """等到这条连接上收到 ``expected`` 条事件帧。"""
    for _ in range(_SPIN_LIMIT):
        if len(_events(websocket)) >= expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {expected} event frames, got {len(_events(websocket))}")


@pytest.mark.asyncio
async def test_adr_005_acceptance_baseline_runs_end_to_end() -> None:
    """ADR-005 验收基线：列项目 → 两项目各 1 run → 事件流不串味 → 取消其一 → cursor 续流。"""
    service = _RunServiceStub()
    console = _FakeProjectConsole(service)
    endpoint = _collection_endpoint(service, console)

    # ---------------------------------------------------------------- ① 列项目
    ws_list = _CommandWebSocket([_projects_frame()])
    await endpoint(ws_list)
    listed = _frames(ws_list)
    assert [frame["type"] for frame in listed] == ["hello", "projects"]
    listing = listed[1]
    assert set(listing) == {"type", "projects", "registry_state"}
    assert listing["registry_state"] == "ok"
    assert [entry["id"] for entry in listing["projects"]] == [_PROJECT_A, _PROJECT_B]
    assert all(set(entry) == {"id", "name", "available"} for entry in listing["projects"]), "远程帧不得带 path"

    # ------------------------------------------- ② 两条集合级连接各为 A、B 提交 1 run
    ws_submit_a = _CommandWebSocket([_run_frame(_PROMPT_A, _PROJECT_A)])
    ws_submit_b = _CommandWebSocket([_run_frame(_PROMPT_B, _PROJECT_B)])
    await asyncio.gather(endpoint(ws_submit_a), endpoint(ws_submit_b))

    ack_a = _frames(ws_submit_a)[1]
    ack_b = _frames(ws_submit_b)[1]
    assert (ack_a["type"], ack_a["command"]) == ("ack", "run")
    assert (ack_b["type"], ack_b["command"]) == ("ack", "run")
    assert ack_a["status"] == RunStatus.RUNNING.value
    run_a, run_b = ack_a["run_id"], ack_b["run_id"]
    assert run_a != run_b, "两条连接的 ack 必须各自指向本次提交的 run"

    # 控制台收到的正是「各自的项目 + 各自的 prompt」：交叉计数 0、每项目恰一次
    assert dict(console.submissions) == {_PROJECT_A: _PROMPT_A, _PROJECT_B: _PROMPT_B}
    assert len(console.submissions) == 2
    # ack 面的 run_id 交叉计数 0：A 的连接上没有 B 的 run，反之亦然
    assert {frame["run_id"] for frame in _frames(ws_submit_a) if "run_id" in frame} == {run_a}
    assert {frame["run_id"] for frame in _frames(ws_submit_b) if "run_id" in frame} == {run_b}

    record_a = service.run(run_a)
    record_b = service.run(run_b)
    assert record_a is not None and record_b is not None
    assert (record_a.project_id, record_b.project_id) == (_PROJECT_A, _PROJECT_B)
    assert (record_a.status, record_b.status) == (RunStatus.RUNNING, RunStatus.RUNNING)

    # ------------------------------------- ③ 两条事件流同时在线，各自只收自己那条 run
    ws_stream_a = _SubscriptionWebSocket(run_a)
    ws_stream_b = _SubscriptionWebSocket(run_b)
    endpoint_run = _run_endpoint(service)
    task_a = asyncio.create_task(endpoint_run(ws_stream_a))
    task_b = asyncio.create_task(endpoint_run(ws_stream_b))
    await _await_subscribed(record_a, 1)
    await _await_subscribed(record_b, 1)

    for index in range(1, 4):
        record_a.append(RunEventKind.TEXT, text=f"A#{index}")
        record_b.append(RunEventKind.TEXT, text=f"B#{index}")
    await _await_events(ws_stream_a, 3)
    await _await_events(ws_stream_b, 3)

    assert [event["text"] for event in _events(ws_stream_a)] == ["A#1", "A#2", "A#3"]
    assert [event["text"] for event in _events(ws_stream_b)] == ["B#1", "B#2", "B#3"]
    assert _seqs(ws_stream_a) == [1, 2, 3], "各自从 1 起连续无空洞"
    assert _seqs(ws_stream_b) == [1, 2, 3]
    # 事件帧不带 run_id（AD-6），交叉计数按归属判定：对端事件出现在本连接上的次数恒 0
    assert _cross_count(ws_stream_a, record_a) == 0
    assert _cross_count(ws_stream_b, record_b) == 0
    assert not any(event["text"].startswith("B#") for event in _events(ws_stream_a))
    assert not any(event["text"].startswith("A#") for event in _events(ws_stream_b))

    # ------------------------------------------------------------ ④ 取消 A，B 仍活
    ws_cancel = _CommandWebSocket([_cancel_run_frame(run_a)])
    await endpoint(ws_cancel)
    cancel_ack = _frames(ws_cancel)[1]
    assert cancel_ack == {"type": "ack", "command": "cancel_run", "run_id": run_a, "status": "cancelled"}
    assert service.cancel_calls == [run_a], "取消只作用于目标 run"

    # A 的流以自身 cancelled 终态收尾（完整到终态），且全程无空洞
    await asyncio.wait_for(task_a, timeout=5)
    a_seqs = _seqs(ws_stream_a)
    assert _events(ws_stream_a)[-1]["kind"] == RunEventKind.CANCELLED.value
    assert a_seqs == list(range(1, len(a_seqs) + 1))
    assert (record_a.status, record_a.is_terminal) == (RunStatus.CANCELLED, True)
    assert _GRACEFUL_CLOSE in ws_stream_a.close_codes

    # B 没有被牵连：仍 running，且此后写入的事件照常落到它**在线**的那条连接上
    assert record_b.status is RunStatus.RUNNING
    assert not task_b.done()
    record_b.append(RunEventKind.TEXT, text="B#4")
    await _await_events(ws_stream_b, 4)
    assert _events(ws_stream_b)[-1]["text"] == "B#4"
    assert _cross_count(ws_stream_b, record_b) == 0

    # ------------------------------------------------- ⑤ B 中途断开 → 凭 cursor 续流
    ws_stream_b.disconnect()
    await asyncio.wait_for(task_b, timeout=5)
    received = _seqs(ws_stream_b)
    last_event_id = received[-1]
    assert received == [1, 2, 3, 4]

    # 断线期间照常产生事件（客户端没看到，靠续流补齐）
    record_b.append(RunEventKind.TEXT, text="B#5")

    ws_resume = _SubscriptionWebSocket(run_b, last_event_id=last_event_id)
    task_resume = asyncio.create_task(endpoint_run(ws_resume))
    await _await_subscribed(record_b, 1)
    await _await_events(ws_resume, 1)
    assert _seqs(ws_resume)[0] <= last_event_id + 1, "首帧不得早于游标的下一号，也不得跳号"

    # 续流连接是**活的**：后续事件继续送达，直到 B 自己的终态
    record_b.append(RunEventKind.TEXT, text="B#6")
    await _await_events(ws_resume, 2)
    assert record_b.claim_terminal(RunStatus.COMPLETED) is True
    record_b.append(RunEventKind.DONE, text="done")
    record_b.close_subscribers()
    await asyncio.wait_for(task_resume, timeout=5)

    resumed = _seqs(ws_resume)
    assert resumed == list(range(resumed[0], resumed[-1] + 1)), "续流其后必须连续递增（无空洞）"
    assert resumed[-1] == record_b.events[-1].seq == 7, "必须读到服务端缓冲的尾部"
    assert _events(ws_resume)[-1]["kind"] == RunEventKind.DONE.value
    assert (record_b.status, record_b.is_terminal) == (RunStatus.COMPLETED, True)
    # 两段拼接是 1..终态 的无空洞序列 —— 「断开重连」不掉事件
    assert received + resumed == list(range(1, record_b.events[-1].seq + 1))

    # ------------------------------------- 回看：两路各自完整到**自己的**终态，且全程不串味
    assert a_seqs == list(range(1, record_a.events[-1].seq + 1))
    assert _cross_count(ws_stream_a, record_a) == 0
    assert _cross_count(ws_resume, record_b) == 0
    assert service.registrations == {}, "两条连接收尾都要注销登记"
    assert ws_cancel.closed_code == _GRACEFUL_CLOSE
