"""Validated, on-demand access to declarative skill packages."""

from __future__ import annotations

import errno
import json
import logging
import os
import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Iterable, cast  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from heagent.pub.frontmatter import parse_inline_pairs, split_frontmatter
from heagent.skills.skill_meta import (
    META_FILENAME,
    SkillMeta,
    SkillMetaError,
    detect_legacy_skill_md_keys,
    parse_meta_yaml,
)
from heagent.tools.path_safety import (
    WorkspacePathError,
    read_bytes_under_root,
    read_text_with_digest_under_root,
    resolve_under_root,
)

logger = logging.getLogger(__name__)

# 完整性凭据文件名：**复用**渲染器 `_bmad/scripts/render_skill.py` 在生成目录写下的
# `manifest.json`（其 `outputs` 为「相对 POSIX 路径 → sha256」），不为本特性新增文件或字段。
_MANIFEST_NAME = "manifest.json"
_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
# 导入器凭据：`memory/skill_importer.py` 把**整批**导入索引写在 skills 根目录下的 `manifest.lock`
# （`resources` 与渲染器 `outputs` 同形），故它是包的**兄弟文件**（`<root>/../manifest.lock`）而非
# 包内产物。同样复用既有产物、不为本特性新增文件或字段。
_LOCK_NAME = "manifest.lock"


class SkillPackageError(ValueError):
    """Base error for an invalid or unusable skill package resource."""

    def __init__(self, skill_id: str, resource: str, reason: str) -> None:
        self.skill_id = skill_id
        self.resource = resource
        self.reason = reason
        super().__init__(f"Skill package '{skill_id}' resource '{resource}': {reason}")


class SkillPackageEntryError(SkillPackageError):
    """Raised when a package entry point is missing or unreadable."""


class SkillPackageResourceError(SkillPackageError):
    """Raised when a package resource is invalid, missing, or outside its root."""


class SkillCatalogError(ValueError):
    """Base error raised while indexing skill packages."""


class SkillResolutionError(SkillCatalogError):
    """Raised when an explicit skill id cannot be resolved unambiguously."""

    def __init__(self, skill_id: str, reason: str, candidates: Iterable[SkillCatalogEntry] = ()) -> None:
        self.skill_id = skill_id
        self.reason = reason
        self.candidates = tuple(candidates)
        details = "; ".join(f"{c.canonical_id} ({c.package_root})" for c in self.candidates)
        suffix = f"; candidates: {details}" if details else ""
        super().__init__(f"Skill '{skill_id}' cannot be resolved: {reason}{suffix}")


class SkillPackageMetadata(BaseModel):
    """Stable metadata associated with a package entry point."""

    model_config = ConfigDict(extra="allow")

    skill_id: str
    package_root: str
    entrypoint: str = "SKILL.md"
    name: str = ""
    description: str = ""
    version: str = ""
    tags: list[str] = Field(default_factory=list)
    canonical_id: str = ""
    source_id: str = ""
    aliases: list[str] = Field(default_factory=list)
    available: bool = True


class SkillPackageEntry(BaseModel):
    """Entry point text and its parsed metadata."""

    text: str
    metadata: SkillPackageMetadata


