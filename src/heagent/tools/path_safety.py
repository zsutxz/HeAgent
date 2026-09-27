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

import errno
import hashlib
import json
import logging
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_workspace_override: Path | None = None
_workspace_runtime = RuntimeSlot[Path]("heagent.pub.workspace_root")


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
    # root 也须 resolve 后再比较：生产默认根是相对路径（如 SkillStore 的
    # ``.heagent/skills``，cwd 锚定）——拿已 resolve 的绝对候选与相对 root 比较会恒拒。
    root_resolved = root.resolve(strict=False)
    if not resolved.is_relative_to(root_resolved):
        raise WorkspacePathError(f"Path escapes current workspace: {path} (workspace: {root})")
    return resolved


def resolve_workspace_path(path: str) -> Path:
    """Resolve a path and ensure it stays inside the current workspace."""
    return resolve_under_root(path, workspace_root())


def read_bytes_under_root(root: Path, relative: str | Path) -> bytes:
    """「解析后安全打开」内核：围栏 → 加固 open → fstat 校验 → 返回**原始字节**。

    全仓技能/包资源读取的**唯一**底层通道（文本读取是其薄封装）：

    1. ``resolve_under_root`` 围栏（逃逸即 ``WorkspacePathError``）；
    2. **加固打开**——两个通道（2026-09-27 硬化）：
       - **POSIX 逐组件 ``openat``**（``os.supports_dir_fd`` 含 ``os.open`` 且有
         ``O_NOFOLLOW``）：从 root 起**每个中间目录组件**都用 ``O_DIRECTORY|O_NOFOLLOW``
         打开，叶组件用 ``O_NOFOLLOW``。围栏之后、打开之前把中间目录换成符号链接的
         替换因此在该组件上直接 ``ELOOP``（旧通道会跟着链接走出去）；
       - **整路径``open``回退**（Windows 无 ``dir_fd``）：语义与硬化前逐字一致，窗口更宽。
       两条通道都带 ``O_NONBLOCK``/``O_CLOEXEC``/``O_BINARY``，且都保留「文件系统不支持
       ``O_NOFOLLOW``（``EINVAL``/``ENOTSUP``）时去掉该标志重试一次」的兼容分支；
    3. ``fstat`` 校验普通文件（拒 FIFO/设备文件，防阻塞与非常规读取）；
    4. 读满并返回原始字节（**不做**解码与换行归一）。

    独立暴露字节通道的原因：内容完整性校验必须对**磁盘上的原始字节**取哈希——文本通道
    会做 CRLF→LF 归一，拿它算哈希会让固有 CRLF 的文件永远对不上（见
    :func:`read_text_with_digest_under_root`）。

    ⚠ defense-in-depth 而非安全边界：竞态窗口收窄但未消除，须 OS 级沙箱兜底。
    """
    raw = Path(relative)
    candidate = raw if raw.is_absolute() else Path.cwd() / raw
    resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    if not resolved.is_relative_to(root_resolved):
        raise WorkspacePathError(f"Path escapes root: {relative} (root: {root})")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is not None:
        flags |= nofollow
    flags |= getattr(os, "O_BINARY", 0)
    parts = _walkable_parts(resolved, root_resolved) if _WALK_SUPPORTED else None
    try:
        if parts is None or nofollow is None:
            descriptor = _open_resolved(resolved, flags, nofollow=nofollow)
        else:
            descriptor = _open_walked(root_resolved, parts, flags, nofollow=nofollow)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise OSError(errno.EISDIR, "resource is not a regular file")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                return stream.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK} and "is a symlink" not in str(exc):
            # 翻译成领域无关的显性消息（与 resolve 围栏同层的路径安全语义）。逐组件通道抛出的
            # ELOOP 已经点名了具体组件（`path component is a symlink: X`），不在这里改写。
            raise OSError(errno.ELOOP, f"final path component is a symlink: {resolved}") from exc
        raise


# ── 「解析后安全打开」的两个内核（POSIX 逐组件 / 整路径回退）───────────────────────────
#
# 2026-09-27（活动台账「技能资源 TOCTOU 残余」的 Ask First 授权项，用户裁定「授权引入平台
# 专用代码」）：把「解析一次 + 整路径 open」换成 **POSIX 逐组件 openat**——每个中间组件都用
# ``O_DIRECTORY | O_NOFOLLOW`` 打开，叶组件用 ``O_NOFOLLOW``。被收窄的窗口是「resolve 之后、
# open 之前把中间目录换成符号链接」：整路径 open 会跟着链接走出去，逐组件 open 在该组件上
# 直接 ``ELOOP``。
#
# ⚠ 仍是**收窄**而非边界：每个组件各自一次原子 open，组件之间仍有时间差（组件级竞态不为零），
# 且 Windows 无 ``dir_fd`` ⇒ 回退整路径 open、窗口与硬化前一样宽。须 OS 级沙箱兜底。

