"""Story 64.7 启动期必需配置验证：判据、门控、覆盖率、耗时与跨层文案一致性。

判据纪律：所有断言只读 ``heagent.config.validation`` 的公开常量/函数，不硬编码比例或键名清单；
跨层文案（composition 的 ProviderConfigError、network 的回环判定）用交叉断言钉死漂移。
"""

from __future__ import annotations

import ast
import statistics
import time
from pathlib import Path

import pytest

from heagent.cli.wiring import ensure_startup_config, load_startup_settings
from heagent.config import Settings
from heagent.config import validation
from heagent.config.validation import (
    NO_CREDENTIALS_MESSAGE,
    OLLAMA_MODEL_MISSING_MESSAGE,
    REQUIRED_CHECKS,
    REQUIRED_SETTING_KEYS,
    covered_setting_keys,
    required_coverage,
    required_coverage_ratio,
    validate_startup,
)

_VALIDATION_SOURCE = Path(validation.__file__).resolve()

_GOOD_DIGEST = "sha256:" + "a" * 64


def _settings(**kwargs: object) -> Settings:
    """构造零外部来源的 ``Settings``（``_env_file=None``：不读项目 ``.env``）。"""
    return Settings(_env_file=None, **kwargs)


def _failed_checks(settings: Settings) -> set[str]:
    return {issue.check for issue in validate_startup(settings).issues}


def _issue(settings: Settings, check: str) -> validation.ConfigIssue:
    """取指定检查的失败结论（不存在即测试失败，比断言集合更直观）。"""
    for item in validate_startup(settings).issues:
        if item.check == check:
            return item
    raise AssertionError(f"check {check!r} did not report an issue; got {_failed_checks(settings)}")


class TestKeyRegistry:
    """必需键注册表与覆盖率口径。"""

    def test_every_required_key_is_a_settings_field(self) -> None:
        unknown = sorted(REQUIRED_SETTING_KEYS - set(Settings.model_fields))
        assert not unknown, f"REQUIRED_SETTING_KEYS 里有不存在的 Settings 字段: {unknown}"

    def test_check_covers_are_settings_fields(self) -> None:
        unknown = sorted(covered_setting_keys() - set(Settings.model_fields))
        assert not unknown, f"REQUIRED_CHECKS 登记了不存在的字段: {unknown}"

    def test_coverage_above_threshold_uses_code_constants(self) -> None:
        """票面 verify「覆盖 >90%」：分子分母都从代码常量读出，比例不硬编码。"""
        covered, total = required_coverage()
        # 两条恒等式只证明分子分母口径一致（都从同一对常量算出），不构成覆盖证据
        assert total == len(REQUIRED_SETTING_KEYS)
        assert covered == len(covered_setting_keys() & REQUIRED_SETTING_KEYS)
        assert total > 0
        # 覆盖证据只有这一行比值：登记表两端同时漏改时恒等式仍会通过，比值断言才拦得住
        assert covered / total > 0.9, f"必需配置项覆盖率 {covered}/{total} 低于 90%"
        assert required_coverage_ratio() == pytest.approx(covered / total)

    def test_registry_guard_rejects_unknown_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """导入即核的守卫要真的能炸：字段名写错不应静默算成「已覆盖」。"""
        monkeypatch.setattr(validation, "REQUIRED_SETTING_KEYS", frozenset({"not_a_real_field"}))
        with pytest.raises(ValueError, match="unknown Settings fields"):
            validation._verify_key_registry()  # noqa: SLF001 - 直接钉住导入期守卫


