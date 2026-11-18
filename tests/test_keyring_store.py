"""Story 67.5 系统 keyring 密钥存储的判据。

覆盖：默认关闭时与现状逐字一致（环境变量优先、完全不碰 keyring）、启用后 keyring 命中即用、
未命中回退、可选依赖缺失时**一次**显性 WARNING 后回退、keyring 后端报错降级、值永不进日志、
未知键名 fail-loud，以及 provider 装配确实走同一收敛点。
"""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

import pytest

from heagent.config import Settings
from heagent.config import keyring_store
from heagent.config.keyring_store import get_secret
from heagent.providers.composition import ProviderConfigError, _build_provider

KEY = "deepseek_api_key"
KEY_ENV = "DEEPSEEK_API_KEY"
FROM_ENV = "sk-from-environment"
FROM_KEYRING = "sk-from-system-keyring"

_API_KEY_ENV_VARS = (
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEYS",
    "KIMI_API_KEY",
    "GLM_API_KEY",
    "OPENAI_RESPONSES_API_KEY",
    "OLLAMA_API_KEY",
)


class _StubKeyring:
    """最小 keyring 替身：记录被查的账户名，可注入后端异常。"""

    def __init__(self, store: dict[str, str] | None = None, *, error: Exception | None = None) -> None:
        self.store = store or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def get_password(self, service: str, account: str) -> str | None:
        self.calls.append((service, account))
        if self.error is not None:
            raise self.error
        return self.store.get(account)


def _install_keyring(monkeypatch: pytest.MonkeyPatch, stub: _StubKeyring) -> _StubKeyring:
    module = types.ModuleType("keyring")
    module.get_password = stub.get_password  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", module)
    return stub


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """抹掉宿主真实密钥 + 重置「只告警一次」的模块级标记。"""
    for name in _API_KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keyring_store, "_MISSING_DEP_WARNED", False)


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


class TestDisabledByDefault:
    def test_default_is_off(self) -> None:
        assert Settings.model_fields["keyring_enabled"].get_default(call_default_factory=True) is False

    def test_disabled_never_touches_keyring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _install_keyring(monkeypatch, _StubKeyring({KEY_ENV: FROM_KEYRING}))
        settings = _settings(deepseek_api_key=FROM_ENV)

        assert get_secret(KEY, settings=settings) == FROM_ENV
        assert stub.calls == []

    def test_environment_variable_is_preferred_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(KEY_ENV, FROM_ENV)
        assert get_secret(KEY_ENV, settings=_settings()) == FROM_ENV

    def test_dotenv_layer_is_used_when_disabled(self) -> None:
        """``.env`` 走的是 ``Settings`` 字段本身——本模块只是原样返回，不改优先级。"""
        assert get_secret(KEY_ENV, settings=_settings(deepseek_api_key="sk-from-dotenv")) == "sk-from-dotenv"

    def test_unset_secret_returns_default(self) -> None:
        assert get_secret(KEY, settings=_settings()) is None
        assert get_secret(KEY, settings=_settings(), default="fallback") == "fallback"


