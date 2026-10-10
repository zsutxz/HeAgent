from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from heagent.skills.skill_importer import SkillImportError, SkillImporter


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["canonicalId", "name", "description", "module", "path"])
        writer.writeheader()
        writer.writerows(rows)


def make_source(root: Path, name: str = "bmad-prd", body: str = "# PRD\n") -> Path:
    package = root / "_bmad" / "core" / name
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}", encoding="utf-8")
    (package / "meta.yaml").write_text("version: 1.0\n", encoding="utf-8")
    return package


def manifest_row(canonical_id: str, path: str) -> dict[str, str]:
    return {"canonicalId": canonical_id, "name": canonical_id, "description": "", "module": "core", "path": path}


class TestSkillImporter:
    def test_materializes_canonical_package_and_lock(self, tmp_path: Path) -> None:
        source = make_source(tmp_path)
        manifest = tmp_path / "manifest.csv"
        write_manifest(
            manifest,
            [manifest_row("bmad-prd", str(source.relative_to(tmp_path)) + "/SKILL.md")],
        )

        records = SkillImporter(manifest, tmp_path / ".heagent" / "skills").import_manifest()

        # bmad-* manifest ids materialize under the same prefix (no he- rewrite).
        assert records[0].canonical_id == "bmad-prd"
        assert (tmp_path / ".heagent" / "skills" / "bmad-prd" / "SKILL.md").read_text(encoding="utf-8") == (
            source / "SKILL.md"
        ).read_text(encoding="utf-8")
        lock = json.loads((tmp_path / ".heagent" / "skills" / "manifest.lock").read_text(encoding="utf-8"))
        assert lock["entries"][0]["version"] == "1.0"
        assert len(lock["entries"][0]["source_hash"]) == 64

    def test_same_source_hash_is_idempotent(self, tmp_path: Path) -> None:
        source = make_source(tmp_path)
        manifest = tmp_path / "manifest.csv"
        row = manifest_row("bmad-prd", str(source.relative_to(tmp_path)) + "/SKILL.md")
        write_manifest(manifest, [row])
        importer = SkillImporter(manifest, tmp_path / "skills")
        first = importer.import_manifest()
        lock_before = (tmp_path / "skills" / "manifest.lock").read_text(encoding="utf-8")
        second = importer.import_manifest()
        assert second == first
        assert (tmp_path / "skills" / "manifest.lock").read_text(encoding="utf-8") == lock_before

    def test_missing_source_is_explicit(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.csv"
        write_manifest(
            manifest,
            [manifest_row("bmad-missing", "_bmad/core/missing/SKILL.md")],
        )
        with pytest.raises(SkillImportError, match=r"bmad-missing.*missing"):
            SkillImporter(manifest, tmp_path / "skills").import_manifest()

    def test_traversal_source_is_rejected(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.csv"
        write_manifest(
            manifest,
            [manifest_row("bmad-escape", "../secret/SKILL.md")],
        )
        with pytest.raises(SkillImportError, match=r"bmad-escape.*escapes"):
            SkillImporter(manifest, tmp_path / "skills").import_manifest()

    def test_duplicate_manifest_ids_are_rejected(self, tmp_path: Path) -> None:
        source = make_source(tmp_path)
        relative = str(source.relative_to(tmp_path)) + "/SKILL.md"
        manifest = tmp_path / "manifest.csv"
        row = {"canonicalId": "bmad-prd", "name": "bmad-prd", "description": "", "module": "core", "path": relative}
        write_manifest(manifest, [row, row])
        with pytest.raises(SkillImportError, match="duplicate"):
            SkillImporter(manifest, tmp_path / "skills").import_manifest()

    def test_corrupt_lock_is_rejected_without_overwrite(self, tmp_path: Path) -> None:
        source = make_source(tmp_path)
        manifest = tmp_path / "manifest.csv"
        write_manifest(
            manifest,
            [manifest_row("bmad-prd", str(source.relative_to(tmp_path)) + "/SKILL.md")],
        )
        destination = tmp_path / "skills"
        destination.mkdir()
        (destination / "manifest.lock").write_text("{broken", encoding="utf-8")
        with pytest.raises(SkillImportError, match="lock"):
            SkillImporter(manifest, destination).import_manifest()


def make_manifest(tmp_path: Path, source: Path) -> Path:
    manifest = tmp_path / "manifest.csv"
    write_manifest(manifest, [manifest_row("bmad-prd", str(source.relative_to(tmp_path)) + "/SKILL.md")])
    return manifest


def make_package_with_resource(tmp_path: Path) -> Path:
    source = make_source(tmp_path)
    (source / "references").mkdir()
    (source / "references" / "note.md").write_text("note\n", encoding="utf-8")
    return source


class TestResourcePinning:
    """A1④：lock 从「只钉入口」补成「钉整棵包」，并在落地前复核（判据与理由见台账同名条目）。"""

    def test_lock_pins_every_file_in_the_package(self, tmp_path: Path) -> None:
        source = make_package_with_resource(tmp_path)
        destination = tmp_path / "skills"

        SkillImporter(make_manifest(tmp_path, source), destination).import_manifest()

        resources = json.loads((destination / "manifest.lock").read_text(encoding="utf-8"))["entries"][0]["resources"]
        assert set(resources) == {"SKILL.md", "meta.yaml", "references/note.md"}
        for name, digest in resources.items():
            assert digest == hashlib.sha256((destination / "bmad-prd" / name).read_bytes()).hexdigest()

    def test_modified_source_resource_is_rejected_on_reimport(self, tmp_path: Path) -> None:
        """入口一字未动、包内其它文件被改 ⇒ 必须显性失败。

        此前 `source_hash` 只钉源 `SKILL.md`，这种漂移**静默放过**（重导入直接 no-op）。
        """
        source = make_package_with_resource(tmp_path)
        importer = SkillImporter(make_manifest(tmp_path, source), tmp_path / "skills")
        importer.import_manifest()

        (source / "references" / "note.md").write_text("tampered\n", encoding="utf-8")

        with pytest.raises(SkillImportError, match="package resources differ from manifest.lock"):
            importer.import_manifest()

    def test_modified_source_entry_is_rejected_on_reimport(self, tmp_path: Path) -> None:
        """入口本身变了 ⇒ 仍是既有的 ``source hash differs``（顺序：先入口、再整包）。"""
        source = make_source(tmp_path)
        importer = SkillImporter(make_manifest(tmp_path, source), tmp_path / "skills")
        importer.import_manifest()

        (source / "SKILL.md").write_text("---\nname: bmad-prd\n---\n# PRD v2\n", encoding="utf-8")

        with pytest.raises(SkillImportError, match="source hash differs from manifest.lock"):
            importer.import_manifest()

    def test_legacy_lock_without_resources_is_upgraded_in_place(self, tmp_path: Path) -> None:
        """老 lock（2026-09-28 之前写下、没有 ``resources``）不得让升级后的导入失败：内容未变 ⇒ 放行并补钉。"""
        source = make_source(tmp_path)
        destination = tmp_path / "skills"
        importer = SkillImporter(make_manifest(tmp_path, source), destination)
        importer.import_manifest()
        lock_path = destination / "manifest.lock"
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        del payload["entries"][0]["resources"]
        lock_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        records = importer.import_manifest()

        assert records[0].resources == {
            "SKILL.md": hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest(),
            "meta.yaml": hashlib.sha256((source / "meta.yaml").read_bytes()).hexdigest(),
        }
        assert json.loads(lock_path.read_text(encoding="utf-8"))["entries"][0]["resources"] == records[0].resources

    def test_tampered_materialization_is_rejected_before_landing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """算钉之后、落地之前被改写 ⇒ 显性失败，且**不留半成品**（destination 与 lock 都不出现）。"""
        source = make_source(tmp_path)
        destination = tmp_path / "skills"
        real_copytree = shutil.copytree

        def tampering_copytree(src: object, dst: object, **kwargs: object) -> object:
            result = real_copytree(src, dst, **kwargs)  # type: ignore[arg-type]
            Path(str(dst), "SKILL.md").write_text("---\nname: bmad-prd\ninjected\n---\n", encoding="utf-8")
            return result

        monkeypatch.setattr(shutil, "copytree", tampering_copytree)

        with pytest.raises(SkillImportError, match="materialized package differs from source"):
            SkillImporter(make_manifest(tmp_path, source), destination).import_manifest()

        assert not (destination / "bmad-prd").exists()
        assert not (destination / "manifest.lock").exists()
        assert not [p for p in destination.iterdir() if p.name.startswith(".bmad-prd-")], "临时目录必须回收"
