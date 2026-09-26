"""HeAgent GUI — Textual terminal interface.

``gui_main()`` 是 Textual TUI 的统一入口：构建 Provider / AgentLoop /
AgentBridge / GuiState / HeAgentApp + 全部 Stores + 事件观察者，然后进入 Textual 事件循环。
"""

from __future__ import annotations

import logging
from pathlib import Path

import heagent.tools.builtins  # noqa: F401 — 触发 @tool 注册

logger = logging.getLogger(__name__)


def gui_main(
    model: str | None = None,
    sandbox: str | None = None,
    sandbox_session_workspace: bool | None = None,
    sandbox_session_keep: bool | None = None,
) -> None:
    """Launch the HeAgent Textual TUI."""
    from heagent.config import resolve_runtime_config
    from heagent.gui.app import HeAgentApp
    from heagent.gui.bridge import AgentBridge
    from heagent.gui.observers import GuiEventObserver
    from heagent.gui.state import GuiState
    from heagent.pub.workspace import WorkspacePaths

    # Phase 1：组装期一次性解析快照；engine 与两类 loop（主/cron）共用同一解析结果。
    paths = WorkspacePaths.from_root(Path.cwd())
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

    skill_store = SkillStore(str(paths.skills))
    # Phase 2 C3（与 CLI 语义统一）：cron 关闭时不创建 JobStore——主 loop 的
    # cron_store 为 None，cron 工具不激活（此前 GUI 无条件创建，cron 关闭时工具
    # 仍可见但无调度器驱动，属装配漂移；经用户确认统一到 CLI 语义）。
    job_store = JobStore(str(paths.cron_file)) if config.cron_enabled else None
    fact_store = FactStore(str(paths.memory_file))
    profile_store = ProfileStore(str(paths.profile_file))

    # ── AgentLoop ───────────────────────────────────────────
    from heagent.agent.loop import AgentLoop
    from heagent.cli.display import SUBAGENT_ANNOUNCER
    from heagent.engine import EngineContainer
    from heagent.tools.registry import ToolRegistry

    engine = EngineContainer.default(
        workspace_root=None,
        sandbox_backend=sandbox or config.sandbox_backend,
        sandbox_session_workspace=sandbox_session_workspace,
        sandbox_session_keep=sandbox_session_keep,
        runtime_config=config,
    )
    from heagent.wiring import build_cron_job_runner, ensure_runtime_config

    config = ensure_runtime_config(engine)

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

    # ── Cron 调度器（/goal auto 注册的 goal-advance job 由它驱动；runner 与 CLI 共享 wiring 工厂）──
    cron_scheduler = None
    if config.cron_enabled and job_store is not None:
        from heagent.agent.middleware import make_retry_middleware
        from heagent.cron.scheduler import CronScheduler

        retry_mw = make_retry_middleware(
            max_attempts=config.retry_max_attempts,
            base_delay=config.retry_base_delay,
            max_delay=config.retry_max_delay,
        )
        # 非 goal 的 cron prompt：一次性 loop 与 GUI 主 loop 共享 stores/engine，
        # 事件经同一 EventBus 到达 GUI 观察者，不与交互中的主 loop 抢占 run_context。
        job_runner = build_cron_job_runner(
            provider,
            engine,
            config,
            job_store,
            skills=skill_store,
            facts=fact_store,
            profile=profile_store,
            retry_mw=retry_mw,
            context_dir=None,
            subagent_announcer=SUBAGENT_ANNOUNCER,
        )
        cron_scheduler = CronScheduler(
            job_store,
            tick_seconds=config.cron_tick_seconds,
            engine=engine,
            job_runner=job_runner,
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
