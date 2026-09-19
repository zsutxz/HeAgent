"""Declarative Markdown artifact contracts for Goal/Epic/Story workflows."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from heagent.frontmatter import FrontmatterSyntaxError, parse_scalar, parse_strict_pairs, split_frontmatter

if TYPE_CHECKING:
    from collections.abc import Iterable


class ArtifactContractError(ValueError):
    """Raised when a Markdown artifact cannot satisfy its declared contract."""


class ArtifactKind(StrEnum):
    GOAL = "goal"
    EPIC = "epic"
    STORY = "story"


class ArtifactStatus(StrEnum):
    BACKLOG = "backlog"
    PLANNING = "planning"
    READY_FOR_DEV = "ready-for-dev"
    IN_PROGRESS = "in-progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"


class Frontmatter(BaseModel):
    """Parsed YAML-like frontmatter and the Markdown body it prefixes."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)
    body: str

    @property
    def data(self) -> dict[str, Any]:
        """Compatibility alias for callers that call the mapping ``data``."""
        return self.values


class ArtifactContract(BaseModel):
    """Common typed metadata for one artifact document."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: ArtifactKind
    status: ArtifactStatus
    title: str = Field(min_length=1)
    parent_id: str | None = None
    goal_id: str | None = None
    sections: dict[str, str] = Field(default_factory=dict)
    source: str = ""


class GoalArtifact(ArtifactContract):
    kind: ArtifactKind = ArtifactKind.GOAL
    epic_ids: list[str] = Field(default_factory=list)


class EpicArtifact(ArtifactContract):
    kind: ArtifactKind = ArtifactKind.EPIC
    goal_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    value: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    dependencies: str = Field(min_length=1)
    acceptance_criteria: str = Field(min_length=1)
    story_ids: list[str] = Field(default_factory=list)
    definition_of_done: str = Field(min_length=1)

    @model_validator(mode="after")
    def set_parent(self) -> EpicArtifact:
        if self.parent_id is not None and self.parent_id != self.goal_id:
            raise ValueError("parent_id must equal goal_id")
        object.__setattr__(self, "parent_id", self.goal_id)
        return self


class StoryArtifact(ArtifactContract):
    kind: ArtifactKind = ArtifactKind.STORY
    goal_id: str = Field(min_length=1)
    epic_id: str = Field(min_length=1)
    user_story: str = Field(min_length=1)
    acceptance_criteria: str = Field(min_length=1)
    tasks: str = Field(min_length=1)
    definition_of_done: str = Field(min_length=1)

    @model_validator(mode="after")
    def set_parent(self) -> StoryArtifact:
        if self.parent_id is not None and self.parent_id != self.epic_id:
            raise ValueError("parent_id must equal epic_id")
        object.__setattr__(self, "parent_id", self.epic_id)
        return self


Artifact = GoalArtifact | EpicArtifact | StoryArtifact

_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_TBD = re.compile(r"\bTBD\b", re.IGNORECASE)
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


def parse_frontmatter(text: str) -> Frontmatter:
    """Parse the constrained YAML frontmatter used by workflow artifacts."""
    if not isinstance(text, str) or not text.strip():
        raise ArtifactContractError("artifact must be non-empty Markdown")
    split = split_frontmatter(text, closed_at_eof=True)
    if split is None:
        raise ArtifactContractError("artifact requires frontmatter")
    raw, _end, body = split
    try:
        pairs = parse_strict_pairs(raw)
    except FrontmatterSyntaxError as exc:
        # 异常类型与消息文案保持收敛前的契约（测试锁定）；结构判定移入共享模块。
        if exc.kind == "invalid_line":
            raise ArtifactContractError(f"invalid frontmatter line {exc.line_number}") from exc
        raise ArtifactContractError(f"duplicate or empty frontmatter key: {exc.key!r}") from exc
    values: dict[str, Any] = {key: parse_scalar(value) for key, value in pairs.items()}
    return Frontmatter(values=values, body=body)


def _sections(body: str) -> dict[str, str]:
    fence_ranges: list[tuple[int, int]] = []
    fence_start: int | None = None
    fence_marker: tuple[str, int] | None = None
    offset = 0
    for line in body.splitlines(keepends=True):
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if fence_start is None:
                fence_start, fence_marker = offset, (marker[0], len(marker))
            elif fence_marker and marker[0] == fence_marker[0] and len(marker) >= fence_marker[1]:
                fence_ranges.append((fence_start, offset + len(line)))
                fence_start, fence_marker = None, None
        offset += len(line)
    if fence_start is not None:
        fence_ranges.append((fence_start, len(body)))
    matches = [
        match
        for match in _HEADING.finditer(body)
        if not any(start <= match.start() < end for start, end in fence_ranges)
    ]
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = re.sub(r"\s+", " ", match.group(1).strip()).casefold()
        content = body[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(body)].strip()
        if name in sections:
            raise ArtifactContractError(f"duplicate section: {match.group(1).strip()}")
        if not content:
            raise ArtifactContractError(f"section is empty: {match.group(1).strip()}")
        sections[name] = content
    return sections


def _required(sections: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if name.casefold() in sections:
            return sections[name.casefold()]
    label = names[0]
    label = "Definition of Done" if label.casefold() == "definition of done" else label.title()
    raise ArtifactContractError(f"missing required section: {label}")


def _ids(content: str) -> list[str]:
    return re.findall(r"(?m)^\s*[-*]\s+(?:\[[ xX]\]\s+)?([A-Za-z][A-Za-z0-9_.-]*)\s*:", content)


def _metadata(values: dict[str, Any], kind: ArtifactKind) -> tuple[str, ArtifactStatus, str]:
    if str(values.get("type", "")).casefold() != kind.value:
        raise ArtifactContractError(f"frontmatter type must be {kind.value}")
    identifier = values.get("id")
    if not isinstance(identifier, str) or not identifier.strip() or not _ID.fullmatch(identifier.strip()):
        raise ArtifactContractError("frontmatter id is required and must be a valid identifier")
    try:
        status = ArtifactStatus(str(values.get("status", "")).strip())
    except ValueError as exc:
        raise ArtifactContractError("frontmatter status is invalid") from exc
    title = str(values.get("title", "")).strip()
    return identifier.strip(), status, title


def parse_artifact(source: str | Path) -> Artifact:
    """Parse and validate a Goal, Epic, or Story Markdown artifact."""
    text = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
    frontmatter = parse_frontmatter(text)
    if _TBD.search(text):
        raise ArtifactContractError("artifact contains unresolved TBD")
    values = frontmatter.values
    try:
        kind = ArtifactKind(str(values.get("type", "")).casefold())
    except ValueError as exc:
        raise ArtifactContractError("frontmatter type must be goal, epic, or story") from exc
    sections = _sections(frontmatter.body)
    identifier, status, title = _metadata(values, kind)
    if not title:
        title = next(
            (line.lstrip("# ").strip() for line in frontmatter.body.splitlines() if line.startswith("# ")), identifier
        )
    common: dict[str, Any] = dict(id=identifier, status=status, title=title, sections=sections, source=text)
    if kind is ArtifactKind.GOAL:
        epic_section = _required(sections, ("epics",))
        if any(name in sections for name in ("stories", "tasks")):
            raise ArtifactContractError("a goal artifact may manage Epics only; Stories belong to EPIC.md")
        return GoalArtifact(**common, epic_ids=_ids(epic_section))
    if kind is ArtifactKind.EPIC:
        goal_id = values.get("goal_id")
        if not isinstance(goal_id, str) or not goal_id.strip():
            raise ArtifactContractError("epic frontmatter requires goal_id")
        story_section = _required(sections, ("stories",))
        return EpicArtifact(
            **common,
            goal_id=goal_id.strip(),
            goal=_required(sections, ("goal", "objective")),
            value=_required(sections, ("value",)),
            scope=_required(sections, ("scope",)),
            dependencies=_required(sections, ("dependencies", "依赖")),
            acceptance_criteria=_required(sections, ("acceptance criteria", "acceptance")),
            story_ids=_ids(story_section),
            definition_of_done=_required(sections, ("definition of done", "definition-of-done")),
        )
    epic_id = values.get("epic_id")
    if not isinstance(epic_id, str) or not epic_id.strip():
        raise ArtifactContractError("story frontmatter requires epic_id")
    goal_id = values.get("goal_id")
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise ArtifactContractError("story frontmatter requires goal_id")
    acceptance = _required(sections, ("acceptance criteria", "acceptance"))
    if not re.search(r"\bgiven\b.*\bwhen\b.*\bthen\b", acceptance, re.IGNORECASE | re.DOTALL):
        raise ArtifactContractError("acceptance criteria must contain Given/When/Then")
    return StoryArtifact(
        **common,
        goal_id=goal_id.strip(),
        epic_id=epic_id.strip(),
        user_story=_required(sections, ("user story",)),
        acceptance_criteria=acceptance,
        tasks=_required(sections, ("tasks",)),
        definition_of_done=_required(sections, ("definition of done", "definition-of-done")),
    )


def validate_hierarchy(artifacts: Iterable[Artifact]) -> None:
    """Validate unique IDs and Goal -> Epic -> Story references."""
    items = list(artifacts)
    by_id: dict[str, Artifact] = {}
    for artifact in items:
        if artifact.id in by_id:
            raise ArtifactContractError(f"duplicate id: {artifact.id}")
        by_id[artifact.id] = artifact
    for artifact in items:
        if isinstance(artifact, GoalArtifact):
            for epic_id in artifact.epic_ids:
                parent = by_id.get(epic_id)
                if not isinstance(parent, EpicArtifact) or parent.goal_id != artifact.id:
                    raise ArtifactContractError(f"invalid Goal -> Epic parent reference: {epic_id}")
        elif isinstance(artifact, EpicArtifact):
            parent = by_id.get(artifact.goal_id)
            if not isinstance(parent, GoalArtifact):
                raise ArtifactContractError(f"invalid Epic parent reference: {artifact.goal_id}")
            for story_id in artifact.story_ids:
                child = by_id.get(story_id)
                if (
                    not isinstance(child, StoryArtifact)
                    or child.epic_id != artifact.id
                    or child.goal_id != artifact.goal_id
                ):
                    raise ArtifactContractError(f"invalid Epic -> Story parent reference: {story_id}")
        elif isinstance(artifact, StoryArtifact):
            parent = by_id.get(artifact.epic_id)
            if not isinstance(parent, EpicArtifact) or parent.goal_id != artifact.goal_id:
                raise ArtifactContractError(f"invalid Story parent reference: {artifact.epic_id}")


def validate_sprint_status_path(
    path: str | Path, canonical_path: str | Path = "_bmad-output/sprint-status.yaml"
) -> Path:
    """Ensure status validation targets the one canonical, read-only status file."""
    actual = Path(path).expanduser().resolve()
    canonical = Path(canonical_path).expanduser().resolve()
    if actual != canonical or actual.name != "sprint-status.yaml":
        raise ArtifactContractError("sprint-status.yaml is the canonical and only status authority")
    return actual


assert_sprint_status_authority = validate_sprint_status_path
