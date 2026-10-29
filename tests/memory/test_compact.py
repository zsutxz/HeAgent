"""Tests for MEMORY.md 语义压缩（``heagent.memory.compact``，Epic 59 / Story 59-1）。

判据对齐 story AC：

1. **AC1 合并执行**：sources 行删除、target 追加到末尾、其余行原序原位。
2. **AC2 留底先行**：归档小节含原文 + 真实 UTC 时间戳；留底失败 ⇒ 整批拒绝、MEMORY.md 不动。
3. **AC3 并发冲突**：比较后写发现文件已变 ⇒ 放弃本批、外部新内容不被覆盖、留底保留。
4. **AC4 显性失败**：source 缺失/不唯一/重复引用、target 空白/含换行/与 source 重合 ⇒ 整批拒绝并点名。
5. **AC5 判重口径**：target 仅对「未被本批移除的条目」判重（自身 source 不参与）；命中只拒该条 merge；
   多条 merge 顺序化应用（后序 merge 的判重集合含前序 merge 的 target）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest  # noqa: TC002 - pytest.raises 是运行期用法

import heagent.memory.compact as compact_mod
from heagent.memory.compact import (
    CompactMerge,
    CompactRejection,
    CompactStats,
    FactCompactConflictError,
    aggregate_compactions,
    compact_facts,
)
from heagent.memory.facts import FactStore

_HEADING = "条；fact_compact）"


def _create_memory_file(path: Path, facts: list[str], *, header: str = "# HeAgent 长期记忆\n\n> 测试文件\n\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(f"- {fact}" for fact in facts) + "\n", encoding="utf-8")


def _facts_of(path: Path) -> list[str]:
    return [ln[2:] for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]


def _lines_of(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _archive_of(path: Path) -> str:
    return (path.parent / "archive" / "MEMORY-archive.md").read_text(encoding="utf-8")


class TestMergeExecution:
    """AC1：sources 行删除、target 追加、其余行原序原位。"""

    def test_sources_removed_target_appended_others_preserved(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "ddd eee fff", "ggg hhh iii", "jjj kkk lll"])

        stats = compact_facts(
            memory_path,
            [CompactMerge(sources=["aaa bbb ccc", "ggg hhh iii"], target="merged first third entries")],
        )

        # 头部（非 fact 行）与幸存条目原序原位；target 追加到文件末尾。
        lines = _lines_of(memory_path)
        assert lines[0] == "# HeAgent 长期记忆"
        assert _facts_of(memory_path) == ["ddd eee fff", "jjj kkk lll", "merged first third entries"]
        assert stats.applied_merges == 1
        assert (stats.removed, stats.added) == (2, 1)
        assert (stats.facts_before, stats.facts_after) == (4, 3)
        src_bytes = len(b"- aaa bbb ccc\n") + len(b"- ggg hhh iii\n")
        assert stats.bytes_freed == src_bytes - len(b"- merged first third entries\n")
        assert stats.archive_path.endswith("MEMORY-archive.md")
        assert stats.rejected == []

    def test_multi_merge_batch_targets_in_declaration_order(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "ddd eee fff", "ggg hhh iii", "jjj kkk lll"])

        stats = compact_facts(
            memory_path,
            [
                CompactMerge(sources=["aaa bbb ccc"], target="first merged entry text"),
                CompactMerge(sources=["ddd eee fff", "ggg hhh iii"], target="second combined phrase output"),
            ],
        )

        assert stats.applied_merges == 2
        assert _facts_of(memory_path) == [
            "jjj kkk lll",
            "first merged entry text",
            "second combined phrase output",
        ]


class TestArchiveFirst:
    """AC2：留底先行——留底小节含原文与真实 UTC 时间戳；留底失败整批拒绝。"""

    def test_archive_section_contains_sources_and_timestamp(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "ddd eee fff"])

        compact_facts(memory_path, [CompactMerge(sources=["aaa bbb ccc"], target="merged entry text here")])

        archive = _archive_of(memory_path)
        assert "# MEMORY.md 归档留底" in archive  # compact 首建时写自己的文件头
        section = [ln for ln in archive.splitlines() if ln.startswith("## 批次")]
        assert len(section) == 1
        assert re.match(r"^## 批次 \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC（1 " + _HEADING, section[0])
        assert "- aaa bbb ccc" in archive  # 原文留底

    def test_archive_failure_rejects_whole_batch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "ddd eee fff"])
        before = memory_path.read_bytes()

        def boom(archive_path: Path, fact_lines: list[str]) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(compact_mod, "_append_archive_section", boom)

        with pytest.raises(OSError, match="disk full"):
            compact_facts(memory_path, [CompactMerge(sources=["aaa bbb ccc"], target="merged entry text here")])

        assert memory_path.read_bytes() == before  # MEMORY.md 未动
        assert not (memory_path.parent / "archive").exists()


class TestConcurrency:
    """AC3：compare-after-write——并发追加不被整份吞掉，冲突放弃本批、留底保留。"""

    def test_concurrent_append_not_clobbered_by_compaction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = ["aaa bbb ccc", "ddd eee fff", "ggg hhh iii"]
        _create_memory_file(memory_path, facts)

        real_update = compact_mod.atomic_update_text

        def spy(path: Path, update: object, **kwargs: object) -> bool:
            # 在 compact 预读之后、锁内写之前模拟并发 fact_add 追加。
            # 只对 MEMORY.md 注入：归档追加（审查修复后同样走 atomic_update_text）不是注入目标。
            if Path(path) == memory_path:
                with memory_path.open("a", encoding="utf-8") as handle:
                    handle.write("- 并发追加的事实\n")
            return real_update(path, update, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(compact_mod, "atomic_update_text", spy)

        with pytest.raises(FactCompactConflictError, match="concurrently"):
            compact_facts(
                memory_path,
                [CompactMerge(sources=["aaa bbb ccc", "ggg hhh iii"], target="merged first third entries")],
            )

        # 外部新内容不被覆盖；原有条目一条不少（合并未应用）。
        remaining = _facts_of(memory_path)
        assert "并发追加的事实" in remaining
        assert remaining[: len(facts)] == facts
        # 留底先行 ⇒ 归档已落档且保留（宁重复不丢失，写进判据）。
        assert "- aaa bbb ccc" in _archive_of(memory_path)
        assert "- ggg hhh iii" in _archive_of(memory_path)


class TestExplicitFailure:
    """AC4：校验失败整批拒绝（不部分应用），一次性点名全部问题条目。"""

    def test_missing_source_rejects_batch_and_names_entry(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc"])
        before = memory_path.read_bytes()

        with pytest.raises(ValueError, match="no such entry"):
            compact_facts(memory_path, [CompactMerge(sources=["no such entry"], target="merged entry text here")])

        assert memory_path.read_bytes() == before
        assert not (memory_path.parent / "archive").exists()

    def test_non_unique_source_rejects_batch(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "aaa bbb ccc"])

        with pytest.raises(ValueError, match="must be unique.*aaa bbb ccc"):
            compact_facts(memory_path, [CompactMerge(sources=["aaa bbb ccc"], target="merged entry text here")])

    def test_duplicate_claim_across_merges_rejects_batch(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "ddd eee fff"])

        with pytest.raises(ValueError, match="already claimed"):
            compact_facts(
                memory_path,
                [
                    CompactMerge(sources=["aaa bbb ccc"], target="first merged entry text"),
                    CompactMerge(sources=["aaa bbb ccc", "ddd eee fff"], target="second merged entry text"),
                ],
            )

    def test_target_duplicating_batch_source_rejects_batch(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "ddd eee fff"])

        with pytest.raises(ValueError, match="must not duplicate a source"):
            compact_facts(
                memory_path,
                [
                    CompactMerge(sources=["aaa bbb ccc"], target="ddd eee fff"),
                    CompactMerge(sources=["ddd eee fff"], target="unrelated fresh entry text"),
                ],
            )

    def test_blank_or_multiline_target_rejected(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc"])
        before = memory_path.read_bytes()

        with pytest.raises(ValueError, match="must not be blank"):
            compact_facts(memory_path, [CompactMerge(sources=["aaa bbb ccc"], target="   ")])

        with pytest.raises(ValueError, match="single line"):
            compact_facts(memory_path, [CompactMerge(sources=["aaa bbb ccc"], target="line one\n- injected line")])

        assert memory_path.read_bytes() == before

    def test_all_problems_reported_at_once(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc"])

        with pytest.raises(ValueError) as exc_info:
            compact_facts(
                memory_path,
                [
                    CompactMerge(sources=["missing one"], target="first merged entry text"),
                    CompactMerge(sources=["missing two"], target="second merged entry text"),
                ],
            )
        message = str(exc_info.value)
        assert "missing one" in message and "missing two" in message

    def test_empty_sources_rejected_by_model_constraint(self) -> None:
        """``CompactMerge`` 的 sources 下界（min_length=1）在模型构造期即拒绝。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CompactMerge(sources=[], target="anything")


