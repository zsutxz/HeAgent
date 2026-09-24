"""File read / write / edit tools scoped to the current workspace.

编辑护栏（实现见 :mod:`heagent.tools.edits`）：

- ``file_read`` 与 ``file_edit`` 共用**同一份文本形态**（去 BOM、行尾归一为 ``\n``），
  保证「读到的片段可直接拿去匹配」，不会因隐形 BOM 或 CRLF 而匹配失败；
- ``file_write`` / ``file_edit`` 落盘走 ``write_bytes``（不触发平台行尾翻译），写前留
  快照、写后回 ``+N -M`` diff 回执——旧版 ``file_write`` 只回 ``wrote N chars``，
  模型与用户都无法自证「实际改了什么」。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from heagent.tools.decorator import tool
from heagent.tools.edits import (
    MAX_DIFF_SOURCE_BYTES,
    read_text_file,
    render_diff,
    render_new_file,
    snapshot_before_write,
    write_text_file,
)
from heagent.tools.path_safety import (
    WorkspacePathError,
    check_read_denied,
    check_write_denied,
    resolve_workspace_path,
    workspace_root,
)

if TYPE_CHECKING:
    from pathlib import Path


def _writable(path: str) -> Path | str:
    """解析可写目标并做写 deny 检查；失败时返回错误消息（字符串），成功返回路径。"""
    try:
        resolved = resolve_workspace_path(path)
    except WorkspacePathError as exc:
        return f"Error: {exc}"
    reason = check_write_denied(path)
    if reason is not None:
        return f"Error: {reason}"
    return resolved


def _read_for_diff(path: Path) -> str | None:
    """读旧内容供 diff 回执使用；不存在 / 超限 / 不可解码 → ``None``（回执退化为计数）。"""
    try:
        if not path.is_file() or path.stat().st_size > MAX_DIFF_SOURCE_BYTES:
            return None
        return read_text_file(path).text
    except (OSError, UnicodeDecodeError):
        return None


def _receipt(header: str, body: str, snapshot: str | None) -> str:
    """拼装统一回执：``header`` + diff ``body`` +（可选）快照行。"""
    lines = [header]
    if body:
        lines.append(body)
    if snapshot:
        lines.append(f"snapshot: {snapshot}")
    return "\n".join(lines)


@tool(read_only=True)
async def file_read(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Read the contents of a file, optionally with line range.

    When ``offset`` and/or ``limit`` are provided, the file is read line-by-line
    (1-indexed).  The returned string includes the selected lines joined with
    newlines, with a tail note if lines were omitted.

    The returned text is the same form ``file_edit`` matches against (BOM stripped,
    line endings normalised to ``\\n``), so a snippet copied from here can be passed
    to ``file_edit`` verbatim.

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
        denied = check_read_denied(path, workspace_root())
        if denied is not None:
            return f"Error: {denied}"
        if not resolved.exists():
            return f"Error: file not found: {path}"
        if resolved.is_dir():
            return f"Error: path is a directory: {path}"

        # 阻塞读经线程卸载（项目全异步纪律，同 memory/skills 工具范式）；
        # exists()/is_dir() 等控制流用的廉价元数据调用有意不包。
        text = (await asyncio.to_thread(read_text_file, resolved)).text

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
        end = start + limit if limit is not None and limit >= 0 else total
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
    """Write content to a file (full overwrite), creating parent directories as needed.

    Returns a ``+N -M`` diff summary of what changed, and leaves a pre-write snapshot
    for existing files.  For a targeted change prefer ``file_edit``: it rewrites only
    the matched snippet, so the rest of the file cannot be lost by truncation.

    Parameters
    ----------
    path:
        Path to the file (relative to workspace or absolute).
    content:
        Full new content of the file (written verbatim; line endings are not translated).
    """
    resolved = _writable(path)
    if isinstance(resolved, str):
        return resolved
    try:
        await asyncio.to_thread(resolved.parent.mkdir, parents=True, exist_ok=True)
    except OSError as exc:
        return f"Error writing file: {exc}"

    existed = await asyncio.to_thread(resolved.is_file)
    previous = await asyncio.to_thread(_read_for_diff, resolved)
    snapshot = await asyncio.to_thread(snapshot_before_write, resolved, op="write")
    try:
        await asyncio.to_thread(resolved.write_bytes, content.encode("utf-8"))
    except OSError as exc:
        return f"Error writing file: {exc}"

    if not existed:
        body = render_new_file(content)
    elif previous is None:
        body = f"{len(content)} chars; diff unavailable (previous content too large or not UTF-8)"
    else:
        body = render_diff(previous, content)
    return _receipt(f"OK: wrote {path} ({len(content)} chars)", body, snapshot)


@tool
async def file_edit(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """Replace an exact snippet inside a file (surgical edit; everything else is untouched).

    ``old_string`` must match the file content exactly — indentation, blank lines and
    surrounding characters included.  Copy it verbatim from ``file_read``.  It must match
    **exactly once** unless ``replace_all`` is true.  A missing or ambiguous match returns
    an error and changes nothing on disk.  Returns a ``+N -M`` diff summary and leaves a
    pre-edit snapshot for rollback.

    Parameters
    ----------
    path:
        Path to the file (relative to workspace or absolute).
    old_string:
        Exact existing snippet to replace (must be unique unless ``replace_all``).
    new_string:
        Replacement text (may be empty to delete the snippet).
    replace_all:
        Replace every occurrence instead of requiring a unique match.
    """
    if not old_string:
        return "Error: old_string must not be empty (use file_write to create a new file)."
    if old_string == new_string:
        return "Error: file_edit is a no-op — old_string and new_string are identical."

    resolved = _writable(path)
    if isinstance(resolved, str):
        return resolved
    if resolved.is_dir():
        return f"Error: path is a directory: {path}"
    if not resolved.is_file():
        return f"Error: file not found: {path}"
    try:
        current = await asyncio.to_thread(read_text_file, resolved)
    except UnicodeDecodeError:
        return f"Error: {path} is not valid UTF-8 text; file_edit only handles text files."
    except OSError as exc:
        return f"Error reading file: {exc}"

    needle = old_string.replace("\r\n", "\n")
    matches = current.text.count(needle)
    if matches == 0:
        return (
            f"Error: old_string not found in {path}. Read the file with file_read and copy the "
            "snippet verbatim — indentation and blank lines must match exactly."
        )
    if matches > 1 and not replace_all:
        return (
            f"Error: old_string matches {matches} locations in {path}. Include more surrounding "
            "context to make it unique, or pass replace_all=true to replace every occurrence."
        )

    replacement = new_string.replace("\r\n", "\n")
    updated = current.text.replace(needle, replacement, -1 if replace_all else 1)
    snapshot = await asyncio.to_thread(snapshot_before_write, resolved, op="edit")
    try:
        await asyncio.to_thread(write_text_file, resolved, updated, newline=current.newline, has_bom=current.has_bom)
    except OSError as exc:
        return f"Error writing file: {exc}"

    header = f"OK: edited {path} ({matches} replacements)" if replace_all else f"OK: edited {path}"
    return _receipt(header, render_diff(current.text, updated), snapshot)
