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
from heagent.network.ws_protocol import WS_MAX_COMMAND_CHARS

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
            # 56-3 起非 `run` 帧守小上限（`WS_MAX_COMMAND_CHARS`）：超限 ⇒ 1009。
            await ws.send(json.dumps({"command": "ping", "pad": "x" * (WS_MAX_COMMAND_CHARS + 100)}))
            with pytest.raises(websockets.exceptions.ConnectionClosedError) as closed:
                while True:
                    await ws.recv()
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 1009
    finally:
        executor.release.set()
        await _stop(server, task)


# ---- Epic 56 Story 56-2：对外模式认证与 TLS（真实 listener）----

TLS_CERT = "tests/fixtures/ws_tls/cert.pem"
TLS_KEY = "tests/fixtures/ws_tls/key.pem"


async def _start_external(
    executor: _Executor, *, token: str = "s3cret", tls: bool = False
) -> tuple[WsServer, HttpRunService, asyncio.Task[None]]:
    """对外模式装配：非回环绑定（``0.0.0.0``）+ token，客户端仍走回环地址连接。"""
    service = HttpRunService(_server_config(), executor)
    config = _ws_config(
        host="0.0.0.0",
        auth_token=token,
        tls_cert_file=TLS_CERT if tls else None,
        tls_key_file=TLS_KEY if tls else None,
    )
    server = WsServer(config, run_service=service)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    await asyncio.sleep(0)
    return server, service, task


@pytest.mark.asyncio
async def test_external_mode_rejects_missing_and_wrong_tokens_before_accept() -> None:
    """D3：缺失 / 错误 token 都在 accept 之前被拒（客户端拿 HTTP 403，无错误信封）。"""
    executor = _Executor()
    server, service, task = await _start_external(executor)
    record = await service.start_run("answer")
    await executor.started.wait()
    uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
    try:
        for headers in ([], [("authorization", "Bearer wrong")], [("authorization", "Basic s3cret")]):
            with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
                async with websockets.connect(uri, additional_headers=headers):
                    pass
            assert rejected.value.response.status_code == 403
        # 正确 token：照常订阅（事件的端到端语义与本地模式逐字相同）。
        async with websockets.connect(uri, additional_headers=[("authorization", "Bearer s3cret")]) as ws:
            frame = json.loads(await ws.recv())
        assert frame["type"] == "event"
        assert frame["event"]["seq"] == 1
        for _ in range(50):  # 端点收尾在另一任务里：等登记注销（避免与调度竞速）
            if service.ws_connection_count(record) == 0:
                break
            await asyncio.sleep(0.01)
        assert service.ws_connection_count(record) == 0  # 连接已正常收尾
    finally:
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_external_mode_throttles_repeated_auth_failures() -> None:
    """连续失败达到阈值后仍回 403（对外表现不变），服务端日志给 ``auth_throttled``。"""
    executor = _Executor()
    server, service, task = await _start_external(executor)
    record = await service.start_run("answer")
    await executor.started.wait()
    uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
    try:
        for _ in range(12):  # 默认阈值 10：前 10 次 invalid，之后 throttled
            with pytest.raises(websockets.exceptions.InvalidStatus):
                async with websockets.connect(uri, additional_headers=[("authorization", "Bearer wrong")]):
                    pass
        # 正确 token 从同一来源来：已被限速 ⇒ 仍然 403（限速窗口内不给通过）。
        with pytest.raises(websockets.exceptions.InvalidStatus):
            async with websockets.connect(uri, additional_headers=[("authorization", "Bearer s3cret")]):
                pass
    finally:
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_tls_listener_accepts_wss_and_rejects_plaintext() -> None:
    """D4：cert/key 配齐即 wss；同一 listener 上的明文 ws:// 握手失败。"""
    import ssl

    executor = _Executor()
    server, service, task = await _start_external(executor, tls=True)
    record = await service.start_run("answer")
    await executor.started.wait()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        async with websockets.connect(
            f"wss://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws",
            ssl=context,
            additional_headers=[("authorization", "Bearer s3cret")],
        ) as ws:
            frame = json.loads(await ws.recv())
        assert frame["type"] == "event"

        with pytest.raises((websockets.exceptions.WebSocketException, OSError, EOFError)):
            async with websockets.connect(
                f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws",
                additional_headers=[("authorization", "Bearer s3cret")],
            ):
                pass
    finally:
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_external_plaintext_and_ignored_token_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    """D4/D5 的可观测性：对外明文必须有 WARNING；本地模式配了 token 必须说明它不生效。"""
    import logging

    executor = _Executor()
    with caplog.at_level(logging.WARNING, logger="heagent.network.ws_host"):
        server, _service, task = await _start_external(executor)
        await _stop(server, task)
        local = WsServer(_ws_config(auth_token="s3cret"), run_service=HttpRunService(_server_config(), executor))
        await local.start()
        local_task = asyncio.create_task(local.serve_forever())
        await asyncio.sleep(0)
        await _stop(local, local_task)
    messages = [record.getMessage() for record in caplog.records]
    assert any("plaintext_external" in message for message in messages)
    assert any("auth_token_ignored" in message for message in messages)


