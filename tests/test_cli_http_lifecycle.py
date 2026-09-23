"""Story 49-2：默认 CLI 的内嵌 HTTP 服务与生命周期。

覆盖两件事：

- **默认路径**（`heagent` / `heagent "prompt"` / `heagent run ...`）在**同一个 asyncio 生命周期**里
  启动 HTTP 服务：交互模式与 REPL 共存，单次模式与那次 run 并存并在结束后释放端口；绑定失败让
  命令显式失败（不进入聊天）。
- **显式非 HTTP 子命令**（`gui` / `tcp-server` / `http-server` / `replay` …）不会派生第二个实例。

测试手法：**替换 provider 而不是 `_run_single` / `_run_chat`**。HTTP 生命周期就在这两个入口内部，
把它们整体打桩等于把被测代码一并打桩（第一版就这么踩过：`_run_single` 被 fake 掉后服务根本没起，
断言只能看到 `ConnectError`）。替换 provider 既能驱动真实的 run 路径，又能在 run **进行中**探测
网页入口。

`tests/conftest.py` 默认把内嵌服务替换成替身（否则每个 CLI 测试都会抢 8766 端口）；需要真实绑定
的用例加 ``@pytest.mark.embedded_http_service`` 退出替身，并用随机空闲端口。
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx
from click.testing import CliRunner

from heagent.cli import main
from heagent.cli_http import build_http_service
from heagent.config import get_settings, reset_settings
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage


def _free_port() -> int:
    """向操作系统要一个当前空闲的端口（随后被 HTTP 服务绑定）。"""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _assert_port_free(port: int) -> None:
    """能立刻重新绑定 ⇒ 端口已释放（服务真的关了，而不是「忘了关但进程还活着」）。"""
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


async def _fetch_health(port: int) -> int:
    """**异步**请求健康检查：测试与服务共用同一个事件循环，同步 httpx 会把服务一起阻塞。"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        return (await client.get(f"http://127.0.0.1:{port}/api/health")).status_code


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
    monkeypatch.setattr("heagent.cli._build_provider", lambda settings, model: provider)
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

    monkeypatch.setattr("heagent.cli._run_prompt", fake_run_prompt)

    result = CliRunner().invoke(main, [], input="hi\n")

    assert result.exit_code == 0, result.output
    assert observed == [200]
    assert f"web UI: http://127.0.0.1:{port}" in result.output
    _assert_port_free(port)


@pytest.mark.embedded_http_service
def test_bind_failure_fails_the_command_without_entering_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """端口被占用：命令显式失败、**不进入 run**、不吐 traceback、不谎报「已监听」。"""
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

    assert result.exit_code == 1
    assert "HTTP server failed to start" in result.output
    assert "web UI" not in result.output
    assert "Traceback" not in result.output
    assert provider.calls == 0


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

    monkeypatch.setattr("heagent.cli._run_prompt", fake_run_prompt)

    result = CliRunner().invoke(main, [], input="hi\n")

    assert result.exit_code == 0, result.output
    assert prompted == ["hi"]
    assert len(embedded_http_services) == 1
    assert embedded_http_services[0].started is True
    assert embedded_http_services[0].closed is True


def test_interactive_mode_stops_when_the_embedded_service_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """网页入口挂掉后不得继续假装可用：交互模式如实报出并退出（AD-5）。"""
    monkeypatch.setattr("heagent.cli_http.build_http_service", _failing_service)
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider)

    result = CliRunner().invoke(main, [])

    assert result.exit_code == 0, result.output
    assert "service stopped unexpectedly" in result.output
    assert "serve loop died" in result.output


def test_explicit_subcommands_never_start_the_embedded_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, embedded_http_services: list[Any]
) -> None:
    """`gui` / `tcp-server` / `http-server` / `replay` 都不派生内嵌实例（Story 49-2 AC）。"""
    provider = _RecordingProvider()
    _drive(monkeypatch, tmp_path, provider)
    served: list[str] = []

    async def fake_serve_tcp(_server: object) -> None:
        served.append("tcp")

    async def fake_serve_http(_server: object) -> None:
        served.append("http")

    monkeypatch.setattr("heagent.cli_tcp._serve_tcp", fake_serve_tcp)
    monkeypatch.setattr("heagent.cli_http._serve_http", fake_serve_http)
    # cli_tcp / cli_http 各自模块级绑定了 `_build_provider`（与 cli 是三处名字），逐一打桩。
    monkeypatch.setattr("heagent.cli_tcp._build_provider", lambda settings, model: provider)
    monkeypatch.setattr("heagent.cli_http._build_provider", lambda settings, model: provider)
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text("", encoding="utf-8")

    runner = CliRunner()
    assert runner.invoke(main, ["tcp-server"]).exit_code == 0
    assert runner.invoke(main, ["http-server"]).exit_code == 0
    assert runner.invoke(main, ["replay", str(rollout)]).exit_code == 0
    assert runner.invoke(main, ["gui", "--help"]).exit_code == 0

    assert served == ["tcp", "http"]
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

    monkeypatch.setattr("heagent.cli._run_prompt", fake_run_prompt)

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
