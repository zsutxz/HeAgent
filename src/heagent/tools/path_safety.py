"""Workspace-bound path validation helpers for file-like tools."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

_workspace_override: Path | None = None
_workspace_runtime = RuntimeSlot[Path]("heagent_workspace_root")


class WorkspacePathError(ValueError):
    """Raised when a tool path escapes the current workspace root."""


def set_workspace_root(path: Path | None) -> None:
    """Override the workspace root (primarily for testing)."""
    global _workspace_override
    _workspace_override = path.resolve() if path is not None else None


def reset_workspace_root() -> None:
    """Clear the workspace override, reverting to cwd."""
    global _workspace_override
    _workspace_override = None


def workspace_root() -> Path:
    """Return the resolved workspace root (override or cwd)."""
    runtime_root = _workspace_runtime.get()
    if runtime_root is not None:
        return runtime_root
    if _workspace_override is not None:
        return _workspace_override
    return Path.cwd().resolve()


def resolve_under_root(path: str, root: Path) -> Path:
    """Resolve ``path`` under ``root`` and fence it; raise ``WorkspacePathError`` if it escapes.

    Single fence algorithm shared by the policy pre-check (``engine.policy._validate_paths``)
    and the handler guard (:func:`resolve_workspace_path`), eliminating two divergent copies.
    Relative paths resolve against ``root``; ``strict=False`` permits not-yet-existing paths
    (e.g. a file about to be written).
    """
    raw = Path(path)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise WorkspacePathError(f"Path escapes current workspace: {path} (workspace: {root})")
    return resolved


def resolve_workspace_path(path: str) -> Path:
    """Resolve a path and ensure it stays inside the current workspace."""
    return resolve_under_root(path, workspace_root())


def configure_workspace_root(path: Path | None) -> None:
    """Set the process-wide fallback workspace root for tool execution."""
    _workspace_runtime.configure(path.resolve() if path is not None else None)


@contextmanager
def bind_workspace_root(path: Path | None) -> Iterator[None]:
    """Bind the workspace root for the current runtime context."""
    resolved = path.resolve() if path is not None else None
    with _workspace_runtime.bind(resolved):
        yield
