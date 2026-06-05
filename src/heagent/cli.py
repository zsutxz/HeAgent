"""HeAgent CLI — 交互式和单次执行的命令行入口。

使用方式：
  python -m heagent "你的问题"     # 单次模式：执行后输出答案并退出
  python -m heagent                 # 交互模式：进入 REPL 聊天循环

Provider 自动检测顺序：DEEPSEEK_API_KEY → OPENAI_API_KEY → ANTHROPIC_API_KEY
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from typing import TYPE_CHECKING

import click

import heagent.tools.builtins  # noqa: F401 — 导入即触发 @tool 注册
from heagent.agent.loop import AgentLoop
from heagent.agent.middleware import make_retry_middleware
from heagent.config import get_settings
from heagent.context.compressor import ContextCompressor
from heagent.context.session import SessionStore
from heagent.exceptions import BudgetExceeded, HeAgentError
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.chain import ProviderChain
from heagent.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)


def _build_provider(settings, model: str) -> BaseProvider:
    """根据可用的 API Key 自动检测并构建 Provider。

    优先级：DeepSeek > OpenAI > Anthropic。
    多个 Key 同时存在时，用 ProviderChain 包装实现自动回退。
    """
    providers: list[BaseProvider] = []

    # DeepSeek（优先检测，使用 OpenAI 兼容接口）
    if settings.deepseek_api_key:
        providers.append(
            OpenAIProvider(
                api_key=settings.deepseek_api_key,
                model=model,
                base_url=settings.deepseek_base_url or "https://api.deepseek.com/v1",
            )
        )

    # OpenAI
    if settings.openai_api_key:
        providers.append(
            OpenAIProvider(api_key=settings.openai_api_key, model=model, base_url=settings.openai_base_url)
        )

    # Anthropic
    if settings.anthropic_api_key:
        providers.append(
            AnthropicProvider(api_key=settings.anthropic_api_key, model=model, base_url=settings.anthropic_base_url)
        )

    # 无可用 Key → 报错退出
    if not providers:
        click.echo(
            "Error: No API key configured. "
            "Set DEEPSEEK_API_KEY, OPENAI_API_KEY or ANTHROPIC_API_KEY in environment.",
            err=True,
        )
        raise SystemExit(1)

    # 单个 Provider 直接返回，多个用 Chain 包装
    if len(providers) == 1:
        return providers[0]

    return ProviderChain(providers)


async def _run_single(
    prompt: str,
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
) -> None:
    """单次模式：执行一个 prompt 并打印结果。"""
    settings = get_settings()

    # 初始化模块
    skills = SkillStore()
    facts = FactStore()
    profile = ProfileStore()
    compressor = ContextCompressor(provider, threshold=settings.compression_threshold)
    retry_mw = make_retry_middleware(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )

    loop = AgentLoop(
        provider,
        max_iterations=max_iterations,
        middlewares=[retry_mw],
        skills=skills,
        facts=facts,
        profile=profile,
        compressor=compressor,
    )
    result = await loop.run(prompt, system=system)
    click.echo(result)


async def _run_chat(
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
) -> None:
    """交互模式：REPL 聊天循环，直到用户输入空行或 Ctrl+C。"""
    settings = get_settings()
    session_id = uuid.uuid4().hex[:8]  # 每次交互会话一个固定 ID

    # 初始化模块
    skills = SkillStore()
    facts = FactStore()
    profile = ProfileStore()
    session = SessionStore()
    compressor = ContextCompressor(provider, threshold=settings.compression_threshold)
    retry_mw = make_retry_middleware(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )

    loop = AgentLoop(
        provider,
        max_iterations=max_iterations,
        middlewares=[retry_mw],
        skills=skills,
        facts=facts,
        profile=profile,
        session=session,
        compressor=compressor,
    )
    click.echo(f"HeAgent interactive mode (session: {session_id}). Type your message, or press Enter to exit.")

    while True:
        try:
            user_input = input("> ")
        except (KeyboardInterrupt, EOFError):
            click.echo("\nBye!")
            break

        if not user_input.strip():
            break

        try:
            result = await loop.run(user_input, system=system, session_id=session_id)
            click.echo(f"\n{result}\n")
        except BudgetExceeded as e:
            click.echo(f"[budget exceeded] {e.message}", err=True)
        except HeAgentError as e:
            click.echo(f"[error] {e.message}", err=True)


@click.command()
@click.argument("prompt", required=False)
@click.option("--model", default=None, help="Model name (default: from settings or gpt-4o)")
@click.option("--system", default=None, help="System prompt")
@click.option("--max-iterations", type=int, default=None, help="Max agent loop iterations")
def main(prompt: str | None, model: str | None, system: str | None, max_iterations: int | None) -> None:
    """HeAgent — self-improving AI agent.

    Run with a PROMPT for single-shot mode, or without for interactive chat.
    """
    # Windows 控制台中文编码修复
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,  # 日志输出到 stderr，不干扰 stdout 的答案输出
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 屏蔽 httpx 请求日志

    settings = get_settings()
    resolved_model = model or settings.default_model
    resolved_iterations = max_iterations or settings.max_iterations

    provider = _build_provider(settings, resolved_model)

    # 根据 prompt 参数决定运行模式
    if prompt:
        asyncio.run(_run_single(prompt, provider, system, resolved_iterations))
    else:
        asyncio.run(_run_chat(provider, system, resolved_iterations))
