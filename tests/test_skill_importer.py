from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from heagent.memory.skill_importer import SkillImportError, SkillImporter


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["canonicalId", "name", "description", "module", "path"])
        writer.writeheader()
        writer.writerows(rows)


def make_source(root: Path, name: str = "bmad-prd", body: str = "# PRD\n") -> Path:
    package = root / "_bmad" / "core" / name
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(f"---\nname: {name}\nversion: 1.0\n---\n{body}", encoding="utf-8")
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
