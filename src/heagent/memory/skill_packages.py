"""Validated, on-demand access to declarative skill packages."""

from __future__ import annotations

import errno
import os
import re
import stat
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Iterable, cast  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from heagent.frontmatter import parse_inline_pairs, split_frontmatter
from heagent.tools.path_safety import WorkspacePathError, resolve_under_root


class SkillPackageError(ValueError):
    """Base error for an invalid or unusable skill package resource."""

    def __init__(self, skill_id: str, resource: str, reason: str) -> None:
        self.skill_id = skill_id
        self.resource = resource
        self.reason = reason
        super().__init__(f"Skill package '{skill_id}' resource '{resource}': {reason}")


class SkillPackageEntryError(SkillPackageError):
    """Raised when a package entry point is missing or unreadable."""


class SkillPackageResourceError(SkillPackageError):
    """Raised when a package resource is invalid, missing, or outside its root."""


class SkillCatalogError(ValueError):
    """Base error raised while indexing skill packages."""


class SkillResolutionError(SkillCatalogError):
    """Raised when an explicit skill id cannot be resolved unambiguously."""

    def __init__(self, skill_id: str, reason: str, candidates: Iterable[SkillCatalogEntry] = ()) -> None:
        self.skill_id = skill_id
        self.reason = reason
        self.candidates = tuple(candidates)
        details = "; ".join(f"{c.canonical_id} ({c.package_root})" for c in self.candidates)
        suffix = f"; candidates: {details}" if details else ""
        super().__init__(f"Skill '{skill_id}' cannot be resolved: {reason}{suffix}")


class SkillPackageMetadata(BaseModel):
    """Stable metadata associated with a package entry point."""

    model_config = ConfigDict(extra="allow")

    skill_id: str
    package_root: str
    entrypoint: str = "SKILL.md"
    name: str = ""
    description: str = ""
    version: str = ""
    tags: list[str] = Field(default_factory=list)
    canonical_id: str = ""
    source_id: str = ""
    aliases: list[str] = Field(default_factory=list)
    available: bool = True


class SkillPackageEntry(BaseModel):
    """Entry point text and its parsed metadata."""

    text: str
    metadata: SkillPackageMetadata


