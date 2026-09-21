"""HeAgent GUI — Textual terminal interface.

``gui_main()`` 是 Textual TUI 的统一入口：构建 Provider / AgentLoop /
AgentBridge / GuiState / HeAgentApp + 全部 Stores + 事件观察者，然后进入 Textual 事件循环。
"""

from __future__ import annotations

import logging

import heagent.tools.builtins  # noqa: F401 — 触发 @tool 注册

logger = logging.getLogger(__name__)


def gui_main(
    model: str | None = None,
    sandbox: str | None = None,
    sandbox_session_workspace: bool | None = None,
    sandbox_session_keep: bool | None = None,
) -> None:
    """Launch the HeAgent Textual TUI."""
    from typing import TYPE_CHECKING

    from heagent.config import resolve_runtime_config
    from heagent.gui.app import HeAgentApp
    from heagent.gui.bridge import AgentBridge
    from heagent.gui.observers import GuiEventObserver
    from heagent.gui.state import GuiState

    if TYPE_CHECKING:
        from heagent.engine.context import RunContext

    # Phase 1：组装期一次性解析快照；engine 与两类 loop（主/cron）共用同一解析结果。
    config = resolve_runtime_config()

    # ── Provider ────────────────────────────────────────────
    from heagent.providers.router import active_model, annotate_route
    from heagent.wiring import _build_provider

    provider = _build_provider(config, model)

    # ── Stores ──────────────────────────────────────────────
    from heagent.cron.jobs import JobStore
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore

    skill_store = SkillStore()
    job_store = JobStore()
    fact_store = FactStore()
    profile_store = ProfileStore()

    # ── AgentLoop ───────────────────────────────────────────
    from heagent.agent.loop import AgentLoop
    from heagent.cli_display import SUBAGENT_ANNOUNCER
    from heagent.engine import EngineContainer
    from heagent.tools.registry import ToolRegistry

    engine = EngineContainer.default(
        workspace_root=None,
        sandbox_backend=sandbox or config.sandbox_backend,
        sandbox_session_workspace=sandbox_session_workspace,
        sandbox_session_keep=sandbox_session_keep,
        runtime_config=config,
    )
    resolved = engine.runtime_config
    assert resolved is not None  # __post_init__ 必然完成解析
    config = resolved

    loop = AgentLoop(
        provider,
        registry=ToolRegistry.get(),
        engine=engine,
        runtime_config=config,
        skills=skill_store,
        facts=fact_store,
        profile=profile_store,
        cron_store=job_store,
        context_dir=None,
        subagent_announcer=SUBAGENT_ANNOUNCER,
    )

    # ── GUI 状态 + 桥接 ─────────────────────────────────────
    state = GuiState(
        model_name=annotate_route(provider, active_model(provider) or provider.get_metadata().model),
        max_iterations=config.max_iterations,
    )
    bridge = AgentBridge(loop, state)

    # ── 事件观察者（共享：EventBus→state 更新 + EventLog 缓冲）──
    observer = GuiEventObserver(state)
    engine.events.subscribe(observer)

    # ── Cron 调度器（/goal auto 注册的 goal-advance job 由它驱动；镜像 cli.py 的 _run_job）──
    cron_scheduler = None
    if config.cron_enabled:
        from heagent.agent.middleware import make_retry_middleware
        from heagent.cli_goal import _goal_auto_goal_id, _goal_cron_advance
        from heagent.cron.scheduler import CronScheduler

        retry_mw = make_retry_middleware(
            max_attempts=config.retry_max_attempts,
            base_delay=config.retry_base_delay,
            max_delay=config.retry_max_delay,
        )

        async def _run_job(prompt: str, run_context: RunContext) -> None:
            goal_id = _goal_auto_goal_id(prompt)
            if goal_id is not None:
                await _goal_cron_advance(provider, engine, job_store, goal_id)
                return
            # 非 goal 的 cron prompt：构造一次性 loop（与 GUI 主 loop 共享 stores/engine，
            # 事件经同一 EventBus 到达 GUI 观察者），不与交互中的主 loop 抢占 run_context。
            await AgentLoop(
                provider,
                registry=ToolRegistry.get(),
                engine=engine,
                runtime_config=config,
                skills=skill_store,
                facts=fact_store,
                profile=profile_store,
                cron_store=job_store,
                context_dir=None,
                run_context=run_context,
                middlewares=[retry_mw],
                subagent_announcer=SUBAGENT_ANNOUNCER,
            ).run(prompt)

        cron_scheduler = CronScheduler(
            job_store,
            tick_seconds=config.cron_tick_seconds,
            engine=engine,
            job_runner=_run_job,
        )

    # ── 启动 Textual ────────────────────────────────────────
    app = HeAgentApp(
        bridge,
        state,
        loop=loop,
        skill_store=skill_store,
        job_store=job_store,
        fact_store=fact_store,
        profile_store=profile_store,
        cron_scheduler=cron_scheduler,
    )
    app._event_observer = observer
    app.run()
