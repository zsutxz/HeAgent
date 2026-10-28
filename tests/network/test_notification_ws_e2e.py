"""只读通知流端点端到端契约（Epic 58）：真实 TCP + 真实 websockets 客户端。

与 ``test_cli_ws_e2e.py`` 同手法（``port=0`` + ``serve_forever`` + 真客户端），区别是被测端点
``/api/notifications/ws`` 订阅的是**宿主 cron 的产物**：跨作业、跨执行、无 run 记录、无取消通道、
ack 帧不带 ``RunStatus``。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from heagent.network.http_protocol import CronResultStatus, HttpErrorCode
from heagent.network.notification_hub import NotificationHub
from heagent.network.ws_host import WsServer, WsServerConfig

websockets = pytest.importorskip("websockets")


def _ws_config() -> WsServerConfig:
    return WsServerConfig(port=0, shutdown_timeout=1)


async def _start(hub: NotificationHub | None) -> tuple[WsServer, asyncio.Task[None]]:
    server = WsServer(_ws_config(), notification_hub=hub)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    # 让 serve 循环真正进入 ``main_loop`` 再返回（同 test_cli_ws_e2e 的理由）。
    await asyncio.sleep(0)
    return server, task


async def _stop(server: WsServer, task: asyncio.Task[None]) -> None:
    await server.close()
    await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_notification_ws_streams_cron_results_with_monotonic_seq() -> None:
    hub = NotificationHub(max_connections=2, buffer_size=8)
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    try:
        async with websockets.connect(uri) as ws:
            hub.publish_cron_result(job_id="job-a", status=CronResultStatus.COMPLETED, text="hello", cron="* * * * *")
            hub.publish_cron_result(job_id="job-b", status=CronResultStatus.FAILED, text="boom")
            frames = [json.loads(await ws.recv()) for _ in range(2)]

        assert [frame["type"] for frame in frames] == ["notification"] * 2
        payloads = [frame["notification"] for frame in frames]
        assert [item["kind"] for item in payloads] == ["cron_result"] * 2
        assert [item["seq"] for item in payloads] == [1, 2]
        assert [item["job_id"] for item in payloads] == ["job-a", "job-b"]
        assert [item["status"] for item in payloads] == ["completed", "failed"]
        assert payloads[0]["text"] == "hello"
        assert payloads[0]["cron"] == "* * * * *"
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_notification_ws_cursor_resumes_and_rejects_evicted_cursor() -> None:
    hub = NotificationHub(buffer_size=2)
    server, task = await _start(hub)
    base = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    try:
        for index in range(3):
            hub.publish_cron_result(job_id="job", status=CronResultStatus.COMPLETED, text=f"n{index}")

        async with websockets.connect(f"{base}?last_event_id=1") as ws:
            resumed = [json.loads(await ws.recv()) for _ in range(2)]
        assert [item["notification"]["seq"] for item in resumed] == [2, 3]

        with pytest.raises(websockets.exceptions.ConnectionClosed):
            async with websockets.connect(f"{base}?last_event_id=0") as ws:
                frame = json.loads(await ws.recv())
                assert frame["error"]["error"]["code"] == HttpErrorCode.RESYNC_REQUIRED.value
                await ws.recv()

        with pytest.raises(websockets.exceptions.ConnectionClosed):
            async with websockets.connect(f"{base}?last_event_id=abc") as ws:
                frame = json.loads(await ws.recv())
                assert frame["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
                await ws.recv()
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_notification_ws_ping_acks_with_an_empty_run_id_and_refuses_commands() -> None:
    """只读流：``ping`` 回 ack（无 ``RunStatus``）；``cancel`` / ``run`` 明确拒绝且**不断连**。"""
    hub = NotificationHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send('{"command":"ping"}')
            assert json.loads(await ws.recv()) == {"type": "ack", "command": "ping", "run_id": ""}

            await ws.send('{"command":"cancel"}')
            refused = json.loads(await ws.recv())
            assert refused["type"] == "error"
            assert refused["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
            assert "read-only" in refused["error"]["error"]["message"]

            await ws.send('{"command":"run","prompt":"hi"}')
            refused_run = json.loads(await ws.recv())
            assert refused_run["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value

            # 连接必须还活着：再 ping 一次仍然回 ack。
            await ws.send('{"command":"ping"}')
            assert json.loads(await ws.recv())["type"] == "ack"
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_notification_ws_limit_returns_rate_limited_frame() -> None:
    hub = NotificationHub(max_connections=1)
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
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
async def test_notification_ws_route_does_not_exist_without_a_hub() -> None:
    """未注入中枢 ⇒ 路由不注册；客户端拿到 Uvicorn 在「应用未 accept」时补的 403。"""
    server, task = await _start(None)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
            async with websockets.connect(uri):
                pass
        assert rejected.value.response.status_code == 403
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_notification_ws_shutdown_notifies_and_closes_connections() -> None:
    hub = NotificationHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    ws = await websockets.connect(uri)
    try:
        while hub.connection_count < 1:
            await asyncio.sleep(0)
        await server.close()
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        assert frame["error"]["error"]["code"] == HttpErrorCode.SHUTTING_DOWN.value
        with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
            await asyncio.wait_for(ws.recv(), timeout=2)
        assert closed.value.rcvd.code == 1001
        assert hub.closing is True
    finally:
        await ws.close()
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_notification_ws_rejects_cross_origin_before_accept() -> None:
    hub = NotificationHub()
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
            async with websockets.connect(uri, origin="http://evil.example"):
                pass
        assert rejected.value.response.status_code == 403
        assert hub.subscriber_count == 0
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_notification_ws_reopen_after_close_accepts_new_connections() -> None:
    """``close()`` → ``start()`` 之后必须可用（与 run_service / cli_hub 同一条 AD-5 理由）。"""
    hub = NotificationHub()
    server, task = await _start(hub)
    await _stop(server, task)
    assert hub.closing is True

    await server.start()
    task = asyncio.create_task(server.serve_forever())
    await asyncio.sleep(0)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    try:
        async with websockets.connect(uri) as ws:
            hub.publish_cron_result(job_id="job", status=CronResultStatus.COMPLETED, text="after-restart")
            frame = json.loads(await ws.recv())
        assert frame["notification"]["text"] == "after-restart"
    finally:
        await _stop(server, task)
