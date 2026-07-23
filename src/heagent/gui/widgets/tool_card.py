"""ToolCard — 工具调用折叠卡片（collapsible widget）。

Story 26-1：收到 StreamEvent(type="tool_call") 时插入折叠卡片，
StreamEvent(type="tool_result") 时更新状态和结果。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Collapsible, Static


class ToolCard(Widget):
    """可折叠的工具调用卡片。

    状态迁移：
      pending  → running  → success / error
    """

    DEFAULT_CSS = """
    ToolCard {
        margin: 1 0;
        border: solid $primary;
    }
    ToolCard > Container {
        padding: 0 1;
    }
    ToolCard.running {
        border: solid $warning;
    }
    ToolCard.success {
        border: solid $success;
    }
    ToolCard.error {
        border: solid $error;
    }
    #card-header {
        padding: 0 1;
        height: 1;
    }
    #card-header.running {
        background: $warning 20%;
    }
    #card-header.success {
        background: $success 20%;
    }
    #card-header.error {
        background: $error 20%;
    }
    """

    tool_name: reactive[str] = reactive("")
    state: reactive[str] = reactive("pending")  # pending | running | success | error
    duration: reactive[str] = reactive("")

    def __init__(
        self,
        tool_name: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id)
        self.tool_name = tool_name
        self._params: str = ""
        self._result: str = ""

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(self._header_text(), id="card-header")
            with Collapsible(title="详情", collapsed=True):
                with Vertical(id="card-body"):
                    yield Static("", id="card-params")
                    yield Static("", id="card-result")

    def on_mount(self) -> None:
        self.set_class(True, "running")

    def set_params(self, params: str) -> None:
        """设置工具调用参数（tool_call 事件到达时调用）。"""
        self._params = params
        self.state = "running"
        self._update()

    def set_result(self, content: str, is_error: bool = False, duration: str = "") -> None:
        """设置工具调用结果（tool_result 事件到达时调用）。"""
        self._result = content
        self.duration = duration
        self.state = "error" if is_error else "success"
        self._update()

    def _update(self) -> None:
        """同步 reactive 状态 → CSS class + 文本。"""
        # CSS class
        for cls_name in ("running", "success", "error"):
            self.set_class(self.state == cls_name, cls_name)

        # 头部
        header = self.query_one("#card-header", Static)
        header.update(self._header_text())
        header.set_class(self.state in ("running", "success", "error"), self.state)

        # 参数
        params_w = self.query_one("#card-params", Static)
        if self._params:
            params_w.update(f"[bold]参数:[/]\n{self._params}")
        else:
            params_w.update("")

        # 结果
        result_w = self.query_one("#card-result", Static)
        if self._result:
            if self.state == "error":
                result_w.update(f"[bold red]错误:[/]\n{self._result}")
            else:
                result_w.update(f"[bold green]结果:[/]\n{self._result}")
        else:
            result_w.update("")

    def _header_text(self) -> str:
        """根据状态生成头部文本。"""
        if self.state == "pending":
            return f"🔧 [bold]{self.tool_name}[/] 等待中..."
        elif self.state == "running":
            return f"🔧 [bold]{self.tool_name}[/] 执行中..."
        elif self.state == "success":
            dur = f" ({self.duration})" if self.duration else ""
            return f"✅ [bold]{self.tool_name}[/] 完成{dur}"
        else:  # error
            return f"❌ [bold]{self.tool_name}[/] 失败"
