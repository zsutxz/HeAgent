from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from heagent.config import GLOBAL_CONFIG_FILE, Settings, reset_settings
from typing import Any


@pytest.fixture(autouse=True)
def _clean_settings() -> Any:
    """Reset settings singleton before and after each test."""
    reset_settings()
    yield
    reset_settings()


class TestEnvLoading:
    def test_loads_deepseek_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-ds")
        s = Settings()
        assert s.deepseek_api_key == "sk-test-ds"

    def test_loads_openai_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-oai")
        s = Settings()
        assert s.openai_api_key == "sk-test-oai"

    def test_loads_anthropic_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-ant")
        s = Settings()
        assert s.anthropic_api_key == "sk-test-ant"

    def test_loads_kimi_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KIMI_API_KEY", "sk-test-kimi")
        s = Settings()
        assert s.kimi_api_key == "sk-test-kimi"

    def test_loads_active_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACTIVE_PROVIDER", "kimi")
        s = Settings()
        assert s.active_provider == "kimi"

    def test_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEFAULT_MODEL", "gpt-4-turbo")
        s = Settings()
        assert s.default_model == "gpt-4-turbo"

    def test_deepseek_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
        s = Settings()
        assert s.deepseek_model == "deepseek-v4-pro"

    def test_kimi_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KIMI_MODEL", "moonshot-v1-128k")
        s = Settings()
        assert s.kimi_model == "moonshot-v1-128k"

    def test_max_iterations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_ITERATIONS", "100")
        s = Settings()
        assert s.max_iterations == 100

    def test_compression_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPRESSION_THRESHOLD", "0.5")
        s = Settings()
        assert s.compression_threshold == 0.5

    def test_context_strategy_default(self) -> None:
        s = Settings()
        assert s.context_strategy == "compressor"

    def test_context_strategy_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTEXT_STRATEGY", "reset")
        s = Settings()
        assert s.context_strategy == "reset"

    def test_window_reset_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WINDOW_RESET_THRESHOLD", "0.7")
        s = Settings()
        assert s.window_reset_threshold == 0.7

    def test_shell_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL_TIMEOUT", "60")
        s = Settings()
        assert s.shell_timeout == 60

    def test_log_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_DIR", "/custom/logs")
        s = Settings()
        assert s.log_dir == "/custom/logs"

    def test_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        s = Settings()
        assert s.log_level == "DEBUG"

    def test_log_file_level_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_FILE_LEVEL", "DEBUG")
        s = Settings()
        assert s.log_file_level == "DEBUG"

    def test_log_file_level_default_none(self, tmp_path: Any) -> None:
        """默认 None（运行时回退到 log_level），用空 .env 避免项目 .env 干扰。"""
        s = Settings(_env_file=tmp_path / ".env")
        assert s.log_file_level is None

    def test_retry_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "5")
        monkeypatch.setenv("RETRY_BASE_DELAY", "2.0")
        monkeypatch.setenv("RETRY_MAX_DELAY", "60.0")
        s = Settings()
        assert s.retry_max_attempts == 5
        assert s.retry_base_delay == 2.0
        assert s.retry_max_delay == 60.0

    def test_mcp_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_ENABLED", "false")
        s = Settings()
        assert s.mcp_enabled is False

    def test_mcp_config_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_CONFIG_PATH", "/custom/.mcp.json")
        s = Settings()
        assert s.mcp_config_path == "/custom/.mcp.json"


# --- Precedence: system env overrides .env (standard pydantic-settings order) ---


