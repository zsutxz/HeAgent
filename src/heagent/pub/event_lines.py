"""引擎事件的**展示层**纯函数（零运行栈依赖，可离线 / 在 CI 单测）。

为什么放在 ``pub/``：``heagent.gui`` 包（含 ``gui.observers`` / ``gui.widgets.*``）的
``__init__`` 会 import textual（可选依赖），因此任何 ``heagent.gui.*`` 的导入都要求 textual
—— 展示逻辑若写在 GUI 包里，CI 的 test job（不装 textual）就永远跳过它的测试，护栏等于没有。
本模块只依赖标准库，故其判据在 CI 也生效；GUI 侧只留薄壳。

两块职责：

* :class:`EventCursor` ——「环形缓冲 + 已消费到第几条」的差分逻辑。
  **2026-09-28 修缺陷（台账 A24）**：旧实现用「缓冲窗口长度 − 已渲染数」做差，而窗口一旦
  到达上限（``GuiEventObserver.get_recent(limit=200)``）两者恒相等 ⇒ 差分恒为 0，事件日志
  **永久停止渲染**（之后再多的 ``tool_call_*`` / ``run_failed`` 都不显示）。正确口径是用
  观察者侧的**单调总数**与「已消费数」做差，并在总数超过窗口时如实报出「丢了几条」。
* :func:`format_event_line` —— 一行事件描述（耗时 / 失败分类 / 迭代 / 作用对象 / workflow 步骤）。
  只产出**纯文本**：Rich markup 与转义由展示层负责（事件值不可信，与 ``tools/call_summary``
  同源立场；GUI 侧一律 ``rich.markup.escape`` 之后再写入 RichLog）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeGuard

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查（本文件启用 future annotations）
    from collections.abc import Mapping, Sequence

#: 单行展示的字段顺序（``details`` 键 → 展示标签）。空串 / 缺省一律省略。
STRING_FIELDS: tuple[tuple[str, str], ...] = (
    ("tool_name", "tool"),
    ("target", "target"),
    ("step", "step"),
    ("story", "story"),
    ("result", "result"),
)

_MAX_ERROR_CHARS = 60


def format_duration(ms: int) -> str:
    """毫秒 → 可读耗时（``999`` → ``999ms``，``1500`` → ``1.5s``）。"""
    return f"{ms}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


def _one_line(value: str) -> str:
    """压成单行并截断（事件的 ``error`` 常带换行；单行日志里换行会破坏渲染）。"""
    flat = " ".join(value.split())
    return flat if len(flat) <= _MAX_ERROR_CHARS else flat[:_MAX_ERROR_CHARS] + "…"


def _is_int(value: Any) -> TypeGuard[int]:
    """``int`` 且非 ``bool``（``True`` 也是 int，展示层不该把它当数字）。"""
    return isinstance(value, int) and not isinstance(value, bool)


def format_event_line(evt_type: str, details: Mapping[str, Any] | None = None) -> str:
    """把一条引擎事件渲染成**纯文本**单行；缺失字段一律省略（不输出 ``None``/空值）。"""
    data: Mapping[str, Any] = details or {}
    parts = [evt_type]
    for key, label in STRING_FIELDS:
        value = data.get(key)
        if isinstance(value, str) and value:
            parts.append(f"{label}={_one_line(value)}")
    iteration = data.get("iteration")
    if _is_int(iteration) and iteration:
        parts.append(f"iter={iteration}")
    duration = data.get("duration_ms")
    if _is_int(duration):
        parts.append(f"duration={format_duration(duration)}")
    error_kind = data.get("error_kind")
    if isinstance(error_kind, str) and error_kind:
        parts.append(f"kind={error_kind}")
    error = data.get("error")
    if isinstance(error, str) and error:
        parts.append(f"error={_one_line(error)}")
    run_id = data.get("run_id")
    if isinstance(run_id, str) and run_id:
        parts.append(f"run={run_id[:8]}")
    return " ".join(parts)


@dataclass
class EventCursor:
    """按**单调总数**推进的消费游标（环形缓冲滚动时不会冻结）。

    ``seen`` 是已消费的事件总数；调用方在「暂停渲染」期间**不要**调用 :meth:`take`，
    恢复时自然补上这段时间的事件（旧实现在暂停时也推进索引 ⇒ 恢复后永久丢事件）。
    """

    seen: int = 0

    def take(self, total: int, available: Sequence[Any]) -> tuple[list[Any], int]:
        """返回 ``(本次新增事件（时间正序）, 因窗口滚动而永久丢掉的条数)``。

        ``total`` 必须由事件生产者单调递增地给出（从不随缓冲淘汰回退）。``total < seen``
        （观察者被清空 / 重建）时按「从头重来」处理。
        """
        if total < self.seen:
            self.seen = 0
        fresh = total - self.seen
        if fresh <= 0:
            return [], 0
        window = list(available)
        take_n = min(fresh, len(window))
        lost = fresh - take_n
        self.seen = total
        return (window[len(window) - take_n :], lost) if take_n else ([], lost)

    def reset(self) -> None:
        """回到「还没消费任何事件」（配合观察者的 ``clear()``）。"""
        self.seen = 0
