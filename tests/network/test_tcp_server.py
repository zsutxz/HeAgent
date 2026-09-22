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
        assert server.active_connections == 1
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
        TcpServerConfig(request_timeout=0)


def test_timeout_error_code_is_stable() -> None:
    assert TcpErrorCode.TIMEOUT.value == "timeout"
