"""Story 49-1 / 50-3：``heagent http-server`` CLI 接线（命令注册 / 参数映射 / 不隐式监听 / 单项目运行时）。

本文件只测**入口层**：命令注册、参数映射、绑定失败的可读错误、「导入 CLI 不会拉起可选 HTTP 栈」，
以及 Story 50-3 的接线不变量——**HTTP 入口拥有完整 cron 工具面、但 handler 内不启停调度器**
（2026-10-28 改判：原「不绑 cron 工具」的 A11② 形态已按用户裁决撤销）与**每个项目各自独立的
运行时切片**。HTTP 传输层与生命周期行为在 ``tests/network/test_http_server.py``。
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from heagent import __version__
from heagent.cli import composition as cli_module
from heagent.cli.console import main
from heagent.cli.http_console import HttpAgentHandler, HttpProjectConsole
from heagent.cli.http import build_server_config, build_http_service
from heagent.config import Settings, get_settings, reset_settings
from heagent.context.session import SessionStore
from heagent.network.http_server import HttpServer, HttpServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, TokenUsage
from heagent.pub.workspace import WorkspacePaths


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
    """把 ``_serve_web`` 换成「记录双 server 即返回」：参数断言不需要真的绑定端口。"""
    captured: dict[str, Any] = {}

    async def fake_serve(http_server: HttpServer, ws_servers: Any) -> None:
        captured["server"] = http_server
        captured["ws"] = ws_servers

    monkeypatch.setattr("heagent.cli.http._serve_web", fake_serve)
    monkeypatch.setattr("heagent.cli.http._build_provider", lambda settings, model: _StubProvider())
    monkeypatch.chdir(tmp_path)
    return captured


def test_help_lists_http_options() -> None:
    result = CliRunner().invoke(main, ["http-server", "--help"])

    assert result.exit_code == 0
    for option in (
        "--no-http",
        "--no-ws",
        "--host",
        "--port",
        "--max-connections",
        "--max-subscribers",
        "--ws-host",
        "--ws-port",
        "--ws-max-connections",
        "--ws-external-host",
        "--ws-external-port",
        "--ws-external-readonly",
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
    assert "--ws-max-connections" in result.output


def test_ws_connection_limit_cli_override_reaches_config_without_mutating_settings(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]
) -> None:
    monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
    monkeypatch.setenv("WS_MAX_CONNECTIONS", "7")
    reset_settings()
    settings = get_settings()

    result = CliRunner().invoke(main, ["http-server", "--ws-max-connections", "3"])

    assert result.exit_code == 0, result.output
    assert captured_server["ws"][0].config.ws_max_connections == 3
    assert settings.ws_max_connections == 7


def test_ws_connection_limit_environment_value_reaches_config(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]
) -> None:
    monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
    monkeypatch.setenv("WS_MAX_CONNECTIONS", "9")
    reset_settings()

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    assert captured_server["ws"][0].config.ws_max_connections == 9


def test_ws_listener_env_reaches_ws_server_config(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, Any]
) -> None:
    """WS_HOST/WS_PORT env 经 http-server 命令落到 WsServer 配置（D1：WS 面独立成配置）。"""
    monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
    monkeypatch.setenv("WS_HOST", "127.0.0.1")
    monkeypatch.setenv("WS_PORT", "9443")
    reset_settings()

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    ws_server = captured_server["ws"][0]
    assert (ws_server.config.host, ws_server.config.port) == ("127.0.0.1", 9443)


def test_registered_as_explicit_subcommand() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "http-server" in result.output


def test_build_server_config_uses_settings_defaults() -> None:
    settings = get_settings()

    # 显式钉住端口路径：默认顺延开启后，裸调用会因 8766 被真实占用而环境化（2026-10-15）。
    config = build_server_config(settings, port=settings.http_port)

    assert config == HttpServerConfig(
        host=settings.http_host,
        port=settings.http_port,
        max_connections=settings.http_max_connections,
        max_subscribers=settings.http_max_subscribers,
        max_inflight_runs=settings.http_max_inflight_runs,
        max_total_inflight=settings.http_max_total_inflight,
        max_request_bytes=settings.http_max_request_bytes,
        event_buffer_size=settings.http_event_buffer_size,
        run_history_size=settings.http_run_history_size,
        request_timeout=settings.http_request_timeout,
        idle_timeout=settings.http_idle_timeout,
        shutdown_timeout=settings.http_shutdown_timeout,
    )
    assert (config.host, config.port) == ("127.0.0.1", 8766)


def test_build_server_config_overrides_only_the_given_fields() -> None:
    settings = get_settings()

    config = build_server_config(
        settings, port=9999, max_inflight_runs=2, max_total_inflight=3, request_timeout=1.5, idle_timeout=2.5
    )

    assert (config.port, config.max_inflight_runs, config.max_total_inflight) == (9999, 2, 3)
    assert (config.request_timeout, config.idle_timeout) == (1.5, 2.5)
    # 未覆盖的字段仍取 Settings（不因某几项覆盖而整体重置）
    assert (config.host, config.max_connections) == (settings.http_host, settings.http_max_connections)


def test_defaults_reach_the_listening_config(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]
) -> None:
    # 默认顺延开启后端口可能被真实占用而顺延：钉住 finder=0 断言纯默认值（2026-10-15）。
    monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
    reset_settings()
    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    server = captured_server["server"]
    assert (server.config.host, server.config.port) == ("127.0.0.1", 8766)
    assert (server.config.max_connections, server.config.max_inflight_runs) == (16, 1)
    # 订阅额度与连接额度**各有旋钮**（2026-09-28 拆键）：默认值相同 ⇒ 默认行为不变。
    assert (server.config.max_connections, server.config.max_subscribers) == (16, 16)
    # 服务级总额默认不限（0）——不设即保持「每项目各一份」的 D9 语义。
    assert server.config.max_total_inflight == 0
    assert (server.config.event_buffer_size, server.config.run_history_size) == (512, 64)
    # 默认**不设**总时长硬上限（0 = 不限制），卡死交给 300s 的静默判定（2026-09-24 修复）。
    assert (server.config.request_timeout, server.config.idle_timeout) == (0.0, 300.0)
    assert server.config.shutdown_timeout == 5.0
    # 健康检查对外报告的版本号取自包元数据（不硬编码在传输层）。
    assert server.version == __version__


def _spy_picker_backends(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """记录 ``HttpProjectConsole`` 装配 ``DirectoryPicker`` 时拿到的后端取值。

    钉的是**默认值**：此前只有「显式传 ``none``」的用例（改默认值对它们毫无影响），
    2026-09-28 实测确认「把默认值改回 ``auto``」不会让任何用例变红 ⇒ A19 的裁定当时没有可执行判据。
    """
    from heagent.cli import http_console as http_console_module

    seen: list[str] = []
    real_picker = http_console_module.DirectoryPicker

    def spy(backend: str) -> Any:
        seen.append(backend)
        return real_picker(backend)

    monkeypatch.setattr(http_console_module, "DirectoryPicker", spy)
    return seen


def test_dialog_backend_defaults_to_disabled(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]
) -> None:
    """A19：``heagent http-server`` 的 ``--dialog-backend`` 默认 ``none``（原生目录选择默认关）。"""
    seen = _spy_picker_backends(monkeypatch)

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    assert seen == ["none"], "默认档必须是禁用；改回 auto 会让本用例变红"


@pytest.mark.embedded_http_service
def test_embedded_service_also_disables_the_directory_dialog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A19：默认 CLI 的**内嵌**服务同样默认关（``build_http_service`` 不传该参数 ⇒ 走控制台默认值）。"""
    monkeypatch.chdir(tmp_path)
    seen = _spy_picker_backends(monkeypatch)

    build_http_service(get_settings())

    assert seen == ["none"]


