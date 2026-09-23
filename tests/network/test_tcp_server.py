import asyncio
import logging

import pytest

from heagent.network import tcp_server
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


# --- Story 48-5: 安全边界与可观测性 ---


async def _ok_handler(request: TcpRequest) -> TcpResponse:
    return success_response(request.id, "ok")


class _ExplodingLogger:
    """所有日志调用都抛异常：验证「观测故障不得改写业务响应」。"""

    def log(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("logging backend is broken")


@pytest.mark.asyncio
async def test_loopback_binding_logs_no_exposure_warning(caplog: pytest.LogCaptureFixture) -> None:
    """默认回环绑定不告警——否则告警会退化成噪音被忽略。"""
    caplog.set_level(logging.INFO)

    server, port = await _start(_ok_handler)
    try:
        await _request(port, b'{"id":"r1","prompt":"hello"}\n')
    finally:
        await server.close()

    assert "tcp event=started host=127.0.0.1" in caplog.text
    assert "event=exposed" not in caplog.text


@pytest.mark.asyncio
async def test_non_loopback_binding_logs_exactly_one_exposure_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """非回环绑定：日志恰一条 ``event=exposed``，含宿主与三个风险事实。

    这里替换 ``asyncio.start_server``：测试不该真的在开发机 / CI 上打开一个对外可达的监听口。
    """
    caplog.set_level(logging.INFO)

    class _FakeListener:
        sockets: tuple[object, ...] = ()

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def _fake_start_server(*_args: object, **_kwargs: object) -> _FakeListener:
        return _FakeListener()

    monkeypatch.setattr(asyncio, "start_server", _fake_start_server)

    server = TcpServer(TcpServerConfig(host="0.0.0.0", port=0), _ok_handler)
    await server.start()
    await server.close()

    exposed = [record for record in caplog.records if "event=exposed" in record.getMessage()]
    assert len(exposed) == 1
    message = exposed[0].getMessage()
    assert "host=0.0.0.0" in message
    assert "no authentication" in message
    assert "no TLS" in message
    assert "not a production security boundary" in message
    assert exposed[0].levelno == logging.WARNING


@pytest.mark.asyncio
async def test_request_stages_are_correlatable_by_request_id(caplog: pytest.LogCaptureFixture) -> None:
    """accepted → processing → completed 可由 request id 串起来，且完成日志带耗时。"""
    caplog.set_level(logging.INFO)

    server, port = await _start(_ok_handler)
    try:
        assert b'"ok":true' in await _request(port, b'{"id":"corr-1","prompt":"hello"}\n')
    finally:
        await server.close()

    lines = [record.getMessage() for record in caplog.records]
    accepted = [line for line in lines if "event=accepted" in line]
    processing = [line for line in lines if "event=processing" in line]
    completed = [line for line in lines if "event=completed" in line]
    assert len(accepted) == len(processing) == len(completed) == 1
    for line in (accepted[0], processing[0], completed[0]):
        assert "request_id=corr-1" in line
    assert "status=ok" in completed[0]
    assert "elapsed_ms=" in completed[0]
    assert "peer=127.0.0.1:" in accepted[0]


@pytest.mark.asyncio
async def test_prompt_body_never_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Never 列表：不记录完整 prompt 正文——只记 request id / 对端 / 字节数这类有界元数据。"""
    caplog.set_level(logging.DEBUG)

    server, port = await _start(_ok_handler)
    try:
        await _request(port, b'{"id":"p1","prompt":"PROMPT-SENTINEL-9d3f"}\n')
    finally:
        await server.close()

    assert "PROMPT-SENTINEL-9d3f" not in caplog.text
    assert "bytes=" in caplog.text


@pytest.mark.asyncio
async def test_decode_rejection_logs_reason_and_stable_code(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    server, port = await _start(_ok_handler)
    try:
        assert b'"code":"invalid_json"' in await _request(port, b"not-json\n")
    finally:
        await server.close()

    assert "event=rejected" in caplog.text
    assert "reason=decode_failed" in caplog.text
    assert "code=invalid_json" in caplog.text


@pytest.mark.asyncio
async def test_inflight_rejection_logs_reason_and_stable_code(caplog: pytest.LogCaptureFixture) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: TcpRequest) -> TcpResponse:
        started.set()
        await release.wait()
        return success_response(request.id, "ok")

    caplog.set_level(logging.INFO)
    server, port = await _start(handler, max_inflight_requests=1)
    _first_reader, first = await asyncio.open_connection("127.0.0.1", port)
    second_reader, second = await asyncio.open_connection("127.0.0.1", port)
    try:
        first.write(b'{"id":"r1","prompt":"one"}\n')
        await first.drain()
        await started.wait()
        second.write(b'{"id":"r2","prompt":"two"}\n')
        await second.drain()
        assert b'"code":"rate_limited"' in await second_reader.readline()
    finally:
        release.set()
        first.close()
        second.close()
        await first.wait_closed()
        await second.wait_closed()
        await server.close()

    assert "reason=inflight_limit" in caplog.text
    assert "code=rate_limited" in caplog.text
    assert "request_id=r2" in caplog.text
    assert "event=accepted request_id=r2" not in caplog.text  # 未被接纳的请求不记 accepted


@pytest.mark.asyncio
async def test_idle_timeout_rejection_logs_reason(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    server, port = await _start(_ok_handler, idle_timeout=0.01)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        assert b'"code":"timeout"' in await reader.readline()
    finally:
        writer.close()
        await writer.wait_closed()
        await server.close()

    assert "reason=idle_timeout" in caplog.text
    assert "code=timeout" in caplog.text


@pytest.mark.asyncio
async def test_broken_logging_cannot_change_a_successful_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """日志设施抛异常时，成功请求仍必须回正常响应（观测故障 ≠ 业务失败）。"""
    monkeypatch.setattr(tcp_server, "logger", _ExplodingLogger())

    server, port = await _start(_ok_handler)
    try:
        response = await _request(port, b'{"id":"r1","prompt":"hello"}\n')
    finally:
        await server.close()

    assert b'"ok":true' in response


@pytest.mark.asyncio
async def test_broken_logging_keeps_the_failure_mapping_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    """handler 抛异常 + 日志损坏：仍回稳定 server_error，且不泄漏内部细节。"""
    monkeypatch.setattr(tcp_server, "logger", _ExplodingLogger())

    async def handler(request: TcpRequest) -> TcpResponse:
        raise RuntimeError("secret internal detail")

    server, port = await _start(handler)
    try:
        response = await _request(port, b'{"id":"r1","prompt":"x"}\n')
    finally:
        await server.close()

    assert b'"code":"server_error"' in response
    assert b"secret internal detail" not in response


@pytest.mark.asyncio
async def test_socket_channel_carries_exactly_one_response_line(capsys: pytest.CaptureFixture[str]) -> None:
    """通道隔离：socket 上只有一条 JSON Lines 响应（读到 EOF 无剩余字节），stdout 零写入。"""
    server, port = await _start(_ok_handler)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b'{"id":"r1","prompt":"hello"}\n')
        await writer.drain()
        payload = await reader.read()  # 读到 EOF：响应之后不得再有字节
    finally:
        writer.close()
        await writer.wait_closed()
        await server.close()

    assert payload.endswith(b"\n")
    assert payload.count(b"\n") == 1
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_cancelled_request_gets_a_terminal_log(caplog: pytest.LogCaptureFixture) -> None:
    """取消同样要留终态日志：否则 request id 只到 processing 就断线（48-5 评审 W-3）。"""
    caplog.set_level(logging.INFO)
    started = asyncio.Event()
    wait_forever = asyncio.get_running_loop().create_future()

    async def handler(request: TcpRequest) -> TcpResponse:
        started.set()
        await wait_forever
        return success_response(request.id, "never")

    server, port = await _start(handler, shutdown_timeout=0.05)
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b'{"id":"cancel-1","prompt":"slow"}\n')
        await writer.drain()
        await started.wait()
        await server.close()
    finally:
        writer.close()
        await writer.wait_closed()

    assert "event=cancelled request_id=cancel-1" in caplog.text
    assert "elapsed_ms=" in caplog.text
    assert "event=completed" not in caplog.text


@pytest.mark.asyncio
async def test_oversized_requests_share_one_reason(caplog: pytest.LogCaptureFixture) -> None:
    """同一违规（请求过大）只用一个 reason：行超 StreamReader limit 与超 max_request_bytes 归一。

    否则按 reason 做指标会把一半的 oversized 记成 decode 失败（48-5 评审 W-5）。
    """
    caplog.set_level(logging.INFO)
    server, port = await _start(_ok_handler, max_request_bytes=64)
    try:
        # (a) 整行越过 StreamReader limit（max+2 = 66）
        assert b'"code":"request_too_large"' in await _request(port, b"{" + b'"x"' * 80 + b"}\n")
        # (b) 行落在 limit 内（65 字节 ≤ max+2）但超过 max_request_bytes，由协议层拦下
        oversized = b'{"id":"r1","prompt":"' + b"x" * 41 + b'"}\n'
        assert len(oversized) == 65
        assert b'"code":"request_too_large"' in await _request(port, oversized)
    finally:
        await server.close()

    rejected = [line for line in caplog.text.splitlines() if "event=rejected" in line]
    assert len(rejected) == 2
    assert all("reason=oversized_line" in line for line in rejected)
    assert "reason=decode_failed" not in caplog.text


@pytest.mark.asyncio
async def test_start_propagates_the_original_bind_error() -> None:
    """48-2 AC6：绑定失败时调用方拿到**原始可诊断**异常（不是被包装过的文案）。

    用确定性不可绑定的地址（无效 IP 字面量）而不是「端口被占」——后者在开启 ``SO_REUSEADDR``
    的平台上可能反而绑定成功，会让这条测试变成平台相关的假绿。
    """
    server = TcpServer(TcpServerConfig(host="256.256.256.256", port=0), _ok_handler)

    with pytest.raises(OSError) as excinfo:
        await server.start()

    assert str(excinfo.value).strip()  # 原始异常带可诊断信息
    assert server.sockets == ()  # 失败不留半成品监听


@pytest.mark.asyncio
async def test_client_disconnect_before_response_reclaims_resources() -> None:
    """48-2 AC4 / 48-6 任务 4：客户端在响应写回前断开 → 服务不崩溃、连接与在途名额都回收。

    断开发生在 handler **在途** 时（不是写完响应后），所以覆盖的是「写回失败 + finally 归还」这条路。
    """
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: TcpRequest) -> TcpResponse:
        started.set()
        await release.wait()
        return success_response(request.id, "late")

    server, port = await _start(handler, max_inflight_requests=1)
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b'{"id":"gone","prompt":"x"}\n')
        await writer.drain()
        await started.wait()
        assert server.active_connections == 1
        assert server.active_inflight == 1

        writer.close()
        await writer.wait_closed()
        release.set()

        async with asyncio.timeout(5):
            while server.active_connections or server.active_inflight:
                await asyncio.sleep(0)

        assert server.active_connections == 0
        assert server.active_inflight == 0
        assert server._request_tasks == set()
        # 服务未受影响：下一连接照常服务
        assert b'"ok":true' in await _request(port, b'{"id":"after","prompt":"y"}\n')
    finally:
        release.set()
        writer.close()
        await server.close()
