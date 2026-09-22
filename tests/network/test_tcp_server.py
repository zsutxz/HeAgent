import asyncio

import pytest

from heagent.network.protocol import TcpRequest, TcpResponse, TcpErrorCode, success_response
from heagent.network.tcp_server import TcpServer, TcpServerConfig


async def _request(port: int, payload: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(payload)
    await writer.drain()
    response = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return response


async def _start(handler, **overrides):
    config = TcpServerConfig(port=0, **overrides)
    server = TcpServer(config, handler)
    await server.start()
    port = server.sockets[0].getsockname()[1]
    return server, port


@pytest.mark.asyncio
async def test_server_handles_one_request_and_closes_connection() -> None:
    calls: list[str] = []

    async def handler(request: TcpRequest) -> TcpResponse:
        calls.append(request.prompt)
        return success_response(request.id, request.prompt.upper())

    server, port = await _start(handler)
    try:
        response = await _request(port, b'{"id":"r1","prompt":"hello"}\n')
        assert response.endswith(b"\n")
        assert b'"result":"HELLO"' in response
        assert calls == ["hello"]
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_server_handles_split_request() -> None:
    async def handler(request: TcpRequest) -> TcpResponse:
        return success_response(request.id, request.prompt)

    server, port = await _start(handler)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b'{"id":"r1",')
        await writer.drain()
        await asyncio.sleep(0)
        writer.write(b'"prompt":"hello"}\n')
        await writer.drain()
        assert b'"result":"hello"' in await reader.readline()
    finally:
        writer.close()
        await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_invalid_request_does_not_stop_server() -> None:
    async def handler(request: TcpRequest) -> TcpResponse:
        return success_response(request.id, "ok")

    server, port = await _start(handler)
    try:
        invalid = await _request(port, b"not-json\n")
        valid = await _request(port, b'{"id":"r2","prompt":"hello"}\n')
        assert b'"code":"invalid_json"' in invalid
        assert b'"result":"ok"' in valid
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_handler_error_isolated_to_request() -> None:
    calls = 0

    async def handler(request: TcpRequest) -> TcpResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("secret internal detail")
        return success_response(request.id, "ok")

    server, port = await _start(handler)
    try:
        failed = await _request(port, b'{"id":"r1","prompt":"fail"}\n')
        succeeded = await _request(port, b'{"id":"r2","prompt":"ok"}\n')
        assert b'"code":"server_error"' in failed
        assert b"secret internal detail" not in failed
        assert b'"result":"ok"' in succeeded
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_idle_timeout_returns_timeout() -> None:
    async def handler(request: TcpRequest) -> TcpResponse:
        return success_response(request.id, "unreachable")

    server, port = await _start(handler, idle_timeout=0.01)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        response = await reader.readline()
        assert b'"code":"timeout"' in response
    finally:
        writer.close()
        await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_request_timeout_returns_timeout() -> None:
    async def handler(request: TcpRequest) -> TcpResponse:
        await asyncio.sleep(0.1)
        return success_response(request.id, "too late")

    server, port = await _start(handler, request_timeout=0.01)
    try:
        response = await _request(port, b'{"id":"r1","prompt":"slow"}\n')
        assert b'"code":"timeout"' in response
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_connection_limit_rejects_new_connection() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: TcpRequest) -> TcpResponse:
        started.set()
        await release.wait()
        return success_response(request.id, "ok")

    server, port = await _start(handler, max_connections=1)
    _first_reader, first_writer = await asyncio.open_connection("127.0.0.1", port)
    second_reader, second_writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        first_writer.write(b'{"id":"r1","prompt":"one"}\n')
        await first_writer.drain()
        await started.wait()
        second_writer.write(b'{"id":"r2","prompt":"two"}\n')
        await second_writer.drain()
        rejected = await second_reader.readline()
        assert b'"code":"rate_limited"' in rejected
    finally:
        release.set()
        first_writer.close()
        second_writer.close()
        await first_writer.wait_closed()
        await second_writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_oversized_line_returns_request_too_large() -> None:
    async def handler(request: TcpRequest) -> TcpResponse:
        return success_response(request.id, "unreachable")

    server, port = await _start(handler, max_request_bytes=16)
    try:
        response = await _request(port, b"{" + b'"x"' * 8 + b"}\n")
        assert b'"code":"request_too_large"' in response
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_close_returns_after_timeout_when_handler_suppresses_cancellation() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: TcpRequest) -> TcpResponse:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            await release.wait()
        return success_response(request.id, "late")

    server, port = await _start(handler, shutdown_timeout=0.01)
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b'{"id":"r1","prompt":"slow"}\n')
        await writer.drain()
        await started.wait()
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        await server.close()
        assert loop.time() - started_at < 0.2
        # 48-4 起：关闭超时后 close() 会**结算**登记与在途名额（asyncio 无法强杀忽略取消的任务）。
        # 此前这里断言 == 1（把「残留仍在登记」当契约），那会让同一实例重启后永久少一份容量。
        assert server.active_connections == 0
        assert server.active_inflight == 0
    finally:
        release.set()
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0)
        await server.close()


