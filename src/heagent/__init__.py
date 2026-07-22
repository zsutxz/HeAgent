"""HeAgent - A self-improving AI Agent core framework."""

__version__ = "0.3.0"

from heagent.agent.loop import AgentLoop as Agent
from heagent.config import Settings, get_settings
from heagent.engine import EngineContainer
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.chain import ProviderChain
from heagent.providers.openai import OpenAIProvider
from heagent.tools.decorator import tool

__all__ = [
    "Agent",
    "AnthropicProvider",
    "EngineContainer",
    "OpenAIProvider",
    "ProviderChain",
    "Settings",
    "get_settings",
    "tool",
]
