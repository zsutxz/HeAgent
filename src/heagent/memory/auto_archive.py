"""MEMORY.md 自动归档 — 超预算时把「中间的老条目」移出，保证注入不省略。

在 CLI 启动时调用 `maybe_archive_old_facts()`（`cli/console.py::_prune_runtime_artifacts`）。

**2026-10-10 重写**（替换原「按估算年龄归档 + 按月分文件」实现）。三条实测出来的缺陷：

1. **原实现的时间信号是伪造的**。事实条目的格式只有 ``- <text>``（``FactStore._parse_facts``），
   **没有真实时间戳**。原实现用 ``DAYS_PER_FACT = 7`` 从 MEMORY.md 的 mtime 线性反推每条的时间，
   再按月分桶写 ``archive/<YYYY-MM>.md``。2026-10-09 那批 170 条因此落进 ``2023-04.md … 2026-07.md``
   共 40 个文件——而它们的真实创建时间全在 2026-09 ~ 2026-09-30。**文件名里的月份是纯虚构**
   （40 个文件实为同一次写入：mtime 全等、文件头时间戳全等）。
2. **原实现会静默丢弃内容**。重写时只保留「首个 fact 之前的行」+ fact 行，fact 之后的任何非 ``- `` 行
   （小节标题、空行）被无声删除（``elif fact_start_idx == -1``）。
3. **触发条件与真实需要无关**。真正需要整理的唯一客观信号是「注入预算即将装不下」——``_fit_facts``
   超预算时省略的是**最新的尾部**条目，所以必须赶在那之前把**中间的老条目**移走。

现行口径（每一条都有 ``tests/memory/test_auto_archive.py`` 的判据）：

- **落点**：单一 append-only ``.heagent/memory/archive/MEMORY-archive.md``；每批一个小节，标题带
  **真实** UTC 时间戳（归档动作发生的时间）。没有真实日期可分，就不再声称有。
- **触发**：MEMORY.md 的 fact 总字节 > ``memory_archive_trigger_bytes``（``0`` = 禁用）。
- **保留**：前 ``CORE_FACTS_TO_KEEP`` 条（核心约定，永久保留）+ **尾部**（最新）能装进预算的那些条；
  被移走的是两者**中间**的条目（即较老的学习记录），保持文件原序。
- **重写**：逐行删除被移走的 fact 行，其余行（header 与任何非 fact 行）**原位保留**。
- **并发**：MEMORY.md 的重写走 ``pub.persist.atomic_update_text``（跨进程锁 + 比较后写），
  并发 ``fact_add`` 的追加不会被整份覆盖。
- **失败 fail-soft**：任何异常只记 WARNING 并返回全 0，绝不阻断启动。
- **归档先于裁剪**：宁可留底里可能多一条重复条目，也不让条目「移出但没落档」。

时间信号缺失这一条是**设计约束**而非待办：``FactStore`` 的值格式里没有时间字段，任何「年龄」都只能是
猜测。若将来需要真实年龄，正确做法是让 ``fact_add`` 写入带日期的条目（格式变更 + 工具描述 + 文档同步），
不是在归档侧继续外推。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from heagent.config import Settings, get_settings
from heagent.pub.persist import atomic_update_text

logger = logging.getLogger(__name__)

#: 归档时永久保留的头部条目数（核心约定写在文件前部；见 MEMORY.md 头部与 ``_fit_facts``）。
CORE_FACTS_TO_KEEP = 20

#: fact 行前缀（``FactStore._parse_facts`` 的唯一判定口径）。
_FACT_PREFIX = "- "

#: 归档标记文件名（记录上次归档时间戳，用于跨进程节流）。落在 MEMORY.md 同目录。
_STAMP_NAME = ".archive-stamp"

#: 归档目录名与文件名（相对 MEMORY.md 所在目录）。
_ARCHIVE_DIR = "archive"
_ARCHIVE_NAME = "MEMORY-archive.md"

_ARCHIVE_HEADER = """# MEMORY.md 归档留底（不参与注入）

