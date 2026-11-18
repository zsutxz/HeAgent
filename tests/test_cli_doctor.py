"""`heagent doctor` 的判据：每类检查都有自己的正/负例，外加退出码与 JSON 形态。"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING

from click.testing import CliRunner

from heagent.cli import doctor as doc
from heagent.cli.doctor import Finding, Severity, run_checks
from heagent.config import Settings
from heagent.config.catalog import build_config_report

if TYPE_CHECKING:
    import pytest

# 干净的 Settings：`_env_file=None` 只关掉 dotenv 文件，进程环境变量仍会被 pydantic-settings 读到
# ⇒ 必须把「会被环境注入」的字段显式置 None，否则跑测机器的环境会改变结论。
_CLEAN: dict[str, object] = {
    "deepseek_api_key": None,
    "kimi_api_key": None,
    "glm_api_key": None,
    "anthropic_api_key": None,
    "anthropic_api_keys": "",
    "openai_responses_api_key": None,
    "ollama_enabled": False,
    "routing_pools": "",
    "ws_host": "127.0.0.1",
    "ws_external_host": None,
    "ws_tls_cert_file": None,
    "ws_tls_key_file": None,
    "ws_external_tls_cert_file": None,
    "ws_external_tls_key_file": None,
    "sandbox_backend": "auto",
    "approval_tools": "",
    "safety_blocked_tools": [],
}
_BASE = {**_CLEAN, "deepseek_api_key": "sk-test"}


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = dict(_BASE)
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _clean_settings(**overrides: object) -> Settings:
    values: dict[str, object] = dict(_CLEAN)
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _report(tmp_path: Path, content: str | None = "") -> object:
    """写一个项目 .env 并求解；``content=None`` 表示**不创建**文件。"""
    env = tmp_path / ".env"
    if content is not None:
        env.write_text(content, encoding="utf-8")
    return build_config_report(env, global_setting_file=None)


def _codes(findings: list[Finding]) -> set[str]:
    return {item.code for item in findings}


def _run(settings: Settings, report: object, *, tools: set[str] | None = None) -> list[Finding]:
    return run_checks(settings, report, registered_tools=tools or set())  # type: ignore[arg-type]


class TestCredentials:
    def test_missing_credential_is_error(self, tmp_path: Path) -> None:
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        findings = _run(settings, _report(tmp_path))
        assert "doctor.no_credentials" in _codes(findings)
        assert next(item for item in findings if item.code == "doctor.no_credentials").severity is Severity.ERROR

    def test_configured_credential_is_clean(self, tmp_path: Path) -> None:
        assert "doctor.no_credentials" not in _codes(_run(_settings(), _report(tmp_path)))

    def test_ollama_without_model_is_error(self, tmp_path: Path) -> None:
        settings = _settings(ollama_enabled=True, ollama_model=None)
        assert "doctor.ollama_model_missing" in _codes(_run(settings, _report(tmp_path)))


class TestLimitsAndRouting:
    def test_output_not_smaller_than_context(self, tmp_path: Path) -> None:
        settings = _settings(max_context_tokens=1000, max_output_tokens=1000)
        assert "doctor.token_limits_inverted" in _codes(_run(settings, _report(tmp_path)))

    def test_unknown_active_provider(self, tmp_path: Path) -> None:
        settings = _settings(active_provider="gpt-5")
        assert "doctor.active_provider_unknown" in _codes(_run(settings, _report(tmp_path)))

    def test_active_provider_without_credentials_is_error(self, tmp_path: Path) -> None:
        settings = _settings(active_provider="kimi")
        findings = _run(settings, _report(tmp_path))
        item = next((f for f in findings if f.code == "doctor.active_provider_without_credentials"), None)
        assert item is not None and item.severity is Severity.ERROR
        assert "KIMI_API_KEY" in item.fix

    def test_known_active_provider_is_clean(self, tmp_path: Path) -> None:
        settings = _settings(active_provider="deepseek")
        assert "doctor.active_provider_unknown" not in _codes(_run(settings, _report(tmp_path)))

    def test_routing_pools_invalid_json(self, tmp_path: Path) -> None:
        settings = _settings(routing_pools="{not json")
        assert "doctor.routing_pools_invalid" in _codes(_run(settings, _report(tmp_path)))

    def test_routing_pool_without_credentials(self, tmp_path: Path) -> None:
        settings = _settings(
            routing_pools='{"glm": {"tiers": {"fast": "glm-5-flash"}}}',
            glm_api_key=None,
        )
        assert "doctor.routing_pool_without_credentials" in _codes(_run(settings, _report(tmp_path)))

    def test_routing_pool_with_credentials_is_clean(self, tmp_path: Path) -> None:
        settings = _settings(
            routing_pools='{"deepseek": {"tiers": {"fast": "deepseek-flash"}}}',
        )
        findings = _run(settings, _report(tmp_path))
        assert "doctor.routing_pool_without_credentials" not in _codes(findings)


class TestEnvFile:
    def test_duplicate_blank_and_unknown_keys(self, tmp_path: Path) -> None:
        report = _report(
            tmp_path,
            "DEEPSEEK_API_KEY=sk-a\nDEEPSEEK_API_KEY=sk-b\nOPENAI_API_KEY=\nNOT_A_REAL_KEY=1\n",
        )
        codes = _codes(_run(_settings(), report))
        assert "doctor.env_duplicate_keys" in codes
        assert "doctor.env_blank_value" in codes
        assert "doctor.env_unknown_keys" in codes

    def test_bom_detected(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_bytes("\ufeffDEEPSEEK_API_KEY=sk-a\n".encode())
        report = build_config_report(env, global_setting_file=None)
        assert "doctor.env_bom" in _codes(_run(_settings(), report))

    def test_missing_env_is_info(self, tmp_path: Path) -> None:
        report = build_config_report(tmp_path / "absent.env", global_setting_file=None)
        findings = _run(_settings(), report)
        item = next((f for f in findings if f.code == "doctor.env_missing"), None)
        assert item is not None and item.severity is Severity.INFO


class TestWsAndPorts:
    def test_main_external_without_token_is_error(self, tmp_path: Path) -> None:
        settings = _settings(ws_host="0.0.0.0")
        findings = _run(settings, _report(tmp_path))
        assert "doctor.ws_main_external_without_token" in _codes(findings)

    def test_ws_disabled_skips_ws_checks(self, tmp_path: Path) -> None:
        settings = _settings(ws_enabled=False, ws_host="0.0.0.0", ws_external_host="192.168.1.5")
        codes = _codes(_run(settings, _report(tmp_path)))
        assert not {code for code in codes if code.startswith("doctor.ws_")}

    def test_external_listener_uses_its_own_code(self, tmp_path: Path) -> None:
        settings = _settings(ws_external_host="192.168.1.5")
        codes = _codes(_run(settings, _report(tmp_path)))
        assert "doctor.ws_external_listener_without_token" in codes
        assert "doctor.ws_main_external_without_token" not in codes

    def test_local_auth_without_token_is_error(self, tmp_path: Path) -> None:
        settings = _settings(ws_local_auth_enabled=True)
        assert "doctor.ws_local_auth_without_token" in _codes(_run(settings, _report(tmp_path)))

    def test_main_and_external_both_non_loopback_conflict(self, tmp_path: Path) -> None:
        settings = _settings(ws_host="0.0.0.0", ws_external_host="192.168.1.5")
        assert "doctor.ws_external_host_conflict" in _codes(_run(settings, _report(tmp_path)))

    def test_external_host_loopback_is_error(self, tmp_path: Path) -> None:
        settings = _settings(ws_external_host="127.0.0.1")
        assert "doctor.ws_external_host_loopback" in _codes(_run(settings, _report(tmp_path)))

    def test_tls_half_configured(self, tmp_path: Path) -> None:
        settings = _settings(ws_tls_cert_file="cert.pem")
        assert "doctor.ws_tls_half_configured" in _codes(_run(settings, _report(tmp_path)))

    def test_port_in_use_detected(self, tmp_path: Path) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            port = sock.getsockname()[1]
            settings = _settings(http_enabled=True, http_port=port)
            findings = _run(settings, _report(tmp_path))
            assert "doctor.port_in_use" in _codes(findings)


class TestToolsAndSandbox:
    def test_unknown_approval_tool(self, tmp_path: Path) -> None:
        settings = _settings(approval_tools="shell,no_such_tool")
        findings = _run(settings, _report(tmp_path), tools={"shell"})
        assert "doctor.approval_tools_unknown" in _codes(findings)

    def test_known_approval_tool_is_clean(self, tmp_path: Path) -> None:
        settings = _settings(approval_tools="shell")
        assert "doctor.approval_tools_unknown" not in _codes(_run(settings, _report(tmp_path), tools={"shell"}))

    def test_blocking_shell_is_flagged(self, tmp_path: Path) -> None:
        settings = _settings(safety_blocked_tools=["shell"])
        assert "doctor.safety_blocks_shell" in _codes(_run(settings, _report(tmp_path)))

    def test_docker_backend_without_daemon(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(doc, "_docker_daemon_endpoint", lambda: None)
        settings = _settings(sandbox_backend="docker")
        findings = _run(settings, _report(tmp_path))
        assert "doctor.docker_backend_unavailable" in _codes(findings)


class TestSkillConflicts:
    def test_conflict_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        class _FakeStore:
            def __init__(self, *_a: object, **_k: object) -> None:
                pass

            def conflicts(self) -> list[object]:
                return [
                    type(
                        "Conflict",
                        (),
                        {"name": "demo", "effective_root": "~/.heagent/skills", "shadowed_root": ".heagent/skills"},
                    )()
                ]

        import heagent.skills.skill_store as skill_store

        monkeypatch.setattr(skill_store, "SkillStore", _FakeStore)
        findings = _run(_settings(), _report(tmp_path))
        assert "doctor.skill_name_conflict" in _codes(findings)


class TestCommand:
    def test_json_output_is_json_array(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(doc, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
        result = CliRunner().invoke(doc.doctor_cmd, ["--json"])
        payload = json.loads(result.output)
        assert isinstance(payload, list) and payload
        for item in payload:
            assert {"code", "severity", "message", "fix"} <= set(item)
        assert result.exit_code == 1  # 无凭据 ⇒ 有 error
        assert any(item["severity"] == "error" for item in payload)

    def test_exit_code_reflects_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(doc, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
        result = CliRunner().invoke(doc.doctor_cmd, [])
        assert result.exit_code == 1

    def test_clean_config_exits_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(doc, "get_settings", lambda: _settings())
        monkeypatch.setattr(doc, "_port_in_use", lambda *_a, **_k: False)
        monkeypatch.setattr(doc, "_docker_daemon_endpoint", lambda: "unix:///tmp/fake.sock")
        (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=sk-a\n", encoding="utf-8")
        result = CliRunner().invoke(doc.doctor_cmd, ["--json"])
        findings = json.loads(result.output)
        assert [f for f in findings if f["severity"] == "error"] == []
        assert result.exit_code == 0

    def test_runtime_under_five_seconds(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(doc, "get_settings", lambda: _settings())
        monkeypatch.setattr(doc, "_port_in_use", lambda *_a, **_k: False)
        started = time.perf_counter()
        CliRunner().invoke(doc.doctor_cmd, [])
        assert time.perf_counter() - started < 5.0
