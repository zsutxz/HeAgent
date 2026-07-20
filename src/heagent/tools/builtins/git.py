"""Git 版本控制工具 — 只读操作供 Agent 理解代码历史。

所有工具均经工作区路径校验，仅执行 ``git diff/log/status/blame`` 等只读子命令，
标记 ``readOnlyHint=True`` 供 PolicyEngine 自动放行。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from heagent.tools.decorator import tool
from heagent.tools.path_safety import resolve_under_root, workspace_root

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


_GIT_TIMEOUT = 60  # 只读 git 操作的硬上界（秒），防凭据提示/远端不可达/巨型 diff 无限挂起


async def _run_git(*args: str, cwd: Path | None = None) -> str:
    """执行 git 子命令，返回 stdout 文本；失败或超时抛 RuntimeError。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or workspace_root(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GIT_TIMEOUT)
    except TimeoutError:
        # wait_for 仅取消 await、不杀子进程——须显式终止防僵尸，再报超时
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        except Exception:
            pass
        raise RuntimeError(f"git {' '.join(args)} timed out after {_GIT_TIMEOUT}s") from None
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        err = detail or f"git {' '.join(args)} failed with code {proc.returncode}"
        raise RuntimeError(err)
    return stdout.decode("utf-8", errors="replace").strip()


def _validate_git_path(file_path: str) -> str:
    """校验路径在工作区内，返回相对于 workspace root 的相对路径（git 用）。"""
    root = workspace_root()
    resolved = resolve_under_root(file_path, root)
    return str(resolved.relative_to(root))


@tool(read_only=True)
async def git_status(path: str = "") -> str:
    """Show working tree status (git status --porcelain). Optionally filter by path."""
    args = ["status", "--porcelain"]
    if path:
        args.append(_validate_git_path(path))
    return await _run_git(*args) or "(clean)"


@tool(read_only=True)
async def git_diff(staged: bool = False, path: str = "") -> str:
    """Show working tree changes (git diff). Read-only.

    Args:
        staged: If True, show staged changes (git diff --staged). Default False (unstaged).
        path: Optional file/directory path to filter (relative to workspace root). Empty = all.
    """
    args = ["diff"]
    if staged:
        args.append("--staged")
    if path:
        args.append("--")
        args.append(_validate_git_path(path))
    return await _run_git(*args) or "(no changes)"


@tool(read_only=True)
async def git_log(max_count: int = 20, path: str = "") -> str:
    """Show commit history (git log --oneline). Read-only.

    Args:
        max_count: Maximum number of commits to show (default 20, max 100).
        path: Optional file/directory path to filter (relative to workspace root). Empty = all.
    """
    count = max(1, min(max_count, 100))
    args = ["log", "--oneline", f"-n{count}"]
    if path:
        args.append("--")
        args.append(_validate_git_path(path))
    return await _run_git(*args) or "(no commits)"


@tool(read_only=True)
async def git_blame(file_path: str) -> str:
    """Show line-by-line authorship for a file (git blame). Read-only.

    Args:
        file_path: Path to the file (relative to workspace root). Required.
    """
    if not file_path.strip():
        raise ValueError("file_path is required")
    rel = _validate_git_path(file_path)
    return await _run_git("blame", rel)
