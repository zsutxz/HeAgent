"""Tests for MEMORY.md auto-archive mechanism (2026-10-10 重写后的口径).

覆盖三件事：

1. **策略**：超 `memory_archive_trigger_bytes` 时只移走「前 N 条核心约定」与「最新尾部」之间的
   中间条目，保持文件原序，且不丢条目。
2. **两条回归**（原实现的缺陷，必须有判据钉住）：① 不再产生 ``<YYYY-MM>.md`` 这类**虚构月份**文件；
   ② 重写时**不再丢弃** fact 之后的非 ``- `` 行（小节标题 / 空行）。
3. **并发**：MEMORY.md 走 ``atomic_update_text`` + 比较后写，并发 ``fact_add`` 的追加不会被整卷覆盖。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import heagent.memory.auto_archive as auto_archive
from heagent.config import Settings
from heagent.memory.auto_archive import CORE_FACTS_TO_KEEP, maybe_archive_old_facts

if TYPE_CHECKING:  # pytest 只用于注解 ⇒ 放类型检查块（TC002）
    import pytest

_HEADING = re.compile(r"^## 批次 \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC（\d+ 条）$")


def _create_memory_file(path: Path, facts: list[str], *, header: str = "# HeAgent 长期记忆\n\n> 测试文件\n\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(f"- {fact}" for fact in facts) + "\n", encoding="utf-8")


def _facts_of(path: Path) -> list[str]:
    return [ln[2:] for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]


def _settings(trigger: int, *, throttle: int = 0) -> Settings:
    """显式传两个键 —— 项目的 ``.env`` 里可能覆盖它们，不显式传会污染判据。"""
    return Settings(memory_archive_trigger_bytes=trigger, memory_archive_min_interval_seconds=throttle)


def _uniform_facts(count: int, pad: int = 80) -> list[str]:
    return [f"fact-{i:03d}-" + "x" * pad for i in range(count)]


def _line_bytes(fact: str) -> int:
    return len(f"- {fact}\n".encode())


class TestGating:
    def test_disabled_when_trigger_bytes_is_zero(self, tmp_path: Path) -> None:
        """``memory_archive_trigger_bytes=0`` ⇒ 整体禁用（文件一字不动、不建归档目录）。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        _create_memory_file(memory_path, _uniform_facts(60))
        before = memory_path.read_bytes()

        result = maybe_archive_old_facts(memory_path, _settings(0))

        assert result == {"archived": 0, "kept": 0, "skipped": True}
        assert memory_path.read_bytes() == before
        assert not (memory_path.parent / "archive").exists()

    def test_skips_when_file_does_not_exist(self, tmp_path: Path) -> None:
        result = maybe_archive_old_facts(tmp_path / "memory" / "MEMORY.md", _settings(1000))
        assert result["skipped"] is True
        assert result["archived"] == 0

    def test_no_archive_when_fact_bytes_within_trigger(self, tmp_path: Path) -> None:
        """未超阈值 ⇒ 不归档、不建归档目录、MEMORY.md 逐字节不变。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = _uniform_facts(5)
        _create_memory_file(memory_path, facts)
        before = memory_path.read_bytes()

        result = maybe_archive_old_facts(memory_path, _settings(10_000))

        assert result == {"archived": 0, "kept": 5, "skipped": False}
        assert memory_path.read_bytes() == before
        assert not (memory_path.parent / "archive").exists()

    def test_fail_soft_when_read_explodes(self, tmp_path: Path) -> None:
        """fail-soft：读取失败（拿目录当文件）只返回全 0 统计，不抛。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        memory_path.mkdir(parents=True)
        result = maybe_archive_old_facts(memory_path, _settings(1))
        assert result == {"archived": 0, "kept": 0, "skipped": True}


