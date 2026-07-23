"""Textual App — root application shell.

持有 AgentLoop / AgentBridge / GuiState + 全部 Stores + 事件观察者，管理多页面导航。

BridgeMessage 路由：
    AgentBridge.post() → App（本层）→ 当前活动 Screen → ChatScreen 或其他 Screen 各自处理。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.widgets import Footer

from heagent.gui.bridge import AgentBridge, BridgeMessage
from heagent.gui.observers import GuiEventObserver
from heagent.gui.screens.chat import ChatScreen
from heagent.gui.state import GuiState

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.cron.jobs import JobStore
    from heagent.engine import EngineContainer
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore


class HeAgentApp(App):
    """HeAgent terminal UI application. F1-F6 导航到各管理页面。"""

    TITLE = "HeAgent"
    SUB_TITLE = "A self-improving AI Agent"

    # Textual 1.0 无 get_current_app() API（2.x 才有），自行实现。
    _current_app: ClassVar[HeAgentApp | None] = None

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
        # 命名为 _agent_loop 避免与 Textual App._loop（asyncio 事件循环）冲突
        self._agent_loop = loop
        self.skill_store = skill_store
        self.job_store = job_store
        self.fact_store = fact_store
        self.profile_store = profile_store
        # 事件观察者引用（供 EventLog widget 拉取）
        self._event_observer: GuiEventObserver | None = None
        # 注册当前实例 + 回注给 bridge（Textual 1.0 无 get_current_app API）
        HeAgentApp._current_app = self
        bridge.set_app(self)

    @classmethod
    def get_current_app(cls) -> HeAgentApp | None:
        """返回当前 HeAgentApp 单例（模拟 Textual 2.x API）。"""
        return cls._current_app

    @property
    def engine(self) -> EngineContainer | None:
        """EngineContainer，供 RunsScreen 访问 RunStore。"""
        if self._agent_loop:
            return self._agent_loop.engine
        return None

    @property
    def agent_loop(self) -> AgentLoop | None:
        """AgentLoop 实例，供外部 Screen/widget 访问。"""
        return self._agent_loop

    def on_mount(self) -> None:
        """Push the main chat screen on startup."""
        self.push_screen(ChatScreen(self._bridge, self._state))

    def compose(self) -> ComposeResult:
        yield Footer()

    # ── BridgeMessage 路由 ─────────────────────────────────
    # AgentBridge.post() 把 BridgeMessage 投到 App 根节点；
    # Textual 消息只沿 DOM 树向上冒泡，不会向下传播。
    # 因此我们在 App 层拦截，再转发给当前活动 Screen。

    def on_bridge_message(self, message: BridgeMessage) -> None:
        """拦截 BridgeMessage 并转发给当前活动 Screen。"""
        screen = self.screen
        if isinstance(screen, ChatScreen):
            screen.on_bridge_message(message)

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
        self._switch_or_push(RunsScreen(self.engine))

    def action_switch_to_logs(self) -> None:
        from heagent.gui.screens.event_log import EventLogScreen
        self._switch_or_push(EventLogScreen())

    def _switch_or_push(self, screen) -> None:
        """若目标 Screen 已在栈中 → pop 到它；否则 push 新实例。"""
        for s in self._screen_stack:
            if type(s) is type(screen):
                self.pop_screen()
                return
        self.push_screen(screen)

    def action_quit(self) -> None:
        """Ctrl+Q 退出：先中断 Agent，再退出。"""
        self._bridge.cancel()
        super().action_quit()
