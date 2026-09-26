"""Tests for CLI provider construction: smart routing composes inside the multi-provider pool.

核心回归：``ROUTING_POOLS`` 声明了某条目时，该条目应为 ``RoutingProvider``（按池内档位
自动切换），并**照常放入 ``SwitchableProvider`` 池**——不影响「Multiple providers Choose」
（启动选择 + ``/model`` 切换 + 自动回退）。只有该一个 provider 时直接返回路由池。

路由池只此一个入口：没有按 provider 的专用开关（``ROUTING_ENABLED`` / ``GPT_ROUTING_ENABLED``
等已移除）——条目出现在 ``ROUTING_POOLS`` 里即为启用。
"""

from __future__ import annotations

import pytest

from heagent.cli.console import _build_provider
from heagent.cli.composition import _extract_routing
from heagent.config import Settings, reset_settings
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.openai import OpenAIProvider
from heagent.providers.responses import OpenAIResponsesProvider
from heagent.providers.router import RoutingProvider
from heagent.providers.switchable import SwitchableProvider
from heagent.pub.types import Message, Role

# 测试用池规格：deepseek 二分（池内名 fast/pro）、gpt 三档（terra/luna/sol + 显式 roles）。
_DEEPSEEK_POOL = '{"deepseek": {"tiers": {"fast": "deepseek-flash", "pro": "deepseek-v4-pro"}}}'
_GPT_POOL = (
    '{"gpt": {"tiers": {"terra": "gpt-5.6-terra", "luna": "gpt-5.6-luna", "sol": "gpt-5.6-sol"},'
    ' "roles": {"fast": "terra", "mid": "luna", "pro": "sol"}, "default": "terra"}}'
)


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
    """路由池与 Multiple providers Choose 的组合语义（deepseek 用声明式池）。"""

    def test_pool_only_deepseek_returns_routing_provider(self, hermetic) -> None:
        """只有 deepseek 且声明了池 → 直接返回 RoutingProvider。"""
        provider = _build_provider(
            Settings(deepseek_api_key="sk-test", routing_pools=_DEEPSEEK_POOL),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert set(provider.names) == {"fast", "pro"}
        assert provider.get_metadata().model == "fast:deepseek-flash, pro:deepseek-v4-pro"

    def test_pool_plus_kimi_returns_switchable_with_routing_deepseek(self, hermetic) -> None:
        """池 + 第二个 provider → SwitchableProvider，deepseek 条目为 RoutingProvider。"""
        provider = _build_provider(
            Settings(deepseek_api_key="sk-ds", kimi_api_key="sk-kimi", routing_pools=_DEEPSEEK_POOL),
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
        assert "deepseek-flash" in summary.model
        assert "deepseek-v4-pro" in summary.model

    def test_pool_without_key_degrades_gracefully(self, hermetic) -> None:
        """声明了池但无对应密钥 → 优雅降级：其余 provider 照常可用（不阻断 Choose）。"""
        provider = _build_provider(Settings(kimi_api_key="sk-kimi", routing_pools=_DEEPSEEK_POOL), None)
        # 不再 SystemExit；kimi 直接可用
        assert isinstance(provider, OpenAIProvider)

    def test_deepseek_without_pool_is_plain_openai(self, hermetic) -> None:
        """未声明池 → deepseek 条目为普通 OpenAIProvider（Multiple providers Choose 原样）。"""
        provider = _build_provider(
            Settings(deepseek_api_key="sk-test", kimi_api_key="sk-kimi"),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        assert isinstance(provider.providers["deepseek"], OpenAIProvider)


class TestBuildProviderDeclarativeRouting:
    """声明式路由池：ROUTING_POOLS 声明档位/角色/关键词，调整池无需改代码。"""

    def test_pool_declared_by_config(self, hermetic) -> None:
        """glm 条目按 JSON 规格构建为 flash/pro 池，/route 可直接驱动。"""
        provider = _build_provider(
            Settings(
                glm_api_key="sk-glm",
                routing_pools='{"glm": {"tiers": {"fast": "glm-5.3-flash", "pro": "glm-5.3"}}}',
            ),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert set(provider.names) == {"fast", "pro"}
        assert provider.get_metadata().model == "fast:glm-5.3-flash, pro:glm-5.3"
        routing, hint = _extract_routing(provider)
        assert routing is provider
        assert hint is None

    def test_pool_names_roles_default_are_config_driven(self, hermetic) -> None:
        """池内名、角色映射、默认档全部来自配置（此处三档 + 别名）。"""
        provider = _build_provider(
            Settings(
                glm_api_key="sk-glm",
                routing_pools=(
                    '{"glm": {"tiers": {"small": "glm-5.3-air", "mid": "glm-5.3", "big": "glm-5.3-max"},'
                    ' "roles": {"fast": "small", "mid": "mid", "pro": "big"}, "default": "small"}}'
                ),
            ),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert set(provider.names) == {"small", "mid", "big"}
        assert provider.get_metadata().model == "small:glm-5.3-air, mid:glm-5.3, big:glm-5.3-max"

    def test_configured_keywords_drive_pro_route(self, hermetic) -> None:
        """配置里的关键词真的参与决策：命中自定义词 → pro，否则 fast。"""
        provider = _build_provider(
            Settings(
                glm_api_key="sk-glm",
                routing_pools=(
                    '{"glm": {"tiers": {"fast": "glm-5.3-flash", "pro": "glm-5.3"},'
                    ' "keywords": {"pro": "totally-custom-token"}}}'
                ),
            ),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        messages = [Message(role=Role.USER, content="please do totally-custom-token now")]
        assert provider._router.route(messages, None).provider == "pro"
        assert provider._router.route([Message(role=Role.USER, content="hello")], None).provider == "fast"

    def test_pool_composes_into_switchable_and_model_flag_warns(self, hermetic, caplog) -> None:
        with caplog.at_level("WARNING"):
            provider = _build_provider(
                Settings(
                    kimi_api_key="sk-kimi",
                    glm_api_key="sk-glm",
                    routing_pools='{"glm": {"tiers": {"fast": "glm-5.3-flash", "pro": "glm-5.3"}}}',
                ),
                "glm-5",
            )
        assert isinstance(provider, SwitchableProvider)
        assert isinstance(provider.providers["glm"], RoutingProvider)
        assert any("ignored for glm" in record.message for record in caplog.records)

    def test_base_url_override_from_config(self, hermetic) -> None:
        provider = _build_provider(
            Settings(
                glm_api_key="sk-glm",
                routing_pools=(
                    '{"glm": {"tiers": {"fast": "a", "pro": "b"}, "base_url": "https://proxy.example.com/v1"}}'
                ),
            ),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        for name in provider.names:
            assert str(provider._providers[name]._client.base_url).startswith("https://proxy.example.com/v1")

    def test_legacy_env_switches_no_longer_create_pools(self, hermetic, monkeypatch) -> None:
        """旧版按 provider 的开关已移除：环境里还留着也不再造池（唯一入口是 ROUTING_POOLS）。"""
        monkeypatch.setenv("ROUTING_ENABLED", "true")
        monkeypatch.setenv("ROUTING_FAST_MODEL", "ds-fast")
        monkeypatch.setenv("GPT_ROUTING_ENABLED", "true")
        provider = _build_provider(Settings(deepseek_api_key="sk-ds"), None)
        assert isinstance(provider, OpenAIProvider)
        assert provider.get_metadata().model == "deepseek-v4-pro"

    def test_invalid_json_ignored_keeps_plain_entry(self, hermetic, caplog) -> None:
        with caplog.at_level("WARNING"):
            provider = _build_provider(Settings(glm_api_key="sk-glm", routing_pools="{not json"), None)
        assert isinstance(provider, OpenAIProvider)
        assert provider.get_metadata().model == "glm-5.3"
        assert any("ROUTING_POOLS" in record.message for record in caplog.records)

    def test_invalid_spec_ignored(self, hermetic, caplog) -> None:
        """roles 指向不存在的档位 → 该条忽略（告警，不阻断启动）。"""
        with caplog.at_level("WARNING"):
            provider = _build_provider(
                Settings(
                    glm_api_key="sk-glm",
                    routing_pools='{"glm": {"tiers": {"fast": "glm-5.3-flash"}, "roles": {"pro": "nope"}}}',
                ),
                None,
            )
        assert isinstance(provider, OpenAIProvider)
        assert any("ROUTING_POOLS[glm] invalid" in record.message for record in caplog.records)

    def test_unknown_entry_ignored(self, hermetic, caplog) -> None:
        with caplog.at_level("WARNING"):
            provider = _build_provider(
                Settings(kimi_api_key="sk-kimi", routing_pools='{"mistral": {"tiers": {"fast": "m-small"}}}'),
                None,
            )
        assert isinstance(provider, OpenAIProvider)
        assert any("unknown provider entry" in record.message for record in caplog.records)

    def test_pool_without_credentials_warns_and_skips(self, hermetic, caplog) -> None:
        with caplog.at_level("WARNING"):
            provider = _build_provider(
                Settings(
                    kimi_api_key="sk-kimi",
                    routing_pools='{"glm": {"tiers": {"fast": "glm-5.3-flash", "pro": "glm-5.3"}}}',
                ),
                None,
            )
        assert isinstance(provider, OpenAIProvider)  # 只剩 kimi（非路由）
        assert any("GLM_API_KEY" in record.message for record in caplog.records)

    def test_gpt_pool_from_config_uses_responses_api(self, hermetic) -> None:
        provider = _build_provider(
            Settings(
                openai_responses_api_key="sk-gpt",
                routing_pools=(
                    '{"gpt": {"tiers": {"terra": "gpt-5.6-terra", "luna": "gpt-5.6-luna", "sol": "gpt-5.6-sol"},'
                    ' "roles": {"fast": "terra", "mid": "luna", "pro": "sol"}, "default": "terra"}}'
                ),
            ),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert set(provider.names) == {"terra", "luna", "sol"}
        assert all(isinstance(child, OpenAIResponsesProvider) for child in provider._providers.values())


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
        provider = _build_provider(Settings(deepseek_api_key="sk-test", routing_pools=_DEEPSEEK_POOL), None)
        routing, hint = _extract_routing(provider)
        assert routing is provider
        assert hint is None

    def test_switchable_active_routing(self, hermetic) -> None:
        provider = _build_provider(
            Settings(deepseek_api_key="sk-ds", kimi_api_key="sk-kimi", routing_pools=_DEEPSEEK_POOL),
            None,
        )
        assert isinstance(provider, SwitchableProvider)
        routing, hint = _extract_routing(provider)
        assert isinstance(routing, RoutingProvider)
        assert hint is None

    def test_switchable_active_not_routing_gives_hint(self, hermetic) -> None:
        """当前活跃 provider 非路由、池内另有路由 → 提示 /model 切回。"""
        provider = _build_provider(
            Settings(deepseek_api_key="sk-ds", kimi_api_key="sk-kimi", routing_pools=_DEEPSEEK_POOL),
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

    def test_openai_model_setting_drives_gpt_entry(self, hermetic) -> None:
        """OPENAI_MODEL（Settings.openai_model）是 gpt 条目（Responses API）的默认模型。"""
        provider = _build_provider(
            Settings(openai_responses_api_key="sk-gpt", openai_model="gpt-5.6-sol"),
            None,
        )
        assert isinstance(provider, OpenAIResponsesProvider)
        assert provider.get_metadata().model == "gpt-5.6-sol"

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
    """声明式池：gpt 条目为 RoutingProvider（terra/luna/sol 三档，Responses API）。"""

    def test_gpt_pool_only_gpt_returns_routing_provider(self, hermetic) -> None:
        """只有 gpt 且声明了三档池 → 直接返回 RoutingProvider（terra/luna/sol）。"""
        provider = _build_provider(
            Settings(openai_responses_api_key="sk-gpt", routing_pools=_GPT_POOL),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert set(provider.names) == {"terra", "luna", "sol"}
        assert provider.get_metadata().model == "terra:gpt-5.6-terra, luna:gpt-5.6-luna, sol:gpt-5.6-sol"

    def test_gpt_pool_plus_kimi_returns_switchable_with_routing_gpt(self, hermetic) -> None:
        """gpt 三档池 + 第二个 provider → SwitchableProvider，gpt 条目为 RoutingProvider。"""
        provider = _build_provider(
            Settings(kimi_api_key="sk-kimi", openai_responses_api_key="sk-gpt", routing_pools=_GPT_POOL),
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

    def test_gpt_pool_without_key_degrades_gracefully(self, hermetic) -> None:
        """声明了三档池但无 Responses API 密钥 → 优雅降级：其余 provider 照常可用。"""
        provider = _build_provider(Settings(kimi_api_key="sk-kimi", routing_pools=_GPT_POOL), None)
        assert isinstance(provider, OpenAIProvider)

    def test_gpt_without_pool_is_plain_responses(self, hermetic) -> None:
        """未声明池 → gpt 条目为普通 OpenAIResponsesProvider。"""
        provider = _build_provider(Settings(openai_responses_api_key="sk-gpt"), None)
        assert isinstance(provider, OpenAIResponsesProvider)


class TestRoutingContinuityWiring:
    """ROUTING_REASONING_CONTINUITY 透传到 HeuristicRouter（默认 False = 尽量用 fast）。"""

    def test_pool_continuity_defaults_off(self, hermetic) -> None:
        provider = _build_provider(
            Settings(deepseek_api_key="sk-test", routing_pools=_DEEPSEEK_POOL),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert provider._router.continuity is False

    def test_global_continuity_honours_setting(self, hermetic) -> None:
        provider = _build_provider(
            Settings(
                deepseek_api_key="sk-test",
                routing_pools=_DEEPSEEK_POOL,
                routing_reasoning_continuity=True,
            ),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert provider._router.continuity is True

    def test_pool_level_continuity_overrides_global(self, hermetic) -> None:
        """池内 "reasoning_continuity" 覆盖全局开关（全局 true、池内 false）。"""
        pool = '{"deepseek": {"tiers": {"fast": "a", "pro": "b"}, "reasoning_continuity": false}}'
        provider = _build_provider(
            Settings(
                deepseek_api_key="sk-test",
                routing_pools=pool,
                routing_reasoning_continuity=True,
            ),
            None,
        )
        assert isinstance(provider, RoutingProvider)
        assert provider._router.continuity is False