class TestTrimPolicy:
    def test_archives_the_middle_and_keeps_core_plus_newest(self, tmp_path: Path) -> None:
        """保留 = 前 ``CORE_FACTS_TO_KEEP`` 条 + 能装进预算的**尾部**；移走的是中间那一段。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        total = 60
        facts = _uniform_facts(total)
        _create_memory_file(memory_path, facts)
        per_line = _line_bytes(facts[0])
        tail = 10
        trigger = (CORE_FACTS_TO_KEEP + tail) * per_line

        result = maybe_archive_old_facts(memory_path, _settings(trigger))

        assert result["archived"] == total - CORE_FACTS_TO_KEEP - tail
        assert result["kept"] == CORE_FACTS_TO_KEEP + tail
        remaining = _facts_of(memory_path)
        assert remaining == facts[:CORE_FACTS_TO_KEEP] + facts[total - tail :]

    def test_no_fact_is_lost_and_original_order_is_preserved(self, tmp_path: Path) -> None:
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = _uniform_facts(50)
        _create_memory_file(memory_path, facts)
        per_line = _line_bytes(facts[0])

        maybe_archive_old_facts(memory_path, _settings((CORE_FACTS_TO_KEEP + 5) * per_line))

        archived = _facts_of(memory_path.parent / "archive" / "MEMORY-archive.md")
        kept = _facts_of(memory_path)
        assert sorted(kept + archived) == sorted(facts)  # 一条不少、一条不多
        assert archived == [f for f in facts if f not in set(kept)]  # 归档内保持原序
        assert len(kept) + len(archived) == len(facts)

    def test_after_archiving_the_fact_bytes_fit_within_the_trigger(self, tmp_path: Path) -> None:
        """整理后 fact 总字节必须回到阈值以内 —— 否则下次启动会立刻再整理一次。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = _uniform_facts(80)
        _create_memory_file(memory_path, facts)
        per_line = _line_bytes(facts[0])
        trigger = 40 * per_line

        maybe_archive_old_facts(memory_path, _settings(trigger))

        used = sum(_line_bytes(f) for f in _facts_of(memory_path))
        assert used <= trigger

    def test_second_batch_appends_to_the_same_archive_file(self, tmp_path: Path) -> None:
        """第二批只追加小节，仍然是**一个**归档文件。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        first = _uniform_facts(50, pad=40)
        per_line = _line_bytes(first[0])
        _create_memory_file(memory_path, first)
        trigger = (CORE_FACTS_TO_KEEP + 5) * per_line
        maybe_archive_old_facts(memory_path, _settings(trigger))

        # 追加足够多的新条目，使文件再次超阈值
        with memory_path.open("a", encoding="utf-8") as handle:
            handle.write("".join(f"- {f}\n" for f in _uniform_facts(50, pad=40)))
        maybe_archive_old_facts(memory_path, _settings(trigger))

        archive_dir = memory_path.parent / "archive"
        assert [p.name for p in archive_dir.iterdir()] == ["MEMORY-archive.md"]
        merged = (archive_dir / "MEMORY-archive.md").read_text(encoding="utf-8")
        headings = [ln for ln in merged.splitlines() if ln.startswith("## ")]
        assert len(headings) == 2
        assert all(_HEADING.match(h) for h in headings)


class TestRegressionOldDefects:
    def test_no_monthly_archive_files_are_created(self, tmp_path: Path) -> None:
        """回归①：不再产生 ``<YYYY-MM>.md`` 这类**虚构月份**文件（原实现按外推年龄分桶）。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = _uniform_facts(50)
        _create_memory_file(memory_path, facts)

        maybe_archive_old_facts(memory_path, _settings((CORE_FACTS_TO_KEEP + 5) * _line_bytes(facts[0])))

        archive_dir = memory_path.parent / "archive"
        assert not list(archive_dir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].md"))

    def test_heading_timestamp_is_the_real_archive_time_not_a_fabricated_month(self, tmp_path: Path) -> None:
        """回归①的一半：小节标题的时间戳是真实 UTC 时间（结构可判定），不是外推月份。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = _uniform_facts(50)
        _create_memory_file(memory_path, facts)

        maybe_archive_old_facts(memory_path, _settings((CORE_FACTS_TO_KEEP + 5) * _line_bytes(facts[0])))

        text = (memory_path.parent / "archive" / "MEMORY-archive.md").read_text(encoding="utf-8")
        headings = [ln for ln in text.splitlines() if ln.startswith("## 批次")]
        assert headings and _HEADING.match(headings[0]), headings
        assert "归档动作的真实时间" in text  # 头部说明了时间戳的语义，避免再被误读成条目创建时间

    def test_non_fact_lines_after_a_fact_survive_the_rewrite(self, tmp_path: Path) -> None:
        """回归②：fact 之后的小节标题 / 空行**不再**被静默丢弃（原实现只保留首个 fact 之前的行）。

        ⚠ 构造要点（第一版判据是**假裁判**）：fact 数必须 > ``CORE_FACTS_TO_KEEP``，否则全部落在
        「永久保留区」⇒ 根本不触发归档 ⇒ 断言因「文件没动」而通过，抓不住任何缺陷。
        """
        memory_path = tmp_path / "memory" / "MEMORY.md"
        pad = 40
        pinned = [f"pinned-{i:02d}-" + "x" * pad for i in range(CORE_FACTS_TO_KEEP)]
        tail = [f"tail-{i:02d}-" + "x" * pad for i in range(CORE_FACTS_TO_KEEP, CORE_FACTS_TO_KEEP + 10)]
        body = ["# 标题", "", "> 头部说明", ""]
        body += [f"- {f}" for f in pinned]
        body += ["", "## 小节甲（夹在中间）", ""]
        body += [f"- {f}" for f in tail]
        body += ["", "## 小节乙（尾注）", ""]
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text("\n".join(body) + "\n", encoding="utf-8")

        per_line = _line_bytes(pinned[0])
        trigger = len(pinned) * per_line + 4 * per_line  # 只装得下 4 条尾部 ⇒ 中间 6 条被移走
        result = maybe_archive_old_facts(memory_path, _settings(trigger))

        assert result["archived"] == 6, "前提：本用例必须真的发生归档，否则断言毫无意义"
        after = memory_path.read_text(encoding="utf-8").splitlines()
        assert "# 标题" in after
        assert "> 头部说明" in after
        assert "## 小节甲（夹在中间）" in after  # ← 原实现在这里静默删掉
        assert "## 小节乙（尾注）" in after
        assert "" in after  # 空行同样保留
        assert _facts_of(memory_path) == pinned + tail[-4:]

    def test_untouched_lines_stay_byte_identical(self, tmp_path: Path) -> None:
        """除了被移走的 fact 行，其它行逐字不动（含头部与空行）。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = _uniform_facts(50)
        _create_memory_file(memory_path, facts)
        trigger = (CORE_FACTS_TO_KEEP + 5) * _line_bytes(facts[0])
        before = memory_path.read_text(encoding="utf-8").splitlines()

        maybe_archive_old_facts(memory_path, _settings(trigger))

        archived = set(_facts_of(memory_path.parent / "archive" / "MEMORY-archive.md"))
        after = memory_path.read_text(encoding="utf-8").splitlines()
        assert after == [ln for ln in before if not (ln.startswith("- ") and ln[2:] in archived)]