class SkillPackage(BaseModel):
    """A package boundary with lazy, root-fenced resource reads."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    skill_id: str
    root: Path
    entrypoint: str = "SKILL.md"
    _metadata: SkillPackageMetadata | None = PrivateAttr(default=None)
    _pinned: dict[str, str] | None = PrivateAttr(default=None)
    #: 命中的凭据文件名（`manifest.json` 或 `manifest.lock`），只用于失败文案。
    _pinned_source: str | None = PrivateAttr(default=None)

    def model_post_init(self, __context: object) -> None:
        root = self.root.expanduser().resolve(strict=False)
        if not root.is_dir():
            raise SkillPackageError(self.skill_id, str(root), "package root is missing or not a directory")
        if self.is_absolute(self.entrypoint) or self.has_parent(self.entrypoint):
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, "entrypoint path is invalid")
        object.__setattr__(self, "root", root)

    @property
    def metadata(self) -> SkillPackageMetadata:
        """Load and parse entry metadata on first access."""
        if self._metadata is None:
            object.__setattr__(self, "_metadata", self.read_entry().metadata)
        return cast("SkillPackageMetadata", self._metadata)

    def read_entry(self) -> SkillPackageEntry:
        """Read the package's SKILL.md entry point and parse basic frontmatter.

        触发面字段（name/description）来自 SKILL.md，包元数据来自 meta.yaml（缺省取默认）。
        """
        try:
            text = self._read_text(self.entrypoint, entry=True)
        except SkillPackageResourceError as exc:
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, exc.reason) from exc
        metadata = self._parse_metadata(text, self._load_meta())
        object.__setattr__(self, "_metadata", metadata)
        return SkillPackageEntry(text=text, metadata=metadata)

    def read_resource(self, resource: str) -> str:
        """Read exactly one root-relative resource, without scanning its package."""
        return self._read_text(resource)

    def _read_text(self, resource: str, *, entry: bool = False) -> str:
        """Open and decode one resolved resource via the shared safe-open kernel.

        Phase 4 C4：「解析后安全打开」收敛到 :func:`~heagent.tools.path_safety.open_text_under_root`
        （围栏 + O_NOFOLLOW + fstat 普通文件校验），本方法只保留包域错误标注
        （skill_id / entry 标签与既有 reason 文案，测试钉死）。

        2026-09-23 起增加**内容完整性校验**：包内若有合法的 ``manifest.json``（渲染器产物），
        读到的**原始字节**摘要必须与该清单一致，否则显性失败（见 :meth:`_pinned_hashes`）。
        摘要取原始字节而非归一化文本，故固有 CRLF 的文件同样可校验。
        """
        label = "entrypoint" if entry else "resource"
        try:
            path = self._resolve(resource, entry=entry)
            text, digest = read_text_with_digest_under_root(self.root, path)
            self._verify_pinned_hash(resource, path, digest)
            return text
        except SkillPackageResourceError:
            raise
        except FileNotFoundError as exc:
            reason = "entrypoint is missing" if entry else "resource is missing"
            raise SkillPackageResourceError(self.skill_id, resource, reason) from exc
        except UnicodeDecodeError as exc:
            raise SkillPackageResourceError(self.skill_id, resource, f"cannot read {label}: {exc}") from exc
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                reason = f"cannot read {label}: final path component is a symlink"
            elif exc.errno in {errno.EISDIR, errno.ENXIO}:
                reason = f"cannot read {label}: target is not a regular file"
            else:
                reason = f"cannot read {label}: {exc}"
            raise SkillPackageResourceError(self.skill_id, resource, reason) from exc

    def read_step(self, resource: str) -> str:
        return self.read_resource(resource)

    # 声明式工作流装配（read_workflow 及其解析助手、WorkflowResource 模型、SkillWorkflowError）
    # 已于 2026-09-20 归位到 /goal 领域层：goal/workflow_loader.py（解析）与
    # engine/workflow_resource.py（运行时模型）。本模块只保留技能包的通用资源索引与安全读取。

    def read_reference(self, resource: str) -> str:
        return self._read_in("references", resource)

    def read_template(self, resource: str) -> str:
        return self._read_in("templates", resource)

    def read_asset(self, resource: str) -> str:
        return self._read_in("assets", resource)

    def read_script(self, resource: str) -> str:
        return self._read_in("scripts", resource)

    def _read_in(self, directory: str, resource: str) -> str:
        if self.is_absolute(resource) or self.has_parent(resource):
            raise SkillPackageResourceError(
                self.skill_id,
                resource,
                "resource path is absolute or traverses parent directory",
            )
        parts = PurePath(resource).parts
        relative = resource if parts and parts[0] == directory else f"{directory}/{resource}"
        return self.read_resource(relative)

    def _pinned_hashes(self) -> dict[str, str]:
        """本包的完整性凭据（``<root>/manifest.json`` 的 ``outputs`` 表）；无凭据返回 ``{}``。

        凭据**复用**渲染器既有产物（``_bmad/scripts/render_skill.py`` 在生成目录写
        ``manifest.json``，``outputs`` 即逐文件 sha256），不为本特性新增文件或 lock 字段。

        判定语义（刻意保守，避免误伤其他生产者）：

        - **无** ``manifest.json``：未托管包（手写技能占多数）⇒ ``{}``，读取行为与改动前逐字节一致；
        - **有但** JSON 损坏 / ``outputs`` 形状不符：记一条 warning 后返回 ``{}``——``manifest.json``
          是通用文件名，可能属于别的工具，不能据此拒读（代价：攻击者可借此关闭校验；但能写该目录者
          本就能直接改写 ``SKILL.md``，这仍属 defense-in-depth 而非边界）；
        - **有且合法**：返回 ``{相对 POSIX 路径: sha256}``，读取时逐资源比对。
        """
        if self._pinned is not None:
            return self._pinned
        pinned = self._renderer_hashes()
        if not pinned:
            pinned = self._imported_hashes()
        object.__setattr__(self, "_pinned", pinned)
        return pinned

    def _renderer_hashes(self) -> dict[str, str]:
        """渲染器凭据（包内 ``manifest.json`` 的 ``outputs`` 表）；无凭据返回 ``{}``。

        凭据**复用**渲染器既有产物（``_bmad/scripts/render_skill.py`` 在生成目录写
        ``manifest.json``，``outputs`` 即逐文件 sha256），不为本特性新增文件或 lock 字段。

        判定语义（刻意保守，避免误伤其他生产者）：

        - **无** ``manifest.json``：未托管包（手写技能占多数）⇒ ``{}``，读取行为与改动前逐字节一致；
        - **有但** JSON 损坏 / ``outputs`` 形状不符：记一条 warning 后返回 ``{}``——``manifest.json``
          是通用文件名，可能属于别的工具，不能据此拒读（代价：攻击者可借此关闭校验；但能写该目录者
          本就能直接改写 ``SKILL.md``，这仍属 defense-in-depth 而非边界）；
        - **有且合法**：返回 ``{相对 POSIX 路径: sha256}``，读取时逐资源比对。
        """
        pinned: dict[str, str] = {}
        raw = b""
        # 先 stat 再读：未托管包（手写技能占多数）因此**零额外 open**——读取次数的刻画测试
        # （tests/test_skill_packages_toctou.py 的「恰好一个描述符」与 EINVAL 回退）依赖这一点。
        # 门控只是「要不要尝试读凭据」，真正的读取仍走围栏内核；探测后被删的竞态等同未托管。
        manifest_path = self.root / _MANIFEST_NAME
        if manifest_path.is_file():
            try:
                raw = read_bytes_under_root(self.root, manifest_path)
            except FileNotFoundError:
                raw = b""  # 竞态：stat 后、open 前被删 → 等同未托管
            except OSError as exc:
                logger.warning(
                    "Skill package '%s' manifest unreadable, skipping integrity check: %s", self.skill_id, exc
                )
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Skill package '%s' manifest is not valid JSON, skipping integrity check: %s", self.skill_id, exc
                )
            else:
                outputs = payload.get("outputs") if isinstance(payload, dict) else None
                if isinstance(outputs, dict):
                    pinned = {
                        str(name): str(value)
                        for name, value in outputs.items()
                        if isinstance(name, str) and isinstance(value, str) and _SHA256_HEX.match(value)
                    }
                if not pinned:
                    logger.warning(
                        "Skill package '%s' manifest has no usable 'outputs' hashes, skipping integrity check",
                        self.skill_id,
                    )
        if pinned:
            object.__setattr__(self, "_pinned_source", _MANIFEST_NAME)
        return pinned

    def _imported_hashes(self) -> dict[str, str]:
        """导入器凭据（``<root>/../manifest.lock`` 里本包条目的 ``resources`` 表）；无凭据返回 ``{}``。

        与渲染器凭据同形（相对 POSIX 路径 → sha256），只是生产者与落点不同：``memory/skill_importer.py``
        把**整批**导入索引写在 skills 根目录（`.heagent/skills/manifest.lock`），不是写进每个包，故凭据
        在 `root.parent`；它此前只钉入口（``source_hash`` = 源 ``SKILL.md``），包内
        `references`/`templates`/`assets`/`scripts` 的漂移无人发现（活动台账 A1④）。

        判定语义（与渲染器凭据一致地保守）：

        - **无** ``manifest.lock``：未托管包 ⇒ ``{}``（只多一次 stat，不 open）；
        - **有但** 损坏 / 无本包条目 / ``resources`` 形状不符：warning 后 ``{}``（lock 同样是通用文件名，
          不能据此拒读）；
        - **老 lock**（有条目但没有 ``resources`` 字段）：直接 ``{}`` 且**不告警**——这是升级路径，
          读取行为与改动前逐字节一致，下一次导入自动补齐钉；
        - **有且命中本包**：返回其 ``resources``，读取时逐资源比对。
        """
        pinned: dict[str, str] = {}
        lock_path = self.root.parent / _LOCK_NAME
        if not lock_path.is_file():
            return pinned
        try:
            raw = read_bytes_under_root(self.root.parent, lock_path)
        except FileNotFoundError:
            return pinned  # 竞态：stat 后、open 前被删 → 等同未托管
        except OSError as exc:
            logger.warning(
                "Skill package '%s' manifest.lock unreadable, skipping integrity check: %s", self.skill_id, exc
            )
            return pinned
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning(
                "Skill package '%s' manifest.lock is not valid JSON, skipping integrity check: %s",
                self.skill_id,
                exc,
            )
            return pinned
        entry = self._lock_entry(payload)
        if entry is None:
            return pinned
        resources = entry.get("resources")
        if resources is None:
            return pinned  # 老 lock：只钉了入口
        if isinstance(resources, dict):
            pinned = {
                str(name): str(value)
                for name, value in resources.items()
                if isinstance(name, str) and isinstance(value, str) and _SHA256_HEX.match(value)
            }
        if not pinned:
            logger.warning(
                "Skill package '%s' manifest.lock has no usable 'resources' hashes, skipping integrity check",
                self.skill_id,
            )
            return pinned
        object.__setattr__(self, "_pinned_source", _LOCK_NAME)
        return pinned

    def _lock_entry(self, payload: object) -> dict[str, object] | None:
        """在 lock 里找**本包**条目：先按规范化目标路径，再按 ``canonical_id`` 兜底。

        路径是导入器的正常形态（目标 = skills 根 / canonical_id）；`canonical_id` 兜底覆盖
        「包被移动/改名」——凭据是**内容寻址**的，命中后若内容已变就该失败，不会误放过。
        """
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return None
        want = os.path.normcase(str(self.root))
        fallback: dict[str, object] | None = None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            destination = entry.get("destination_path")
            if isinstance(destination, str) and destination:
                candidate = Path(destination).expanduser().resolve(strict=False)
                if os.path.normcase(str(candidate)) == want:
                    return entry
            if fallback is None and entry.get("canonical_id") == self.skill_id:
                fallback = entry
        return fallback

    def _verify_pinned_hash(self, resource: str, path: Path, digest: str) -> None:
        """把刚读到的原始字节摘要与该资源的凭据比对；不一致即显性失败。

        **未列出**的文件不比对：两种凭据都只钉自己那一批文件（渲染器钉它生成的、导入器钉它物化的），
        包内出现新文件不是本校验的对象（是否允许新增属包目录写权限的问题，见模块与 frame 的非边界声明）。
        """
        pinned = self._pinned_hashes()
        if not pinned:
            return
        try:
            key = path.relative_to(self.root).as_posix()
        except ValueError:  # pragma: no cover - _resolve 已保证落在 root 内
            return
        expected = pinned.get(key)
        if expected is None:
            return
        if expected.lower() != digest.lower():
            source = self._pinned_source or _MANIFEST_NAME
            tail = "file changed after generation" if source == _MANIFEST_NAME else "file changed after import"
            raise SkillPackageResourceError(
                self.skill_id,
                resource,
                f"content hash differs from {source} ({tail})",
            )

    def _resolve(self, resource: str, *, entry: bool = False) -> Path:
        if self.is_absolute(resource) or self.has_parent(resource):
            reason = (
                "entrypoint path is invalid" if entry else "resource path is absolute or traverses parent directory"
            )
            raise SkillPackageResourceError(self.skill_id, resource, reason)
        try:
            return resolve_under_root(resource, self.root)
        except WorkspacePathError as exc:
            raise SkillPackageResourceError(
                self.skill_id, resource, f"resource path escapes package root: {exc}"
            ) from exc

    @staticmethod
    def is_absolute(resource: str) -> bool:
        return any(parser(resource).is_absolute() for parser in (PurePath, PurePosixPath, PureWindowsPath))

    @staticmethod
    def has_parent(resource: str) -> bool:
        return any(".." in parser(resource).parts for parser in (PurePath, PurePosixPath, PureWindowsPath))

    def _load_meta(self) -> SkillMeta:
        """读取包内 meta.yaml；缺文件返回全默认（纯声明面镜像包的常态）。

        stat 先行：无 meta.yaml 的包零额外 open（读取次数刻画测试依赖这一点）。
        meta.yaml 解析失败（契约外键/非法值）抛 :class:`SkillMetaError` 显性失败——
        调用方（``_index_package``）据此产出带诊断的不可用条目，不做静默兜底。
        """
        meta_path = self.root / META_FILENAME
        if not meta_path.is_file():
            return SkillMeta()
        try:
            return parse_meta_yaml(self._read_text(META_FILENAME))
        except (FileNotFoundError, SkillPackageResourceError):
            return SkillMeta()  # 竞态：stat 后被删 → 等同缺文件（镜像 manifest 探测语义）

    def _parse_metadata(self, text: str, meta: SkillMeta) -> SkillPackageMetadata:
        values: dict[str, str] = {}
        split = split_frontmatter(text)
        if split is not None:
            raw_block, _end, _body = split
            legacy = detect_legacy_skill_md_keys(raw_block)
            if legacy:
                raise SkillMetaError(
                    f"SKILL.md frontmatter holds meta contract keys {legacy}; "
                    "move them to meta.yaml (scripts/migrate_skill_meta.py migrates existing skills)"
                )
            # 宽档 keys=() 模式（任意含冒号行、不跳注释），值还原历史语义：strip + 成对引号剥壳。
            values = {key: value.strip().strip("\"'") for key, value in parse_inline_pairs(raw_block).items()}
        return SkillPackageMetadata(
            skill_id=self.skill_id,
            package_root=str(self.root),
            entrypoint=self.entrypoint,
            name=values.get("name", self.skill_id),
            description=values.get("description", ""),
            version=meta.version,
            tags=meta.tags,
            canonical_id=meta.canonical_id,
            source_id=meta.source_id,
            aliases=meta.aliases,
            available=meta.available,
        )


class SkillCatalogEntry(BaseModel):
    """An indexed package and its stable identifiers."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    canonical_id: str
    source_id: str
    aliases: list[str] = Field(default_factory=list)
    version: str = ""
    available: bool = True
    package_root: str
    package: SkillPackage | None = None
    error: str | None = None


