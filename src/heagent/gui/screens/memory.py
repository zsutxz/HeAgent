"""MemoryScreen — 记忆/画像浏览面板（只读 Tab 切换）。

Story 27-3：事实记忆（MEMORY.md）+ 用户画像（USER.md），只读展示。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

if TYPE_CHECKING:
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore


class MemoryScreen(Screen):
    """记忆/画像浏览面板。"""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
    ]

    def __init__(
        self,
        facts: FactStore | None = None,
        profile: ProfileStore | None = None,
    ) -> None:
        super().__init__()
        self._facts = facts
        self._profile = profile

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("事实记忆"):
                yield Static(self._load_facts(), id="facts-content")
            with TabPane("用户画像"):
                yield Static(self._load_profile(), id="profile-content")
        yield Footer()

    def _load_facts(self) -> str:
        if self._facts is None:
            return "[dim]FactStore 未初始化[/]"
        facts = self._facts.load()
        if not facts:
            return "[dim]暂无事实记忆。Agent 可通过 fact_add 工具自动记录。[/]"
        lines = ["[bold]已记录的事实:[/]\n"]
        for f in facts:
            lines.append(f"- {f}")
        return "\n".join(lines)

    def _load_profile(self) -> str:
        if self._profile is None:
            return "[dim]ProfileStore 未初始化[/]"
        sections = self._profile.load()
        if not sections:
            return "[dim]暂无用户画像。Agent 可通过 profile_update 工具自动更新。[/]"
        lines = ["[bold]用户画像:[/]\n"]
        for section, value in sorted(sections.items()):
            lines.append(f"[bold]{section}[/]: {value}")
        return "\n".join(lines)
