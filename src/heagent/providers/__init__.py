"""HeAgent provider abstraction layer.

导出面走 PEP 562 懒加载：模块级 ``__getattr__`` 在**首次取用**某个符号时才导入对应子模块，
因此 ``import heagent`` / ``import heagent.providers`` 不再顺带拉起 provider 实现与其 SDK 依赖。
``from heagent.providers import OpenAIProvider`` 等调用点行为不变。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from heagent.providers.anthropic import AnthropicProvider
    from heagent.providers.base import BaseProvider, ProviderMetadata
    from heagent.providers.chain import ProviderChain
    from heagent.providers.openai import OpenAIProvider
    from heagent.providers.router import HeuristicRouter, RouteDecision, Router, RoutingProvider
    from heagent.providers.switchable import SwitchableProvider

__all__ = [
    "AnthropicProvider",
    "BaseProvider",
    "HeuristicRouter",
    "OpenAIProvider",
    "ProviderChain",
    "ProviderMetadata",
    "RouteDecision",
    "Router",
    "RoutingProvider",
    "SwitchableProvider",
]

# 符号名 → 定义它的子模块（懒导入的唯一路由表，与 ``__all__`` 一一对应）。
_EXPORTS: dict[str, str] = {
    "AnthropicProvider": "heagent.providers.anthropic",
    "BaseProvider": "heagent.providers.base",
    "HeuristicRouter": "heagent.providers.router",
    "OpenAIProvider": "heagent.providers.openai",
    "ProviderChain": "heagent.providers.chain",
    "ProviderMetadata": "heagent.providers.base",
    "RouteDecision": "heagent.providers.router",
    "Router": "heagent.providers.router",
    "RoutingProvider": "heagent.providers.router",
    "SwitchableProvider": "heagent.providers.switchable",
}


def __getattr__(name: str) -> Any:
    """按需导入并缓存导出符号（取用后写回模块 ``globals()``，后续访问不再走本函数）。"""
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value
