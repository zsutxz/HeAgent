"""HeAgent GUI — Textual terminal interface.

``gui_main()`` 是 Textual TUI 的统一入口：构建 Provider / AgentLoop /
AgentBridge / GuiState / HeAgentApp + 全部管理面板 stores，然后进入 Textual 事件循环。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def gui_main(model: str | None = None, sandbox: str | None = None) -> None:
    """Launch the HeAgent Textual TUI.

    Args:
        model: Override default model name.
        sandbox: Sandbox backend (``"passthrough"`` or ``"firejail"``).
    """
    from heagent.config import get_settings
    from heagent.gui.app import HeAgentApp
    from heagent.gui.bridge import AgentBridge
    from heagent.gui.state import GuiState

    settings = get_settings()

    # ── Provider ────────────────────────────────────────────
    from heagent.cli import _build_provider

    provider = _build_provider(settings, model)

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
    from heagent.engine import EngineContainer
    from heagent.tools.registry import ToolRegistry

    engine = EngineContainer.default(workspace_root=None, sandbox_backend=sandbox or settings.sandbox_backend)

    loop = AgentLoop(
        provider,
        registry=ToolRegistry.get(),
        engine=engine,
        skills=skill_store,
        facts=fact_store,
        profile=profile_store,
        cron_store=job_store,
        context_dir=None,
    )

    # ── GUI 状态 + 桥接 ─────────────────────────────────────
    state = GuiState(
        model_name=provider.get_metadata().model,
        max_iterations=settings.max_iterations,
    )
    bridge = AgentBridge(loop, state, event_bus=engine.events)

    # ── 启动 Textual ────────────────────────────────────────
    app = HeAgentApp(
        bridge, state,
        loop=loop,
        skill_store=skill_store,
        job_store=job_store,
        fact_store=fact_store,
        profile_store=profile_store,
    )
    app.run()