class TestPrecedence:
    def test_system_env_overrides_dotenv(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """同 key 同时存在于 .env 与系统环境变量时，系统环境变量胜出。"""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")
        monkeypatch.setenv("OPENAI_API_KEY", "from-system")
        s = Settings(_env_file=env_file)
        assert s.openai_api_key == "from-system"

    def test_system_env_fills_gap_not_in_dotenv(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """.env 未声明的 key，由系统环境变量兜底填充。"""
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=ds-dotenv\n", encoding="utf-8")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-system")
        # 清除可能存在的环境变量，确保测试孤立
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        s = Settings(_env_file=env_file)
        assert s.deepseek_api_key == "ds-dotenv"
        assert s.anthropic_api_key == "ant-system"


# --- Multi-key parsing ---


class TestMultiKeyParsing:
    def test_comma_separated_openai_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEYS", "sk-1,sk-2,sk-3")
        s = Settings()
        assert s.openai_key_pool == ["sk-1", "sk-2", "sk-3"]

    def test_comma_separated_anthropic_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEYS", "ant-1, ant-2 , ant-3")
        s = Settings()
        assert s.anthropic_key_pool == ["ant-1", "ant-2", "ant-3"]

    def test_empty_keys_yield_empty_list(self) -> None:
        s = Settings()
        assert s.openai_key_pool == []
        assert s.anthropic_key_pool == []

    def test_single_key_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEYS", "sk-solo")
        s = Settings()
        assert s.openai_key_pool == ["sk-solo"]


class TestValidation:
    def test_threshold_above_1_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPRESSION_THRESHOLD", "1.5")
        with pytest.raises(ValidationError):
            Settings()

    def test_threshold_zero_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPRESSION_THRESHOLD", "0.0")
        s = Settings()
        assert s.compression_threshold == 0.0

    def test_threshold_one_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPRESSION_THRESHOLD", "1.0")
        s = Settings()
        assert s.compression_threshold == 1.0

    def test_negative_max_iterations_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_ITERATIONS", "-1")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_non_numeric_max_iterations_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_ITERATIONS", "abc")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_max_iterations_zero_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_ITERATIONS", "0")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_shell_timeout_zero_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL_TIMEOUT", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_retry_max_attempts_zero_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_retry_base_delay_negative_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETRY_BASE_DELAY", "-1.0")
        with pytest.raises(ValidationError):
            Settings()

    def test_retry_max_delay_negative_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETRY_MAX_DELAY", "-5.0")
        with pytest.raises(ValidationError):
            Settings()


class TestSingleton:
    def test_get_settings_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-singleton")
        from heagent.config import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        assert s1.openai_api_key == "sk-singleton"

    def test_reset_settings_creates_new_instance(self) -> None:
        from heagent.config import get_settings

        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2


class TestSandboxEnv:
    def test_default_sandbox_backend(self, tmp_path: Any) -> None:
        """默认值 passthrough（使用空 .env 避免项目 .env 干扰）。"""
        s = Settings(_env_file=tmp_path / ".env")
        assert s.sandbox_backend == "passthrough"

    def test_sandbox_backend_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_BACKEND", "firejail")
        s = Settings()
        assert s.sandbox_backend == "firejail"

    def test_firejail_path_default(self, tmp_path: Any) -> None:
        """默认值 firejail（使用空 .env 避免项目 .env 干扰）。"""
        s = Settings(_env_file=tmp_path / ".env")
        assert s.sandbox_firejail_path == "firejail"

    def test_firejail_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_FIREJAIL_PATH", "/usr/local/bin/firejail")
        s = Settings()
        assert s.sandbox_firejail_path == "/usr/local/bin/firejail"


class TestSandboxSessionWorkspaceEnv:
    """FR-1: ``sandbox_session_workspace`` 开关解析（default=False / "true" / "1" / 非法值）。"""

    def test_default_off(self, tmp_path: Any) -> None:
        """默认 False（空 .env 隔离项目配置干扰）。"""
        s = Settings(_env_file=tmp_path / ".env")
        assert s.sandbox_session_workspace is False

    def test_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        assert Settings().sandbox_session_workspace is True

    def test_env_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "1")
        assert Settings().sandbox_session_workspace is True

    def test_env_false_stays_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "false")
        assert Settings().sandbox_session_workspace is False

    def test_env_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非法值（非布尔字面量）→ pydantic 校验错误，显性失败不静默取默认。"""
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "banana")
        with pytest.raises(ValidationError):
            Settings()


class TestLedgerRetention:
    def test_default_ledger_retention_days(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认值 7（使用空 .env 避免项目 .env 干扰，并清除系统环境残留）。"""
        monkeypatch.delenv("LEDGER_RETENTION_DAYS", raising=False)
        s = Settings(_env_file=tmp_path / ".env")
        assert s.ledger_retention_days == 7

    def test_ledger_retention_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEDGER_RETENTION_DAYS", "14")
        s = Settings()
        assert s.ledger_retention_days == 14

    def test_ledger_retention_zero_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEDGER_RETENTION_DAYS", "0")
        s = Settings()
        assert s.ledger_retention_days == 0


class TestDefaults:
    def test_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEFAULT_MODEL", raising=False)
        s = Settings(_env_file=None)
        assert s.default_model == "gpt-4o"

    def test_default_max_iterations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAX_ITERATIONS", raising=False)
        s = Settings(_env_file=None)
        assert s.max_iterations == 50

    def test_default_compression_threshold(self) -> None:
        s = Settings()
        assert s.compression_threshold == 0.8

    def test_default_shell_timeout(self) -> None:
        s = Settings()
        assert s.shell_timeout == 120

    def test_default_retry_params(self) -> None:
        s = Settings()
        assert s.retry_max_attempts == 3
        assert s.retry_base_delay == 1.0
        assert s.retry_max_delay == 30.0

    def test_default_single_api_keys_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        s = Settings(_env_file=None)
        assert s.openai_api_key is None
        assert s.anthropic_api_key is None

    def test_default_api_keys_empty_str(self) -> None:
        s = Settings()
        assert s.openai_api_keys == ""
        assert s.anthropic_api_keys == ""

    def test_default_key_pools_empty(self) -> None:
        s = Settings()
        assert s.openai_key_pool == []
        assert s.anthropic_key_pool == []

    def test_default_mcp_enabled(self) -> None:
        s = Settings()
        assert s.mcp_enabled is True

    def test_default_mcp_config_path(self) -> None:
        s = Settings()
        assert s.mcp_config_path == ".mcp.json"


