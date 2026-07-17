"""File read/write tools scoped to the current workspace."""

from __future__ import annotations

from heagent.tools.decorator import tool
from heagent.tools.path_safety import WorkspacePathError, resolve_workspace_path


@tool
async def file_read(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Read the contents of a file, optionally with line range.

    When ``offset`` and/or ``limit`` are provided, the file is read line-by-line
    (1-indexed).  The returned string includes the selected lines joined with
    newlines, with a tail note if lines were omitted.

    Parameters
    ----------
    path:
        Path to the file (relative to workspace or absolute).
    offset:
        1-based starting line number.  ``None`` (default) means start of file.
    limit:
        Maximum number of lines to return.  ``None`` (default) means all lines
        from ``offset`` to end of file.
    """
    try:
        resolved = resolve_workspace_path(path)
        if not resolved.exists():
            return f"Error: file not found: {path}"
        if resolved.is_dir():
            return f"Error: path is a directory: {path}"

        text = resolved.read_text(encoding="utf-8")

        if offset is None and limit is None:
            return text

        lines = text.splitlines()
        total = len(lines)

        # offset: 1-based, clamp to [1, total]
        start = (offset - 1) if offset is not None else 0
        if start < 0:
            start = 0
        if start >= total:
            return f"Error: offset {offset} exceeds file length ({total} lines)"

        # limit: number of lines
        if limit is not None and limit >= 0:
            end = start + limit
        else:
            end = total
        if end > total:
            end = total

        selected = lines[start:end]
        result = "\n".join(selected)

        # Append tail note when truncation occurred
        if start > 0 or end < total:
            notes: list[str] = []
            if start > 0:
                notes.append(f"{start} lines above")
            if end < total:
                notes.append(f"{total - end} lines below")
            result += f"\n\n(truncated — {', '.join(notes)}, use offset/limit to navigate)"

        return result
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
