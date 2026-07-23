"""Textual App — root application shell.

持有 AgentLoop / AgentBridge / GuiState + 全部 Stores，管理多页面导航。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.widgets import Footer

from heagent.gui.bridge import AgentBridge
from heagent.gui.screens.chat import ChatScreen
from heagent.gui.state import GuiState

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.cron.jobs import JobStore
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore


class HeAgentApp(App):
    """HeAgent terminal UI application.

    绑定 F1-F6 快速导航到各管理页面。
    """

    TITLE = "HeAgent"
    SUB_TITLE = "A self-improving AI Agent"

    BINDINGS = [
        ("f1", "switch_to_chat", "聊天"),
        ("f2", "switch_to_skills", "技能"),
        ("f3", "switch_to_cron", "Cron"),
        ("f4", "switch_to_memory", "记忆"),
        ("f5", "switch_to_runs", "运行"),
        ("f6", "switch_to_logs", "日志"),
        ("ctrl+q", "quit", "退出"),
    ]

    def __init__(
        self,
        bridge: AgentBridge,
        state: GuiState,
        *,
        loop: AgentLoop | None = None,
        skill_store: SkillStore | None = None,
        job_store: JobStore | None = None,
        fact_store: FactStore | None = None,
        profile_store: ProfileStore | None = None,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._state = state
        self._loop = loop
        self.skill_store = skill_store
        self.job_store = job_store
        self.fact_store = fact_store
        self.profile_store = profile_store

    def on_mount(self) -> None:
        """Push the main chat screen on startup."""
        self.push_screen(ChatScreen(self._bridge, self._state))

    def compose(self) -> ComposeResult:
        yield Footer()

    # ── 导航动作 ───────────────────────────────────────────

    def action_switch_to_chat(self) -> None:
        self._switch_or_push(ChatScreen(self._bridge, self._state))

    def action_switch_to_skills(self) -> None:
        from heagent.gui.screens.skills import SkillScreen
        self._switch_or_push(SkillScreen(self.skill_store))

    def action_switch_to_cron(self) -> None:
        from heagent.gui.screens.cron import CronScreen
        self._switch_or_push(CronScreen(self.job_store))

    def action_switch_to_memory(self) -> None:
        from heagent.gui.screens.memory import MemoryScreen
        self._switch_or_push(MemoryScreen(self.fact_store, self.profile_store))

    def action_switch_to_runs(self) -> None:
        from heagent.gui.screens.runs import RunsScreen
        self._switch_or_push(RunsScreen())

    def action_switch_to_logs(self) -> None:
        from heagent.gui.screens.event_log import EventLogScreen
        self._switch_or_push(EventLogScreen())

    def _switch_or_push(self, screen) -> None:
        """若目标 Screen 已在栈中 → pop 到它；否则 push 新实例。"""
        for s in self._screen_stack:
            if type(s) is type(screen):
                self.pop_screen()
                # 如果 pop 后栈顶不是 chat，而目标是 chat → 保留
                return
        self.push_screen(screen)

    def action_quit(self) -> None:
        """Ctrl+Q 退出：先中断 Agent，再退出。"""
        self._bridge.cancel()
        super().action_quit()
