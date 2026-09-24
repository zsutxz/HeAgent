"""Persistent registry for existing local project workspaces."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from heagent.persist import atomic_update_text
from heagent.workspace import WorkspacePaths

if TYPE_CHECKING:
    from builtins import list as builtins_list

logger = logging.getLogger(__name__)

MAX_PROJECTS = 32
MAX_PROJECT_NAME_CHARS = 64
MAX_PROJECT_PATH_CHARS = 4096


class ProjectRegistryError(ValueError):
    """Stable project registry failure; the transport maps ``code`` to HTTP."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProjectEntry(BaseModel):
    """Bounded public project metadata. Availability is computed when listing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_CHARS)
    path: str = Field(min_length=1, max_length=MAX_PROJECT_PATH_CHARS)
    available: bool
    last_opened_at: str | None = None
    is_default: bool = False


class _StoredProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_CHARS)
    path: str = Field(min_length=1, max_length=MAX_PROJECT_PATH_CHARS)
    last_opened_at: str | None = None


def normalize_project_path(path: str | Path) -> str:
    """Expand, resolve, and remove redundant trailing separators from a path."""
    raw = str(path)
    if not raw or len(raw) > MAX_PROJECT_PATH_CHARS:
        raise ProjectRegistryError("invalid_project_path", "project path is invalid")
    try:
        resolved = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectRegistryError("invalid_project_path", "project path is invalid") from exc
    normalized = os.path.normpath(str(resolved))
    if len(normalized) > MAX_PROJECT_PATH_CHARS:
        raise ProjectRegistryError("invalid_project_path", "project path is too long")
    return normalized


def project_id_for(path: str | Path) -> str:
    """Create a stable ID from the platform-normalized canonical path."""
    normalized = normalize_project_path(path)
    return "p" + hashlib.sha256(os.path.normcase(normalized).encode("utf-8")).hexdigest()[:8]


class ProjectRegistry:
    """Atomic, cross-process registry. Project directories are never mutated."""

    def __init__(self, path: str | Path, *, default_path: str | Path) -> None:
        self._path = Path(path)
        self._default_path = normalize_project_path(default_path)

    def load(self) -> builtins_list[_StoredProject]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError) as exc:
            logger.warning("Unable to read project registry %s: %s", self._path, exc)
            return []
        return self._decode(raw)

    def list(self) -> builtins_list[ProjectEntry]:
        entries = [
            ProjectEntry(
                id="default",
                name=Path(self._default_path).name or self._default_path,
                path=self._default_path,
                available=Path(self._default_path).is_dir(),
                is_default=True,
            )
        ]
        entries.extend(
            ProjectEntry(
                id=item.id,
                name=item.name,
                path=item.path,
                available=Path(item.path).is_dir(),
                last_opened_at=item.last_opened_at,
            )
            for item in self.load()
        )
        registered = entries[1:]
        registered.sort(key=lambda item: item.last_opened_at or "", reverse=True)
        return [*registered, entries[0]]

    def register(self, path: str | Path, name: str | None = None) -> ProjectEntry:
        normalized = normalize_project_path(path)
        target = Path(normalized)
        if not target.is_dir():
            raise ProjectRegistryError("invalid_project_path", "project path must be an existing directory")
        display_name = name.strip() if name is not None else target.name
        if not display_name or len(display_name) > MAX_PROJECT_NAME_CHARS:
            raise ProjectRegistryError("invalid_request", "project name is invalid")
        entry_id = project_id_for(normalized)
        result: _StoredProject | None = None

        def update(raw: str) -> tuple[str, None]:
            nonlocal result
            entries = self._decode(raw)
            identity = os.path.normcase(normalized)
            for entry in entries:
                if os.path.normcase(entry.path) == identity:
                    result = entry
                    return self._encode(entries), None
            if len(entries) >= MAX_PROJECTS - 1:
                raise ProjectRegistryError("project_limit_reached", "project registry is full")
            if not target.is_dir():
                raise ProjectRegistryError("invalid_project_path", "project path must be an existing directory")
            result = _StoredProject(id=entry_id, name=display_name, path=normalized)
            entries.append(result)
            return self._encode(entries), None

        atomic_update_text(self._path, update)
        if result is None:
            raise RuntimeError("project registration completed without a result")
        return self._public(result)

    def rename(self, project_id: str, name: str) -> ProjectEntry:
        display_name = name.strip()
        if not display_name or len(display_name) > MAX_PROJECT_NAME_CHARS:
            raise ProjectRegistryError("invalid_request", "project name is invalid")
        result: _StoredProject | None = None

        def update(raw: str) -> tuple[str, None]:
            nonlocal result
            entries = self._decode(raw)
            for index, entry in enumerate(entries):
                if entry.id == project_id:
                    result = entry.model_copy(update={"name": display_name})
                    entries[index] = result
                    return self._encode(entries), None
            raise ProjectRegistryError("unknown_project", "no such project")

        atomic_update_text(self._path, update)
        if result is None:
            raise RuntimeError("project rename completed without a result")
        return self._public(result)

    def remove(self, project_id: str) -> ProjectEntry:
        if project_id == "default":
            raise ProjectRegistryError("project_not_removable", "default project cannot be removed")
        result: _StoredProject | None = None

        def update(raw: str) -> tuple[str, None]:
            nonlocal result
            entries = self._decode(raw)
            result = next((entry for entry in entries if entry.id == project_id), None)
            if result is None:
                raise ProjectRegistryError("unknown_project", "no such project")
            return self._encode([entry for entry in entries if entry.id != project_id]), None

        atomic_update_text(self._path, update)
        if result is None:
            raise RuntimeError("project removal completed without a result")
        return self._public(result)

    def touch(self, project_id: str) -> ProjectEntry:
        if project_id == "default":
            return next(item for item in self.list() if item.is_default)
        timestamp = datetime.now(UTC).isoformat()
        result: _StoredProject | None = None

        def update(raw: str) -> tuple[str, None]:
            nonlocal result
            entries = self._decode(raw)
            for index, entry in enumerate(entries):
                if entry.id == project_id:
                    result = entry.model_copy(update={"last_opened_at": timestamp})
                    entries[index] = result
                    return self._encode(entries), None
            raise ProjectRegistryError("unknown_project", "no such project")

        atomic_update_text(self._path, update)
        if result is None:
            raise RuntimeError("project touch completed without a result")
        return self._public(result)

    @classmethod
    def _decode(cls, raw: str) -> builtins_list[_StoredProject]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError("registry root must be an array")
            entries = [_StoredProject.model_validate(item) for item in data]
            if len(entries) > MAX_PROJECTS or len({item.id for item in entries}) != len(entries):
                raise ValueError("registry entries are invalid")
            return entries
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            logger.warning("Invalid project registry; using an empty registry (%s)", exc)
            return []

    @staticmethod
    def _encode(entries: builtins_list[_StoredProject]) -> str:
        return json.dumps([entry.model_dump(mode="json") for entry in entries], ensure_ascii=False, indent=2) + "\n"

    @staticmethod
    def _public(entry: _StoredProject) -> ProjectEntry:
        return ProjectEntry(
            **entry.model_dump(),
            available=Path(entry.path).is_dir(),
            is_default=False,
        )


def default_project_registry(workspace: str | Path, configured_path: str | Path | None = None) -> ProjectRegistry:
    paths = WorkspacePaths.from_root(workspace)
    return ProjectRegistry(configured_path or paths.projects_file, default_path=paths.root)


__all__ = [
    "MAX_PROJECT_NAME_CHARS",
    "MAX_PROJECT_PATH_CHARS",
    "MAX_PROJECTS",
    "ProjectEntry",
    "ProjectRegistry",
    "ProjectRegistryError",
    "default_project_registry",
    "normalize_project_path",
    "project_id_for",
]
