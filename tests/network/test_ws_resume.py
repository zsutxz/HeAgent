"""76.1 · 断连续流三判据（AD-5）：无空洞 / 窗口不足必须响 / 重复可见可去重。

四条用例把「可能重复、绝不缺失、超出窗口必须显式失败」落成可跑断言，全部用 fake
``RunWebSocketService`` 驱动真实端点（``build_ws_endpoint``），不跑真 run：

① **无空洞**：连收 N 帧后断开，以第 N 帧的事件 id 作 ``last_event_id`` 重连 ⇒ 续到的首帧
   ``id <= N + 1``、此后连续递增，直到取消终态仍在读（取消后仍可续读到尾部）；
② **窗口不足必须响**：ring buffer 置 1、cursor 落后 ≥2 ⇒ 收到 ``resync_required`` 错误帧，
   且**没有任何 event 帧**先于它发出；反向控制（cursor 恰在窗口边界）**不得**误判为 resync；
③ **重复可见可去重**：重放窗口与本地已有事件重叠时重复确实被收到，按事件 id 去重后条数
   == 服务端事件总数（客户端去重即可收敛，服务端不承诺恰好一次）；
④ **run 已清理**：``run()`` 回 ``None`` ⇒ 具名错误帧 ``unknown_run``，**不是静默空流**。

记录用生产的 ``_RunRecord``（真实有界 ring buffer + 广播队列），游标判据用生产的
``cursor_out_of_window``——本文件测的是端点接线，不是自己重写的算术。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from heagent.network.http_protocol import HttpErrorCode, RunEventKind, RunStatus, cursor_out_of_window
from heagent.network.http_server.records import _RunRecord
from heagent.network.ws_protocol import WS_CLOSE_POLICY
from heagent.network.ws_server import build_ws_endpoint

#: 客户端在第一次连接上收到多少帧后才断线（够看出「首帧 / 连续 / 终态」三段即可）。
_FIRST_SESSION_FRAMES = 5


class WebSocketDisconnect(Exception):
    """与 Starlette 同名：``_next_command`` 按类型名判「对端断开」。"""


class _ResumeWebSocket:
    """``WebSocketLike`` 替身：发满 ``stop_after`` 帧即模拟客户端读循环结束（断线）。"""

    def __init__(self, run_id: str, *, last_event_id: int | None = None, stop_after: int | None = None) -> None:
        self.scope: dict[str, Any] = {}
        self.path_params: dict[str, Any] = {"run_id": run_id}
        self.query_params: dict[str, Any] = {} if last_event_id is None else {"last_event_id": str(last_event_id)}
        self._stop_after = stop_after
        self._disconnected = asyncio.Event()
        self.sent: list[str] = []
        # 端点会 close 两次（错误帧的 POLICY 关闭 + 骨架收尾的默认关闭），故按序全记。
        self.close_codes: list[int] = []

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000) -> None:
        self.close_codes.append(code)

    async def receive_text(self) -> str:
        await self._disconnected.wait()
        raise WebSocketDisconnect()

    async def send_text(self, data: str) -> None:
        self.sent.append(data)
        if self._stop_after is not None and len(self.sent) >= self._stop_after:
            self._disconnected.set()

    @property
    def frames(self) -> list[dict[str, Any]]:
        return [json.loads(frame) for frame in self.sent]


class _ResumeService:
    """``RunWebSocketService`` 替身：只持有记录，不起 run、不做取消。

    ``needs_resync`` 用生产的 :func:`cursor_out_of_window`（与 ``HttpRunService`` 同一份算术），
    因此「窗口不足」判据不依赖本文件自造的公式。
    """

    _closing = False

    def __init__(self, *records: _RunRecord) -> None:
        self._runs = {record.run_id: record for record in records}

    def run(self, run_id: str) -> _RunRecord | None:
        return self._runs.get(run_id)

    def needs_resync(self, record: _RunRecord, last_event_id: int | None) -> bool:
        return cursor_out_of_window(last_event_id, record.oldest_seq)

    async def start_run(self, prompt: str) -> Any:  # pragma: no cover - 本文件不提交 run
        raise AssertionError("resume 用例不该走到提交路径")

    async def cancel_run(self, run_id: str) -> _RunRecord | None:  # pragma: no cover - 本文件不发取消命令
        return self.run(run_id)

    def register_ws(self, connection_id: str, run_id: str, websocket: Any) -> None:
        return None

    def unregister_ws(self, connection_id: str) -> None:
        return None


def _origin_ok(_scope: dict[str, Any]) -> None:
    """``OriginCheck`` 替身：本机同源口径，恒通过。"""
    return None


async def _subscribe(service: _ResumeService, ws: _ResumeWebSocket) -> _ResumeWebSocket:
    """跑完一遍端点会话（重放 → 跟随 → 收尾 / 握手门回错误帧），返回同一个连接替身。

    ``version`` 留空 ⇒ 没有 hello 帧，``sent`` 里只有事件帧与错误帧，断言不必跳首帧。
    """
    endpoint = build_ws_endpoint(service, origin_violation=_origin_ok, max_connections=4, version="")
    await asyncio.wait_for(endpoint(ws), timeout=5)
    return ws


def _event_seqs(ws: _ResumeWebSocket) -> list[int]:
    """已发出**事件帧**的 seq，顺序即到达顺序（非事件帧在这里被跳过，由别处断言）。"""
    return [frame["event"]["seq"] for frame in ws.frames if frame["type"] == "event"]


def _record(*, buffer_size: int = 16, run_id: str = "run-resume") -> _RunRecord:
    return _RunRecord(run_id, "prompt", buffer_size=buffer_size)


def _append_text(record: _RunRecord, *texts: str) -> None:
    for text in texts:
        record.append(RunEventKind.TEXT, text=text)


@pytest.mark.asyncio
async def test_reconnect_from_the_last_event_id_leaves_no_hole() -> None:
    """① 无空洞：以第 N 帧 id 作 ``last_event_id`` 重连 ⇒ 首帧 ≤ N+1、其后连续递增到取消终态。"""
    record = _record()
    _append_text(record, *(f"live-{index}" for index in range(_FIRST_SESSION_FRAMES)))

    first = await _subscribe(
        _ResumeService(record),
        _ResumeWebSocket(record.run_id, stop_after=_FIRST_SESSION_FRAMES),
    )
    received = _event_seqs(first)
    assert received == list(range(1, _FIRST_SESSION_FRAMES + 1))

    # 断线期间事件照常产生，随后运行被取消（取消后仍必须能续读到尾部）。
    _append_text(record, "while-offline")
    assert record.claim_terminal(RunStatus.CANCELLED) is True
    record.append(RunEventKind.CANCELLED, text="cancelled by user")
    record.close_subscribers()

    second = await _subscribe(
        _ResumeService(record),
        _ResumeWebSocket(record.run_id, last_event_id=received[-1]),
    )
    resumed = _event_seqs(second)

    assert resumed, "续流必须至少发出断线期间新增的那条事件"
    assert resumed[0] <= received[-1] + 1, "首帧不得早于游标的下一号，也不得跳号"
    assert resumed == list(range(resumed[0], resumed[-1] + 1)), "其后必须连续递增（无空洞）"
    assert resumed[-1] == record.events[-1].seq, "必须读到服务端缓冲的尾部"
    assert second.frames[-1]["event"]["kind"] == RunEventKind.CANCELLED.value, "尾部就是取消终态"
    # 两次会话拼起来是一条无空洞的序列 —— 「断开重连」不掉事件。
    assert received + resumed == list(range(1, received[-1] + len(resumed) + 1))


@pytest.mark.asyncio
async def test_a_cursor_behind_the_ring_window_must_fail_loudly_before_any_event() -> None:
    """② 窗口不足必须响：``resync_required`` 错误帧，且**没有任何 event 帧**先于它发出。"""
    record = _record(buffer_size=1)
    _append_text(record, "evicted-1", "evicted-2", "oldest-in-window")
    assert record.oldest_seq == 3

    ws = await _subscribe(_ResumeService(record), _ResumeWebSocket(record.run_id, last_event_id=1))

    frames = ws.frames
    assert [frame["type"] for frame in frames] == ["error"], "只能是这一条错误帧：先发事件再报 resync 即违约"
    assert frames[0]["error"]["error"]["code"] == HttpErrorCode.RESYNC_REQUIRED.value
    assert WS_CLOSE_POLICY in ws.close_codes, "窗口不足按策略码关闭，客户端据此改走会话快照"

    # 反向控制：游标恰在窗口边界（oldest_seq - 1）**不得**误判 resync，须照常续读。
    boundary = await _subscribe(
        _ResumeService(record),
        _ResumeWebSocket(record.run_id, last_event_id=record.oldest_seq - 1, stop_after=1),
    )
    assert _event_seqs(boundary) == [3]
    assert "error" not in [frame["type"] for frame in boundary.frames]


@pytest.mark.asyncio
async def test_overlapping_replay_is_visible_and_dedupes_by_event_id() -> None:
    """③ 重复可见可去重：重放重叠 ⇒ 同一 id 收到两次；按 id 去重后恰好是服务端事件全集。"""
    record = _record()
    _append_text(record, "a", "b", "c", "d")

    first = await _subscribe(_ResumeService(record), _ResumeWebSocket(record.run_id, stop_after=4))
    local = _event_seqs(first)
    assert local == [1, 2, 3, 4]

    # 断线期间产生一条新事件后运行终态收尾（终态事件在流结束标记之前）。
    _append_text(record, "e")
    assert record.claim_terminal(RunStatus.COMPLETED) is True
    record.append(RunEventKind.DONE)
    record.close_subscribers()

    # 客户端把游标回退到 2（失忆重连）⇒ 服务端重放 3..6，与本地已有的 3、4 重叠。
    second = await _subscribe(_ResumeService(record), _ResumeWebSocket(record.run_id, last_event_id=2))
    replay = _event_seqs(second)
    assert replay == [3, 4, 5, 6]
    assert second.frames[-1]["event"]["kind"] == RunEventKind.DONE.value

    merged = local + replay
    assert len(merged) - len(set(merged)) == 2, "重复必须是**可见**的（同一 id 收到两次），不是被服务端悄悄吞掉"
    assert sorted(set(merged)) == [payload.seq for payload in record.events], "按 id 去重后 == 服务端事件总数"


@pytest.mark.asyncio
async def test_a_cleaned_up_run_returns_a_named_error_frame_not_an_empty_stream() -> None:
    """④ run 已清理：``run()`` 回 ``None`` ⇒ ``unknown_run`` 错误帧，不回空流。"""
    ws = await _subscribe(_ResumeService(), _ResumeWebSocket("run-evicted"))

    frames = ws.frames
    assert frames, "静默空流不可接受：客户端会以为「这条 run 没有事件」而不是「记录已清理」"
    assert [frame["type"] for frame in frames] == ["error"]
    assert frames[0]["error"]["error"]["code"] == HttpErrorCode.UNKNOWN_RUN.value
    assert WS_CLOSE_POLICY in ws.close_codes