@pytest.mark.asyncio
async def test_close_cancels_long_running_handler() -> None:
    cancelled = asyncio.Event()
    started = asyncio.Event()
    wait_forever = asyncio.get_running_loop().create_future()

    async def handler(request: TcpRequest) -> TcpResponse:
        started.set()
        try:
            await wait_forever
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return success_response(request.id, "never")

    server, port = await _start(handler, shutdown_timeout=0.01)
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b'{"id":"r1","prompt":"slow"}\n')
    await writer.drain()
    await started.wait()
    assert server.active_connections == 1
    assert len(server._request_tasks) == 1
    await server.close()
    writer.close()
    await writer.wait_closed()
    assert cancelled.is_set()
    assert server.active_connections == 0


def test_server_config_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError):
        TcpServerConfig(port=-1)
    with pytest.raises(ValueError):
        TcpServerConfig(max_connections=0)
    with pytest.raises(ValueError):
        TcpServerConfig(max_inflight_requests=0)
    with pytest.raises(ValueError):
        TcpServerConfig(request_timeout=0)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_server_config_rejects_non_finite_timeouts(value: float) -> None:
    """``Inf`` 会把超时变成无限制（关闭等待无界），``NaN`` 会绕过比较——两者都必须显式失败。"""
    with pytest.raises(ValueError):
        TcpServerConfig(idle_timeout=value)
    with pytest.raises(ValueError):
        TcpServerConfig(request_timeout=value)
    with pytest.raises(ValueError):
        TcpServerConfig(shutdown_timeout=value)


def test_timeout_error_code_is_stable() -> None:
    assert TcpErrorCode.TIMEOUT.value == "timeout"


# --- Story 48-4: 两级限制与超时下的名额回收 ---


