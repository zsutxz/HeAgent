"""Story 48-3：``heagent tcp-server`` CLI 接线（组合根 / 参数 / 不隐式监听）。

本文件只测**入口层**：命令注册、参数映射、handler 装配与「普通 CLI 不监听」。
网络生命周期与协议行为在 ``tests/network/``，Agent 适配端到端在
``tests/test_tcp_agent_integration.py``。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner

from heagent.cli.console import main
from heagent.cli.tcp import TcpAgentHandler, build_server_config
from heagent.config import get_settings, reset_settings
from heagent.exceptions import HeAgentError
from heagent.network.protocol import TcpErrorCode, TcpRequest
from heagent.network.tcp_server import TcpServer, TcpServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class _StubProvider:
    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        return ProviderResponse(
            content="stub answer",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> AsyncGenerator[Any, None]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture()
def captured_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> dict[str, TcpServer]:
    """把 ``_serve_tcp`` 换成「记录 server 即返回」：参数断言不需要真的绑定端口。"""
    captured: dict[str, TcpServer] = {}

    async def fake_serve(server: TcpServer) -> None:
        captured["server"] = server

    monkeypatch.setattr("heagent.cli.tcp._serve_tcp", fake_serve)
    monkeypatch.setattr("heagent.cli.tcp._build_provider", lambda settings, model: _StubProvider())
    monkeypatch.chdir(tmp_path)
    return captured


def test_help_lists_connection_options() -> None:
    result = CliRunner().invoke(main, ["tcp-server", "--help"])

    assert result.exit_code == 0
    for option in ("--host", "--port", "--model", "--system", "--max-iterations", "--sandbox"):
        assert option in result.output
    assert "127.0.0.1" in result.output
    assert "JSON Lines" in result.output


def test_registered_as_explicit_subcommand() -> None:
    """显式子命令是唯一启动方式：普通 ``heagent`` 启动不隐式监听端口。"""
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "tcp-server" in result.output


def test_build_server_config_uses_settings_defaults() -> None:
    settings = get_settings()

    config = build_server_config(settings)

    assert config == TcpServerConfig(
        host=settings.tcp_host,
        port=settings.tcp_port,
        max_connections=settings.tcp_max_connections,
        max_inflight_requests=settings.tcp_max_inflight_requests,
        max_request_bytes=settings.tcp_max_request_bytes,
        idle_timeout=settings.tcp_idle_timeout,
        request_timeout=settings.tcp_request_timeout,
        shutdown_timeout=settings.tcp_shutdown_timeout,
    )
    assert (config.host, config.port) == ("127.0.0.1", 8765)


def test_build_server_config_overrides_only_the_given_fields() -> None:
    settings = get_settings()

    config = build_server_config(settings, host="0.0.0.0", max_inflight=1, request_timeout=1.5)

    assert (config.host, config.max_inflight_requests, config.request_timeout) == ("0.0.0.0", 1, 1.5)
    # 未覆盖的字段仍取 Settings（不因某几项覆盖而整体重置）
    assert (config.port, config.max_connections) == (settings.tcp_port, settings.tcp_max_connections)


def test_defaults_reach_the_listening_config(captured_server: dict[str, TcpServer]) -> None:
    result = CliRunner().invoke(main, ["tcp-server"])

    assert result.exit_code == 0, result.output
    server = captured_server["server"]
    assert (server.config.host, server.config.port) == ("127.0.0.1", 8765)
    assert (server.config.max_connections, server.config.max_inflight_requests) == (32, 4)
    assert (server.config.idle_timeout, server.config.request_timeout) == (60.0, 300.0)
    assert isinstance(server.handler, TcpAgentHandler)
    # 网络入口不装交互式审批处理器：无人应答 stdin 会把请求挂死，需要审批的调用按 fail-safe 阻断。
    assert server.handler.engine.approval_handler is None


def test_settings_env_drives_defaults(monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, TcpServer]) -> None:
    """未传 CLI 参数时用 Settings（env）的值——CLI 与 env 走同一套字段。"""
    monkeypatch.setenv("TCP_PORT", "9100")
    monkeypatch.setenv("TCP_MAX_INFLIGHT_REQUESTS", "1")
    monkeypatch.setenv("TCP_REQUEST_TIMEOUT", "42")
    reset_settings()

    result = CliRunner().invoke(main, ["tcp-server"])

    assert result.exit_code == 0, result.output
    config = captured_server["server"].config
    assert (config.port, config.max_inflight_requests, config.request_timeout) == (9100, 1, 42.0)


def test_cli_overrides_reach_the_config_without_mutating_settings(
    captured_server: dict[str, TcpServer],
) -> None:
    result = CliRunner().invoke(
        main,
        [
            "tcp-server",
            "--host",
            "0.0.0.0",
            "--port",
            "9001",
            "--max-connections",
            "5",
            "--max-inflight",
            "2",
            "--max-request-bytes",
            "2048",
            "--idle-timeout",
            "1.5",
            "--request-timeout",
            "2.5",
            "--shutdown-timeout",
            "3.5",
        ],
    )

    assert result.exit_code == 0, result.output
    config = captured_server["server"].config
    assert (config.host, config.port) == ("0.0.0.0", 9001)
    assert (config.max_connections, config.max_inflight_requests) == (5, 2)
    assert (config.max_request_bytes, config.idle_timeout) == (2048, 1.5)
    assert (config.request_timeout, config.shutdown_timeout) == (2.5, 3.5)
    # 覆盖只作用于本次服务：设置单例保持默认值
    settings = get_settings()
    assert (settings.tcp_host, settings.tcp_port) == ("127.0.0.1", 8765)
    assert settings.tcp_max_inflight_requests == 4


@pytest.mark.parametrize(
    "args",
    [
        ["--port", "-1"],
        ["--port", "0"],
        ["--port", "70000"],
        ["--max-connections", "0"],
        ["--max-inflight", "0"],
        ["--max-request-bytes", "0"],
        ["--idle-timeout", "0"],
        ["--idle-timeout", "nan"],
        ["--request-timeout", "-1"],
        ["--request-timeout", "inf"],
        ["--shutdown-timeout", "0"],
        ["--shutdown-timeout", "nan"],
    ],
)
def test_invalid_limits_are_rejected_before_serving(args: list[str], captured_server: dict[str, TcpServer]) -> None:
    """CLI 侧用同一套范围规则拦下非法值（与 Settings 校验同义：端口 1..65535、计数 >=1、超时 >0）。"""
    result = CliRunner().invoke(main, ["tcp-server", *args])

    assert result.exit_code == 2
    assert "server" not in captured_server


def test_startup_failure_is_reported_without_a_listening_banner(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, TcpServer]
) -> None:
    """绑定失败（端口占用 / 地址不可用）必须显性失败，且不谎报「已监听」。"""

    async def failing_serve(server: TcpServer) -> None:
        raise OSError("address already in use")

    monkeypatch.setattr("heagent.cli.tcp._serve_tcp", failing_serve)

    result = CliRunner().invoke(main, ["tcp-server"])

    assert result.exit_code == 1
    assert "TCP server failed to start" in result.output
    assert "listening" not in result.output
    assert "server" not in captured_server


def test_plain_cli_never_creates_a_tcp_listener(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, TcpServer]
) -> None:
    """回归：普通单次 / 交互 CLI 不得构造 ``TcpServer``（不隐式监听端口）。"""
    ran: list[str] = []

    async def fake_run_single(*_args: object, **_kwargs: object) -> None:
        ran.append("run_single")

    class _ExplodingServer:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("普通 CLI 不得构造 TCP listener")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("heagent.cli.console._run_single", fake_run_single)
    monkeypatch.setattr("heagent.cli.tcp.TcpServer", _ExplodingServer)

    result = CliRunner().invoke(main, ["hi"])

    assert result.exit_code == 0, result.output
    assert ran == ["run_single"]
    assert "server" not in captured_server


# --- Story 48-5: 安全边界与可观测性 ---


def test_default_loopback_binding_prints_no_exposure_warning(captured_server: dict[str, TcpServer]) -> None:
    """回环绑定不告警：告警一旦常见就会退化成被忽略的噪音。"""
    result = CliRunner().invoke(main, ["tcp-server"])

    assert result.exit_code == 0, result.output
    assert "WARNING" not in result.output


def test_non_loopback_host_prints_one_exposure_warning(captured_server: dict[str, TcpServer]) -> None:
    """``--host 0.0.0.0`` 启动时 CLI 向 stderr 打**一行**告警（含无认证 / 无 TLS / 非生产安全边界）。

    注意通道分工：CLI 这一行是给操作者的显式提示；``TcpServer.start()`` 另记一条
    ``event=exposed`` 日志（默认 logging 配置把它也写到 stderr，故默认下 stderr 会出现两行——
    这是刻意冗余：``LOG_LEVEL=ERROR`` 时仍保证 stderr 有提示）。日志侧「恰一条」由
    ``tests/network/test_tcp_server.py::test_non_loopback_binding_logs_exactly_one_exposure_warning`` 钉住。
    """
    result = CliRunner().invoke(main, ["tcp-server", "--host", "0.0.0.0"])

    assert result.exit_code == 0, result.output
    warnings = [line for line in result.output.splitlines() if "[tcp] WARNING:" in line]
    assert len(warnings) == 1
    line = warnings[0]
    assert "0.0.0.0" in line
    assert "no authentication" in line
    assert "no TLS" in line
    assert "not a production security boundary" in line


def test_hostname_binding_is_warned_about_conservatively(captured_server: dict[str, TcpServer]) -> None:
    """非字面量主机名不做 DNS 解析：按「可能对外暴露」处理（fail-safe 方向）。"""
    result = CliRunner().invoke(main, ["tcp-server", "--host", "heagent.example.invalid"])

    assert result.exit_code == 0, result.output
    assert "[tcp] WARNING:" in result.output


def test_tcp_entry_never_connects_mcp_servers(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, TcpServer]
) -> None:
    """Story 48-5 的安全决策：网络入口**不**自动连接 ``.mcp.json`` 声明的外部 server。

    入口无认证、客户端不可信——自动拉起第三方 stdio 子进程 / 连远端端点，等于把不可信代码的
    触达面暴露给任何能连上端口的人。这里把 MCP 生命周期打成「一被调用就炸」：命令启动与
    请求级 loop 的装配路径都不得触碰它（需要 MCP 时应在可控的交互式会话里显式启用）。
    """

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("TCP 入口不得构造 MCP 生命周期")

    monkeypatch.setattr("heagent.cli.console._mcp_lifecycle", _explode)

    result = CliRunner().invoke(main, ["tcp-server"])

    assert result.exit_code == 0, result.output
    handler = captured_server["server"].handler
    assert isinstance(handler, TcpAgentHandler)
    assert handler.new_loop() is not None


# --- Story 48-5 评审 C-1：入口层插桩的日志故障不得改写协议结果 ---


class _ExplodingLogger:
    """所有日志调用都抛异常（``emit`` 里抛异常的 handler 会传播，与 raiseExceptions 无关）。"""

    def log(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("logging backend is broken")


class _FailingProvider:
    """``send`` 抛 ``HeAgentError``：走 ``__call__`` 的「已知框架异常 → agent_error」分支。"""

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        raise HeAgentError("provider is not configured")

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        raise HeAgentError("provider is not configured")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="failing", model="failing")


def test_logging_failure_does_not_rewrite_the_agent_error_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """反例（评审实测复现）：``logger.warning`` 抛异常时，兜底 ``except`` 把 agent_error 改写成 server_error。

    入口层插桩全部经 ``_safe_log`` 后，协议码必须保持 ``agent_error``。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("heagent.cli.tcp.logger", _ExplodingLogger())
    handler = TcpAgentHandler(_FailingProvider(), get_settings())

    response = asyncio.run(handler(TcpRequest(id="r1", prompt="hi")))

    assert response.ok is False
    assert response.error is not None
    assert response.error.code is TcpErrorCode.AGENT_ERROR
