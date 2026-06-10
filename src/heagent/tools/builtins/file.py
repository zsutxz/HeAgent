"""File read/write tools scoped to the current workspace."""

from __future__ import annotations

from heagent.tools.decorator import tool
from heagent.tools.path_safety import WorkspacePathError, resolve_workspace_path


@tool
async def file_read(path: str) -> str:
    """Read the contents of a file."""
    try:
        resolved = resolve_workspace_path(path)
        if not resolved.exists():
            return f"Error: file not found: {path}"
        if resolved.is_dir():
            return f"Error: path is a directory: {path}"
        return resolved.read_text(encoding="utf-8")
    except WorkspacePathError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


@tool
async def file_write(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed."""
    try:
        resolved = resolve_workspace_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"OK: wrote {len(content)} chars to {path}"
    except WorkspacePathError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error writing file: {e}"