_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW_UNSUPPORTED = frozenset(
    {
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
)


# 平台是否支持逐组件通道：有 ``O_DIRECTORY`` / ``O_NOFOLLOW`` 且 ``os.open`` 收 ``dir_fd``
# （Windows 的 ``os.supports_dir_fd`` 不含 ``os.open`` ⇒ False，走整路径回退通道）。
#
# **在导入期算一次**，不是每次调用重算：`os.open in os.supports_dir_fd` 是**函数对象身份**比较，
# 任何把 ``os.open`` 包一层的代码（测试探针、观测装饰器）都会让它变 False ⇒ 整条逐组件硬化被
# **静默**降级回宽窗口通道（2026-09-27 实测：`monkeypatch.setattr(os, "open", ...)` 后新通道
# 一次都没走）。能力只描述「这个解释器/平台有没有 dir_fd 版 open」，与谁当前挂在 ``os.open`` 上
# 无关，故冻结为常量。
_WALK_SUPPORTED = (
    _O_DIRECTORY != 0
    and getattr(os, "O_NOFOLLOW", None) is not None
    and os.open in getattr(os, "supports_dir_fd", frozenset())
)


def _walkable_parts(resolved: Path, root_resolved: Path) -> tuple[str, ...] | None:
    """``resolved`` 相对 ``root_resolved`` 的组件元组；无法逐组件表达时返回 ``None``（走回退通道）。

    纯路径逻辑（平台能力由 :func:`_walk_supported` 判定）。``resolved`` 已由围栏 resolve 过（无
    ``..`` / ``.`` / 符号链接），这里仍显式拒一次 ``..``——逐组件 open 的路径语义完全由组件名
    序列决定，任何 ``..`` 都会让它指到 root 之外。
    """
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError:
        return None
    parts = tuple(part for part in relative.parts if part not in {"", "."})
    if not parts or ".." in parts:
        return None
    return parts


def _is_symlink_at(directory: int, part: str) -> bool:
    """该组件在**这个目录句柄**上是不是符号链接（仅在 open 失败后调用，用于归因）。"""
    try:
        os.readlink(part, dir_fd=directory)
    except (OSError, TypeError, NotImplementedError):
        return False
    return True


def _open_dir_component(directory: int, part: str, nofollow: int) -> int:
    """打开一个**中间目录**组件（相对 ``directory``）：``O_DIRECTORY|O_NOFOLLOW``。

    「该组件被换成符号链接」在内核侧有**两种**表现：普通 open 带 ``O_NOFOLLOW`` 是 ``ELOOP``，
    而 ``O_DIRECTORY|O_NOFOLLOW`` 撞上符号链接时 Linux 回 ``ENOTDIR``（链接本身不是目录）——
    两条都做一次「到底是不是链接」的归因，是就统一成**点名组件**的 ``ELOOP`` 消息（Windows
    回退通道没有这一层，故该消息只会在 POSIX 出现）；真实文件组件（非链接）仍按原样 ``ENOTDIR``
    上抛。文件系统不支持 ``O_NOFOLLOW`` 时去掉该标志重试一次，与叶组件同口径。
    """
    flags = os.O_RDONLY | _O_DIRECTORY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(part, flags, dir_fd=directory)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK, errno.ENOTDIR} and _is_symlink_at(directory, part):
            raise OSError(errno.ELOOP, f"path component is a symlink: {part}") from exc
        if exc.errno in _NOFOLLOW_UNSUPPORTED:
            return os.open(part, flags & ~nofollow, dir_fd=directory)
        raise


