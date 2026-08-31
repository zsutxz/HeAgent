"""Validated, on-demand access to declarative skill packages."""

from __future__ import annotations

import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

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
            path = self._resolve(self.entrypoint, entry=True)
        except SkillPackageResourceError as exc:
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, exc.reason) from exc
        if not path.is_file():
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, "entrypoint is missing")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, f"cannot read entrypoint: {exc}") from exc
        metadata = self._parse_metadata(text)
        object.__setattr__(self, "_metadata", metadata)
        return SkillPackageEntry(text=text, metadata=metadata)

    def read_resource(self, resource: str) -> str:
        """Read exactly one root-relative resource, without scanning its package."""
        path = self._resolve(resource)
        if not path.is_file():
            raise SkillPackageResourceError(self.skill_id, resource, "resource is missing")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SkillPackageResourceError(self.skill_id, resource, f"cannot read resource: {exc}") from exc

    def read_step(self, resource: str) -> str:
        return self.read_resource(resource)

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
            reason = "entrypoint path is invalid" if entry else "resource path is absolute or traverses parent directory"
            raise SkillPackageResourceError(self.skill_id, resource, reason)
        try:
            return resolve_under_root(resource, self.root)
        except WorkspacePathError as exc:
            raise SkillPackageResourceError(self.skill_id, resource, f"resource path escapes package root: {exc}") from exc

    @staticmethod
    def _is_absolute(resource: str) -> bool:
        return any(parser(resource).is_absolute() for parser in (PurePath, PurePosixPath, PureWindowsPath))

    @staticmethod
    def _has_parent(resource: str) -> bool:
        return any(".." in parser(resource).parts for parser in (PurePath, PurePosixPath, PureWindowsPath))

    def _parse_metadata(self, text: str) -> SkillPackageMetadata:
        values: dict[str, str] = {}
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if match:
            for line in match.group(1).splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    values[key.strip()] = value.strip().strip("\"'")
        tags = [tag.strip() for tag in values.get("tags", "").strip("[]").split(",") if tag.strip()]
        return SkillPackageMetadata(
            skill_id=self.skill_id,
            package_root=str(self.root),
            entrypoint=self.entrypoint,
            name=values.get("name", self.skill_id),
            description=values.get("description", ""),
            version=values.get("version", ""),
            tags=tags,
        )


# Short aliases keep callers independent of the concrete diagnostic subclass names.
SkillResourceError = SkillPackageResourceError
