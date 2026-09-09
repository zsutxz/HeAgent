"""Tests for CLI provider construction: smart routing composes inside the multi-provider pool.

核心回归：``ROUTING_ENABLED=true`` 时 DeepSeek 条目应为 ``RoutingProvider``（flash/pro 按
问题难度自动切换），并**照常放入 ``SwitchableProvider`` 池**——不影响「Multiple providers
Choose」（启动选择 + ``/model`` 切换 + 自动回退）。只有 deepseek 一个 provider 时直接返回
路由池（等价旧行为）。
"""

from __future__ import annotations

import pytest

from heagent.cli import _build_provider, _extract_routing
from heagent.config import Settings, reset_settings
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.openai import OpenAIProvider
from heagent.providers.responses import OpenAIResponsesProvider
from heagent.providers.router import RoutingProvider
from heagent.providers.switchable import SwitchableProvider


def _clear_all_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_RESPONSES_API_KEY",
        "ANTHROPIC_API_KEY",
        "KIMI_API_KEY",
        "GLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Clear API-key env + .env pollution; reset Settings singleton."""
    _clear_all_api_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    reset_settings()
    yield
    reset_settings()


class TestBuildProviderRoutingComposition:
    """ROUTING_ENABLED=true 与 Multiple providers Choose 的组合语义。"""

    def test_routing_only_deepseek_returns_routing_provider(self, hermetic) -> None:
        """只有 deepseek 且开启路由 → 直接返回 RoutingProvider（等价旧行为）。"""
        provider = _build_provider(Settings(deepseek_api_key="sk-test", routing_enabled=True), None)
        assert isinstance(provider, RoutingProvider)
        assert set(provider.names) == {"fast", "pro"}
        assert provider.get_metadata().model == "fast:deepseek-v4-flash, pro:deepseek-v4-pro"

    def test_routing_plus_kimi_returns_switchable_with_routing_deepseek(self, hermetic) -> None:
        """路由 + 第二个 provider → SwitchableProvider，deepseek 条目为 RoutingProvider。"""
        provider = _build_provider(
            Settings(deepseek_api_key="sk-ds", kimi_api_key="sk-kimi", routing_enabled=True),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        assert set(provider.names) == {"deepseek", "kimi"}
        deepseek_entry = provider.providers["deepseek"]
        assert isinstance(deepseek_entry, RoutingProvider)
        # 默认 active=deepseek → 路由当前生效
        assert isinstance(provider.current, RoutingProvider)
        # /model 列表展示：deepseek 条目展示 fast/pro 两个模型
        summary = provider.info()["deepseek"]
        assert "deepseek-v4-flash" in summary.model
        assert "deepseek-v4-pro" in summary.model

    def test_routing_enabled_without_deepseek_key_degrades_gracefully(self, hermetic) -> None:
        """路由开启但无 deepseek 密钥 → 优雅降级：其余 provider 照常可用（不阻断 Choose）。"""
        provider = _build_provider(Settings(kimi_api_key="sk-kimi", routing_enabled=True), None)
        # 不再 SystemExit；kimi 直接可用
        assert isinstance(provider, OpenAIProvider)

    def test_routing_disabled_deepseek_is_plain_openai(self, hermetic) -> None:
        """未开启路由 → deepseek 条目为普通 OpenAIProvider（Multiple providers Choose 原样）。"""
        provider = _build_provider(
            Settings(deepseek_api_key="sk-test", kimi_api_key="sk-kimi"),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        assert isinstance(provider.providers["deepseek"], OpenAIProvider)


class TestBuildProviderGlm:
    """GLM（智谱）条目构建：OpenAI 兼容端点，照 kimi 模式入池。"""

    def test_glm_only_returns_plain_openai_provider(self, hermetic) -> None:
        provider = _build_provider(Settings(glm_api_key="sk-glm"), None)
        assert isinstance(provider, OpenAIProvider)
        assert provider.get_metadata().model == "glm-5.3"

    def test_glm_with_kimi_returns_switchable(self, hermetic) -> None:
        provider = _build_provider(Settings(kimi_api_key="sk-kimi", glm_api_key="sk-glm"), None)
        assert isinstance(provider, SwitchableProvider)
        assert set(provider.names) == {"kimi", "glm"}
        glm_meta = provider.providers["glm"].get_metadata()
        assert glm_meta.model == "glm-5.3"

    def test_model_flag_overrides_glm_default(self, hermetic) -> None:
        provider = _build_provider(Settings(glm_api_key="sk-glm"), "glm-5.3-air")
        assert isinstance(provider, OpenAIProvider)
        assert provider.get_metadata().model == "glm-5.3-air"


class TestBuildProviderOllama:
    """本地 Ollama 条目：显式开关（OLLAMA_ENABLED）而非密钥存在性，OpenAI 兼容 /v1。"""

    def test_disabled_excluded_from_pool(self, hermetic) -> None:
        """默认关闭：即使配了 OLLAMA_MODEL 也不入池（不静默连 localhost）。"""
        provider = _build_provider(
            Settings(kimi_api_key="sk-kimi", ollama_enabled=False, ollama_model="qwen3:8b"),
            None,
        )
        assert isinstance(provider, OpenAIProvider)
        assert provider.get_metadata().model == "kimi-k3"

    def test_enabled_builds_openai_compatible_provider(self, hermetic) -> None:
        provider = _build_provider(
            Settings(ollama_enabled=True, ollama_model="qwen3.5-9b-local:latest"),
            None,
        )
        assert isinstance(provider, OpenAIProvider)
        assert provider.get_metadata().model == "qwen3.5-9b-local:latest"
        assert str(provider._client.base_url).startswith("http://127.0.0.1:11434")

    def test_enabled_without_model_fails_fast(self, hermetic, capsys) -> None:
        """OLLAMA_ENABLED=true 但未配模型 → fail-fast（不猜模型名）。"""
        with pytest.raises(SystemExit):
            _build_provider(Settings(ollama_enabled=True), None)
        assert "OLLAMA_MODEL" in capsys.readouterr().err

    def test_custom_base_url(self, hermetic) -> None:
        provider = _build_provider(
            Settings(
                ollama_enabled=True,
                ollama_model="qwen3:8b",
                ollama_base_url="http://192.168.1.9:11434/v1",
            ),
            None,
        )
        assert isinstance(provider, OpenAIProvider)
        assert str(provider._client.base_url).startswith("http://192.168.1.9:11434")

    def test_ollama_with_cloud_provider_returns_switchable(self, hermetic) -> None:
        provider = _build_provider(
            Settings(kimi_api_key="sk-kimi", ollama_enabled=True, ollama_model="qwen3:8b"),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        assert set(provider.names) == {"kimi", "ollama"}
        assert provider.providers["ollama"].get_metadata().model == "qwen3:8b"

    def test_model_flag_overrides_ollama_default(self, hermetic) -> None:
        provider = _build_provider(Settings(ollama_enabled=True, ollama_model="qwen3:8b"), "qwen3:4b")
        assert isinstance(provider, OpenAIProvider)
        assert provider.get_metadata().model == "qwen3:4b"

    def test_active_provider_selects_ollama(self, hermetic) -> None:
        provider = _build_provider(
            Settings(
                kimi_api_key="sk-kimi",
                ollama_enabled=True,
                ollama_model="qwen3:8b",
                active_provider="ollama",
            ),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        assert provider.active == "ollama"


class TestBuildProviderMaxOutputTokens:
    """Settings.max_output_tokens 透传到各 provider 的输出上限。"""

    def test_wired_to_openai_compat(self, hermetic) -> None:
        provider = _build_provider(Settings(kimi_api_key="sk-kimi", max_output_tokens=1234), None)
        assert isinstance(provider, OpenAIProvider)
        assert provider._max_tokens == 1234

    def test_defaults_to_no_cap(self, hermetic) -> None:
        provider = _build_provider(Settings(kimi_api_key="sk-kimi"), None)
        assert provider._max_tokens is None

    def test_wired_to_ollama(self, hermetic) -> None:
        provider = _build_provider(
            Settings(ollama_enabled=True, ollama_model="qwen3:8b", max_output_tokens=2048),
            None,
        )
        assert isinstance(provider, OpenAIProvider)
        assert provider._max_tokens == 2048

    def test_wired_to_responses(self, hermetic) -> None:
        provider = _build_provider(
            Settings(openai_responses_api_key="sk-gpt", max_output_tokens=777),
            None,
        )
        assert isinstance(provider, OpenAIResponsesProvider)
        assert provider._max_output_tokens == 777

    def test_wired_to_anthropic(self, hermetic) -> None:
        provider = _build_provider(
            Settings(anthropic_api_key="sk-ant", max_output_tokens=999),
            None,
        )
        assert isinstance(provider, AnthropicProvider)
        assert provider._max_tokens == 999


class TestExtractRouting:
    """/route 命令解包：支持 SwitchableProvider 嵌套。"""

    def test_direct_routing(self, hermetic) -> None:
        provider = _build_provider(Settings(deepseek_api_key="sk-test", routing_enabled=True), None)
        routing, hint = _extract_routing(provider)
        assert routing is provider
        assert hint is None

    def test_switchable_active_routing(self, hermetic) -> None:
        provider = _build_provider(
            Settings(deepseek_api_key="sk-ds", kimi_api_key="sk-kimi", routing_enabled=True),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        routing, hint = _extract_routing(provider)
        assert isinstance(routing, RoutingProvider)
        assert hint is None

    def test_switchable_active_not_routing_gives_hint(self, hermetic) -> None:
        """当前活跃 provider 非路由、池内另有路由 → 提示 /model 切回。"""
        provider = _build_provider(
            Settings(deepseek_api_key="sk-ds", kimi_api_key="sk-kimi", routing_enabled=True),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        plain = OpenAIProvider(api_key="sk-kimi", model="moonshot-v1-8k", base_url="https://api.moonshot.cn/v1")
        sp = SwitchableProvider(
            {"deepseek": provider.providers["deepseek"], "kimi": plain},
            default="kimi",
        )
        routing, hint = _extract_routing(sp)
        assert routing is None
        assert hint is not None
        assert "/model deepseek" in hint

    def test_no_routing_anywhere(self, hermetic) -> None:
        provider = _build_provider(Settings(kimi_api_key="sk-kimi"), None)
        routing, hint = _extract_routing(provider)
        assert routing is None
        assert hint is None


class TestSwitchableAccessors:
    """SwitchableProvider.current / .providers 只读访问器（供 /route 解包）。"""

    def test_current_and_providers_view(self) -> None:
        a = OpenAIProvider(api_key="sk-a", model="m-a", base_url="https://api.example.com/v1")
        b = OpenAIProvider(api_key="sk-b", model="m-b", base_url="https://api.example.com/v1")
        sp = SwitchableProvider({"a": a, "b": b}, default="a")
        assert sp.current is a
        assert sp.providers == {"a": a, "b": b}
        # 副本：外部修改不影响池
        sp.providers["x"] = b  # type: ignore[assignment]
        assert "x" not in sp.names


class TestBuildProviderGpt:
    """gpt 条目构建：走 Responses API（wire_api="responses"），独立于 Chat Completions 的 openai。"""

    def test_gpt_only_returns_responses_provider(self, hermetic) -> None:
        provider = _build_provider(Settings(openai_responses_api_key="sk-gpt"), None)
        assert isinstance(provider, OpenAIResponsesProvider)
        assert provider.get_metadata().model == "gpt-5.6-terra"

    def test_gpt_with_kimi_returns_switchable(self, hermetic) -> None:
        provider = _build_provider(
            Settings(kimi_api_key="sk-kimi", openai_responses_api_key="sk-gpt"),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        assert set(provider.names) == {"kimi", "gpt"}
        assert isinstance(provider.providers["gpt"], OpenAIResponsesProvider)

    def test_model_flag_overrides_gpt_default(self, hermetic) -> None:
        provider = _build_provider(Settings(openai_responses_api_key="sk-gpt"), "gpt-5.5")
        assert isinstance(provider, OpenAIResponsesProvider)
        assert provider.get_metadata().model == "gpt-5.5"

    def test_gpt_and_openai_coexist_in_pool(self, hermetic) -> None:
        provider = _build_provider(
            Settings(openai_api_key="sk-chat", openai_responses_api_key="sk-gpt"),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        assert set(provider.names) == {"openai", "gpt"}
        assert isinstance(provider.providers["openai"], OpenAIProvider)
        assert isinstance(provider.providers["gpt"], OpenAIResponsesProvider)


class TestBuildProviderGptRouting:
    """GPT_ROUTING_ENABLED=true 时 gpt 条目为 RoutingProvider（terra/luna/sol 三档）。"""

    def test_gpt_routing_only_gpt_returns_routing_provider(self, hermetic) -> None:
        """只有 gpt 且开启 GPT 路由 → 直接返回 RoutingProvider（terra/luna/sol）。"""
        provider = _build_provider(
            Settings(openai_responses_api_key="sk-gpt", gpt_routing_enabled=True),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert set(provider.names) == {"terra", "luna", "sol"}
        assert provider.get_metadata().model == "terra:gpt-5.6-terra, luna:gpt-5.6-luna, sol:gpt-5.6-sol"

    def test_gpt_routing_plus_kimi_returns_switchable_with_routing_gpt(self, hermetic) -> None:
        """GPT 路由 + 第二个 provider → SwitchableProvider，gpt 条目为 RoutingProvider。"""
        provider = _build_provider(
            Settings(kimi_api_key="sk-kimi", openai_responses_api_key="sk-gpt", gpt_routing_enabled=True),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        assert set(provider.names) == {"kimi", "gpt"}
        gpt_entry = provider.providers["gpt"]
        assert isinstance(gpt_entry, RoutingProvider)
        # /model 列表展示：gpt 条目展示 terra/luna/sol 三个模型
        summary = provider.info()["gpt"]
        assert "gpt-5.6-terra" in summary.model
        assert "gpt-5.6-luna" in summary.model
        assert "gpt-5.6-sol" in summary.model

    def test_gpt_routing_enabled_without_key_degrades_gracefully(self, hermetic) -> None:
        """GPT 路由开启但无 Responses API 密钥 → 优雅降级：其余 provider 照常可用。"""
        provider = _build_provider(Settings(kimi_api_key="sk-kimi", gpt_routing_enabled=True), None)
        assert isinstance(provider, OpenAIProvider)

    def test_gpt_routing_disabled_gpt_is_plain_responses(self, hermetic) -> None:
        """未开启 GPT 路由 → gpt 条目为普通 OpenAIResponsesProvider。"""
        provider = _build_provider(Settings(openai_responses_api_key="sk-gpt"), None)
        assert isinstance(provider, OpenAIResponsesProvider)
