"""``pub/event_lines`` 判据：事件日志的差分与行渲染（台账 A24）。

为什么在这测：GUI 包 ``heagent.gui.*`` 的导入要求 textual（可选依赖），CI 的 test job 不装它
⇒ GUI 里的判据会被 skip。展示纯逻辑因此放在 ``heagent.pub.event_lines``，本文件不依赖 textual，
在 CI 也跑。另有一条**结构性**判据保证 GUI 侧薄壳真的用了它（而不是退回旧的索引差分）。
"""

from __future__ import annotations

from pathlib import Path

from heagent.pub.event_lines import EventCursor, format_duration, format_event_line

WIDGET = Path(__file__).resolve().parents[1] / "src" / "heagent" / "gui" / "widgets" / "event_log.py"


def _evt(i: int) -> tuple[float, str, dict[str, object]]:
    return (float(i), "tool_call_completed", {"tool_name": f"t{i}"})


# ── format_event_line ─────────────────────────────────────────────────────


def test_formats_all_supported_fields_in_order() -> None:
    line = format_event_line(
        "workflow_step_completed",
        {"step": "dev-story", "story": "s-3", "duration_ms": 1500, "result": "completed", "run_id": "abcdef123456"},
    )
    assert line == "workflow_step_completed step=dev-story story=s-3 result=completed duration=1.5s run=abcdef12"


def test_omits_missing_and_empty_fields() -> None:
    assert format_event_line("run_started", {}) == "run_started"
    assert format_event_line("run_started", None) == "run_started"
    assert format_event_line("tool_call_failed", {"tool_name": "", "error": "", "error_kind": ""}) == "tool_call_failed"


def test_tool_and_iteration_and_error_fields() -> None:
    line = format_event_line(
        "tool_call_failed",
        {"tool_name": "shell", "target": "pytest -q", "iteration": 3, "error_kind": "timeout", "error": "boom"},
    )
    assert line == "tool_call_failed tool=shell target=pytest -q iter=3 kind=timeout error=boom"


def test_duration_formatting_boundaries() -> None:
    assert format_duration(0) == "0ms"
    assert format_duration(999) == "999ms"
    assert format_duration(1000) == "1.0s"
    assert format_duration(12345) == "12.3s"


def test_multiline_error_is_flattened_and_truncated() -> None:
    line = format_event_line("tool_call_failed", {"error": "line1\nline2\t  line3", "duration_ms": 5})
    assert "\n" not in line and "\t" not in line
    assert "line1 line2 line3" in line

    long_error = "x" * 200
    line = format_event_line("tool_call_failed", {"error": long_error})
    assert line.endswith("…")
    assert len(line) < 120


def test_values_are_not_interpreted_as_markup() -> None:
    """事件值不可信：格式化只产出纯文本，``[red]`` 之类必须原样保留（转义由展示层做）。"""
    line = format_event_line("tool_call_completed", {"tool_name": "[red]evil[/]", "target": "[b]x[/b]"})
    assert "[red]evil[/]" in line
    assert "[b]x[/b]" in line


def test_unknown_event_kind_passes_through() -> None:
    """``kind`` 是开集：未知事件类型必须原样渲染（不得过滤）。"""
    assert format_event_line("brand_new_kind", {"tool_name": "x"}).startswith("brand_new_kind ")


# ── EventCursor ───────────────────────────────────────────────────────────


def test_cursor_consumes_all_then_reports_nothing_new() -> None:
    cursor = EventCursor()
    events = [_evt(i) for i in range(3)]
    new, lost = cursor.take(3, events)
    assert new == events and lost == 0
    assert cursor.take(3, events) == ([], 0)
    assert cursor.seen == 3


def test_cursor_returns_only_the_newest_when_window_holds_more_than_new() -> None:
    cursor = EventCursor()
    cursor.take(100, [_evt(i) for i in range(100)])
    window = [_evt(i) for i in range(50, 150)]
    new, lost = cursor.take(150, window)
    assert lost == 0
    assert [d["tool_name"] for _, _, d in new] == [f"t{i}" for i in range(100, 150)]


def test_cursor_never_freezes_when_the_ring_buffer_is_full() -> None:
    """台账 A24 的回归判据：窗口满（200）时事件仍在产出 ⇒ 游标必须继续给出新事件。

    对照：旧实现的判据 ``len(window) - seen`` 在同一状态下恒为 0（日志永久冻结）。
    """
    window_size = 200
    buffer: list[tuple[float, str, dict[str, object]]] = []
    cursor = EventCursor()
    rendered = 0
    stale_formula_values = []
    post_full: list[int] = []
    for i in range(window_size * 2):  # 产出 400 条，缓冲只留最近 200 条
        buffer.append(_evt(i))
        del buffer[:-window_size]
        total = i + 1
        new, _lost = cursor.take(total, buffer)
        rendered += len(new)
        stale_formula_values.append(max(0, len(buffer) - cursor.seen))
        if i >= window_size:
            post_full.append(len(new))

    assert rendered == window_size * 2, f"每次轮询都该消费到新事件（累计 400 条），实为 {rendered}"
    assert min(post_full) == 1, "缓冲满之后仍有新事件却不再渲染 —— 这正是 A24 的冻结形态"
    assert max(stale_formula_values) == 0, "旧公式在缓冲满后恒为 0（冻结成因），留此作对照"
    assert cursor.seen == window_size * 2


def test_cursor_reports_lost_events_when_they_rolled_out_of_the_window() -> None:
    cursor = EventCursor()
    cursor.take(100, [_evt(i) for i in range(100)])
    new, lost = cursor.take(400, [_evt(i) for i in range(200, 400)])
    assert lost == 100
    assert len(new) == 200


def test_cursor_resets_when_producer_restarts() -> None:
    cursor = EventCursor()
    cursor.take(10, [_evt(i) for i in range(10)])
    new, lost = cursor.take(2, [_evt(0), _evt(1)])  # 观察者被 clear → total 回退
    assert cursor.seen == 2 and lost == 0
    assert len(new) == 2


def test_cursor_reset_helper() -> None:
    cursor = EventCursor(seen=99)
    cursor.reset()
    new, _ = cursor.take(2, [_evt(0), _evt(1)])
    assert len(new) == 2


# ── 结构性判据：GUI 薄壳必须真的用上面这套 ─────────────────────────────────


def test_event_log_widget_uses_the_cursor_and_never_the_index_diff() -> None:
    """GUI 侧不得退回「窗口长度 − 已渲染数」的索引差分（A24 的成因），且必须转义。"""
    source = WIDGET.read_text(encoding="utf-8")
    assert "EventCursor" in source and "format_event_line" in source
    assert "_last_rendered_idx" not in source
    assert "escape(" in source, "事件值不可信，写入 RichLog 前必须转义"
