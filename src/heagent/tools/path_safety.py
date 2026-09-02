"""Workspace-bound path validation helpers for file-like tools.

另含**凭证文件 deny** 与**内部状态读 deny**（借鉴 hermes `agent/file_safety.py` 设计）：

- 写 deny：凭证/敏感文件与目录（``~/.ssh/*`` / ``~/.aws/*`` / ``.env`` / ``.netrc`` 等）
- 读 deny：secret-bearing 文件名（``.env`` 等）+ ``.heagent/`` 内部状态目录

⚠ 安全立场：deny 规则是 **defense-in-depth 启发式层，非真正安全边界**——shell 工具仍可
``cat .env`` 绕过。仅拦截「合作模式下尊重工具拒绝」的模型，须 OS 级沙箱兜底（见 CLAUDE.md）。
"""

from __future__ import annotations

import os
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


# ═══════════════════════════════════════════════════════════════
# 凭证 deny / 内部状态读 deny（借鉴 hermes file_safety.py，纯函数）
# ═══════════════════════════════════════════════════════════════


def build_write_denied_paths() -> set[str]:
    """Return exact sensitive paths that must never be written (realpath, absolute)."""
    home = Path.home()
    return {
        str(p.resolve())
        for p in [
            home / ".ssh" / "authorized_keys",
            home / ".ssh" / "id_rsa",
            home / ".ssh" / "id_ed25519",
            home / ".env",
            home / ".netrc",
            home / ".npmrc",
            home / ".pypirc",
            home / ".git-credentials",
            Path("/etc/sudoers"),
            Path("/etc/passwd"),
            Path("/etc/shadow"),
        ]
    }


def build_write_denied_prefixes() -> list[str]:
    """Return sensitive directory prefixes that must never be written."""
    home = Path.home()
    return [
        str((home / ".ssh").resolve()) + os.sep,
        str((home / ".aws").resolve()) + os.sep,
        str((home / ".gnupg").resolve()) + os.sep,
        str((home / ".kube").resolve()) + os.sep,
        "/etc/sudoers.d" + os.sep,
        str((home / ".docker").resolve()) + os.sep,
        str((home / ".azure").resolve()) + os.sep,
        str((home / ".config" / "gh").resolve()) + os.sep,
        str((home / ".config" / "gcloud").resolve()) + os.sep,
    ]


def build_read_denied_basenames() -> set[str]:
    """Return secret-bearing project-local environment file basenames that must not be read."""
    return {
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
        ".env.staging",
        ".envrc",
    }


def build_internal_state_dirs() -> set[str]:
    """Return HeAgent internal state directories that must not be read into context.

    覆盖两个根（``cwd`` 与 ``home``）下的 ``.heagent`` 状态子目录，与 ``session.py`` /
    ``ledger.py`` / ``store.py`` / ``memory`` / ``skills`` 的默认 ``base_dir`` 一致。
    """
    roots = (Path.cwd().resolve(), Path.home().resolve())
    subdirs = ("sessions", "ledger", "runs", "memory", "skills")
    dirs: set[str] = set()
    for root in roots:
        base = root / ".heagent"
        for sub in subdirs:
            dirs.add(str(base / sub))
    return dirs


def check_write_denied(path: str) -> str | None:
    """Return a deny reason if writing ``path`` is blocked, else ``None``."""
    resolved = Path(path).expanduser().resolve()
    resolved_str = str(resolved)
    if resolved_str in build_write_denied_paths():
        return f"Write denied: '{path}' is a protected credential/system file."
    for prefix in build_write_denied_prefixes():
        if resolved_str.startswith(prefix):
            return f"Write denied: '{path}' is inside a protected directory."
    return None


def check_read_denied(path: str) -> str | None:
    """Return a deny reason if reading ``path`` is blocked, else ``None``."""
    resolved = Path(path).expanduser().resolve()
    if resolved.name.lower() in build_read_denied_basenames():
        return f"Read denied: '{path}' is a secret-bearing environment file. Read .env.example instead."
    resolved_str = str(resolved)
    for d in build_internal_state_dirs():
        if resolved_str == d or resolved_str.startswith(d + os.sep):
            return f"Read denied: '{path}' is internal HeAgent state and cannot be read directly."
    return None
