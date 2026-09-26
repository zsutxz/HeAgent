"""入口层装配：provider / engine / AgentLoop / 记忆存储 / plan mode / dream 调度。

**为什么单独成模块**（`heagent/cli/` 包内拆分，2026-09-26）：console.py 曾把「读配置造 runtime」
与「跑 CLI 流程」混在 1252 行里——前者随 provider 接入、路由池、沙箱档位、记忆存储形态变，
后者随交互体验变。

**缝（monkeypatch 模块路径）纪律**：``_build_loop`` 是测试缝，patch 目标随**调用方**分模块——

- 网络入口（``cli/http.py`` / ``cli/tcp.py``）在**函数内**导入它 ⇒ patch 落在本模块
  （``heagent.cli.composition._build_loop``），调用期按属性查找才生效；
- CLI 路径（``cli/interactive.py``）模块级导入 ⇒ 它持有自己的全局，patch 落在
  ``heagent.cli.interactive._build_loop``。

分层：本模块属**入口层**，可依赖 engine/agent/context/memory 与顶层共用模块；不被下层反向导入。
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING, Any

import heagent.tools.builtins  # noqa: F401
from heagent.agent.loop import AgentLoop
from heagent.agent.middleware import make_retry_middleware
from heagent.cli.display import (
    SUBAGENT_ANNOUNCER,
)
from heagent.config import Settings, resolve_runtime_config
from heagent.context.compressor import ContextCompressor
from heagent.context.session import SessionStore
from heagent.context.window_reset import WindowResetConfig
from heagent.cron.jobs import JobStore
from heagent.cron.scheduler import CronScheduler
from heagent.engine import ConsoleApprovalHandler, EngineContainer
from heagent.events.sink import JsonlSink, default_rollout_dir
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.memory.soul import SoulStore
from heagent.providers.router import RoutingProvider
from heagent.providers.switchable import SwitchableProvider
from heagent.pub.workspace import WorkspacePaths
from heagent.tools.registry import ToolRegistry
from heagent.wiring import build_cron_job_runner, ensure_runtime_config

if TYPE_CHECKING:
    from heagent.context.session import SessionStore
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)


def _build_soul(soul_path: str | None = None) -> SoulStore | None:
    """Build the SOUL store from an optional custom path."""
    if soul_path:
        return SoulStore(global_path=soul_path, project_path=soul_path)
    return SoulStore()


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
    enable_cron: bool = True,
) -> tuple[AgentLoop, CronScheduler | None]:
    """Build the loop runtime and optional cron scheduler.

    可选的预构建记忆存储（``skills``/``facts``/``profile``/``soul``）允许调用方与
    后台调度器（如 DreamScheduler）共享同一份存储实例；缺省时各自新建。

    ``enable_cron=False`` 让调用方**显式拒绝**构造 ``CronScheduler``（HTTP 入口用）：注意
    scheduler 的构造条件里含 ``session is not None``，因此「网页侧没有后台调度」在传入会话后
    再也不是 `session=None` 的副作用——必须显式关掉（Story 50-3 的 T6 / 评审 F2）。
    """
    # Phase 1：组装期一次性解析快照；engine 与两类 loop（主/cron）共用同一解析结果。
    config = ensure_runtime_config(engine) if engine is not None else resolve_runtime_config(settings)
    paths = WorkspacePaths.from_root(
        (engine.workspace_root if engine else None) or config.workspace_root or os.getcwd()
    )
    config = resolve_runtime_config(config, workspace_root=str(paths.root))
    skills = skills or SkillStore(str(paths.skills))
    facts = facts or FactStore(str(paths.memory_file))
    profile = profile or ProfileStore(str(paths.profile_file))
    soul = soul or _build_soul(soul_path)
    cron_store = JobStore(str(paths.cron_file)) if config.cron_enabled else None
    compressor, window_reset = _build_context_strategy(config, provider)
    engine = engine or EngineContainer.default(
        workspace_root=str(paths.root), sandbox_backend=sandbox_backend, runtime_config=config
    )
    config = ensure_runtime_config(engine)
    retry_mw = make_retry_middleware(
        max_attempts=config.retry_max_attempts,
        base_delay=config.retry_base_delay,
        max_delay=config.retry_max_delay,
    )

    scheduler: CronScheduler | None = None
    if enable_cron and session is not None and config.cron_enabled and cron_store:
        job_runner = build_cron_job_runner(
            provider,
            engine,
            config,
            cron_store,
            skills=skills,
            facts=facts,
            profile=profile,
            soul=soul,
            max_iterations=max_iterations,
            retry_mw=retry_mw,
            compressor=compressor,
            window_reset=window_reset,
            context_dir=str(paths.root),
            subagent_announcer=SUBAGENT_ANNOUNCER,
        )
        scheduler = CronScheduler(
            cron_store,
            tick_seconds=config.cron_tick_seconds,
            engine=engine,
            job_runner=job_runner,
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
        context_dir=str(paths.root),
        soul=soul,
        cron_store=cron_store,
        engine=engine,
        runtime_config=config,
        subagent_announcer=SUBAGENT_ANNOUNCER,
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


def _prepare_engine(
    *,
    sandbox_backend: str | None,
    sandbox_session_workspace: bool | None,
    sandbox_session_keep: bool | None,
    plan_mode: bool,
    system: str | None,
    tty_approval: bool = False,
) -> tuple[EngineContainer, str | None]:
    """装配引擎容器：审批处理器 + plan mode 约束 + 系统提示词前缀。

    ``tty_approval=True``（单次执行模式）只在**有 TTY** 时装 ``ConsoleApprovalHandler``：
    管道 / CI 里没人能应答审批，装了会把 run 挂住；交互模式（``_run_chat``）本身就在 TTY 上，
    无条件装。

    返回 ``(容器, 可能已加 plan 前缀的 system)``——两者必须同源，拆分调用会出现
    「容器已进只读档、提示词却没说」这类静默不一致。
    """
    engine = EngineContainer.default(
        workspace_root=str(WorkspacePaths.from_root(os.getcwd()).root),
        sandbox_backend=sandbox_backend,
        sandbox_session_workspace=sandbox_session_workspace,
        sandbox_session_keep=sandbox_session_keep,
    )
    if engine.approval_handler is None and (not tty_approval or sys.stdin.isatty()):
        engine.approval_handler = ConsoleApprovalHandler()
    plan_hint = _apply_plan_mode(engine, plan_mode=plan_mode)
    if plan_hint:
        system = f"{plan_hint}\n\n{system}" if system else plan_hint
    return engine, system


def _build_event_sink(settings: Settings, *, json_output: bool) -> JsonlSink | None:
    """构造 JSONL 事件接收器（不需要则返回 None）。

    两个动作互相独立，刻意不做隐式耦合：``--json`` 只负责 stdout（用户可自行重定向成文件），
    rollout 落盘只由 ``EVENTS_ROLLOUT_ENABLED`` 决定（默认关闭——落盘含工具原始输出）。
    """
    stream = sys.stdout if json_output else None
    rollout_dir = default_rollout_dir() if settings.events_rollout_enabled else None
    if stream is None and rollout_dir is None:
        return None
    return JsonlSink(stream=stream, rollout_dir=rollout_dir)


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
    from heagent.memory.dream import DreamResult, DreamScheduler  # noqa: PLC0415
    from heagent.pub.roles import get_role  # noqa: PLC0415

    context_dir = str(WorkspacePaths.from_root(os.getcwd()).root)
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
            announcer=SUBAGENT_ANNOUNCER,
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
