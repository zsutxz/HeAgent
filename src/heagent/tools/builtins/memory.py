"""Builtin tools for long-term memory and profile updates."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from heagent.config import get_settings
from heagent.memory.compact import CompactMerge, FactCompactConflictError
from heagent.tools.decorator import tool
from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from heagent.memory.compact import CompactStats
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore


@dataclass(slots=True)
class MemoryToolRuntime:
    """Runtime dependencies for memory tools."""

    facts: FactStore | None
    profile: ProfileStore | None


_memory_runtime = RuntimeSlot[MemoryToolRuntime]("heagent_memory_tools")


def configure_memory_tools(
    facts: FactStore | None = None,
    profile: ProfileStore | None = None,
) -> None:
    """Set fallback stores used by memory tools outside an agent run."""
    _memory_runtime.configure(MemoryToolRuntime(facts=facts, profile=profile))


def reset_memory_tools() -> None:
    """Clear fallback memory tool bindings."""
    _memory_runtime.reset()


@contextmanager
def bind_memory_tools(
    *,
    facts: FactStore | None = None,
    profile: ProfileStore | None = None,
) -> Iterator[None]:
    """Bind memory stores for the current run context."""
    with _memory_runtime.bind(MemoryToolRuntime(facts=facts, profile=profile)):
        yield


def _runtime() -> MemoryToolRuntime | None:
    return _memory_runtime.get()


@tool(
    # 显式 description 而非依赖 docstring：`@tool` 只取 docstring **首行**，而写入准则需要完整两句。
    # 这是唯一能触达模型的**写侧**闸门——MEMORY.md 的头部注记不进 system prompt（只有 `- ` 行被注入）。
    description=(
        "Save one long-term fact: behavior-changing conclusions only (user preferences, code invariants, "
        "environment quirks, reusable techniques). Do not record session narration, status bookkeeping "
        "(pending work, commit/test bookkeeping), or probe details — they crowd durable facts out of the "
        "injection budget."
    ),
)
async def fact_add(fact: str) -> str:
    """Save one long-term fact (behavior-changing conclusions only; guidance lives in the description)."""
    runtime = _runtime()
    store = runtime.facts if runtime is not None else None
    if store is None:
        return "Error: fact tools not configured."
    added = await asyncio.to_thread(store.add, fact)
    if added:
        return f"Fact saved: {fact}"
    return "Fact already exists (duplicate detected)."


@tool
async def profile_update(section: str, value: str) -> str:
    """Update one profile section."""
    runtime = _runtime()
    store = runtime.profile if runtime is not None else None
    if store is None:
        return "Error: profile tools not configured."
    await asyncio.to_thread(store.update_section, section, value)
    return f"Profile section '{section}' updated."


@tool(
    # 显式 description 而非依赖 docstring：与 fact_add 同理，写侧准则必须完整触达模型——
    # 本工具是 MEMORY.md 语义压缩（Epic 59）的写侧唯一入口，merges 条目结构、精确匹配定位、
    # 「不确定不改」原则全部只住这里（参数 schema 由装饰器生成，`list` 无条目结构，见下）。
    description=(
        "Merge semantic duplicates and outdated entries in long-term memory (MEMORY.md) to free injection budget. "
        'Pass merges=[{"sources": [exact existing entry texts], "target": rewritten single entry}]; '
        "each source must match an existing entry exactly and uniquely (never line numbers). "
        "Removed entries are archived before MEMORY.md is rewritten, so a merge is recoverable. "
        "A target that duplicates a surviving entry (>70% word overlap) is rejected for that merge — "
        "merge conservatively: when uncertain, do not merge. "
        "Disabled unless memory_compact_enabled=true (dream-time consolidation)."
    ),
)
async def fact_compact(merges: list[dict[str, Any]]) -> str:
    """Compact MEMORY.md by merging semantic-duplicate entries (write-side criteria live in the description)."""
    runtime = _runtime()
    store = runtime.facts if runtime is not None else None
    if store is None:
        return "Error: fact tools not configured."
    if not get_settings().memory_compact_enabled:
        # fail-closed（D5）：无人监督删改持久记忆默认不开；关闭即显性报错，不静默成功。
        return "Error: memory compaction is disabled (memory_compact_enabled=false)."
    if not merges:
        return "Error: merges must not be empty."
    try:
        parsed = [
            CompactMerge(sources=item["sources"], target=item["target"])
            for item in merges
        ]
    except (KeyError, TypeError, ValidationError) as exc:
        return f"Error: each merge must be {{'sources': [entry text, ...], 'target': new entry text}} ({exc})."
    try:
        stats = await asyncio.to_thread(store.compact, parsed)
    except FactCompactConflictError as exc:
        return f"Error: {exc}"
    return _format_compact_result(stats)


def _format_compact_result(stats: CompactStats) -> str:
    """把 CompactStats 格式化为工具返回文本（统计 + 留底位置 + 逐条拒绝原因）。"""
    lines = [
        f"Compacted: {stats.applied_merges} merge(s) applied, {stats.removed} removed, {stats.added} added, "
        f"{stats.bytes_freed} bytes freed; facts: {stats.facts_before} -> {stats.facts_after}."
    ]
    if stats.archive_path:
        lines.append(f"Archived to: {stats.archive_path}")
    lines.extend(f"Rejected merge (target={r.target!r}): {r.reason}" for r in stats.rejected)
    return "\n".join(lines)
