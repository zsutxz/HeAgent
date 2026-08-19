"""Command-line entrypoint for HeAgent."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

import heagent.tools.builtins  # noqa: F401
from heagent import __version__
from heagent.agent.loop import AgentLoop
from heagent.agent.middleware import make_retry_middleware
from heagent.config import GLOBAL_CONFIG_DIR, GLOBAL_CONFIG_FILE, Settings, get_settings
from heagent.context.compressor import ContextCompressor
from heagent.context.session import SessionStore
from heagent.cron.jobs import JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.engine import ConsoleApprovalHandler, EngineContainer
from heagent.exceptions import BudgetExceeded, HeAgentError
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.memory.soul import SoulStore
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.openai import OpenAIProvider
from heagent.providers.switchable import SwitchableProvider
from heagent.slash import SlashRegistry, load_custom_commands
from heagent.tools.mcp import MCPClientManager, load_mcp_config

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from heagent.engine.context import RunContext
    from heagent.providers.base import BaseProvider
    from heagent.types import TokenUsage

logger = logging.getLogger(__name__)


# =============================================================================
# Shared utilities (CLI / GUI reuse)
# =============================================================================


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


def _print_stream_event(event: Any) -> None:
    """Render one streaming event from ``AgentLoop.run_stream`` to the terminal."""
    if event.type == "text":
        click.echo(event.text, nl=False)
    elif event.type == "tool_call":
        click.echo(f"\n[calling {event.tool_name}...]", nl=False)
    elif event.type == "tool_result":
        click.echo(" [done]", nl=False)


def _format_tokens_k(n: int) -> str:
    """Format token count with K/M suffix (e.g. 1234 -> '1.2K', 128000 -> '128K', 1000000 -> '1M')."""
    if n < 1000:
        return str(n)
    if n >= 1_000_000:
        m = n / 1_000_000
        if m == int(m):
            return f"{int(m)}M"
        return f"{m:.1f}M"
    k = n / 1000
    if k == int(k):
        return f"{int(k)}K"
    return f"{k:.1f}K"


def _format_status(loop: AgentLoop) -> str:
    """Format CLI prompt prefix: model + per-call tokens / context window + compression threshold + cumulative.

    Shows per-call token usage against the model context window, the compression
    trigger threshold (compression_threshold % of max_context_tokens), and the
    cumulative tokens consumed since program start (across runs, only when > 0).
    """
    meta = loop.provider.get_metadata()
    model = meta.model
    settings = get_settings()
    max_tok = settings.max_context_tokens
    usage = loop.last_usage
    used = usage.total_tokens if usage and usage.total_tokens > 0 else 0
    cmp_pct = int(settings.compression_threshold * 100)
    parts = [
        model,
        f"{_format_tokens_k(used)}/{_format_tokens_k(max_tok)} tok",
        f"cmp@{cmp_pct}%",
    ]
    if loop.cumulative_tokens > 0:
        parts.append(f"累计: {_format_tokens_k(loop.cumulative_tokens)} tok")
    return f"[{' | '.join(parts)}]"


def _setup_logging() -> None:
    """Configure logging for CLI mode (stderr console + file)."""
    _settings = get_settings()
    _console_level = getattr(logging, _settings.log_level.upper(), logging.INFO)
    _file_level = getattr(logging, (_settings.log_file_level or _settings.log_level).upper(), _console_level)
    _log_dir = Path(_settings.log_dir)
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _log_dir / f"heagent-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    _console_handler = logging.StreamHandler(sys.stderr)
    _console_handler.setLevel(_console_level)
    _file_handler = logging.FileHandler(str(_log_file), encoding="utf-8")
    _file_handler.setLevel(_file_level)

    logging.basicConfig(
        level=min(_console_level, _file_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[_console_handler, _file_handler],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _prompt_startup_provider(provider: SwitchableProvider) -> None:
    """Prompt the user to select a provider at startup (interactive mode).

    ACTIVE_PROVIDER in .env determines the default (press Enter to accept).
    """
    if not sys.stdin.isatty():
        return

    info = provider.info()
    names = list(info.keys())

    if len(names) <= 1:
        return

    default_idx = names.index(provider.active) + 1

    click.echo("Multiple providers available. Choose one:", err=True)
    for i, name in enumerate(names, 1):
        meta = info[name]
        marker = "<- default" if i == default_idx else ""
        click.echo(f"  [{i}] {name}  ({meta.model})  {marker}", err=True)

    while True:
        try:
            raw = click.prompt("Select (number)", type=str, default=str(default_idx))
            choice = int(raw)
            if 1 <= choice <= len(names):
                await provider.switch(names[choice - 1])
                active_meta = provider.get_metadata()
                click.echo(f"  -> Using {provider.active} ({active_meta.model})", err=True)
                return
            click.echo(f"  Please enter 1-{len(names)}", err=True)
        except (ValueError, click.Abort):
            raise SystemExit(0) from None


def _build_provider(settings: Settings, model: str | None) -> BaseProvider:
    """Build the best available provider from configured credentials."""
    named: dict[str, BaseProvider] = {}

    if settings.deepseek_api_key:
        named["deepseek"] = OpenAIProvider(
            api_key=settings.deepseek_api_key,
            model=model or settings.deepseek_model,
            base_url=settings.deepseek_base_url or "https://api.deepseek.com/v1",
        )

    if settings.kimi_api_key:
        named["kimi"] = OpenAIProvider(
            api_key=settings.kimi_api_key,
            model=model or settings.kimi_model,
            base_url=settings.kimi_base_url or "https://api.moonshot.cn/v1",
        )

    openai_provider = _build_openai_providers(settings, model or settings.default_model)
    if openai_provider:
        named["openai"] = openai_provider

    anthropic_provider = _build_anthropic_providers(settings, model or settings.default_model)
    if anthropic_provider:
        named["anthropic"] = anthropic_provider

    if not named:
        click.echo(
            "Error: No API key configured. Set DEEPSEEK_API_KEY, KIMI_API_KEY, "
            "OPENAI_API_KEY or ANTHROPIC_API_KEY in environment.",
            err=True,
        )
        raise SystemExit(1)

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
    sandbox_backend: str | None = None,
    skills: SkillStore | None = None,
    facts: FactStore | None = None,
    profile: ProfileStore | None = None,
    soul: SoulStore | None = None,
) -> tuple[AgentLoop, CronScheduler | None]:
    """Build the loop runtime and optional cron scheduler.

    可选的预构建记忆存储（``skills``/``facts``/``profile``/``soul``）允许调用方与
    后台调度器（如 DreamScheduler）共享同一份存储实例；缺省时各自新建。
    """
    skills = skills or SkillStore()
    facts = facts or FactStore()
    profile = profile or ProfileStore()
    soul = soul or _build_soul(soul_path)
    cron_store = JobStore() if settings.cron_enabled else None
    compressor = ContextCompressor(provider, threshold=settings.compression_threshold)
    engine = engine or EngineContainer.default(workspace_root=os.getcwd(), sandbox_backend=sandbox_backend)
    retry_mw = make_retry_middleware(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )

    scheduler: CronScheduler | None = None
    if session is not None and settings.cron_enabled and cron_store:

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
    sandbox_backend: str | None = None,
) -> None:
    """Run a single prompt and print the result."""
    settings = get_settings()
    engine = EngineContainer.default(workspace_root=os.getcwd(), sandbox_backend=sandbox_backend)
    if sys.stdin.isatty() and engine.approval_handler is None:
        engine.approval_handler = ConsoleApprovalHandler()

    async with mcp_ctx or contextlib.nullcontext():
        loop, _ = _build_loop(
            settings, provider, max_iterations, soul_path, engine=engine, sandbox_backend=sandbox_backend
        )
        try:
            result = await loop.run(prompt, system=system)
            click.echo(result)
            _print_usage(loop.last_usage)
        except BudgetExceeded as exc:
            click.echo(f"[budget exceeded] {exc.message}", err=True)
        except HeAgentError as exc:
            click.echo(f"[error] {exc.message}", err=True)


def _build_dream_scheduler(
    settings: Settings,
    provider: BaseProvider,
    engine: EngineContainer,
    session: SessionStore,
    skills: SkillStore,
    facts: FactStore,
    profile: ProfileStore,
    soul: SoulStore | None,
) -> Any | None:
    """Construct DreamScheduler when dream_enabled (opt-in); otherwise return None.

    dreaming = 无人监督后台跑 + 联网 + 改持久记忆；PolicyEngine/role/web 围栏均非真正安全边界，
    须 OS 级沙箱兜底。``dream_enabled`` 默认 False。

    DAG 合规：dreamer SubAgent 的构造在此（cli.py 组合根）经 dream_runner 闭包注入，
    使 ``memory/dream.py`` 无需导入 ``agent/``。
    """
    if not settings.dream_enabled:
        return None
    from heagent.agent.sub import SubAgent  # noqa: PLC0415
    from heagent.engine.roles import get_role  # noqa: PLC0415
    from heagent.memory.dream import DreamResult, DreamScheduler  # noqa: PLC0415

    context_dir = os.getcwd()
    role = get_role("dreamer")
    max_iterations = settings.dream_max_iterations

    async def _dream_runner(prompt: str) -> DreamResult:  # noqa: ANN202
        agent = SubAgent(
            provider,
            skills=skills,
            facts=facts,
            profile=profile,
            soul=soul,
            context_dir=context_dir,
            engine=engine,
            role=role,
            max_iterations=max_iterations,
        )
        result = await agent.run(prompt)
        return DreamResult(
            success=result.success,
            iterations=result.iterations,
            output=result.output,
            run_id=result.run_id,
        )

    return DreamScheduler(
        _dream_runner,
        engine=engine,
        session_store=session,
        settings=settings,
    )


def _resolve_session_id(
    session: SessionStore,
    *,
    continue_session: bool = False,
    resume_session: str | None = None,
) -> str:
    """决定本次交互会话的 session_id（Epic 30）。

    - ``resume_session`` 指定时复用该 id；
    - ``continue_session`` 时复用最近一次会话 id（无历史则回退新 id 并提示）；
    - 否则新建随机 id。
    """
    if resume_session:
        return resume_session
    if continue_session:
        recent = session.recent_session_ids(1)
        if recent:
            click.echo(f"[session] Continuing most recent session: {recent[0]}", err=True)
            return recent[0]
        click.echo("[session] No prior session found; starting a new one.", err=True)
    return uuid.uuid4().hex[:8]


async def _run_chat(
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
    soul_path: str | None = None,
    mcp_ctx: AbstractAsyncContextManager[Any] | None = None,
    sandbox_backend: str | None = None,
    continue_session: bool = False,
    resume_session: str | None = None,
) -> None:
    """Run interactive chat mode."""
    settings = get_settings()
    engine = EngineContainer.default(workspace_root=os.getcwd(), sandbox_backend=sandbox_backend)
    if engine.approval_handler is None:
        engine.approval_handler = ConsoleApprovalHandler()

    async with mcp_ctx or contextlib.nullcontext() as mcp_manager:
        session = SessionStore()
        # 会话复用（Epic 30）：--resume 指定 / --continue 最近 / 否则新建。
        session_id = _resolve_session_id(session, continue_session=continue_session, resume_session=resume_session)
        # 预构建记忆存储，与 DreamScheduler 共享同一份实例（dream 回写即主 loop 可见）。
        skills = SkillStore()
        facts = FactStore()
        profile = ProfileStore()
        soul = _build_soul(soul_path)
        loop, scheduler = _build_loop(
            settings,
            provider,
            max_iterations,
            soul_path,
            session=session,
            engine=engine,
            sandbox_backend=sandbox_backend,
            skills=skills,
            facts=facts,
            profile=profile,
            soul=soul,
        )
        dream_scheduler = _build_dream_scheduler(settings, provider, engine, session, skills, facts, profile, soul)
        registry = _build_slash_registry(provider, mcp_manager, session, session_id, loop, system)
        click.echo(f"HeAgent interactive mode (session: {session_id}). Type your message, or press Enter to exit.")

        try:
            if scheduler:
                await scheduler.start()
            if dream_scheduler:
                await dream_scheduler.start()
            while True:
                try:
                    status = _format_status(loop)
                    user_input = await asyncio.to_thread(input, f"{status}\n> ")
                except (KeyboardInterrupt, EOFError):
                    click.echo("\nBye!")
                    break

                if not user_input.strip():
                    break

                if user_input.startswith("/"):
                    handled = await _handle_slash(user_input, registry)
                    if handled:
                        continue

                await _run_prompt(loop, user_input, system, session_id)
        finally:
            if dream_scheduler:
                await dream_scheduler.stop()
            if scheduler:
                await scheduler.stop()


# =============================================================================
# Slash command routing (CLI interactive mode)
# =============================================================================


async def _run_prompt(loop: AgentLoop, prompt: str, system: str | None, session_id: str) -> None:
    """把一条用户消息提交给 loop 流式执行并打印结果（自定义斜杠命令复用）。"""
    try:
        async for event in loop.run_stream(prompt, system=system, session_id=session_id):
            _print_stream_event(event)
        click.echo("\n")
        _print_usage(loop.last_usage)
    except BudgetExceeded as exc:
        click.echo(f"[budget exceeded] {exc.message}", err=True)
    except HeAgentError as exc:
        click.echo(f"[error] {exc.message}", err=True)


def _build_slash_registry(
    provider: BaseProvider,
    mcp_manager: Any,
    session: SessionStore | None,
    session_id: str,
    loop: AgentLoop,
    system: str | None,
) -> SlashRegistry:
    """构造斜杠命令注册表：内置命令 + 用户自定义命令（Epic 31）。"""
    registry = SlashRegistry()

    async def _model(args: str) -> None:
        await _handle_model_cmd(["/model", *args.split()], provider)

    async def _mcp_prompt(args: str) -> None:
        await _handle_mcp_prompt(f"/mcp-prompt {args}".strip(), mcp_manager)

    async def _clear(args: str) -> None:
        if session is not None:
            session.delete(session_id)
        click.echo("[clear] Session history cleared. Next message starts fresh.", err=True)

    async def _help(args: str) -> None:
        click.echo("Available slash commands:", err=True)
        for name in registry.names():
            click.echo(f"  /{name}  {registry.describe(name)}", err=True)

    registry.register("model", "切换 LLM 模型", _model)
    registry.register("mcp-prompt", "调度 MCP prompt", _mcp_prompt)
    registry.register("clear", "清空当前会话上下文", _clear)
    registry.register("help", "列出所有斜杠命令", _help)

    for command in load_custom_commands():
        prompt = command.prompt

        async def _custom(args: str, prompt: str = prompt) -> None:
            await _run_prompt(loop, prompt, system, session_id)

        registry.register(command.name, command.description, _custom)

    return registry


async def _handle_slash(user_input: str, registry: SlashRegistry) -> bool:
    """Route slash commands via registry; returns True if handled, False to pass through."""
    parts = user_input.split()
    cmd = parts[0].lower() if parts else ""
    if not cmd.startswith("/"):
        return False
    name = cmd[1:]
    args = " ".join(parts[1:])
    return await registry.dispatch(name, args)


async def _handle_model_cmd(parts: list[str], provider: BaseProvider) -> None:
    """Handle /model slash command for runtime LLM switching."""
    if not isinstance(provider, SwitchableProvider):
        click.echo("[model] Only one provider configured; switching not available.", err=True)
        return

    if len(parts) == 1:
        info = provider.info()
        click.echo("Available models:", err=True)
        for name, meta in info.items():
            marker = "->" if meta.active else " "
            click.echo(f"  [{marker}] {name}  ({meta.model})", err=True)
        return

    name = parts[1]
    try:
        await provider.switch(name)
        active_meta = provider.get_metadata()
        click.echo(f"[model] Switched to {name} ({active_meta.model})", err=True)
    except ValueError as exc:
        click.echo(f"[model] {exc}", err=True)


def _format_prompt_args(args: list[dict[str, Any]]) -> str:
    """Format MCP Prompt arguments list for display."""
    if not args:
        return "(no args)"
    return " ".join(f"{a['name']}=..." if a.get("required") else f"{a['name']}?" for a in args)


async def _handle_mcp_prompt(user_input: str, mcp_manager: Any) -> None:
    """Handle /mcp-prompt slash command in chat mode."""
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
    from heagent.tools.mcp.mapping import guard_content  # noqa: PLC0415

    return guard_content(text)


# =============================================================================
# Core CLI implementation (shared by run subcommand and default path)
# =============================================================================


def _run_cli_impl(
    prompt: str | None,
    model: str | None,
    system: str | None,
    max_iterations: int | None,
    soul: str | None,
    sandbox: str | None,
    continue_session: bool = False,
    resume_session: str | None = None,
) -> None:
    """Core CLI routine — logging, provider, MCP, dispatch to single/chat."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _setup_logging()
    _print_banner()

    settings = get_settings()
    resolved_iterations = max_iterations or settings.max_iterations
    provider = _build_provider(settings, model)

    # --- Sandbox warning ---
    sandbox_resolved = sandbox or settings.sandbox_backend
    if sandbox_resolved == "firejail":
        import shutil as _shutil

        if _shutil.which(settings.sandbox_firejail_path) is None:
            click.echo(
                f" WARNING: firejail not found ({settings.sandbox_firejail_path}). "
                f"Shell commands will run WITHOUT sandbox isolation. "
                f"Install firejail: sudo apt install firejail",
                err=True,
            )
        else:
            click.echo(f" firejail sandbox ENABLED ({settings.sandbox_firejail_path})", err=True)

    # --- Interactive provider selection at startup ---
    if isinstance(provider, SwitchableProvider):
        asyncio.run(_prompt_startup_provider(provider))

    try:
        mcp_ctx = _mcp_lifecycle(settings)
    except HeAgentError as exc:
        click.echo(f"[mcp config error] {exc.message}", err=True)
        raise SystemExit(1) from None

    if prompt:
        asyncio.run(
            _run_single(
                prompt,
                provider,
                system,
                resolved_iterations,
                soul_path=soul,
                mcp_ctx=mcp_ctx,
                sandbox_backend=sandbox,
            )
        )
    else:
        asyncio.run(
            _run_chat(
                provider,
                system,
                resolved_iterations,
                soul_path=soul,
                mcp_ctx=mcp_ctx,
                sandbox_backend=sandbox,
                continue_session=continue_session,
                resume_session=resume_session,
            )
        )