class SkillPackage(BaseModel):
    """A package boundary with lazy, root-fenced resource reads."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    skill_id: str
    root: Path
    entrypoint: str = "SKILL.md"
    _metadata: SkillPackageMetadata | None = PrivateAttr(default=None)

    def model_post_init(self, __context: object) -> None:
        root = self.root.expanduser().resolve(strict=False)
        if not root.is_dir():
            raise SkillPackageError(self.skill_id, str(root), "package root is missing or not a directory")
        if self._is_absolute(self.entrypoint) or self._has_parent(self.entrypoint):
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, "entrypoint path is invalid")
        object.__setattr__(self, "root", root)

    @property
    def metadata(self) -> SkillPackageMetadata:
        """Load and parse entry metadata on first access."""
        if self._metadata is None:
            object.__setattr__(self, "_metadata", self.read_entry().metadata)
        return cast("SkillPackageMetadata", self._metadata)

    def read_entry(self) -> SkillPackageEntry:
        """Read the package's SKILL.md entry point and parse basic frontmatter."""
        try:
            text = self._read_text(self.entrypoint, entry=True)
        except SkillPackageResourceError as exc:
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, exc.reason) from exc
        metadata = self._parse_metadata(text)
        object.__setattr__(self, "_metadata", metadata)
        return SkillPackageEntry(text=text, metadata=metadata)

    def read_resource(self, resource: str) -> str:
        """Read exactly one root-relative resource, without scanning its package."""
        return self._read_text(resource)

    def _read_text(self, resource: str, *, entry: bool = False) -> str:
        """Open and decode one resolved resource while retaining its descriptor lifetime."""
        # Non-blocking open lets fstat reject FIFOs/devices without waiting for
        # another process to provide a writer. Regular files ignore this flag.
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is not None:
            flags |= nofollow
        binary = getattr(os, "O_BINARY", 0)
        flags |= binary
        try:
            path = self._resolve(resource, entry=entry)
            try:
                descriptor = os.open(path, flags)
            except OSError as exc:
                # Some platforms expose O_NOFOLLOW but their filesystem does not
                # implement it. Preserve the compatibility read in that case.
                unsupported = {
                    errno.EINVAL,
                    getattr(errno, "ENOTSUP", errno.EINVAL),
                    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
                }
                if nofollow is not None and exc.errno in unsupported:
                    descriptor = os.open(path, flags & ~nofollow)
                else:
                    raise
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode):
                    raise OSError(errno.EISDIR, "resource is not a regular file")
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = -1
                    text = stream.read().decode("utf-8")
                    # Path.read_text() historically performed universal newline
                    # translation; retain that public behavior after decoding.
                    return text.replace("\r\n", "\n").replace("\r", "\n")
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        except FileNotFoundError as exc:
            reason = "entrypoint is missing" if entry else "resource is missing"
            raise SkillPackageResourceError(self.skill_id, resource, reason) from exc
        except UnicodeDecodeError as exc:
            label = "entrypoint" if entry else "resource"
            raise SkillPackageResourceError(self.skill_id, resource, f"cannot read {label}: {exc}") from exc
        except OSError as exc:
            label = "entrypoint" if entry else "resource"
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                reason = f"cannot read {label}: final path component is a symlink"
            elif exc.errno in {errno.EISDIR, errno.ENXIO}:
                reason = f"cannot read {label}: target is not a regular file"
            else:
                reason = f"cannot read {label}: {exc}"
            raise SkillPackageResourceError(self.skill_id, resource, reason) from exc

    def read_step(self, resource: str) -> str:
        return self.read_resource(resource)

    # 声明式工作流装配（read_workflow 及其解析助手、WorkflowResource 模型、SkillWorkflowError）
    # 已于 2026-09-20 归位到 /goal 领域层：goal/workflow_loader.py（解析）与
    # engine/workflow_resource.py（运行时模型）。本模块只保留技能包的通用资源索引与安全读取。

    def read_reference(self, resource: str) -> str:
        return self._read_in("references", resource)

    def read_template(self, resource: str) -> str:
        return self._read_in("templates", resource)

    def read_asset(self, resource: str) -> str:
        return self._read_in("assets", resource)

    def read_script(self, resource: str) -> str:
        return self._read_in("scripts", resource)

    def _read_in(self, directory: str, resource: str) -> str:
        if self._is_absolute(resource) or self._has_parent(resource):
            raise SkillPackageResourceError(
                self.skill_id,
                resource,
                "resource path is absolute or traverses parent directory",
            )
        parts = PurePath(resource).parts
        relative = resource if parts and parts[0] == directory else f"{directory}/{resource}"
        return self.read_resource(relative)

    def _resolve(self, resource: str, *, entry: bool = False) -> Path:
        if self._is_absolute(resource) or self._has_parent(resource):
            reason = (
                "entrypoint path is invalid" if entry else "resource path is absolute or traverses parent directory"
            )
            raise SkillPackageResourceError(self.skill_id, resource, reason)
        try:
            return resolve_under_root(resource, self.root)
        except WorkspacePathError as exc:
            raise SkillPackageResourceError(
                self.skill_id, resource, f"resource path escapes package root: {exc}"
            ) from exc

    @staticmethod
    def _is_absolute(resource: str) -> bool:
        return any(parser(resource).is_absolute() for parser in (PurePath, PurePosixPath, PureWindowsPath))

    @staticmethod
    def _has_parent(resource: str) -> bool:
        return any(".." in parser(resource).parts for parser in (PurePath, PurePosixPath, PureWindowsPath))

    def _parse_metadata(self, text: str) -> SkillPackageMetadata:
        values: dict[str, str] = {}
        split = split_frontmatter(text)
        if split is not None:
            raw_block, _end, _body = split
            # 宽档 keys=() 模式（任意含冒号行、不跳注释），值还原历史语义：strip + 成对引号剥壳。
            values = {key: value.strip().strip("\"'") for key, value in parse_inline_pairs(raw_block).items()}
        tags = [tag.strip() for tag in values.get("tags", "").strip("[]").split(",") if tag.strip()]
        aliases = [tag.strip().strip("\"'") for tag in values.get("aliases", "").strip("[]").split(",") if tag.strip()]
        canonical_id = values.get("canonical_id", values.get("canonicalId", ""))
        source_id = values.get("source_id", values.get("sourceId", ""))
        available_value = values.get("available", "true").lower()
        if available_value not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError(f"invalid available flag '{available_value}'")
        available = available_value not in {"false", "0", "no"}
        return SkillPackageMetadata(
            skill_id=self.skill_id,
            package_root=str(self.root),
            entrypoint=self.entrypoint,
            name=values.get("name", self.skill_id),
            description=values.get("description", ""),
            version=values.get("version", ""),
            tags=tags,
            canonical_id=canonical_id,
            source_id=source_id,
            aliases=aliases,
            available=available,
        )