class TestDedupScope:
    """AC5：判重只看「未被本批移除的条目」；命中只拒该条 merge；顺序化应用。"""

    def test_target_duplicating_surviving_entry_rejects_merge_only(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        # "user prefers dark mode" 幸存（不在任何 merge 的 sources 里）。
        _create_memory_file(memory_path, ["aaa bbb ccc", "user prefers dark mode", "ddd eee fff"])

        stats = compact_facts(
            memory_path,
            [
                # target 与幸存条目重叠 4/5 > 70% ⇒ 仅这条 merge 被拒。
                CompactMerge(sources=["aaa bbb ccc"], target="user prefers dark mode always"),
                CompactMerge(sources=["ddd eee fff"], target="second merged entry text"),
            ],
        )

        assert stats.applied_merges == 1
        assert len(stats.rejected) == 1
        assert stats.rejected[0].target == "user prefers dark mode always"
        assert ">70% word overlap" in stats.rejected[0].reason
        # 被拒 merge 的 source 留在正文；被采纳 merge 正常应用。
        assert _facts_of(memory_path) == [
            "aaa bbb ccc",
            "user prefers dark mode",
            "second merged entry text",
        ]

    def test_target_overlapping_own_sources_allowed(self, tmp_path: Path) -> None:
        """被删 source 不参与判重——target 高重叠自身 source 是合并的本意，不得自拒。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["the quick brown fox jumps", "unrelated entry words here"])

        stats = compact_facts(
            memory_path,
            [
                CompactMerge(
                    sources=["the quick brown fox jumps", "unrelated entry words here"], target="the quick brown fox"
                )
            ],
        )

        assert stats.applied_merges == 1
        assert stats.rejected == []
        assert _facts_of(memory_path) == ["the quick brown fox"]

    def test_sequential_dedup_covers_earlier_targets(self, tmp_path: Path) -> None:
        """后一条 merge 的判重集合含前序 merge 已追加的 target ⇒ 批内产物互不重复。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "ddd eee fff"])

        stats = compact_facts(
            memory_path,
            [
                CompactMerge(sources=["aaa bbb ccc"], target="shared target entry text"),
                # target 与前序 merge 的 target 重叠 4/5 > 70% ⇒ 被拒。
                CompactMerge(sources=["ddd eee fff"], target="shared target entry text again"),
            ],
        )

        assert stats.applied_merges == 1
        assert len(stats.rejected) == 1
        assert _facts_of(memory_path) == ["ddd eee fff", "shared target entry text"]


