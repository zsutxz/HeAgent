"""Story 48-3：``heagent tcp-server`` 的 Agent 适配端到端测试（真实 loopback + StubProvider）。

契约要点（story 48-3 的 AC）：

- 合法 prompt 经**现有** AgentLoop / Engine 治理链执行，最终答案映射为一条 JSONL 响应；
- 工具调用仍走 ``PolicyEngine`` → ``ToolExecutor`` → handler，而不是网络层直调；
- 已知 / 未知 Agent 异常 → 稳定 ``agent_error``，服务继续接受下一连接；
- 服务关闭时在途请求被取消，取消**不**被包装成 ``agent_error``；
- 并发请求各自持有独立的运行态（每请求一个 ``AgentLoop``：``last_usage`` 不被互相覆盖）。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import pytest

from heagent.cli.tcp import TcpAgentHandler, _serve_tcp
from heagent.config import get_settings, reset_settings
from heagent.exceptions import HeAgentError
from heagent.network.protocol import TcpErrorCode, TcpRequest, TcpResponse, TcpUsage
from heagent.network.tcp_server import TcpServer, TcpServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.providers.router import RouteDecision, RoutingProvider
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from heagent.providers.base import BaseProvider


def _usage(prompt: int = 10, completion: int = 5) -> TokenUsage:
    return TokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)


def _final(content: str, usage: TokenUsage | None = None) -> ProviderResponse:
    return ProviderResponse(content=content, usage=usage or _usage(), model="stub", finish_reason="stop")


def _tool_calls(calls: list[ToolCall], *, usage: TokenUsage | None = None) -> ProviderResponse:
    return ProviderResponse(
        content="",
        tool_calls=calls,
        usage=usage or _usage(),
        model="stub",
        finish_reason="tool_calls",
    )


class _ScriptedProvider:
    """按脚本顺序返回响应或抛异常（每个测试文件独立一份，与仓库既有 StubProvider 同构）。"""

    def __init__(self, script: list[ProviderResponse | Exception]) -> None:
        self._script = list(script)
        self._idx = 0
        self.calls: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls.append([message.model_copy(deep=True) for message in messages])
        item = self._script[min(self._idx, len(self._script) - 1)]
        self._idx += 1
        if isinstance(item, BaseException):  # 含 asyncio.CancelledError（BaseException 而非 Exception）
            raise item
        return item

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> AsyncGenerator[Any, None]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


class _BlockingProvider:
    """首次调用即挂起，直到被取消（用于验证服务关闭时的取消语义）。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return _final("too late")

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> AsyncGenerator[Any, None]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


class _PerPromptProvider:
    """按 prompt 返回不同答案与用量，且「slow」故意慢于「fast」（制造并发交错）。"""

    def __init__(self) -> None:
        self._delays = {"slow": 0.05, "fast": 0.0}
        self._usages = {"slow": _usage(1, 1), "fast": _usage(3, 3)}

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        prompt = messages[-1].content or ""
        await asyncio.sleep(self._delays.get(prompt, 0.0))
        return _final(f"answer for {prompt}", self._usages.get(prompt))

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> AsyncGenerator[Any, None]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


class _TierRouter:
    """按 prompt 选档的极简 Router：含 ``slow`` 走 pro 档，否则 fast 档。"""

    def __init__(self, fast: str, pro: str) -> None:
        self._fast = fast
        self._pro = pro

    def route(self, messages: list[Message], tools: object = None) -> RouteDecision:
        text = messages[-1].content or ""
        return RouteDecision(provider=self._pro if "slow" in text else self._fast, reason="test_router")


class _TierProvider:
    """固定模型名 + 可选延迟的 provider（延迟用于制造请求交错）。"""

    def __init__(self, model: str, *, delay: float = 0.0) -> None:
        self._model = model
        self._delay = delay

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        await asyncio.sleep(self._delay)
        return ProviderResponse(
            content=f"answer from {self._model}",
            usage=_usage(),
            model=self._model,
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> AsyncGenerator[Any, None]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name=self._model, model=self._model)


def _build_handler(provider: BaseProvider) -> TcpAgentHandler:
    """入口层组合根的最小用法：服务端 provider + 当前 Settings（engine / 记忆存储由 handler 装配）。"""
    return TcpAgentHandler(provider, get_settings())


async def _start(handler: TcpAgentHandler) -> tuple[TcpServer, int]:
    server = TcpServer(TcpServerConfig(port=0), handler)
    await server.start()
    return server, server.sockets[0].getsockname()[1]


