"""Epic 72 Story 72.1：内网免认证监听模式（``lan``）。

三组判据：

- **准入面**：``is_private_address`` 的白名单（私有 / link-local 才真，通配 / 公网 / 主机名 / 回环 /
  CGNAT 全假）；``config/`` 内联实现与 ``network/`` 实现等价（跨层一致性）。
- **配置面**：``WsServerConfig.mode`` 三值、``requires_auth`` 只在 ``external``（或回环 + 本地强制认证）
  为真、四条非法组合 fail-loud；``cli`` 装配层把同样的失败转成 ``WsConfigError``。
- **行为面**：``lan`` listener 无 token 真连得上（真实 TCP），Host/Origin 防线**仍然生效**（同一 listener
  上伪装 Host 被拒）；启动日志恰一条 ``listener=lan auth=none``；旁路仍只在回环挂载。
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

import pytest
from pydantic import ValidationError

from heagent.config import Settings
from heagent.config.validation import REQUIRED_CHECKS, _is_private_address, validate_startup
from heagent.network.exposure import is_private_address
from heagent.network.http_server import HttpRunService, HttpServerConfig
from heagent.network.ws_host import (
    RUNS_SUBMIT_PATH,
    RUNS_WS_PATH,
    WsConfigError,
    WsServer,
    WsServerConfig,
    build_ws_app,
)

websockets = pytest.importorskip("websockets")

#: 一个私有地址字面量（不会真的绑定，只用于配置层断言）。
PRIVATE_HOST = "192.168.2.226"
#: 任何主机上都不会被绑定的公网地址。
PUBLIC_HOST = "61.141.165.202"


def _local_private_ipv4() -> str | None:
    """本机一个**私有** IPv4（真实 TCP 用例的绑定地址）；取不到返回 ``None``（用例 skip）。

    用 UDP ``connect`` 读内核选中的出口地址：不发包、不依赖 DNS，容器与 CI runner 上通常都有
    ``172.x`` / ``10.x`` 私网地址。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1：connect 只决定路由，不发包
        candidate = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return candidate if is_private_address(candidate) else None


# ---------------------------------------------------------------- 准入面


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("192.168.2.226", True),
        ("10.1.2.3", True),
        ("172.16.5.5", True),
        ("169.254.10.10", True),  # link-local
        ("fd00::1", True),  # 唯一本地 IPv6
        ("0.0.0.0", False),  # 通配 = 所有接口
        ("::", False),
        ("127.0.0.1", False),  # 回环归本地模式
        ("[::1]", False),
        (PUBLIC_HOST, False),  # 公网
        ("100.64.0.1", False),  # CGNAT：既非 private 也非 global
        ("example.lan", False),  # 主机名不解析 DNS
        ("", False),
    ],
)
def test_is_private_address_whitelist(host: str, expected: bool) -> None:
    """准入白名单：只有私有 / link-local 的 IP 字面量算「内网地址」。"""
    assert is_private_address(host) is expected, host


def test_config_layer_mirror_matches_network_layer() -> None:
    """跨层等价：``config/validation.py`` 的内联实现与 ``network/exposure.py`` 判定逐值一致。

    两处实现是刻意的（``config/`` 不得依赖 ``network/``），等价性必须由判据钉住，否则两份白名单
    会各自漂移，出现「启动校验放行、装配时拒」或反过来的分裂。
    """
    hosts = [
        "192.168.2.226",
        "10.0.0.1",
        "172.31.255.254",
        "169.254.1.1",
        "fd00::1",
        "0.0.0.0",
        "::",
        "127.0.0.1",
        PUBLIC_HOST,
        "100.64.0.1",
        "example.lan",
        "",
    ]
    for host in hosts:
        assert _is_private_address(host) is is_private_address(host), host


# ---------------------------------------------------------------- 配置面


def test_loopback_bind_stays_local_and_unauthenticated() -> None:
    """默认形态零改动：回环 = ``local``、免 token。"""
    config = WsServerConfig()
    assert config.mode == "local"
    assert config.requires_auth is False


