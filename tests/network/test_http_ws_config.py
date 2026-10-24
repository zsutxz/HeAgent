"""Epic 54 Story 54-2：WebSocket 依赖与配置契约。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from heagent.config import Settings
from heagent.config.catalog import RESOURCE_CEILINGS, classify, whitelist
from heagent.network.http_protocol import SSE_HEARTBEAT_SECONDS
from heagent.network.http_server import HttpServerConfig
from heagent.network.ws_protocol import WS_MAX_FRAME_BYTES, WS_PING_INTERVAL_SECONDS, WS_PING_TIMEOUT_SECONDS


def test_http_extra_declares_websockets_with_frozen_bounds() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    http_extra = project.split("http = [", 1)[1].split("]", 1)[0]
    dev_extra = project.split("dev = [", 1)[1].split("gui = [", 1)[0]

    assert '"websockets>=13.0,<18"' in http_extra
    assert "websockets" not in dev_extra
    assert project.count('"websockets>=13.0,<18"') == 1


def test_ws_connection_limit_defaults_and_validation_match_server_config() -> None:
    settings_field = Settings.model_fields["http_ws_max_connections"]
    config_field = HttpServerConfig.model_fields["ws_max_connections"]

    assert settings_field.default == config_field.default == 16
    assert Settings().http_ws_max_connections == 16
    assert HttpServerConfig().ws_max_connections == 16
    for value in (0, -1):
        with pytest.raises(ValidationError):
            Settings(http_ws_max_connections=value)
        with pytest.raises(ValidationError):
            HttpServerConfig(ws_max_connections=value)


def test_ws_connection_limit_is_classified_as_read_only_listening_surface() -> None:
    result = classify("HTTP_WS_MAX_CONNECTIONS")
    assert result.reason == "listening_surface"
    assert not result.writable
    assert "HTTP_WS_MAX_CONNECTIONS" not in whitelist()
    assert "HTTP_WS_MAX_CONNECTIONS" not in RESOURCE_CEILINGS


def test_ws_config_documented_in_env_example() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "HTTP_WS_MAX_CONNECTIONS" in example


def test_uvicorn_ws_options_are_declared_in_config() -> None:
    source = Path("src/heagent/network/http_server.py").read_text(encoding="utf-8")
    assert "ws_max_size=WS_MAX_FRAME_BYTES" in source
    assert "ws_ping_interval=WS_PING_INTERVAL_SECONDS" in source
    assert "ws_ping_timeout=WS_PING_TIMEOUT_SECONDS" in source
    assert WS_PING_INTERVAL_SECONDS == SSE_HEARTBEAT_SECONDS == 15.0
    assert WS_PING_TIMEOUT_SECONDS == 20.0
    assert WS_MAX_FRAME_BYTES == 64 * 1024


def test_http_server_config_ws_limit_is_independent_from_sse_pool() -> None:
    config = HttpServerConfig(max_subscribers=3, ws_max_connections=7)
    assert config.max_subscribers == 3
    assert config.ws_max_connections == 7


# ---- CLI 旁路订阅（Epic 55）----


def test_cli_ws_is_off_by_default_and_documented() -> None:
    """默认关是**契约**：无认证的本机通道不该因为升级就自己打开。"""
    assert Settings().http_cli_ws_enabled is False
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "HTTP_CLI_WS_ENABLED=false" in example


def test_cli_ws_switch_is_classified_as_read_only_listening_surface() -> None:
    result = classify("HTTP_CLI_WS_ENABLED")
    assert result.reason == "listening_surface"
    assert not result.writable
    assert "HTTP_CLI_WS_ENABLED" not in whitelist()


@pytest.mark.embedded_http_service
def test_embedded_service_only_attaches_a_hub_when_the_switch_is_on() -> None:
    """``embedded_http_service`` 标记：要断言真实的 ``build_http_service``（conftest 默认打桩）。"""
    from heagent.cli.http import build_http_service

    assert build_http_service(Settings(), executor=None).cli_hub is None
    hub = build_http_service(Settings(http_cli_ws_enabled=True), executor=None).cli_hub
    assert hub is not None
    # 额度取自同一个监听面旋钮：旁路只有一条流，故按 hub 计（与「每 run」的 WS 额度是不同口径）。
    assert hub.max_connections == Settings().http_ws_max_connections
