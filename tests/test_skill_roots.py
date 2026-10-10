"""双根技能库行为：全局优先读取、写路由、跨根删除拒绝、冲突清单与警告、catalog 消歧。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from heagent.skills.skill_packages import SkillCatalog, SkillResolutionError, SkillResolver
from heagent.skills.skill_store import SkillStore, default_skill_roots


@pytest.fixture()
def two_roots(tmp_path: Path) -> tuple[SkillStore, Path, Path]:
    """全局根（含 demo 技能）+ 本地根（含同名 demo），返回 (store, 全局根, 本地根)。"""
    global_root = tmp_path / "global"
    local_root = tmp_path / "local"
    global_store = SkillStore(str(global_root))
    global_store.save("demo", "global version", "pattern g", ["step g"], tags=["demo"])
    local_store = SkillStore(str(local_root))
    local_store.save("demo", "local version", "pattern l", ["step l"], tags=["demo"])
    local_store.save("local_only", "only here", "pattern", ["step"])
    return SkillStore([str(global_root), str(local_root)]), global_root, local_root


class TestDualRootStore:
    def test_default_skill_roots_global_first(self, tmp_path: Path) -> None:
        roots = default_skill_roots(tmp_path)
        assert roots[0].endswith("skills")
        assert ".heagent" in roots[0]  # ~/.heagent/skills
        assert roots[1] == str(tmp_path / ".heagent" / "skills")

    def test_read_prefers_first_root(self, two_roots: tuple[SkillStore, Path, Path]) -> None:
        store, _global_root, _local_root = two_roots
        raw = store.load("demo")
        assert raw is not None and "global version" in raw
        parsed = store.parse("demo")
        assert parsed is not None and parsed.description == "global version"
        assert store.list_skills() == ["demo", "local_only"]
        assert store.owner_root("demo") is not None

    def test_shadowed_warning_fires_once_per_name(
        self, two_roots: tuple[SkillStore, Path, Path], caplog: pytest.LogCaptureFixture
    ) -> None:
        store, _global_root, _local_root = two_roots
        with caplog.at_level(logging.WARNING, logger="heagent.skills.skill_store"):
            store.list_skills()
            store.list_skills()
        assert sum(1 for r in caplog.records if "multiple roots" in r.message) == 1

    def test_conflicts_report_effective_and_shadowed(self, two_roots: tuple[SkillStore, Path, Path]) -> None:
        store, global_root, local_root = two_roots
        conflicts = store.conflicts()
        assert [(c.name, c.effective_root, c.shadowed_root) for c in conflicts] == [
            ("demo", str(global_root), str(local_root))
        ]
        # 差异数据源：两份 meta 可比对（tags 同为 ["demo"]，描述差异在 SKILL.md 不在 meta）
        assert conflicts[0].effective_meta.tags == ["demo"]
        assert conflicts[0].shadowed_meta.tags == ["demo"]

    def test_save_existing_routes_to_owner_new_goes_to_authoring(
        self, two_roots: tuple[SkillStore, Path, Path]
    ) -> None:
        store, global_root, local_root = two_roots
        # 已存在于全局 → 就地更新拥有根
        path = store.save("demo", "rewritten", "pattern", ["step"])
        assert str(global_root) in path
        assert "rewritten" in (global_root / "demo" / "SKILL.md").read_text(encoding="utf-8")
        # 新建 → authoring（本地）根
        path = store.save("fresh", "new skill", "pattern", ["step"])
        assert str(local_root) in path
        assert store.load("fresh") is not None

    def test_usage_and_update_accumulate_on_owner_root(self, two_roots: tuple[SkillStore, Path, Path]) -> None:
        store, global_root, _local_root = two_roots
        store.record_usage("demo")
        # 跨实例（模拟另一项目/进程）读同一全局根：计数是全局技能的属性
        again = SkillStore(str(global_root))
        parsed = again.parse("demo")
        assert parsed is not None and parsed.usage_count == 1
        store.update("demo", description="updated in place")
        assert "updated in place" in (global_root / "demo" / "SKILL.md").read_text(encoding="utf-8")

    def test_delete_and_archive_refuse_cross_root(self, two_roots: tuple[SkillStore, Path, Path]) -> None:
        store, _global_root, local_root = two_roots
        with pytest.raises(ValueError, match="another root"):
            store.delete("demo")
        with pytest.raises(ValueError, match="another root"):
            store.archive("demo")
        # 本地根技能照常删
        assert store.delete("local_only") is True
        assert store.load("local_only") is None
        assert local_root is not None

    def test_single_root_default_keeps_hermetic_behavior(self, tmp_path: Path) -> None:
        """默认单根（不碰用户家目录）：delete/archive 语义与旧版逐字节一致。"""
        store = SkillStore(str(tmp_path / "only"))
        store.save("solo", "d", "p", ["s"])
        assert store.delete("solo") is True
        assert store.roots == (tmp_path / "only",)

    def test_empty_roots_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one root"):
            SkillStore([])


class TestDualRootCatalog:
    def test_scan_cross_root_first_source_wins(self, tmp_path: Path) -> None:
        first, second = tmp_path / "first", tmp_path / "second"
        first.mkdir()
        second.mkdir()
        for root, name in ((first, "he-one"), (second, "he-one")):
            (root / name).mkdir(parents=True)
            (root / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
        catalog = SkillCatalog([first, second])
        entries = catalog.scan()
        assert [e.canonical_id for e in entries] == ["he-one"]
        assert entries[0].package_root == str((first / "he-one").resolve())
        assert len(catalog.conflicts) == 1

    def test_different_ids_clashing_alias_still_ambiguous(self, tmp_path: Path) -> None:
        """跨根消歧只对同 id 生效；不同 id 撞同一别名仍显性 ambiguous（resolve 零改动）。"""
        first, second = tmp_path / "first", tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "he-prd").mkdir()
        (first / "he-prd" / "SKILL.md").write_text("---\nname: he-prd\n---\n", encoding="utf-8")
        (first / "he-prd" / "meta.yaml").write_text("aliases: [shared]\n", encoding="utf-8")
        (second / "he-doc").mkdir()
        (second / "he-doc" / "SKILL.md").write_text("---\nname: he-doc\n---\n", encoding="utf-8")
        (second / "he-doc" / "meta.yaml").write_text("aliases: [shared]\n", encoding="utf-8")
        catalog = SkillCatalog([first, second])
        catalog.scan()
        with pytest.raises(SkillResolutionError, match="ambiguous"):
            SkillResolver(catalog).resolve("shared")

    def test_single_root_scan_has_no_conflicts(self, tmp_path: Path) -> None:
        (tmp_path / "he-a").mkdir()
        (tmp_path / "he-a" / "SKILL.md").write_text("---\nname: he-a\n---\n", encoding="utf-8")
        catalog = SkillCatalog([tmp_path])
        assert catalog.scan()
        assert catalog.conflicts == []
