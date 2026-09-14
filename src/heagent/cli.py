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
from heagent.agent.loop import AgentLoop
from heagent.agent.middleware import make_retry_middleware
from heagent.cli_display import (
    _echo_status,
    _format_status,
    _format_tokens_k,  # noqa: F401
    _LineState,
    _print_banner,
    _print_stream_event,
    _print_usage,
    show_deferred_work,
    show_tool_activity,
)
from heagent.cli_goal import _goal_auto_goal_id, _goal_cron_advance, _goal_runner
from heagent.config import GLOBAL_CONFIG_DIR, GLOBAL_CONFIG_FILE, Settings, get_settings
from heagent.context.compressor import ContextCompressor
from heagent.context.session import SessionStore
from heagent.context.window_reset import WindowResetConfig
from heagent.cron.jobs import JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.engine import ConsoleApprovalHandler, EngineContainer
from heagent.engine.roles import load_agent_roles
from heagent.exceptions import BudgetExceeded, HeAgentError
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.memory.soul import SoulStore
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.openai import OpenAIProvider
from heagent.providers.responses import OpenAIResponsesProvider
from heagent.providers.router import HeuristicRouter, RoutingProvider, active_model, display_reason
from heagent.providers.switchable import SwitchableProvider
from heagent.slash import SlashRegistry, load_custom_commands
from heagent.terminal import KeyInterruptMonitor
from heagent.tools.mcp import MCPClientManager, load_mcp_config
from heagent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from heagent.engine.context import RunContext
    from heagent.providers.base import BaseProvider
    from heagent.types import RoutingPoolSpec

    # 单档 provider 构建器：(档位模型名, base_url 覆盖) → provider
    ProviderBuilder = Callable[[str, str | None], BaseProvider]

