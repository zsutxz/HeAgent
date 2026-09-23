"""Story 49-1：``heagent http-server`` CLI 接线（命令注册 / 参数映射 / 不隐式监听）。

本文件只测**入口层**：命令注册、参数映射、绑定失败的可读错误，以及「导入 CLI 不会拉起可选
HTTP 栈」。HTTP 传输层与生命周期行为在 ``tests/network/test_http_server.py``。
"""

from __future__ import annotations

import socket
from typing import Any

import pytest
from click.testing import CliRunner

from heagent import __version__
from heagent.cli import main
from heagent.cli_http import build_server_config
from heagent.config import get_settings, reset_settings
from heagent.network.http_server import HttpServer, HttpServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage


class _StubProvider:
    """最小 provider：``http-server`` 命令会装配 Agent handler，测试里不需要真的建连接。"""

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        return ProviderResponse(
            content="stub",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture()
def captured_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> dict[str, HttpServer]:
    """把 ``_serve_http`` 换成「记录 server 即返回」：参数断言不需要真的绑定端口。"""
    captured: dict[str, HttpServer] = {}

    async def fake_serve(server: HttpServer) -> None:
        captured["server"] = server

    monkeypatch.setattr("heagent.cli_http._serve_http", fake_serve)
    monkeypatch.setattr("heagent.cli_http._build_provider", lambda settings, model: _StubProvider())
    monkeypatch.chdir(tmp_path)
    return captured


def test_help_lists_http_options() -> None:
    result = CliRunner().invoke(main, ["http-server", "--help"])

    assert result.exit_code == 0
    for option in (
        "--host",
        "--port",
        "--max-connections",
        "--max-inflight-runs",
        "--max-request-bytes",
        "--event-buffer-size",
        "--run-history-size",
        "--request-timeout",
        "--shutdown-timeout",
    ):
        assert option in result.output
    assert "127.0.0.1" in result.output
    assert "8766" in result.output
    assert "no authentication" in result.output


def test_registered_as_explicit_subcommand() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "http-server" in result.output


def test_build_server_config_uses_settings_defaults() -> None:
    settings = get_settings()

    config = build_server_config(settings)

    assert config == HttpServerConfig(
        host=settings.http_host,
        port=settings.http_port,
        max_connections=settings.http_max_connections,
        max_inflight_runs=settings.http_max_inflight_runs,
        max_request_bytes=settings.http_max_request_bytes,
        event_buffer_size=settings.http_event_buffer_size,
        run_history_size=settings.http_run_history_size,
        request_timeout=settings.http_request_timeout,
        shutdown_timeout=settings.http_shutdown_timeout,
    )
    assert (config.host, config.port) == ("127.0.0.1", 8766)


def test_build_server_config_overrides_only_the_given_fields() -> None:
    settings = get_settings()

    config = build_server_config(settings, port=9999, max_inflight_runs=2, request_timeout=1.5)

    assert (config.port, config.max_inflight_runs, config.request_timeout) == (9999, 2, 1.5)
    # 未覆盖的字段仍取 Settings（不因某几项覆盖而整体重置）
    assert (config.host, config.max_connections) == (settings.http_host, settings.http_max_connections)


def test_defaults_reach_the_listening_config(captured_server: dict[str, HttpServer]) -> None:
    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    server = captured_server["server"]
    assert (server.config.host, server.config.port) == ("127.0.0.1", 8766)
    assert (server.config.max_connections, server.config.max_inflight_runs) == (16, 1)
    assert (server.config.event_buffer_size, server.config.run_history_size) == (512, 64)
    assert (server.config.request_timeout, server.config.shutdown_timeout) == (300.0, 5.0)
    # 健康检查对外报告的版本号取自包元数据（不硬编码在传输层）。
    assert server.version == __version__


def test_settings_env_drives_defaults(monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]) -> None:
    """未传 CLI 参数时用 Settings（env）的值——CLI 与 env 走同一套字段。"""
    monkeypatch.setenv("HTTP_PORT", "9100")
    monkeypatch.setenv("HTTP_MAX_INFLIGHT_RUNS", "3")
    monkeypatch.setenv("HTTP_RUN_HISTORY_SIZE", "8")
    reset_settings()

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    server = captured_server["server"]
    assert (server.config.port, server.config.max_inflight_runs, server.config.run_history_size) == (9100, 3, 8)