# ---- Epic 56 Story 56-3：经 WS 提交 run（集合级端点 /api/runs/ws）----


async def _submit_uri(server: WsServer) -> str:
    return f"ws://127.0.0.1:{server.port}/api/runs/ws"


@pytest.mark.asyncio
async def test_submit_run_acks_then_subscribe_sees_monotonic_events_and_cancel_works() -> None:
    """D2 期一形状：提交 → ack(run_id) → 订阅既有单 run 端点 → 事件 seq 单调 → cancel 等价 DELETE。"""
    executor = _Executor()
    server, service, task = await _start(executor)
    try:
        async with websockets.connect(await _submit_uri(server)) as submit:
            await submit.send(json.dumps({"command": "run", "prompt": "answer"}))
            ack = json.loads(await submit.recv())
        assert ack["type"] == "ack"
        assert ack["command"] == "run"
        assert ack["status"] == "running"
        run_id = ack["run_id"]
        assert service.run(run_id) is not None

        await executor.started.wait()
        executor.release.set()
        async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/{run_id}/ws") as ws:
            frames = [json.loads(await ws.recv()) for _ in range(4)]
        assert [frame["type"] for frame in frames] == ["event"] * 4
        assert [frame["event"]["seq"] for frame in frames] == [1, 2, 3, 4]

        # 再提交一次（前一次已终态）：拿到新 run_id，然后经单 run 端点 cancel（等价 DELETE）。
        executor2 = _Executor()
        service._executor = executor2  # type: ignore[attr-defined]
        async with websockets.connect(await _submit_uri(server)) as submit:
            await submit.send(json.dumps({"command": "run", "prompt": "second"}))
            second = json.loads(await submit.recv())
        await executor2.started.wait()
        async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/{second['run_id']}/ws") as ws:
            await ws.send('{"command":"cancel"}')
            while True:
                frame = json.loads(await ws.recv())
                if frame.get("type") == "ack" and frame.get("command") == "cancel":
                    break
        assert service.run(second["run_id"]).status is RunStatus.CANCELLED
    finally:
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_submit_run_conflict_and_shutting_down_semantics() -> None:
    """名额满 ⇒ ``run_conflict``（不排队）；错误帧**不断连**，同一连接可继续提交。"""
    executor = _Executor()
    server, service, task = await _start(executor)
    try:
        async with websockets.connect(await _submit_uri(server)) as submit:
            await submit.send(json.dumps({"command": "run", "prompt": "first"}))
            assert json.loads(await submit.recv())["type"] == "ack"
            await submit.send(json.dumps({"command": "run", "prompt": "second"}))
            conflict = json.loads(await submit.recv())
            assert conflict["type"] == "error"
            assert conflict["error"]["error"]["code"] == HttpErrorCode.RUN_CONFLICT.value
            assert service.active_runs == 1
            # 连接仍可用：ping 回连接级 ack（无 run 绑定 ⇒ run_id 空串）。
            await submit.send('{"command":"ping"}')
            ping = json.loads(await submit.recv())
            assert ping == {"type": "ack", "command": "ping", "run_id": ""}
            # cancel 在集合端点没有对象：回错误帧、不断连。
            await submit.send('{"command":"cancel"}')
            rejected = json.loads(await submit.recv())
            assert rejected["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
            await submit.send('{"command":"ping"}')
            assert json.loads(await submit.recv())["command"] == "ping"
    finally:
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_submit_validates_prompt_like_the_http_endpoint() -> None:
    """与 ``POST /api/runs`` **逐字等价**：空白 ⇒ ``empty_prompt``；空串/超长 ⇒ ``invalid_request``。

    「空串为什么不是 empty_prompt」不是本 story 的判断——那是 `RunRequest` 既有口径
    （`min_length=1` 先于 field validator 触发），WS 侧刻意不去改写它，否则两条入口会分叉。
    """
    from heagent.network.http_protocol import MAX_PROMPT_CHARS

    executor = _Executor()
    server, service, task = await _start(executor)
    try:
        async with websockets.connect(await _submit_uri(server)) as submit:
            blank_cases = {
                "   \n\t ": HttpErrorCode.EMPTY_PROMPT,
                "": HttpErrorCode.INVALID_REQUEST,
            }
            for prompt, expected in blank_cases.items():
                await submit.send(json.dumps({"command": "run", "prompt": prompt}))
                frame = json.loads(await submit.recv())
                assert frame["error"]["error"]["code"] == expected.value, repr(prompt)
            assert service.active_runs == 0

            await submit.send(json.dumps({"command": "run", "prompt": "中" * (MAX_PROMPT_CHARS + 1)}))
            too_long = json.loads(await submit.recv())
            assert too_long["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
            assert service.active_runs == 0

            # 协议允许的最大 prompt 必须能过传输层（帧上限与 HTTP 请求体上限同源）。
            await submit.send(json.dumps({"command": "run", "prompt": "中" * MAX_PROMPT_CHARS}, ensure_ascii=False))
            ack = json.loads(await submit.recv())
            assert ack["type"] == "ack"
            assert service.active_runs == 1
    finally:
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_single_run_endpoint_rejects_the_run_command() -> None:
    """提交能力不外溢：单 run 端点与 CLI 旁路收到 ``run`` 一律 invalid_request 且不断连。"""
    executor = _Executor()
    server, service, task = await _start(executor)
    record = await service.start_run("answer")
    await executor.started.wait()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws") as ws:
            await ws.send(json.dumps({"command": "run", "prompt": "hijack"}))
            while True:
                frame = json.loads(await ws.recv())
                if frame["type"] == "error":
                    break
            assert frame["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
            await ws.send('{"command":"ping"}')
            while True:
                frame = json.loads(await ws.recv())
                if frame["type"] == "ack":
                    break
            assert frame["command"] == "ping"
        assert service.active_runs == 1  # 未额外创建运行
    finally:
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_submit_connections_have_their_own_atomic_slot_pool() -> None:
    """提交连接也受额度约束（Uvicorn 的 limit_concurrency 不约束 WS）：满额回 rate_limited。"""
    executor = _Executor()
    server, _service, task = await _start(executor, ws_limit=1)
    try:
        first = await websockets.connect(await _submit_uri(server))
        async with first:
            second = await websockets.connect(await _submit_uri(server))
            async with second:
                frame = json.loads(await second.recv())
                assert frame["type"] == "error"
                assert frame["error"]["error"]["code"] == HttpErrorCode.RATE_LIMITED.value
        # 席位随连接关闭归还：额度恢复，可再连。
        for _ in range(50):
            try:
                third = await websockets.connect(await _submit_uri(server))
            except Exception:  # 端口/握手竞态：重试
                await asyncio.sleep(0.02)
                continue
            async with third:
                await third.send('{"command":"ping"}')
                assert json.loads(await third.recv())["command"] == "ping"
            break
        else:  # pragma: no cover - 只在连接始终失败时触发
            pytest.fail("submit slot was never released")
    finally:
        executor.release.set()
        await _stop(server, task)


@pytest.mark.asyncio
async def test_submit_on_a_closing_service_reports_shutting_down() -> None:
    """关停期提交 ⇒ ``shutting_down`` 错误帧（不排队、不静默丢弃）。"""
    executor = _Executor()
    server, service, task = await _start(executor)
    await service.close()
    try:
        # 关停标记在 accept 后立刻检查：连接一建立就收到终态帧，不必先发命令。
        async with websockets.connect(await _submit_uri(server)) as submit:
            frame = json.loads(await submit.recv())
        assert frame["type"] == "error"
        assert frame["error"]["error"]["code"] == HttpErrorCode.SHUTTING_DOWN.value
        assert service.active_runs == 0
    finally:
        await _stop(server, task)


@pytest.mark.asyncio
async def test_idle_submit_connection_is_closed_by_server_shutdown_within_budget() -> None:
    """空闲提交连接不能把有界关停拖成无界等待（D1 的有界关停口径对三条端点一致）。"""
    executor = _Executor()
    server, service, task = await _start(executor)
    ws = await websockets.connect(await _submit_uri(server))
    try:
        started = asyncio.get_running_loop().time()
        await service.close()
        await server.close()
        elapsed = asyncio.get_running_loop().time() - started
        with contextlib.suppress(websockets.exceptions.ConnectionClosed):
            await asyncio.wait_for(ws.recv(), timeout=2)
        assert elapsed <= 2 * server.config.shutdown_timeout + 2
        await asyncio.wait_for(task, timeout=5)
    finally:
        await ws.close()
        if not task.done():
            await _stop(server, task)