class TestThrottle:
    def test_respects_min_interval_throttling(self, tmp_path: Path) -> None:
        """节流标记写在 MEMORY.md 同目录（不再落到仓库的真实 ``.heagent/`` 上）。"""
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = _uniform_facts(50)
        _create_memory_file(memory_path, facts)
        trigger = (CORE_FACTS_TO_KEEP + 5) * _line_bytes(facts[0])

        settings = _settings(trigger, throttle=3600)
        maybe_archive_old_facts(memory_path, settings)
        second = maybe_archive_old_facts(memory_path, settings)

        assert (memory_path.parent / ".archive-stamp").exists()
        assert second["skipped"] is True


class TestConcurrency:
    def test_a_concurrent_append_is_not_clobbered_by_the_rewrite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """并发 ``fact_add`` 的追加不会被整卷覆盖：比较后写发现内容已变 ⇒ 放弃裁剪。

        归档文件此时**已经**写完（先落底后裁剪），所以归档里可能出现「仍在正文里」的重复条目 ——
        这是刻意的取舍（宁可留底重复，不可移出丢档），本用例把它写进判据。
        """
        memory_path = tmp_path / "memory" / "MEMORY.md"
        facts = _uniform_facts(50)
        _create_memory_file(memory_path, facts)

        real_update = auto_archive.atomic_update_text

        def spy(path: Path, update, **kwargs):  # type: ignore[no-untyped-def]
            with Path(path).open("a", encoding="utf-8") as handle:
                handle.write("- 并发追加的事实\n")
            return real_update(path, update, **kwargs)

        monkeypatch.setattr(auto_archive, "atomic_update_text", spy)

        result = maybe_archive_old_facts(memory_path, _settings((CORE_FACTS_TO_KEEP + 5) * _line_bytes(facts[0])))

        assert result["archived"] == 0  # 放弃裁剪
        remaining = _facts_of(memory_path)
        assert "并发追加的事实" in remaining
        assert remaining[: len(facts)] == facts  # 原有条目一条不少
        # 先落底 ⇒ 归档文件已存在（可能与正文重复），这是设计取舍
        assert (memory_path.parent / "archive" / "MEMORY-archive.md").exists()
