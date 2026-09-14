"""GUI 工具活动展示态测试（2026-09-14 复核 P2/P3）。

``gui/observers.py`` 只依赖 engine / state，CI（test job 仅装 ``.[dev]``，无 textual）
也能跑；``gui/bridge.py`` 与 ``gui/screens/chat.py`` 需要 textual（可选组 gui），
故按需 :func:`pytest.importorskip`。
"""

from __future__ import annotations

import pytest

from heagent.engine.observability import EngineEvent
from heagent.gui.observers import GuiEventObserver
from heagent.gui.state import GuiState


def test_engine_event_path_labels_with_the_target() -> None:
    """引擎事件路径：状态栏 label 带作用对象（与 CLI 提示行同一口径）。"""
    state = GuiState()

    GuiEventObserver(state).handle(
        EngineEvent(event_type="tool_call_started", tool_name="file_read", target="docs/frame.md")
    )

    assert state.active_tool == "file_read → docs/frame.md"


def test_engine_event_path_clears_on_completion() -> None:
    state = GuiState()
    observer = GuiEventObserver(state)
    observer.handle(EngineEvent(event_type="tool_call_started", tool_name="shell", target="pytest -q"))

    observer.handle(EngineEvent(event_type="tool_call_completed", tool_name="shell", target="pytest -q"))

    assert state.active_tool == ""


def test_stream_event_path_uses_the_same_label() -> None:
    """流式事件路径（bridge）与引擎事件路径必须同格式。

    两条路径在同一次 run 中都活跃（bridge 消费 run_stream，observers 订阅 EventBus），
    各写一套会让同一字段在「带 target」与「不带」之间来回覆盖。
    """
    pytest.importorskip("textual")
    from heagent.gui.bridge import AgentBridge
    from heagent.types import StreamEvent

    state = GuiState()
    bridge = AgentBridge(loop=None, state=state)  # type: ignore[arg-type]

    bridge._update_state(StreamEvent(type="tool_call", tool_name="file_read", tool_target="docs/frame.md"))

    assert state.active_tool == "file_read → docs/frame.md"


def test_stream_event_path_clears_on_result() -> None:
    pytest.importorskip("textual")
    from heagent.gui.bridge import AgentBridge
    from heagent.types import StreamEvent

    state = GuiState(active_tool="file_read → docs/frame.md")
    bridge = AgentBridge(loop=None, state=state)  # type: ignore[arg-type]

    bridge._update_state(StreamEvent(type="tool_result", tool_name="file_read", tool_result_content="ok"))

    assert state.active_tool == ""


class TestToolResultRendering:
    """P3：失败不得画绿勾；工具输出不可信，不得被当成 Rich markup 解释。"""

    @staticmethod
    def _event(**kwargs: object) -> object:
        from heagent.types import StreamEvent

        return StreamEvent(type="tool_result", **kwargs)  # type: ignore[arg-type]

    def test_failure_is_attributed_and_not_green(self) -> None:
        pytest.importorskip("textual")
        from heagent.gui.screens.chat import _render_tool_result

        line = _render_tool_result(
            self._event(tool_name="shell", tool_result_content="Tool error: boom", tool_error=True)
        )

        assert "[red]✗ shell[/]" in line
        assert "[green]" not in line

    def test_success_keeps_the_green_check(self) -> None:
        pytest.importorskip("textual")
        from heagent.gui.screens.chat import _render_tool_result

        line = _render_tool_result(self._event(tool_name="file_read", tool_result_content="ok"))

        assert line.startswith("  [green]✓[/]")
        assert "[red]" not in line

    def test_markup_in_tool_output_is_escaped(self) -> None:
        pytest.importorskip("textual")
        from heagent.gui.screens.chat import _render_tool_result

        line = _render_tool_result(self._event(tool_name="shell", tool_result_content="[red]injected[/]"))

        assert "\\[red]injected" in line
