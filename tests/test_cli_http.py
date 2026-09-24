"""Story 49-1 / 50-3：``heagent http-server`` CLI 接线（命令注册 / 参数映射 / 不隐式监听 / 单项目运行时）。

本文件只测**入口层**：命令注册、参数映射、绑定失败的可读错误、「导入 CLI 不会拉起可选 HTTP 栈」，
以及 Story 50-3 的两条接线不变量——**HTTP 进程内不构造 ``CronScheduler``**（评审 F2）与**每个项目
各自独立的运行时切片**。HTTP 传输层与生命周期行为在 ``tests/network/test_http_server.py``。
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from heagent import __version__
from heagent import cli as cli_module
from heagent.cli import main
from heagent.cli_http import HttpAgentHandler, HttpProjectConsole, build_server_config
from heagent.config import get_settings, reset_settings
from heagent.context.session import SessionStore
from heagent.network.http_server import HttpServer, HttpServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage
from heagent.workspace import WorkspacePaths


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
        [
            "http-server",
            "--port",
            "9401",
            "--max-inflight-runs",
            "2",
            "--shutdown-timeout",
            "1.5",
        ],
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
    """CLI 侧用同一套范围规则拦下非法值（端口 1..65535、计数 >=1、超时 >0）。"""
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


# ── Story 50-3：单项目运行时的接线不变量 ──


def test_new_loop_refuses_to_own_a_cron_scheduler(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """评审 F2：传入 session 后，「HTTP 侧没有后台调度」必须靠**显式** ``enable_cron=False``。

    两半都钉住：①``new_loop()`` 真的把 ``enable_cron=False`` 与 ``session`` 传下去；②即便
    ``_build_loop`` 将来不听话地回了调度器，``new_loop()`` 也必须**显式失败**——把带无人监督执行面的
    运行时装进 HTTP 进程是 49-5 明令禁止的形态，静默忽略等于把 forbid 变成注释。
    """
    seen: dict[str, Any] = {}
    real_build = cli_module._build_loop  # noqa: SLF001 - 本用例的意义就是钉住「谁调它、怎么调」

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real_build(*args, **kwargs)

    monkeypatch.setattr("heagent.cli._build_loop", spy)
    store = SessionStore(str(tmp_path / "sessions"))
    handler = HttpAgentHandler(_StubProvider(), get_settings(), workspace_root=tmp_path, session_store=store)

    loop = handler.new_loop()

    assert seen["enable_cron"] is False
    assert seen["session"] is store
    assert loop.session is store  # 运行因此真的会写这个会话存储（此前是 session=None）

    monkeypatch.setattr("heagent.cli._build_loop", lambda *args, **kwargs: (loop, object()))
    with pytest.raises(RuntimeError, match="must not own a CronScheduler"):
        handler.new_loop()


def test_for_workspace_rebinds_paths_and_sessions_per_project(tmp_path: Path) -> None:
    """跨项目零共享可变状态：路径派生、会话存储、引擎都指向各自的项目根（脊柱 §6）。

    连接与策略参数（provider / settings / system / 迭代与沙箱参数）**共享**——它们不含项目数据。
    """
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    base = HttpAgentHandler(
        _StubProvider(),
        get_settings(),
        workspace_root=root_a,
        session_store=SessionStore(str(root_a / ".heagent" / "sessions")),
    )

    other = base.for_workspace(WorkspacePaths.from_root(root_b), SessionStore(str(root_b / ".heagent" / "sessions")))

    assert (base.paths.root, other.paths.root) == (Path(root_a), Path(root_b))
    assert base.session_store is not other.session_store
    assert base.session_store is not None and other.session_store is not None
    assert Path(str(other.session_store._base)) == root_b / ".heagent" / "sessions"  # noqa: SLF001 - 落点即契约
    assert base.engine is not other.engine
    assert base.provider is other.provider


def test_http_server_command_wires_the_console_for_project_runs(captured_server: dict[str, HttpServer]) -> None:
    """``http-server`` 把运行服务与 per-project 工厂一起交给 console（否则项目内运行永远 409）。"""
    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    server = captured_server["server"]
    console = server.console
    assert isinstance(console, HttpProjectConsole)
    runtime = console._runtime_for("default")  # noqa: SLF001 - 接线点本身就是要断言的事实
    assert runtime.executor is not None
    assert Path(str(runtime.sessions._base)) == Path.cwd() / ".heagent" / "sessions"  # noqa: SLF001
