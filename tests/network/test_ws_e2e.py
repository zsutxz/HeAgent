"""Epic 54 Story 54-3 端到端契约，Epic 56 D1 起驱动 = WsServer（9001，宿主迁移）。"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import pytest

from heagent.network.http_protocol import HttpErrorCode, RunOutcome, RunStatus
from heagent.network.http_server import HttpRunService, HttpServerConfig
from heagent.network.ws_host import WsServer, WsServerConfig

websockets = pytest.importorskip("websockets")


class _Executor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = 0

    async def __call__(self, prompt: str, publisher: Any) -> RunOutcome:
        publisher.text("hello")
        publisher.tool_call("shell", "echo hello")
        publisher.tool_result("shell", "hello", is_error=False)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return RunOutcome(answer=prompt)


def _server_config(**kwargs: Any) -> HttpServerConfig:
    return HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0, **kwargs)


def _ws_config(**kwargs: Any) -> WsServerConfig:
    return WsServerConfig(port=0, shutdown_timeout=1, **kwargs)


async def _start(
    executor: _Executor, *, ws_limit: int = 4, buffer_size: int = 16
) -> tuple[WsServer, HttpRunService, asyncio.Task[None]]:
    """双配置装配：运行状态机吃 HTTP 配置（进程内注入），WS listener 吃 WsServerConfig（D1 接缝事实）。"""
    service = HttpRunService(
        _server_config(event_buffer_size=buffer_size),
        executor,
    )
    server = WsServer(_ws_config(ws_max_connections=ws_limit), run_service=service)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    # 让 serve 协程先进入 main_loop（防「建任务后立刻 close」的首次调度竞态，同旧注释）。
    await asyncio.sleep(0)
    return server, service, task


async def _stop(server: WsServer, task: asyncio.Task[None]) -> None:
    await server.close()
    await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_ws_replays_events_in_sequence_and_rejects_origin() -> None:
    executor = _Executor()
    server, service, task = await _start(executor)
    record = await service.start_run("answer")
    await executor.started.wait()
    executor.release.set()
    while not record.is_terminal:
        await asyncio.sleep(0)
    uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
    try:
        async with websockets.connect(uri) as ws:
            frames = [json.loads(await ws.recv()) for _ in range(len(record.events))]
        assert [frame["type"] for frame in frames] == ["event"] * len(record.events)
        assert [frame["event"]["seq"] for frame in frames] == list(range(1, len(record.events) + 1))
        assert [frame["event"]["kind"] for frame in frames] == [event.kind.value for event in record.events]

        with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
            async with websockets.connect(uri, origin="http://evil.example"):
                pass
        assert rejected.value.response.status_code == 403
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_ws_cursor_resumes_and_rejects_expired_cursor() -> None:
    executor = _Executor()
    server, service, task = await _start(executor, buffer_size=3)
    record = await service.start_run("answer")
    await executor.started.wait()
    executor.release.set()
    while not record.is_terminal:
        await asyncio.sleep(0)
    uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws?last_event_id=2"
    try:
        async with websockets.connect(uri) as ws:
            frames = [json.loads(await ws.recv()) for _ in range(2)]
        assert [frame["type"] for frame in frames] == ["event", "event"]
        assert [frame["event"]["seq"] for frame in frames] == [3, 4]

        stale = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws?last_event_id=0"
        async with websockets.connect(stale) as ws:
            error = json.loads(await ws.recv())
            assert error["type"] == "error"
            assert error["error"]["error"]["code"] == HttpErrorCode.RESYNC_REQUIRED.value
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_ws_cancel_is_idempotent_and_disconnect_does_not_cancel_run() -> None:
    executor = _Executor()
    server, service, task = await _start(executor)
    record = await service.start_run("answer")
    await executor.started.wait()
    uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send('{"command":"cancel"}')
            ack = json.loads(await ws.recv())
            assert ack["type"] in {"event", "ack"}
            received = [ack]
            while True:
                try:
                    received.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=1)))
                except (TimeoutError, websockets.exceptions.ConnectionClosed):
                    break
            assert any(item.get("type") == "ack" and item.get("command") == "cancel" for item in received)
        assert record.status is RunStatus.CANCELLED
        assert executor.cancelled == 1
        assert service.ws_connection_count(record) == 0
        assert service.subscriber_count(record) == 0
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_ws_limit_errors_and_sse_subscriber_count_remains_independent() -> None:
    executor = _Executor()
    server, service, task = await _start(executor, ws_limit=1)
    record = await service.start_run("answer")
    await executor.started.wait()
    first_uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
    first = await websockets.connect(first_uri)
    try:
        second = await websockets.connect(first_uri)
        async with second:
            frame = json.loads(await second.recv())
            assert frame["type"] == "error"
            assert frame["error"]["error"]["code"] == HttpErrorCode.RATE_LIMITED.value
        assert service.ws_connection_count(record) == 1
        assert service.subscriber_count(record) == 0
        await first.close()
        await asyncio.sleep(0)
        assert service.ws_connection_count(record) == 0
        assert record.status is RunStatus.RUNNING
        executor.release.set()
        await asyncio.wait_for(service._run_tasks[record.run_id], timeout=2)
        assert record.status is RunStatus.COMPLETED
    finally:
        await first.close()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_concurrent_ws_limit_accepts_exactly_n_and_rejects_n_plus_one() -> None:
    executor = _Executor()
    server, service, task = await _start(executor, ws_limit=2)
    record = await service.start_run("answer")
    await executor.started.wait()
    uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
    clients: list[Any] = []
    try:
        clients = await asyncio.gather(websockets.connect(uri), websockets.connect(uri))
        while service.ws_connection_count(record) < 2:
            await asyncio.sleep(0)
        third = await websockets.connect(uri)
        async with third:
            frame = json.loads(await third.recv())
            assert frame["type"] == "error"
            assert frame["error"]["error"]["code"] == HttpErrorCode.RATE_LIMITED.value
        assert service.ws_connection_count(record) == 2
        assert service.subscriber_count(record) == 0
    finally:
        for client in clients:
            await client.close()
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_shutdown_closes_websocket_and_cancels_run_within_budget() -> None:
    executor = _Executor()
    server, service, task = await _start(executor, ws_limit=2)
    record = await service.start_run("answer")
    await executor.started.wait()
    uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
    ws = await websockets.connect(uri)
    try:
        while service.ws_connection_count(record) == 0:
            await asyncio.sleep(0)
        started = asyncio.get_running_loop().time()
        # 入口层编排口径：HTTP 侧先排空运行到终态（service.close），WS 侧再关连接与 listener。
        await service.close()
        await server.close()
        elapsed = asyncio.get_running_loop().time() - started
        frames: list[dict[str, Any]] = []
        with contextlib.suppress(websockets.exceptions.ConnectionClosed):
            while True:
                frames.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=0.2)))
        assert any(
            frame.get("type") == "error" and frame["error"]["error"]["code"] == HttpErrorCode.SHUTTING_DOWN.value
            for frame in frames
        )
        assert ws.close_code == 1001
        assert record.status is RunStatus.CANCELLED
        assert service.ws_connection_count(record) == 0
        assert elapsed <= 2 * server.config.shutdown_timeout + 2
        # main_loop 以 0.1s 轮询 should_exit：显式等 serve 任务退出，不和调度竞速。
        await asyncio.wait_for(task, timeout=5)
        assert task.done()
    finally:
        await ws.close()
        if not task.done():
            await _stop(server, task)


@pytest.mark.asyncio
async def test_invalid_cursor_and_malformed_command_get_stable_error_frames() -> None:
    executor = _Executor()
    server, service, task = await _start(executor)
    record = await service.start_run("answer")
    await executor.started.wait()
    bad_cursor = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws?last_event_id=abc"
    try:
        async with websockets.connect(bad_cursor) as ws:
            frame = json.loads(await ws.recv())
            assert frame["type"] == "error"
            assert frame["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value

        async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws") as ws:
            await ws.send("{}")
            frame = json.loads(await ws.recv())
            while frame["type"] == "event":
                frame = json.loads(await ws.recv())
            assert frame["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value

        async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws") as ws:
            await ws.send("x" * 4097)
            with pytest.raises(websockets.exceptions.ConnectionClosedError) as closed:
                while True:
                    await ws.recv()
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 1009
    finally:
        executor.release.set()
        await _stop(server, task)