# --- Global config (~/.heagent/.env) ---


class TestGlobalConfig:
    """Test the ~/.heagent/.env global configuration layer via env_file sequence."""

    def test_global_config_used_when_no_project_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """全局配置作为默认值，当项目 .env 未覆盖时生效。"""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        global_env = tmp_path / "global.env"
        global_env.write_text("OPENAI_API_KEY=global-key\n", encoding="utf-8")

        project_env = tmp_path / ".env"
        project_env.write_text("", encoding="utf-8")

        s = Settings(_env_file=[str(global_env), str(project_env)])
        assert s.openai_api_key == "global-key"

    def test_project_env_overrides_global(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """项目 .env 覆盖全局配置。"""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        global_env = tmp_path / "global.env"
        global_env.write_text("OPENAI_API_KEY=global-key\n", encoding="utf-8")

        project_env = tmp_path / ".env"
        project_env.write_text("OPENAI_API_KEY=project-key\n", encoding="utf-8")

        s = Settings(_env_file=[str(global_env), str(project_env)])
        assert s.openai_api_key == "project-key"

    def test_system_env_overrides_both(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """显式环境变量优先级最高，覆盖项目 .env 和全局配置。"""
        monkeypatch.setenv("OPENAI_API_KEY", "system-key")

        global_env = tmp_path / "global.env"
        global_env.write_text("OPENAI_API_KEY=global-key\n", encoding="utf-8")

        project_env = tmp_path / ".env"
        project_env.write_text("OPENAI_API_KEY=project-key\n", encoding="utf-8")

        s = Settings(_env_file=[str(global_env), str(project_env)])
        assert s.openai_api_key == "system-key"

    def test_missing_global_file_falls_back_to_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """全局配置文件不存在时静默跳过，回退到字段默认值。"""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        nonexistent = tmp_path / "nonexistent.env"
        project_env = tmp_path / ".env"
        project_env.write_text("", encoding="utf-8")

        s = Settings(_env_file=[str(nonexistent), str(project_env)])
        assert s.openai_api_key is None

    def test_class_level_env_file_sequence(
        self,
        _isolate_dotenv_files: list[str],  # noqa: PT019 - fixture 有返回值，ruff 0.15 误报
    ) -> None:
        """``model_config.env_file`` 为 [global, project] 序列（源码契约）。

        全局层路径在模块导入时固化自 ``GLOBAL_CONFIG_FILE``；运行时 ``model_config`` 可能
        被 ``conftest`` 隔离 fixture 改写（指向 tmp），故全局层经源码常量断言、项目层经
        fixture 捕获的原始序列断言——两者解耦后互不干扰。
        """
        # 源码契约：全局层 = ~/.heagent/.env（类级声明来源，未被运行时 fixture 改）
        assert GLOBAL_CONFIG_FILE.parent.name == ".heagent"
        assert GLOBAL_CONFIG_FILE.name == ".env"

        # 项目层：源码声明为相对 ".env"
        assert isinstance(_isolate_dotenv_files, list) and len(_isolate_dotenv_files) == 2
        assert ".env" in _isolate_dotenv_files


class TestSandboxEnvAllowlist:
    """FR-3: ``sandbox_env_allowlist`` 解析（default 空 / 逗号分隔 / property set）。"""

    def test_default_empty(self, tmp_path: Any) -> None:
        s = Settings(_env_file=tmp_path / ".env")
        assert s.sandbox_env_allowlist == ""
        assert s.sandbox_env_allowlist_set == frozenset()

    def test_comma_separated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_ENV_ALLOWLIST", "GITHUB_TOKEN,CUSTOM_SECRET")
        s = Settings()
        assert s.sandbox_env_allowlist_set == frozenset({"GITHUB_TOKEN", "CUSTOM_SECRET"})

    def test_whitespace_trimmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_ENV_ALLOWLIST", " GITHUB_TOKEN , CUSTOM ")
        s = Settings()
        assert s.sandbox_env_allowlist_set == frozenset({"GITHUB_TOKEN", "CUSTOM"})
