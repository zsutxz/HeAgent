"""CLI 旁路 WS 端点端到端契约（Epic 55）：真实 TCP + 真实 websockets 客户端。

与 ``test_http_ws_e2e.py`` 同手法（``port=0`` + ``serve_forever`` + 真客户端），区别是被测端点
``/api/cli/ws`` 订阅的是**终端自己那一轮** run（跨轮次、无 run 记录、无取消通道）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from heagent.network.cli_event_hub import CliEventHub
from heagent.network.http_protocol import HttpErrorCode
from heagent.network.http_server import HttpServer, HttpServerConfig

websockets = pytest.importorskip("websockets")


def _server_config(**kwargs: Any) -> HttpServerConfig:
    return HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0, **kwargs)


async def _start(hub: CliEventHub | None, **config_kwargs: Any) -> tuple[HttpServer, asyncio.Task[None]]:
    server = HttpServer(_server_config(**config_kwargs), version="test", cli_hub=hub)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    # 让 serve 循环真正进入 ``main_loop`` 再返回：否则「建任务后立刻 close()」的用例里
    # 协程体可能在 ``_server`` 已被置空之后才第一次被调度，直接抛 RuntimeError。
    await asyncio.sleep(0)
    return server, task


async def _stop(server: HttpServer, task: asyncio.Task[None]) -> None:
    await server.close()
    await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_cli_ws_streams_events_with_run_id_and_monotonic_seq() -> None:
    hub = CliEventHub(max_connections=2, buffer_size=8)
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        async with websockets.connect(uri) as ws:
            run_id = hub.begin_run()
            hub.publish_text("hello")
            hub.publish_tool_call("shell", "echo hi")
            hub.publish_done("finished")
            frames = [json.loads(await ws.recv()) for _ in range(3)]

        assert [frame["type"] for frame in frames] == ["event"] * 3
        assert {frame["run_id"] for frame in frames} == {run_id}
        assert [frame["event"]["seq"] for frame in frames] == [1, 2, 3]
        assert [frame["event"]["kind"] for frame in frames] == ["text", "tool_call", "done"]
        assert frames[1]["event"]["tool_target"] == "echo hi"
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_cursor_resumes_and_rejects_evicted_cursor() -> None:
    hub = CliEventHub(buffer_size=3)
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        hub.begin_run()
        for _ in range(4):
            hub.publish_text("x")

        async with websockets.connect(f"{uri}?last_event_id=2") as ws:
            replay = [json.loads(await ws.recv()) for _ in range(2)]
        assert [frame["event"]["seq"] for frame in replay] == [3, 4]

        async with websockets.connect(f"{uri}?last_event_id=0") as ws:
            stale = json.loads(await ws.recv())
        assert stale["type"] == "error"
        assert stale["error"]["error"]["code"] == HttpErrorCode.RESYNC_REQUIRED.value

        async with websockets.connect(f"{uri}?last_event_id=abc") as ws:
            malformed = json.loads(await ws.recv())
        assert malformed["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_ping_acks_but_cancel_is_refused_without_closing() -> None:
    """旁路是观众席：``cancel`` 明确拒绝，且**不断连接**（客户端可以继续用）。"""
    hub = CliEventHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        async with websockets.connect(uri) as ws:
            run_id = hub.begin_run()
            await ws.send('{"command":"ping"}')
            ack = json.loads(await ws.recv())
            assert ack == {"type": "ack", "command": "ping", "run_id": run_id}

            await ws.send('{"command":"cancel"}')
            refused = json.loads(await ws.recv())
            assert refused["type"] == "error"
            assert refused["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
            assert "cancel is not supported" in refused["error"]["error"]["message"]

            # 连接必须还活着：再 ping 一次仍然回 ack。
            await ws.send('{"command":"ping"}')
            assert json.loads(await ws.recv())["type"] == "ack"
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_ack_reports_an_empty_run_id_when_nothing_is_running() -> None:
    hub = CliEventHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send('{"command":"ping"}')
            assert json.loads(await ws.recv())["run_id"] == ""
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_limit_returns_rate_limited_frame() -> None:
    hub = CliEventHub(max_connections=1)
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    first = await websockets.connect(uri)
    try:
        while hub.subscriber_count < 1:
            await asyncio.sleep(0)
        second = await websockets.connect(uri)
        async with second:
            frame = json.loads(await second.recv())
            assert frame["type"] == "error"
            assert frame["error"]["error"]["code"] == HttpErrorCode.RATE_LIMITED.value
        assert hub.subscriber_count == 1
    finally:
        await first.close()
        await asyncio.sleep(0)
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_rejects_cross_origin_before_accept() -> None:
    hub = CliEventHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
            async with websockets.connect(uri, origin="http://evil.example"):
                pass
        assert rejected.value.response.status_code == 403
        assert hub.subscriber_count == 0
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_route_does_not_exist_without_a_hub() -> None:
    """未注入中枢 ⇒ 路由不注册。客户端拿到的是 Uvicorn 在「应用未 accept」时补的 403。

    刻意不断言 404：路由缺失发生在 ASGI 层之下，Uvicorn 统一用 403 拒绝升级，客户端因此**只能**
    从「没有帧、连接立刻结束」判断这条流不存在（应用层 404 是另一层）。
    """
    server, task = await _start(None)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
            async with websockets.connect(uri):
                pass
        assert rejected.value.response.status_code == 403
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_shutdown_notifies_and_closes_connections() -> None:
    hub = CliEventHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    ws = await websockets.connect(uri)
    try:
        while hub.connection_count < 1:
            await asyncio.sleep(0)
        await server.close()
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        assert frame["type"] == "error"
        assert frame["error"]["error"]["code"] == HttpErrorCode.SHUTTING_DOWN.value
        with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
            await asyncio.wait_for(ws.recv(), timeout=2)
        assert closed.value.rcvd.code == 1001
        # 关停后中枢处于「停止接收」：此刻进来的连接一律收 shutting_down（与 run_service 同序）。
        assert hub.closing is True
    finally:
        await ws.close()
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_cli_ws_reopen_after_close_accepts_new_connections() -> None:
    """``close()`` → ``start()`` 之后必须可用（与 ``run_service.reopen`` 同一条 AD-5 理由）。"""
    hub = CliEventHub()
    server, task = await _start(hub)
    await _stop(server, task)

    await server.start()
    task = asyncio.create_task(server.serve_forever())
    await asyncio.sleep(0)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        hub.begin_run()
        hub.publish_text("again")
        async with websockets.connect(uri) as ws:
            frame = json.loads(await ws.recv())
        assert frame["event"]["kind"] == "text"
        assert frame["event"]["text"] == "again"
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_refuses_new_connections_while_closing() -> None:
    hub = CliEventHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        hub.close()
        async with websockets.connect(uri) as ws:
            frame = json.loads(await ws.recv())
            assert frame["type"] == "error"
            assert frame["error"]["error"]["code"] == HttpErrorCode.SHUTTING_DOWN.value
            with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
                await asyncio.wait_for(ws.recv(), timeout=2)
            assert closed.value.rcvd.code == 1001
        assert hub.subscriber_count == 0
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_internal_failure_is_an_error_frame_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """中枢内部炸了：客户端拿脱敏的 ``server_error`` + 1011，而不是裸断连。"""
    hub = CliEventHub()

    def _boom(cursor: int | None) -> None:
        raise RuntimeError("hub exploded")

    monkeypatch.setattr(hub, "open_subscription", _boom)
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        async with websockets.connect(uri) as ws:
            frame = json.loads(await ws.recv())
            assert frame["type"] == "error"
            assert frame["error"]["error"]["code"] == HttpErrorCode.SERVER_ERROR.value
            assert "exploded" not in json.dumps(frame)
            with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
                await asyncio.wait_for(ws.recv(), timeout=2)
            assert closed.value.rcvd.code == 1011
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_malformed_command_closes_with_policy_violation() -> None:
    hub = CliEventHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send("not json")
            frame = json.loads(await ws.recv())
            assert frame["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
            with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
                await asyncio.wait_for(ws.recv(), timeout=2)
            assert closed.value.rcvd.code == 1008
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_cli_ws_oversized_command_closes_with_too_large() -> None:
    hub = CliEventHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/cli/ws"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send("x" * 5000)
            with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
                await asyncio.wait_for(ws.recv(), timeout=2)
            assert closed.value.rcvd.code == 1009
    finally:
        await _stop(server, task)
