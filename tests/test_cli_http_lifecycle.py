"""Story 49-2：默认 CLI 的内嵌 HTTP 服务与生命周期。

覆盖两件事：

- **默认路径**（`heagent` / `heagent "prompt"` / `heagent run ...`）在**同一个 asyncio 生命周期**里
  启动 HTTP 服务：交互模式与 REPL 共存，单次模式与那次 run 并存并在结束后释放端口；绑定失败让
  命令显式失败（不进入聊天）。
- **显式非 HTTP 子命令**（`gui` / `http-server` / `replay` …）不会派生第二个实例。

测试手法：**替换 provider 而不是 `_run_single` / `_run_chat`**。HTTP 生命周期就在这两个入口内部，
把它们整体打桩等于把被测代码一并打桩（第一版就这么踩过：`_run_single` 被 fake 掉后服务根本没起，
断言只能看到 `ConnectError`）。替换 provider 既能驱动真实的 run 路径，又能在 run **进行中**探测
网页入口。

`tests/conftest.py` 默认把内嵌服务替换成替身（否则每个 CLI 测试都会抢 9101 端口）；需要真实绑定
的用例加 ``@pytest.mark.embedded_http_service`` 退出替身，并用随机空闲端口。
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import time
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx
from click.testing import CliRunner

from heagent.cli.console import main
from heagent.cli.http import build_http_service
from heagent.config import get_settings, reset_settings
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, TokenUsage


def _free_port() -> int:
    """向操作系统要一个当前空闲的端口（随后被 HTTP 服务绑定）。"""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _assert_port_free(port: int) -> None:
    """端口上已没有 listener：connect 必须被拒绝。

    刻意**不用** ``bind`` 判定（2026-10-24，epic-56 retro P2-A1）：服务关闭后同一四元组进入
    TIME_WAIT 是正常 OS 行为，``bind`` 会报 ``EADDRINUSE``——Linux 上要加 ``SO_REUSEADDR`` 才能
    立刻重绑，而 Windows 的 ``SO_REUSEADDR`` 又允许抢占别人正在监听的端口（会让断言假绿）。
    两头都不是可靠判据。「还有人在听吗」只有 connect 能回答：回环上未监听的端口立刻回 RST
    （``ECONNREFUSED``），已关闭的 listener 因此**必然**让这里抛错。
    """
    probe = socket.socket()
    probe.settimeout(2.0)
    try:
        with pytest.raises(OSError):
            probe.connect(("127.0.0.1", port))
    finally:
        probe.close()


async def _fetch_health(port: int) -> int:
    """**异步**请求健康检查：测试与服务共用同一个事件循环，同步 httpx 会把服务一起阻塞。"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        return (await client.get(f"http://127.0.0.1:{port}/api/health")).status_code


async def _raw_status(port: int) -> int:
    """裸 HTTP GET 的状态码：连不上 / 无应答都会抛错，故「返回了状态码」= accept 循环还活着。

    WS listener 没有健康端点，这里不断言具体码（404/426 都证明 ASGI 栈在应答），只证明**有人在听**。
    异步实现是硬要求：同步 urllib 会阻塞与服务共用的那个事件循环，自己把服务憋死。
    """
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b"GET / HTTP/1.1\r\nhost: 127.0.0.1\r\nconnection: close\r\n\r\n")
        await writer.drain()
        status_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
    finally:
        writer.close()
    match = re.match(rb"HTTP/1\.[01] (\d{3})", status_line)
    assert match, status_line
    return int(match.group(1))