class TestProviderChecks:
    """provider 面：零凭据与 Ollama 缺模型都是 composition 的既有 fail-fast 点。"""

    def test_no_credentials_blocks(self) -> None:
        issue = _issue(_settings(), "provider_credentials")
        assert issue.message == NO_CREDENTIALS_MESSAGE
        assert "No API key configured" in issue.message
        assert "DEEPSEEK_API_KEY" in issue.message
        assert issue.options

    @pytest.mark.parametrize(
        "field",
        [
            "deepseek_api_key",
            "anthropic_api_key",
            "anthropic_api_keys",
            "kimi_api_key",
            "glm_api_key",
            "openai_responses_api_key",
        ],
    )
    def test_single_credential_passes(self, field: str) -> None:
        assert "provider_credentials" not in _failed_checks(_settings(**{field: "sk-test"}))

    def test_ollama_enabled_counts_as_credential(self) -> None:
        assert "provider_credentials" not in _failed_checks(_settings(ollama_enabled=True, ollama_model="qwen3:8b"))

    def test_ollama_enabled_without_model_blocks(self) -> None:
        issue = _issue(_settings(ollama_enabled=True), "ollama_model")
        assert issue.message == OLLAMA_MODEL_MISSING_MESSAGE
        assert "OLLAMA_MODEL" in issue.message
        assert issue.options

    def test_ollama_gate_off_when_disabled(self) -> None:
        """未启用 Ollama 时 `OLLAMA_MODEL` 为空不算问题（门控）。"""
        assert "ollama_model" not in _failed_checks(_settings(deepseek_api_key="sk-test"))

    def test_blank_model_string_blocks(self) -> None:
        """空白串等价于未配置——不能让 ``OLLAMA_MODEL="   "`` 混过去。"""
        assert "ollama_model" in _failed_checks(_settings(ollama_enabled=True, ollama_model="   "))


