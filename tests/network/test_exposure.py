"""Story 48-5：监听地址暴露判定的语义（回环判定 / 不解析 DNS / 告警文案）。

判定是「谁能连上」的解释，**不是安全边界**——回环客户端同样不可信，故这里只钉住
「告警是否该出」，不钉任何「本地即可信」的假设。
"""

from __future__ import annotations

import socket

import pytest

from heagent.network.exposure import exposure_warning, is_loopback_host


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.1.2.3", "127.0.0.0", "::1", "[::1]", "localhost", "LOCALHOST", " 127.0.0.1 "],
)
def test_loopback_hosts_are_not_warned_about(host: str) -> None:
    assert is_loopback_host(host) is True
    assert exposure_warning(host) is None


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "[::]", "192.168.1.10", "10.0.0.1", "203.0.113.7", "example.invalid", "", "   "],
)
def test_everything_else_is_treated_as_exposed(host: str) -> None:
    """含未识别的字面量与主机名：不解析 DNS，一律判「可能对外暴露」（fail-safe 方向）。"""
    assert is_loopback_host(host) is False

    warning = exposure_warning(host)

    assert warning is not None
    assert "no authentication" in warning


def test_warning_states_the_three_risk_facts_and_stays_bounded() -> None:
    warning = exposure_warning("0.0.0.0")

    assert warning is not None
    assert "0.0.0.0" in warning
    assert "no authentication" in warning
    assert "no TLS" in warning
    assert "not a production security boundary" in warning
    # 不把「本机」当可信：文案必须同时说明回环客户端也不可信（story 48-5 的 Never 列表）。
    assert "untrusted input" in warning
    # 有界：stderr 一行 / 日志一条，不刷屏。
    assert len(warning) < 400


def test_hostname_resolution_is_never_attempted(monkeypatch: pytest.MonkeyPatch) -> None:
    """启动期不做 DNS：解析会引入阻塞 I/O，且「解析到本机」≠「实际绑定到本机」。"""

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("暴露判定不得解析主机名")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    monkeypatch.setattr(socket, "gethostbyname", _boom)
    monkeypatch.setattr(socket, "gethostbyname_ex", _boom)

    assert is_loopback_host("localhost") is True  # RFC 6761 约定的本机名：直接判定，不查表
    assert is_loopback_host("127.0.0.1") is True  # IP 字面量：只走 ipaddress
    assert is_loopback_host("some-name.invalid") is False  # 未识别主机名：按暴露处理


@pytest.mark.parametrize("host", ["localhost.", "LOCALHOST.", "[localhost]"])
def test_hostname_variants_that_are_not_the_literal_localhost_are_conservative(host: str) -> None:
    """``localhost.``（带根点 FQDN）等变体不特殊放行。

    判定只认字面量 ``localhost`` 与 IP 字面量：宁可多出一条告警（fail-safe），也不为省一条提示
    去解析 DNS——解析结果还会随网络环境变化。
    """
    assert is_loopback_host(host) is False
    assert exposure_warning(host) is not None
