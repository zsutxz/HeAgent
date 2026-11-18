"""Story 66.4：技能包 entry 按需懒加载（索引期只读一次 entry）。

现状（改前）：``SkillCatalog._index_package`` 对每个包读**两次** entry——先
``provisional.read_entry()`` 定 ``canonical_id``，再 ``package.read_entry()`` 且丢弃返回。

三条硬判据：
- **计数**：单包 ``scan()`` 只读 1 次 ``SKILL.md``；多包目录 = 包数（改前是 2×）。
- **懒**：``SkillPackage`` 构造不读任何文件；首次访问 ``metadata`` 读 1 次；再次访问不读。
- **等价**：注入的元数据与「重新读一遍 entry」得到的结果一致（skill_id 换成 canonical id）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.skills import skill_packages
from heagent.skills.skill_packages import SkillCatalog, SkillPackage

ENTRY_NAME = "SKILL.md"


@pytest.fixture()
def read_log(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """记录每次经安全内核的文本读取路径（entry 与 resource 共用同一入口）。"""
    calls: list[Path] = []
    original = skill_packages.read_text_with_digest_under_root

    def recording(root: Path, path: Path) -> tuple[str, str]:
        calls.append(Path(path))
        return original(root, path)

    monkeypatch.setattr(skill_packages, "read_text_with_digest_under_root", recording)
    return calls


def entry_reads(calls: list[Path]) -> list[Path]:
    return [path for path in calls if path.name == ENTRY_NAME]


def make_package(root: Path, name: str = "he-build", *, canonical_id: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ENTRY_NAME).write_text(
        f"---\nname: {name}\ndescription: Build a feature\n---\n\n# Build\n",
        encoding="utf-8",
        newline="\n",
    )
    meta = "version: 1.2.3\ntags: [build]\n"
    if canonical_id:
        meta = f"canonical_id: {canonical_id}\n" + meta
    (root / "meta.yaml").write_text(meta, encoding="utf-8", newline="\n")
    return root


class TestSingleEntryRead:
    def test_single_package_scan_reads_the_entry_once(self, tmp_path: Path, read_log: list[Path]) -> None:
        make_package(tmp_path / "he-build")

        entries = SkillCatalog([tmp_path]).scan()

        assert [entry.canonical_id for entry in entries] == ["he-build"]
        assert len(entry_reads(read_log)) == 1, "索引期不得二次读 entry（改前为 2 次）"

    def test_multi_package_scan_reads_one_entry_per_package(self, tmp_path: Path, read_log: list[Path]) -> None:
        for name in ("he-build", "he-review", "he-deploy"):
            make_package(tmp_path / name, name)

        entries = SkillCatalog([tmp_path]).scan()

        assert len(entries) == 3
        assert len(entry_reads(read_log)) == 3, "总读取次数应等于包数（改前为 2×包数）"

    def test_root_that_is_itself_a_package_reads_once(self, tmp_path: Path, read_log: list[Path]) -> None:
        make_package(tmp_path)

        entries = SkillCatalog([tmp_path]).scan()

        assert len(entries) == 1
        assert len(entry_reads(read_log)) == 1

    def test_scan_does_not_read_resources(self, tmp_path: Path, read_log: list[Path]) -> None:
        package = make_package(tmp_path / "he-build")
        (package / "templates").mkdir()
        (package / "templates" / "GOAL.md").write_text("template body", encoding="utf-8")

        SkillCatalog([tmp_path]).scan()

        assert [path.name for path in read_log] == [ENTRY_NAME, "meta.yaml"], (
            "只有 entry 与 meta.yaml 该被读；templates 一律按需"
        )


class TestMetadataInjection:
    def test_injected_metadata_is_equivalent_to_a_fresh_read(self, tmp_path: Path, read_log: list[Path]) -> None:
        package_root = make_package(tmp_path / "legacy", "legacy", canonical_id="he-prd")

        entry = SkillCatalog([tmp_path]).scan()[0]

        assert entry.package is not None
        injected = entry.package.metadata
        fresh = SkillPackage(skill_id="he-prd", root=package_root).read_entry().metadata
        assert injected.model_dump() == fresh.model_dump()
        assert injected.skill_id == "he-prd", "注入后 skill_id 是 canonical id，不是目录名"
        assert entry.available and entry.error is None

    def test_defaulted_name_follows_the_first_read(self, tmp_path: Path) -> None:
        """frontmatter 缺 ``name`` 时名称由 canonical id 回落（不是目录名），与重新读一致。"""
        package_root = tmp_path / "legacy-dir"
        package_root.mkdir()
        (package_root / ENTRY_NAME).write_text("---\ndescription: no name here\n---\n\n# body\n", encoding="utf-8")
        (package_root / "meta.yaml").write_text("canonical_id: he-flow\n", encoding="utf-8")

        entry = SkillCatalog([tmp_path]).scan()[0]

        assert entry.package is not None
        injected = entry.package.metadata
        fresh = SkillPackage(skill_id="he-flow", root=package_root).read_entry().metadata
        assert injected.skill_id == "he-flow" and injected.name == "he-flow"
        assert injected.model_dump() == fresh.model_dump(), "注入结果须与重新读 entry 逐字段一致"

    def test_unavailable_package_keeps_the_diagnostic(self, tmp_path: Path) -> None:
        package = make_package(tmp_path / "he-off")
        (package / "meta.yaml").write_text("available: false\n", encoding="utf-8", newline="\n")

        entry = SkillCatalog([tmp_path]).scan()[0]

        assert entry.package is None
        assert not entry.available
        assert entry.error is not None and "unavailable" in entry.error

    def test_integrity_check_still_runs_on_the_single_read(self, tmp_path: Path) -> None:
        """注入不得绕过完整性校验：manifest.json 摘要不符仍显性失败（本条落成不可用条目）。"""
        import hashlib
        import json

        package = make_package(tmp_path / "he-build")
        (package / ENTRY_NAME).write_text(
            "---\nname: he-build\ndescription: Build a feature\n---\n\n# Tampered\n", encoding="utf-8"
        )
        digest = hashlib.sha256((package / ENTRY_NAME).read_bytes()).hexdigest()
        (package / "manifest.json").write_text(json.dumps({"outputs": {ENTRY_NAME: "0" * 64}}), encoding="utf-8")
        assert digest != "0" * 64

        entry = SkillCatalog([tmp_path]).scan()[0]

        assert not entry.available
        assert entry.error is not None and "content hash differs" in entry.error


class TestLazySemantics:
    def test_construction_reads_nothing(self, tmp_path: Path, read_log: list[Path]) -> None:
        package_root = make_package(tmp_path / "he-build")

        package = SkillPackage(skill_id="he-build", root=package_root)

        assert read_log == []
        assert package.skill_id == "he-build"

    def test_first_metadata_access_reads_once_then_is_cached(self, tmp_path: Path, read_log: list[Path]) -> None:
        package = SkillPackage(skill_id="he-build", root=make_package(tmp_path / "he-build"))

        first = package.metadata
        reads_after_first = len(entry_reads(read_log))
        second = package.metadata

        assert reads_after_first == 1
        assert len(entry_reads(read_log)) == reads_after_first, "二次访问 metadata 不得重复读"
        assert first is second

    def test_resources_stay_on_demand(self, tmp_path: Path, read_log: list[Path]) -> None:
        package_root = make_package(tmp_path / "he-build")
        (package_root / "references").mkdir()
        (package_root / "references" / "api.md").write_text("api body", encoding="utf-8")
        package = SkillPackage(skill_id="he-build", root=package_root)
        _ = package.metadata

        assert package.read_reference("api.md") == "api body"

        assert [path.name for path in read_log] == [ENTRY_NAME, "meta.yaml", "api.md"]