class TestWsChecks:
    """WS 面：认证 / 绑定 / TLS 三条 fail-closed 判据，全部按启用状态门控。"""

    def test_loopback_bind_needs_no_token(self) -> None:
        """默认配置（回环 + 无对外 listener）不要求 token——门控不触发的核心用例。"""
        assert _failed_checks(_settings(deepseek_api_key="sk-test")) == set()

    def test_lan_mode_waives_the_token_requirement(self) -> None:
        """`WS_LAN_NO_AUTH=true` + 私有地址是显式免认证 ⇒ 不再要求 token（否则第一步起不来）。"""
        settings = _settings(ws_host="192.168.2.226", ws_lan_no_auth=True)
        assert "ws_auth_token" not in _failed_checks(settings)

    def test_lan_mode_rejects_a_wildcard_bind(self) -> None:
        issue = _issue(_settings(ws_host="0.0.0.0", ws_lan_no_auth=True), "ws_lan_no_auth")
        assert "private address literal" in issue.message
        assert issue.options

    def test_lan_mode_rejects_loopback_and_auth_conflict(self) -> None:
        loopback = _issue(_settings(ws_host="127.0.0.1", ws_lan_no_auth=True), "ws_lan_no_auth")
        assert "no effect on a loopback bind" in loopback.message

        conflict = _issue(
            _settings(ws_host="192.168.2.226", ws_lan_no_auth=True, ws_local_auth_enabled=True),
            "ws_lan_no_auth",
        )
        assert "mutually exclusive" in conflict.message

    def test_non_loopback_main_host_requires_token(self) -> None:
        issue = _issue(_settings(ws_host="0.0.0.0"), "ws_auth_token")
        assert "WS_HOST" in issue.message

    def test_local_auth_switch_requires_token(self) -> None:
        issue = _issue(_settings(ws_local_auth_enabled=True), "ws_auth_token")
        assert "WS_LOCAL_AUTH_ENABLED" in issue.message

    def test_token_from_user_setting_file_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        setting_md = tmp_path / "setting.md"
        setting_md.write_text("---\nws_auth_token: test-token\n---\n", encoding="utf-8")
        monkeypatch.setattr(Settings, "_user_setting_file", setting_md)
        settings = _settings(ws_host="192.168.2.226")
        assert "ws_auth_token" not in _failed_checks(settings)

    def test_ws_disabled_skips_every_ws_check(self) -> None:
        """``WS_ENABLED=false`` 时 token / 绑定 / TLS 都无从生效（否则是最吵的误报源）。"""
        settings = _settings(
            ws_enabled=False,
            ws_host="0.0.0.0",
            ws_lan_no_auth=True,
            ws_local_auth_enabled=True,
            ws_tls_cert_file="/certs/only-cert.pem",
        )
        assert {name for name in _failed_checks(settings) if name.startswith("ws_")} == set()

    def test_tls_half_config_blocks(self) -> None:
        issue = _issue(_settings(ws_tls_cert_file="/certs/cert.pem"), "ws_tls_pair")
        assert "WS_TLS_KEY_FILE" in issue.message
        assert issue.options

    def test_tls_pair_passes(self) -> None:
        settings = _settings(
            ws_tls_cert_file="/certs/cert.pem",
            ws_tls_key_file="/certs/key.pem",
        )
        assert "ws_tls_pair" not in _failed_checks(settings)

    def test_gate_skips_user_setting_file_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """门控为假时**不读** ``setting.md``：文件坏掉也不该在 WS 关闭时拦住启动。"""
        settings = _settings(deepseek_api_key="sk-test", ws_enabled=False, ws_host="192.168.2.226")
        broken = tmp_path / "setting.md"
        broken.write_text("no frontmatter here\n", encoding="utf-8")
        # 构造之后再指向坏文件：`Settings` 的构造会读用户层，这里只想让 token 属性去踩它。
        monkeypatch.setattr(Settings, "_user_setting_file", broken)
        assert validate_startup(settings).ok

    def test_broken_user_setting_file_surfaces_as_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``setting.md`` 语法错（读 token 时抛 SettingsError）必须转成阻断项，而不是无声跳过。"""
        settings = _settings(ws_host="192.168.2.226")
        broken = tmp_path / "setting.md"
        broken.write_text("no frontmatter here\n", encoding="utf-8")
        monkeypatch.setattr(Settings, "_user_setting_file", broken)
        issue = _issue(settings, "ws_auth_token")
        assert "crashed" in issue.message
        assert "SettingsError" in issue.message
        assert len(issue.options) >= 2


class TestSandboxChecks:
    """沙箱面：``SANDBOX_BACKEND=docker`` 时镜像引用是每条命令的输入。"""

    def test_docker_requires_image(self) -> None:
        issue = _issue(_settings(sandbox_backend="docker", sandbox_docker_image="  "), "sandbox_docker")
        assert "SANDBOX_DOCKER_IMAGE" in issue.message
        assert issue.options

    def test_docker_rejects_malformed_digest(self) -> None:
        issue = _issue(_settings(sandbox_backend="docker", sandbox_docker_digest="sha256:abc"), "sandbox_docker")
        assert "SANDBOX_DOCKER_DIGEST" in issue.message

    def test_docker_accepts_repo_digest(self) -> None:
        settings = _settings(sandbox_backend="docker", sandbox_docker_digest=_GOOD_DIGEST)
        assert "sandbox_docker" not in _failed_checks(settings)

    @pytest.mark.parametrize("backend", ["passthrough", "auto", "firejail", "winjob"])
    def test_non_docker_backend_is_gated_out(self, backend: str) -> None:
        settings = _settings(sandbox_backend=backend, sandbox_docker_image="", sandbox_docker_digest="bogus")
        assert "sandbox_docker" not in _failed_checks(settings)


class TestCrashHandling:
    """单项检查崩溃必须升为阻断项——静默放行会让「验证过了却起不来」重新出现。"""

    def _check(self, *, judge, gate=lambda settings: True) -> validation.RequiredCheck:  # noqa: ANN001
        return validation.RequiredCheck(
            name="boom",
            covers=(),
            gate=gate,
            judge=judge,
            options=("fix it",),
        )

    def test_judge_crash_becomes_blocking_issue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(settings: Settings) -> str | None:
            raise RuntimeError("kaboom")

        monkeypatch.setattr(validation, "REQUIRED_CHECKS", (self._check(judge=_boom),))
        result = validate_startup(_settings())
        assert not result.ok
        assert result.issues[0].check == "boom"
        assert "RuntimeError" in result.issues[0].message
        assert "kaboom" in result.issues[0].message

    def test_gate_crash_becomes_blocking_issue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _gate(settings: Settings) -> bool:
            raise KeyError("gate")

        monkeypatch.setattr(
            validation,
            "REQUIRED_CHECKS",
            (self._check(judge=lambda settings: None, gate=_gate),),
        )
        result = validate_startup(_settings())
        assert not result.ok
        assert "KeyError" in result.issues[0].message


class TestRendering:
    """入口层呈现：失败走「描述 + Try + Docs」+ 退出码 1；通过则完全静默。"""

    def test_ensure_startup_config_exits_with_hints(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            ensure_startup_config(_settings())
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "No API key configured" in err
        assert "Try:" in err
        assert "Docs: docs/errors.md#" in err
        assert "DEEPSEEK_API_KEY" in err

    def test_ensure_startup_config_silent_when_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        ensure_startup_config(_settings(deepseek_api_key="sk-test"))
        assert capsys.readouterr().err == ""

    def test_load_startup_settings_wraps_construction_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _boom() -> Settings:
            raise ValueError("MAX_ITERATIONS must be >= 1")

        monkeypatch.setattr("heagent.cli.wiring.get_settings", _boom)
        with pytest.raises(SystemExit) as excinfo:
            load_startup_settings()
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "configuration could not be loaded" in err
        assert "MAX_ITERATIONS must be >= 1" in err
        assert "Try:" in err
        assert "Docs: docs/errors.md#" in err


class TestPerformanceAndPurity:
    """票面 verify「验证耗时 <100ms」与「不探测」的静态约束。"""

    def test_validation_is_fast_steady_state(self) -> None:
        settings = _settings(ws_host="192.168.2.226", sandbox_backend="docker")
        samples: list[float] = []
        for _ in range(200):
            started = time.perf_counter()
            result = validate_startup(settings)
            samples.append((time.perf_counter() - started) * 1000.0)
            assert result.duration_ms < 100.0
        p95 = statistics.quantiles(samples, n=20)[-1]
        assert max(samples) < 100.0, f"max={max(samples):.2f}ms"
        assert p95 < 100.0, f"p95={p95:.2f}ms"

    def test_module_does_not_probe_sockets_or_spawn_processes(self) -> None:
        tree = ast.parse(_VALIDATION_SOURCE.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        forbidden = {"socket", "subprocess", "asyncio", "urllib", "http", "requests", "httpx"}
        assert not (imported & forbidden), f"启动验证不得引入探测能力: {sorted(imported & forbidden)}"


class TestCrossLayerContracts:
    """跨层文案与判定的等价性：任一侧漂移都先在本文件变红。"""

    def test_credentials_message_matches_composition_contract(self) -> None:
        from heagent.providers.composition import ProviderConfigError
        from heagent.providers.composition import _build_provider as composition_build_provider

        with pytest.raises(ProviderConfigError) as excinfo:
            composition_build_provider(_settings(), None)
        assert str(excinfo.value) == NO_CREDENTIALS_MESSAGE

    def test_ollama_message_matches_composition_contract(self) -> None:
        from heagent.providers.composition import ProviderConfigError
        from heagent.providers.composition import _build_provider as composition_build_provider

        with pytest.raises(ProviderConfigError) as excinfo:
            composition_build_provider(_settings(ollama_enabled=True), None)
        assert str(excinfo.value) == OLLAMA_MODEL_MISSING_MESSAGE

    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "127.1.2.3",
            "::1",
            "[::1]",
            "localhost",
            "LOCALHOST",
            "0.0.0.0",
            "::",
            "192.168.2.226",
            "example.local",
            "",
            " 127.0.0.1 ",
            "[localhost]",
            "10.0.0.1",
        ],
    )
    def test_loopback_matches_network_exposure(self, host: str) -> None:
        from heagent.network.exposure import is_loopback_host

        assert validation._is_loopback(host) == is_loopback_host(host)  # noqa: SLF001

    def test_check_names_are_unique(self) -> None:
        names = [check.name for check in REQUIRED_CHECKS]
        assert len(names) == len(set(names))
        assert all(check.options for check in REQUIRED_CHECKS)
