"""Tests for the ``fact_compact`` tool layer (Epic 59 / Story 59-1，工具边界)。

覆盖 story AC 的工具侧判据：

- **AC6 开关 fail-closed**：``memory_compact_enabled`` 默认 False；关闭即显性报错（不静默成功），
  文件不动；开启后正常执行。
- **AC7 未绑定降级**：FactStore 未绑定 ⇒ 与 ``fact_add`` 同款错误。
- **参数整形**：``merges`` 条目畸形（缺键 / 非 dict / 空列表）⇒ 显性报错，不触 store。
- **结果格式化**：统计 + 留底位置 + 逐条拒绝原因进返回文本（FR6 的工具侧出口）。
- **description 即写侧闸门**：关键准则（精确匹配 / 留底先行 / 开关）必须在 description 里
  （``@tool`` 生成的参数 schema 对 ``list`` 无条目结构，准则只住这一处）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest  # noqa: TC002 - @pytest.fixture 是运行期用法

from heagent.memory.compact import FactCompactConflictError
from heagent.memory.facts import FactStore
from heagent.tools.builtins import memory as memory_tools
from heagent.tools.builtins.memory import configure_memory_tools, fact_compact, reset_memory_tools
from heagent.tools.registry import ToolRegistry


def _settings(memory_compact_enabled: bool) -> SimpleNamespace:
    """工具只读 ``memory_compact_enabled`` 一个键；用命名空间隔离项目 ``.env`` 污染。"""
    return SimpleNamespace(memory_compact_enabled=memory_compact_enabled)


@pytest.fixture(autouse=True)
def _reset_after() -> None:
    """Wipe module-level memory tool state between tests to avoid cross-test pollution."""
    yield
    reset_memory_tools()


def _store_with_facts(path: Path, facts: list[str]) -> FactStore:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# HeAgent 长期记忆\n\n" + "\n".join(f"- {fact}" for fact in facts) + "\n", encoding="utf-8")
    return FactStore(path=str(path))


def _enabled(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> None:
    monkeypatch.setattr(memory_tools, "get_settings", lambda: _settings(enabled))


_VALID_MERGES = [{"sources": ["aaa bbb ccc", "ggg hhh iii"], "target": "merged first third entries"}]


class TestGates:
    """AC6 / AC7：开关 fail-closed 与未绑定降级。"""

    async def test_unbound_store_reports_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enabled(monkeypatch, enabled=True)  # 开关即使开着，未绑定也先降级
        result = await fact_compact(merges=_VALID_MERGES)
        assert result == "Error: fact tools not configured."

    async def test_disabled_by_default_fails_closed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _enabled(monkeypatch, enabled=False)
        memory_path = tmp_path / "memory" / "MEMORY.md"
        configure_memory_tools(facts=_store_with_facts(memory_path, ["aaa bbb ccc"]))
        before = memory_path.read_bytes()

        result = await fact_compact(merges=_VALID_MERGES)

        assert result == "Error: memory compaction is disabled (memory_compact_enabled=false)."
        assert memory_path.read_bytes() == before  # 文件不动
        assert not (memory_path.parent / "archive").exists()

    async def test_enabled_switch_executes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _enabled(monkeypatch, enabled=True)
        memory_path = tmp_path / "memory" / "MEMORY.md"
        configure_memory_tools(facts=_store_with_facts(memory_path, ["aaa bbb ccc", "ggg hhh iii"]))

        result = await fact_compact(merges=_VALID_MERGES)

        assert result.startswith("Compacted: 1 merge(s) applied")
        assert "merged first third entries" in memory_path.read_text(encoding="utf-8")


class TestArgShaping:
    """merges 条目畸形 ⇒ 显性报错，不触 store。"""

    async def test_empty_merges_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _enabled(monkeypatch, enabled=True)
        configure_memory_tools(facts=_store_with_facts(tmp_path / "memory" / "MEMORY.md", ["aaa bbb ccc"]))
        result = await fact_compact(merges=[])
        assert result == "Error: merges must not be empty."

    async def test_missing_target_key_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _enabled(monkeypatch, enabled=True)
        configure_memory_tools(facts=_store_with_facts(tmp_path / "memory" / "MEMORY.md", ["aaa bbb ccc"]))

        result = await fact_compact(merges=[{"sources": ["aaa bbb ccc"]}])

        assert result.startswith("Error: each merge must be")

    async def test_non_dict_item_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _enabled(monkeypatch, enabled=True)
        configure_memory_tools(facts=_store_with_facts(tmp_path / "memory" / "MEMORY.md", ["aaa bbb ccc"]))

        result = await fact_compact(merges=["not-a-dict"])  # type: ignore[list-item]

        assert result.startswith("Error: each merge must be")


class TestResultFormatting:
    """FR6 的工具侧出口：统计、留底位置、拒绝原因、冲突文案。"""

    async def test_reports_stats_and_archive_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _enabled(monkeypatch, enabled=True)
        memory_path = tmp_path / "memory" / "MEMORY.md"
        configure_memory_tools(
            facts=_store_with_facts(memory_path, ["aaa bbb ccc", "user prefers dark mode", "ddd eee fff"])
        )

        result = await fact_compact(
            merges=[
                {"sources": ["aaa bbb ccc"], "target": "user prefers dark mode always"},  # 判重命中 ⇒ 拒
                {"sources": ["ddd eee fff"], "target": "second merged entry text"},
            ]
        )

        assert "1 merge(s) applied" in result
        assert "Archived to:" in result
        assert "Rejected merge (target='user prefers dark mode always')" in result

    async def test_conflict_error_mentions_archive_retention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enabled(monkeypatch, enabled=True)
        memory_path = tmp_path / "memory" / "MEMORY.md"
        configure_memory_tools(facts=_store_with_facts(memory_path, ["aaa bbb ccc"]))

        def boom(merges: object) -> None:
            raise FactCompactConflictError("MEMORY.md changed concurrently; batch rejected")

        # duck-typing 注入：工具层只调 store.compact
        configure_memory_tools(facts=SimpleNamespace(compact=boom))  # type: ignore[arg-type]

        result = await fact_compact(merges=_VALID_MERGES)

        assert result.startswith("Error: MEMORY.md changed concurrently")


class TestDescription:
    """description 是唯一触达模型的写侧闸门（参数 schema 对 list 无条目结构）。"""

    def test_description_carries_write_side_criteria(self) -> None:
        schema = ToolRegistry.get().get_schema("fact_compact")
        assert schema is not None, "fact_compact must be auto-registered by @tool"
        description = schema.description
        assert "exactly and uniquely" in description  # D6 精确匹配
        assert "archived before MEMORY.md is rewritten" in description  # D3 留底先行
        assert "memory_compact_enabled" in description  # D5 默认关
        assert "when uncertain, do not merge" in description  # 不确定不改
        assert schema.parameters["properties"]["merges"] == {"type": "array"}  # 条目结构只在 description