# =============================================================================
# Click command group (with DefaultGroup for backward-compatible "heagent msg")
# =============================================================================

_RUN_OPTIONS = [
    click.argument("prompt", required=False),
    click.option("--model", default=None, help="Model name (default: per-provider setting)"),
    click.option("--system", default=None, help="System prompt"),
    click.option("--max-iterations", type=int, default=None, help="Max agent loop iterations"),
    click.option("--soul", default=None, help="Path to custom SOUL.md personality file"),
    click.option(
        "--sandbox",
        type=click.Choice(["passthrough", "firejail"]),
        default=None,
        help="Sandbox backend for shell execution (default: from SANDBOX_BACKEND setting)",
    ),
    click.option(
        "--continue",
        "continue_session",
        is_flag=True,
        default=False,
        help="Continue the most recent session (interactive mode)",
    ),
    click.option(
        "--resume",
        "resume_session",
        default=None,
        help="Resume a specific session by id (interactive mode)",
    ),
]


def _apply_options(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: apply shared CLI options to a Click command."""
    for opt in reversed(_RUN_OPTIONS):
        fn = opt(fn)
    return fn


class DefaultGroup(click.Group):
    """A Click Group that falls back to the ``default_command`` when an unknown
    command name is provided (instead of raising ``NoSuchCommand``).

    This allows ``heagent "hello"`` to be treated as ``heagent run "hello"``
    while explicit subcommands (``gui``, ``run``) take priority.
    """

    _default_command: str | None = None

    def set_default_command(self, name: str) -> None:
        self._default_command = name

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        """已注册子命令优先；其余一律回退到默认命令 run 解析。

        ``heagent "prompt"`` 与 ``heagent --model X "prompt"`` 都依赖该回退——
        未知选项随后仍由 run 自身的解析器报错，不会静默吞掉。
        """
        if args and args[0] in self.commands:
            return super().resolve_command(ctx, args)
        default = self._default_command
        if default is not None and default in self.commands:
            return default, self.commands[default], args
        return super().resolve_command(ctx, args)


@click.command(cls=DefaultGroup, invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """HeAgent — A self-improving AI Agent core framework.

    Run without arguments for interactive chat mode, or provide a prompt
    for single-shot execution.

    \b
    Examples:
      heagent                        # interactive chat
      heagent "analyze this file"    # single-shot
      heagent run "prompt"           # explicit run subcommand
      heagent init                   # create global config in ~/.heagent
      heagent gui                    # launch terminal UI
    """
    if ctx.invoked_subcommand is None:
        # No subcommand -> interactive mode
        ctx.invoke(run, prompt=None)


@main.command("run")
@_apply_options
def run(
    prompt: str | None,
    model: str | None,
    system: str | None,
    max_iterations: int | None,
    soul: str | None,
    sandbox: str | None,
    continue_session: bool,
    resume_session: str | None,
) -> None:
    """Run HeAgent in single-shot or interactive mode."""
    _run_cli_impl(prompt, model, system, max_iterations, soul, sandbox, continue_session, resume_session)


# =============================================================================
# Init subcommand
# =============================================================================

_INIT_ENV_TEMPLATE = """# HeAgent 全局配置文件
# 存放路径：{path}
# 加载优先级：显式环境变量 > 项目 .env > 本文件 > 字段默认值
# 意即：在任意项目目录下运行 heagent 时，本文件中的配置作为默认值自动生效，
#       可在单个项目的 .env 中覆盖。

# ---- 活跃 Provider ----
# ACTIVE_PROVIDER=deepseek

# ---- API 密钥 ----
# DEEPSEEK_API_KEY=your-deepseek-key
# OPENAI_API_KEY=your-openai-key
# ANTHROPIC_API_KEY=your-anthropic-key
# KIMI_API_KEY=your-kimi-key

# ---- API 基础 URL（用于代理或自营服务）----
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
# OPENAI_BASE_URL=
# ANTHROPIC_BASE_URL=
# KIMI_BASE_URL=https://api.moonshot.cn/v1

# ---- 各 Provider 默认模型 ----
# DEFAULT_MODEL=gpt-4o
# DEEPSEEK_MODEL=deepseek-chat
# KIMI_MODEL=moonshot-v1-8k

# ---- Anthropic 提示词缓存 ----
# ANTHROPIC_PROMPT_CACHING=true

# ---- 重试策略 ----
# RETRY_MAX_ATTEMPTS=3
# RETRY_BASE_DELAY=1.0
# RETRY_MAX_DELAY=30.0

# ---- 日志 ----
# LOG_LEVEL=INFO
# LOG_FILE_LEVEL=DEBUG
# LOG_DIR=logs

# ---- 沙箱后端 ----
# SANDBOX_BACKEND=passthrough
# SANDBOX_FIREJAIL_PATH=firejail

# ---- MCP ----
# MCP_ENABLED=true
# MCP_CONFIG_PATH=.mcp.json
"""


@main.command("init")
def init_cmd() -> None:
    """初始化 HeAgent 全局配置目录。

    在用户主目录创建 ``~/.heagent/``，并生成带注释的配置模板 ``~/.heagent/.env``。
    如果文件已存在，则保留不覆盖。
    """
    created_dir = False
    if not GLOBAL_CONFIG_DIR.exists():
        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        created_dir = True

    created_file = False
    if not GLOBAL_CONFIG_FILE.exists():
        template = _INIT_ENV_TEMPLATE.format(path=str(GLOBAL_CONFIG_FILE))
        GLOBAL_CONFIG_FILE.write_text(template, encoding="utf-8")
        created_file = True

    if created_dir and created_file:
        click.echo(f"[OK] Created global config directory: {GLOBAL_CONFIG_DIR}")
        click.echo(f"[OK] Created config template: {GLOBAL_CONFIG_FILE}")
        click.echo("")
        click.echo("Edit ~/.heagent/.env to set your API keys and preferences.")
        click.echo("Project-level .env files can still override per-project.")
    elif created_file:
        click.echo(f"[OK] Created config template: {GLOBAL_CONFIG_FILE}")
        click.echo("Edit it to set your API keys and preferences.")
    else:
        click.echo(f"Already exists: {GLOBAL_CONFIG_FILE} (not overwritten)")


# Set run as the default command (heagent "hello" -> run "hello")
main.set_default_command("run")

# Register gui subcommand (lazy import to avoid loading Textual on non-GUI paths)
try:
    from heagent.gui.cli import gui_cmd

    main.add_command(gui_cmd)
except ImportError:
    pass