class SkillCatalog:
    """Discover packages from explicitly supplied source directories."""

    def __init__(self, source_dirs: Iterable[str | Path] = ()) -> None:
        self.source_dirs = tuple(Path(path).expanduser() for path in source_dirs)
        self._entries: tuple[SkillCatalogEntry, ...] = ()

    @property
    def entries(self) -> list[SkillCatalogEntry]:
        return list(self._entries)

    def scan(self, source_dirs: Iterable[str | Path] | None = None) -> list[SkillCatalogEntry]:
        """Scan immediate child package directories in deterministic order."""
        if source_dirs is not None:
            self.source_dirs = tuple(Path(path).expanduser() for path in source_dirs)
        found: list[SkillCatalogEntry] = []
        for source_dir in self.source_dirs:
            root = source_dir.resolve(strict=False)
            if not root.is_dir() or root.name == ".archive":
                continue
            candidates = (
                [root]
                if (root / "SKILL.md").exists()
                else sorted(
                    (child for child in root.iterdir() if child.is_dir() and child.name != ".archive"),
                    key=lambda p: p.name,
                )
            )
            for package_root in candidates:
                found.append(self._index_package(package_root))
        # Identical canonical packages from the same root are one package, not a conflict.
        unique: dict[tuple[str, str, tuple[str, ...]], SkillCatalogEntry] = {}
        for entry in found:
            key = (entry.canonical_id, entry.package_root, tuple(entry.aliases))
            unique.setdefault(key, entry)
        self._entries = tuple(sorted(unique.values(), key=lambda e: (e.canonical_id, e.package_root)))
        return self.entries

    def _index_package(self, package_root: Path) -> SkillCatalogEntry:
        source_id = package_root.name
        package_root_text = str(package_root.resolve(strict=False))
        try:
            provisional = SkillPackage(skill_id=source_id, root=package_root)
            metadata = provisional.read_entry().metadata
            declared_id = metadata.canonical_id.strip() or metadata.name.strip() or source_id
            canonical_id = self._canonical_id(declared_id)
            source_id = metadata.source_id.strip() or metadata.name.strip() or source_id
            aliases = list(metadata.aliases)
            if source_id != canonical_id:
                aliases.append(source_id)
            if canonical_id.startswith("he-"):
                aliases.append("bmad-" + canonical_id[3:])
            elif canonical_id.startswith("bmad-"):
                aliases.append("he-" + canonical_id[5:])
            aliases = sorted(set(alias for alias in aliases if alias != canonical_id))
            package = SkillPackage(skill_id=canonical_id, root=package_root)
            package.read_entry()
            return SkillCatalogEntry(
                canonical_id=canonical_id,
                source_id=source_id,
                aliases=aliases,
                version=metadata.version,
                package_root=package_root_text,
                package=package if metadata.available else None,
                available=metadata.available,
                error=None if metadata.available else "package marked unavailable by metadata",
            )
        except (SkillPackageError, ValueError, OSError) as exc:
            try:
                canonical_id = self._canonical_id(source_id)
            except ValueError:
                canonical_id = "he-" + re.sub(r"[^a-z0-9_-]+", "-", source_id.lower()).strip("-")
            reason = f"invalid metadata: {exc}" if isinstance(exc, ValueError) else str(exc)
            return SkillCatalogEntry(
                canonical_id=canonical_id,
                source_id=source_id,
                aliases=(
                    ["bmad-" + canonical_id[3:]]
                    if canonical_id.startswith("he-")
                    else ["he-" + canonical_id[5:]]
                    if canonical_id.startswith("bmad-")
                    else []
                ),
                available=False,
                package_root=package_root_text,
                error=reason,
            )

    @staticmethod
    def _canonical_id(skill_id: str) -> str:
        value = skill_id.strip()
        if not re.fullmatch(r"(?:he|bmad)-[a-z0-9][a-z0-9_-]*", value):
            raise ValueError(f"invalid skill id '{skill_id}'")
        return value


class SkillResolver:
    """Resolve canonical ids and compatibility aliases deterministically."""

    def __init__(self, catalog: SkillCatalog | Iterable[SkillCatalogEntry]) -> None:
        self.catalog = catalog

    def resolve(self, skill_id: str) -> SkillPackage:
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise SkillResolutionError(str(skill_id), "skill id is empty")
        entries = self.catalog.entries if isinstance(self.catalog, SkillCatalog) else list(self.catalog)
        requested = skill_id.strip()
        try:
            canonical_requested = SkillCatalog._canonical_id(requested)
        except ValueError:
            canonical_requested = ""
        # Canonical ids are explicit and always outrank alias matches.
        canonical = [e for e in entries if canonical_requested and e.canonical_id == canonical_requested]
        matches = canonical or [e for e in entries if requested == e.source_id or requested in e.aliases]
        if not matches:
            reason = "invalid skill id" if not canonical_requested else "skill id was not found"
            raise SkillResolutionError(requested, reason)
        if len(matches) != 1:
            raise SkillResolutionError(requested, "canonical or alias id is ambiguous", matches)
        entry = matches[0]
        if not entry.available or entry.package is None:
            raise SkillResolutionError(requested, entry.error or "package is unavailable", matches)
        return entry.package
