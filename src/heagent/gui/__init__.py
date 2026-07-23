"""HeAgent GUI — Textual terminal interface.

``gui_main()`` 是 Textual TUI 的统一入口：构建 Provider / AgentLoop /
AgentBridge / GuiState / HeAgentApp，然后进入 Textual 事件循环。
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
    # 复用 cli.py 的 Provider 构建逻辑（单一真源）
    from heagent.cli import _build_provider

    provider = _build_provider(settings, model)

    # ── AgentLoop ───────────────────────────────────────────
    from heagent.agent.loop import AgentLoop
    from heagent.engine import EngineContainer
    from heagent.tools.registry import ToolRegistry

    engine = EngineContainer.default(workspace_root=None, sandbox_backend=sandbox or settings.sandbox_backend)

    loop = AgentLoop(
        provider,
        registry=ToolRegistry.get(),
        engine=engine,
        context_dir=None,
    )

    # ── GUI 状态 + 桥接 ─────────────────────────────────────
    state = GuiState(
        model_name=provider.get_metadata().model,
        max_iterations=settings.max_iterations,
    )
    bridge = AgentBridge(loop, state, event_bus=engine.events)

    # ── 启动 Textual ────────────────────────────────────────
    app = HeAgentApp(bridge, state, loop=loop)
    app.run()