def test_private_bind_with_the_flag_is_lan_mode() -> None:
    config = WsServerConfig(host=PRIVATE_HOST, lan_no_auth=True)
    assert config.mode == "lan"
    assert config.requires_auth is False


def test_private_bind_without_the_flag_still_fails_closed() -> None:
    """不开开关时非回环绑定仍是 fail-closed（不因新增模式而放宽默认）。"""
    with pytest.raises(ValidationError) as exc:
        WsServerConfig(host=PRIVATE_HOST)
    assert "WS_AUTH_TOKEN" in str(exc.value)
    assert "WS_LAN_NO_AUTH" in str(exc.value)


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"host": PRIVATE_HOST, "lan_no_auth": True, "local_auth": True}, "mutually exclusive"),
        ({"host": "0.0.0.0", "lan_no_auth": True}, "private address literal"),
        ({"host": "::", "lan_no_auth": True}, "private address literal"),
        ({"host": PUBLIC_HOST, "lan_no_auth": True}, "private address literal"),
        ({"host": "example.lan", "lan_no_auth": True}, "private address literal"),
        ({"host": "127.0.0.1", "lan_no_auth": True}, "no effect on a loopback bind"),
    ],
)
def test_lan_mode_rejects_invalid_combinations(kwargs: dict[str, Any], needle: str) -> None:
    """四条非法组合（含互斥与「回环上开了没意义」）逐条拒绝，消息点名规则。"""
    with pytest.raises(ValidationError) as exc:
        WsServerConfig(**kwargs)
    assert needle in str(exc.value), str(exc.value)