> `FactStore` 只读 `.heagent/memory/MEMORY.md`，本文件**不进 system prompt**，仅供检索与回溯。
> 每个小节 = 一批由 `heagent.memory.auto_archive` 从 MEMORY.md 移出的条目；小节标题里的时间戳是
> **归档动作的真实时间**，不是条目的创建时间。
> 条目本身不带时间戳（`FactStore` 的格式只有 `- <text>`）⇒ **文件顺序是唯一的先后凭据**：
> 越靠前越早写入，同一批次内保持原文件顺序。
"""


def _should_skip_prune(stamp_path: Path, min_interval_seconds: int) -> bool:
    """检查是否应该跳过清理（基于上次清理时间戳和最小间隔）。"""
    if min_interval_seconds <= 0:
        return False
    if not stamp_path.exists():
        return False
    try:
        last_prune = float(stamp_path.read_text(encoding="utf-8").strip())
        elapsed = time.time() - last_prune
        return elapsed < min_interval_seconds
    except (ValueError, OSError):
        return False


def _touch_stamp(stamp_path: Path) -> None:
    """刷新节流标记；失败只记 DEBUG（节流是优化，坏掉不能影响归档本身）。"""
    try:
        stamp_path.parent.mkdir(parents=True, exist_ok=True)
        stamp_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        logger.debug("Cannot write archive stamp %s", stamp_path, exc_info=True)


def _fact_line_bytes(line: str) -> int:
    """一条 fact 行在注入侧占的字节数（与 ``_fit_facts`` 的 ``len(f"- {fact}\\n")`` 同口径）。"""
    return len((line + "\n").encode("utf-8"))


def _build_plan(text: str, trigger_bytes: int) -> tuple[list[str], str | None, int]:
    """算出「移走哪些 fact 行 / 新文本 / 保留多少条」。

    返回 ``(被移出的 fact 行（原序）, 新文本（无需改动时为 None）, 保留的 fact 条数)``。
    """
    lines = text.split("\n")
    fact_indexes = [i for i, line in enumerate(lines) if line.startswith(_FACT_PREFIX)]

    pinned = fact_indexes[:CORE_FACTS_TO_KEEP]
    rest = fact_indexes[CORE_FACTS_TO_KEEP:]
    budget = trigger_bytes - sum(_fact_line_bytes(lines[i]) for i in pinned)

    keep_tail: list[int] = []
    used = 0
    for i in reversed(rest):  # 从**最新**往前装，装不下就停 ⇒ 被移走的是较老的那一段
        size = _fact_line_bytes(lines[i])
        if used + size > budget:
            break
        keep_tail.append(i)
        used += size

    keep = set(pinned) | set(keep_tail)
    archived = [i for i in fact_indexes if i not in keep]
    if not archived:
        return [], None, len(fact_indexes)
    removed = set(archived)
    new_text = "\n".join(line for i, line in enumerate(lines) if i not in removed)
    return [lines[i] for i in archived], new_text, len(keep)


def _append_archive(archive_path: Path, fact_lines: list[str]) -> None:
    """把一批 fact 行追加成新小节（标题带真实 UTC 时间戳）。"""
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    section = f"## 批次 {stamp}（{len(fact_lines)} 条）\n\n" + "\n".join(fact_lines) + "\n"
    if archive_path.exists():
        existing = archive_path.read_text(encoding="utf-8").rstrip("\n")
        archive_path.write_text(f"{existing}\n\n{section}", encoding="utf-8")
    else:
        archive_path.write_text(f"{_ARCHIVE_HEADER}\n{section}", encoding="utf-8")


def _replace_if_unchanged(path: Path, before: str, after: str) -> bool:
    """锁内读到的内容仍等于 ``before`` 时才写 ``after``；已变则原样保留并返回 False。

    没有这层比较，一次并发 ``fact_add``（它走 ``atomic_update_text`` 追加）就会被本函数的
    整份重写**静默吞掉**。
    """

    def _update(current: str) -> tuple[str, bool]:
        return (after, True) if current == before else (current, False)

    return atomic_update_text(path, _update)


def maybe_archive_old_facts(
    memory_path: Path | str = ".heagent/memory/MEMORY.md",
    settings: Settings | None = None,
) -> dict[str, int]:
    """在启动时检查并归档 MEMORY.md 里「中间的老条目」（跨进程节流、fail-soft）。

    归档策略见模块 docstring。``memory_archive_trigger_bytes <= 0`` 时整体禁用。

    Returns:
        统计信息字典：

        - ``archived``: 本批移出并落档的条目数
        - ``kept``: 归档后 MEMORY.md 里保留的条目数
        - ``skipped``: 因禁用 / 节流 / 文件缺失 / 失败而跳过（返回全 0）

    失败时 fail-soft：记录 WARNING 并返回全 0 统计，不中断启动流程。
    """
    settings = settings or get_settings()

    if settings.memory_archive_trigger_bytes <= 0:
        return {"archived": 0, "kept": 0, "skipped": True}

    memory_path = Path(memory_path)
    stamp_path = memory_path.parent / _STAMP_NAME
    if _should_skip_prune(stamp_path, settings.memory_archive_min_interval_seconds):
        logger.debug("Skipping memory auto-archive (last run was too recent)")
        return {"archived": 0, "kept": 0, "skipped": True}

    if not memory_path.exists():
        logger.debug("MEMORY.md does not exist, skipping auto-archive")
        return {"archived": 0, "kept": 0, "skipped": True}

    trigger = settings.memory_archive_trigger_bytes
    try:
        before = memory_path.read_text(encoding="utf-8")
        archived_lines, new_text, kept = _build_plan(before, trigger)

        if not archived_lines or new_text is None:
            logger.info("No old facts to archive (fact bytes within %d)", trigger)
            _touch_stamp(stamp_path)
            return {"archived": 0, "kept": kept, "skipped": False}

        archive_path = memory_path.parent / _ARCHIVE_DIR / _ARCHIVE_NAME
        _append_archive(archive_path, archived_lines)  # 先落底，再裁剪

        if not _replace_if_unchanged(memory_path, before, new_text):
            logger.warning(
                "MEMORY.md changed while archiving; left it untouched (%d 条已写入 %s，可能与正文重复)",
                len(archived_lines),
                archive_path,
            )
            _touch_stamp(stamp_path)
            return {"archived": 0, "kept": kept, "skipped": False}

        _touch_stamp(stamp_path)
        logger.info(
            "Memory auto-archive completed: %d facts archived, %d kept (trigger: %d bytes)",
            len(archived_lines),
            kept,
            trigger,
        )
        return {"archived": len(archived_lines), "kept": kept, "skipped": False}

    except Exception as exc:
        logger.warning(
            "Memory auto-archive failed (%s: %s); continuing without archiving",
            type(exc).__name__,
            exc,
        )
        return {"archived": 0, "kept": 0, "skipped": True}
