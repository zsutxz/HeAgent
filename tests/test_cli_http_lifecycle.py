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
    from heagent.network import http_server as http_server_module
    from heagent.network.http_server import HttpDependencyError

    def _missing(name: str) -> Any:
        raise HttpDependencyError(f"missing {name!r}; install them with: pip install 'heagent[http]'")

    monkeypatch.setattr(http_server_module, "_require_module", _missing)
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

    async def fake_serve_web(http_server: object, ws_servers: object) -> None:
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