def test_assembly_layer_turns_the_refusal_into_a_wscfg_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cli`` 装配层把同一拒绝转成 ``WsConfigError``（命令级错误，不是 traceback）。"""
    from heagent.cli.http_config import build_ws_server_config

    monkeypatch.setenv("WS_HOST", PRIVATE_HOST)
    monkeypatch.setenv("WS_LAN_NO_AUTH", "false")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(WsConfigError) as exc:
        build_ws_server_config(settings)
    assert "WS_LAN_NO_AUTH" in str(exc.value)
    assert "loopback" in str(exc.value)


def test_assembly_layer_wires_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from heagent.cli.http_config import build_ws_server_config

    monkeypatch.setenv("WS_HOST", PRIVATE_HOST)
    monkeypatch.setenv("WS_LAN_NO_AUTH", "true")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    config = build_ws_server_config(settings)
    assert (config.mode, config.requires_auth) == ("lan", False)


def test_startup_preflight_accepts_a_valid_lan_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """启动期预检与装配层同口径：合法 ``lan`` 配置不产阻断项，非法组合产一条并点名键。"""
    monkeypatch.setenv("WS_HOST", PRIVATE_HOST)
    monkeypatch.setenv("WS_LAN_NO_AUTH", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")  # 只为本用例回避「无凭据」阻断
    ok = Settings(_env_file=None)  # type: ignore[call-arg]
    issue_names = [issue.check for issue in _validate(ok).issues]
    assert "ws_lan_no_auth" not in issue_names

    monkeypatch.setenv("WS_HOST", "0.0.0.0")
    bad = Settings(_env_file=None)  # type: ignore[call-arg]
    issues = {issue.check: issue.message for issue in _validate(bad).issues}
    assert "WS_LAN_NO_AUTH=true requires a private address literal" in issues["ws_lan_no_auth"]


def _validate(settings: Settings) -> Any:
    return validate_startup(settings)


def test_preflight_registers_the_lan_check() -> None:
    """新检查已登记（覆盖率分母/分子与 ``REQUIRED_SETTING_KEYS`` 同步）。"""
    assert "ws_lan_no_auth" in {check.name for check in REQUIRED_CHECKS}


# ---------------------------------------------------------------- 行为面


def _http_config(**kwargs: Any) -> HttpServerConfig:
    return HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0, **kwargs)


class _NullExecutor:
    """不需要真的执行 run：本文件只验握手与拒绝，不跑 agent。"""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover - 不会被调用
        raise AssertionError("no run should start in these cases")


@pytest.mark.asyncio
async def test_lan_listener_accepts_a_tokenless_handshake_over_real_tcp(caplog: pytest.LogCaptureFixture) -> None:
    """``lan`` 真连：无 ``Authorization`` 头拿到 101，Host 等于绑定地址时通过同源校验。"""
    host = _local_private_ipv4()
    if host is None:
        pytest.skip("本机没有可绑定的私有 IPv4，真实 TCP 判据无法执行")
    caplog.set_level(logging.INFO, logger="heagent.network.ws_host")
    service = HttpRunService(_http_config(), _NullExecutor())  # type: ignore[arg-type]
    server = WsServer(WsServerConfig(host=host, port=0, shutdown_timeout=1, lan_no_auth=True), run_service=service)
    await asyncio.wait_for(server.start(), timeout=15)
    task = asyncio.create_task(server.serve_forever())
    try:
        async with websockets.connect(f"ws://{host}:{server.port}{RUNS_SUBMIT_PATH}") as ws:
            # 无认证门 ⇒ 命令通道可用：ping 直接拿 ack（不是 403 / close 1008）。
            await ws.send(json.dumps({"command": "ping"}))
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert ack == {"type": "ack", "command": "ping", "run_id": ""}, ack
    finally:
        await server.close()
        await asyncio.wait_for(task, timeout=5)

    exposed = [record.getMessage() for record in caplog.records if "listener=lan auth=none" in record.getMessage()]
    assert len(exposed) == 1, exposed
    assert "auth=token" not in " ".join(record.getMessage() for record in caplog.records)


def test_lan_mode_keeps_the_host_check(caplog: pytest.LogCaptureFixture) -> None:
    """``lan`` 不复制对外模式的「防线替换」：伪装 Host 仍被拒，原生 Host 放行。"""
    from starlette.testclient import TestClient

    config = WsServerConfig(host=PRIVATE_HOST, lan_no_auth=True)
    app = build_ws_app(config, run_service=HttpRunService(_http_config(), _NullExecutor()))  # type: ignore[arg-type]
    client = TestClient(app)
    path = RUNS_WS_PATH.replace("{run_id}", "nope")

    # 伪装 Host：origin 门在 accept 之前拒绝（TestClient 把「未 accept 即关」收敛为异常）。
    caplog.set_level(logging.WARNING, logger="heagent.network.ws_server")
    with (
        pytest.raises(Exception),  # noqa: B017 - 类型由 starlette 决定，只断言「被拒」
        client.websocket_connect(path, headers={"host": "evil.example:9201"}) as ws,
    ):
        ws.receive_json()
    rejected = [record.getMessage() for record in caplog.records if "origin_rejected" in record.getMessage()]
    assert rejected and "host not allowed" in rejected[0], rejected

    # 绑定地址形态的 Host：放行（无 Origin 头 = 非浏览器客户端，既有规则照放行）；
    # 未知 run 的订阅被端点按 unknown_run 拒——证明请求已过同源门、落到端点逻辑。
    with client.websocket_connect(path, headers={"host": f"{PRIVATE_HOST}:9201"}) as ws:
        frame = ws.receive_json()
    assert frame["type"] == "error"
    assert frame["error"]["error"]["code"] == "unknown_run"


def test_cli_bypass_is_not_mounted_on_a_lan_listener() -> None:
    """旁路仍只挂回环（D9 不变量）：``lan`` 下 ``/api/cli/ws`` 不注册，返回跳过告警。"""
    from heagent.cli.http_config import build_ws_servers

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        ws_host=PRIVATE_HOST,
        ws_lan_no_auth=True,
        ws_cli_bypass_enabled=True,
        ws_external_host=None,
    )
    servers, hub = build_ws_servers(settings)
    assert len(servers) == 1
    assert servers[0].config.mode == "lan"
    assert hub is None
