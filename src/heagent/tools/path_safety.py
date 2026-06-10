"""Workspace-bound path validation helpers for file-like tools."""

from __future__ import annotations

from pathlib import Path

_workspace_override: Path | None = None


class WorkspacePathError(ValueError):
    """Raised when a tool path escapes the current workspace root."""


def set_workspace_root(path: Path | None) -> None:
    """Override the workspace root (primarily for testing)."""
    global _workspace_override
    _workspace_override = path


def reset_workspace_root() -> None:
    """Clear the workspace override, reverting to cwd."""
    global _workspace_override
    _workspace_override = None


def workspace_root() -> Path:
    """Return the resolved workspace root (override or cwd)."""
    if _workspace_override is not None:
        return _workspace_override
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
