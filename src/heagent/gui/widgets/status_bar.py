"""StatusBar — 模型名 / Token 用量 / 迭代数 / 运行状态。

显示每次调用的 token 用量 vs 上下文窗口上限（非累计）。
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Widget):
    """底部状态栏：模型名 + Token (used/max) + 迭代数 + 运行指示。"""

    model_name: reactive[str] = reactive("")
    iteration: reactive[int] = reactive(0)
    max_iterations: reactive[int] = reactive(50)
    total_tokens: reactive[int] = reactive(0)
    max_context_tokens: reactive[int] = reactive(0)
    is_running: reactive[bool] = reactive(False)
    active_tool: reactive[str] = reactive("")

    def __init__(self, *, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self._label = Static("", id="status-label")

    def compose(self):
        yield self._label

    def watch_model_name(self, value: str) -> None:
        self._refresh()

    def watch_iteration(self, value: int) -> None:
        self._refresh()

    def watch_total_tokens(self, value: int) -> None:
        self._refresh()

    def watch_max_context_tokens(self, value: int) -> None:
        self._refresh()

    def watch_is_running(self, value: bool) -> None:
        self._refresh()

    def watch_active_tool(self, value: str) -> None:
        self._refresh()

    def _refresh(self) -> None:
        parts: list[str] = []
        if self.model_name:
            parts.append(self.model_name)
        if self.is_running:
            if self.active_tool:
                parts.append(f"🔧 {self.active_tool}")
            else:
                parts.append("⏳ 运行中...")
        tok_str = (
            f"{self.total_tokens}/{self.max_context_tokens} tok"
            if self.max_context_tokens > 0
            else f"Tok: {self.total_tokens}"
        )
        parts.append(tok_str)
        if self.iteration > 0:
            parts.append(f"轮: {self.iteration}/{self.max_iterations}")
        self._label.update(" │ ".join(parts))

    def on_mount(self) -> None:
        """初始渲染。"""
        self._refresh()
