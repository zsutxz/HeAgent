"""通用只读事件流中枢的单元契约（Epic 58 D3）：seq / 缓冲 / 游标 / 背压 / 关停。

这里测的是**核**（``EventStreamHub``），不看任何具体端点：两个子类（CLI 旁路 / 通知流）
的语义差异在各自的测试文件里钉。用最小载荷模型，避免核的测试被业务字段拖成集成测试。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import BaseModel

from heagent.network.event_stream_hub import EventStreamHub


class _Payload(BaseModel):
    """核只要求 ``seq`` 一个字段（游标的全部依赖）。"""

    seq: int
    text: str = ""


class _Hub(EventStreamHub[_Payload]):
    """把受保护的 ``_emit`` 暴露成一条发布便利方法（只为测试形态服务）。"""

    def __init__(self, *, buffer_size: int = 4, max_connections: int = 16) -> None:
        super().__init__(
            buffer_size=buffer_size,
            log_prefix="test_ws",
            stream_label="stream_id",
            max_connections=max_connections,
        )

    def publish(self, text: str = "x", *, stream_id: str = "s1", fail: bool = False) -> None:
        def build(seq: int) -> _Payload:
            if fail:
                raise RuntimeError("boom")
            return _Payload(seq=seq, text=text)

        self._emit(stream_id, build)


class _FakeSocket:
    """``close_websockets`` 只需要 ``send_text`` 与 ``close`` 两件事。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed_with: int | None = None

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


def test_core_rejects_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="max_connections"):
        _Hub(max_connections=0)
    with pytest.raises(ValueError, match="buffer_size"):
        _Hub(buffer_size=0)


def test_seq_is_monotonic_across_stream_ids() -> None:
    hub = _Hub()
    hub.publish("a", stream_id="first")
    hub.publish("b", stream_id="second")
    hub.publish("c", stream_id="first")

    published = hub.published_events
    assert [stream_id for stream_id, _ in published] == ["first", "second", "first"]
    assert [payload.seq for _, payload in published] == [1, 2, 3]


def test_a_failed_build_does_not_consume_a_seq() -> None:
    """载荷校验失败只能是「少一条事件」，不能让 seq 出现空洞（否则客户端游标会误判 resync）。"""
    hub = _Hub()
    hub.publish("dropped", fail=True)
    hub.publish("kept")

    published = hub.published_events
    assert len(published) == 1
    assert published[0][1].seq == 1
    assert published[0][1].text == "kept"


def test_cursor_replay_and_resync_window() -> None:
    hub = _Hub(buffer_size=3)
    for index in range(4):
        hub.publish(str(index))

    assert hub.oldest_seq == 2
    assert hub.needs_resync(1) is False  # 1 之后的都还在
    assert hub.needs_resync(0) is True
    assert hub.needs_resync(None) is True  # 从头读也补齐不了开头
    assert hub.needs_resync(-5) is True

    subscription = hub.open_subscription(2)
    assert subscription is not None
    assert [payload.seq for _, payload in subscription.backlog] == [3, 4]


def test_connection_limit_returns_none_then_recovers_after_removal() -> None:
    hub = _Hub(max_connections=1)
    first = hub.open_subscription(None)
    assert first is not None
    assert hub.open_subscription(None) is None
    hub.remove_subscriber(first.queue)
    assert hub.open_subscription(None) is not None


def test_lagging_subscriber_is_ended_instead_of_losing_events_silently() -> None:
    hub = _Hub(buffer_size=2)
    subscription = hub.open_subscription(None)
    assert subscription is not None
    for index in range(3):
        hub.publish(str(index))

    assert hub.subscriber_count == 0
    drained: list[object] = []
    while True:
        try:
            drained.append(subscription.queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    assert drained[-1] is None


def test_ws_registry_and_shutdown_flag_are_idempotent() -> None:
    hub = _Hub()
    hub.register_ws("c1", "s1", object())
    hub.register_ws("c2", "s2", object())
    assert hub.connection_count == 2
    hub.unregister_ws("c1")
    hub.unregister_ws("missing")
    assert hub.connection_count == 1

    hub.close()
    assert hub.closing is True
    hub.reopen()
    assert hub.closing is False


@pytest.mark.asyncio
async def test_close_websockets_is_a_noop_without_connections() -> None:
    hub = _Hub()
    await hub.close_websockets(timeout=0.1)
    assert hub.connection_count == 0


@pytest.mark.asyncio
async def test_close_websockets_sends_shutting_down_and_closes_with_1001() -> None:
    hub = _Hub()
    socket = _FakeSocket()
    hub.register_ws("c1", "s1", socket)

    await hub.close_websockets(timeout=1)

    assert socket.sent[0]["type"] == "error"
    assert socket.sent[0]["error"]["error"]["code"] == "shutting_down"
    assert socket.closed_with == 1001
    assert hub.connection_count == 0


@pytest.mark.asyncio
async def test_a_socket_that_raises_does_not_block_the_others() -> None:
    """关停时单条连接发帧失败不得拖住整条收尾（登记仍回收）。"""

    class _Broken:
        async def send_text(self, data: str) -> None:
            raise RuntimeError("socket gone")

        async def close(self, code: int = 1000) -> None:
            raise RuntimeError("socket gone")

    hub = _Hub()
    healthy = _FakeSocket()
    hub.register_ws("broken", "s1", _Broken())
    hub.register_ws("healthy", "s2", healthy)

    await hub.close_websockets(timeout=1)

    assert hub.connection_count == 0
    assert healthy.closed_with == 1001