class SkillCatalogEntry(BaseModel):
    """An indexed package and its stable identifiers."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    canonical_id: str
    source_id: str
    aliases: list[str] = Field(default_factory=list)
    version: str = ""
    available: bool = True
    package_root: str
    package: SkillPackage | None = None
    error: str | None = None


class SkillCatalog:
    """Discover packages from explicitly supplied source directories."""

    def __init__(self, source_dirs: Iterable[str | Path] = ()) -> None:
        self.source_dirs = tuple(Path(path).expanduser() for path in source_dirs)
        self._entries: tuple[SkillCatalogEntry, ...] = ()

    @property
    def entries(self) -> list[SkillCatalogEntry]:
        return list(self._entries)

    def scan(self, source_dirs: Iterable[str | Path] | None = None) -> list[SkillCatalogEntry]:
        """Scan immediate child package directories in deterministic order."""
        if source_dirs is not None:
            self.source_dirs = tuple(Path(path).expanduser() for path in source_dirs)
        found: list[SkillCatalogEntry] = []
        for source_dir in self.source_dirs:
            root = source_dir.resolve(strict=False)
            if not root.is_dir() or root.name == ".archive":
                continue
            candidates = (
                [root]
                if (root / "SKILL.md").exists()
                else sorted(
                    (child for child in root.iterdir() if child.is_dir() and child.name != ".archive"),
                    key=lambda p: p.name,
                )
            )
            for package_root in candidates:
                found.append(self._index_package(package_root))
        # Identical canonical packages from the same root are one package, not a conflict.
        unique: dict[tuple[str, str, tuple[str, ...]], SkillCatalogEntry] = {}
        for entry in found:
            key = (entry.canonical_id, entry.package_root, tuple(entry.aliases))
            unique.setdefault(key, entry)
        self._entries = tuple(sorted(unique.values(), key=lambda e: (e.canonical_id, e.package_root)))
        return self.entries

    def _index_package(self, package_root: Path) -> SkillCatalogEntry:
        source_id = package_root.name
        package_root_text = str(package_root.resolve(strict=False))
        try:
            provisional = SkillPackage(skill_id=source_id, root=package_root)
            metadata = provisional.read_entry().metadata
            declared_id = metadata.canonical_id.strip() or metadata.name.strip() or source_id
            canonical_id = self._canonical_id(declared_id)
            source_id = metadata.source_id.strip() or metadata.name.strip() or source_id
            aliases = list(metadata.aliases)
            if source_id != canonical_id:
                aliases.append(source_id)
            if canonical_id.startswith("he-"):
                aliases.append("bmad-" + canonical_id[3:])
            elif canonical_id.startswith("bmad-"):
                aliases.append("he-" + canonical_id[5:])
            aliases = sorted(set(alias for alias in aliases if alias != canonical_id))
            package = SkillPackage(skill_id=canonical_id, root=package_root)
            package.read_entry()
            return SkillCatalogEntry(
                canonical_id=canonical_id,
                source_id=source_id,
                aliases=aliases,
                version=metadata.version,
                package_root=package_root_text,
                package=package if metadata.available else None,
                available=metadata.available,
                error=None if metadata.available else "package marked unavailable by metadata",
            )
        except (SkillPackageError, ValueError, OSError) as exc:
            try:
                canonical_id = self._canonical_id(source_id)
            except ValueError:
                canonical_id = "he-" + re.sub(r"[^a-z0-9_-]+", "-", source_id.lower()).strip("-")
            reason = f"invalid metadata: {exc}" if isinstance(exc, ValueError) else str(exc)
            return SkillCatalogEntry(
                canonical_id=canonical_id,
                source_id=source_id,
                aliases=(
                    ["bmad-" + canonical_id[3:]]
                    if canonical_id.startswith("he-")
                    else ["he-" + canonical_id[5:]]
                    if canonical_id.startswith("bmad-")
                    else []
                ),
                available=False,
                package_root=package_root_text,
                error=reason,
            )

    @staticmethod
    def _canonical_id(skill_id: str) -> str:
        value = skill_id.strip()
        if not re.fullmatch(r"(?:he|bmad)-[a-z0-9][a-z0-9_-]*", value):
            raise ValueError(f"invalid skill id '{skill_id}'")
        return value


class SkillResolver:
    """Resolve canonical ids and compatibility aliases deterministically."""

    def __init__(self, catalog: SkillCatalog | Iterable[SkillCatalogEntry]) -> None:
        self.catalog = catalog

    def resolve(self, skill_id: str) -> SkillPackage:
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise SkillResolutionError(str(skill_id), "skill id is empty")
        entries = self.catalog.entries if isinstance(self.catalog, SkillCatalog) else list(self.catalog)
        requested = skill_id.strip()
        try:
            canonical_requested = SkillCatalog._canonical_id(requested)
        except ValueError:
            canonical_requested = ""
        # Canonical ids are explicit and always outrank alias matches.
        canonical = [e for e in entries if canonical_requested and e.canonical_id == canonical_requested]
        matches = canonical or [e for e in entries if requested == e.source_id or requested in e.aliases]
        if not matches:
            reason = "invalid skill id" if not canonical_requested else "skill id was not found"
            raise SkillResolutionError(requested, reason)
        if len(matches) != 1:
            raise SkillResolutionError(requested, "canonical or alias id is ambiguous", matches)
        entry = matches[0]
        if not entry.available or entry.package is None:
            raise SkillResolutionError(requested, entry.error or "package is unavailable", matches)
        return entry.package
