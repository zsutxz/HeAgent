"""HeAgent CLI — 交互式和单次执行的命令行入口。

使用方式：
  python -m heagent "你的问题"     # 单次模式：执行后输出答案并退出
  python -m heagent                 # 交互模式：进入 REPL 聊天循环

Provider 自动检测顺序：DEEPSEEK_API_KEY → OPENAI_API_KEY → ANTHROPIC_API_KEY
"""

from __future__ import annotations

import asyncio
import logging
import os
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
from heagent.cron.jobs import JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.exceptions import BudgetExceeded, HeAgentError
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.memory.soul import SoulStore
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.chain import ProviderChain
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.openai import OpenAIProvider
from heagent.tools.builtins.subagent import configure_subagent_tools

if TYPE_CHECKING:
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)


def _print_usage(usage: object | None) -> None:
    """在回答后显示 token 消耗统计。"""
    if usage is None or not hasattr(usage, "total_tokens") or usage.total_tokens == 0:
        return
    click.echo(
        f"  [tokens: {usage.prompt_tokens} in + "
        f"{usage.completion_tokens} out = "
        f"{usage.total_tokens} total]",
        err=True,
    )


def _build_provider(settings, model: str) -> BaseProvider:
    """根据可用的 API Key 自动检测并构建 Provider。

    优先级：DeepSeek > OpenAI > Anthropic。
    多个 Key 同时存在时，用 ProviderChain 包装实现自动回退。
    单 Provider 多 Key 时，用 KeyRotatingProvider 实现密钥轮换。
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

    # OpenAI（支持多密钥池轮换）
    openai_providers = _build_openai_providers(settings, model)
    if openai_providers:
        providers.append(openai_providers)

    # Anthropic（支持多密钥池轮换）
    anthropic_providers = _build_anthropic_providers(settings, model)
    if anthropic_providers:
        providers.append(anthropic_providers)

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


def _build_openai_providers(settings, model: str) -> BaseProvider | None:
    """构建 OpenAI Provider（含密钥池轮换）。"""
    # 主 key + 密钥池合并
    keys: list[str] = []
    if settings.openai_api_key:
        keys.append(settings.openai_api_key)
    for k in settings.openai_key_pool:
        if k not in keys:
            keys.append(k)

    if not keys:
        return None

    provider_list = [
        OpenAIProvider(api_key=k, model=model, base_url=settings.openai_base_url)
        for k in keys
    ]
    if len(provider_list) == 1:
        return provider_list[0]
    return KeyRotatingProvider(provider_list)


def _build_anthropic_providers(settings, model: str) -> BaseProvider | None:
    """构建 Anthropic Provider（含密钥池轮换）。"""
    keys: list[str] = []
    if settings.anthropic_api_key:
        keys.append(settings.anthropic_api_key)
    for k in settings.anthropic_key_pool:
        if k not in keys:
            keys.append(k)

    if not keys:
        return None

    provider_list = [
        AnthropicProvider(
            api_key=k,
            model=model,
            base_url=settings.anthropic_base_url,
            prompt_caching=settings.anthropic_prompt_caching,
        )
        for k in keys
    ]
    if len(provider_list) == 1:
        return provider_list[0]
    return KeyRotatingProvider(provider_list)


def _build_soul(soul_path: str | None = None) -> SoulStore | None:
    """构建 SoulStore。指定路径时使用该路径，否则使用默认两级路径。"""
    if soul_path:
        return SoulStore(global_path=soul_path, project_path=soul_path)
    return SoulStore()


async def _run_single(
    prompt: str,
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
    soul_path: str | None = None,
) -> None:
    """单次模式：执行一个 prompt 并打印结果。"""
    settings = get_settings()

    # 初始化模块
    skills = SkillStore()
    facts = FactStore()
    profile = ProfileStore()
    soul = _build_soul(soul_path)
    cron_store = JobStore() if settings.cron_enabled else None
    compressor = ContextCompressor(provider, threshold=settings.compression_threshold)
    retry_mw = make_retry_middleware(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )

    configure_subagent_tools(provider)

    loop = AgentLoop(
        provider,
        max_iterations=max_iterations,
        middlewares=[retry_mw],
        skills=skills,
        facts=facts,
        profile=profile,
        compressor=compressor,
        context_dir=os.getcwd(),
        soul=soul,
        cron_store=cron_store,
    )
    result = await loop.run(prompt, system=system)
    click.echo(result)
    _print_usage(loop.last_usage)


async def _run_chat(
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
    soul_path: str | None = None,
) -> None:
    """交互模式：REPL 聊天循环，直到用户输入空行或 Ctrl+C。"""
    settings = get_settings()
    session_id = uuid.uuid4().hex[:8]  # 每次交互会话一个固定 ID

    # 初始化模块
    skills = SkillStore()
    facts = FactStore()
    profile = ProfileStore()
    soul = _build_soul(soul_path)
    session = SessionStore()
    cron_store = JobStore() if settings.cron_enabled else None
    compressor = ContextCompressor(provider, threshold=settings.compression_threshold)
    retry_mw = make_retry_middleware(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )

    # Cron 调度器（交互模式专用）
    scheduler: CronScheduler | None = None
    if settings.cron_enabled and cron_store:
        scheduler = CronScheduler(
            cron_store, provider,
            tick_seconds=settings.cron_tick_seconds,
            skills=skills, facts=facts, profile=profile,
            compressor=compressor, soul=soul, cron_store=cron_store,
        )

    configure_subagent_tools(provider)

    loop = AgentLoop(
        provider,
        max_iterations=max_iterations,
        middlewares=[retry_mw],
        skills=skills,
        facts=facts,
        profile=profile,
        session=session,
        compressor=compressor,
        context_dir=os.getcwd(),
        soul=soul,
        cron_store=cron_store,
    )
    click.echo(f"HeAgent interactive mode (session: {session_id}). Type your message, or press Enter to exit.")

    try:
        if scheduler:
            await scheduler.start()
        while True:
            try:
                user_input = input("> ")
            except (KeyboardInterrupt, EOFError):
                click.echo("\nBye!")
                break

            if not user_input.strip():
                break

            try:
                final_answer = ""
                async for event in loop.run_stream(user_input, system=system, session_id=session_id):
                    if event.type == "text":
                        click.echo(event.text, nl=False)
                    elif event.type == "tool_call":
                        click.echo(f"\n[calling {event.tool_name}...]", nl=False)
                    elif event.type == "tool_result":
                        click.echo(f" [done]", nl=False)
                    elif event.type == "done":
                        final_answer = event.final_answer
                click.echo("\n")
                _print_usage(loop.last_usage)
            except BudgetExceeded as e:
                click.echo(f"[budget exceeded] {e.message}", err=True)
            except HeAgentError as e:
                click.echo(f"[error] {e.message}", err=True)
    finally:
        if scheduler:
            await scheduler.stop()


@click.command()
@click.argument("prompt", required=False)
@click.option("--model", default=None, help="Model name (default: from settings or gpt-4o)")
@click.option("--system", default=None, help="System prompt")
@click.option("--max-iterations", type=int, default=None, help="Max agent loop iterations")
@click.option("--soul", default=None, help="Path to custom SOUL.md personality file")
def main(prompt: str | None, model: str | None, system: str | None, max_iterations: int | None, soul: str | None) -> None:
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
        asyncio.run(_run_single(prompt, provider, system, resolved_iterations, soul_path=soul))
    else:
        asyncio.run(_run_chat(provider, system, resolved_iterations, soul_path=soul))
