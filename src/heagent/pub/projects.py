"""Persistent registry for existing local project workspaces."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from heagent.pub.persist import atomic_update_text
from heagent.pub.workspace import WorkspacePaths

if TYPE_CHECKING:
    from builtins import list as builtins_list
    from collections.abc import Callable

logger = logging.getLogger(__name__)

MAX_PROJECTS = 32
MAX_PROJECT_NAME_CHARS = 64
MAX_PROJECT_PATH_CHARS = 4096
MAX_HEALTH_DETAIL_CHARS = 200

# 不可读告警的去重键：按**成因**分两类，同一句柄上每类只出一条 WARNING。
_READ_FAILED = "read_failed"
_CONTENT_CORRUPT = "content_corrupt"


class ProjectRegistryError(ValueError):
    """Stable project registry failure; the transport maps ``code`` to HTTP."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _RegistryCorrupt(Exception):
    """注册表内容无法解析（写路径必须据此**拒绝**改写，见 ``_decode_or_raise``）。"""


class ProjectEntry(BaseModel):
    """Bounded public project metadata. Availability is computed when listing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_CHARS)
    path: str = Field(min_length=1, max_length=MAX_PROJECT_PATH_CHARS)
    available: bool
    last_opened_at: str | None = None
    is_default: bool = False


class _StoredProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_CHARS)
    path: str = Field(min_length=1, max_length=MAX_PROJECT_PATH_CHARS)
    last_opened_at: str | None = None


class ProjectRegistryHealth(BaseModel):
    """注册表健康探针结果（只读、不含路径）。

    ``code`` 是机读判据：``ok`` = 读得到且解析得了（文件不存在也算——空表是合法状态）；
    ``unreadable`` = 读不出（``OSError`` / ``UnicodeError``）或解析不了（内容不合规）。

    ``detail`` 只在 ``unreadable`` 时非空，是给服务端日志与本地排查看的一句原因：**不含注册表
    路径、不含异常类名**（路径只出现在 WARNING 行里）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Literal["ok", "unreadable"] = "ok"
    detail: str = Field(default="", max_length=MAX_HEALTH_DETAIL_CHARS)


def _read_failure_detail(error: OSError | UnicodeError) -> str:
    """把读盘失败折叠成一句无路径原因（``strerror`` 不含路径，也不回显异常类名）。"""
    if isinstance(error, UnicodeError):
        return "registry file is not valid UTF-8 text"
    strerror = getattr(error, "strerror", None)
    return f"registry file cannot be read ({strerror})" if strerror else "registry file cannot be read"


def _corrupt_detail(error: _RegistryCorrupt) -> str:
    """把解析失败折叠成一句原因。

    只按成因归类，不回显原始报错——Pydantic 的校验消息会把条目字段（含登记路径）原样带出来。
    """
    cause = error.__cause__
    if isinstance(cause, json.JSONDecodeError):
        return f"registry file is not valid JSON (line {cause.lineno} column {cause.colno})"
    if isinstance(cause, ValidationError):
        return "registry entries do not match the expected schema"
    return "registry entries are invalid"


def normalize_project_path(path: str | Path) -> str:
    """Expand, resolve, and remove redundant trailing separators from a path."""
    raw = str(path)
    if not raw or len(raw) > MAX_PROJECT_PATH_CHARS:
        raise ProjectRegistryError("invalid_project_path", "project path is invalid")
    try:
        resolved = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectRegistryError("invalid_project_path", "project path is invalid") from exc
    normalized = os.path.normpath(str(resolved))
    if len(normalized) > MAX_PROJECT_PATH_CHARS:
        raise ProjectRegistryError("invalid_project_path", "project path is too long")
    return normalized


def project_id_for(path: str | Path) -> str:
    """Create a stable ID from the platform-normalized canonical path."""
    normalized = normalize_project_path(path)
    return "p" + hashlib.sha256(os.path.normcase(normalized).encode("utf-8")).hexdigest()[:8]


