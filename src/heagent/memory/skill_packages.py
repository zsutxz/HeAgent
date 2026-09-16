"""Validated, on-demand access to declarative skill packages."""

from __future__ import annotations

import errno
import os
import re
import stat
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Literal, cast  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from heagent.tools.path_safety import WorkspacePathError, resolve_under_root


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


class SkillWorkflowError(SkillPackageResourceError):
    """Raised when a declarative workflow or its ordered steps are invalid."""


class WorkflowStepResource(BaseModel):
    """One Markdown workflow step and its declarative execution contract."""

    index: int
    name: str
    instructions: str
    input: str = ""
    output: str = ""
    next: str | None = None
    checkpoint: str = ""
    validation_rules: str = ""
    role: str = ""
    story_loop: str = ""
    max_parallel_stories: int = Field(default=1, ge=1, le=5)
    # Per-step iteration budget; 0 = inherit Settings.goal_max_iterations.
    max_iterations: int = Field(default=0, ge=0)
    frontmatter: dict[str, Any] = Field(default_factory=dict)


CheckpointMode = Literal["", "auto", "prompt"]
OpenQuestionMode = Literal["", "block", "default"]


class WorkflowResource(BaseModel):
    """A workflow declaration with steps in execution order."""

    name: str
    instructions: str
    steps: list[WorkflowStepResource]
    entrypoint: str = ""
    on_create: str = "persist_goal_identity"
    step_executor: str = "subagent"
    # Empty means the workflow defers to GOAL_CHECKPOINT_MODE/settings.
    checkpoint_mode: CheckpointMode = ""
    # Empty means the workflow defers to GOAL_OPEN_QUESTION_MODE/settings.
    open_question_mode: OpenQuestionMode = ""
    frontmatter: dict[str, Any] = Field(default_factory=dict)


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

    def model_post_init(self, __context: object) -> None:
        root = self.root.expanduser().resolve(strict=False)
        if not root.is_dir():
            raise SkillPackageError(self.skill_id, str(root), "package root is missing or not a directory")
        if self._is_absolute(self.entrypoint) or self._has_parent(self.entrypoint):
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, "entrypoint path is invalid")
        object.__setattr__(self, "root", root)

    @property
    def metadata(self) -> SkillPackageMetadata:
        """Load and parse entry metadata on first access."""
        if self._metadata is None:
            object.__setattr__(self, "_metadata", self.read_entry().metadata)
        return cast("SkillPackageMetadata", self._metadata)

    def read_entry(self) -> SkillPackageEntry:
        """Read the package's SKILL.md entry point and parse basic frontmatter."""
        try:
            text = self._read_text(self.entrypoint, entry=True)
        except SkillPackageResourceError as exc:
            raise SkillPackageEntryError(self.skill_id, self.entrypoint, exc.reason) from exc
        metadata = self._parse_metadata(text)
        object.__setattr__(self, "_metadata", metadata)
        return SkillPackageEntry(text=text, metadata=metadata)

    def read_resource(self, resource: str) -> str:
        """Read exactly one root-relative resource, without scanning its package."""
        return self._read_text(resource)

    def _read_text(self, resource: str, *, entry: bool = False) -> str:
        """Open and decode one resolved resource while retaining its descriptor lifetime."""
        # Non-blocking open lets fstat reject FIFOs/devices without waiting for
        # another process to provide a writer. Regular files ignore this flag.
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is not None:
            flags |= nofollow
        binary = getattr(os, "O_BINARY", 0)
        flags |= binary
        try:
            path = self._resolve(resource, entry=entry)
            try:
                descriptor = os.open(path, flags)
            except OSError as exc:
                # Some platforms expose O_NOFOLLOW but their filesystem does not
                # implement it. Preserve the compatibility read in that case.
                unsupported = {
                    errno.EINVAL,
                    getattr(errno, "ENOTSUP", errno.EINVAL),
                    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
                }
                if nofollow is not None and exc.errno in unsupported:
                    descriptor = os.open(path, flags & ~nofollow)
                else:
                    raise
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode):
                    raise OSError(errno.EISDIR, "resource is not a regular file")
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = -1
                    text = stream.read().decode("utf-8")
                    # Path.read_text() historically performed universal newline
                    # translation; retain that public behavior after decoding.
                    return text.replace("\r\n", "\n").replace("\r", "\n")
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        except FileNotFoundError as exc:
            reason = "entrypoint is missing" if entry else "resource is missing"
            raise SkillPackageResourceError(self.skill_id, resource, reason) from exc
        except UnicodeDecodeError as exc:
            label = "entrypoint" if entry else "resource"
            raise SkillPackageResourceError(self.skill_id, resource, f"cannot read {label}: {exc}") from exc
        except OSError as exc:
            label = "entrypoint" if entry else "resource"
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                reason = f"cannot read {label}: final path component is a symlink"
            elif exc.errno in {errno.EISDIR, errno.ENXIO}:
                reason = f"cannot read {label}: target is not a regular file"
            else:
                reason = f"cannot read {label}: {exc}"
            raise SkillPackageResourceError(self.skill_id, resource, reason) from exc

    def read_step(self, resource: str) -> str:
        return self.read_resource(resource)

    def read_workflow(self, resource: str = "workflow.md") -> WorkflowResource:  # noqa: C901
        """Load ``workflow.md`` and all declared/discovered steps in order.

        The workflow file is the only authority for an explicit ``steps`` list.
        A workflow may keep its step contracts in the same file using ``## Step
        NN: name`` sections; external ``step-NN-*.md`` resources remain
        supported for compatibility with existing packages.
        """
        try:
            text = self.read_resource(resource)
        except SkillPackageResourceError as exc:
            raise SkillWorkflowError(self.skill_id, resource, exc.reason) from exc
        try:
            values, body = self._parse_resource_frontmatter(text)
        except ValueError as exc:
            raise SkillWorkflowError(self.skill_id, resource, str(exc)) from exc
        declared = values.get("steps")
        inline = self._parse_inline_workflow_steps(body)
        if declared is None or declared == "":
            names = [step.name for step in inline] if inline else self._discover_workflow_steps()
        else:
            names = self._resource_list(declared, resource)
        if not names:
            raise SkillWorkflowError(self.skill_id, resource, "workflow has no steps")
        steps: list[WorkflowStepResource] = []
        seen_names: set[str] = set()
        seen_indexes: set[int] = set()
        for position, name in enumerate(names, 1):
            if name in seen_names:
                raise SkillWorkflowError(self.skill_id, name, "duplicate step reference")
            seen_names.add(name)
            match = re.match(r"^step-(\d+)(?:[-_].*)?\.md$", Path(name).name, re.IGNORECASE)
            if match is None:
                raise SkillWorkflowError(self.skill_id, name, "step filename must use step-NN-*.md order")
            index = int(match.group(1))
            if index in seen_indexes:
                raise SkillWorkflowError(self.skill_id, name, "duplicate step number")
            seen_indexes.add(index)
            if index != position:
                raise SkillWorkflowError(self.skill_id, name, "step order must start at 1 and be contiguous")
            inline_step = next((step for step in inline if step.name == name), None)
            if inline_step is not None:
                steps.append(inline_step.model_copy(update={"index": index}))
                continue
            try:
                step_text = self.read_resource(name)
            except SkillPackageResourceError as exc:
                raise SkillWorkflowError(self.skill_id, name, exc.reason) from exc
            try:
                step_values, step_body = self._parse_resource_frontmatter(step_text)
            except ValueError as exc:
                raise SkillWorkflowError(self.skill_id, name, str(exc)) from exc
            steps.append(
                WorkflowStepResource(
                    index=index,
                    name=name,
                    instructions=step_body.strip(),
                    input=self._value_text(step_values, "input", "inputs"),
                    output=self._value_text(step_values, "output", "outputs"),
                    next=self._value_text(step_values, "next", "next_step") or None,
                    checkpoint=self._value_text(step_values, "checkpoint"),
                    validation_rules=self._value_text(step_values, "validation", "validation_rules", "verify"),
                    role=self._value_text(step_values, "role", "agent"),
                    story_loop=self._value_text(step_values, "story_loop"),
                    max_parallel_stories=self._parallel_limit(step_values, name),
                    max_iterations=self._iteration_budget(step_values, name),
                    frontmatter=step_values,
                )
            )
        known = {step.name for step in steps}
        for step in steps:
            if step.next and step.next not in known:
                raise SkillWorkflowError(self.skill_id, step.name, f"next step reference is not declared: {step.next}")
        checkpoint_mode = self._value_text(values, "checkpoint_mode").casefold()
        if checkpoint_mode not in {"", "auto", "prompt"}:
            raise SkillWorkflowError(
                self.skill_id,
                resource,
                f"invalid checkpoint_mode '{checkpoint_mode}'; expected auto or prompt",
            )
        open_question_mode = self._value_text(values, "open_question_mode", "open_questions").casefold()
        if open_question_mode not in {"", "block", "default"}:
            raise SkillWorkflowError(
                self.skill_id,
                resource,
                f"invalid open_question_mode '{open_question_mode}'; expected block or default",
            )
        return WorkflowResource(
            name=self._value_text(values, "name", "id") or self.skill_id,
            instructions=(body.split("\n## Step ", 1)[0] if inline else body).strip(),
            steps=steps,
            entrypoint=self._value_text(values, "entrypoint"),
            on_create=self._value_text(values, "on_create", "initialize") or "persist_goal_identity",
            step_executor=self._value_text(values, "step_executor", "executor") or "subagent",
            checkpoint_mode=cast("CheckpointMode", checkpoint_mode),
            open_question_mode=cast("OpenQuestionMode", open_question_mode),
            frontmatter=values,
        )

    load_workflow = read_workflow

    def _discover_workflow_steps(self) -> list[str]:
        candidates = sorted(
            (
                path.name
                for path in self.root.iterdir()
                if path.is_file() and re.match(r"^step-\d+.*\.md$", path.name, re.I)
            ),
            key=self._step_sort_key,
        )
        return candidates

    def _parse_inline_workflow_steps(self, body: str) -> list[WorkflowStepResource]:
        """Parse step contracts embedded in ``workflow.md``.

        Each section starts with ``## Step NN: name``. Metadata immediately
        following the heading uses the same ``key: value`` syntax as a step
        file; the remaining section is the step instruction text.
        """
        matches = list(re.finditer(r"(?m)^##\s+Step\s+(\d+)\s*:\s*([^\n]+)\s*$", body))
        if not matches:
            return []
        steps: list[WorkflowStepResource] = []
        for position, match in enumerate(matches, 1):
            number = int(match.group(1))
            if number != position:
                raise SkillWorkflowError(
                    self.skill_id, "workflow.md", "inline step order must start at 1 and be contiguous"
                )
            raw_name = re.sub(r"[^a-z0-9]+", "-", match.group(2).strip().casefold()).strip("-")
            name = f"step-{number:02d}-{raw_name or 'step'}.md"
            end = matches[position].start() if position < len(matches) else len(body)
            section = body[match.end() : end].strip("\n")
            lines = section.splitlines()
            metadata: dict[str, Any] = {}
            instruction_start = 0
            for idx, line in enumerate(lines):
                if not line.strip():
                    instruction_start = idx + 1
                    break
                if ":" not in line or line[:1].isspace():
                    instruction_start = idx
                    break
                key, value = line.split(":", 1)
                key = key.strip()
                if not key or key in metadata:
                    raise SkillWorkflowError(self.skill_id, name, f"invalid inline step metadata: {line}")
                metadata[key] = value.strip().strip("\"'")
                instruction_start = idx + 1
            steps.append(
                WorkflowStepResource(
                    index=number,
                    name=name,
                    instructions="\n".join(lines[instruction_start:]).strip(),
                    input=self._value_text(metadata, "input", "inputs"),
                    output=self._value_text(metadata, "output", "outputs"),
                    next=self._value_text(metadata, "next", "next_step") or None,
                    checkpoint=self._value_text(metadata, "checkpoint"),
                    validation_rules=self._value_text(metadata, "validation", "validation_rules", "verify"),
                    role=self._value_text(metadata, "role", "agent"),
                    story_loop=self._value_text(metadata, "story_loop"),
                    max_parallel_stories=self._parallel_limit(metadata, name),
                    max_iterations=self._iteration_budget(metadata, name),
                    frontmatter=metadata,
                )
            )
        return steps

    @staticmethod
    def _step_sort_key(value: str) -> tuple[int, str]:
        match = re.match(r"^step-(\d+)", value, re.IGNORECASE)
        if match is None:
            raise ValueError(f"invalid step filename: {value}")
        return int(match.group(1)), value.lower()

    def _resource_list(self, value: Any, workflow: str) -> list[str]:
        if isinstance(value, str):
            items = [item.strip() for item in value.strip("[]").split(",") if item.strip()]
        elif isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
        else:
            raise SkillWorkflowError(self.skill_id, workflow, "steps must be a list")
        for item in items:
            if self._is_absolute(item) or self._has_parent(item):
                raise SkillWorkflowError(self.skill_id, item, "step reference must stay within package root")
        return items

    @staticmethod
    def _value_text(values: dict[str, Any], *keys: str) -> str:
        for key in keys:
            if key in values and values[key] is not None:
                value = values[key]
                if isinstance(value, list):
                    return ", ".join(str(item) for item in value)
                result = str(value).strip().strip("\"'")
                return "" if result.casefold() in {"none", "null"} else result
        return ""

    def _bounded_int(self, values: dict[str, Any], resource: str, *, key: str, default: int, maximum: int) -> int:
        """解析有界整数设置（缺省取 ``default``；bool / 非数字 / 越界一律抛，不做强制转换）。

        ``max_parallel_stories`` 与 ``max_iterations`` 的校验规则本来逐字相同（各持一份副本），
        此处参数化为唯一实现：**两条规则必须一致**，否则同一份 frontmatter 在两处得到不同宽容度。
        """
        if key not in values:
            return default
        message = f"{key} must be an integer from 1 to {maximum}"
        raw = values[key]
        if isinstance(raw, bool):
            raise SkillWorkflowError(self.skill_id, resource, message)
        text = str(raw).strip().strip("\"'")
        if not re.fullmatch(r"[1-9]\d*", text or "") or int(text) > maximum:
            raise SkillWorkflowError(self.skill_id, resource, message)
        return int(text)

    def _parallel_limit(self, values: dict[str, Any], resource: str) -> int:
        """Parse the bounded Step 07 concurrency setting without coercion."""
        return self._bounded_int(values, resource, key="max_parallel_stories", default=1, maximum=5)

    def _iteration_budget(self, values: dict[str, Any], resource: str) -> int:
        """Parse the optional per-step iteration budget (0 = inherit the global setting)."""
        return self._bounded_int(values, resource, key="max_iterations", default=0, maximum=1000)

    @staticmethod
    def _parse_resource_frontmatter(text: str) -> tuple[dict[str, Any], str]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.DOTALL)
        if match is None:
            return {}, text
        values: dict[str, Any] = {}
        for line in match.group(1).splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if ":" not in line or line[:1].isspace():
                raise ValueError(f"invalid workflow frontmatter line: {line}")
            key, raw = line.split(":", 1)
            key = key.strip()
            if not key or key in values:
                raise ValueError(f"duplicate workflow frontmatter key: {key}")
            raw = raw.strip()
            if raw.startswith("[") and raw.endswith("]"):
                values[key] = [item.strip().strip("\"'") for item in raw[1:-1].split(",") if item.strip()]
            elif raw.lower() in {"true", "false"}:
                values[key] = raw.lower() == "true"
            else:
                values[key] = raw.strip("\"'")
        return values, text[match.end() :]

    def read_reference(self, resource: str) -> str:
        return self._read_in("references", resource)

    def read_template(self, resource: str) -> str:
        return self._read_in("templates", resource)

    def read_asset(self, resource: str) -> str:
        return self._read_in("assets", resource)

    def read_script(self, resource: str) -> str:
        return self._read_in("scripts", resource)

    def _read_in(self, directory: str, resource: str) -> str:
        if self._is_absolute(resource) or self._has_parent(resource):
            raise SkillPackageResourceError(
                self.skill_id,
                resource,
                "resource path is absolute or traverses parent directory",
            )
        parts = PurePath(resource).parts
        relative = resource if parts and parts[0] == directory else f"{directory}/{resource}"
        return self.read_resource(relative)

    def _resolve(self, resource: str, *, entry: bool = False) -> Path:
        if self._is_absolute(resource) or self._has_parent(resource):
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
    def _is_absolute(resource: str) -> bool:
        return any(parser(resource).is_absolute() for parser in (PurePath, PurePosixPath, PureWindowsPath))

    @staticmethod
    def _has_parent(resource: str) -> bool:
        return any(".." in parser(resource).parts for parser in (PurePath, PurePosixPath, PureWindowsPath))

    def _parse_metadata(self, text: str) -> SkillPackageMetadata:
        values: dict[str, str] = {}
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if match:
            for line in match.group(1).splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    values[key.strip()] = value.strip().strip("\"'")
        tags = [tag.strip() for tag in values.get("tags", "").strip("[]").split(",") if tag.strip()]
        aliases = [tag.strip().strip("\"'") for tag in values.get("aliases", "").strip("[]").split(",") if tag.strip()]
        canonical_id = values.get("canonical_id", values.get("canonicalId", ""))
        source_id = values.get("source_id", values.get("sourceId", ""))
        available_value = values.get("available", "true").lower()
        if available_value not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError(f"invalid available flag '{available_value}'")
        available = available_value not in {"false", "0", "no"}
        return SkillPackageMetadata(
            skill_id=self.skill_id,
            package_root=str(self.root),
            entrypoint=self.entrypoint,
            name=values.get("name", self.skill_id),
            description=values.get("description", ""),
            version=values.get("version", ""),
            tags=tags,
            canonical_id=canonical_id,
            source_id=source_id,
            aliases=aliases,
            available=available,
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