class TestEnabledKeyring:
    def test_keyring_hit_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _install_keyring(monkeypatch, _StubKeyring({KEY_ENV: FROM_KEYRING}))
        settings = _settings(keyring_enabled=True, deepseek_api_key=FROM_ENV)

        assert get_secret(KEY, settings=settings) == FROM_KEYRING
        assert stub.calls == [(keyring_store.KEYRING_SERVICE, KEY_ENV)]

    def test_keyring_miss_falls_back_to_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_keyring(monkeypatch, _StubKeyring({}))
        monkeypatch.setenv(KEY_ENV, FROM_ENV)
        settings = _settings(keyring_enabled=True)

        assert get_secret(KEY_ENV, settings=settings) == FROM_ENV

    def test_keyring_miss_falls_back_to_dotenv_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_keyring(monkeypatch, _StubKeyring({}))
        assert get_secret(KEY, settings=_settings(keyring_enabled=True, deepseek_api_key="sk-from-dotenv")) == (
            "sk-from-dotenv"
        )

    def test_missing_optional_dependency_warns_once_and_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setitem(sys.modules, "keyring", None)  # `import keyring` → ImportError
        settings = _settings(keyring_enabled=True, deepseek_api_key=FROM_ENV)

        with caplog.at_level(logging.WARNING, logger="heagent.config.keyring_store"):
            assert get_secret(KEY, settings=settings) == FROM_ENV
            assert get_secret(KEY, settings=settings) == FROM_ENV

        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 1, "未安装 keyring 的告警每次进程只应打一次"
        assert "pip install keyring" in caplog.text
        assert "falling back" in caplog.text

    def test_backend_error_falls_back_without_raising(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _install_keyring(monkeypatch, _StubKeyring(error=RuntimeError("no DBus session")))
        settings = _settings(keyring_enabled=True, deepseek_api_key=FROM_ENV)

        with caplog.at_level(logging.WARNING, logger="heagent.config.keyring_store"):
            assert get_secret(KEY, settings=settings) == FROM_ENV
        assert "keyring lookup for DEEPSEEK_API_KEY failed" in caplog.text

    def test_secret_value_never_reaches_the_log(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _install_keyring(monkeypatch, _StubKeyring({KEY_ENV: FROM_KEYRING}))
        settings = _settings(keyring_enabled=True)

        with caplog.at_level(logging.DEBUG, logger="heagent.config.keyring_store"):
            assert get_secret(KEY, settings=settings) == FROM_KEYRING
        assert FROM_KEYRING not in caplog.text
        assert "DEEPSEEK_API_KEY" in caplog.text  # 名字可见，值不可见


class TestResolutionContract:
    def test_unknown_name_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="Unknown secret name"):
            get_secret("DEEPSEEK_SECRET_SAUCE", settings=_settings())

    def test_case_insensitive_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _install_keyring(monkeypatch, _StubKeyring({KEY_ENV: FROM_KEYRING}))
        settings = _settings(keyring_enabled=True)
        assert get_secret("DEEPSEEK_API_KEY", settings=settings) == FROM_KEYRING
        assert get_secret("DeepSeek_Api_Key", settings=settings) == FROM_KEYRING
        assert [call for call in stub.calls] == [(keyring_store.KEYRING_SERVICE, KEY_ENV)] * 2

    def test_settings_secret_is_the_single_convergence_point(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_keyring(monkeypatch, _StubKeyring({KEY_ENV: FROM_KEYRING}))
        settings = _settings(keyring_enabled=True, deepseek_api_key=FROM_ENV)
        assert settings.secret(KEY) == FROM_KEYRING


class TestProviderAssembly:
    def test_assembly_uses_keyring_backed_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境里没有 key、keyring 里有 ⇒ 装配成功（证明装配走同一收敛点）。"""
        _install_keyring(monkeypatch, _StubKeyring({KEY_ENV: FROM_KEYRING}))
        provider = _build_provider(_settings(keyring_enabled=True), None)
        assert provider._client.api_key == FROM_KEYRING  # type: ignore[attr-defined]

    def test_assembly_still_fails_without_any_credential(self) -> None:
        with pytest.raises(ProviderConfigError, match="No API key configured"):
            _build_provider(_settings(keyring_enabled=True), None)

    def test_duck_typed_settings_handle_falls_back_to_field(self) -> None:
        """装配层不 import 配置面：无 ``secret()`` 方法的句柄直接读同名字段。"""

        class _Handle:
            deepseek_api_key = FROM_ENV
            deepseek_base_url = None
            deepseek_model = "deepseek-v4-pro"
            ollama_enabled = False
            ollama_model = None
            ollama_base_url = None
            ollama_api_key = None
            anthropic_api_key = None
            anthropic_api_keys = ""
            openai_responses_api_key = None
            kimi_api_key = None
            glm_api_key = None
            active_provider = None
            routing_pools = ""
            routing_reasoning_continuity = False
            max_output_tokens = 4096
            anthropic_prompt_caching = True

            @property
            def anthropic_key_pool(self) -> list[str]:
                return []

            @property
            def routing_pool_map(self) -> dict[str, Any]:
                return {}

        provider = _build_provider(_Handle(), None)  # type: ignore[arg-type]
        assert provider._client.api_key == FROM_ENV  # type: ignore[attr-defined]
