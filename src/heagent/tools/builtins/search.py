"""File search tools scoped to the current workspace."""

from __future__ import annotations

import re

from heagent.tools.decorator import tool
from heagent.tools.path_safety import WorkspacePathError, resolve_workspace_path


@tool
async def file_search(
    pattern: str,
    directory: str = ".",
    max_results: int = 20,
) -> str:
    """Search for files by name pattern (glob) under a directory."""
    try:
        root = resolve_workspace_path(directory)
        if not root.exists():
            return f"Error: directory not found: {directory}"
        if not root.is_dir():
            return f"Error: path is not a directory: {directory}"

        matches: list[str] = []
        for path in root.rglob(pattern):
            try:
                resolve_workspace_path(str(path))
            except WorkspacePathError:
                continue
            matches.append(str(path))
            if len(matches) >= max_results:
                break
        if not matches:
            return f"No files matching '{pattern}' found in {directory}"
        return "\n".join(matches)
    except WorkspacePathError as e:
        return f"Error: {e}"


@tool
async def content_search(
    query: str,
    directory: str = ".",
    file_pattern: str = "*.txt",
    max_results: int = 20,
) -> str:
    """Search file contents for a regex pattern."""
    try:
        root = resolve_workspace_path(directory)
        if not root.exists():
            return f"Error: directory not found: {directory}"
        if not root.is_dir():
            return f"Error: path is not a directory: {directory}"
    except WorkspacePathError as e:
        return f"Error: {e}"

    try:
        regex = re.compile(query, re.IGNORECASE)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    results: list[str] = []
    for path in root.rglob(file_pattern):
        try:
            resolved = resolve_workspace_path(str(path))
        except WorkspacePathError:
            continue
        if not resolved.is_file():
            continue
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                results.append(f"{resolved}:{i}: {line.strip()}")
                if len(results) >= max_results:
                    break
        if len(results) >= max_results:
            break
    if not results:
        return f"No matches for '{query}' in {file_pattern} files under {directory}"
    return "\n".join(results)