def test_settings_env_drives_defaults(monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]) -> None:
    """未传 CLI 参数时用 Settings（env）的值——CLI 与 env 走同一套字段。"""
    monkeypatch.setenv("HTTP_PORT", "9100")
    monkeypatch.setenv("HTTP_MAX_INFLIGHT_RUNS", "3")
    monkeypatch.setenv("HTTP_MAX_SUBSCRIBERS", "5")
    monkeypatch.setenv("HTTP_MAX_TOTAL_INFLIGHT", "4")
    monkeypatch.setenv("HTTP_RUN_HISTORY_SIZE", "8")
    monkeypatch.setenv("HTTP_IDLE_TIMEOUT", "7")
    reset_settings()

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    server = captured_server["server"]
    assert (server.config.port, server.config.max_inflight_runs, server.config.run_history_size) == (9100, 3, 8)
    assert server.config.max_total_inflight == 4
    assert server.config.max_subscribers == 5
    assert server.config.idle_timeout == 7.0


def test_cli_overrides_reach_the_config_without_mutating_settings(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]
) -> None:
    """CLI 覆盖只作用于本次实例：Settings 单例保持 env 默认值。"""
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
            "--max-total-inflight",
            "3",
            "--max-subscribers",
            "4",
            "--shutdown-timeout",
            "1.5",
            "--idle-timeout",
            "0",
            "--request-timeout",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    server = captured_server["server"]
    assert (server.config.port, server.config.max_inflight_runs, server.config.shutdown_timeout) == (9401, 2, 1.5)
    assert server.config.max_total_inflight == 3
    assert server.config.max_subscribers == 4
    # ``0`` 是**合法**取值（关掉该时限 / 不设总时长上限），CLI 边界不得比配置层更严（2026-09-24）。
    assert (server.config.idle_timeout, server.config.request_timeout) == (0.0, 0.0)
    assert (settings.http_port, settings.http_max_inflight_runs, settings.http_shutdown_timeout) == (8766, 1, 5.0)
    # CLI 覆盖不写回 Settings：服务级总额仍是 env / 默认值。
    assert settings.http_max_total_inflight == 0
    assert settings.http_idle_timeout == 300.0


