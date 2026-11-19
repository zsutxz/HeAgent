"""Story 73.3 的判据：启动期 TLS 身份自检（到期 / SAN / 配对）与 doctor 的三项 finding。

时钟注入是这套判据的关键：夹具叶证书到期在 2036 年，余量一律用 ``now = not_after - N 天`` 构造，
**不现签短期证书**（现签依赖 openssl，且「余量」判据会随机器时钟漂移）。

四类事实各有独立判据：

- 未启用 TLS（cert/key 任一为空）⇒ 三条检查零输出、零告警；
- 到期余量 < ``TLS_EXPIRY_WARNING_DAYS`` ⇒ 恰一条 WARNING，文案点名 ``heagent tls issue``；
- 绑定地址不在 SAN ⇒ 恰一条 WARNING，点名 ``heagent tls issue --san <addr>``，**不阻断启动**；
- cert 与 key 不配对 / 材料读不出来 ⇒ ``WsConfigError`` 拒绝启动，且 CLI 侧只有一行可读文案。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from heagent.cli import doctor as doc
from heagent.cli import http_config
from heagent.cli.http import embedded_http_error_message
from heagent.cli.http_config import TLS_EXPIRY_WARNING_DAYS, _check_tls_identity, build_ws_servers
from heagent.config import Settings
from heagent.config.catalog import build_config_report
from heagent.network.tls_identity import cert_not_after
from heagent.network.ws_host import WsConfigError, WsServerConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tls"
CERT = str(FIXTURES / "cert.pem")
KEY = str(FIXTURES / "key.pem")
OTHER_KEY = str(FIXTURES / "other-key.pem")
NO_SAN_CERT = str(FIXTURES / "no-san-cert.pem")
NO_SAN_KEY = str(FIXTURES / "no-san-key.pem")

#: 夹具叶证书的到期时刻（固定材料 ⇒ 常量，见 ``tests/test_tls_identity.py`` 的 EXPECTED_NOT_AFTER）。
NOT_AFTER = cert_not_after(CERT)

_LOGGER = "heagent.cli.http_config"

# 干净基线：``_env_file=None`` 只关 dotenv，进程环境变量仍会进 Settings ⇒ 参与判据的键逐项显式给值。
_CLEAN: dict[str, Any] = {
    "deepseek_api_key": "sk-test",
    "ws_enabled": True,
    "ws_host": "127.0.0.1",
    "ws_lan_no_auth": False,
    "ws_local_auth_enabled": False,
    "ws_cli_bypass_enabled": False,
    "ws_tls_cert_file": None,
    "ws_tls_key_file": None,
}


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**_CLEAN, **overrides})  # type: ignore[call-arg]


def _tls_settings(**overrides: Any) -> Settings:
    """TLS 已启用（cert + key 默认是夹具材料，可逐项覆盖）的配置。"""
    values: dict[str, Any] = {"ws_tls_cert_file": CERT, "ws_tls_key_file": KEY}
    values.update(overrides)
    return _settings(**values)


def _tls_identity_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    """本次装配打出的 TLS 身份告警（判据用它数「恰一条」）。"""
    return [record.getMessage() for record in caplog.records if "ws event=tls_identity" in record.getMessage()]


class TestTlsOffIsSilent:
    def test_no_checks_and_no_logs_when_tls_is_off(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = _settings()
        assert _check_tls_identity(settings, "127.0.0.1") == []
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            servers, _hub = build_ws_servers(settings)
        assert len(servers) == 1
        assert _tls_identity_records(caplog) == []

    def test_blank_strings_count_as_unconfigured(self) -> None:
        """``.env`` 里写 ``WS_TLS_CERT_FILE=`` 的形态：空串不是「已配置」。"""
        assert _check_tls_identity(_settings(ws_tls_cert_file="  ", ws_tls_key_file="  "), "127.0.0.1") == []

    def test_half_configured_keeps_the_existing_semantics(self, caplog: pytest.LogCaptureFixture) -> None:
        """半配仍由 ``WsServerConfig`` / ``doctor.ws_tls_half_configured`` 处理，自检不新增告警。"""
        settings = _settings(ws_tls_cert_file=CERT)
        assert _check_tls_identity(settings, "127.0.0.1") == []
        with caplog.at_level(logging.WARNING, logger=_LOGGER), pytest.raises(WsConfigError):
            build_ws_servers(settings)
        assert _tls_identity_records(caplog) == []


class TestExpiry:
    def test_three_days_left_is_one_warning_naming_the_command(self) -> None:
        warnings = _check_tls_identity(_tls_settings(), "127.0.0.1", now=NOT_AFTER - timedelta(days=3))
        assert len(warnings) == 1
        assert "expires in 3.0 days" in warnings[0]
        assert "heagent tls issue" in warnings[0]

    def test_twenty_days_left_is_silent(self) -> None:
        assert _check_tls_identity(_tls_settings(), "127.0.0.1", now=NOT_AFTER - timedelta(days=20)) == []

    def test_threshold_is_exactly_the_shared_constant(self) -> None:
        """6 天 23 小时告警、整 7 天不告警 ⇒ 阈值就是 :data:`TLS_EXPIRY_WARNING_DAYS`，没有第二份字面量。"""
        assert TLS_EXPIRY_WARNING_DAYS == 7
        soon = NOT_AFTER - timedelta(days=TLS_EXPIRY_WARNING_DAYS) + timedelta(hours=1)
        edge = NOT_AFTER - timedelta(days=TLS_EXPIRY_WARNING_DAYS)
        assert _check_tls_identity(_tls_settings(), "127.0.0.1", now=soon) != []
        assert _check_tls_identity(_tls_settings(), "127.0.0.1", now=edge) == []

    def test_expired_certificate_is_still_one_warning(self) -> None:
        warnings = _check_tls_identity(_tls_settings(), "127.0.0.1", now=NOT_AFTER + timedelta(days=2))
        assert len(warnings) == 1
        assert "expired 2.0 days ago" in warnings[0]
        assert "heagent tls issue" in warnings[0]

    def test_assembly_logs_it_exactly_once(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """装配点只跑一次自检 ⇒ 每次启动恰一条，不因多次装配叠加。"""
        monkeypatch.setattr(http_config, "tls_remaining_days", lambda *_a, **_k: 3.0)
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            build_ws_servers(_tls_settings())
        records = _tls_identity_records(caplog)
        assert len(records) == 1
        assert "heagent tls issue" in records[0]


class TestSanCoverage:
    def test_uncovered_bind_address_warns_with_the_resign_command(self, caplog: pytest.LogCaptureFixture) -> None:
        """装配点确实把 SAN 缺失写成 WARNING（用无 SAN 的夹具证书走回环，避开认证档的 token 依赖）。"""
        settings = _tls_settings(ws_host="127.0.0.1", ws_tls_cert_file=NO_SAN_CERT, ws_tls_key_file=NO_SAN_KEY)
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            servers, _hub = build_ws_servers(settings)
        # 不阻断启动：内网地址漂移是常态，只能告警 + 给命令。
        assert len(servers) == 1
        records = _tls_identity_records(caplog)
        assert len(records) == 1
        assert "--san 127.0.0.1" in records[0]

    def test_covered_addresses_are_silent(self) -> None:
        assert _check_tls_identity(_tls_settings(), "127.0.0.1") == []
        assert _check_tls_identity(_tls_settings(), "heagent.local") == []
        assert _check_tls_identity(_tls_settings(ws_host="192.168.2.226"), "192.168.2.226") == []

    def test_wildcard_bind_is_not_judged(self) -> None:
        """``0.0.0.0`` 不是客户端要连的地址：拿它比 SAN 只会制造假告警。"""
        assert _check_tls_identity(_tls_settings(), "0.0.0.0") == []
        assert _check_tls_identity(_tls_settings(), "[::]") == []

    def test_certificate_without_san_warns(self) -> None:
        warnings = _check_tls_identity(_settings(ws_tls_cert_file=NO_SAN_CERT, ws_tls_key_file=KEY), "127.0.0.1")
        assert len(warnings) == 1
        assert "none" in warnings[0]


class TestPairing:
    def test_mismatched_pair_refuses_startup_naming_both_keys(self) -> None:
        with pytest.raises(WsConfigError) as caught:
            build_ws_servers(_tls_settings(ws_tls_key_file=OTHER_KEY))
        message = str(caught.value)
        assert "WS_TLS_CERT_FILE" in message
        assert "WS_TLS_KEY_FILE" in message
        assert "heagent tls verify" in message

    def test_cli_turns_it_into_one_line_without_a_traceback(self) -> None:
        with pytest.raises(WsConfigError) as caught:
            build_ws_servers(_tls_settings(ws_tls_key_file=OTHER_KEY))
        text = embedded_http_error_message(caught.value)
        assert text is not None
        assert "Traceback" not in text
        assert "WS_TLS_CERT_FILE" in text

    def test_unreadable_materials_refuse_startup(self, tmp_path: Path) -> None:
        settings = _tls_settings(
            ws_tls_cert_file=str(tmp_path / "absent.pem"),
            ws_tls_key_file=str(tmp_path / "absent.key"),
        )
        with pytest.raises(WsConfigError) as caught:
            build_ws_servers(settings)
        message = str(caught.value)
        assert "unreadable" in message
        assert "WS_TLS_CERT_FILE" in message

    def test_config_construction_still_defers_unreadable_materials(self, tmp_path: Path) -> None:
        """构造期只判「读得出却不配对」；读失败留给装配期与启动期报（不给两份互相矛盾的错）。"""
        config = WsServerConfig(
            tls_cert_file=str(tmp_path / "absent.pem"),
            tls_key_file=str(tmp_path / "absent.key"),
        )
        assert config.tls_enabled is True


class TestDoctorFindings:
    def test_healthy_materials_produce_all_three(self) -> None:
        findings = doc._check_ws_tls_identity(_tls_settings())
        codes = [item.code for item in findings]
        assert codes == ["doctor.ws_tls_fingerprint", "doctor.ws_tls_expiry", "doctor.ws_tls_san"]
        fingerprint, expiry, san = findings
        assert fingerprint.severity is doc.Severity.INFO
        assert "2WXW-EXAT-426J" in fingerprint.message
        assert "sha256/" in fingerprint.message
        assert expiry.severity is doc.Severity.INFO
        assert san.severity is doc.Severity.INFO

    def test_expiry_below_threshold_is_a_warning(self) -> None:
        findings = doc._check_ws_tls_identity(_tls_settings(), now=NOT_AFTER - timedelta(days=3))
        expiry = next(item for item in findings if item.code == "doctor.ws_tls_expiry")
        assert expiry.severity is doc.Severity.WARNING
        assert "3.0 days" in expiry.message
        assert "heagent tls issue" in expiry.fix

    def test_expired_certificate_is_a_warning_pointing_at_the_command(self) -> None:
        findings = doc._check_ws_tls_identity(_tls_settings(), now=NOT_AFTER + timedelta(days=1))
        expiry = next(item for item in findings if item.code == "doctor.ws_tls_expiry")
        assert expiry.severity is doc.Severity.WARNING
        assert "expired" in expiry.message
        assert "heagent tls issue" in expiry.fix

    def test_san_miss_is_a_warning_naming_the_resign_command(self) -> None:
        findings = doc._check_ws_tls_identity(_tls_settings(ws_host="192.168.2.99"))
        san = next(item for item in findings if item.code == "doctor.ws_tls_san")
        assert san.severity is doc.Severity.WARNING
        assert "heagent tls issue --san 192.168.2.99" in san.fix

    def test_wildcard_bind_is_info_not_a_false_alarm(self) -> None:
        findings = doc._check_ws_tls_identity(_tls_settings(ws_host="0.0.0.0"))
        san = next(item for item in findings if item.code == "doctor.ws_tls_san")
        assert san.severity is doc.Severity.INFO

    def test_tls_off_and_half_configured_produce_nothing(self) -> None:
        assert doc._check_ws_tls_identity(_settings()) == []
        assert doc._check_ws_tls_identity(_settings(ws_tls_cert_file=CERT)) == []

    def test_unreadable_certificate_is_a_single_error(self, tmp_path: Path) -> None:
        findings = doc._check_ws_tls_identity(
            _settings(ws_tls_cert_file=str(tmp_path / "absent.pem"), ws_tls_key_file=KEY)
        )
        assert [item.code for item in findings] == ["doctor.ws_tls_unreadable"]
        assert findings[0].severity is doc.Severity.ERROR

    def test_run_checks_surfaces_them_in_the_ws_group(self, tmp_path: Path) -> None:
        report = build_config_report(tmp_path / ".env", global_setting_file=None)
        codes = {item.code for item in doc.run_checks(_tls_settings(), report, registered_tools=set())}
        assert {"doctor.ws_tls_fingerprint", "doctor.ws_tls_expiry", "doctor.ws_tls_san"} <= codes

    def test_ws_disabled_skips_them(self, tmp_path: Path) -> None:
        report = build_config_report(tmp_path / ".env", global_setting_file=None)
        settings = _tls_settings(ws_enabled=False)
        codes = {item.code for item in doc.run_checks(settings, report, registered_tools=set())}
        assert not {code for code in codes if code.startswith("doctor.ws_tls_")}


class TestDoctorExitCode:
    def test_warning_does_not_change_the_exit_code(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """WARNING 不阻断：只有 ERROR 才把退出码变成 1（语义与既有三档一致）。"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(doc, "get_settings", lambda: _tls_settings())
        monkeypatch.setattr(doc, "tls_remaining_days", lambda *_a, **_k: 3.0)
        monkeypatch.setattr(doc, "_port_in_use", lambda *_a, **_k: False)
        monkeypatch.setattr(doc, "_docker_daemon_endpoint", lambda: "unix:///tmp/fake.sock")
        (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=sk-a\n", encoding="utf-8")
        result = CliRunner().invoke(doc.doctor_cmd, ["--json"])
        payload = result.output
        assert "doctor.ws_tls_expiry" in payload
        assert result.exit_code == 0