class ProjectRegistry:
    """Atomic, cross-process registry. Project directories are never mutated."""

    def __init__(self, path: str | Path, *, default_path: str | Path) -> None:
        self._path = Path(path)
        self._default_path = normalize_project_path(default_path)
        # 已告警的成因键：同一句柄上 `health()` + `list()` 合计每类只留 1 条，不随请求数刷屏。
        self._warned: set[str] = set()

    def _read_raw(self) -> tuple[str | None, OSError | UnicodeError | None]:
        """唯一的读盘内核：返回 ``(原文, 读失败异常)``；文件不存在 ⇒ ``(None, None)``。

        刻意不在这里打日志：``load()`` 与 ``health()`` 共用这一次读径，各自决定是否经
        :meth:`_warn_once` 告警，两个调用方的告警文案因此不会漂移。
        """
        try:
            return self._path.read_text(encoding="utf-8"), None
        except FileNotFoundError:
            return None, None
        except (OSError, UnicodeError) as exc:
            return None, exc

    def _warn_once(self, reason: str, message: str, *args: object) -> None:
        """同一句柄上同一成因只在**首次**判定不可读时打一条 WARNING（重复请求静默）。"""
        if reason in self._warned:
            return
        self._warned.add(reason)
        logger.warning(message, *args)

    def health(self) -> ProjectRegistryHealth:
        """只读健康探针：不写盘、不改文件，读不出或解析不了一律映射为 ``unreadable``。

        与 :meth:`load` 共用 :meth:`_read_raw`；解析走严格内核 :meth:`_parse`（不用 fail-soft 的
        ``_decode``），否则「解析不了」与「空表」在探针里无法区分。
        """
        raw, error = self._read_raw()
        if error is not None:
            self._warn_once(_READ_FAILED, "Unable to read project registry %s: %s", self._path, error)
            return ProjectRegistryHealth(code="unreadable", detail=_read_failure_detail(error))
        if raw is None:
            return ProjectRegistryHealth()
        try:
            self._parse(raw)
        except _RegistryCorrupt as exc:
            self._warn_once(_CONTENT_CORRUPT, "Invalid project registry; using an empty registry (%s)", exc)
            return ProjectRegistryHealth(code="unreadable", detail=_corrupt_detail(exc))
        return ProjectRegistryHealth()

    def load(self) -> builtins_list[_StoredProject]:
        """读取登记表文件并解析为内部条目；文件不存在视作空表（默认项由 `list()` 补齐）。"""
        raw, error = self._read_raw()
        if error is not None:
            self._warn_once(_READ_FAILED, "Unable to read project registry %s: %s", self._path, error)
            return []
        if raw is None:
            return []
        return self._decode(raw)

    def _default_entry(self) -> ProjectEntry:
        return ProjectEntry(
            id="default",
            name=Path(self._default_path).name or self._default_path,
            path=self._default_path,
            available=Path(self._default_path).is_dir(),
            is_default=True,
        )

    def find(self, project_id: str) -> ProjectEntry | None:
        """按 id 取单条项目（**1 次注册表读 + 1 次** ``is_dir``）——供「只解析一个项目」的热路径。

        ``list()`` 会为**每条**已登记项目各做一次 ``Path.is_dir()``（≤ 31 次）；网页控制台每个
        请求都要解析一个项目、且全程同步跑在事件循环上，故把 stat 收敛到目标项（2026-09-28，台账 A10）。
        语义与 ``list()`` 一致：默认项目恒存在；未登记 ⇒ ``None``；注册表不可读 ⇒ fail-soft 空表。
        """
        if project_id == "default":
            return self._default_entry()
        for item in self.load():
            if item.id == project_id:
                return self._public(item)
        return None

    def list(self) -> builtins_list[ProjectEntry]:
        """返回对外项目列表：`default` 恒在首位，其余按登记顺序。"""
        entries = [self._default_entry()]
        entries.extend(
            ProjectEntry(
                id=item.id,
                name=item.name,
                path=item.path,
                available=Path(item.path).is_dir(),
                last_opened_at=item.last_opened_at,
            )
            for item in self.load()
        )
        registered = entries[1:]
        registered.sort(key=lambda item: item.last_opened_at or "", reverse=True)
        return [*registered, entries[0]]

    def _rewrite_registry(
        self,
        action: str,
        rewrite: Callable[[builtins_list[_StoredProject]], tuple[builtins_list[_StoredProject], _StoredProject]],
    ) -> ProjectEntry:
        """Registry rewrite scaffold: decode(fail-closed) → ``rewrite``（返回新条目表 + 结果条目）→
        atomic write → public entry."""
        result: _StoredProject | None = None

        def update(raw: str) -> tuple[str, None]:
            nonlocal result
            entries, result = rewrite(self._decode_or_raise(raw))
            return self._encode(entries), None

        atomic_update_text(self._path, update)
        if result is None:
            raise RuntimeError(f"project {action} completed without a result")
        return self._public(result)

    def register(self, path: str | Path, name: str | None = None) -> ProjectEntry:
        """登记一个已存在的目录并返回条目（路径先规范化；不可用路径显性拒绝）。"""
        normalized = normalize_project_path(path)
        target = Path(normalized)
        if not target.is_dir():
            raise ProjectRegistryError("invalid_project_path", "project path must be an existing directory")
        display_name = name.strip() if name is not None else target.name
        if not display_name or len(display_name) > MAX_PROJECT_NAME_CHARS:
            raise ProjectRegistryError("invalid_request", "project name is invalid")
        entry_id = project_id_for(normalized)

        def rewrite(entries: builtins_list[_StoredProject]) -> tuple[builtins_list[_StoredProject], _StoredProject]:
            identity = os.path.normcase(normalized)
            for entry in entries:
                if os.path.normcase(entry.path) == identity:
                    return entries, entry
            if len(entries) >= MAX_PROJECTS - 1:
                raise ProjectRegistryError("project_limit_reached", "project registry is full")
            if not target.is_dir():
                raise ProjectRegistryError("invalid_project_path", "project path must be an existing directory")
            entry = _StoredProject(id=entry_id, name=display_name, path=normalized)
            return [*entries, entry], entry

        return self._rewrite_registry("registration", rewrite)

    def _mutate_entry(
        self, project_id: str, action: str, mutate: Callable[[_StoredProject], _StoredProject]
    ) -> ProjectEntry:
        """Registry entry mutation scaffold: decode → locate by id → mutate → persist atomically → project."""

        def rewrite(entries: builtins_list[_StoredProject]) -> tuple[builtins_list[_StoredProject], _StoredProject]:
            for index, entry in enumerate(entries):
                if entry.id == project_id:
                    updated = mutate(entry)
                    entries[index] = updated
                    return entries, updated
            raise ProjectRegistryError("unknown_project", "no such project")

        return self._rewrite_registry(action, rewrite)

    def rename(self, project_id: str, name: str) -> ProjectEntry:
        """改项目显示名；空名或超长显性拒绝（不改路径与 id）。"""
        display_name = name.strip()
        if not display_name or len(display_name) > MAX_PROJECT_NAME_CHARS:
            raise ProjectRegistryError("invalid_request", "project name is invalid")
        return self._mutate_entry(project_id, "rename", lambda entry: entry.model_copy(update={"name": display_name}))

    def remove(self, project_id: str) -> ProjectEntry:
        """撤登记一个项目；`default` 不可移除。"""
        if project_id == "default":
            raise ProjectRegistryError("project_not_removable", "default project cannot be removed")

        def rewrite(entries: builtins_list[_StoredProject]) -> tuple[builtins_list[_StoredProject], _StoredProject]:
            for entry in entries:
                if entry.id == project_id:
                    return [item for item in entries if item.id != project_id], entry
            raise ProjectRegistryError("unknown_project", "no such project")

        return self._rewrite_registry("removal", rewrite)

    def touch(self, project_id: str) -> ProjectEntry:
        """更新项目的最近使用时间戳；`default` 不写盘，直接返回。"""
        if project_id == "default":
            return next(item for item in self.list() if item.is_default)
        timestamp = datetime.now(UTC).isoformat()
        return self._mutate_entry(
            project_id, "touch", lambda entry: entry.model_copy(update={"last_opened_at": timestamp})
        )

    def _decode(self, raw: str) -> builtins_list[_StoredProject]:
        """**读路径**口径：fail-soft —— 解析失败返回空表（脊柱 §4：不阻断 HTTP 服务）。"""
        try:
            return self._parse(raw)
        except _RegistryCorrupt as exc:
            self._warn_once(_CONTENT_CORRUPT, "Invalid project registry; using an empty registry (%s)", exc)
            return []

    @classmethod
    def _decode_or_raise(cls, raw: str) -> builtins_list[_StoredProject]:
        """**写路径**口径：fail-closed —— 绝不在自己解析不了的内容上做「解码 → 改 → 编码」写回。

        写路径若复用 fail-soft 的 ``_decode``，「解析失败 ⇒ 空表」就会被回写进文件：一次坏字节
        （BOM / 超 32 条 / 重复 id / 任何一条缺字段）会在下次 register / rename / remove / touch 时
        **静默清空全部已登记项目**。读到脏数据时宁可让这次写失败（响亮），也不把用户的注册表变成空表。
        """
        try:
            return cls._parse(raw)
        except _RegistryCorrupt as exc:
            raise ProjectRegistryError(
                "server_error", "project registry file is unreadable; refusing to overwrite it"
            ) from exc

    @staticmethod
    def _parse(raw: str) -> builtins_list[_StoredProject]:
        """严格解析（读写的公共内核）；不可解析一律抛 :class:`_RegistryCorrupt`。"""
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError("registry root must be an array")
            entries = [_StoredProject.model_validate(item) for item in data]
            if len(entries) > MAX_PROJECTS or len({item.id for item in entries}) != len(entries):
                raise ValueError("registry entries are invalid")
            return entries
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise _RegistryCorrupt(str(exc)) from exc

    @staticmethod
    def _encode(entries: builtins_list[_StoredProject]) -> str:
        return json.dumps([entry.model_dump(mode="json") for entry in entries], ensure_ascii=False, indent=2) + "\n"

    @staticmethod
    def _public(entry: _StoredProject) -> ProjectEntry:
        return ProjectEntry(
            **entry.model_dump(),
            available=Path(entry.path).is_dir(),
            is_default=False,
        )


def default_project_registry(workspace: str | Path, configured_path: str | Path | None = None) -> ProjectRegistry:
    """按工作区根构造登记表句柄（显式配置路径优先，否则状态根下的 `projects.json`）。"""
    paths = WorkspacePaths.from_root(workspace)
    return ProjectRegistry(configured_path or paths.projects_file, default_path=paths.root)


__all__ = [
    "MAX_HEALTH_DETAIL_CHARS",
    "MAX_PROJECT_NAME_CHARS",
    "MAX_PROJECT_PATH_CHARS",
    "MAX_PROJECTS",
    "ProjectEntry",
    "ProjectRegistry",
    "ProjectRegistryError",
    "ProjectRegistryHealth",
    "default_project_registry",
    "normalize_project_path",
    "project_id_for",
]
