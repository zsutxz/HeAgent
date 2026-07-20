"""Command-line entrypoint for HeAgent."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import uuid
from typing import TYPE_CHECKING, Any

import click

import heagent.tools.builtins  # noqa: F401
from heagent import __version__
from heagent.agent.loop import AgentLoop
from heagent.agent.middleware import make_retry_middleware
from heagent.config import Settings, get_settings
from heagent.context.compressor import ContextCompressor
from heagent.context.session import SessionStore
from heagent.cron.jobs import JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.engine import EngineContainer
from heagent.exceptions import BudgetExceeded, HeAgentError
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.memory.soul import SoulStore
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.chain import ProviderChain
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.openai import OpenAIProvider
from heagent.tools.mcp import MCPClientManager, load_mcp_config

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager
    from typing import Any

    from heagent.engine.context import RunContext
    from heagent.providers.base import BaseProvider
    from heagent.types import TokenUsage

logger = logging.getLogger(__name__)


def _print_banner() -> None:
    """Print the HeAgent version banner to stderr on startup."""
    click.echo(f"HeAgent v{__version__} — A self-improving AI Agent core framework", err=True)


def _print_usage(usage: TokenUsage | None) -> None:
    """Print token usage to stderr after a run."""
    if usage is None or usage.total_tokens == 0:
        return
    click.echo(
        f"  [tokens: {usage.prompt_tokens} in + {usage.completion_tokens} out = {usage.total_tokens} total]",
        err=True,
    )


def _build_provider(settings: Settings, model: str) -> BaseProvider:
    """Build the best available provider chain from configured credentials."""
    providers: list[BaseProvider] = []

    if settings.deepseek_api_key:
        providers.append(
            OpenAIProvider(
                api_key=settings.deepseek_api_key,
                model=model,
                base_url=settings.deepseek_base_url or "https://api.deepseek.com/v1",
            )
        )

    openai_provider = _build_openai_providers(settings, model)
    if openai_provider:
        providers.append(openai_provider)

    anthropic_provider = _build_anthropic_providers(settings, model)
    if anthropic_provider:
        providers.append(anthropic_provider)

    if not providers:
        click.echo(
            "Error: No API key configured. Set DEEPSEEK_API_KEY, OPENAI_API_KEY or ANTHROPIC_API_KEY in environment.",
            err=True,
        )
        raise SystemExit(1)

    return providers[0] if len(providers) == 1 else ProviderChain(providers)


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


def _build_openai_providers(settings: Settings, model: str) -> BaseProvider | None:
    """Build the OpenAI-compatible provider stack."""
    return _build_key_rotated(
        settings.openai_api_key,
        settings.openai_key_pool,
        lambda key: OpenAIProvider(api_key=key, model=model, base_url=settings.openai_base_url),
    )


def _build_anthropic_providers(settings: Settings, model: str) -> BaseProvider | None:
    """Build the Anthropic provider stack."""
    return _build_key_rotated(
        settings.anthropic_api_key,
        settings.anthropic_key_pool,
        lambda key: AnthropicProvider(
            api_key=key,
            model=model,
            base_url=settings.anthropic_base_url,
            prompt_caching=settings.anthropic_prompt_caching,
        ),
    )


def _build_soul(soul_path: str | None = None) -> SoulStore | None:
    """Build the SOUL store from an optional custom path."""
    if soul_path:
        return SoulStore(global_path=soul_path, project_path=soul_path)
    return SoulStore()


def _mcp_lifecycle(settings: Settings) -> AbstractAsyncContextManager[Any]:
    """Return the MCP lifecycle context manager based on current settings."""
    if not settings.mcp_enabled:
        logger.info("MCP disabled via settings")
        return contextlib.nullcontext()
    config = load_mcp_config(settings.mcp_config_path)
    if config.is_empty:
        return contextlib.nullcontext()
    return MCPClientManager(config)


def _build_loop(
    settings: Settings,
    provider: BaseProvider,
    max_iterations: int,
    soul_path: str | None,
    *,
    session: SessionStore | None = None,
    engine: EngineContainer | None = None,
) -> tuple[AgentLoop, CronScheduler | None]:
    """Build the loop runtime and optional cron scheduler."""
    skills = SkillStore()
    facts = FactStore()
    profile = ProfileStore()
    soul = _build_soul(soul_path)
    cron_store = JobStore() if settings.cron_enabled else None
    compressor = ContextCompressor(provider, threshold=settings.compression_threshold)
    engine = engine or EngineContainer.default(workspace_root=os.getcwd())
    retry_mw = make_retry_middleware(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )

    scheduler: CronScheduler | None = None
    if session is not None and settings.cron_enabled and cron_store:
        # C-3: cron 不再反向依赖 agent——job_runner 由本层注入，cron 仅依赖协议类型。
        async def _run_job(prompt: str, run_context: RunContext) -> None:
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
                engine=engine,
                run_context=run_context,
            )
            await loop.run(prompt)

        scheduler = CronScheduler(
            cron_store,
            provider,
            tick_seconds=settings.cron_tick_seconds,
            engine=engine,
            job_runner=_run_job,
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
        context_dir=os.getcwd(),
        soul=soul,
        cron_store=cron_store,
        engine=engine,
    )
    return loop, scheduler


async def _run_single(
    prompt: str,
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
    soul_path: str | None = None,
    mcp_ctx: AbstractAsyncContextManager[Any] | None = None,
) -> None:
    """Run a single prompt and print the result."""
    settings = get_settings()
    engine = EngineContainer.default(workspace_root=os.getcwd())

    async with mcp_ctx or contextlib.nullcontext():
        loop, _ = _build_loop(settings, provider, max_iterations, soul_path, engine=engine)
        try:
            result = await loop.run(prompt, system=system)
            click.echo(result)
            _print_usage(loop.last_usage)
        except BudgetExceeded as exc:
            click.echo(f"[budget exceeded] {exc.message}", err=True)
        except HeAgentError as exc:
            click.echo(f"[error] {exc.message}", err=True)


async def _run_chat(
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
    soul_path: str | None = None,
    mcp_ctx: AbstractAsyncContextManager[Any] | None = None,
) -> None:
    """Run interactive chat mode."""
    settings = get_settings()
    session_id = uuid.uuid4().hex[:8]
    engine = EngineContainer.default(workspace_root=os.getcwd())

    async with mcp_ctx or contextlib.nullcontext() as mcp_manager:
        session = SessionStore()
        loop, scheduler = _build_loop(settings, provider, max_iterations, soul_path, session=session, engine=engine)
        click.echo(f"HeAgent interactive mode (session: {session_id}). Type your message, or press Enter to exit.")

        try:
            if scheduler:
                await scheduler.start()
            while True:
                try:
                    user_input = await asyncio.to_thread(input, "> ")
                except (KeyboardInterrupt, EOFError):
                    click.echo("\nBye!")
                    break

                if not user_input.strip():
                    break

                # Slash command dispatch
                if user_input.startswith("/mcp-prompt"):
                    await _handle_mcp_prompt(user_input, mcp_manager)
                    continue

                try:
                    async for event in loop.run_stream(user_input, system=system, session_id=session_id):
                        if event.type == "text":
                            click.echo(event.text, nl=False)
                        elif event.type == "tool_call":
                            click.echo(f"\n[calling {event.tool_name}...]", nl=False)
                        elif event.type == "tool_result":
                            click.echo(" [done]", nl=False)
                    click.echo("\n")
                    _print_usage(loop.last_usage)
                except BudgetExceeded as exc:
                    click.echo(f"[budget exceeded] {exc.message}", err=True)
                except HeAgentError as exc:
                    click.echo(f"[error] {exc.message}", err=True)
        finally:
            if scheduler:
                await scheduler.stop()


def _format_prompt_args(args: list[dict[str, Any]]) -> str:
    """Format MCP Prompt arguments list for display."""
    if not args:
        return "(no args)"
    return " ".join(
        f"{a['name']}=..." if a.get("required") else f"{a['name']}?"
        for a in args
    )


async def _handle_mcp_prompt(user_input: str, mcp_manager: Any) -> None:
    """Handle /mcp-prompt slash command in chat mode.

    Syntax:
        /mcp-prompt                              - list all prompts from all servers
        /mcp-prompt <server>                     - list prompts from one server
        /mcp-prompt <server> <name> [k=v ...]    - render a prompt with optional arguments
    """
    if mcp_manager is None or not hasattr(mcp_manager, "list_prompts"):
        click.echo("[mcp] No MCP server connected.", err=True)
        return

    parts = user_input.split()

    if len(parts) == 1:
        result = await mcp_manager.list_prompts()
        data = json.loads(result)
        if not data:
            click.echo("[mcp-prompt] No prompts available.")
            return
        for p in data:
            server = p["server"]
            name = p["name"]
            desc = p.get("description", "")
            arg_str = _format_prompt_args(p.get("arguments", []))
            click.echo(f"  [{server}] {name}: {desc} ({arg_str})")
        return

    if len(parts) == 2:
        server = parts[1]
        result = await mcp_manager.list_prompts(server)
        data = json.loads(result)
        if not data:
            click.echo(f"[mcp-prompt] No prompts on server '{server}'.")
            return
        for p in data:
            name = p["name"]
            desc = p.get("description", "")
            arg_str = _format_prompt_args(p.get("arguments", []))
            click.echo(f"  {name}: {desc} ({arg_str})")
        return

    # len(parts) >= 3: render a prompt
    server = parts[1]
    prompt_name = parts[2]
    arguments: dict[str, str] = {}
    for arg in parts[3:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            arguments[k] = v
    try:
        text = await mcp_manager.get_prompt(server, prompt_name, arguments or None)
        guarded = _guard_mcp_content(text)
        click.echo(guarded)
    except Exception as exc:
        click.echo(f"[mcp-prompt error] {exc}", err=True)


def _guard_mcp_content(text: str) -> str:
    """Apply heuristic injection guard to MCP prompt output (non-bridge path, CLI only)."""
    from heagent.tools.mcp.mapping import guard_content  # noqa: PLC0415 - inline import for CLI-only
    return guard_content(text)


@click.command()
@click.argument("prompt", required=False)
@click.option("--model", default=None, help="Model name (default: from settings or gpt-4o)")
@click.option("--system", default=None, help="System prompt")
@click.option("--max-iterations", type=int, default=None, help="Max agent loop iterations")
@click.option("--soul", default=None, help="Path to custom SOUL.md personality file")
def main(
    prompt: str | None,
    model: str | None,
    system: str | None,
    max_iterations: int | None,
    soul: str | None,
) -> None:
    """Run HeAgent in single-shot or interactive mode."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Display version banner on every startup
    _print_banner()

    settings = get_settings()
    resolved_model = model or settings.default_model
    resolved_iterations = max_iterations or settings.max_iterations
    provider = _build_provider(settings, resolved_model)

    try:
        mcp_ctx = _mcp_lifecycle(settings)
    except HeAgentError as exc:
        click.echo(f"[mcp config error] {exc.message}", err=True)
        raise SystemExit(1) from None

    if prompt:
        asyncio.run(_run_single(prompt, provider, system, resolved_iterations, soul_path=soul, mcp_ctx=mcp_ctx))
    else:
        asyncio.run(_run_chat(provider, system, resolved_iterations, soul_path=soul, mcp_ctx=mcp_ctx))