def _open_walked(root_resolved: Path, parts: tuple[str, ...], flags: int, *, nofollow: int) -> int:
    """POSIX 逐组件 ``openat``：中间组件 ``O_DIRECTORY|O_NOFOLLOW``，叶组件沿用 ``flags``。

    root 自身**不做** ``O_NOFOLLOW``：调用方给的 root 可能本身就是符号链接（例如工作区经链接
    指向真实目录），对它加 ``NOFOLLOW`` 会把合法布局判死；加固只针对 root **之内**的组件。
    """
    directory = os.open(root_resolved, os.O_RDONLY | _O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    try:
        for part in parts[:-1]:
            child = _open_dir_component(directory, part, nofollow)
            os.close(directory)
            directory = child
        try:
            return os.open(parts[-1], flags, dir_fd=directory)
        except OSError as exc:
            if exc.errno in _NOFOLLOW_UNSUPPORTED:
                return os.open(parts[-1], flags & ~nofollow, dir_fd=directory)
            raise
    finally:
        os.close(directory)


def _open_resolved(resolved: Path, flags: int, *, nofollow: int | None) -> int:
    """整路径 ``open``——Windows 与不支持 ``dir_fd`` 的环境；语义与 2026-09-27 前逐字一致。"""
    try:
        return os.open(resolved, flags)
    except OSError as exc:
        # Some platforms expose O_NOFOLLOW but their filesystem does not
        # implement it. Preserve the compatibility read in that case.
        if nofollow is not None and exc.errno in _NOFOLLOW_UNSUPPORTED:
            return os.open(resolved, flags & ~nofollow)
        raise


def _decode_text(raw: bytes) -> str:
    """utf-8 解码 + universal newlines（对齐 ``Path.read_text`` 的历史行为）。"""
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def open_text_under_root(root: Path, relative: str | Path) -> str:
    """读取并解码一个受围栏保护的文本文件（:func:`read_bytes_under_root` 的薄封装）。

    语义与拆分前逐字节一致：解码 + CRLF/CR → LF 归一。错误语义：``FileNotFoundError`` /
    ``OSError`` / ``UnicodeDecodeError`` 原样上抛，由调用方映射各自领域错误（如
    ``SkillPackageResourceError``）。``relative`` 接受**绝对路径或 cwd 相对路径**（可已含
    root 前缀——如 ``SkillStore`` 的 ``<base>/<name>/SKILL.md``）；kernel 不再对相对输入二次
    join root（那会把「root/name」拼成「root/root/name」），而是 resolve 后按 ``root`` 围栏
    校验——裸资源名（相对 root 的名字）会因 cwd join 不中而**显性报越界**，不猜。

    ⚠ defense-in-depth 而非安全边界：竞态窗口收窄但未消除，须 OS 级沙箱兜底。
    """
    return _decode_text(read_bytes_under_root(root, relative))


def read_text_with_digest_under_root(root: Path, relative: str | Path) -> tuple[str, str]:
    """文本 + **原始字节**的 sha256 十六进制摘要（内容完整性校验专用）。

    调用方（如 ``SkillPackage`` 对 ``manifest.json`` 的校验）拿它一次性完成「读内容」与
    「算摘要」，避免读两遍文件（读两遍既慢，又人为制造第二个竞态窗口）。
    """
    raw = read_bytes_under_root(root, relative)
    return _decode_text(raw), hashlib.sha256(raw).hexdigest()


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


def build_internal_state_dirs(workspace_root: str | Path | None = None) -> set[str]:
    """Return HeAgent internal state directories that must not be read into context.

    Explicit workspaces protect all twelve runtime directories from WorkspacePaths.
    Without a workspace, preserve the legacy cwd/home roots and five directories.
    """
    if workspace_root is not None:
        from heagent.pub.workspace import WorkspacePaths

        paths = WorkspacePaths.from_root(workspace_root)
        return {
            str(path.resolve())
            for path in (
                paths.sessions,
                paths.ledger,
                paths.runs,
                paths.skills,
                paths.memory_file.parent,
                paths.profile_file.parent,
                paths.cron_file.parent,
                paths.checkpoints,
                paths.sandboxes,
                paths.edit_snapshots,
                paths.console_dir,
                paths.config_backups,
            )
        }
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


def check_read_denied(path: str, root: Path | None = None) -> str | None:
    """Return a deny reason if reading ``path`` is blocked, else ``None``.

    用户 basename 豁免仅作用于 secret-bearing 文件名档；内部状态目录 deny
    **不接受豁免**（另一保护类，不随用户配置放松）。
    """
    candidate = Path(path).expanduser()
    resolved = (candidate if candidate.is_absolute() else (root or workspace_root()) / candidate).resolve()
    rules = user_deny_rules()
    basename = resolved.name.lower()
    if basename not in rules.allow_read_basenames and basename in (
        build_read_denied_basenames() | rules.deny_read_basenames
    ):
        return f"Read denied: '{path}' is a secret-bearing environment file. Read .env.example instead."
    resolved_str = str(resolved)
    for d in build_internal_state_dirs() | build_internal_state_dirs(workspace_root()):
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