logger = logging.getLogger(__name__)


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
        # 智能路由条目（RoutingProvider）：只显示默认模型（如 deepseek-flash），而非池内全部模型列表。
        display_model = active_model(provider.providers[name]) or meta.model
        marker = "<- default" if i == default_idx else ""
        click.echo(f"  [{i}] {name}  ({display_model})  {marker}", err=True)

    while True:
        try:
            raw = click.prompt("Select (number)", type=str, default=str(default_idx))
            choice = int(raw)
            if 1 <= choice <= len(names):
                await provider.switch(names[choice - 1])
                display_model = active_model(provider.current) or provider.get_metadata().model
                click.echo(f"  -> Using {provider.active} ({display_model})", err=True)
                return
            click.echo(f"  Please enter 1-{len(names)}", err=True)
        except (ValueError, click.Abort):
            raise SystemExit(0) from None


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
    "openai": "OPENAI_API_KEY",
    "gpt": "OPENAI_RESPONSES_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
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
    """单密钥 Responses API 条目的构建器（gpt 条目）：每档一个模型名。"""

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
    ——不影响「Multiple providers Choose」（启动选择 + ``/model`` 切换 + 自动回退）。

    路由池只有这一个入口：条目出现在 ``ROUTING_POOLS`` 里即为启用该池
    （见 ``Settings.routing_pool_map``）；没有按 provider 的专用开关。

    本地 Ollama 经 ``OLLAMA_ENABLED=true`` 显式启用（OpenAI 兼容 ``/v1``、无需真实 key），
    作为独立条目入池，可经 ``/model`` 切换、``--model`` 覆盖模型名。
    """
    named: dict[str, BaseProvider] = {}
    specs = settings.routing_pool_map
    continuity = settings.routing_reasoning_continuity

    if settings.deepseek_api_key:
        deepseek_url = settings.deepseek_base_url or _DEEPSEEK_BASE_URL
        named["deepseek"] = _build_entry(
            "deepseek",
            specs.get("deepseek"),
            model=model,
            default_model=settings.deepseek_model,
            default_base_url=deepseek_url,
            build=_openai_builder(settings, key=settings.deepseek_api_key, base_url=deepseek_url),
            continuity=continuity,
        )

    if settings.kimi_api_key:
        kimi_url = settings.kimi_base_url or _KIMI_BASE_URL
        named["kimi"] = _build_entry(
            "kimi",
            specs.get("kimi"),
            model=model,
            default_model=settings.kimi_model,
            default_base_url=kimi_url,
            build=_openai_builder(settings, key=settings.kimi_api_key, base_url=kimi_url),
            continuity=continuity,
        )

    if settings.glm_api_key:
        glm_url = settings.glm_base_url or _GLM_BASE_URL
        named["glm"] = _build_entry(
            "glm",
            specs.get("glm"),
            model=model,
            default_model=settings.glm_model,
            default_base_url=glm_url,
            build=_openai_builder(settings, key=settings.glm_api_key, base_url=glm_url),
            continuity=continuity,
        )

    if settings.ollama_enabled:
        if not settings.ollama_model:
            click.echo(
                "Error: OLLAMA_ENABLED=true requires OLLAMA_MODEL "
                "(e.g. OLLAMA_MODEL=qwen3:8b; list local models: curl http://127.0.0.1:11434/api/tags).",
                err=True,
            )
            raise SystemExit(1)
        ollama_url = settings.ollama_base_url or _OLLAMA_BASE_URL
        named["ollama"] = _build_entry(
            "ollama",
            specs.get("ollama"),
            model=model,
            default_model=settings.ollama_model,
            default_base_url=ollama_url,
            build=_openai_builder(settings, key=settings.ollama_api_key or "ollama", base_url=ollama_url),
            continuity=continuity,
        )

    if settings.openai_api_key or settings.openai_key_pool:
        named["openai"] = _build_entry(
            "openai",
            specs.get("openai"),
            model=model,
            default_model=settings.default_model,
            default_base_url=settings.openai_base_url,
            build=_openai_pool_builder(settings),
            continuity=continuity,
        )

    if settings.openai_responses_api_key:
        named["gpt"] = _build_entry(
            "gpt",
            specs.get("gpt"),
            model=model,
            default_model=settings.openai_model,
            default_base_url=settings.openai_responses_base_url,
            build=_responses_builder(
                settings,
                key=settings.openai_responses_api_key,
                base_url=settings.openai_responses_base_url,
            ),
            continuity=continuity,
        )

    if settings.anthropic_api_key or settings.anthropic_key_pool:
        named["anthropic"] = _build_entry(
            "anthropic",
            specs.get("anthropic"),
            model=model,
            default_model=settings.default_model,
            default_base_url=settings.anthropic_base_url,
            build=_anthropic_pool_builder(settings),
            continuity=continuity,
        )

    for entry in specs:
        if entry not in named:
            logger.warning(
                "A routing pool is configured for %r but that provider entry is unavailable "
                "(%s not set / entry disabled); pool skipped, other providers unaffected.",
                entry,
                _ENTRY_CREDENTIAL_HINTS.get(entry, "credentials"),
            )

    if not named:
        click.echo(
            "Error: No API key configured. Set DEEPSEEK_API_KEY, KIMI_API_KEY, "
            "GLM_API_KEY, OPENAI_API_KEY, OPENAI_RESPONSES_API_KEY or ANTHROPIC_API_KEY "
            "in environment, or enable the local Ollama entry with OLLAMA_ENABLED=true.",
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
            raise SystemExit("Error: provider entry requested without credentials.")
        return provider

    return build


def _openai_pool_builder(settings: Settings) -> ProviderBuilder:
    """openai 条目构建器（Chat Completions，多密钥池）。"""
    return _key_rotated_builder(
        settings.openai_api_key,
        settings.openai_key_pool,
        lambda key, tier_model, url: OpenAIProvider(
            api_key=key,
            model=tier_model,
            base_url=url,
            max_tokens=settings.max_output_tokens,
        ),
    )


def _anthropic_pool_builder(settings: Settings) -> ProviderBuilder:
    """anthropic 条目构建器（多密钥池）。"""
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


def _build_context_strategy(
    settings: Settings, provider: BaseProvider
) -> tuple[ContextCompressor | None, WindowResetConfig | None]:
    """按 CONTEXT_STRATEGY 构造上下文管理策略（compressor / window_reset，二选一）。

    D3 决策：两者互斥，AgentLoop 同传即报错。默认 "compressor"；未知值告警并回退
    compressor，避免静默失效。
    """
    strategy = settings.context_strategy
    if strategy == "reset":
        return None, WindowResetConfig(threshold=settings.window_reset_threshold)
    if strategy == "compressor":
        return ContextCompressor(provider, threshold=settings.compression_threshold), None
    logger.warning("CONTEXT_STRATEGY=%r invalid; falling back to compressor", strategy)
    return ContextCompressor(provider, threshold=settings.compression_threshold), None


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
    compressor, window_reset = _build_context_strategy(settings, provider)
    engine = engine or EngineContainer.default(workspace_root=os.getcwd(), sandbox_backend=sandbox_backend)
    retry_mw = make_retry_middleware(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )

    scheduler: CronScheduler | None = None
    if session is not None and settings.cron_enabled and cron_store:

        async def _run_job(prompt: str, run_context: RunContext) -> None:
            goal_id = _goal_auto_goal_id(prompt)
            if goal_id is not None:
                await _goal_cron_advance(provider, engine, cron_store, goal_id)
                return
            loop = AgentLoop(
                provider,
                max_iterations=max_iterations,
                middlewares=[retry_mw],
                skills=skills,
                facts=facts,
                profile=profile,
                compressor=compressor,
                window_reset=window_reset,
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
        window_reset=window_reset,
        context_dir=os.getcwd(),
        soul=soul,
        cron_store=cron_store,
        engine=engine,
    )
    return loop, scheduler


def _apply_plan_mode(engine: EngineContainer, *, plan_mode: bool) -> str | None:
    """Plan Mode（Epic 33）：收敛 PolicyEngine 白名单为只读工具集，返回 plan 提示拼入 system。

    只读工具集 = 所有 ``readOnlyHint=True`` 的**内置**工具（排除 MCP 工具——其
    ``readOnlyHint`` 由 server 自声明、不可信，见 CLAUDE.md 安全声明；plan mode 下
    默认排除全部 MCP 工具是 fail-safe 方向，误判只导致可用工具变少，不泄漏写操作）。
    """
    if not plan_mode:
        return None
    readonly = {
        s.name
        for s in ToolRegistry.get().enabled_schemas()
        if "__" not in s.name and s.annotations is not None and s.annotations.readOnlyHint
    }
    engine.policy.allowed_tools = readonly
    return (
        "You are in PLAN MODE (read-only). Do not modify files, execute shell commands, "
        "or change any persistent state. Only read, analyze, and present a plan."
    )


async def _run_single(
    prompt: str,
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
    soul_path: str | None = None,
    mcp_ctx: AbstractAsyncContextManager[Any] | None = None,
    sandbox_backend: str | None = None,
    plan_mode: bool = False,
) -> None:
    """Run a single prompt and print the result."""
    settings = get_settings()
    engine = EngineContainer.default(workspace_root=os.getcwd(), sandbox_backend=sandbox_backend)
    if sys.stdin.isatty() and engine.approval_handler is None:
        engine.approval_handler = ConsoleApprovalHandler()
    plan_hint = _apply_plan_mode(engine, plan_mode=plan_mode)
    if plan_hint:
        system = f"{plan_hint}\n\n{system}" if system else plan_hint

    async with mcp_ctx or contextlib.nullcontext():
        loop, _ = _build_loop(
            settings, provider, max_iterations, soul_path, engine=engine, sandbox_backend=sandbox_backend
        )
        try:
            result = await loop.run(prompt, system=system)
            click.echo(result)
            _print_usage(loop.last_usage, model=loop.provider.get_metadata().model)
        except BudgetExceeded as exc:
            click.echo(f"[budget exceeded] {exc.message}", err=True)
        except HeAgentError as exc:
            click.echo(f"[error] {exc.message}", err=True)
        finally:
            # 活动回顾放 finally：出错/超预算时「它到底动了什么」往往才是最需要看的。
            show_tool_activity(loop)


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


def _setup_readline() -> None:
    """配置 readline 历史（Epic 35 体验优化）；readline 不可用（如 Windows）时静默跳过。"""
    try:
        import readline  # noqa: PLC0415
    except ImportError:
        return
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    histfile = GLOBAL_CONFIG_DIR / "history"
    with contextlib.suppress(OSError, FileNotFoundError):
        # unused-ignore：Windows 的 readline 存根缺这些属性（ignore 被使用），Linux 的
        # 有（ignore 未被使用）——列上 unused-ignore 让两个平台都不报 strict 的未用告警。
        readline.read_history_file(str(histfile))  # type: ignore[attr-defined, unused-ignore]
    readline.set_history_length(1000)  # type: ignore[attr-defined, unused-ignore]
    import atexit  # noqa: PLC0415

    atexit.register(readline.write_history_file, str(histfile))  # type: ignore[attr-defined, unused-ignore]


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
    plan_mode: bool = False,
) -> None:
    """Run interactive chat mode."""
    _setup_readline()
    settings = get_settings()
    engine = EngineContainer.default(workspace_root=os.getcwd(), sandbox_backend=sandbox_backend)
    if engine.approval_handler is None:
        engine.approval_handler = ConsoleApprovalHandler()
    plan_hint = _apply_plan_mode(engine, plan_mode=plan_mode)
    if plan_hint:
        system = f"{plan_hint}\n\n{system}" if system else plan_hint

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
        registry = _build_slash_registry(provider, mcp_manager, session, session_id, loop, system, loop.cron_store)
        click.echo(
            f"HeAgent interactive mode (session: {session_id}). Type your message (Esc to pause, Enter to resume, double Esc to interrupt, Ctrl+C to exit)."
        )

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
                    continue

                if user_input.startswith("/"):
                    handled = await _dispatch_slash_interactive(user_input, registry)
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


def _pause_loop(loop: AgentLoop, line_state: _LineState) -> None:
    """暂停当前 run（幂等，已暂停则无操作）。"""
    if not loop.is_paused:
        loop.pause()
        _echo_status("[paused] Run paused (Enter to resume).", line_state)
        # 补一行状态：暂停常发生在长工具中途，把在途工具显示出来才知道卡在哪。
        _echo_status(_format_status(loop), line_state)


def _resume_loop(loop: AgentLoop, line_state: _LineState) -> None:
    """恢复被暂停的 run（幂等，未暂停则无操作）。"""
    if loop.is_paused:
        loop.unpause()
        _echo_status("[paused] Run resumed.", line_state)
        _echo_status(_format_status(loop), line_state)


async def _run_prompt(loop: AgentLoop, prompt: str, system: str | None, session_id: str) -> None:
    """把一条用户消息提交给 loop 流式执行并打印结果（自定义斜杠命令复用）。

    运行期间后台监听按键：
      - 单击 Esc 暂停当前 run（暂停不取消，恢复后从挂起点继续）；
      - Enter 恢复被暂停的 run；
      - 双击 Esc 取消当前 run、回到交互输入状态（程序不退出）。
    """
    monitor = KeyInterruptMonitor()
    monitor.start(asyncio.get_running_loop())
    line_state = _LineState()
    run_task = asyncio.create_task(_consume_stream(loop, prompt, system, session_id, line_state))
    interrupt_wait: asyncio.Task[bool] | None = None
    pause_wait: asyncio.Task[bool] | None = None
    resume_wait: asyncio.Task[bool] | None = None
    try:
        if monitor.active:
            interrupt_wait = asyncio.create_task(monitor.interrupted.wait())
            while not run_task.done():
                pause_wait = asyncio.create_task(monitor.pause_toggle.wait())
                resume_wait = asyncio.create_task(monitor.resume.wait())
                done, _ = await asyncio.wait(
                    {run_task, interrupt_wait, pause_wait, resume_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if run_task.done():
                    break
                if interrupt_wait in done:
                    run_task.cancel()
                    break
                if pause_wait in done:
                    _pause_loop(loop, line_state)
                    monitor.pause_toggle.clear()
                if resume_wait in done:
                    _resume_loop(loop, line_state)
                    monitor.resume.clear()
                for task in (pause_wait, resume_wait):
                    task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            _echo_status("[interrupted] Run interrupted by double Esc.", line_state)
    finally:
        monitor.stop()

        async def _cancel(task: asyncio.Task[bool] | None) -> None:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        await _cancel(interrupt_wait)
        await _cancel(pause_wait)
        await _cancel(resume_wait)


async def _consume_stream(
    loop: AgentLoop, prompt: str, system: str | None, session_id: str, line_state: _LineState
) -> None:
    """消费 ``loop.run_stream`` 并打印；业务异常在此收口（CancelledError 透传）。"""
    try:
        async for event in loop.run_stream(prompt, system=system, session_id=session_id):
            _print_stream_event(event, line_state)
        if not line_state.at_line_start:
            click.echo("")
            line_state.at_line_start = True
        _print_usage(loop.last_usage, model=loop.provider.get_metadata().model)
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
    cron_store: JobStore | None = None,
) -> SlashRegistry:
    """构造斜杠命令注册表：内置命令 + 用户自定义命令（Epic 31）。"""
    registry = SlashRegistry()

    async def _model(args: str) -> None:
        await _handle_model_cmd(["/model", *args.split()], provider)

    async def _route(args: str) -> None:
        await _handle_route_cmd(provider, args)

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
    registry.register("route", "智能路由状态 / 强制模型 (<name>|auto)", _route)
    registry.register("mcp-prompt", "调度 MCP prompt", _mcp_prompt)

    async def _deferred(args: str) -> None:
        show_deferred_work(Path.cwd())

    registry.register("deferred", "列出 deferred-work 台账（遗留项登记）", _deferred)
    registry.register("clear", "清空当前会话上下文", _clear)
    registry.register("help", "列出所有斜杠命令", _help)

    async def _goal(args: str) -> None:
        await _goal_runner(provider, loop.engine, args, cron_store=cron_store)

    registry.register("goal", "目标驱动开发（new/next/run/status/pause/resume/auto/audit/reset）", _goal)

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


async def _dispatch_slash_interactive(user_input: str, registry: SlashRegistry) -> bool:
    """Dispatch one interactive slash command while preserving cancellation semantics."""
    try:
        return await _handle_slash(user_input, registry)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        click.echo("[interrupted] Slash command interrupted; state is preserved.", err=True)
        return True
    except Exception as exc:
        click.echo(f"[error] Slash command failed: {exc}", err=True)
        return True


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
            display_model = active_model(provider.providers[name]) or meta.model
            click.echo(f"  [{marker}] {name}  ({display_model})", err=True)
        return

    name = parts[1]
    try:
        await provider.switch(name)
        display_model = active_model(provider.current) or provider.get_metadata().model
        click.echo(f"[model] Switched to {name} ({display_model})", err=True)
    except ValueError as exc:
        click.echo(f"[model] {exc}", err=True)


def _extract_routing(provider: BaseProvider) -> tuple[RoutingProvider | None, str | None]:
    """从 provider 栈中取出当前生效的智能路由实例（支持 ``SwitchableProvider`` 嵌套）。

    Returns:
        (routing, hint): routing 为当前活跃 provider 上的 ``RoutingProvider``（无则 None）；
        hint 为「池内存在路由但不在当前活跃 provider 上」时的提示语（无则 None）。
    """
    if isinstance(provider, RoutingProvider):
        return provider, None
    if isinstance(provider, SwitchableProvider):
        current = provider.current
        if isinstance(current, RoutingProvider):
            return current, None
        routed = [name for name, p in provider.providers.items() if isinstance(p, RoutingProvider)]
        if routed:
            return None, (
                f"Smart routing is on provider '{routed[0]}'; "
                f"switch to it with /model {routed[0]} (active: {provider.active})."
            )
    return None, None


async def _handle_route_cmd(provider: BaseProvider, args: str = "") -> None:
    """Handle /route slash command: show/force smart-routing model.

    ``/route``           显示路由池 + 最近决策 + 当前强制状态；
    ``/route <name>``    强制固定使用池内某个模型（后续调用跳过启发式路由）；
    ``/route auto``      清除强制，恢复自动路由。
    """
    routing, hint = _extract_routing(provider)
    if routing is None:
        if hint:
            click.echo(f"[route] {hint}", err=True)
        else:
            click.echo("[route] Smart routing not enabled (configure ROUTING_POOLS).", err=True)
        return

    arg = (args or "").strip().lower()
    if arg == "auto":
        routing.set_force(None)
        click.echo("[route] Forced model cleared; back to auto routing.", err=True)
        return
    if arg:
        if arg in routing.names:
            try:
                routing.set_force(arg)
            except ValueError as exc:
                click.echo(f"[route] {exc}", err=True)
                return
            click.echo(f"[route] Forced model -> {arg} ({routing.current_model})", err=True)
            return
        click.echo(f"[route] Unknown argument {arg!r} (use: {' | '.join(routing.names)} | auto).", err=True)
        return

    click.echo("Smart routing pool:", err=True)
    click.echo(f"  models: {routing.get_metadata().model}", err=True)
    if routing.force is not None:
        click.echo(f"  forced: {routing.force} ({routing.current_model})", err=True)
    if routing.last_decision is not None:
        # 与状态行同一展示策略：兜底理由（default_fast）不展示——它不解释任何东西，
        # 还容易被误读成模型名。原始 reason 仍可查（日志 / active_route_reason）。
        line = f"  last decision: {routing.last_decision.provider}"
        reason = display_reason(routing.last_decision.reason)
        if reason:
            line += f" ({reason})"
        click.echo(line, err=True)
    else:
        click.echo("  last decision: (none yet)", err=True)


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
    plan_mode: bool = False,
) -> None:
    """Core CLI routine — logging, provider, MCP, dispatch to single/chat."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _setup_logging()
    _print_banner()

    settings = get_settings()
    resolved_iterations = max_iterations or settings.max_iterations
    resolved_plan = plan_mode or settings.plan_mode
    provider = _build_provider(settings, model)

    # 加载配置文件驱动的自定义角色（Epic 34）：.heagent/agents/*.md + ~/.heagent/agents/*.md
    load_agent_roles()

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
                plan_mode=resolved_plan,
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
                plan_mode=resolved_plan,
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
        type=click.Choice(["auto", "passthrough", "firejail", "winjob"]),
        default=None,
        help="Sandbox backend for shell execution (default: auto = probe firejail)",
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
    click.option(
        "--plan",
        "plan_mode",
        is_flag=True,
        default=False,
        help="Plan mode: read-only (no write tools / shell)",
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
    plan_mode: bool,
) -> None:
    """Run HeAgent in single-shot or interactive mode."""
    _run_cli_impl(prompt, model, system, max_iterations, soul, sandbox, continue_session, resume_session, plan_mode)


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
# GLM_API_KEY=your-glm-key

