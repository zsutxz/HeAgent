"""Workspace-bound path validation helpers for file-like tools."""

from __future__ import annotations

from pathlib import Path


class WorkspacePathError(ValueError):
    """Raised when a tool path escapes the current workspace root."""


def workspace_root() -> Path:
    """Return the resolved current working directory as the workspace root."""
    return Path.cwd().resolve()


def resolve_workspace_path(path: str) -> Path:
    """Resolve a path and ensure it stays inside the current workspace."""
    root = workspace_root()
    raw = Path(path)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise WorkspacePathError(
            f"Path escapes current workspace: {path} (workspace: {root})"
        )
    return resolved
