"""File search tools scoped to the current workspace."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from heagent.tools.decorator import tool
from heagent.tools.path_safety import WorkspacePathError, check_read_denied, resolve_workspace_path

if TYPE_CHECKING:
    from pathlib import Path

# P1-18 修复：content_search 文件大小上限（10 MB），防大文件 OOM。
# 与 web_fetch 2 MB 上限同思路：对工作区内文件做防御性限制。
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _resolve_dir(directory: str) -> Path | str:
    """解析并校验工作区目录，返回 Path 或错误消息字符串。"""
    try:
        root = resolve_workspace_path(directory)
    except WorkspacePathError as e:
        return f"Error: {e}"
    denied = check_read_denied(directory)
    if denied is not None:
        return f"Error: {denied}"
    if not root.exists():
        return f"Error: directory not found: {directory}"
    if not root.is_dir():
        return f"Error: path is not a directory: {directory}"
    return root


def _resolve_searchable(path: str) -> Path | None:
    """解析工作区路径并做读 deny 检查；返回可读路径，或 ``None`` 表示应跳过。"""
    try:
        resolved = resolve_workspace_path(path)
    except WorkspacePathError:
        return None
    if check_read_denied(path) is not None:
        return None
    return resolved


def _file_search_impl(root: Path, pattern: str, max_results: int) -> list[str]:
    """同步内核：rglob 收集文件名匹配（含逐条 deny 校验）。

    handler 经**单次** ``asyncio.to_thread`` 整体执行本内核——rglob / 逐文件
    stat 在万级条目下若逐条跳线程，跳转成本远超 I/O 本身（同 ``persist.py``
    批量内核的量化论证）。``resolve_workspace_path`` 读 RuntimeSlot contextvar，
    ``asyncio.to_thread`` 会拷贝 context，线程内可见，安全。
    """
    matches: list[str] = []
    for path in root.rglob(pattern):
        if _resolve_searchable(str(path)) is None:
            continue
        matches.append(str(path))
        if len(matches) >= max_results:
            break
    return matches


def _content_search_impl(root: Path, regex: re.Pattern[str], file_pattern: str, max_results: int) -> list[str]:
    """同步内核：rglob + 逐文件限流读取 + 按行正则匹配（单次线程跳转执行，见上）。"""
    results: list[str] = []
    for path in root.rglob(file_pattern):
        resolved = _resolve_searchable(str(path))
        if resolved is None or not resolved.is_file():
            continue
        # P1-18 修复：跳过超大文件，避免 read_text() OOM
        try:
            file_size = resolved.stat().st_size
        except OSError:
            continue
        if file_size > _MAX_FILE_SIZE:
            results.append(f"{resolved}: [skipped — file too large ({file_size / (1024 * 1024):.1f} MB)]")
            if len(results) >= max_results:
                break
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
    return results


@tool(read_only=True)
async def file_search(
    pattern: str,
    directory: str = ".",
    max_results: int = 20,
) -> str:
    """Search for files by name pattern (glob) under a directory."""
    root = _resolve_dir(directory)
    if isinstance(root, str):
        return root

    matches = await asyncio.to_thread(_file_search_impl, root, pattern, max_results)
    if not matches:
        return f"No files matching '{pattern}' found in {directory}"
    return "\n".join(matches)


@tool(read_only=True)
async def content_search(
    query: str,
    directory: str = ".",
    file_pattern: str = "*.txt",
    max_results: int = 20,
) -> str:
    """Search file contents for a regex pattern."""
    root = _resolve_dir(directory)
    if isinstance(root, str):
        return root

    try:
        regex = re.compile(query, re.IGNORECASE)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    results = await asyncio.to_thread(_content_search_impl, root, regex, file_pattern, max_results)
    if not results:
        return f"No matches for '{query}' in {file_pattern} files under {directory}"
    return "\n".join(results)
