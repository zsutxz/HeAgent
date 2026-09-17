"""Workspace-bound path validation helpers for file-like tools.

另含**凭证文件 deny** 与**内部状态读 deny**（借鉴 hermes `agent/file_safety.py` 设计）：

- 写 deny：凭证/敏感文件与目录（``~/.ssh/*`` / ``~/.aws/*`` / ``.env`` / ``.netrc`` 等）
- 读 deny：secret-bearing 文件名（``.env`` 等）+ ``.heagent/`` 内部状态目录

deny 规则支持**项目级配置** ``.heagent/path_deny.json``（2026-09-17，仿
``injection_signatures.json`` 先例）：只允许**收紧**（追加 deny 项）或**放行显式列举项**
（精确路径 / basename 豁免）——**无任何整体关闭入口**，fail-safe 默认仍为拒。

⚠ 安全立场：deny 规则是 **defense-in-depth 启发式层，非真正安全边界**——shell 工具仍可
``cat .env`` 绕过。仅拦截「合作模式下尊重工具拒绝」的模型，须 OS 级沙箱兜底（见 CLAUDE.md）。
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

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
    """Return a deny reason if writing ``path`` is blocked, else ``None``.

    裁决顺序：用户 allow 豁免（仅精确路径）→ 内置 ∪ 用户收紧 deny。
    """
    resolved = Path(path).expanduser().resolve()
    resolved_str = str(resolved)
    rules = user_deny_rules()
    if resolved_str in rules.allow_write_paths:
        return None  # 放行仅豁免显式列举项；前缀 deny 与内置表语义不变
    if resolved_str in (build_write_denied_paths() | rules.deny_write_paths):
        return f"Write denied: '{path}' is a protected credential/system file."
    for prefix in (*build_write_denied_prefixes(), *rules.deny_write_prefixes):
        if resolved_str.startswith(prefix):
            return f"Write denied: '{path}' is inside a protected directory."
    return None


def check_read_denied(path: str) -> str | None:
    """Return a deny reason if reading ``path`` is blocked, else ``None``.

    用户 basename 豁免仅作用于 secret-bearing 文件名档；内部状态目录 deny
    **不接受豁免**（另一保护类，不随用户配置放松）。
    """
    resolved = Path(path).expanduser().resolve()
    rules = user_deny_rules()
    basename = resolved.name.lower()
    if basename not in rules.allow_read_basenames and basename in (
        build_read_denied_basenames() | rules.deny_read_basenames
    ):
        return f"Read denied: '{path}' is a secret-bearing environment file. Read .env.example instead."
    resolved_str = str(resolved)
    for d in build_internal_state_dirs():
        if resolved_str == d or resolved_str.startswith(d + os.sep):
            return f"Read denied: '{path}' is internal HeAgent state and cannot be read directly."
    return None


# ── 项目级可配置 deny 规则（.heagent/path_deny.json，仿 injection_signatures.json）──

_USER_DENY_PATH = Path(".heagent") / "path_deny.json"


@dataclass(frozen=True)
class _UserDenyRules:
    """项目级 deny/allow 规则（全部为 resolve 后的绝对路径 / 小写 basename）。"""

    deny_write_paths: frozenset[str] = field(default_factory=frozenset)
    deny_write_prefixes: tuple[str, ...] = ()
    deny_read_basenames: frozenset[str] = field(default_factory=frozenset)
    allow_write_paths: frozenset[str] = field(default_factory=frozenset)
    allow_read_basenames: frozenset[str] = field(default_factory=frozenset)


_USER_DENY_RULES: _UserDenyRules | None = None


def reset_user_deny_rules() -> None:
    """清空项目级 deny 规则缓存（测试用；运行中改文件不生效是**有意**的，对齐注入签名先例）。"""
    global _USER_DENY_RULES
    _USER_DENY_RULES = None


def user_deny_rules(path: Path | None = None) -> _UserDenyRules:
    """加载并缓存项目级 deny 规则；文件缺失/非法一律 fail-safe 到「仅内置表」。

    路径经 workspace 围栏锚定（越界即拒绝）；``path`` 参数为测试注入通道
    （对齐 ``_load_user_signatures``）。坏文件 ERROR 告警 + 忽略，从不抛出。
    """
    global _USER_DENY_RULES
    if _USER_DENY_RULES is not None and path is None:
        return _USER_DENY_RULES
    try:
        signature_path = path if path is not None else resolve_under_root(str(_USER_DENY_PATH), workspace_root())
        raw = signature_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        rules = _UserDenyRules()
    except (OSError, UnicodeError, WorkspacePathError) as exc:
        logger.error("Unable to read user path deny rules from %s: %s", _USER_DENY_PATH, exc)
        rules = _UserDenyRules()
    else:
        rules = _parse_user_deny_rules(raw)

    if path is None:
        _USER_DENY_RULES = rules
    return rules


def _parse_user_deny_rules(raw: str) -> _UserDenyRules:
    """解析 ``path_deny.json``；逐键校验，非法键跳过并告警（不整体失效）。"""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("Invalid user path deny rules JSON: %s; using built-in rules only", exc)
        return _UserDenyRules()
    if not isinstance(payload, dict):
        logger.error("User path deny rules must be a JSON object; using built-in rules only")
        return _UserDenyRules()

    def _str_list(key: str) -> list[str]:
        value = payload.get(key, [])
        if not isinstance(value, list):
            logger.error("User path deny rules[%r] must be a JSON array; skipped", key)
            return []
        items: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                logger.error("User path deny rules[%r][%d] must be a non-empty string; skipped", key, index)
                continue
            items.append(item)
        return items

    deny_write_paths = {str(Path(item).expanduser().resolve()) for item in _str_list("deny_write_paths")}
    deny_write_prefixes = tuple(
        str(Path(item).expanduser().resolve()) + os.sep for item in _str_list("deny_write_prefixes")
    )
    deny_read_basenames = {item.lower() for item in _str_list("deny_read_basenames")}
    allow_write_paths = {str(Path(item).expanduser().resolve()) for item in _str_list("allow_write_paths")}
    allow_read_basenames = {item.lower() for item in _str_list("allow_read_basenames")}
    return _UserDenyRules(
        deny_write_paths=frozenset(deny_write_paths),
        deny_write_prefixes=deny_write_prefixes,
        deny_read_basenames=frozenset(deny_read_basenames),
        allow_write_paths=frozenset(allow_write_paths),
        allow_read_basenames=frozenset(allow_read_basenames),
    )