@pytest.mark.asyncio
async def test_inflight_limit_rejects_immediately_without_queueing() -> None:
    """在途 Agent 名额满 → 立即 rate_limited，绝不排队等待（排队会把洪峰变成无界等待）。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: TcpRequest) -> TcpResponse:
        started.set()
        await release.wait()
        return success_response(request.id, "ok")

    server, port = await _start(handler, max_inflight_requests=1)
    _first_reader, first = await asyncio.open_connection("127.0.0.1", port)
    second_reader, second = await asyncio.open_connection("127.0.0.1", port)
    try:
        first.write(b'{"id":"r1","prompt":"one"}\n')
        await first.drain()
        await started.wait()

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        second.write(b'{"id":"r2","prompt":"two"}\n')
        await second.drain()
        rejected = await second_reader.readline()
        elapsed = loop.time() - started_at

        assert b'"code":"rate_limited"' in rejected
        assert b'"id":"r2"' in rejected  # request id 保真（客户端可归因）
        assert elapsed < 1.0  # 第一个请求仍在途，第二个没有被排队等待
        assert server.active_inflight == 1
    finally:
        release.set()
        first.close()
        second.close()
        await first.wait_closed()
        await second.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_inflight_slot_is_released_after_each_request() -> None:
    async def handler(request: TcpRequest) -> TcpResponse:
        return success_response(request.id, request.prompt)

    server, port = await _start(handler, max_inflight_requests=1)
    try:
        for index in range(3):
            payload = f'{{"id":"r{index}","prompt":"p{index}"}}\n'.encode()
            assert b'"ok":true' in await _request(port, payload)
            assert server.active_inflight == 0  # 正常路径归还名额
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_request_timeout_releases_the_inflight_slot() -> None:
    async def handler(request: TcpRequest) -> TcpResponse:
        await asyncio.sleep(30)
        return success_response(request.id, "late")

    server, port = await _start(handler, max_inflight_requests=1, request_timeout=0.05)
    try:
        response = await _request(port, b'{"id":"slow","prompt":"slow"}\n')

        assert b'"code":"timeout"' in response
        assert server.active_inflight == 0
        assert server._request_tasks == set()  # 超时任务已回收，无 pending task
        # 名额确实归还：下一个请求被**接纳**（继续超时，但不再是 rate_limited）
        assert b'"code":"timeout"' in await _request(port, b'{"id":"next","prompt":"next"}\n')
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_handler_error_releases_the_inflight_slot() -> None:
    async def handler(request: TcpRequest) -> TcpResponse:
        raise RuntimeError("boom")

    server, port = await _start(handler, max_inflight_requests=1)
    try:
        failed = await _request(port, b'{"id":"r1","prompt":"x"}\n')

        assert b'"code":"server_error"' in failed
        assert server.active_inflight == 0
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_close_cancels_inflight_request_and_releases_the_slot() -> None:
    started = asyncio.Event()
    wait_forever = asyncio.get_running_loop().create_future()

    async def handler(request: TcpRequest) -> TcpResponse:
        started.set()
        await wait_forever
        return success_response(request.id, "never")

    server, port = await _start(handler, max_inflight_requests=1, shutdown_timeout=0.05)
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b'{"id":"r1","prompt":"slow"}\n')
        await writer.drain()
        await started.wait()
        assert server.active_inflight == 1

        await server.close()

        assert server.active_inflight == 0
        assert server.active_connections == 0
        assert server._request_tasks == set()
        assert server.sockets == ()
    finally:
        writer.close()
        await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_close_timeout_settles_accounting_and_the_instance_can_restart() -> None:
    """关闭超时（handler 吞掉取消）后不得留下永久容量损失。

    ``asyncio`` 无法强杀忽略取消的任务，故 ``close()`` 超时返回时必须结算登记与在途名额；
    残留任务随后自行结束时它们的归还是幂等 no-op（不能把集合/计数改坏），实例可再次 ``start()``
    并恢复正常容量。
    """
    release = asyncio.Event()
    first_started = asyncio.Event()
    calls = 0

    async def handler(request: TcpRequest) -> TcpResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                await release.wait()  # 病态：吞掉取消，直到测试放行
        return success_response(request.id, f"answer {calls}")

    server = TcpServer(
        TcpServerConfig(port=0, max_inflight_requests=1, shutdown_timeout=0.01),
        handler,
    )
    await server.start()
    port = server.sockets[0].getsockname()[1]
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b'{"id":"zombie","prompt":"slow"}\n')
    await writer.drain()
    await first_started.wait()
    assert server.active_inflight == 1

    await server.close()

    assert server.active_inflight == 0
    assert server.active_connections == 0
    assert server.sockets == ()

    # 放行残留任务后，它的收尾不得把结算过的登记/名额改坏（幂等归还）。
    release.set()
    writer.close()
    await writer.wait_closed()
    for _ in range(3):
        await asyncio.sleep(0)
    assert server.active_inflight == 0
    assert server.active_connections == 0

    # 同一实例可重启，且容量完好：新的合法请求被接纳（不是 rate_limited）。
    await server.start()
    try:
        restarted_port = server.sockets[0].getsockname()[1]
        assert b'"code":"rate_limited"' not in await _request(restarted_port, b'{"id":"after","prompt":"go"}\n')
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_idle_timeout_releases_the_connection() -> None:
    """空闲超时只覆盖读取阶段：连接被释放（EOF），且不占用任何名额。"""

    async def handler(request: TcpRequest) -> TcpResponse:
        return success_response(request.id, "unreachable")

    server, port = await _start(handler, idle_timeout=0.01)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        assert b'"code":"timeout"' in await reader.readline()
        assert await reader.readline() == b""  # 服务端关闭了连接

        assert server.active_connections == 0
        assert server.active_inflight == 0
    finally:
        writer.close()
        await writer.wait_closed()
        await server.close()