async def _await_failure(service: Any, *, timeout: float) -> BaseException:
    """轮询 ``EmbeddedHttpService.failure``（交互模式每轮就是这么检查的），超时即判失败。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        failure = service.failure
        if failure is not None:
            return failure
        await asyncio.sleep(0.05)
    raise AssertionError("serve 循环死掉后 failure 仍未置位")


class _RecordingProvider:
    """最小 provider：记录 ``send`` 次数，可选用一次真实请求探测网页入口，也可抛错。

    ``send`` 在 **run 进行中**被调用，因此「它里面能打通 ``/api/health``」正好等价于
    「HTTP 服务与这次 run 并存」。
    """

    def __init__(
        self,
        *,
        probe_port: int | None = None,
        observed: list[int] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls = 0
        self._probe_port = probe_port
        self._observed = observed
        self._error = error

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._probe_port is not None and self._observed is not None:
            self._observed.append(await _fetch_health(self._probe_port))
        return ProviderResponse(
            content="stub answer",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    provider: _RecordingProvider,
    *,
    port: int | None = None,
) -> None:
    """把默认 CLI 指向替身 provider（与可选的随机 HTTP 端口），并在 tmp 目录里跑。"""
    if port is not None:
        monkeypatch.setenv("HTTP_PORT", str(port))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("heagent.cli.console._build_provider", lambda settings, model: provider)
    reset_settings()


class _FailingEmbeddedHttp:
    """启动后立刻暴露「serve 循环异常结束」的替身（模拟 Uvicorn 主循环崩溃）。"""

    def __init__(self) -> None:
        self.address = "127.0.0.1:0"
        self.failure: BaseException | None = None
        self.closed = False

    async def start(self) -> None:
        self.failure = RuntimeError("serve loop died")

    async def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> _FailingEmbeddedHttp:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()


def _failing_service(_settings: object, **_kwargs: object) -> _FailingEmbeddedHttp:
    return _FailingEmbeddedHttp()


@pytest.mark.embedded_http_service
def test_single_shot_mode_serves_during_the_run_and_releases_the_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """单次模式：HTTP 与那次 run 并存，运行结束即关闭并释放端口。"""
    port = _free_port()
    observed: list[int] = []
    provider = _RecordingProvider(probe_port=port, observed=observed)
    _drive(monkeypatch, tmp_path, provider, port=port)

    result = CliRunner().invoke(main, ["hi"])

    assert result.exit_code == 0, result.output
    assert observed == [200]
    assert provider.calls == 1
    assert f"web UI: http://127.0.0.1:{port}" in result.output
    _assert_port_free(port)


@pytest.mark.embedded_http_service
def test_interactive_mode_serves_alongside_the_repl(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """交互模式：REPL 与网页入口同时存活，退出后端口释放。"""
    port = _free_port()
    observed: list[int] = []
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider, port=port)

    async def fake_run_prompt(_loop: object, _prompt: str, _system: object, _session_id: str) -> None:
        observed.append(await _fetch_health(port))

    monkeypatch.setattr("heagent.cli.interactive._run_prompt", fake_run_prompt)

    result = CliRunner().invoke(main, [], input="hi\n")

    assert result.exit_code == 0, result.output
    assert observed == [200]
    assert f"web UI: http://127.0.0.1:{port}" in result.output
    _assert_port_free(port)


@pytest.mark.embedded_http_service
def test_env_port_conflict_drifts_instead_of_failing(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """env 端口被占用：按 2026-10-15 契约（a545613）**顺延**到后续端口继续服务，run 正常完成。

    「绑定失败显性失败、不进入 run、不谎报已监听」的 fail-loud 契约保留给**显式 --port**，
    由 ``tests/test_cli_http.py::test_explicit_port_is_never_silently_replaced`` 钉住；
    默认 CLI 入口无 ``--port``，env 端口即自动端口，冲突时顺延而非失败。
    """
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider, port=port)
    try:
        result = CliRunner().invoke(main, ["hi"])
    finally:
        holder.close()

    assert result.exit_code == 0, result.output
    assert provider.calls == 1
    drift = re.search(r"web UI: http://127\.0\.0\.1:(\d+)", result.output)
    assert drift is not None and int(drift.group(1)) > port, f"expected drifted port above {port}: {result.output}"


@pytest.mark.embedded_http_service
def test_missing_http_extra_fails_the_command_with_the_install_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """缺 ``heagent[http]``：显式失败并给安装提示（不静默降级成「没有网页入口但聊天照常」）。"""
    from heagent.network.http_server import HttpDependencyError
    from heagent.network.http_server import listener as http_server_listener

    def _missing(name: str) -> Any:
        raise HttpDependencyError(f"missing {name!r}; install them with: pip install 'heagent[http]'")

    monkeypatch.setattr(http_server_listener, "_require_module", _missing)
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider)

    result = CliRunner().invoke(main, ["hi"])

    assert result.exit_code == 1
    assert "heagent[http]" in result.output
    assert "Traceback" not in result.output
    assert provider.calls == 0


def test_embedded_service_is_closed_when_the_run_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, embedded_http_services: list[Any]
) -> None:
    """run 抛异常也必须走关闭路径（否则端口与任务会泄漏）。"""
    provider = _RecordingProvider(error=RuntimeError("boom"))
    _drive(monkeypatch, tmp_path, provider, port=_free_port())

    result = CliRunner().invoke(main, ["hi"])

    assert result.exit_code != 0
    assert len(embedded_http_services) == 1
    assert embedded_http_services[0].started is True
    assert embedded_http_services[0].closed is True


def test_plain_cli_goes_through_the_embedded_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, embedded_http_services: list[Any]
) -> None:
    """默认 CLI（交互模式）确实经由内嵌服务入口启动并收尾（替身视角，不绑端口）。"""
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider)
    prompted: list[str] = []

    async def fake_run_prompt(_loop: object, prompt: str, _system: object, _session_id: str) -> None:
        prompted.append(prompt)

    monkeypatch.setattr("heagent.cli.interactive._run_prompt", fake_run_prompt)

    result = CliRunner().invoke(main, [], input="hi\n")

    assert result.exit_code == 0, result.output
    assert prompted == ["hi"]
    assert len(embedded_http_services) == 1
    assert embedded_http_services[0].started is True
    assert embedded_http_services[0].closed is True


def test_interactive_mode_stops_when_the_embedded_service_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """网页入口挂掉后不得继续假装可用：交互模式如实报出并退出（AD-5）。"""
    monkeypatch.setattr("heagent.cli.http.build_http_service", _failing_service)
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider)

    result = CliRunner().invoke(main, [])

    assert result.exit_code == 0, result.output
    assert "service stopped unexpectedly" in result.output
    assert "serve loop died" in result.output


def test_explicit_subcommands_never_start_the_embedded_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, embedded_http_services: list[Any]
) -> None:
    """`gui` / `http-server` / `replay` 都不派生内嵌实例（Story 49-2 AC；2026-09-27 TCP 入口删除后同步）。"""
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider)
    served: list[str] = []

    async def fake_serve_web(http_server: object, ws_servers: object, _backend: object = None) -> None:
        served.append("http")
        # 多 listener：显式命令同样装配 WS listener，且至少有一条。
        assert isinstance(ws_servers, tuple) and ws_servers

    monkeypatch.setattr("heagent.cli.http._serve_web", fake_serve_web)
    # cli/http.py 模块级绑定了 `_build_provider`（与 cli/console.py 是两处名字），逐一打桩。
    monkeypatch.setattr("heagent.cli.http._build_provider", lambda settings, model: provider)
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text("", encoding="utf-8")

    runner = CliRunner()
    assert runner.invoke(main, ["http-server"]).exit_code == 0
    assert runner.invoke(main, ["replay", str(rollout)]).exit_code == 0
    assert runner.invoke(main, ["gui", "--help"]).exit_code == 0

    assert served == ["http"]
    assert embedded_http_services == []


async def test_service_lifecycle_is_idempotent_and_reports_no_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """直接驱动真实 ``EmbeddedHttpService``：start → 服务可用 → close（幂等）→ 端口释放。"""
    port = _free_port()
    monkeypatch.setenv("HTTP_PORT", str(port))
    reset_settings()
    service = build_http_service(get_settings())

    await service.start()
    try:
        assert service.address == f"127.0.0.1:{port}"
        assert await _fetch_health(port) == 200
        assert service.failure is None
    finally:
        await service.close()
        await service.close()  # 幂等：第二次是 no-op

    assert service.failure is None
    _assert_port_free(port)


@pytest.mark.embedded_http_service
async def test_one_listener_dying_is_surfaced_while_the_others_keep_serving() -> None:
    """A49：**真实**双 listener 故障注入 —— 一条 serve 循环真死，``failure`` 拿到首个异常，其余仍活。

    注入点选在 uvicorn 自己的 poll 循环里（``Config.callback_notify`` 抛错 ⇒ ``Server.main_loop``
    在 tick 中抛出），不替换 HeAgent 的 ``serve_forever``：被测的传播链（done callback →
    ``_failure`` → 所有者轮询）与真实运行时同一条。其余全部真实：真 socket、真端口、真 HTTP/WS 栈。
    """
    from heagent.cli.http import EmbeddedHttpService
    from heagent.network.http_server import HttpServer, HttpServerConfig
    from heagent.network.ws_host import WsServer, WsServerConfig

    http_server = HttpServer(
        HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0),
        version="test",
    )
    survivor = WsServer(WsServerConfig(port=0, shutdown_timeout=1))
    doomed = WsServer(WsServerConfig(port=0, shutdown_timeout=1))
    service = EmbeddedHttpService(http_server, (survivor, doomed))

    await service.start()
    try:
        assert service.failure is None
        survivor_port = survivor.port
        assert await _fetch_health(http_server.port) == 200  # 起点：三条 listener 都活着

        async def _boom() -> None:
            raise RuntimeError("serve loop died (injected)")

        uvicorn_server: Any = doomed._server
        assert uvicorn_server is not None
        uvicorn_server.config.callback_notify = _boom
        uvicorn_server.last_notified = 0.0  # 下一 tick（≤100ms）就触发

        failure = await _await_failure(service, timeout=5.0)
        assert isinstance(failure, RuntimeError), failure
        assert "injected" in str(failure)

        # 兄弟 listener 仍活：真实 TCP + 真实 ASGI 应答（监听循环没被连带杀掉）
        assert (await _raw_status(survivor_port)) // 100 in {2, 4, 5}
        # HTTP 入口也仍活
        assert await _fetch_health(http_server.port) == 200
        # 首个异常不被后来的抖动覆盖
        assert service.failure is failure
    finally:
        await service.close()

    assert service.failure is not None  # 关闭不清空历史失败（所有者据此收尾）
    _assert_port_free(survivor_port)


@pytest.mark.embedded_http_service
def test_default_cli_exposes_the_run_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """默认 CLI 的内嵌服务带着**运行入口**：网页能真的提交提示词并读到事件流（Story 49-3 接线）。

    这是「默认 CLI → 内嵌服务 → ``HttpAgentHandler`` → 独立 loop」整条链路的端到端断言：
    服务是真 listener、handler 是真适配器、provider 是 stub（不联网）。
    """
    port = _free_port()
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider, port=port)
    observed: list[Any] = []

    async def fake_run_prompt(_loop: object, prompt: str, _system: object, _session_id: str) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            created = await client.post(f"http://127.0.0.1:{port}/api/runs", json={"prompt": prompt})
            observed.append(created.status_code)
            if created.status_code == 201:
                run_id = created.json()["run_id"]
                observed.append((await client.get(f"http://127.0.0.1:{port}/api/runs/{run_id}/events")).text)
                observed.append((await client.get(f"http://127.0.0.1:{port}/api/session")).json())

    monkeypatch.setattr("heagent.cli.interactive._run_prompt", fake_run_prompt)

    result = CliRunner().invoke(main, [], input="hi\n")

    assert result.exit_code == 0, result.output
    status, events, snapshot = observed
    assert status == 201
    assert '"kind":"done"' in events
    assert '"text":"stub answer"' in events
    assert snapshot["messages"] == [
        {"role": "user", "text": "hi"},
        {"role": "assistant", "text": "stub answer"},
    ]


# --- Epic 75 / 75.5：项目通道的装配注入 ------------------------------------------------
#
# 三条判据各自钉一层，缺一层就会留下「参数收到了、端点没收到」「端点收到了、不是同一个对象」
# 这类只在真客户端发 `projects` 时才暴露的洞：
#   1. 两条装配路径（内嵌服务 / `http-server` 命令）都注入了非 None 的适配器；
#   2. 每条路径只建**一份**控制台，适配器包的就是它（两份状态会让配置写入后 WS 按旧项目跑）；
#   3. 同一个适配器实例真的进了 listener 的两个端点构造点（不是停在 `build_ws_servers` 形参）。


def _record_ws_wiring(monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict[str, Any]], list[Any]]:
    """记录 `build_ws_servers` 收到的关键字与每次装配建出的控制台实例。"""
    from heagent.cli import http as http_module

    calls: list[dict[str, Any]] = []
    consoles: list[Any] = []
    real_build = http_module.build_ws_servers
    real_console = http_module._project_console

    def record_build(settings: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return real_build(settings, **kwargs)

    def record_console(**kwargs: Any) -> Any:
        console = real_console(**kwargs)
        consoles.append(console)
        return console

    monkeypatch.setattr(http_module, "build_ws_servers", record_build)
    monkeypatch.setattr(http_module, "_project_console", record_console)
    return calls, consoles


def _assert_single_adapter(calls: list[dict[str, Any]], consoles: list[Any]) -> Any:
    """一条装配路径的公共断言：恰一次装配、恰一份控制台、适配器包的正是它。"""
    from heagent.cli.ws_project_adapter import ProjectChannelAdapter

    assert len(calls) == 1, calls
    # R6 的判据取**启动期实际生效**的沙箱档位：入口层必须把 `sandbox_backend` 传下来
    # （不传时 `build_ws_servers` 会回落到配置值，``auto``/降级场景就会误判成「非 docker」）。
    assert "sandbox_backend" in calls[0], calls
    adapter = calls[0]["project_service"]
    assert isinstance(adapter, ProjectChannelAdapter), adapter
    assert len(consoles) == 1, consoles
    assert adapter._console is consoles[0]
    return adapter


def test_embedded_entry_injects_the_project_channel(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """内嵌服务路径（`build_http_service`）：注入非 None 适配器，且与控制台同一个实例。"""
    calls, consoles = _record_ws_wiring(monkeypatch)
    _drive(monkeypatch, tmp_path, _RecordingProvider())

    service = build_http_service(get_settings())

    adapter = _assert_single_adapter(calls, consoles)
    # HTTP 面拿到的也是同一份控制台（控制台注入 `_http_listener_for`，不另建第二份）。
    assert service._http is not None
    assert service._http.console is consoles[0]
    assert service._ws_servers[0].project_service is adapter


def test_http_server_command_injects_the_project_channel(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """`http-server` 路径：同样注入非 None 适配器（第二条装配分支不缺项目通道）。

    顺带钉住「生效沙箱档位只有一个来源」：WS 装配与 `_serve_web` 的公告拿到的必须是**同一个**值。
    """
    calls, consoles = _record_ws_wiring(monkeypatch)
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider)
    served_with: dict[str, object] = {}

    async def fake_serve_web(_http_server: object, _ws_servers: object, backend: object = None) -> None:
        served_with["backend"] = backend

    monkeypatch.setattr("heagent.cli.http._serve_web", fake_serve_web)
    monkeypatch.setattr("heagent.cli.http._build_provider", lambda settings, model: provider)

    result = CliRunner().invoke(main, ["http-server"])

    assert result.exit_code == 0, result.output
    _assert_single_adapter(calls, consoles)
    assert served_with["backend"] == calls[0]["sandbox_backend"]


def test_project_channel_reaches_both_endpoints_of_the_listener(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """注入真的到达端点构造点：集合级端点与单 run 端点拿到**同一个**适配器实例。

    只断言 `build_ws_servers` 的形参不足以证明注入生效——`WsServer` 之后还有 `build_ws_app` 一跳。
    这里在端点构造函数上记录 kwargs，再取 `WsServer.app`（延迟构造一次）触发整条装配链。
    """
    from heagent.network import ws_server as ws_server_module

    calls, consoles = _record_ws_wiring(monkeypatch)
    _drive(monkeypatch, tmp_path, _RecordingProvider())
    service = build_http_service(get_settings(), executor=object())
    adapter = _assert_single_adapter(calls, consoles)

    seen: dict[str, Any] = {}
    real_collection = ws_server_module.build_runs_collection_endpoint
    real_run = ws_server_module.build_ws_endpoint

    def record_collection(run_service: Any, **kwargs: Any) -> Any:
        seen["collection"] = kwargs
        return real_collection(run_service, **kwargs)

    def record_run(run_service: Any, **kwargs: Any) -> Any:
        seen["run"] = kwargs
        return real_run(run_service, **kwargs)

    monkeypatch.setattr(ws_server_module, "build_runs_collection_endpoint", record_collection)
    monkeypatch.setattr(ws_server_module, "build_ws_endpoint", record_run)

    assert service._ws_servers[0].app is not None  # 触发 routes 构造

    assert seen["collection"]["project_service"] is adapter
    assert seen["run"]["project_service"] is adapter


# ── E76-S04（R6）：external 档 + 非 docker 沙箱的启动 WARNING ─────────────────────────


def _external_ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """对外 listener 的最小可成立配置：非回环 + token（token 只认用户级 setting.md）。"""
    from heagent.config import Settings

    setting_file = tmp_path / "setting.md"
    setting_file.write_text("---\nWS_AUTH_TOKEN: test-token\n---\n", encoding="utf-8")
    monkeypatch.setattr(Settings, "_user_setting_file", setting_file, raising=False)
    monkeypatch.setenv("WS_ENABLED", "true")
    monkeypatch.setenv("WS_HOST", "192.168.2.226")
    monkeypatch.setenv("WS_LAN_NO_AUTH", "false")
    monkeypatch.setenv("WS_TLS_CERT_FILE", "")
    monkeypatch.setenv("WS_TLS_KEY_FILE", "")
    reset_settings()
    return get_settings()


def _sandbox_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if "external_without_sandbox" in record.getMessage()]


def test_external_listener_on_a_non_docker_backend_warns_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """R6：对外 listener + 非容器后端 ⇒ 恰 1 条固定锚点 WARNING（含 `listener=external` 与后端名）。"""
    from heagent.cli.http_config import build_ws_servers

    caplog.set_level(logging.WARNING, logger="heagent.cli.http_config")
    try:
        servers, _hub = build_ws_servers(_external_ws_settings(monkeypatch, tmp_path), sandbox_backend="passthrough")

        assert servers and servers[0].config.mode == "external"  # 告警不改变启动成败
        lines = _sandbox_warnings(caplog)
        assert len(lines) == 1, lines
        assert "listener=external" in lines[0]
        assert "sandbox=passthrough" in lines[0]
    finally:
        reset_settings()


def test_external_listener_on_docker_stays_quiet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """R6：docker 档 0 条——远程 run 已经落在容器里，没什么可喊的。"""
    from heagent.cli.http_config import build_ws_servers

    caplog.set_level(logging.WARNING, logger="heagent.cli.http_config")
    try:
        servers, _hub = build_ws_servers(_external_ws_settings(monkeypatch, tmp_path), sandbox_backend="docker")

        assert servers and servers[0].config.mode == "external"
        assert _sandbox_warnings(caplog) == []
    finally:
        reset_settings()


def test_access_note_appends_the_host_execution_clause_for_external_without_docker() -> None:
    """`_ws_access_note` 的既有三段文案逐字不变，只在对外 + 非 docker 时尾部追加一句。"""
    from heagent.cli.http import _ws_access_note
    from heagent.network.ws_host import WsServerConfig

    external = WsServerConfig(host="192.168.2.226", port=9201, auth_token="tok")
    plain = _ws_access_note(external)
    assert plain == "(external mode; Bearer token required; PLAINTEXT)"

    note = _ws_access_note(external, "passthrough")
    assert note.startswith(plain[:-1])  # 既有文案逐字不变，只在收尾括号前追加
    assert note.endswith("; sandbox=passthrough: remote runs execute on the HOST)")
    assert "HOST" not in _ws_access_note(external, "docker")
    # 本地 listener 不受这条影响（没有对端可提交）。
    local = WsServerConfig(host="127.0.0.1", port=9201)
    assert _ws_access_note(local, "passthrough") == "(run & CLI WebSocket entry; local only; no authentication)"


class _FakeWsListener:
    """`_serve_web` 的最小 listener：只提供它真正用到的四样东西（起停 + 地址 + 配置）。"""

    def __init__(self, config: Any, address: str) -> None:
        self.config = config
        self.address = address
        self.closed = False

    async def start(self) -> None:
        return None

    async def serve_forever(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def test_announce_ws_listeners_and_serve_web_share_the_host_clause(capsys: Any) -> None:
    """两条启动公告同口径：`[ws] WARNING` 与 `[ws] listening on` 都要说「远端 run 跑在宿主」。

    此前只有嵌入服务的 `[ws] event stream` 带这句，`http-server` 命令自己的两条公告都没带 ——
    同一进程里「有没有容器护栏」会随公告路径而变。
    """
    from heagent.cli.http import _announce_ws_listeners
    from heagent.network.ws_host import WsServerConfig

    external = WsServerConfig(host="192.168.2.226", port=9201, auth_token="tok")
    assert external.mode == "external"
    listener = _FakeWsListener(external, "192.168.2.226:9201")

    _announce_ws_listeners((listener,), "passthrough")
    warn = capsys.readouterr().err
    assert "Bearer token required" in warn
    assert "sandbox=passthrough: remote runs execute on the HOST" in warn

    _announce_ws_listeners((listener,), "docker")
    assert "remote runs execute on the HOST" not in capsys.readouterr().err


async def test_serve_web_listening_line_carries_the_host_clause(capsys: Any) -> None:
    """`_serve_web` 的 `[ws] listening on` 与访问口径用同一个生效档位（不是「没传就省略」）。"""
    from heagent.cli.http import _serve_web
    from heagent.network.ws_host import WsServerConfig

    external = WsServerConfig(host="192.168.2.226", port=9201, auth_token="tok")
    listener = _FakeWsListener(external, "192.168.2.226:9201")

    await _serve_web(None, (listener,), "passthrough")
    err = capsys.readouterr().err
    assert "[ws] listening on ws://192.168.2.226:9201" in err
    assert "sandbox=passthrough: remote runs execute on the HOST" in err
    assert listener.closed  # 服务循环返回后必须走 close