class TestNoOp:
    """全部 merge 被判重拒绝 ⇒ 无操作：文件一字不动、不写归档。"""

    def test_all_rejected_writes_nothing(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc", "user prefers dark mode"])
        before = memory_path.read_bytes()

        stats = compact_facts(
            memory_path,
            [CompactMerge(sources=["aaa bbb ccc"], target="user prefers dark mode always")],
        )

        assert stats.applied_merges == 0
        assert stats.facts_before == stats.facts_after == 2
        assert stats.archive_path == ""
        assert memory_path.read_bytes() == before
        assert not (memory_path.parent / "archive").exists()


class TestEncoding:
    def test_bom_file_normalized_on_write(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        memory_path.parent.mkdir(parents=True)
        memory_path.write_bytes(
            b"\xef\xbb\xbf# HeAgent \xe9\x95\xbf\xe6\x9c\x9f\xe8\xae\xb0\xe5\xbf\x86\n\n- aaa bbb ccc\n"
        )

        stats = compact_facts(memory_path, [CompactMerge(sources=["aaa bbb ccc"], target="merged entry text here")])

        assert stats.applied_merges == 1
        raw = memory_path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")  # 与 add() 同口径：写回时归一化掉 BOM
        assert "merged entry text here" in raw.decode("utf-8")

    def test_invalid_utf8_raises_valueerror_naming_path(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        memory_path.parent.mkdir(parents=True)
        memory_path.write_bytes(b"- \xd6\xd0\xce\xc4 GBK bytes\n")

        with pytest.raises(ValueError, match="MEMORY.md.*UTF-8"):
            compact_facts(memory_path, [CompactMerge(sources=["x"], target="y")])

    def test_missing_file_treated_as_no_facts(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"

        with pytest.raises(ValueError, match="ghost entry"):
            compact_facts(memory_path, [CompactMerge(sources=["ghost entry"], target="merged entry text here")])


class TestAggregate:
    """窗口聚合（59-2 dream_end 统计的源头）：计数求和、首尾口径、rejected 拼接、空窗口 None。"""

    def test_empty_window_returns_none(self) -> None:
        assert aggregate_compactions([]) is None

    def test_single_stats_passes_through_semantics(self) -> None:
        stats = CompactStats(
            applied_merges=1,
            removed=2,
            added=1,
            facts_before=10,
            facts_after=9,
            bytes_freed=50,
            archive_path="a.md",
        )
        agg = aggregate_compactions([stats])
        assert agg is not None
        assert (agg.applied_merges, agg.removed, agg.added) == (1, 2, 1)
        assert (agg.facts_before, agg.facts_after) == (10, 9)
        assert agg.archive_path == "a.md"

    def test_multi_window_first_before_last_after_sums_and_rejected_concat(self) -> None:
        first = CompactStats(
            applied_merges=1,
            removed=2,
            added=1,
            facts_before=10,
            facts_after=9,
            bytes_freed=30,
            archive_path="a.md",
            rejected=[CompactRejection(sources=["s1"], target="t1", reason="dup")],
        )
        last = CompactStats(
            applied_merges=2,
            removed=3,
            added=2,
            facts_before=9,
            facts_after=8,
            bytes_freed=-5,
            archive_path="",
        )
        agg = aggregate_compactions([first, last])
        assert agg is not None
        assert (agg.applied_merges, agg.removed, agg.added) == (3, 5, 3)
        assert (agg.facts_before, agg.facts_after) == (10, 8)  # 首/尾口径
        assert agg.bytes_freed == 25  # 可为负的净变化如实求和
        assert agg.archive_path == "a.md"  # 取最后一个非空留底位置
        assert [r.target for r in agg.rejected] == ["t1"]


class TestFactStoreDrain:
    """FactStore 实例级累积 + drain（dream 闭包窗口归属的存储侧判据）。"""

    def test_compact_accumulates_and_drain_clears(self, tmp_path: Path) -> None:
        store = FactStore(path=str(tmp_path / "memory" / "MEMORY.md"))
        store.add("aaa bbb ccc")
        store.add("ddd eee fff")

        stats = store.compact([CompactMerge(sources=["aaa bbb ccc"], target="merged entry text here")])
        assert stats.applied_merges == 1

        drained = store.drain_compactions()
        assert len(drained) == 1
        assert drained[0].applied_merges == 1
        assert store.drain_compactions() == []  # drain 即清空

    def test_rejected_only_compact_not_recorded(self, tmp_path: Path) -> None:
        """全部被判重拒绝的「无操作」压缩不留统计（未发生移除，进窗口统计会是假信号）。"""
        store = FactStore(path=str(tmp_path / "memory" / "MEMORY.md"))
        store.add("aaa bbb ccc")
        store.add("user prefers dark mode")

        stats = store.compact([CompactMerge(sources=["aaa bbb ccc"], target="user prefers dark mode always")])
        assert stats.applied_merges == 0
        assert store.drain_compactions() == []


class TestArchiveSerialization:
    """审查 HIGH 修复的回归判据：归档追加必须经 atomic_update_text 锁内串行化。"""

    def test_archive_append_goes_through_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """无锁 read-modify-write 会让并发 compact 互相覆盖留底小节（无声数据丢失）。

        本用例钉机制而非竞态：归档路径必须经 :func:`atomic_update_text`（归档自身 .lock），
        与 MEMORY.md 的比较后写共用同一锁原语族。
        """
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, ["aaa bbb ccc"])
        locked_paths: list[Path] = []

        real_update = compact_mod.atomic_update_text

        def spy(path: Path, update: object, **kwargs: object) -> bool:
            locked_paths.append(Path(path))
            return real_update(path, update, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(compact_mod, "atomic_update_text", spy)

        compact_facts(memory_path, [CompactMerge(sources=["aaa bbb ccc"], target="merged entry text here")])

        archive_path = memory_path.parent / "archive" / "MEMORY-archive.md"
        assert archive_path in locked_paths, "归档追加必须经 atomic_update_text（锁内串行化）"
        assert "merged entry text here" in memory_path.read_text(encoding="utf-8")
