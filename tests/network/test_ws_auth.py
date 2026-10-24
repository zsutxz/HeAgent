"""Epic 56 Story 56-2：对外模式认证与 TLS 的判据（纯逻辑面 + 配置契约 + 端点前门）。

三层分工：

- **纯逻辑**（``network/ws_auth.py``）：bearer 解析 / 常量时间比较 / 失败限速滑窗；
- **配置契约**（``WsServerConfig`` / ``Settings.user_ws_auth_token`` / ``build_ws_server_config``）：
  非回环缺 token 与 TLS 半配都 fail-closed，token 只认用户级 ``setting.md``；
- **端点前门**（替身 WebSocket）：认证失败发生在 ``accept()`` **之前**且 close code = 1008。

真实 listener 的判据（客户端拿 HTTP 403 / wss 握手）在 ``test_ws_e2e.py``；
``tests/fixtures/ws_tls/`` 下的自签证书与私钥是**测试专用**（非凭证、不含任何真实系统身份）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from heagent.config import Settings
from heagent.network.ws_auth import (
    AUTH_CLOSE_CODE,
    AuthThrottle,
    client_source,
    make_authorizer,
    parse_bearer,
    token_matches,
)
from heagent.network.ws_host import WsConfigError, WsServerConfig, build_ws_app
from heagent.network.ws_server import build_ws_endpoint

TLS_FIXTURES = Path("tests/fixtures/ws_tls")


# ---- 纯逻辑：Bearer 解析 ----


def _h(value: str, name: str = "authorization") -> tuple[bytes, bytes]:
    return (name.encode(), value.encode())


def test_parse_bearer_accepts_canonical_form() -> None:
    assert parse_bearer([_h("Bearer s3cret")]) == "s3cret"
    assert parse_bearer([_h("bearer   s3cret  ")]) == "s3cret"
    assert parse_bearer([_h("BEARER s3cret")]) == "s3cret"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [_h("Basic s3cret")],
        [_h("Bearer")],
        [_h("Bearer    ")],
        [_h("s3cret")],
        [_h("Bearer s3cret"), _h("Bearer other")],  # 重复头：不可信输入
        [_h("Bearer s3cret", name="x-authorization")],
    ],
)
def test_parse_bearer_rejects_malformed(headers: list[tuple[bytes, bytes]]) -> None:
    assert parse_bearer(headers) is None


def test_token_matches_is_strict_and_never_empty() -> None:
    assert token_matches("abc", "abc")
    assert not token_matches("abc", "abd")
    assert not token_matches("abc", "abcd")
    assert not token_matches("", "")
    assert not token_matches("abc", None)
    assert not token_matches("abc", "")


# ---- 纯逻辑：失败限速 ----


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_throttle_blocks_after_threshold_and_recovers_after_window() -> None:
    clock = _Clock()
    throttle = AuthThrottle(max_failures=3, window_seconds=10, clock=clock)
    for _ in range(2):
        throttle.record_failure("10.0.0.9")
    assert not throttle.blocked("10.0.0.9")
    throttle.record_failure("10.0.0.9")
    assert throttle.blocked("10.0.0.9")
    # 窗口滑过后自动解封（不需要显式清理）。
    clock.now += 11
    assert not throttle.blocked("10.0.0.9")
    assert throttle.failures("10.0.0.9") == 0
    assert len(throttle) == 0


def test_throttle_success_resets_only_that_source() -> None:
    throttle = AuthThrottle(max_failures=2)
    throttle.record_failure("a")
    throttle.record_failure("b")
    throttle.record_success("a")
    assert throttle.failures("a") == 0
    assert throttle.failures("b") == 1


def test_throttle_entries_are_bounded() -> None:
    throttle = AuthThrottle(max_failures=5, max_sources=3)
    for source in ("a", "b", "c", "d"):
        throttle.record_failure(source)
    assert len(throttle) == 3
    # 淘汰的是最久未更新的来源（a），最新记录仍在。
    assert throttle.failures("a") == 0
    assert throttle.failures("d") == 1


@pytest.mark.parametrize("kwargs", [{"max_failures": 0}, {"window_seconds": 0}, {"max_sources": 0}])
def test_throttle_rejects_degenerate_limits(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        AuthThrottle(**kwargs)


def test_authorizer_distinguishes_reasons_without_leaking() -> None:
    throttle = AuthThrottle(max_failures=2)
    authorize = make_authorizer("s3cret", throttle)
    ok_scope = {"headers": [_h("Bearer s3cret")], "client": ("10.0.0.1", 1)}
    bad_scope = {"headers": [_h("Bearer nope")], "client": ("10.0.0.2", 1)}
    missing_scope = {"headers": [], "client": ("10.0.0.3", 1)}

    assert authorize(ok_scope) is None
    assert authorize(bad_scope) == "invalid"
    assert authorize(missing_scope) == "missing"
    assert authorize(bad_scope) == "invalid"  # 第 2 次：达到阈值（本次仍走比较路径）
    # 达到阈值后转 throttled，且不再触碰比较路径（reasons 对客户端不可区分，都回 1008）。
    assert authorize(bad_scope) == "throttled"
    assert authorize(ok_scope) is None  # 其它来源不受牵连


def test_authorizer_requires_token() -> None:
    with pytest.raises(ValueError):
        make_authorizer("", AuthThrottle())


def test_client_source_falls_back_to_unknown() -> None:
    assert client_source({"client": ("1.2.3.4", 5)}) == "1.2.3.4"
    assert client_source({}) == "unknown"
    assert client_source({"client": ()}) == "unknown"


# ---- 配置契约：监听模式与 fail-closed ----


def test_loopback_bind_is_local_mode_without_auth() -> None:
    config = WsServerConfig()
    assert config.mode == "local"
    assert config.requires_auth is False
    # 本地模式即使配了 token 也不启用认证（D5：单监听器按绑定地址切模式）。
    assert WsServerConfig(auth_token="s3cret").requires_auth is False


def test_non_loopback_bind_requires_a_token() -> None:
    with pytest.raises(ValidationError) as caught:
        WsServerConfig(host="0.0.0.0")
    assert "WS_AUTH_TOKEN" in str(caught.value)


@pytest.mark.parametrize("token", ["", "   ", "\t\n"])
def test_blank_token_does_not_count_as_configured(token: str) -> None:
    with pytest.raises(ValidationError):
        WsServerConfig(host="192.168.1.10", auth_token=token)


def test_external_mode_hides_the_token_from_repr_and_dump() -> None:
    config = WsServerConfig(host="0.0.0.0", auth_token="s3cret")
    assert config.mode == "external"
    assert config.requires_auth is True
    assert config.auth_secret == "s3cret"
    assert "s3cret" not in repr(config)
    assert "s3cret" not in json.dumps(config.model_dump(mode="json"), default=str)


def test_tls_needs_both_halves() -> None:
    assert WsServerConfig().tls_enabled is False
    with pytest.raises(ValidationError):
        WsServerConfig(tls_cert_file=str(TLS_FIXTURES / "cert.pem"))
    with pytest.raises(ValidationError):
        WsServerConfig(tls_key_file=str(TLS_FIXTURES / "key.pem"))
    config = WsServerConfig(
        tls_cert_file=str(TLS_FIXTURES / "cert.pem"),
        tls_key_file=str(TLS_FIXTURES / "key.pem"),
    )
    assert config.tls_enabled is True


# ---- 配置契约：token 真源只有用户级 setting.md ----


def _write_setting_md(path: Path, body: str) -> Path:
    path.write_text(f"---\n{body}\n---\n", encoding="utf-8")
    return path


def test_user_token_comes_from_user_setting_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setting = _write_setting_md(tmp_path / "setting.md", "WS_AUTH_TOKEN: from-user-md")
    monkeypatch.setattr(Settings, "_user_setting_file", setting)
    assert Settings().user_ws_auth_token == "from-user-md"


def test_user_token_ignores_environment_and_project_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """凭证只认用户级文件：系统环境变量（更高优先级层）也不能供给它。"""
    setting = _write_setting_md(tmp_path / "setting.md", "WS_AUTH_TOKEN: from-user-md")
    monkeypatch.setattr(Settings, "_user_setting_file", setting)
    monkeypatch.setenv("WS_AUTH_TOKEN", "from-env")
    assert Settings().user_ws_auth_token == "from-user-md"


def test_user_token_absent_or_blank_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Settings, "_user_setting_file", tmp_path / "missing.md")
    assert Settings().user_ws_auth_token is None
    blank = _write_setting_md(tmp_path / "blank.md", "WS_AUTH_TOKEN:   ")
    monkeypatch.setattr(Settings, "_user_setting_file", blank)
    assert Settings().user_ws_auth_token is None


def test_user_token_is_not_a_settings_field() -> None:
    """做成字段就会进入「env > 项目 .env > 用户 md」优先级链——那正是 D3 禁止的。"""
    assert "ws_auth_token" not in Settings.model_fields
    assert "ws_auth_token" not in Settings().model_dump()


# ---- 组合根：build_ws_server_config 的三件接线 ----


def test_build_ws_server_config_fails_closed_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from heagent.cli.http import build_ws_server_config

    monkeypatch.setattr(Settings, "_user_setting_file", tmp_path / "missing.md")
    with pytest.raises(WsConfigError) as caught:
        build_ws_server_config(Settings(), host="0.0.0.0")
    assert "WS_AUTH_TOKEN" in str(caught.value)


def test_build_ws_server_config_wires_token_and_tls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from heagent.cli.http import build_ws_server_config

    setting = _write_setting_md(tmp_path / "setting.md", "WS_AUTH_TOKEN: s3cret")
    monkeypatch.setattr(Settings, "_user_setting_file", setting)
    settings = Settings(
        ws_tls_cert_file=str(TLS_FIXTURES / "cert.pem"),
        ws_tls_key_file=str(TLS_FIXTURES / "key.pem"),
    )
    config = build_ws_server_config(settings, host="0.0.0.0")
    assert config.requires_auth is True
    assert config.auth_secret == "s3cret"
    assert config.tls_enabled is True


def test_announcements_reflect_mode_and_tls() -> None:
    """入口层公告不得在对外模式说「no authentication」，也不得把 wss 写成 ws。"""
    from heagent.cli.http import _ws_access_note, _ws_url

    class _FakeServer:
        def __init__(self, config: WsServerConfig) -> None:
            self.config = config
            self.address = f"{config.host}:{config.port}"

    local = _FakeServer(WsServerConfig())
    external = _FakeServer(WsServerConfig(host="0.0.0.0", auth_token="s3cret"))
    external_tls = _FakeServer(
        WsServerConfig(
            host="0.0.0.0",
            auth_token="s3cret",
            tls_cert_file=str(TLS_FIXTURES / "cert.pem"),
            tls_key_file=str(TLS_FIXTURES / "key.pem"),
        )
    )
    assert _ws_url(local) == f"ws://{local.address}"
    assert "no authentication" in _ws_access_note(local.config)
    assert "Bearer token required" in _ws_access_note(external.config)
    assert "PLAINTEXT" in _ws_access_note(external.config)
    assert _ws_url(external_tls) == f"wss://{external_tls.address}"
    assert "TLS" in _ws_access_note(external_tls.config)


# ---- 端点前门：认证在 accept 之前 ----


class _FakeWebSocket:
    """替身 WebSocket：只记录 accept / close / 发出的帧。"""

    def __init__(
        self,
        *,
        headers: list[tuple[bytes, bytes]] | None = None,
        client: tuple[str, int] | None = ("10.0.0.1", 4242),
        query: dict[str, str] | None = None,
        path_params: dict[str, str] | None = None,
    ) -> None:
        self.scope = {"headers": list(headers or []), "client": client}
        self.query_params = dict(query or {})
        self.path_params = dict(path_params or {})
        self.accepted = False
        self.close_code: int | None = None
        self.sent: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    async def receive_text(self) -> str:
        raise RuntimeError("no inbound frames in this test")

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


class _NoRunService:
    """最小服务替身：认证通过后端点会走到 ``run()`` 并回 unknown_run。"""

    _closing = False

    def run(self, run_id: str) -> Any | None:
        return None


async def _invoke(endpoint: Any, websocket: _FakeWebSocket) -> None:
    await endpoint(websocket)


@pytest.mark.asyncio
async def test_endpoint_closes_1008_before_accept_when_token_missing() -> None:
    endpoint = build_ws_endpoint(
        _NoRunService(),
        origin_violation=lambda scope: None,
        max_connections=4,
        authorize=make_authorizer("s3cret", AuthThrottle(max_failures=5)),
    )
    websocket = _FakeWebSocket()
    await _invoke(endpoint, websocket)
    assert websocket.accepted is False
    assert websocket.close_code == AUTH_CLOSE_CODE == 1008
    assert websocket.sent == []  # 不泄露错误信封


@pytest.mark.asyncio
async def test_endpoint_accepts_with_the_correct_token() -> None:
    endpoint = build_ws_endpoint(
        _NoRunService(),
        origin_violation=lambda scope: None,
        max_connections=4,
        authorize=make_authorizer("s3cret", AuthThrottle()),
    )
    websocket = _FakeWebSocket(headers=[_h("Bearer s3cret")])
    await _invoke(endpoint, websocket)
    # 通过认证后走到 run 查询（无记录 ⇒ unknown_run 错误帧），但**已经 accept**。
    assert websocket.accepted is True
    assert websocket.sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_endpoint_without_authorize_keeps_legacy_behaviour() -> None:
    """本地模式（``authorize=None``）不改变 Epic 54/55 语义：无认证头照常 accept。"""
    endpoint = build_ws_endpoint(
        _NoRunService(),
        origin_violation=lambda scope: None,
        max_connections=4,
    )
    websocket = _FakeWebSocket()
    await _invoke(endpoint, websocket)
    assert websocket.accepted is True


def _first_route(app: Any) -> Any:
    from starlette.routing import WebSocketRoute

    return next(item for item in app.routes if isinstance(item, WebSocketRoute))


@pytest.mark.asyncio
async def test_external_mode_ignores_host_and_origin_headers() -> None:
    """对外模式 Host/Origin 不适用：任意主机名 + 正确 token 仍能通过前门（防线由 token 取代）。"""
    from heagent.network.ws_host import WsServer

    server = WsServer(WsServerConfig(host="0.0.0.0", auth_token="s3cret"), run_service=_NoRunService())
    route = _first_route(server.app)
    websocket = _FakeWebSocket(
        headers=[_h("Bearer s3cret"), (b"host", b"evil.example:9001"), (b"origin", b"http://evil.example:9001")],
        path_params={"run_id": "x"},
        client=("203.0.113.5", 1),
    )
    await route.endpoint(websocket)
    assert websocket.accepted is True


@pytest.mark.asyncio
async def test_local_mode_still_rejects_foreign_host_before_accept() -> None:
    """本地模式的 Origin/Host 防线逐字保留（D5：回环绑定不改语义）。"""
    from heagent.network.ws_host import WsServer

    server = WsServer(WsServerConfig(), run_service=_NoRunService())
    route = _first_route(server.app)
    websocket = _FakeWebSocket(
        headers=[(b"host", b"evil.example:9001")],
        path_params={"run_id": "x"},
        client=("127.0.0.1", 1),
    )
    await route.endpoint(websocket)
    assert websocket.accepted is False


@pytest.mark.asyncio
async def test_external_mode_still_registers_all_three_routes() -> None:
    """对外模式不减少路由：认证只是前门，端点矩阵与本地模式一致（矩阵细节见 test_ws_server.py）。"""
    from starlette.routing import WebSocketRoute

    from heagent.network.ws_host import WsServer

    server = WsServer(
        WsServerConfig(host="0.0.0.0", auth_token="s3cret"),
        run_service=_NoRunService(),
    )
    paths = [item.path for item in server.app.routes if isinstance(item, WebSocketRoute)]
    assert paths == ["/api/runs/ws", "/api/runs/{run_id}/ws"]


@pytest.mark.asyncio
async def test_cli_bypass_endpoint_also_requires_the_token() -> None:
    """D7：旁路随迁进 WS server，对外模式下同样过认证门（终端事件不该被无凭证者读走）。"""
    from heagent.network.cli_event_hub import CliEventHub
    from heagent.network.ws_server import build_cli_ws_endpoint

    endpoint = build_cli_ws_endpoint(
        CliEventHub(),
        origin_violation=lambda scope: None,
        authorize=make_authorizer("s3cret", AuthThrottle()),
    )
    websocket = _FakeWebSocket()
    await endpoint(websocket)
    assert websocket.accepted is False
    assert websocket.close_code == AUTH_CLOSE_CODE


# ---- 文档与诊断口径（三处同步：.env.example / setting.md / 配置面板不误报）----


def test_env_example_documents_tls_and_warns_about_the_token_placement() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "WS_TLS_CERT_FILE=" in example
    assert "WS_TLS_KEY_FILE=" in example
    # token 不能以「可直接填」的形式出现在项目 .env 模板里：只留说明行，不留赋值示例。
    for line in example.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("WS_AUTH_TOKEN="), stripped
    assert "WS_AUTH_TOKEN" in example
    assert "setting.md" in example


def test_user_level_token_is_not_reported_as_an_unknown_key(tmp_path: Path) -> None:
    """它是合法的用户级键（不是拼写错），配置面板不得把它列进 `unknown_keys`。"""
    from heagent.config.catalog import build_config_report

    project = tmp_path / "project" / ".env"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_bytes(b"MAX_ITERATIONS=7\n")
    setting = tmp_path / "setting.md"
    setting.write_bytes(b"---\nWS_AUTH_TOKEN: s3cret\n---\n")
    report = build_config_report(project, global_setting_file=setting)
    assert [entry.key for entry in report.unknown_keys] == []
    # 但它也**不是**配置项（不出现在 items 里，更不可写）。
    assert "WS_AUTH_TOKEN" not in {item.key for item in report.items}


def test_user_level_token_in_the_project_env_is_still_reported_as_unknown(tmp_path: Path) -> None:
    """写错位置要能被诊断面板看见：用户级专属键在项目 `.env` 里照常算未知键。"""
    from heagent.config.catalog import ConfigSource, build_config_report

    project = tmp_path / "project" / ".env"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_bytes(b"WS_AUTH_TOKEN=s3cret\nMAX_ITERATIONS=7\n")
    setting = tmp_path / "setting.md"
    setting.write_bytes(b"---\nWS_AUTH_TOKEN: from-user-md\n---\n")
    report = build_config_report(project, global_setting_file=setting)
    assert [(entry.key, entry.source) for entry in report.unknown_keys] == [("WS_AUTH_TOKEN", ConfigSource.PROJECT_ENV)]