# ---- API 基础 URL（用于代理或自营服务）----
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
# OPENAI_BASE_URL=
# ANTHROPIC_BASE_URL=
# KIMI_BASE_URL=https://api.moonshot.cn/v1
# GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4

# ---- 各 Provider 默认模型 ----
# DEFAULT_MODEL=gpt-4o
# DEEPSEEK_MODEL=deepseek-v4-pro
# KIMI_MODEL=kimi-k3
# GLM_MODEL=glm-5.3

# ---- 本地 Ollama（OpenAI 兼容 /v1，显式 opt-in；无需真实 API Key）----
# OLLAMA_ENABLED=true
# OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
# OLLAMA_MODEL=qwen3:8b
# MAX_OUTPUT_TOKENS=4096   # 可选：单次输出上限（本地思考模型建议设，防无限生成）
# 本地模型窗口通常远小于默认 512000（Ollama 取 Modelfile 的 num_ctx），请按实际值下调
# MAX_CONTEXT_TOKENS，否则压缩/窗口重置阈值永不触发、先撞 API 400。

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


_CONTEXT_TEMPLATE = """# CONTEXT.md

> HeAgent 每次运行会自动加载本文件（优先级：`.heagent/CONTEXT.md` > `AGENTS.md` > `CLAUDE.md`）。
> 在此填写项目的关键背景与约定，帮助 Agent 更好地理解本项目。

## 项目概述

<!-- 项目是做什么的、技术栈、目录结构 -->

## 关键约定

<!-- 命名规范、代码规范、构建 / 测试命令等 -->

## 注意事项

<!-- 哪些文件 / 目录不要修改、哪些是生成产物、安全边界等 -->
"""


def _init_project_context() -> None:
    """生成项目 ``.heagent/CONTEXT.md`` 模板（若不存在）。"""
    context_path = Path(".heagent") / "CONTEXT.md"
    if context_path.exists():
        click.echo(f"Already exists: {context_path} (not overwritten)")
        return
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(_CONTEXT_TEMPLATE, encoding="utf-8")
    click.echo(f"[OK] Created project context template: {context_path}")


@main.command("init")
@click.option(
    "--project",
    "project",
    is_flag=True,
    default=False,
    help="Also generate project .heagent/CONTEXT.md template",
)
def init_cmd(project: bool) -> None:
    """初始化 HeAgent 全局配置目录。

    在用户主目录创建 ``~/.heagent/``，并生成带注释的配置模板 ``~/.heagent/.env``。
    如果文件已存在，则保留不覆盖。``--project`` 时额外生成项目 ``.heagent/CONTEXT.md``。
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

    if project:
        _init_project_context()


# Set run as the default command (heagent "hello" -> run "hello")
main.set_default_command("run")

# Register the lightweight GUI command wrapper; Textual itself remains lazy.
from heagent.gui.cli import gui_cmd  # noqa: E402

main.add_command(gui_cmd)
