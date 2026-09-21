"""Import declared BMad skill packages into the local HeAgent skill directory."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from heagent.memory.skill_packages import SkillCatalog, SkillPackage
from heagent.persist import atomic_write_text
from heagent.tools.path_safety import WorkspacePathError, open_text_under_root, resolve_under_root


class SkillImportError(ValueError):
    """Raised when a manifest cannot be imported without ambiguity or loss."""

    def __init__(self, skill_id: str, reason: str) -> None:
        self.skill_id = skill_id
        self.reason = reason
        super().__init__(f"Skill import '{skill_id}': {reason}")


class SkillManifestEntry(BaseModel):
    """One row from the BMad skill manifest."""

    model_config = ConfigDict(extra="forbid")

    canonical_id: str
    name: str = ""
    description: str = ""
    module: str = ""
    path: str


class SkillLockEntry(BaseModel):
    """Immutable source and content metadata recorded after import."""

    canonical_id: str
    source_id: str
    source_path: str
    destination_path: str
    version: str = ""
    source_hash: str


class SkillManifestLock(BaseModel):
    version: int = 1
    entries: list[SkillLockEntry] = Field(default_factory=list)


class SkillImporter:
    """Materialize manifest entries into canonical package directories."""

    _REQUIRED_COLUMNS = frozenset({"canonicalId", "path"})

    def __init__(
        self,
        manifest_path: str | Path,
        destination_root: str | Path,
        *,
        source_root: str | Path | None = None,
    ) -> None:
        self.manifest_path = Path(manifest_path).expanduser().resolve(strict=False)
        self.destination_root = Path(destination_root).expanduser().resolve(strict=False)
        # The repository's manifest lives at <root>/_bmad/_config/; tests and
        # callers may pass an explicit root for manifests in another layout.
        manifest_dir = self.manifest_path.parent
        inferred_root = (
            manifest_dir.parent.parent
            if manifest_dir.name == "_config" and manifest_dir.parent.name == "_bmad"
            else manifest_dir
        )
        self.source_root = (Path(source_root).expanduser() if source_root is not None else inferred_root).resolve(
            strict=False
        )
        self.lock_path = self.destination_root / "manifest.lock"

    def import_manifest(self) -> list[SkillLockEntry]:
        entries = self._read_manifest()
        lock = self._read_lock()
        existing = {entry.canonical_id: entry for entry in lock.entries}
        planned: list[SkillLockEntry] = []
        seen: set[str] = set()

        for manifest_entry in entries:
            canonical_id = self._canonical_id(manifest_entry)
            if canonical_id in seen:
                raise SkillImportError(canonical_id, "duplicate manifest entry")
            seen.add(canonical_id)

        for manifest_entry in entries:
            canonical_id = self._canonical_id(manifest_entry)
            source_file = self._source_file(manifest_entry)
            source_package = source_file.parent
            try:
                package = SkillPackage(skill_id=canonical_id, root=source_package)
                metadata = package.read_entry().metadata
            except (ValueError, OSError) as exc:
                raise SkillImportError(canonical_id, f"invalid source package '{source_package}': {exc}") from exc
            source_hash = self._hash(source_file)
            destination = self.destination_root / canonical_id
            record = SkillLockEntry(
                canonical_id=canonical_id,
                source_id=manifest_entry.canonical_id,
                source_path=str(source_package),
                destination_path=str(destination),
                version=metadata.version,
                source_hash=source_hash,
            )
            prior = existing.get(canonical_id)
            if prior is not None and prior != record:
                if prior.source_hash != source_hash:
                    raise SkillImportError(canonical_id, "source hash differs from manifest.lock")
                raise SkillImportError(canonical_id, "manifest.lock metadata differs from current source")
            planned.append(record)

        for record, manifest_entry in zip(planned, entries, strict=True):
            destination = Path(record.destination_path)
            if destination.exists():
                if existing.get(record.canonical_id) == record:
                    continue
                raise SkillImportError(record.canonical_id, f"destination already exists: {destination}")
            self._materialize(self._source_file(manifest_entry).parent, destination)

        merged = [existing[key] for key in sorted(existing) if key not in seen]
        merged.extend(sorted(planned, key=lambda entry: entry.canonical_id))
        lock_payload = SkillManifestLock(entries=merged).model_dump_json(indent=2) + "\n"
        atomic_write_text(self.lock_path, lock_payload, lock=True)
        return planned

    def _read_manifest(self) -> list[SkillManifestEntry]:
        if not self.manifest_path.is_file():
            raise SkillImportError("manifest", f"manifest is missing: {self.manifest_path}")
        try:
            with self.manifest_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                columns = set(reader.fieldnames or ())
                missing = self._REQUIRED_COLUMNS - columns
                if missing:
                    raise SkillImportError("manifest", f"missing columns: {', '.join(sorted(missing))}")
                rows = list(reader)
        except SkillImportError:
            raise
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise SkillImportError("manifest", f"cannot read manifest: {exc}") from exc
        result: list[SkillManifestEntry] = []
        for row_number, row in enumerate(rows, start=2):
            try:
                result.append(
                    SkillManifestEntry(
                        canonical_id=(row.get("canonicalId") or "").strip(),
                        name=(row.get("name") or "").strip(),
                        description=(row.get("description") or "").strip(),
                        module=(row.get("module") or "").strip(),
                        path=(row.get("path") or "").strip(),
                    )
                )
            except ValueError as exc:
                raise SkillImportError(f"manifest row {row_number}", str(exc)) from exc
        return result

    def _read_lock(self) -> SkillManifestLock:
        if not self.lock_path.exists():
            return SkillManifestLock()
        try:
            # Phase 4 C4：文本读取经 open_text_under_root 单一安全入口（manifest.csv 例外：
            # csv.DictReader 需 raw newline 语义；_hash 需字节流——两者保留直读）。
            payload = open_text_under_root(self.lock_path.parent, self.lock_path)
            return SkillManifestLock.model_validate_json(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise SkillImportError("manifest.lock", f"lock is corrupt: {exc}") from exc

    def _source_file(self, entry: SkillManifestEntry) -> Path:
        try:
            source = resolve_under_root(entry.path, self.source_root)
        except WorkspacePathError as exc:
            raise SkillImportError(entry.canonical_id, f"source path escapes root: {entry.path} ({exc})") from exc
        if source.name != "SKILL.md":
            raise SkillImportError(entry.canonical_id, f"source entry must be SKILL.md: {entry.path}")
        if not source.is_file():
            raise SkillImportError(entry.canonical_id, f"source file is missing: {entry.path}")
        return source

    @staticmethod
    def _canonical_id(entry: SkillManifestEntry) -> str:
        try:
            return SkillCatalog._canonical_id(entry.canonical_id)
        except ValueError as exc:
            raise SkillImportError(entry.canonical_id, f"invalid canonical id: {exc}") from exc

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise SkillImportError(str(path), f"cannot hash source: {exc}") from exc
        return digest.hexdigest()

    @staticmethod
    def _materialize(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
        try:
            shutil.copytree(source, temporary / destination.name)
            os.replace(temporary / destination.name, destination)
        except (OSError, shutil.Error) as exc:
            raise SkillImportError(destination.name, f"cannot materialize package: {exc}") from exc
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


__all__ = [
    "SkillImportError",
    "SkillImporter",
    "SkillLockEntry",
    "SkillManifestEntry",
    "SkillManifestLock",
]
