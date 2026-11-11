"""Provider 装配规则真身 —— 从 ``Settings`` 读配置 → 造 provider 栈（providers 层）。

组合根规则（~270 行）原住入口层 ``cli/wiring.py``（批次 9 卡 B，2026-11-07 迁入），自此
与 cron/loop 运行时装配按变化原因分居。本模块**零终端呈现**：致命配置错误抛
``ProviderConfigError``，呈现（``click.echo(err=True)`` + ``SystemExit(1)``）由入口层薄壳
``heagent.cli.wiring`` 完成——搬规则不搬呈现。named 插入序契约：deepseek → claude →
openai → kimi → glm → ollama；单条目直返，多条目默认 ``active_provider`` 覆盖，未配置/
未命中时**先插入者赢**——由 ``tests/test_cli_provider_build.py`` 钉住。

分层：本模块是 providers 层（共享层），不 import 入口层；``Settings`` 仅 TYPE_CHECKING
引用——``settings`` 是参数注入的配置句柄，运行期零 config 依赖。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.openai import OpenAIProvider
from heagent.providers.responses import OpenAIResponsesProvider
from heagent.providers.router import HeuristicRouter, RoutingProvider
from heagent.providers.switchable import SwitchableProvider

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.config import Settings
    from heagent.providers.base import BaseProvider
    from heagent.pub.types import RoutingPoolSpec

    # 单档 provider 构建器：(档位模型名, base_url 覆盖) → provider
    ProviderBuilder = Callable[[str, str | None], BaseProvider]

logger = logging.getLogger(__name__)


class ProviderConfigError(ValueError):
    """provider 装配的致命配置错误（规则侧）。

    呈现契约：``heagent.cli.wiring._build_provider`` 薄壳 catch 本异常后
    ``click.echo(str(exc), err=True)`` + ``SystemExit(1)``——消息文本即终端字节，
    改消息即改呈现，两侧一起改。
    """


# provider 条目的默认 base_url（未配置对应 *_BASE_URL 时使用）。
_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
_KIMI_BASE_URL = "https://api.moonshot.cn/v1"
_GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
_OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"

# 路由池声明了某条目、但该条目凭据缺失时的告警提示（键与 ROUTING_POOL_ENTRIES 对齐）。
_ENTRY_CREDENTIAL_HINTS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "kimi": "KIMI_API_KEY",
    "glm": "GLM_API_KEY",
    "ollama": "OLLAMA_ENABLED",
    "openai": "OPENAI_RESPONSES_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}


def _openai_builder(settings: Settings, *, key: str, base_url: str | None) -> ProviderBuilder:
    """单密钥 OpenAI 兼容条目的构建器（Chat Completions）：每档一个模型名。"""

    def build(tier_model: str, override: str | None) -> BaseProvider:
        return OpenAIProvider(
            api_key=key,
            model=tier_model,
            base_url=override or base_url,
            max_tokens=settings.max_output_tokens,
        )

    return build


def _responses_builder(settings: Settings, *, key: str, base_url: str | None) -> ProviderBuilder:
    """单密钥 Responses API 条目的构建器（openai 条目）：每档一个模型名。"""

    def build(tier_model: str, override: str | None) -> BaseProvider:
        return OpenAIResponsesProvider(
            api_key=key,
            model=tier_model,
            base_url=override or base_url,
            max_output_tokens=settings.max_output_tokens,
        )

    return build


def _build_entry(
    entry: str,
    spec: RoutingPoolSpec | None,
    *,
    model: str | None,
    default_model: str,
    default_base_url: str | None,
    build: ProviderBuilder,
    continuity: bool,
) -> BaseProvider:
    """构建单个 provider 条目：无池规格 → 单模型条目；有规格 → 按规格构建路由池。

    池规格来自 ``ROUTING_POOLS``（或旧版开关换算而来）：池内名、档位模型、角色映射、默认
    档、关键词、base_url 覆盖**全部由配置决定**——调整路由池无需改代码。
    """
    if spec is None:
        return build(model or default_model, default_base_url)

    if model:
        logger.warning(
            "--model %s ignored for %s: a routing pool is configured for it (use /route to force).",
            model,
            entry,
        )
    children: dict[str, BaseProvider] = {
        tier: build(tier_model, spec.base_url or default_base_url) for tier, tier_model in spec.tiers.items()
    }
    router = HeuristicRouter(
        fast=spec.fast_name,
        mid=spec.mid_name,
        pro=spec.pro_name,
        reasoning_keywords=spec.keyword_list("pro") or None,
        mid_keywords=spec.keyword_list("mid") or None,
        continuity=continuity if spec.reasoning_continuity is None else spec.reasoning_continuity,
    )
    return RoutingProvider(children, router, default=spec.default_name)


def _build_provider(settings: Settings, model: str | None) -> BaseProvider:
    """Build the best available provider from configured credentials.

    每个 provider 条目既可以是**单模型**，也可以是**声明式多档路由池**：``ROUTING_POOLS``
    （JSON）按条目名声明档位/角色/默认档/关键词，命中即把该条目构建为 ``RoutingProvider``
    （按任务难度自动切档，``/route <池内名>`` 手动钉死），并**照常放入多 provider 池**
    ——不影响「Multiple providers Choose」（启动选择 + ``/provider`` 切换 + 自动回退）。

    路由池只有这一个入口：条目出现在 ``ROUTING_POOLS`` 里即为启用该池
    （见 ``Settings.routing_pool_map``）；没有按 provider 的专用开关。

    本地 Ollama 经 ``OLLAMA_ENABLED=true`` 显式启用（OpenAI 兼容 ``/v1``、无需真实 key），
    作为独立条目入池，可经 ``/provider`` 切换、``--model`` 覆盖模型名。
    """
    named: dict[str, BaseProvider] = {}
    specs = settings.routing_pool_map
    continuity = settings.routing_reasoning_continuity

    def _entry(
        name: str,
        *,
        default_model: str,
        default_base_url: str | None,
        build: ProviderBuilder,
    ) -> None:
        """把一个 provider 条目放进池。

        ``specs`` / ``model`` / ``continuity`` 与调用形状在 6 个条目里完全相同，故就地绑定，
        只留各条目的差异（守卫、默认模型、默认 base_url、构建器）。keyword-only 是刻意的：
        ``default_model`` 与 ``default_base_url`` 极易位置传参互换（后者可为 None）。
        """
        named[name] = _build_entry(
            name,
            specs.get(name),
            model=model,
            default_model=default_model,
            default_base_url=default_base_url,
            build=build,
            continuity=continuity,
        )

    if settings.deepseek_api_key:
        url = settings.deepseek_base_url or _DEEPSEEK_BASE_URL
        build = _openai_builder(settings, key=settings.deepseek_api_key, base_url=url)
        _entry("deepseek", default_model=settings.deepseek_model, default_base_url=url, build=build)

    if settings.anthropic_api_key or settings.anthropic_key_pool:
        build = _anthropic_pool_builder(settings)
        _entry(
            "claude", default_model=settings.default_model, default_base_url=settings.anthropic_base_url, build=build
        )

    if settings.openai_responses_api_key:
        build = _responses_builder(
            settings,
            key=settings.openai_responses_api_key,
            base_url=settings.openai_responses_base_url,
        )
        _entry(
            "openai",
            default_model=settings.openai_model,
            default_base_url=settings.openai_responses_base_url,
            build=build,
        )

    if settings.kimi_api_key:
        url = settings.kimi_base_url or _KIMI_BASE_URL
        build = _openai_builder(settings, key=settings.kimi_api_key, base_url=url)
        _entry("kimi", default_model=settings.kimi_model, default_base_url=url, build=build)

    if settings.glm_api_key:
        url = settings.glm_base_url or _GLM_BASE_URL
        build = _openai_builder(settings, key=settings.glm_api_key, base_url=url)
        _entry("glm", default_model=settings.glm_model, default_base_url=url, build=build)

    if settings.ollama_enabled:
        if not settings.ollama_model:
            raise ProviderConfigError(
                "Error: OLLAMA_ENABLED=true requires OLLAMA_MODEL "
                "(e.g. OLLAMA_MODEL=qwen3:8b; list local models: curl http://127.0.0.1:11434/api/tags).",
            )
        url = settings.ollama_base_url or _OLLAMA_BASE_URL
        build = _openai_builder(settings, key=settings.ollama_api_key or "ollama", base_url=url)
        _entry("ollama", default_model=settings.ollama_model, default_base_url=url, build=build)

    for entry in specs:
        if entry not in named:
            logger.warning(
                "A routing pool is configured for %r but that provider entry is unavailable "
                "(%s not set / entry disabled); pool skipped, other providers unaffected.",
                entry,
                _ENTRY_CREDENTIAL_HINTS.get(entry, "credentials"),
            )

    if not named:
        raise ProviderConfigError(
            "Error: No API key configured. Set DEEPSEEK_API_KEY, KIMI_API_KEY, "
            "GLM_API_KEY, OPENAI_RESPONSES_API_KEY or ANTHROPIC_API_KEY "
            "in environment, or enable the local Ollama entry with OLLAMA_ENABLED=true.",
        )

    if len(named) == 1:
        return next(iter(named.values()))

    default_name = settings.active_provider or next(iter(named.keys()))
    if default_name not in named:
        logger.warning(
            "ACTIVE_PROVIDER=%s not configured (missing API key), falling back to %s",
            default_name,
            next(iter(named.keys())),
        )
        default_name = next(iter(named.keys()))
    return SwitchableProvider(named, default=default_name)


def _build_key_rotated(
    primary_key: str | None,
    pool: list[str],
    factory: Callable[[str], BaseProvider],
) -> BaseProvider | None:
    """Build one provider or a key-rotating provider pool."""
    keys: list[str] = []
    if primary_key:
        keys.append(primary_key)
    for key in pool:
        if key not in keys:
            keys.append(key)
    if not keys:
        return None
    providers = [factory(key) for key in keys]
    return providers[0] if len(providers) == 1 else KeyRotatingProvider(providers)


def _key_rotated_builder(
    primary_key: str | None,
    pool: list[str],
    make: Callable[[str, str, str | None], BaseProvider],
) -> ProviderBuilder:
    """多密钥轮换条目的构建器：同一组密钥在**每个档位**内各自轮换。

    Args:
        primary_key: 主密钥（可选）。
        pool: 备用密钥池。
        make: ``(api_key, 档位模型, base_url 覆盖) → 单档 provider``。
    """

    def build(tier_model: str, override: str | None) -> BaseProvider:
        provider = _build_key_rotated(primary_key, pool, lambda key: make(key, tier_model, override))
        if provider is None:
            # 调用点已确认存在密钥；此处仅防御内部不一致（不静默造出空 provider）
            raise ProviderConfigError("Error: provider entry requested without credentials.")
        return provider

    return build


def _anthropic_pool_builder(settings: Settings) -> ProviderBuilder:
    """claude 条目构建器（多密钥池）。"""
    return _key_rotated_builder(
        settings.anthropic_api_key,
        settings.anthropic_key_pool,
        lambda key, tier_model, url: AnthropicProvider(
            api_key=key,
            model=tier_model,
            base_url=url,
            prompt_caching=settings.anthropic_prompt_caching,
            max_tokens=settings.max_output_tokens or 4096,
        ),
    )
