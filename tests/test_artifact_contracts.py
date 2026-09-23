from pathlib import Path

import pytest

from heagent.engine.artifacts import (
    ArtifactContractError,
    ArtifactKind,
    parse_artifact,
    parse_frontmatter,
    validate_hierarchy,
    validate_sprint_status_path,
)


GOAL = """---
id: goal-1
type: goal
status: planning
---
# Goal

## Epics
- epic-1: Example
"""

EPIC = """---
id: epic-1
type: epic
goal_id: goal-1
status: planning
---
# Example Epic

## Goal
Ship the feature.
## Value
Users can use it.
## Scope
Included.
## Dependencies
None.
## Acceptance Criteria
- It works.
## Stories
- story-1: Example story
## Definition of Done
- Tests pass.
"""

STORY = """---
id: story-1
type: story
epic_id: epic-1
goal_id: goal-1
status: ready-for-dev
---
# Example story

## User Story
As a user, I want a feature, so I get value.
## Acceptance Criteria
- Given a user, when they act, then it works.
## Tasks
- [ ] Implement it.
## Definition of Done
- Tests pass.
"""


def test_valid_hierarchy_and_frontmatter() -> None:
    assert parse_frontmatter(STORY).values["id"] == "story-1"
    assert parse_artifact(GOAL).kind is ArtifactKind.GOAL
    validate_hierarchy([parse_artifact(GOAL), parse_artifact(EPIC), parse_artifact(STORY)])


def test_bom_prefixed_artifact_parses_like_plain() -> None:
    """文件头 UTF-8 BOM 的 artifacts：此前 loud 拒绝（requires frontmatter），现按同一契约解析。

    钉住这条**行为变更**（2026-09-23 frontmatter 层 BOM 容忍的下游表现）：消费者侧不再
    因 BOM 拒收，且 frontmatter/正文与无 BOM 版本完全一致。
    """
    parsed = parse_frontmatter("\ufeff" + STORY)

    assert parsed.values == parse_frontmatter(STORY).values
    assert parsed.body == parse_frontmatter(STORY).body
    assert parse_artifact("\ufeff" + STORY).kind is ArtifactKind.STORY


def test_missing_section_and_tbd_fail_loudly() -> None:
    with pytest.raises(ArtifactContractError, match="Definition of Done"):
        parse_artifact(EPIC.replace("## Definition of Done", "## Done"))
    with pytest.raises(ArtifactContractError, match="TBD"):
        parse_artifact(STORY.replace("Implement it", "TBD"))


def test_duplicate_id_and_wrong_parent_fail() -> None:
    duplicate = EPIC.replace("epic-1", "goal-1")
    with pytest.raises(ArtifactContractError, match="duplicate id"):
        validate_hierarchy([parse_artifact(GOAL), parse_artifact(duplicate)])
    wrong = STORY.replace("epic-1", "epic-404")
    with pytest.raises(ArtifactContractError, match="parent"):
        validate_hierarchy([parse_artifact(GOAL), parse_artifact(EPIC), parse_artifact(wrong)])

    wrong_goal = STORY.replace("goal_id: goal-1", "goal_id: goal-404")
    with pytest.raises(ArtifactContractError, match="parent"):
        validate_hierarchy([parse_artifact(GOAL), parse_artifact(EPIC), parse_artifact(wrong_goal)])


def test_sprint_status_is_single_authority(tmp_path: Path) -> None:
    canonical = tmp_path / "_bmad-output" / "sprint-status.yaml"
    canonical.parent.mkdir()
    canonical.write_text("development_status:\n  epic-1: planning\n", encoding="utf-8")
    assert validate_sprint_status_path(canonical, canonical) == canonical.resolve()
    with pytest.raises(ArtifactContractError, match="唯一|canonical"):
        validate_sprint_status_path(canonical.parent / "other.yaml", canonical)
