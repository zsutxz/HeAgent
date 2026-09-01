"""Command-line entrypoint for HeAgent."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import click

import heagent.tools.builtins  # noqa: F401
from heagent import __version__
from heagent.agent.loop import AgentLoop
from heagent.agent.middleware import make_retry_middleware
from heagent.config import GLOBAL_CONFIG_DIR, GLOBAL_CONFIG_FILE, Settings, get_settings
from heagent.context.compressor import ContextCompressor
from heagent.context.session import SessionStore
from heagent.context.tokens import estimate_cost
from heagent.context.window_reset import WindowResetConfig
from heagent.cron.expr import cron_matches
from heagent.cron.jobs import JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.engine import (
    ConsoleApprovalHandler,
    EngineContainer,
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    WorkflowOrchestrator,
    WorkflowPhase,
    WorkflowRunner,
    WorkflowStatus,
    WorkflowStepResult,
)
from heagent.engine.persist import atomic_write_text
from heagent.engine.roles import load_agent_roles
from heagent.exceptions import BudgetExceeded, HeAgentError
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skill_packages import SkillPackage, SkillWorkflowError, WorkflowResource
from heagent.memory.skills import SkillStore
from heagent.memory.soul import SoulStore
from heagent.providers.anthropic import AnthropicProvider
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.openai import OpenAIProvider
from heagent.providers.responses import OpenAIResponsesProvider
from heagent.providers.router import HeuristicRouter, RoutingProvider, active_model
from heagent.providers.switchable import SwitchableProvider
from heagent.slash import SlashRegistry, load_custom_commands
from heagent.terminal import KeyInterruptMonitor
from heagent.tools.mcp import MCPClientManager, load_mcp_config
from heagent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from heagent.agent.sub import SubAgentResult
    from heagent.engine.context import RunContext
    from heagent.providers.base import BaseProvider
    from heagent.types import TokenUsage

logger = logging.getLogger(__name__)
_GOAL_AUTO_DEFAULT_CRON = "*/15 * * * *"
_GOAL_AUTO_PREFIX = "goal-advance "
_goal_auto_lock = asyncio.Lock()


# =============================================================================
# Shared utilities (CLI / GUI reuse)
# =============================================================================


def _print_banner() -> None:
    """Print the HeAgent version banner to stderr on startup."""
    click.echo(f"HeAgent v{__version__} — A self-improving AI Agent core framework", err=True)


def _print_usage(usage: TokenUsage | None, *, model: str | None = None) -> None:
    """Print token usage to stderr after a run (with optional cost, Epic 34)."""
    if usage is None or usage.total_tokens == 0:
        return
    line = f"  [tokens: {usage.prompt_tokens} in + {usage.completion_tokens} out = {usage.total_tokens} total]"
    if model:
        cost = estimate_cost(usage, model, get_settings().model_pricing_map)
        if cost is not None:
            line += f" [cost: ${cost:.4f}]"
    click.echo(line, err=True)


@dataclass
class _LineState:
    """跟踪终端光标是否在行首（供状态消息决定是否补换行）。

    流式输出经 ``click.echo(..., nl=False)`` 打印、常停半行；暂停/恢复等状态消息
    需从行首开始，故按需补换行，避免无谓空行。
    """

    at_line_start: bool = True

    def write(self, text: str) -> None:
        """记录一次不带尾换行的输出，更新行首状态。"""
        if text:
            self.at_line_start = text.endswith("\n")


def _echo_status(message: str, line_state: _LineState) -> None:
    """打印状态消息：光标不在行首时先补换行；``click.echo`` 默认尾换行后置行首。"""
    prefix = "" if line_state.at_line_start else "\n"
    click.echo(f"{prefix}{message}", err=True)
    line_state.at_line_start = True


def _print_stream_event(event: Any, line_state: _LineState) -> None:
    """Render one streaming event from ``AgentLoop.run_stream`` to the terminal."""
    if event.type == "text":
        click.echo(event.text, nl=False)
        line_state.write(event.text)
    elif event.type == "tool_call":
        text = f"\n[calling {event.tool_name}...]"
        click.echo(text, nl=False)
        line_state.write(text)
    elif event.type == "tool_result":
        click.echo(" [done]", nl=False)
        line_state.write(" [done]")


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
    """Format CLI prompt prefix: model + current context occupancy / window + strategy threshold + cumulative.

    Shows the **current** context occupancy (``loop.last_context_tokens``, i.e. the token
    estimate of what the next call would send) against the context window, the active
    context-management strategy threshold (compressor / window_reset), and the cumulative
    tokens consumed since program start (across runs, only when > 0).
    """
    meta = loop.provider.get_metadata()
    # RoutingProvider：只显示当前实际使用的模型（flash/pro），而非池内全部模型列表。
    model = active_model(loop.provider) or meta.model
    settings = get_settings()
    max_tok = settings.max_context_tokens
    used = loop.last_context_tokens
    parts = [model, f"{_format_tokens_k(used)}/{_format_tokens_k(max_tok)} tok"]
    # 上下文策略标签：window_reset 与 compressor 互斥，据 loop 实际启用的策略取阈值。
    if loop.window_reset is not None:
        parts.append(f"reset@{int(loop.window_reset.config.threshold * 100)}%")
    elif loop.compressor is not None:
        parts.append(f"cmp@{int(loop.compressor.threshold * 100)}%")
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
        # 智能路由条目（RoutingProvider）：只显示默认模型（如 deepseek-v4-flash），而非池内全部模型列表。
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


def _build_provider(settings: Settings, model: str | None) -> BaseProvider:
    """Build the best available provider from configured credentials.

    智能路由（``ROUTING_ENABLED=true``）作用于 **DeepSeek 条目本身**：此时 deepseek 池内
    构建为 ``RoutingProvider``（flash=快速 / pro=深度，按问题难度自动切换），并**照常放入
    多 provider 池**——不影响「Multiple providers Choose」（启动选择 + ``/model`` 切换 +
    自动回退）。只有 deepseek 一个 provider 时直接返回该 ``RoutingProvider``（等价旧行为）。
    """
    named: dict[str, BaseProvider] = {}

    if settings.deepseek_api_key:
        if settings.routing_enabled:
            if model:
                logger.warning(
                    "--model %s ignored for deepseek: ROUTING_ENABLED=true builds a flash/pro pool (use /route to force).",
                    model,
                )
            named["deepseek"] = _build_routing_provider(settings)
        else:
            named["deepseek"] = OpenAIProvider(
                api_key=settings.deepseek_api_key,
                model=model or settings.deepseek_model,
                base_url=settings.deepseek_base_url or "https://api.deepseek.com/v1",
            )
    elif settings.routing_enabled:
        # 路由仅绑定 DeepSeek：未配置密钥时优雅降级（其余 provider 照常可用），
        # 不因误配置而阻断整个「Multiple providers Choose」。
        logger.warning(
            "ROUTING_ENABLED=true but DEEPSEEK_API_KEY is not set; smart routing skipped "
            "(other providers remain available)."
        )

    if settings.kimi_api_key:
        named["kimi"] = OpenAIProvider(
            api_key=settings.kimi_api_key,
            model=model or settings.kimi_model,
            base_url=settings.kimi_base_url or "https://api.moonshot.cn/v1",
        )

    if settings.glm_api_key:
        named["glm"] = OpenAIProvider(
            api_key=settings.glm_api_key,
            model=model or settings.glm_model,
            base_url=settings.glm_base_url or "https://open.bigmodel.cn/api/paas/v4",
        )

    openai_provider = _build_openai_providers(settings, model or settings.default_model)
    if openai_provider:
        named["openai"] = openai_provider

    gpt_provider = _build_gpt_providers(settings, model)
    if gpt_provider:
        named["gpt"] = gpt_provider

    anthropic_provider = _build_anthropic_providers(settings, model or settings.default_model)
    if anthropic_provider:
        named["anthropic"] = anthropic_provider

    if not named:
        click.echo(
            "Error: No API key configured. Set DEEPSEEK_API_KEY, KIMI_API_KEY, "
            "GLM_API_KEY, OPENAI_API_KEY, OPENAI_RESPONSES_API_KEY or ANTHROPIC_API_KEY "
            "in environment.",
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


def _build_routing_provider(settings: Settings) -> BaseProvider:
    """Build a RoutingProvider for DeepSeek's flash/pro split (chat=fast, reasoner=pro).

    ``ROUTING_ENABLED=true`` 时由 ``_build_provider`` 调用。DeepSeek 是唯一有天然
    「快速版/深度版」二分的 OpenAI 兼容 provider，故路由默认绑定 DeepSeek：
    fast → ``routing_fast_model``（默认 deepseek-v4-flash），pro → ``routing_pro_model``
    （默认 deepseek-v4-pro）。启发式路由见 ``providers/router.py``。
    """
    if not settings.deepseek_api_key:
        click.echo(
            "Error: ROUTING_ENABLED=true requires DEEPSEEK_API_KEY (fast=deepseek-v4-flash, pro=deepseek-v4-pro).",
            err=True,
        )
        raise SystemExit(1)

    base_url = settings.deepseek_base_url or "https://api.deepseek.com/v1"
    fast = OpenAIProvider(api_key=settings.deepseek_api_key, model=settings.routing_fast_model, base_url=base_url)
    pro = OpenAIProvider(api_key=settings.deepseek_api_key, model=settings.routing_pro_model, base_url=base_url)
    router = HeuristicRouter(fast="fast", pro="pro", reasoning_keywords=settings.routing_keyword_list or None)
    return RoutingProvider({"fast": fast, "pro": pro}, router, default="fast")


def _build_gpt_providers(settings: Settings, model: str | None) -> BaseProvider | None:
    """Build the GPT (Responses API) entry: routing pool (terra/luna/sol) or plain provider.

    返回 None 表示未配置 GPT 凭据。``GPT_ROUTING_ENABLED=true`` 时构建 ``RoutingProvider``
    （terra/luna/sol 三档，按问题难度自动切换），否则构建普通 ``OpenAIResponsesProvider``
    （/model gpt 切换）。
    """
    if settings.openai_responses_api_key:
        if settings.gpt_routing_enabled:
            if model:
                logger.warning(
                    "--model %s ignored for gpt: GPT_ROUTING_ENABLED=true builds a "
                    "terra/luna/sol pool (use /route to force).",
                    model,
                )
            return _build_gpt_routing_provider(settings)
        return OpenAIResponsesProvider(
            api_key=settings.openai_responses_api_key,
            model=model or settings.openai_responses_model,
            base_url=settings.openai_responses_base_url,
        )
    if settings.gpt_routing_enabled:
        logger.warning(
            "GPT_ROUTING_ENABLED=true but OPENAI_RESPONSES_API_KEY is not set; gpt routing skipped "
            "(other providers remain available)."
        )
    return None


def _build_gpt_routing_provider(settings: Settings) -> BaseProvider:
    """Build a RoutingProvider for GPT's terra/luna/sol split (Responses API).

    ``GPT_ROUTING_ENABLED=true`` 时由 ``_build_provider`` 调用：gpt（Responses API）
    条目构建为 ``RoutingProvider``（terra=快速 / luna=中档 / sol=深度，按问题难度
    自动切换）。三档对应 komapi.top 等中转站暴露的 gpt-5.6-terra / gpt-5.6-luna /
    gpt-5.6-sol；模型名经 Settings 可配。启发式路由见 ``providers/router.py``。
    """
    if not settings.openai_responses_api_key:
        click.echo(
            "Error: GPT_ROUTING_ENABLED=true requires OPENAI_RESPONSES_API_KEY "
            "(terra=gpt-5.6-terra, luna=gpt-5.6-luna, sol=gpt-5.6-sol).",
            err=True,
        )
        raise SystemExit(1)

    base_url = settings.openai_responses_base_url
    terra = OpenAIResponsesProvider(
        api_key=settings.openai_responses_api_key,
        model=settings.gpt_routing_terra_model,
        base_url=base_url,
    )
    luna = OpenAIResponsesProvider(
        api_key=settings.openai_responses_api_key,
        model=settings.gpt_routing_luna_model,
        base_url=base_url,
    )
    sol = OpenAIResponsesProvider(
        api_key=settings.openai_responses_api_key,
        model=settings.gpt_routing_sol_model,
        base_url=base_url,
    )
    router = HeuristicRouter(
        fast="terra",
        mid="luna",
        pro="sol",
        reasoning_keywords=settings.gpt_routing_reasoning_keyword_list or None,
        mid_keywords=settings.gpt_routing_mid_keyword_list or None,
    )
    return RoutingProvider({"terra": terra, "luna": luna, "sol": sol}, router, default="terra")


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
        readline.read_history_file(str(histfile))  # type: ignore[attr-defined]  # Unix readline only
    readline.set_history_length(1000)  # type: ignore[attr-defined]  # Unix readline only
    import atexit  # noqa: PLC0415

    atexit.register(readline.write_history_file, str(histfile))  # type: ignore[attr-defined]  # Unix readline only


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


def _resume_loop(loop: AgentLoop, line_state: _LineState) -> None:
    """恢复被暂停的 run（幂等，未暂停则无操作）。"""
    if loop.is_paused:
        loop.unpause()
        _echo_status("[paused] Run resumed.", line_state)


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
    registry.register("clear", "清空当前会话上下文", _clear)
    registry.register("help", "列出所有斜杠命令", _help)

    async def _goal(args: str) -> None:
        await _goal_runner(provider, loop.engine, args, cron_store=cron_store)

    registry.register("goal", "目标驱动开发（new/next/status/reset，Story 41.1）", _goal)

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


# =============================================================================
# /goal 命令族（Story 41.1：目标驱动开发工作流——skill 正文直读 + 逐 story 会话）
# =============================================================================

# goal 状态目录与 skill 正文路径（相对路径，使用时锚定 Path.cwd()）。
_GOALS_DIR = Path(".heagent/goals")
_GOAL_SKILL_PATH = Path(".heagent/skills/goal/SKILL.md")
_GOAL_DECLARATIVE_WORKFLOW_PATH = Path(".heagent/workflows/bmad-development/workflow.md")
_GOAL_STATUSES = frozenset({"planning", "executing", "done", "blocked"})
_GOAL_HEX = frozenset("0123456789abcdef")  # goal_id 字符集（与 uuid4().hex[:8] 写入格式一致）
# 保留子命令（首 token 命中即子命令；new 之外带尾文本时显性拒绝，防尾文本被静默吞掉）。
_GOAL_RESERVED = ("next", "status", "reset", "run", "auto", "pause", "resume", "audit")
_GOAL_RUN_MAX_ROUNDS = 10
_GOAL_ADVANCED = "advanced"
_GOAL_DONE = "done"
_GOAL_STALLED = "stalled"
_GOAL_FAILED = "failed"


def _goal_declarative_workflow() -> WorkflowResource | None:
    """Load the explicitly configured declarative goal workflow, if enabled.

    The configuration file is the feature flag. A malformed configured workflow is
    an error rather than a reason to silently run the incompatible GOAL.md flow.
    """
    if not _GOAL_DECLARATIVE_WORKFLOW_PATH.is_file():
        return None
    try:
        package = SkillPackage(
            skill_id="goal-declarative-workflow",
            root=_GOAL_DECLARATIVE_WORKFLOW_PATH.parent,
        )
        return package.read_workflow(_GOAL_DECLARATIVE_WORKFLOW_PATH.name)
    except (SkillWorkflowError, ValueError, OSError) as exc:
        raise ValueError(f"declarative workflow configuration is invalid: {exc}") from exc


def _goal_declarative_store(goal_dir: Path) -> WorkflowCheckpointStore:
    return WorkflowCheckpointStore(
        str(goal_dir / "checkpoints"),
        workflow_path=str(goal_dir / "workflow.json"),
    )


def _goal_declarative_active_dir() -> Path | None:
    goal_md = _goal_active_md()
    return goal_md.parent if goal_md is not None else None


async def _goal_declarative_runner(
    workflow: WorkflowResource,
    goal_dir: Path,
) -> WorkflowRunner:
    """Restore the latest Runner snapshot or create a new one for this goal."""
    store = _goal_declarative_store(goal_dir)
    checkpoints = await store.list_checkpoints(goal_id=goal_dir.name)
    workflow_state = await store.load_workflow()
    if workflow_state is not None:
        matching = [
            checkpoint
            for checkpoint in checkpoints
            if checkpoint.active_step == workflow_state.active_step
            and checkpoint.status is workflow_state.status
            and checkpoint.active_skill == workflow.name
        ]
        if matching:
            return WorkflowRunner.from_checkpoint(
                workflow,
                matching[-1],
                checkpoint_store=store,
                phase=WorkflowPhase.IMPLEMENTATION,
            )
    # Each goal owns its checkpoint directory, so the latest checkpoint for this
    # goal is the authoritative recovery point. Do not make recovery contingent
    # on optional descriptive metadata such as ``active_skill``.
    if checkpoints:
        return WorkflowRunner.from_checkpoint(
            workflow,
            checkpoints[-1],
            checkpoint_store=store,
            phase=WorkflowPhase.IMPLEMENTATION,
        )
    return WorkflowRunner(
        workflow,
        goal_id=goal_dir.name,
        checkpoint_store=store,
        phase=WorkflowPhase.IMPLEMENTATION,
    )


def _goal_declarative_prompt(
    workflow: WorkflowResource,
    step_name: str,
    description: str,
    goal_dir: Path,
) -> str:
    return (
        f"{workflow.instructions}\n\n# Declarative workflow step\n"
        f"Goal: {description}\n"
        f"Goal directory: {goal_dir.resolve()}\n"
        f"Step: {step_name}\n"
        "Execute only this declared step and leave the declared artifacts on disk."
    )


async def _goal_declarative_advance(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
) -> str:
    """Execute one declared step, preserving completed-step checkpoints exactly."""
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        click.echo("[goal] no active declarative goal; use /goal new <description>", err=True)
        return _GOAL_FAILED
    try:
        description = (goal_dir / "goal.txt").read_text(encoding="utf-8").strip()
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] declarative goal metadata is unreadable: {exc}", err=True)
        return _GOAL_FAILED
    if not description:
        click.echo("[goal] declarative goal metadata is empty", err=True)
        return _GOAL_FAILED
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
    except WorkflowCheckpointError as exc:
        click.echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
        return _GOAL_FAILED
    if runner.done:
        click.echo("[goal] declarative workflow is already complete", err=True)
        return _GOAL_DONE
    # A pause/cancellation is persisted as a non-completed Runner state. Resume
    # is explicit at the command boundary, then this call may continue the step.
    if runner.state.status is WorkflowStatus.WAITING_USER:
        click.echo("[goal] declarative workflow is paused; use /goal resume first", err=True)
        return _GOAL_FAILED
    if runner.state.status in {WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
        click.echo(f"[goal] declarative workflow is {runner.state.status.value}: {runner.state.reason}", err=True)
        return _GOAL_FAILED

    async def execute_step(step: Any) -> WorkflowStepResult:
        result = await _goal_session(
            provider,
            engine,
            _goal_declarative_prompt(workflow, step.name, description, goal_dir) + f"\n\n{step.instructions}",
            metadata={"goal_id": goal_dir.name, "goal_kind": "declarative", "workflow_step": step.name},
        )
        if result is None:
            return WorkflowStepResult(
                status=WorkflowStatus.WAITING_USER, reason="interrupted; resume to retry the active step"
            )
        if not result.success:
            return WorkflowStepResult(status=WorkflowStatus.FAILED, reason=str(result.output))
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output=result.output)

    # Input declarations describe the context supplied by this deterministic CLI
    # boundary. Artifact names from completed steps remain available on resume.
    inputs = set(runner.state.outputs)
    inputs.update(
        item.strip() for item in re.split(r"[,\n]", workflow.steps[runner.state.active_step].input) if item.strip()
    )
    try:
        result = await runner.run_step(execute_step, inputs=inputs)
    except (WorkflowCheckpointError, ValueError, TypeError) as exc:
        click.echo(f"[goal] declarative workflow failed: {exc}", err=True)
        return _GOAL_FAILED
    click.echo(
        f"[goal] declarative workflow: step={result.step_index if result.step_index is not None else '-'} "
        f"status={result.status.value}",
        err=True,
    )
    if result.status is WorkflowStatus.COMPLETED:
        return _GOAL_DONE
    if result.status is WorkflowStatus.PENDING:
        return _GOAL_ADVANCED
    return _GOAL_FAILED


async def _goal_declarative_new(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    description: str,
    *,
    cron_store: JobStore | None = None,
) -> None:
    """Create the minimum durable declarative-goal identity, then run step one."""
    previous = _goal_declarative_active_dir()
    goal_id = uuid.uuid4().hex[:8]
    goal_dir = _GOALS_DIR / goal_id
    for _ in range(100):
        if not goal_dir.exists():
            break
        goal_id = uuid.uuid4().hex[:8]
        goal_dir = _GOALS_DIR / goal_id
    else:
        click.echo("[goal] unable to allocate a declarative goal id", err=True)
        return
    try:
        atomic_write_text(goal_dir / "goal.txt", description)
        atomic_write_text(_GOALS_DIR / "current", goal_id)
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] failed to persist declarative goal: {exc}", err=True)
        return
    if previous is not None and cron_store is not None:
        _goal_auto_remove(cron_store, previous.name)
    await _goal_declarative_advance(provider, engine, workflow)


async def _goal_declarative_status(workflow: WorkflowResource) -> None:
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        click.echo("[goal] no active declarative goal", err=True)
        return
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
    except WorkflowCheckpointError as exc:
        click.echo(f"[goal] declarative checkpoint failed: {exc}", err=True)
        return
    click.echo(
        f"[goal] declarative progress: {len(runner.state.completed_steps)}/{len(workflow.steps)} "
        f"status={runner.state.status.value} step={runner.state.active_step}",
        err=True,
    )


async def _goal_declarative_pause_resume(workflow: WorkflowResource, *, resume: bool) -> None:
    goal_dir = _goal_declarative_active_dir()
    if goal_dir is None:
        click.echo("[goal] no active declarative goal", err=True)
        return
    try:
        runner = await _goal_declarative_runner(workflow, goal_dir)
        if resume:
            if runner.state.status is not WorkflowStatus.WAITING_USER:
                click.echo(f"[goal] workflow status={runner.state.status.value}; resume is not required", err=True)
                return
            runner.resume()
            action = "resumed"
        else:
            if runner.state.status is WorkflowStatus.WAITING_USER:
                click.echo("[goal] already paused; use /goal resume to continue", err=True)
                return
            runner.state = runner.state.model_copy(
                update={"status": WorkflowStatus.WAITING_USER, "reason": "user requested pause; resume to continue"}
            )
            action = "paused"
        await runner.persist_state()
    except (WorkflowCheckpointError, ValueError) as exc:
        click.echo(f"[goal] declarative {action if 'action' in locals() else 'workflow'} failed: {exc}", err=True)
        return
    click.echo(f"[goal] declarative workflow {action}: step={runner.state.active_step}", err=True)


async def _goal_declarative_run(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
) -> None:
    try:
        for _ in range(_GOAL_RUN_MAX_ROUNDS):
            async with _goal_auto_lock:
                outcome = await _goal_declarative_advance(provider, engine, workflow)
            if outcome != _GOAL_ADVANCED:
                return
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("[goal] declarative workflow interrupted; use /goal resume to continue", err=True)


async def _goal_declarative_auto(
    workflow: WorkflowResource,
    args: str,
    cron_store: JobStore | None,
) -> None:
    goal_dir = _goal_declarative_active_dir()
    if args == "off":
        if cron_store is None or goal_dir is None:
            click.echo("[goal] cron is not enabled or there is no active declarative goal", err=True)
            return
        click.echo(f"[goal] auto disabled: removed {_goal_auto_remove(cron_store, goal_dir.name)} job(s)", err=True)
        return
    if cron_store is None or goal_dir is None:
        click.echo("[goal] cron is not enabled or there is no active declarative goal", err=True)
        return
    schedule = args or _GOAL_AUTO_DEFAULT_CRON
    try:
        fields = schedule.split()
        if len(fields) != 5 or any(not field or any(not part.strip() for part in field.split(",")) for field in fields):
            raise ValueError("cron must contain five non-empty fields")
        cron_matches(schedule, datetime.now(UTC))
    except (TypeError, ValueError) as exc:
        click.echo(f"[goal] invalid cron expression: {exc}", err=True)
        return
    _goal_auto_remove(cron_store, goal_dir.name)
    job = cron_store.create_job(f"{_GOAL_AUTO_PREFIX}{goal_dir.name}", schedule)
    cron_store.add(job)
    click.echo(f"[goal] declarative auto registered: {job.id} workflow={workflow.name}", err=True)


async def _goal_declarative_dispatch(
    provider: BaseProvider,
    engine: EngineContainer | None,
    workflow: WorkflowResource,
    args: str,
    *,
    cron_store: JobStore | None,
) -> None:
    """Route the supported /goal commands without touching the legacy board."""
    parts = args.split(None, 1)
    head = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not parts:
        await _goal_declarative_status(workflow)
    elif head == "new":
        if not rest:
            _goal_usage()
        else:
            async with _goal_auto_lock:
                await _goal_declarative_new(provider, engine, workflow, rest, cron_store=cron_store)
    elif head in ("next", "status", "reset", "run", "pause", "resume", "audit") and rest:
        _goal_usage()
    elif head == "next":
        async with _goal_auto_lock:
            await _goal_declarative_advance(provider, engine, workflow)
    elif head == "run":
        await _goal_declarative_run(provider, engine, workflow)
    elif head == "status":
        await _goal_declarative_status(workflow)
    elif head == "pause":
        await _goal_declarative_pause_resume(workflow, resume=False)
    elif head == "resume":
        await _goal_declarative_pause_resume(workflow, resume=True)
    elif head == "audit":
        await _goal_audit(engine)
    elif head == "reset":
        _goal_reset()
    elif head == "auto":
        await _goal_declarative_auto(workflow, rest, cron_store)
    else:
        async with _goal_auto_lock:
            await _goal_declarative_new(provider, engine, workflow, args.strip(), cron_store=cron_store)


class GoalProgress(NamedTuple):
    """GOAL.md 边界扫描结果（NamedTuple：零依赖，命名访问消魔法下标）。"""

    status: str | None  # 首非空行 status: <planning|executing|done|blocked>，非法为 None
    total: int  # `- [ ]` / `- [x]` checkbox 总数
    done: int  # 已勾选数（GFM 大写 `- [X]` 同计）
    in_progress: str | None  # `> in-progress: S<n>` 的 <n>，无则 None


def _scan_goal_md(text: str) -> GoalProgress:
    """扫描 GOAL.md 的三个机器标记（无状态纯函数）：status 行 / checkbox / in-progress 行。

    status 须为**首非空行** ``status: <planning|executing|done|blocked>``，非法返回
    None（调用方显性报错）；story 只认 ``- [ ]`` / ``- [x]`` 行首 checkbox（大写 ``X``
    按 GFM 同计勾选）；in-progress 取首个合法 ``> in-progress: S<n>`` 行的 ``<n>``。
    """
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    status: str | None = None
    if first.startswith("status:"):
        value = first.split(":", 1)[1].strip()
        status = value if value in _GOAL_STATUSES else None
    total = done = 0
    in_progress: str | None = None
    for line in text.splitlines():
        story = re.match(r"- \[([ xX])\] S\d+: ", line)
        if story:
            total += 1
            if story.group(1).lower() == "x":
                done += 1
        elif in_progress is None and line.startswith("> in-progress:"):
            value = line.split(":", 1)[1].strip()
            if value.upper().startswith("S") and value[1:].isdigit():
                in_progress = value[1:]
    return GoalProgress(status, total, done, in_progress)


def _goal_usage() -> None:
    """打印 /goal 子命令用法表（缺参 / 未实现 / 拼错时）。"""
    click.echo(
        "/goal 用法：\n"
        "  /goal <目标描述>      新建 goal 并执行 planning 规程\n"
        "  /goal new <目标描述>  同上（显式 new 形式）\n"
        "  /goal next            推进下一条 story（每步全新会话）\n"
        "  /goal status          查看进度与 GOAL.md 全文\n"
        "  /goal reset           清除 current 指针（goal 目录保留）\n"
        f"  /goal run             连续推进 goal（最多 {_GOAL_RUN_MAX_ROUNDS} 步；Ctrl+C 可中断）\n"
        "  /goal auto            尚未实现（Story 41.3）",
        err=True,
    )


def _goal_skill_text() -> str | None:
    """路径直读 goal skill 正文（不走 SkillStore 相似度匹配）；缺失/不可读/解码失败返回 None。"""
    try:
        return _GOAL_SKILL_PATH.read_text(encoding="utf-8")
    except (OSError, ValueError):  # ValueError 覆盖 UnicodeDecodeError（GBK 存档，P1-23 先例）
        return None


def _goal_active_md() -> Path | None:
    """解析活跃 goal 的 GOAL.md 路径；指针缺失/解码失败返回 None，内容非法显性报错。"""
    try:
        goal_id = (_GOALS_DIR / "current").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] 显性失败：current 指针读取失败（{exc}）。", err=True)
        return None
    if not goal_id:
        return None
    # 指针内容须为 8 位小写十六进制（与写入格式一致）：防手改指针以 ../.. 或绝对路径
    # 把围栏外任意文件当 GOAL.md 注入 LLM prompt（仿 sandbox_session_dir 先例）。
    if len(goal_id) != 8 or any(c not in _GOAL_HEX for c in goal_id):
        click.echo(f"[goal] current 指针内容非法：{goal_id!r}（须为 8 位十六进制 goal_id）。", err=True)
        return None
    goals_root = _GOALS_DIR.resolve()
    goal_root = (_GOALS_DIR / goal_id).resolve()
    if not goal_root.is_relative_to(goals_root):
        click.echo("[goal] current 指针解析后越过 goals 根目录。", err=True)
        return None
    return goal_root / "GOAL.md"


def _goal_read_md(goal_md: Path) -> tuple[str, GoalProgress] | None:
    """读 GOAL.md 并扫描标记；缺失/不合规时显性报错并返回 None（目录保留可重试）。"""
    try:
        text = goal_md.read_text(encoding="utf-8")
    except FileNotFoundError:
        click.echo(f"[goal] 显性失败：GOAL.md 缺失（{goal_md}）——会话未落盘。目录保留，可重试。", err=True)
        return None
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] 显性失败：GOAL.md 读取失败（{exc}）。目录保留，可重试。", err=True)
        return None
    progress = _scan_goal_md(text)
    if progress.status is None:
        click.echo(
            "[goal] 显性失败：GOAL.md 首非空行须为「status: planning|executing|done|blocked」。目录保留，可重试。",
            err=True,
        )
        return None
    return text, progress


async def _goal_session(
    provider: BaseProvider,
    engine: EngineContainer | None,
    prompt: str,
    *,
    metadata: dict[str, Any] | None = None,
    max_iterations: int | None = None,
) -> SubAgentResult | None:
    """开一个**全新** SubAgent 会话执行一个 goal 步骤（非流式，流式 deferred）。

    每次 ``run()`` 新建 AgentLoop+RunContext；``window_reset`` 按设置阈值启用（长会话
    清窗续跑）。Ctrl+C / 任务取消不崩出交互层：捕获后回显「状态在盘」并返回 None。
    """
    from heagent.agent.sub import SubAgent  # noqa: PLC0415

    agent = SubAgent(
        provider,
        engine=engine,
        metadata=metadata,
        max_iterations=max_iterations if max_iterations is not None else get_settings().goal_max_iterations,
        window_reset=WindowResetConfig(threshold=get_settings().window_reset_threshold),
    )
    try:
        return await agent.run(prompt)
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("[goal] 已中断：状态在盘（GOAL.md），/goal next 可续跑。", err=True)
        return None


def _goal_workflow_store(goal_md: Path) -> WorkflowCheckpointStore:
    return WorkflowCheckpointStore(
        str(goal_md.parent / "checkpoints"),
        workflow_path=str(goal_md.parent / "workflow.json"),
    )


async def _goal_pause() -> None:
    goal_md = _goal_active_md()
    if goal_md is None or not goal_md.exists():
        click.echo("[goal] no active goal available to pause", err=True)
        return
    store = _goal_workflow_store(goal_md)
    try:
        state = await store.load_workflow() or GoalWorkflowState(goal_id=goal_md.parent.name)
        if state.status is WorkflowStatus.WAITING_USER:
            click.echo("[goal] already paused; use /goal resume to continue", err=True)
            return
        paused = WorkflowOrchestrator.wait_for_user(state, "user requested pause; resume to continue")
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=f"{state.goal_id}-pause",
            goal_id=state.goal_id,
            phase=paused.phase,
            status=paused.status,
            run_id=f"manual-{state.goal_id}",
            active_skill=paused.active_skill,
            active_step=paused.active_step,
            active_story=paused.active_story,
            artifact_refs=list(paused.artifact_refs),
            next_action=paused.next_action,
        )
        await store.save(checkpoint, paused)
    except WorkflowCheckpointError as exc:
        click.echo(f"[goal] checkpoint failed: {exc}", err=True)
        return
    click.echo(f"[goal] paused: phase={paused.phase.value}, step={paused.active_step or '-'}", err=True)


async def _goal_resume() -> None:
    goal_md = _goal_active_md()
    if goal_md is None or not goal_md.exists():
        click.echo("[goal] no active goal available to resume", err=True)
        return
    store = _goal_workflow_store(goal_md)
    try:
        state = await store.load_workflow()
        if state is None:
            click.echo("[goal] no workflow checkpoint; use /goal next first", err=True)
            return
        if state.status is not WorkflowStatus.WAITING_USER:
            click.echo(f"[goal] workflow status={state.status.value}; resume is not required", err=True)
            return
        resumed = GoalWorkflowState.model_validate(
            state.model_copy(update={"status": WorkflowStatus.RUNNING, "next_action": ""})
        )
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=f"{state.goal_id}-resume-{state.active_step or 0}",
            goal_id=state.goal_id,
            phase=resumed.phase,
            status=resumed.status,
            run_id=f"manual-{state.goal_id}",
            active_skill=resumed.active_skill,
            active_step=resumed.active_step,
            active_story=resumed.active_story,
            artifact_refs=list(resumed.artifact_refs),
        )
        await store.save(checkpoint, resumed)
    except WorkflowCheckpointError as exc:
        click.echo(f"[goal] resume failed: {exc}", err=True)
        return
    click.echo(f"[goal] resumed: phase={resumed.phase.value}, step={resumed.active_step or '-'}", err=True)


async def _goal_status() -> None:
    """打印活跃 goal 进度（done/total + status）与 GOAL.md 全文。"""
    goal_md = _goal_active_md()
    if goal_md is None:
        click.echo("[goal] 无活跃 goal。用 /goal new <目标描述> 新建；/goal next 或 /goal run 可继续推进。", err=True)
        return
    read = _goal_read_md(goal_md)
    if read is None:
        return
    text, prog = read
    click.echo(f"[goal] 进度：{prog.done}/{prog.total} 条 story 已完成（status: {prog.status}）", err=True)
    try:
        workflow = await _goal_workflow_store(goal_md).load_workflow()
    except WorkflowCheckpointError as exc:
        click.echo(f"[goal] workflow state corrupted: {exc}", err=True)
        workflow = None
    if workflow is not None:
        click.echo(
            f"[goal] workflow: phase={workflow.phase.value} status={workflow.status.value} "
            f"skill={workflow.active_skill or '-'} step={workflow.active_step or '-'} "
            f"segment={workflow.segment_index} cumulative_tokens={workflow.cumulative_tokens} "
            f"next={workflow.next_action or '-'}",
            err=True,
        )
    click.echo(text)


async def _goal_audit(engine: EngineContainer | None) -> None:
    goal_md = _goal_active_md()
    if goal_md is None:
        click.echo("[goal] no active goal available for audit", err=True)
        return
    goal_id = goal_md.parent.name
    if engine is None:
        click.echo("[goal] audit unavailable without engine", err=True)
        return
    records = [record for record in await engine.ledger.list_records() if record.metadata.get("goal_id") == goal_id]
    events = [
        event
        for event in engine.events.recent_events
        if event.details.get("goal_id") == goal_id or event.run_id == goal_id
    ]
    click.echo(f"[goal] audit: goal={goal_id} records={len(records)} events={len(events)}", err=True)
    for record in records:
        click.echo(
            f"  record={record.key} status={record.status.value} run={record.run_id or '-'} "
            f"started={record.started_at} finished={record.finished_at or '-'} error={record.error or '-'}",
            err=True,
        )
    for event in events:
        click.echo(
            f"  event={event.event_type} run={event.run_id or '-'} at={event.timestamp} details={event.details}",
            err=True,
        )


def _goal_reset() -> None:
    """清除 current 指针（不删任何其他文件）；goal 目录保留并回显路径。"""
    try:
        (_GOALS_DIR / "current").unlink(missing_ok=True)  # missing_ok：竞态下指针已消失视为已清
    except OSError as exc:
        click.echo(f"[goal] 落盘失败：清除 current 指针失败（{exc}）。", err=True)
        return
    click.echo(f"[goal] current 指针已清除；goal 目录保留：{_GOALS_DIR.resolve()}", err=True)


def _goal_planning_prompt(skill: str, description: str, goal_md: Path) -> str:
    """planning 会话 prompt（确定性拼接：skill 正文 + 任务段 + 目标 + GOAL.md 绝对路径）。"""
    return f"{skill}\n\n# 任务：执行 planning 规程\n目标：{description}\nGOAL.md 路径：{goal_md.resolve()}"


async def _goal_run_planning(
    provider: BaseProvider, engine: EngineContainer | None, skill: str, description: str, goal_md: Path
) -> bool | None:
    """跑 planning 会话并做产物校验收口（``_goal_new`` 与 goal.txt 恢复路径共用）。"""
    result = await _goal_session(
        provider,
        engine,
        _goal_planning_prompt(skill, description, goal_md),
        metadata={"goal_id": goal_md.parent.name, "goal_kind": "planning"},
    )
    if result is None:
        return None
    if not result.success:
        click.echo(f"[goal] planning 会话失败：{result.output}", err=True)
        return False
    click.echo(result.output)
    read = _goal_read_md(goal_md)
    if read is None:
        return False
    _, prog = read
    if prog.status != "executing" or prog.total < 1:
        click.echo(
            f"[goal] 显性失败：planning 产物不合规（要求 status=executing 且 ≥1 条 story，"
            f"实际 status={prog.status}、story={prog.total} 条）。目录保留，可重试。",
            err=True,
        )
        return False
    click.echo(f"[goal] planning 完成：{prog.done}/{prog.total} 条 story。用 /goal next 推进。", err=True)
    return True


async def _goal_new(
    provider: BaseProvider,
    engine: EngineContainer | None,
    skill: str,
    description: str,
    *,
    cron_store: JobStore | None = None,
) -> None:
    """新建 goal（goal.txt + current 原子写）并跑 planning 会话，扫描校验产物。"""
    previous = _goal_active_md()
    goal_id = uuid.uuid4().hex[:8]
    goal_dir = _GOALS_DIR / goal_id
    for _ in range(100):
        if not goal_dir.exists():
            break
        goal_id = uuid.uuid4().hex[:8]
        goal_dir = _GOALS_DIR / goal_id
    else:
        click.echo("[goal] 显性失败：无法分配未占用的 goal_id（UUID 前缀持续碰撞）。", err=True)
        return
    try:
        atomic_write_text(goal_dir / "goal.txt", description)
        atomic_write_text(_GOALS_DIR / "current", goal_id)
    except (OSError, ValueError) as exc:
        click.echo(f"[goal] 落盘失败：{exc}", err=True)
        return
    if previous is not None and cron_store is not None:
        removed = _goal_auto_remove(cron_store, previous.parent.name)
        if removed:
            click.echo(f"[goal] 已清理旧 goal {previous.parent.name} 的 {removed} 个 auto job。", err=True)
    await _goal_run_planning(provider, engine, skill, description, goal_dir / "GOAL.md")


async def _goal_advance(provider: BaseProvider, engine: EngineContainer | None, skill: str) -> str:  # noqa: C901
    """推进一条 story：prompt=skill 正文 + GOAL.md 全文 + 单 story 指令，全新会话执行。"""
    goal_md = _goal_active_md()
    if goal_md is None:
        click.echo("[goal] 无活跃 goal。用 /goal new <目标描述> 新建；/goal next 或 /goal run 可继续推进。", err=True)
        return _GOAL_FAILED
    if not goal_md.exists():
        # goal.txt 恢复路径：GOAL.md 缺失（planning 未落盘）时用原始描述重跑 planning，
        # 复用现有 goal_id/goal_dir（不建新目录、不动 current 指针）。
        description = None
        try:
            text = (goal_md.parent / "goal.txt").read_text(encoding="utf-8").strip()
            if text:
                description = text
        except (OSError, ValueError):
            pass
        if description is None:
            _goal_read_md(goal_md)  # 无恢复路径（goal.txt 亦缺失）：显性报「GOAL.md 缺失」
            return _GOAL_FAILED
        click.echo("[goal] GOAL.md 缺失，用 goal.txt 原始描述重跑 planning。", err=True)
        planning = await _goal_run_planning(provider, engine, skill, description, goal_md)
        return _GOAL_FAILED if planning is not True else _GOAL_ADVANCED
    read = _goal_read_md(goal_md)
    if read is None:
        return _GOAL_FAILED
    text, prog = read
    if prog.status in ("blocked", "planning"):
        click.echo(f"[goal] 当前 goal status={prog.status}，停止推进；请先处理状态。", err=True)
        return _GOAL_FAILED
    if prog.status == "done" or (prog.total > 0 and prog.done >= prog.total):
        click.echo(f"[goal] 全部 story 已完成（{prog.done}/{prog.total}，status: {prog.status}），不开会话。", err=True)
        return _GOAL_DONE
    if prog.total < 1:
        click.echo("[goal] GOAL.md 无 story 可推进（0 条 checkbox）。目录保留，可重试。", err=True)
        return _GOAL_FAILED
    prompt = f"{skill}\n\n# 任务：执行 story 规程（仅一条）\nGOAL.md 路径：{goal_md.resolve()}\n\n{text}"
    result = await _goal_session(
        provider,
        engine,
        prompt,
        metadata={"goal_id": goal_md.parent.name, "goal_kind": "story"},
    )
    if result is None:
        return _GOAL_FAILED
    if not result.success:
        click.echo(f"[goal] story 会话失败：{result.output}", err=True)
        return _GOAL_FAILED
    click.echo(result.output)
    read = _goal_read_md(goal_md)
    if read is None:
        return _GOAL_FAILED
    _, after = read
    click.echo(f"[goal] 进度：{after.done}/{after.total}（status: {after.status}）", err=True)
    # run 白跑可检测（纯读侧对比，不写 GOAL.md）：零变化显性告警；全部勾选但 status 未翻 done 提示。
    if after.status in ("blocked", "planning"):
        click.echo(f"[goal] 会话后 status 变为 {after.status}，停止推进。", err=True)
        return _GOAL_FAILED
    if after.done < prog.done or after.total < prog.total:
        click.echo(f"[goal] 进度回退：此前 {prog.done}/{prog.total}，现在 {after.done}/{after.total}。", err=True)
        return _GOAL_FAILED
    if after.status == "done":
        return _GOAL_DONE
    if after.total > 0 and after.done == after.total:
        click.echo("[goal] 全部 story 已勾选但 status 未翻 done（skill 契约遗漏）；按完成处理。", err=True)
        return _GOAL_DONE
    if after.done == prog.done:
        click.echo("[goal] 会话未推进任何 story（GOAL.md 无 story 净完成）。", err=True)
        return _GOAL_STALLED
    return _GOAL_ADVANCED


async def _goal_next(provider: BaseProvider, engine: EngineContainer | None, skill: str) -> None:
    """推进一个 story；保留旧 slash 命令的无返回值接口。"""
    await _goal_advance(provider, engine, skill)


async def _goal_run(provider: BaseProvider, engine: EngineContainer | None, skill: str) -> None:
    """连续推进 goal，遇到完成、失败、停滞或规划状态立即停止。"""
    try:
        for round_no in range(1, _GOAL_RUN_MAX_ROUNDS + 1):
            click.echo(f"[goal] run 第 {round_no}/{_GOAL_RUN_MAX_ROUNDS} 步", err=True)
            async with _goal_auto_lock:
                outcome = await _goal_advance(provider, engine, skill)
            if outcome == _GOAL_DONE:
                click.echo(f"[goal] run 完成：共 {round_no} 步。", err=True)
                return
            if outcome != _GOAL_ADVANCED:
                return
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("[goal] 已中断：状态在盘（GOAL.md），/goal next 可继续跑（也可用 /goal run 继续推进）。", err=True)
        return
    click.echo(
        f"[goal] run 触顶：连续 {_GOAL_RUN_MAX_ROUNDS} 步推进仍未达到 done。GOAL.md 状态保留，可再次 /goal run 继续。",
        err=True,
    )


def _goal_auto_remove(store: JobStore, goal_id: str) -> int:
    removed = 0
    for job in store.list_jobs():
        if job.prompt == f"{_GOAL_AUTO_PREFIX}{goal_id}" and store.remove(job.id):
            removed += 1
    return removed


def _goal_auto_goal_id(prompt: str) -> str | None:
    """Return the exact goal id from a scheduler-owned auto prompt, if any."""
    if not prompt.startswith(_GOAL_AUTO_PREFIX):
        return None
    goal_id = prompt[len(_GOAL_AUTO_PREFIX) :].strip()
    if len(goal_id) == 8 and all(char in _GOAL_HEX for char in goal_id):
        return goal_id
    return None


async def _goal_cron_advance(
    provider: BaseProvider, engine: EngineContainer | None, store: JobStore, goal_id: str
) -> None:
    """Run one scheduled goal step under the same process lock as manual commands."""
    async with _goal_auto_lock:
        current = _goal_active_md()
        if current is None or current.parent.name != goal_id:
            removed = _goal_auto_remove(store, goal_id)
            if removed:
                click.echo(f"[goal] auto 已收口：goal {goal_id} 已非当前 goal，注销 {removed} 个 job。", err=True)
            return
        try:
            declarative_workflow = _goal_declarative_workflow()
        except ValueError as exc:
            click.echo(f"[goal] auto stopped: {exc}", err=True)
            _goal_auto_remove(store, goal_id)
            return
        if declarative_workflow is not None:
            outcome = await _goal_declarative_advance(provider, engine, declarative_workflow)
            if outcome in {_GOAL_DONE, _GOAL_FAILED}:
                removed = _goal_auto_remove(store, goal_id)
                click.echo(f"[goal] declarative auto closed: goal {goal_id}, removed {removed} job(s)", err=True)
            return
        skill = _goal_skill_text()
        if skill is None:
            click.echo("[goal] auto 停止：缺少 .heagent/skills/goal/SKILL.md，注销 auto job。", err=True)
            _goal_auto_remove(store, goal_id)
            return
        outcome = await _goal_advance(provider, engine, skill)
        after = _goal_read_md(current)
        if outcome == _GOAL_DONE or (after is not None and after[1].status == "blocked"):
            removed = _goal_auto_remove(store, goal_id)
            click.echo(f"[goal] auto 已收口：goal {goal_id}，注销 {removed} 个 job。", err=True)


async def _goal_runner(  # noqa: C901
    provider: BaseProvider,
    engine: EngineContainer | None,
    args: str,
    *,
    cron_store: JobStore | None = None,
) -> None:
    """/goal 子命令族总入口：skill 缺失守卫 → 子命令解析分发。

    首 token 命中子命令集合（new/next/run/auto/status/reset）即子命令；否则整段
    args 视为目标描述（等价 ``new``——中文目标常为单 token，无法与「拼错的子命令」
    结构性区分，故按 Design Notes 解析契约一律视为描述）。``run``/``auto`` 属保留
    子命令但 41.2/41.3 未实现，回用法表；保留字（new 除外）带尾文本时同样回用法表，
    防尾文本被静默吞掉。
    """
    try:
        declarative_workflow = _goal_declarative_workflow()
    except ValueError as exc:
        click.echo(f"[goal] {exc}", err=True)
        return
    if declarative_workflow is not None:
        await _goal_declarative_dispatch(provider, engine, declarative_workflow, args, cron_store=cron_store)
        return
    skill = _goal_skill_text()
    if skill is None:
        click.echo(
            "[goal] 缺少 skill：.heagent/skills/goal/SKILL.md 不存在（工作流方法论契约）。\n"
            "请创建该文件，frontmatter 最小示例：\n"
            "  ---\n  name: goal\n  description: 目标驱动开发工作流契约\n  ---\n"
            "正文写 GOAL.md 状态文件格式与 planning/story 规程。",
            err=True,
        )
        return
    parts = args.split(None, 1)
    head = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not parts:
        await _goal_status()
    elif head == "new":
        if rest:
            async with _goal_auto_lock:
                await _goal_new(provider, engine, skill, rest, cron_store=cron_store)
        else:
            _goal_usage()
    elif head in ("next", "status", "reset", "run", "pause", "resume", "audit") and rest:
        _goal_usage()  # 保留字带尾文本：显性拒绝，防尾文本被静默吞掉
    elif head == "status":
        await _goal_status()
    elif head == "reset":
        _goal_reset()
    elif head == "next":
        async with _goal_auto_lock:
            await _goal_next(provider, engine, skill)
    elif head == "run":
        await _goal_run(provider, engine, skill)
    elif head == "pause":
        await _goal_pause()
    elif head == "resume":
        await _goal_resume()
    elif head == "audit":
        await _goal_audit(engine)
    elif head == "auto":
        goal_md = _goal_active_md()
        if rest == "off":
            if cron_store is None:
                click.echo("[goal] cron 未启用，无法注销 auto job。", err=True)
            elif goal_md is None:
                click.echo("[goal] 无活跃 goal。", err=True)
            else:
                removed = _goal_auto_remove(cron_store, goal_md.parent.name)
                click.echo(f"[goal] auto 已关闭：注销 {removed} 个 job。", err=True)
        elif cron_store is None:
            click.echo("[goal] cron 未启用；请设置 CRON_ENABLED=true 后重试。/goal next 可手动推进。", err=True)
        elif goal_md is None:
            click.echo("[goal] 无活跃 goal。请先使用 /goal new <目标描述>。", err=True)
        else:
            read = _goal_read_md(goal_md)
            if read is None:
                return
            _, progress = read
            if progress.status == "done" or (progress.total > 0 and progress.done >= progress.total):
                click.echo(
                    "[goal] \u5f53\u524d goal \u5df2\u5b8c\u6210\uff0c\u4e0d\u6ce8\u518c auto job\u3002", err=True
                )
                return
            schedule = rest or _GOAL_AUTO_DEFAULT_CRON
            try:
                fields = schedule.split()
                if len(fields) != 5:
                    raise ValueError("cron 必须为 5 字段标准表达式")
                if any(not field or any(not part.strip() for part in field.split(",")) for field in fields):
                    raise ValueError("cron 字段不能包含空的逗号分段")
                cron_matches(schedule, datetime.now(UTC))
            except (TypeError, ValueError) as exc:
                click.echo(f"[goal] 非法 cron 表达式：{exc}", err=True)
            else:
                goal_id = goal_md.parent.name
                _goal_auto_remove(cron_store, goal_id)
                job = cron_store.create_job(f"{_GOAL_AUTO_PREFIX}{goal_id}", schedule)
                cron_store.add(job)
                click.echo(f"[goal] auto 已注册：{job.id}，schedule={schedule!r}。", err=True)
    else:
        async with _goal_auto_lock:
            await _goal_new(provider, engine, skill, args.strip(), cron_store=cron_store)


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
            click.echo("[route] Smart routing not enabled (set ROUTING_ENABLED=true).", err=True)
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
        click.echo(
            f"  last decision: {routing.last_decision.provider} ({routing.last_decision.reason})",
            err=True,
        )
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

# Register gui subcommand (lazy import to avoid loading Textual on non-GUI paths)
try:
    from heagent.gui.cli import gui_cmd

    main.add_command(gui_cmd)
except ImportError:
    pass
