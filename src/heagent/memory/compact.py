"""MEMORY.md 语义压缩 — 合并语义重复/过时条目，释放注入预算（Epic 59 写侧唯一入口）。

与 :mod:`heagent.memory.auto_archive` 同款的**自包含维护模块**：auto_archive 在启动侧做确定性
字节归档（不判语义），本模块在 dream 侧做语义级合并改写。两者共享同一留底文件
（``archive/MEMORY-archive.md``）与留底格式（小节 + 真实 UTC 时间戳），但小节标题带
``；fact_compact`` 标记以区分写者。

写侧纪律（对齐 epic-59 冻结决策）：

- **留底先行（D3）**：被移除条目先写归档再改 MEMORY.md；留底失败整批拒绝（文件不动）。
- **比较后写（D4）**：MEMORY.md 重写走 :func:`heagent.pub.persist.atomic_update_text`
  compare-after-read，并发 ``fact_add`` 的追加不被整份吞掉；冲突即放弃本批，留底保留
  （宁重复不丢失）。
- **精确匹配定位（D6）**：source 以条目原文精确匹配（非行号），缺失或不唯一即整批拒绝。
- **语义判重（AC5）**：target 对「本批尚未移除的条目」做 70% 词级判重（与 ``FactStore.add``
  同一公式），命中仅拒绝**该条 merge**（被删 source 不参与判重——合并产物天然与其 source
  高重叠，这正是合并的本意）。多个 merge 按声明顺序**依次**应用：后一条 merge 的判重集合
  包含前序 merge 已追加的 target，批内产物互不重复。
- **显性失败**：校验失败一次性点名全部问题条目；开关关闭属工具层职责（fail-closed），
  本模块不管开关。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from heagent.pub.exceptions import HeAgentError
from heagent.pub.persist import atomic_update_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logger = logging.getLogger(__name__)

#: fact 行前缀（与 ``FactStore._parse_facts`` / ``auto_archive._FACT_PREFIX`` 同一口径）。
_FACT_PREFIX = "- "

#: UTF-8 BOM 字符（与 ``FactStore._strip_bom`` 同一归一化口径；比较与写回前一律剥离）。
#: 用 ``chr`` 而非转义字面量：源码里放不可见字符经不起编辑器/工具链往返。
_BOM = chr(0xFEFF)

#: 归档目录名与文件名（相对 MEMORY.md 所在目录；与 auto_archive 同一留底文件）。
_ARCHIVE_DIR = "archive"
_ARCHIVE_NAME = "MEMORY-archive.md"

# compact 首次创建留底文件时的文件头（auto_archive 已建文件时直接追加小节，不覆写其头部）。
_ARCHIVE_HEADER = (
    "# MEMORY.md 归档留底（不参与注入）\n"
    "\n"
    "> 本文件不进 system prompt，仅供检索与回溯；小节标题里的时间戳是**归档动作的真实时间**。\n"
    "> 「批次 …（N 条）」小节由 ``heagent.memory.auto_archive`` 移出；"
    "「批次 …（N 条；fact_compact）」小节由 ``heagent.memory.compact`` 的合并留底。\n"
)


class FactCompactConflictError(HeAgentError):
    """compare-after-write 冲突：MEMORY.md 在读与写之间已被并发修改 ⇒ 整批放弃，留底已落档。"""


class CompactMerge(BaseModel):
    """一次语义合并的声明：把语义重复/过时的 ``sources`` 条目改写为单条 ``target``。

    ``sources`` 以**条目原文精确匹配**定位（D6，非行号）——LLM 从注入列表读到的文本原样传入，
    不做归一化；匹配必须存在且唯一（AC4），否则整批拒绝并点名问题条目。
    """

    model_config = ConfigDict(frozen=True)

    sources: list[str] = Field(min_length=1)
    target: str


class CompactRejection(BaseModel):
    """单个 merge 被拒绝的记录（AC5 判重命中；批级校验失败走异常路径、不进本结构）。"""

    model_config = ConfigDict(frozen=True)

    sources: list[str]
    target: str
    reason: str


class CompactStats(BaseModel):
    """一次语义压缩的统计（FR6：压缩前/后条数、释放字节、留底位置）。"""

    model_config = ConfigDict(frozen=True)

    applied_merges: int
    removed: int
    added: int
    facts_before: int
    facts_after: int
    bytes_freed: int
    #: 留底文件路径；本批无任何条目被移除时为空串。
    archive_path: str = ""
    rejected: list[CompactRejection] = Field(default_factory=list)


def aggregate_compactions(stats: Sequence[CompactStats]) -> CompactStats | None:
    """把一个时间窗口内的多次压缩统计聚合成单份（dream_end 事件用；D8）。

    计数类字段（applied_merges/removed/added/bytes_freed）求和；``facts_before`` 取首份、
    ``facts_after`` 取末份（窗口首尾口径）；``archive_path`` 取最后一个非空留底位置；
    ``rejected`` 按序拼接。空窗口返回 ``None``（事件侧不携带 compact 键）。
    """
    if not stats:
        return None
    first, last = stats[0], stats[-1]
    return CompactStats(
        applied_merges=sum(s.applied_merges for s in stats),
        removed=sum(s.removed for s in stats),
        added=sum(s.added for s in stats),
        facts_before=first.facts_before,
        facts_after=last.facts_after,
        bytes_freed=sum(s.bytes_freed for s in stats),
        archive_path=next((s.archive_path for s in reversed(stats) if s.archive_path), ""),
        rejected=[r for s in stats for r in s.rejected],
    )


def compact_facts(memory_path: Path | str, merges: Sequence[CompactMerge]) -> CompactStats:
    """按「合并计划」语义压缩 MEMORY.md：留底先行 + 锁内比较后写。

    校验失败（source 缺失/不唯一/重复引用、target 空白或含换行、target 与批内任一 source 重合）
    抛 :class:`ValueError` 并一次性点名全部问题条目（AC4）；留底写失败（OSError）原样向上抛
    ⇒ 整批拒绝、MEMORY.md 不动（AC2）；锁内发现文件已变抛
    :class:`FactCompactConflictError`，留底保留（AC3，宁重复不丢失）。

    Returns:
        :class:`CompactStats`；全部 merge 被判重拒绝时 ``applied_merges=0`` 且不写任何文件。
    """
    memory_path = Path(memory_path)
    merge_list = list(merges)
    if not merge_list:
        raise ValueError("merges must not be empty")

    try:
        raw = memory_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raw = ""
    except UnicodeDecodeError as exc:
        # 同 ``FactStore.add``：UnicodeDecodeError 文本不含路径，点名后再抛（Z-D12）。
        raise ValueError(f"MEMORY.md is not valid UTF-8 ({memory_path}): {exc}") from exc

    before = raw.lstrip(_BOM)
    lines = before.split("\n")
    #: 条目原文 → 匹配行号列表（唯一性校验与精确定位同源；重复行天然不唯一）。
    occurrences: dict[str, list[int]] = {}
    for i, line in enumerate(lines):
        if line.startswith(_FACT_PREFIX):
            occurrences.setdefault(line[len(_FACT_PREFIX) :], []).append(i)

    problems = _validate_merges(merge_list, occurrences)
    if problems:
        raise ValueError("\n".join(problems))

    # ── 顺序化应用（AC5）：后一条 merge 的判重集合包含前序 merge 已追加的 target。
    removed_line_ids: set[int] = set()
    appended: list[str] = []
    rejected: list[CompactRejection] = []
    for merge in merge_list:
        own_ids = {occurrences[src][0] for src in merge.sources}
        survivors = (
            line[len(_FACT_PREFIX) :]
            for i, line in enumerate(lines)
            if i not in removed_line_ids and i not in own_ids and line.startswith(_FACT_PREFIX)
        )
        if _word_overlap_duplicate(merge.target, survivors) or _word_overlap_duplicate(merge.target, appended):
            rejected.append(
                CompactRejection(
                    sources=list(merge.sources),
                    target=merge.target,
                    reason="target duplicates an existing entry (>70% word overlap); merge rejected",
                )
            )
            continue
        removed_line_ids |= own_ids
        appended.append(merge.target)

    facts_before = sum(len(ids) for ids in occurrences.values())
    if not appended:
        # 全部被判重拒绝 ⇒ 无操作：不写归档、不碰文件（留底只为真正被移除的条目服务）。
        return CompactStats(
            applied_merges=0,
            removed=0,
            added=0,
            facts_before=facts_before,
            facts_after=facts_before,
            bytes_freed=0,
            rejected=rejected,
        )

    # ── 改写：被移除行删除，其余行原序原位（AC1）；target 追加到文件末尾（最新尾，_fit_facts 预算内最可能保留）。
    kept = [line for i, line in enumerate(lines) if i not in removed_line_ids]
    new_text = "\n".join(kept)
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    new_text += "".join(f"- {target}\n" for target in appended)

    # ── 留底先行（D3）：写失败（OSError）⇒ 异常向上抛，MEMORY.md 未动、整批拒绝。
    archive_path = memory_path.parent / _ARCHIVE_DIR / _ARCHIVE_NAME
    archive_lines = [lines[i] for i in sorted(removed_line_ids)]
    _append_archive_section(archive_path, archive_lines)

    # ── 比较后写（D4）：锁内内容与预读不一致 ⇒ 放弃本批，留底保留（宁重复不丢失）。
    def _update(current: str) -> tuple[str, bool]:
        if current.lstrip(_BOM) != before:
            return current, False
        return new_text, True

    if not atomic_update_text(memory_path, _update):
        raise FactCompactConflictError(
            "MEMORY.md changed concurrently; compaction batch rejected; "
            "archived backup was written first and is retained (duplicates-in-archive by design)"
        )

    source_bytes = sum(_fact_line_bytes(lines[i]) for i in removed_line_ids)
    target_bytes = sum(_fact_line_bytes(f"- {target}") for target in appended)
    return CompactStats(
        applied_merges=len(appended),
        removed=len(removed_line_ids),
        added=len(appended),
        facts_before=facts_before,
        facts_after=facts_before - len(removed_line_ids) + len(appended),
        # 如实报告净变化，可为负（合并产物比原文更长）——钳成 0 会掩盖「越压越大」。
        bytes_freed=source_bytes - target_bytes,
        archive_path=str(archive_path),
        rejected=rejected,
    )


def _validate_merges(merges: list[CompactMerge], occurrences: dict[str, list[int]]) -> list[str]:
    """批级校验（AC4）：一次性收集全部问题并点名条目；无问题时返回空列表。

    - 每个 source 必须在文件中**存在且唯一**（D6 精确匹配）。
    - 同一 source 不得被批内多条 merge（或同一条 merge 多次）引用——重复引用语义不明，显性拒绝。
    - target 不得为空白、不得含换行（``- `` 行不变量），且不得与批内任一 source 重合
      （「既是被删条目又是合并产物」属计划自相矛盾）。
    """
    problems: list[str] = []
    claimed: dict[str, int] = {}
    for idx, merge in enumerate(merges):
        for src in merge.sources:
            if src not in occurrences:
                problems.append(f"merges[{idx}]: source not found: {src!r}")
            elif len(occurrences[src]) > 1:
                problems.append(
                    f"merges[{idx}]: source matches {len(occurrences[src])} entries (must be unique): {src!r}"
                )
            elif src in claimed:
                problems.append(f"merges[{idx}]: source already claimed by merges[{claimed[src]}]: {src!r}")
            else:
                claimed[src] = idx
    all_sources = set(claimed)
    for idx, merge in enumerate(merges):
        if not merge.target.strip():
            problems.append(f"merges[{idx}]: target must not be blank")
        elif "\n" in merge.target:
            problems.append(f"merges[{idx}]: target must be a single line (no newlines)")
        elif merge.target in all_sources:
            problems.append(f"merges[{idx}]: target must not duplicate a source in the same batch: {merge.target!r}")
    return problems


def _word_overlap_duplicate(target: str, existing_texts: Iterable[str]) -> bool:
    """AC5 判重：target 对给定条目文本做 70% 词级判重。

    与 ``FactStore.add`` 同一公式（交集/新条目词数 > 0.7）。
    """
    target_words = set(target.lower().split())
    for text in existing_texts:
        old_words = set(text.lower().split())
        if len(target_words & old_words) / max(len(target_words), 1) > 0.7:
            return True
    return False


def _fact_line_bytes(line: str) -> int:
    """一条 fact 行在注入侧占的字节数（与 ``_fit_facts`` 的 ``len(f"- {fact}\\n")`` 同口径）。"""
    return len((line + "\n").encode("utf-8"))


def _append_archive_section(archive_path: Path, fact_lines: list[str]) -> None:
    """把本批被移除条目留底为归档新小节（小节 + 真实 UTC 时间戳；格式沿用 auto_archive）。

    「留底先行」由调用方保证：本函数先于 MEMORY.md 重写调用，写失败 ⇒ 异常向上抛 ⇒ 整批拒绝。
    追加走 :func:`atomic_update_text`（归档自身 ``.lock`` 内读改写）：并发 compact 的留底小节
    互相不被覆盖——留底丢失是**无声且不可检测**的数据丢失（被移除条目既不在 MEMORY.md 也不在
    archive），比 MEMORY.md 的比较后写冲突更严重，故必须在归档文件自己的锁上串行化。
    """

    def _append(current: str) -> tuple[str, bool]:
        stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        section = f"## 批次 {stamp}（{len(fact_lines)} 条；fact_compact）\n\n" + "\n".join(fact_lines) + "\n"
        if current:
            return f"{current.rstrip(chr(10))}\n\n{section}", True
        return f"{_ARCHIVE_HEADER}\n{section}", True

    atomic_update_text(archive_path, _append)
