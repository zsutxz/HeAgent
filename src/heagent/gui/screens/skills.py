"""SkillScreen — 技能管理面板（DataTable + 详情/创建弹窗）。

Story 27-2：列出所有技能，查看详情，创建/归档/删除。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static, TextArea

if TYPE_CHECKING:
    from heagent.memory.skills import SkillStore


class SkillScreen(Screen):
    """技能管理面板。"""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
    ]

    CSS = """
    SkillScreen {
        layout: vertical;
    }
    #skill-table {
        height: 1fr;
    }
    #skill-actions {
        height: auto;
        padding: 1;
    }
    """

    def __init__(self, store: SkillStore | None = None) -> None:
        super().__init__()
        self._store = store

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="skill-table")
        with Container(id="skill-actions"):
            with Horizontal():
                yield Button("新建技能", id="btn-create", variant="primary")
                yield Button("查看详情", id="btn-detail")
                yield Button("归档过期", id="btn-archive", variant="warning")
                yield Button("删除", id="btn-delete", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#skill-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("技能名", "描述", "使用次数", "最后使用")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#skill-table", DataTable)
        table.clear()
        if self._store is None:
            return
        for name in self._store.list_skills():
            content = self._store.parse(name)
            if content is None:
                continue
            usage = str(content.usage_count)
            last = content.last_used[:16] if content.last_used else "从未"
            desc = content.description[:40] + ("..." if len(content.description) > 40 else "")
            table.add_row(name, desc, usage, last)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-create":
            self.app.push_screen(_SkillCreateModal(self._store, self._refresh_table))
            return

        table = self.query_one("#skill-table", DataTable)
        row = table.cursor_row
        if row is None:
            return
        name = str(table.get_row_at(row)[0])
        if btn_id == "btn-detail":
            self.app.push_screen(_SkillDetailModal(self._store, name))
        elif btn_id == "btn-archive":
            if self._store:
                self._store.archive(name)
            self._refresh_table()
        elif btn_id == "btn-delete":
            if self._store:
                self._store.delete(name)
            self._refresh_table()


class _SkillDetailModal(ModalScreen[None]):
    """技能详情弹窗 —— 展示 SKILL.md 内容。"""

    CSS = """
    _SkillDetailModal {
        align: center middle;
    }
    #detail-box {
        width: 60;
        height: auto;
        max-height: 80%;
        background: $panel;
        border: solid $primary;
        padding: 1 2;
    }
    """

    def __init__(self, store: SkillStore | None, name: str) -> None:
        super().__init__()
        self._store = store
        self._name = name

    def compose(self) -> ComposeResult:
        raw = self._store.load(self._name) if self._store else "无法加载"
        content = raw if raw else f"技能 '{self._name}' 不存在"
        with Vertical(id="detail-box"):
            yield Static(f"[bold]技能: {self._name}[/]\n\n{content}")
            yield Button("关闭", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss()


class _SkillCreateModal(ModalScreen[None]):
    """新建技能弹窗。"""

    CSS = """
    _SkillCreateModal {
        align: center middle;
    }
    #create-box {
        width: 50;
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 1 2;
    }
    """

    def __init__(self, store: SkillStore | None, refresh_cb) -> None:
        super().__init__()
        self._store = store
        self._refresh = refresh_cb

    def compose(self) -> ComposeResult:
        with Vertical(id="create-box"):
            yield Static("[bold]新建技能[/]")
            yield Label("名称")
            yield Input(placeholder="技能名称 (英文/数字/_-)", id="input-name")
            yield Label("描述")
            yield Input(placeholder="简短描述", id="input-desc")
            yield Label("匹配模式")
            yield Input(placeholder="触发 pattern", id="input-pattern")
            yield Label("步骤 (每行一步)")
            yield TextArea("", id="input-steps")
            yield Button("创建", id="btn-dosave", variant="primary")
            yield Button("取消", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss()
        elif event.button.id == "btn-dosave":
            self._do_create()

    def _do_create(self) -> None:
        name = self.query_one("#input-name", Input).value.strip()
        desc = self.query_one("#input-desc", Input).value.strip()
        pattern = self.query_one("#input-pattern", Input).value.strip()
        area = self.query_one("#input-steps", TextArea)
        steps = [s.strip() for s in area.text.splitlines() if s.strip()]

        if not name or not desc or not pattern:
            return

        if self._store:
            try:
                self._store.save(name, desc, pattern, steps)
            except ValueError:
                pass  # 名称非法时静默忽略
        self._refresh()
        self.dismiss()
