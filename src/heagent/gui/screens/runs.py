"""RunsScreen — 运行历史面板（Epic 28-2/3）。

Tree 渲染运行树（RunStore.build_run_tree），选中节点查看详情/恢复运行。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static, Tree

if TYPE_CHECKING:
    from heagent.engine import EngineContainer


class RunsScreen(Screen):
    """运行历史面板。"""

    BINDINGS = [
        ("escape", "app.pop_screen", "返回"),
    ]

    CSS = """
    RunsScreen {
        layout: vertical;
    }
    #runs-body {
        height: 1fr;
    }
    #run-tree {
        width: 40;
        border-right: solid $primary;
    }
    #run-detail {
        width: 1fr;
        padding: 1;
    }
    Static.detail-label {
        text-style: bold;
        color: $text-muted;
    }
    """

    def __init__(self, engine: EngineContainer | None = None) -> None:
        super().__init__()
        self._engine = engine

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="runs-body"):
            yield Tree("运行", id="run-tree")
            with Vertical(id="run-detail"):
                yield Static("[dim]← 选择左侧运行查看详情[/]", id="detail-content")
                yield Button("恢复运行", id="btn-resume", variant="primary", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self._load_tree()

    def _load_tree(self) -> None:
        """从 RunStore 加载运行树。"""
        tree = self.query_one("#run-tree", Tree)
        tree.clear()
        root = tree.root
        root.set_label("📋 运行历史")

        if self._engine is None:
            root.add("引擎未初始化")
            return

        import asyncio

        async def _fetch():
            store = self._engine.run_store
            roots = await store.build_run_tree()
            self._populate_tree(roots)

        asyncio.create_task(_fetch())

    def _populate_tree(self, roots: list) -> None:
        tree = self.query_one("#run-tree", Tree)
        for rn in roots:
            status_icon = self._icon(rn.status)
            label = f"{status_icon} {rn.run_id[:8]}"
            node = tree.root.add(label)
            node.data = rn  # 存引用，选中时取
            for child in rn.children:
                c_icon = self._icon(child.status)
                c_label = f"{c_icon} {child.run_id[:8]}"
                c_node = node.add(c_label)
                c_node.data = child

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """选中节点 → 展示详情。"""
        data = event.node.data
        if data is None:
            return
        detail = self.query_one("#detail-content", Static)
        btn = self.query_one("#btn-resume", Button)

        lines = [
            f"[bold]Run ID:[/] {data.run_id}",
            f"[bold]Parent:[/] {data.parent_run_id or '— (根运行)'}",
            f"[bold]状态:[/] {self._status_text(data.status)}",
        ]
        detail.update("\n".join(lines))
        btn.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "btn-resume":
            return
        tree = self.query_one("#run-tree", Tree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return
        run_id = node.data.run_id
        detail = self.query_one("#detail-content", Static)

        async def _resume():
            from heagent.gui.app import HeAgentApp
            app = HeAgentApp.get_current_app()
            if not isinstance(app, HeAgentApp) or app.agent_loop is None:
                detail.update("[red]无法恢复：AgentLoop 未初始化[/]")
                return
            try:
                result = await app.agent_loop.resume(run_id)
                detail.update(f"[green]运行 {run_id[:8]} 恢复完成[/]\n\n{result[:500]}")
                self._load_tree()
            except Exception as exc:
                detail.update(f"[red]恢复失败: {exc}[/]")

        import asyncio
        asyncio.create_task(_resume())

    @staticmethod
    def _icon(status) -> str:
        if status is None:
            return "⬜"
        name = getattr(status, "value", str(status))
        if "COMPLETED" in name:
            return "✅"
        if "FAILED" in name:
            return "❌"
        if "RUNNING" in name:
            return "⏳"
        return "⬜"

    @staticmethod
    def _status_text(status) -> str:
        if status is None:
            return "未知"
        name = getattr(status, "value", str(status))
        return name
