"""默认 CLI 的网页入口开关：``--no-http`` / ``--no-ws``。

为什么单独一个文件：这两个开关有三层，任何一层漏接都不会被「设置层」的用例发现——
装配层（``build_http_service`` 的 ``http_enabled=`` / ``ws_enabled=`` 覆盖）、
CLI 解析层（``run`` 命令上的两个 flag 与 DefaultGroup 回退）、
透传层（``_run_cli_impl`` → ``_run_single``、``_embedded_http_service`` → ``build_http_service``）。

覆盖只作用于**本次进程**：不改配置文件、不改 ``Settings`` 单例（判据见每条用例的断言）。
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from heagent.cli.console import main
from heagent.cli.console import run as run_command
from heagent.config import Settings

pytestmark = pytest.mark.embedded_http_service


def _settings(**overrides: Any) -> Settings:
    """完全脱离 ``.env`` / 用户级文件的设置（其余字段取默认）。"""
    return Settings(_env_file=None, **overrides)


# ---------------------------------------------------------------------------
# 1. 装配层：覆盖参数真的改变 listener 装配
# ---------------------------------------------------------------------------


def test_override_disables_the_http_listener_only() -> None:
    from heagent.cli.http import build_http_service  # noqa: PLC0415

    service = build_http_service(_settings(http_enabled=True, ws_enabled=True), http_enabled=False)
    assert service._http is None
    assert len(service.ws_servers) == 1


def test_override_disables_the_ws_listeners_only() -> None:
    from heagent.cli.http import build_http_service  # noqa: PLC0415

    service = build_http_service(_settings(http_enabled=True, ws_enabled=True), ws_enabled=False)
    assert service._http is not None
    assert service.ws_servers == ()


def test_override_disables_both_listeners_yielding_a_dormant_service() -> None:
    from heagent.cli.http import build_http_service  # noqa: PLC0415

    settings = _settings(http_enabled=True, ws_enabled=True)
    service = build_http_service(settings, http_enabled=False, ws_enabled=False)
    assert service._http is None
    assert service.ws_servers == ()
    # 覆盖不写回 Settings：单例仍是配置文件的值。
    assert settings.http_enabled is True
    assert settings.ws_enabled is True


def test_override_none_falls_back_to_settings() -> None:
    from heagent.cli.http import build_http_service  # noqa: PLC0415

    service = build_http_service(_settings(http_enabled=False, ws_enabled=False))
    assert service._http is None
    assert service.ws_servers == ()


# ---------------------------------------------------------------------------
# 2. CLI 解析层：两个 flag 注册在 run 上，默认关闭态不生效
# ---------------------------------------------------------------------------


def test_run_command_exposes_both_flags_as_off_by_default() -> None:
    params = {param.name: param for param in run_command.params}
    for name in ("no_http", "no_ws"):
        assert name in params, f"run 命令缺少 {name} 参数"
        assert params[name].is_flag is True
        assert params[name].default is False


def test_cli_flags_reach_the_impl_with_the_right_values(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_impl(*_args: object, **kwargs: Any) -> None:
        captured.clear()
        captured.update(kwargs)

    monkeypatch.setattr("heagent.cli.console._run_cli_impl", fake_impl)
    runner = CliRunner()

    assert runner.invoke(main, ["run", "hi", "--no-http"]).exit_code == 0
    assert (captured["no_http"], captured["no_ws"]) == (True, False)

    assert runner.invoke(main, ["run", "hi", "--no-ws"]).exit_code == 0
    assert (captured["no_http"], captured["no_ws"]) == (False, True)

    assert runner.invoke(main, ["run", "hi", "--no-http", "--no-ws"]).exit_code == 0
    assert (captured["no_http"], captured["no_ws"]) == (True, True)

    # 不带 flag ⇒ 两个都保持 False（= 照配置装配，行为与加入开关前逐字一致）。
    assert runner.invoke(main, ["run", "hi"]).exit_code == 0
    assert (captured["no_http"], captured["no_ws"]) == (False, False)


def test_flags_live_on_the_run_subcommand_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """边界：group 级**不**接受这两个 flag（``heagent --no-http`` 报 No such option）。

    click 的 Group 先解析自己的选项，因此「``heagent --model X "prompt"``」这类写法本就不成立
    （既有行为，与本次改动无关）；可用的形态是 ``heagent run --no-http [prompt]``。
    这条用例把边界钉成可执行契约：将来若给 group 加同名选项，必须同步文档与默认路径的转发。
    """
    monkeypatch.setattr("heagent.cli.console._run_cli_impl", lambda *_a, **_k: None)
    runner = CliRunner()

    group_form = runner.invoke(main, ["--no-http", "hi"])
    assert group_form.exit_code == 2
    assert "No such option" in group_form.output

    # 不带 prompt 的 run 就是交互模式：开关同样生效。
    captured: dict[str, Any] = {}
    monkeypatch.setattr("heagent.cli.console._run_cli_impl", lambda *_a, **kwargs: captured.update(kwargs))
    assert runner.invoke(main, ["run", "--no-http"]).exit_code == 0
    assert (captured["no_http"], captured["no_ws"]) == (True, False)


# ---------------------------------------------------------------------------
# 3. 透传层：console → interactive → 装配
# ---------------------------------------------------------------------------


def test_cli_impl_forwards_the_flags_to_the_entrypoints(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, Any] = {}

    async def fake_single(*_args: object, **kwargs: Any) -> None:
        captured.update(kwargs)

    async def fake_chat(*_args: object, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("heagent.cli.console._setup_logging", lambda: None)
    monkeypatch.setattr("heagent.cli.console._print_banner", lambda: None)
    monkeypatch.setattr("heagent.cli.console._prune_runtime_artifacts", lambda _settings: None)
    monkeypatch.setattr("heagent.cli.console._build_provider", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr("heagent.cli.console.load_agent_roles", lambda: None)
    monkeypatch.setattr("heagent.cli.console.echo_sandbox_hint", lambda *_a, **_k: None)
    monkeypatch.setattr("heagent.cli.console.get_settings", lambda: _settings())
    monkeypatch.setattr("heagent.cli.console._mcp_lifecycle", lambda _settings: contextlib.nullcontext())
    monkeypatch.setattr("heagent.cli.interactive._run_single", fake_single)
    monkeypatch.setattr("heagent.cli.interactive._run_chat", fake_chat)

    from heagent.cli.console import _run_cli_impl  # noqa: PLC0415

    # 单次模式（给了 prompt）
    _run_cli_impl("hi", None, None, None, None, None, no_http=True, no_ws=True)
    assert (captured["no_http"], captured["no_ws"]) == (True, True)

    # 交互模式（prompt=None）走 _run_chat，开关同样透传
    captured.clear()
    _run_cli_impl(None, None, None, None, None, None, no_ws=True)
    assert (captured["no_http"], captured["no_ws"]) == (False, True)

    # 两者都不是 True 时不额外传覆盖（行为与加入开关前逐字一致）
    captured.clear()
    _run_cli_impl("hi", None, None, None, None, None)
    assert (captured["no_http"], captured["no_ws"]) == (False, False)


def test_embedded_service_forwards_overrides_to_the_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    from heagent.cli import http as cli_http  # noqa: PLC0415
    from heagent.cli.interactive import _embedded_http_service  # noqa: PLC0415

    captured: dict[str, Any] = {}

    class _StubService:
        async def __aenter__(self) -> _StubService:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    def fake_build(settings: Settings, **kwargs: Any) -> _StubService:
        captured.update(kwargs)
        return _StubService()

    monkeypatch.setattr(cli_http, "build_http_service", fake_build)
    monkeypatch.setattr("heagent.cli.http_console.HttpAgentHandler", lambda *_a, **_k: object())

    async def _run(**kwargs: Any) -> None:
        async with _embedded_http_service(_settings(), SimpleNamespace(), **kwargs):
            pass

    asyncio.run(_run(http_enabled=False))
    assert captured["http_enabled"] is False
    assert captured["ws_enabled"] is None

    captured.clear()
    asyncio.run(_run())
    assert captured["http_enabled"] is None
    assert captured["ws_enabled"] is None


def test_listener_overrides_maps_the_flags_to_three_state_values() -> None:
    """单一换算点：False/True 的四种组合 → 装配覆盖参数。"""
    from heagent.cli.interactive import _listener_overrides  # noqa: PLC0415

    assert _listener_overrides(False, False) == {"http_enabled": None, "ws_enabled": None}
    assert _listener_overrides(True, False) == {"http_enabled": False, "ws_enabled": None}
    assert _listener_overrides(False, True) == {"http_enabled": None, "ws_enabled": False}
    assert _listener_overrides(True, True) == {"http_enabled": False, "ws_enabled": False}


def test_full_cli_path_forwards_the_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """全链路：``heagent run --no-http`` → click 解析 → ``_run_cli_impl`` → ``_run_single``。"""
    monkeypatch.chdir(tmp_path)
    captured: dict[str, Any] = {}

    async def fake_single(*_args: object, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("heagent.cli.console._setup_logging", lambda: None)
    monkeypatch.setattr("heagent.cli.console._print_banner", lambda: None)
    monkeypatch.setattr("heagent.cli.console._prune_runtime_artifacts", lambda _settings: None)
    monkeypatch.setattr("heagent.cli.console._build_provider", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr("heagent.cli.console.load_agent_roles", lambda: None)
    monkeypatch.setattr("heagent.cli.console.echo_sandbox_hint", lambda *_a, **_k: None)
    monkeypatch.setattr("heagent.cli.console.get_settings", lambda: _settings())
    monkeypatch.setattr("heagent.cli.console._mcp_lifecycle", lambda _settings: contextlib.nullcontext())
    monkeypatch.setattr("heagent.cli.interactive._run_single", fake_single)

    result = CliRunner().invoke(main, ["run", "--no-http", "hi"])
    assert result.exit_code == 0, result.output
    assert captured["no_http"] is True
    assert captured["no_ws"] is False

    captured.clear()
    result = CliRunner().invoke(main, ["run", "--no-ws", "hi"])
    assert result.exit_code == 0, result.output
    assert captured["no_http"] is False
    assert captured["no_ws"] is True

    captured.clear()
    result = CliRunner().invoke(main, ["run", "--no-http", "--no-ws", "hi"])
    assert result.exit_code == 0, result.output
    assert captured["no_http"] is True
    assert captured["no_ws"] is True


def test_no_http_keeps_the_cli_bypass_on_the_ws_listener() -> None:
    """只关 HTTP 时，WS 侧（含 CLI 旁路中枢）照常装配——两条入口的开关互不牵连。

    这是 `--no-http` 最容易被写错的一环：把「关 HTTP」顺手实现成「关整个网页服务」。
    """
    from heagent.cli.http import build_http_service  # noqa: PLC0415

    settings = _settings(http_enabled=True, ws_enabled=True, ws_cli_bypass_enabled=True)
    service = build_http_service(settings, http_enabled=False)
    assert service._http is None
    assert len(service.ws_servers) == 1
    assert service.cli_hub is not None
    with pytest.raises(RuntimeError, match="--no-http"):
        _ = service.address


def test_disabling_a_listener_is_announced_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """不静默：显式关掉一条入口，stderr 必须有一行说明（双关时标明零监听）。"""
    from heagent.cli import http as cli_http  # noqa: PLC0415
    from heagent.cli.interactive import _embedded_http_service  # noqa: PLC0415

    class _StubService:
        async def __aenter__(self) -> _StubService:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(cli_http, "build_http_service", lambda *_a, **_k: _StubService())
    monkeypatch.setattr("heagent.cli.http_console.HttpAgentHandler", lambda *_a, **_k: object())

    async def _run(**kwargs: Any) -> None:
        async with _embedded_http_service(_settings(), SimpleNamespace(), **kwargs):
            pass

    asyncio.run(_run(http_enabled=False, ws_enabled=False))
    err = capsys.readouterr().err
    assert "[web] HTTP + WS entry disabled by CLI flag" in err
    assert "零监听" in err

    asyncio.run(_run(ws_enabled=False))
    err = capsys.readouterr().err
    assert "[web] WS entry disabled by CLI flag" in err
    assert "HTTP" not in err.split("[web]")[1].splitlines()[0]

    # 没有覆盖时不打这行（默认路径输出与加入开关前逐字一致）
    asyncio.run(_run())
    assert "[web]" not in capsys.readouterr().err


def test_service_is_dormant_only_when_both_listeners_are_absent() -> None:
    """``is_dormant`` 只在**两条都**没有时为真（单关一侧仍算「有入口」）。"""
    from heagent.cli.http import EmbeddedHttpService, build_http_service  # noqa: PLC0415

    assert EmbeddedHttpService(None, ()).is_dormant is True
    assert build_http_service(_settings(http_enabled=True, ws_enabled=True)).is_dormant is False
    assert build_http_service(_settings(http_enabled=True, ws_enabled=True), http_enabled=False).is_dormant is False
    assert build_http_service(_settings(http_enabled=True, ws_enabled=True), ws_enabled=False).is_dormant is False
    assert (
        build_http_service(
            _settings(http_enabled=True, ws_enabled=True), http_enabled=False, ws_enabled=False
        ).is_dormant
        is True
    )


def test_echo_web_entry_overrides_speaks_only_when_a_flag_closes_something(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """共用公告函数：三种组合各一行；无覆盖时一个字都不打。"""
    from heagent.cli.display import echo_web_entry_overrides  # noqa: PLC0415

    echo_web_entry_overrides(http_disabled=False, ws_disabled=False)
    assert capsys.readouterr().err == ""

    echo_web_entry_overrides(http_disabled=True, ws_disabled=False)
    err = capsys.readouterr().err
    assert "[web] HTTP entry disabled by CLI flag" in err
    assert "零监听" not in err

    echo_web_entry_overrides(http_disabled=False, ws_disabled=True)
    err = capsys.readouterr().err
    assert "[web] WS entry disabled by CLI flag" in err
    assert "零监听" not in err

    echo_web_entry_overrides(http_disabled=True, ws_disabled=True)
    err = capsys.readouterr().err
    assert "[web] HTTP + WS entry disabled by CLI flag" in err
    assert "本进程零监听" in err