@pytest.mark.parametrize(
    "args",
    [
        ["--port", "0"],
        ["--port", "70000"],
        ["--max-connections", "0"],
        ["--max-subscribers", "0"],
        ["--ws-max-connections", "0"],
        ["--max-inflight-runs", "0"],
        ["--max-total-inflight", "-1"],
        ["--max-request-bytes", "0"],
        ["--event-buffer-size", "0"],
        ["--run-history-size", "0"],
        ["--request-timeout", "-1"],
        ["--request-timeout", "inf"],
        ["--request-timeout", "nan"],
        ["--idle-timeout", "-1"],
        ["--idle-timeout", "nan"],
        ["--shutdown-timeout", "0"],
        ["--shutdown-timeout", "nan"],
    ],
)
def test_invalid_limits_are_rejected_before_serving(args: list[str], captured_server: dict[str, HttpServer]) -> None:
    """CLI 侧用同一套范围规则拦下非法值（端口 1..65535、计数 >=1）。

    超时里只有 ``--shutdown-timeout`` 仍要求 ``>0``（0 会让「有界关闭」变成无界等待）；
    两条运行时限的 ``0`` 是**合法语义**（0 = 关掉该时限），故不在此列表（2026-09-24）。
    """
    result = CliRunner().invoke(main, ["http-server", *args])

    assert result.exit_code == 2
    assert "server" not in captured_server