def test_cli_overrides_reach_the_config_without_mutating_settings(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]
) -> None:
    """CLI 覆盖只作用于本次实例：Settings 单例保持 env 默认值（与 TCP 入口同语义）。"""
    reset_settings()
    settings = get_settings()

    result = CliRunner().invoke(
        main,
        ["http-server", "--port", "9401", "--max-inflight-runs", "2", "--shutdown-timeout", "1.5"],
    )

    assert result.exit_code == 0, result.output
    server = captured_server["server"]
    assert (server.config.port, server.config.max_inflight_runs, server.config.shutdown_timeout) == (9401, 2, 1.5)
    assert (settings.http_port, settings.http_max_inflight_runs, settings.http_shutdown_timeout) == (8766, 1, 5.0)


@pytest.mark.parametrize(
    "args",
    [
        ["--port", "0"],
        ["--port", "70000"],
        ["--max-connections", "0"],
        ["--max-inflight-runs", "0"],
        ["--max-request-bytes", "0"],
        ["--event-buffer-size", "0"],
        ["--run-history-size", "0"],
        ["--request-timeout", "-1"],
        ["--request-timeout", "inf"],
        ["--request-timeout", "nan"],
        ["--shutdown-timeout", "0"],
        ["--shutdown-timeout", "nan"],
    ],
)
def test_invalid_limits_are_rejected_before_serving(args: list[str], captured_server: dict[str, HttpServer]) -> None:
    """CLI 侧用同一套范围规则拦下非法值（与 Settings 校验同义：端口 1..65535、计数 >=1、超时 >0）。"""
    result = CliRunner().invoke(main, ["http-server", *args])

    assert result.exit_code == 2
    assert "server" not in captured_server


def test_startup_failure_is_reported_without_a_listening_banner(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """绑定失败（端口占用 / 地址不可用）必须显性失败，且不谎报「已监听」。"""
    monkeypatch.setattr("heagent.cli_http._build_provider", lambda settings, model: _StubProvider())
    monkeypatch.chdir(tmp_path)
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        result = CliRunner().invoke(main, ["http-server", "--port", str(port)])
    finally:
        holder.close()

    assert result.exit_code == 1
    assert "HTTP server failed to start" in result.output
    assert "listening on" not in result.output
    assert "Traceback" not in result.output


def test_missing_http_extra_reports_the_install_hint(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """缺 ``heagent[http]`` 时给安装诊断，而不是 ImportError 栈。"""
    from heagent.network import http_server as http_server_module
    from heagent.network.http_server import HttpDependencyError

    def _missing(name: str) -> Any:
        raise HttpDependencyError(f"missing {name!r}; install with: pip install 'heagent[http]'")

    monkeypatch.setattr(http_server_module, "_require_module", _missing)
    monkeypatch.setattr("heagent.cli_http._build_provider", lambda settings, model: _StubProvider())
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 1
    assert "heagent[http]" in result.output
    assert "Traceback" not in result.output


def test_default_loopback_binding_prints_no_exposure_warning(captured_server: dict[str, HttpServer]) -> None:
    """回环绑定不告警：告警一旦常见就会退化成被忽略的噪音。"""
    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    assert "WARNING" not in result.output


def test_non_loopback_host_prints_one_exposure_warning(captured_server: dict[str, HttpServer]) -> None:
    """``--host 0.0.0.0`` 启动时 CLI 向 stderr 打**一行**告警（含无认证 / 无 TLS / 非生产安全边界）。"""
    result = CliRunner().invoke(main, ["http-server", "--host", "0.0.0.0"])

    assert result.exit_code == 0, result.output
    warnings = [line for line in result.output.splitlines() if "[http] WARNING:" in line]
    assert len(warnings) == 1
    line = warnings[0]
    assert "0.0.0.0" in line
    assert "no authentication" in line
    assert "no TLS" in line
    assert "not a production security boundary" in line


def test_explicit_subcommand_paths_do_not_go_through_the_embedded_service(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer], embedded_http_services: list[Any]
) -> None:
    """显式 `http-server` 命令走自己的路径：不经默认 CLI 的内嵌服务（后者只属 ``run``）。

    真实的「默认 CLI 会启动内嵌服务」与「各子命令不派生第二实例」由
    ``tests/test_cli_http_lifecycle.py`` 覆盖（那里能驱动真实 run 路径并拿到替身/真实端口）。
    """
    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    assert "server" in captured_server
    assert embedded_http_services == []