async def _roundtrip(port: int, payload: str) -> TcpResponse:
    """发一条 JSON Lines 请求并读回一条响应（``payload`` 为不含 LF 的 JSON 文本，此处补 framing）。"""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(payload.encode("utf-8") + b"\n")
        await writer.drain()
        return TcpResponse.model_validate_json(await reader.readline())
    finally:
        writer.close()
        await writer.wait_closed()


async def _wait_for_port(server: TcpServer) -> int:
    async with asyncio.timeout(5):
        while not server.sockets:
            await asyncio.sleep(0)
    return server.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_tcp_request_runs_agent_and_returns_result_with_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    provider = _ScriptedProvider([_final("hello from agent")])
    server, port = await _start(_build_handler(provider))
    try:
        response = await _roundtrip(port, '{"id":"r1","prompt":"hi"}')
    finally:
        await server.close()

    assert response.id == "r1"
    assert response.ok is True
    assert response.result == "hello from agent"
    assert response.model == "stub"
    assert response.usage == TcpUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    # prompt 原样进入 AgentLoop（唯一从请求读取的字段之一）
    assert provider.calls[0][-1].content == "hi"


@pytest.mark.asyncio
async def test_tool_calls_run_through_the_engine_execution_chain(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.txt").write_text("engine-governed content", encoding="utf-8")
    provider = _ScriptedProvider(
        [
            _tool_calls([ToolCall(id="c1", name="file_read", arguments={"path": "note.txt"})]),
            _final("done"),
        ]
    )
    handler = _build_handler(provider)
    server, port = await _start(handler)
    try:
        response = await _roundtrip(port, '{"id":"r1","prompt":"read the note"}')
    finally:
        await server.close()

    assert response.result == "done"
    # 工具结果回灌给模型（证明 handler 真的执行了，而非网络层伪造答案）
    tool_messages = [message for message in provider.calls[1] if message.role == Role.TOOL]
    assert any("engine-governed content" in (message.content or "") for message in tool_messages)
    # 执行经过引擎执行链：事件由 ToolExecutor 发布（PolicyEngine → ToolExecutor → handler）
    completed = [
        event
        for event in handler.engine.events.recent_events
        if event.event_type == "tool_call_completed" and event.tool_name == "file_read"
    ]
    assert completed, "tool_call_completed 事件缺失：工具未走引擎执行链"


@pytest.mark.asyncio
async def test_known_agent_error_is_reported_and_service_survives(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    provider = _ScriptedProvider([HeAgentError("provider is not configured"), _final("second ok")])
    server, port = await _start(_build_handler(provider))
    try:
        failed = await _roundtrip(port, '{"id":"e1","prompt":"boom"}')
        succeeded = await _roundtrip(port, '{"id":"e2","prompt":"fine"}')
    finally:
        await server.close()

    assert failed.ok is False
    assert failed.result is None
    assert failed.error is not None
    assert failed.error.code == TcpErrorCode.AGENT_ERROR
    assert failed.error.message == "provider is not configured"
    assert succeeded.ok is True
    assert succeeded.result == "second ok"
    assert succeeded.id == "e2"


@pytest.mark.asyncio
async def test_unknown_agent_failure_is_sanitized(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    provider = _ScriptedProvider([RuntimeError("secret detail in C:/private/path")])
    server, port = await _start(_build_handler(provider))
    try:
        response = await _roundtrip(port, '{"id":"r1","prompt":"boom"}')
    finally:
        await server.close()

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == TcpErrorCode.AGENT_ERROR
    assert response.error.message == "agent request failed"
    assert "secret detail" not in response.error.message


@pytest.mark.asyncio
async def test_handler_cancellation_is_not_converted_to_agent_error(monkeypatch, tmp_path) -> None:
    """取消是**服务级**信号：handler 必须原样传播，不能伪装成业务失败。"""
    monkeypatch.chdir(tmp_path)
    handler = _build_handler(_ScriptedProvider([asyncio.CancelledError()]))
    request = TcpRequest(id="r1", prompt="cancel me")

    with pytest.raises(asyncio.CancelledError):
        await handler(request)


@pytest.mark.asyncio
async def test_server_shutdown_cancels_in_flight_request_without_agent_error(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    provider = _BlockingProvider()
    server, port = await _start(_build_handler(provider))
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b'{"id":"r1","prompt":"slow"}\n')
        await writer.drain()
        await provider.started.wait()

        await server.close()

        assert provider.cancelled.is_set()
        assert await reader.readline() == b""  # EOF：取消没有被写成 agent_error 响应
    finally:
        writer.close()
        await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_concurrent_requests_keep_their_own_result_and_usage(monkeypatch, tmp_path) -> None:
    """每请求一个 AgentLoop：并发时 answer / usage / id 不互相污染。"""
    monkeypatch.chdir(tmp_path)
    handler = _build_handler(_PerPromptProvider())
    loops: list[object] = []
    original_new_loop = handler.new_loop

    def spy_new_loop() -> object:
        loop = original_new_loop()
        loops.append(loop)
        return loop

    monkeypatch.setattr(handler, "new_loop", spy_new_loop)
    server, port = await _start(handler)
    try:
        slow, fast = await asyncio.gather(
            _roundtrip(port, '{"id":"s","prompt":"slow"}'),
            _roundtrip(port, '{"id":"f","prompt":"fast"}'),
        )
    finally:
        await server.close()

    # 决策证据：并发请求各持一个 loop 实例（共享单实例会让 last_usage/model 互相覆盖）
    assert len(loops) == 2
    assert loops[0] is not loops[1]
    assert (slow.id, slow.result) == ("s", "answer for slow")
    assert slow.usage == TcpUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    assert (fast.id, fast.result) == ("f", "answer for fast")
    assert fast.usage == TcpUsage(prompt_tokens=3, completion_tokens=3, total_tokens=6)


@pytest.mark.asyncio
async def test_concurrent_routed_requests_report_their_own_model(monkeypatch, tmp_path) -> None:
    """回归：响应里的 ``model`` 必须来自**本请求**的运行记录。

    反例（评审实测复现）：``_resolve_model`` 读共享 ``RoutingProvider.last_decision``——那是
    **实例级最近一次决策**，慢请求结束时会读到快请求的档位，于是把别人的模型名写进自己的响应。
    ``slow`` 档故意慢于 ``fast`` 档，保证 fast 请求先写入共享路由状态。
    """
    monkeypatch.chdir(tmp_path)
    provider = RoutingProvider(
        {"fast": _TierProvider("fast-model"), "pro": _TierProvider("pro-model", delay=0.05)},
        _TierRouter(fast="fast", pro="pro"),
        default="fast",
    )
    server, port = await _start(_build_handler(provider))
    try:
        slow, fast = await asyncio.gather(
            _roundtrip(port, '{"id":"s","prompt":"slow work"}'),
            _roundtrip(port, '{"id":"f","prompt":"quick work"}'),
        )
    finally:
        await server.close()

    assert (slow.id, slow.model) == ("s", "pro-model")
    assert (fast.id, fast.model) == ("f", "fast-model")


@pytest.mark.asyncio
async def test_serve_tcp_listens_serves_and_closes(monkeypatch, tmp_path, capsys) -> None:
    """``_serve_tcp`` 是被 CLI 调用的真实生命周期包装：启动 → 服务 → 关闭（无残留监听）。"""
    monkeypatch.chdir(tmp_path)
    server = TcpServer(TcpServerConfig(port=0), _build_handler(_ScriptedProvider([_final("served")])))
    task = asyncio.create_task(_serve_tcp(server))
    try:
        port = await _wait_for_port(server)
        response = await _roundtrip(port, '{"id":"r1","prompt":"hi"}')
        assert response.result == "served"
        assert "listening on 127.0.0.1:" in capsys.readouterr().err
    finally:
        await server.close()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert task.done()
    assert server.sockets == ()
    assert server.active_connections == 0


# --- Story 48-5: 通道隔离（rollout 事件流不混进 TCP 响应） ---


@pytest.mark.asyncio
@pytest.mark.parametrize("rollout_enabled", [False, True])
async def test_tcp_response_is_one_line_regardless_of_rollout_setting(
    monkeypatch, tmp_path, capsys, rollout_enabled: bool
) -> None:
    """``EVENTS_ROLLOUT_ENABLED`` 任一状态：socket 上只有一条 JSON 响应行，且 stdout 零写入。

    同时钉住**当前边界**（48-5 评审 W-2）：TCP 入口**不构造** ``JsonlSink``，故该开关在本入口
    不产生 rollout 文件——第三条通道目前只属于 CLI 单次模式。这里断言「开关打开也不会凭空多出
    rollout 产物」，避免文档与事实漂移（要接入是后续工作，见 story 的 Deviation）。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EVENTS_ROLLOUT_ENABLED", "true" if rollout_enabled else "false")
    reset_settings()
    try:
        server, port = await _start(_build_handler(_ScriptedProvider([_final("served")])))
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b'{"id":"r1","prompt":"hi"}\n')
            await writer.drain()
            payload = await reader.read()  # 读到 EOF：响应之后不得再有字节
        finally:
            writer.close()
            await writer.wait_closed()
            await server.close()
    finally:
        reset_settings()

    assert payload.endswith(b"\n")
    assert payload.count(b"\n") == 1
    assert TcpResponse.model_validate_json(payload).result == "served"
    assert capsys.readouterr().out == ""
    assert list((tmp_path / ".heagent" / "runs").rglob("rollout.jsonl")) == []