def test_startup_failure_is_reported_without_a_listening_banner(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """绑定失败（端口占用 / 地址不可用）必须显性失败，且不谎报「已监听」。"""
    monkeypatch.setattr("heagent.cli.http._build_provider", lambda settings, model: _StubProvider())
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


def test_explicit_port_is_never_silently_replaced() -> None:
    """端口顺延的两条边界：**默认开启（10 次）**，且**显式 ``--port`` 永不被改写**。

    2026-09-27 的「端口自动查找」最初对**显式端口**也顺延 ⇒ 占用端口时服务照常起来，
    上面那条「启动失败必须显性」的用例于是永久 hang（全量套件跑不完）⇒ 曾改为默认关闭。
    2026-10-15 契约修订：默认重新开启（=10，多开实例不冲突），但「显式端口永不顺延」
    的 fail-loud 契约不变——hang 的根因（显式端口被改写）早已修掉。
    """
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    busy = holder.getsockname()[1]
    try:
        assert Settings(_env_file=None).http_port_auto_find_attempts == 10, "默认必须开启顺延（多开不冲突）"

        settings = Settings(_env_file=None, http_port=busy, http_port_auto_find_attempts=10)
        assert build_server_config(settings, port=busy).port == busy, "显式端口被静默改写"

        moved = build_server_config(settings).port
        assert moved != busy, "未显式指定端口时应顺延到空闲端口"
        assert moved > busy
    finally:
        holder.close()


def test_missing_http_extra_reports_the_install_hint(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """缺 ``heagent[http]`` 时给安装诊断，而不是 ImportError 栈。"""
    from heagent.network import http_server as http_server_module
    from heagent.network.http_server import HttpDependencyError

    def _missing(name: str) -> Any:
        raise HttpDependencyError(f"missing {name!r}; install with: pip install 'heagent[http]'")

    monkeypatch.setattr(http_server_module, "_require_module", _missing)
    monkeypatch.setattr("heagent.cli.http._build_provider", lambda settings, model: _StubProvider())
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


def test_new_loop_binds_the_full_cron_surface(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """2026-10-28 裁决：网页会话与交互模式拥有**同一套** cron 工具面（``enable_cron=True``）。

    接线断言三条：①``enable_cron=True`` 与 session 一起传下去；②loop 真的绑了**该项目**的
    ``JobStore``（端口可达者因此能 `cron_list`，也能 `cron_add`/`cron_remove`——A11② 的写面风险
    改为显式接受，任务由交互模式 / GUI 的调度器触发）；③本方法**不启动**调度器：即便
    ``_build_loop`` 回了 ``CronScheduler``，也只是丢弃（不 start、不抛），进程级 start/stop
    归 ``cli/interactive.py`` 与 ``gui/app.py``。
    """
    from heagent.cron.jobs import JobStore

    seen: dict[str, Any] = {}
    real_build = cli_module._build_loop  # noqa: SLF001 - 本用例的意义就是钉住「谁调它、怎么调」

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real_build(*args, **kwargs)

    monkeypatch.setattr("heagent.cli.composition._build_loop", spy)
    sessions = SessionStore(str(tmp_path / "sessions"))
    settings = Settings(_env_file=None, cron_enabled=True)
    handler = HttpAgentHandler(_StubProvider(), settings, workspace_root=tmp_path, session_store=sessions)

    loop = handler.new_loop()

    assert seen["enable_cron"] is True
    assert seen["session"] is sessions
    assert loop.session is sessions  # 运行因此真的会写这个会话存储（此前是 session=None）
    assert isinstance(loop.cron_store, JobStore)
    # store 指向该项目的 jobs.json，读到的是**盘上现值**（list_jobs 每次加载、无缓存）——
    # 交互式 CLI 刚写的任务，网页会话的下一次 run 立刻可见。
    cron_file = WorkspacePaths.from_root(tmp_path).cron_file
    writer = JobStore(str(cron_file))
    writer.add(writer.create_job("nightly report", "0 9 * * *"))
    assert [job.prompt for job in loop.cron_store.list_jobs()] == ["nightly report"]

    # 调度器被丢弃：不 start、不抛（旧实现见到 scheduler 即 raise，那会让本姿态不可实现）。
    monkeypatch.setattr("heagent.cli.composition._build_loop", lambda *args, **kwargs: (loop, object()))
    assert handler.new_loop() is loop


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


def test_for_workspace_resolves_settings_from_the_project_env(tmp_path: Path) -> None:
    """脊柱 §7：项目运行时的配置解析必须显式传 ``_env_file``（不得退化成服务器 cwd 的 `.env`）。

    评审发现（镜头一 H4，high）：派生 handler 原先**共享**服务级 settings，而服务级 settings 是按
    **进程 cwd** 解析的 ⇒ 非 default 项目的运行读不到该项目 `.env`，而配置面板（50-4）却按项目
    `.env` 报来源与取值——同一键在「面板」与「运行期」两个口径下不一致，且运行端拿的是别的项目的
    配置。本用例钉住「运行端按项目 `.env` 取值」。
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / ".env").write_bytes(b"MAX_ITERATIONS=7\nMAX_CONTEXT_TOKENS=1234\n")
    base = HttpAgentHandler(
        _StubProvider(),
        get_settings(),
        workspace_root=tmp_path,
        session_store=SessionStore(str(tmp_path / "sessions")),
    )

    derived = base.for_workspace(WorkspacePaths.from_root(root), SessionStore(str(root / ".heagent" / "sessions")))

    assert derived.settings.max_iterations == 7
    assert derived.settings.max_context_tokens == 1234
    assert derived.settings is not base.settings  # 按项目解析，不再共享 cwd 口径的那一份
    assert derived.provider is base.provider  # 连接参数仍共享（脊柱 §6）


def test_for_workspace_falls_back_when_the_project_env_is_invalid(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """坏掉的项目 `.env` 只影响它自己：回退服务级 settings 并留 WARNING，不阻断控制台。"""
    root = tmp_path / "bad"
    root.mkdir()
    (root / ".env").write_bytes(b"MAX_ITERATIONS=not-a-number\n")
    base = HttpAgentHandler(
        _StubProvider(),
        get_settings(),
        workspace_root=tmp_path,
        session_store=SessionStore(str(tmp_path / "sessions")),
    )

    derived = base.for_workspace(WorkspacePaths.from_root(root), SessionStore(str(root / ".heagent" / "sessions")))

    assert derived.settings is base.settings
    assert "is unusable" in caplog.text


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


# ── Story 50-5：写入闸门 / 注册表落点 / 生效语义 ──


def test_write_gate_defaults_to_closed(captured_server: dict[str, HttpServer]) -> None:
    """D4/I12：默认关；网页任何请求都改不到它（它自己不在白名单里）。"""
    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    console = captured_server["server"].console
    assert isinstance(console, HttpProjectConsole)
    assert console.write_enabled is False
    assert "write channel is ENABLED" not in (result.stderr or "")


def test_write_gate_can_be_opened_by_startup_configuration(
    captured_server: dict[str, HttpServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4：任何**启动**配置渠道都能开（此处用系统环境变量），且启动时必须打高亮告警（stderr + 日志）。"""
    monkeypatch.setenv("HTTP_CONSOLE_WRITE_ENABLED", "true")

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    console = captured_server["server"].console
    assert isinstance(console, HttpProjectConsole)
    assert console.write_enabled is True
    assert "config write channel is ENABLED" in (result.stderr or "")


def test_console_honours_the_configured_registry_path(
    captured_server: dict[str, HttpServer], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``HTTP_CONSOLE_PROJECTS_FILE`` 必须真的被接线（否则该键是死的）；缺省仍是启动工作区内那份。"""
    shared = tmp_path / "shared-projects.json"
    monkeypatch.setenv("HTTP_CONSOLE_PROJECTS_FILE", str(shared))
    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    console = captured_server["server"].console
    assert isinstance(console, HttpProjectConsole)
    assert Path(str(console.registry._path)) == shared  # noqa: SLF001 - 落点即契约


def test_write_channel_applies_on_the_next_run_only(tmp_path: Path) -> None:
    """T8/I10：写成功后运行时缓存失效 ⇒ **下一次** run 用新快照，在途 run 的旧快照不受影响。

    「在途 run」在实现上就是「已经构造出 ``AgentLoop`` 的那次运行」——loop 在构造期把
    ``ResolvedRuntimeConfig`` 冻进 ``_runtime``，因此本用例直接钉住两件事：旧 loop 的快照仍是旧值、
    下一次取到的 handler 已经解析出新值。
    """
    import asyncio

    from heagent.config import envfile
    from heagent.network.http_console_protocol import ConfigWriteChangeRequest, ConfigWriteRequest

    root = tmp_path / "proj"
    root.mkdir()
    (root / ".env").write_bytes(b"MAX_ITERATIONS=5\n")
    base = HttpAgentHandler(
        _StubProvider(),
        get_settings(),
        workspace_root=tmp_path,
        session_store=SessionStore(str(tmp_path / "sessions")),
    )
    console = HttpProjectConsole(root, handler_factory=base.for_workspace, write_enabled=True, global_setting_file=None)

    before = console._runtime_for("default")  # noqa: SLF001 - 运行时切片本身就是要断言的事实
    assert before.executor is not None
    running = before.executor.new_loop()  # 在途 run（构造期快照）
    fingerprint = envfile.fingerprint((root / ".env").read_bytes())

    written = asyncio.run(
        console.update_project_config(
            "default",
            ConfigWriteRequest(
                changes=[ConfigWriteChangeRequest(key="MAX_ITERATIONS", value="42")],
                fingerprint=fingerprint,
            ),
        )
    )

    assert written.applied == "next_run"
    assert console.config_generation("default") == 1
    after = console._runtime_for("default")  # noqa: SLF001
    assert after is not before  # 缓存已失效 ⇒ 重新解析
    assert after.executor is not None and after.executor.settings.max_iterations == 42
    assert running._runtime.max_iterations == 5  # noqa: SLF001 - 在途 run 继续用旧快照
    assert before.executor.settings.max_iterations == 5  # 旧 handler 不被就地改写
    assert written.changes[0].key == "MAX_ITERATIONS" and written.changes[0].value == 42
    assert written.changes[0].source.value == "project_env"


# ---- Epic 56 Story 56-2/56-3：对外模式在命令层的显式失败与公告 ----


def _write_user_setting(tmp_path: Path, token: str | None) -> Path:
    path = tmp_path / "setting.md"
    body = "---\n" + (f"WS_AUTH_TOKEN: {token}\n" if token is not None else "\n") + "---\n"
    path.write_text(body, encoding="utf-8")
    return path


def test_external_ws_bind_without_token_fails_closed_at_the_command_level(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer], tmp_path: Path
) -> None:
    """非回环 WS 绑定缺 token：命令级一行可读错误 + exit 1，**不**打印任何监听公告。"""
    monkeypatch.setattr(Settings, "_user_setting_file", _write_user_setting(tmp_path, None))

    result = CliRunner().invoke(main, ["http-server", "--ws-host", "0.0.0.0"])

    assert result.exit_code == 1, result.output
    assert "WS_AUTH_TOKEN" in result.output
    assert "Traceback" not in result.output
    assert "[ws] listening" not in result.output
    assert "server" not in captured_server  # 根本没进服务编排


def test_external_ws_bind_with_token_announces_token_and_plaintext(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer], tmp_path: Path
) -> None:
    """有 token + 无 TLS：公告写 wss 以外的真实传输，并给出明文告警（D4 的可见性要求）。"""
    monkeypatch.setattr(Settings, "_user_setting_file", _write_user_setting(tmp_path, "s3cret"))

    result = CliRunner().invoke(main, ["http-server", "--ws-host", "0.0.0.0"])

    assert result.exit_code == 0, result.output
    assert captured_server["ws"][0].config.requires_auth is True
    assert "WS_AUTH_TOKEN in the project .env is ignored" not in result.output
    assert "external WS mode without TLS" in result.output
    # token 绝不出现在命令输出里。
    assert "s3cret" not in result.output


def test_external_listener_cli_overrides_build_a_second_listener(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer], tmp_path: Path
) -> None:
    """期二 D8：`--ws-external-host/--ws-external-port` 落到第二个 listener，主 listener 不受影响。"""
    monkeypatch.setattr(Settings, "_user_setting_file", _write_user_setting(tmp_path, "s3cret"))
    monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
    reset_settings()

    result = CliRunner().invoke(
        main,
        ["http-server", "--ws-external-host", "0.0.0.0", "--ws-external-port", "9202"],
    )

    assert result.exit_code == 0, result.output
    servers = captured_server["ws"]
    assert [server.config.mode for server in servers] == ["local", "external"]
    assert servers[0].config.port == 9901
    assert (servers[1].config.host, servers[1].config.port) == ("0.0.0.0", 9202)
    # 对外那条按 mode 分流告警：不能套用 HTTP 的「no authentication」文案（它是 token 认证）。
    assert "external mode; Bearer token required; PLAINTEXT" in result.output


def test_external_readonly_cli_flag_reaches_the_listener(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer], tmp_path: Path
) -> None:
    """P2-A3：`--ws-external-readonly` 让对外 listener 只订阅、不提交（主 listener 不受影响）。"""
    monkeypatch.setattr(Settings, "_user_setting_file", _write_user_setting(tmp_path, "s3cret"))

    result = CliRunner().invoke(
        main,
        ["http-server", "--ws-external-host", "0.0.0.0", "--ws-external-readonly"],
    )

    assert result.exit_code == 0, result.output
    servers = captured_server["ws"]
    assert [server.config.readonly for server in servers] == [False, True]


def test_external_listener_cli_override_rejects_a_loopback_host(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer], tmp_path: Path
) -> None:
    """期二 D8：CLI 覆盖同样走 fail-loud 校验（回环地址不是被静默忽略）。"""
    monkeypatch.setattr(Settings, "_user_setting_file", _write_user_setting(tmp_path, "s3cret"))

    result = CliRunner().invoke(main, ["http-server", "--ws-external-host", "127.0.0.1"])

    assert result.exit_code == 1, result.output
    assert "non-loopback" in result.output
    assert "server" not in captured_server
    assert "Traceback" not in result.output


def test_project_env_token_is_reported_as_ignored(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer], tmp_path: Path
) -> None:
    """项目 `.env` 里写 token 不生效：启动时必须说出来（否则用户以为已经认证过）。"""
    monkeypatch.setattr(Settings, "_user_setting_file", _write_user_setting(tmp_path, None))
    (tmp_path / ".env").write_text("WS_AUTH_TOKEN=from-project-env\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    assert "WS_AUTH_TOKEN in the project .env is ignored" in result.output
    assert captured_server["ws"][0].config.requires_auth is False


def test_no_http_flag_starts_only_the_ws_listener(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, Any]
) -> None:
    """``--no-http``：只起 WS，且必须明说 HTTP 被 CLI 关掉（不静默）。"""
    monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
    reset_settings()

    result = CliRunner().invoke(main, ["http-server", "--no-http"])

    assert result.exit_code == 0, result.output
    assert captured_server["server"] is None
    assert len(captured_server["ws"]) == 1
    assert "[web] HTTP entry disabled by CLI flag" in result.output


def test_no_ws_flag_starts_only_the_http_listener(
    monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, Any]
) -> None:
    """``--no-ws``：只起 HTTP。"""
    monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
    reset_settings()

    result = CliRunner().invoke(main, ["http-server", "--no-ws"])

    assert result.exit_code == 0, result.output
    assert captured_server["server"] is not None
    assert captured_server["ws"] == ()
    assert "[web] WS entry disabled by CLI flag" in result.output


def test_both_no_flags_fail_fast(captured_server: dict[str, Any]) -> None:
    """两个 flag 同时给 = 什么都不起：命令层 fail-loud，不留「启动成功但零监听」的假可用。"""
    result = CliRunner().invoke(main, ["http-server", "--no-http", "--no-ws"])

    assert result.exit_code != 0
    assert "nothing to serve" in result.output
    assert "server" not in captured_server
    assert "Traceback" not in result.output
