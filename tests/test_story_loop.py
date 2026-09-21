"""Story-loop expansion for declarative workflow steps."""

from __future__ import annotations

import asyncio

import pytest

from heagent.engine.checkpoint import WorkflowCheckpointStore, WorkflowPhase, WorkflowStatus
from heagent.engine.workflow_runner import (
    StorySpec,
    WorkflowRunner,
    WorkflowStepResult,
    parse_story_list,
)
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.cli_goal import _goal_step_artifact_path

STORIES = [
    StorySpec(id="S-1", summary="Scene rendering"),
    StorySpec(id="S-2", summary="Movement"),
]

PARALLEL_STORIES = [
    StorySpec(id="S-1", summary="One", epic="E1"),
    StorySpec(id="S-2", summary="Two", epic="E1"),
    StorySpec(id="S-3", summary="Three", epic="E1"),
    StorySpec(id="S-4", summary="Other Epic", epic="E2"),
]


def _story_workflow(**step_kwargs: object) -> WorkflowResource:
    step = WorkflowStepResource(
        index=1,
        name="step-06-implement.md",
        instructions="implement",
        story_loop="epics.md",
        **step_kwargs,
    )
    return WorkflowResource(name="demo", instructions="", steps=[step])


def _parallel_workflow(limit: int = 2) -> WorkflowResource:
    return _story_workflow(max_parallel_stories=limit)


def _story_callback(seen: list[str | None]):
    async def callback(step, story):
        seen.append(story.id if story is not None else None)
        return WorkflowStepResult(output=f"impl {story.id}" if story is not None else "done")

    return callback


def test_parse_story_list_recognizes_heading_list_and_table() -> None:
    text = """
# Epic E-1

| E-1 | Space Duel MVP | S-1 ~ S-5 | playable round | P0 |

## Stories

- S-1 Scene rendering
- [ ] S-2: Movement

### S-3 Shooting

| S-4 | Life and win | |

（S-2 重复，去重）
"""
    stories = parse_story_list(text)
    assert [story.id for story in stories] == ["S-1", "S-2", "S-3", "S-4"]
    assert stories[0].summary == "Scene rendering"
    assert stories[1].summary == "Movement"
    assert stories[2].summary == "Shooting"
    assert stories[3].summary == "Life and win"


def test_parse_story_list_returns_empty_for_no_stories() -> None:
    assert parse_story_list("") == []
    assert parse_story_list("# Epic E-1\n\n| E-1 | title | value |") == []


@pytest.mark.asyncio
async def test_parallel_story_loop_batches_one_epic_and_keeps_epics_serial() -> None:
    runner = WorkflowRunner(_parallel_workflow(2))
    running = 0
    peak = 0
    seen: list[str] = []

    async def callback(step, story):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        seen.append(story.id)
        await asyncio.sleep(0.01)
        running -= 1
        return WorkflowStepResult(output=f"impl {story.id}")

    first = await runner.run_step(callback, stories=PARALLEL_STORIES)
    assert first.status is WorkflowStatus.PENDING
    assert peak == 2
    assert seen == ["S-1", "S-2"]
    second = await runner.run_step(callback, stories=PARALLEL_STORIES)
    assert second.status is WorkflowStatus.PENDING
    assert seen == ["S-1", "S-2", "S-3"]
    third = await runner.run_step(callback, stories=PARALLEL_STORIES)
    assert third.status is WorkflowStatus.COMPLETED
    assert seen == ["S-1", "S-2", "S-3", "S-4"]


@pytest.mark.asyncio
async def test_parallel_story_failure_isolated_and_checkpointed() -> None:
    runner = WorkflowRunner(_parallel_workflow(2))

    async def callback(step, story):
        if story.id == "S-2":
            raise RuntimeError("broken story")
        return WorkflowStepResult(output=f"impl {story.id}")

    result = await runner.run_step(callback, stories=PARALLEL_STORIES)
    assert result.status is WorkflowStatus.FAILED
    assert runner.state.story_statuses["S-1"] == "completed"
    assert runner.state.story_statuses["S-2"] == "failed"
    assert runner.state.story_outputs == {"S-1": "impl S-1"}


@pytest.mark.asyncio
async def test_parallel_story_checkpoint_restore_does_not_repeat_completed_batch(tmp_path) -> None:
    workflow = _parallel_workflow(2)
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)
    seen: list[str] = []

    async def callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=f"impl {story.id}")

    assert (await runner.run_step(callback, stories=PARALLEL_STORIES)).status is WorkflowStatus.PENDING
    checkpoint = (await store.list_checkpoints(goal_id="goal"))[-1]
    assert checkpoint.completed_stories == ["S-1", "S-2"]
    assert checkpoint.story_statuses["S-1"] == "completed"
    restored = WorkflowRunner.from_checkpoint(workflow, checkpoint, checkpoint_store=store)
    assert (await restored.run_step(callback, stories=PARALLEL_STORIES)).status is WorkflowStatus.PENDING
    assert seen == ["S-1", "S-2", "S-3"]


@pytest.mark.asyncio
async def test_story_loop_executes_one_story_per_call_and_combines_outputs() -> None:
    runner = WorkflowRunner(_story_workflow())
    seen: list[str | None] = []
    callback = _story_callback(seen)

    first = await runner.run_step(callback, stories=STORIES)
    assert first.status is WorkflowStatus.PENDING
    assert first.story_id == "S-1"
    assert first.story_index == 0
    assert seen == ["S-1"]
    assert runner.state.active_step == 0
    assert runner.state.story_index == 1

    second = await runner.run_step(callback, stories=STORIES)
    assert second.status is WorkflowStatus.COMPLETED
    assert second.story_id == "S-2"
    assert seen == ["S-1", "S-2"]
    assert runner.done
    assert runner.state.outputs["step-06-implement.md"] == "impl S-1\n\n---\n\nimpl S-2"


@pytest.mark.asyncio
async def test_story_loop_checkpoint_waits_between_stories() -> None:
    workflow = _story_workflow(checkpoint="user")
    runner = WorkflowRunner(workflow)
    seen: list[str | None] = []

    first = await runner.run_step(_story_callback(seen), stories=STORIES)
    assert first.status is WorkflowStatus.WAITING_USER
    assert first.story_id == "S-1"
    assert runner.state.active_step == 0
    assert runner.state.story_index == 1

    runner.resume()
    second = await runner.run_step(_story_callback(seen), stories=STORIES)
    assert second.status is WorkflowStatus.COMPLETED
    assert runner.done


@pytest.mark.asyncio
async def test_story_loop_persists_and_restores_story_progress(tmp_path) -> None:
    workflow = _story_workflow(checkpoint="user")
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    first = await runner.run_step(_story_callback([]), stories=STORIES)
    assert first.status is WorkflowStatus.WAITING_USER

    checkpoints = await store.list_checkpoints(goal_id="goal")
    checkpoint = checkpoints[-1]
    assert checkpoint.story_index == 1
    assert checkpoint.completed_stories == ["S-1"]
    assert checkpoint.active_story == "S-2"
    assert checkpoint.story_outputs == {"S-1": "impl S-1"}
    assert "story-1" in checkpoint.checkpoint_id

    restored = WorkflowRunner.from_checkpoint(workflow, checkpoint, checkpoint_store=store)
    assert restored.state.story_index == 1
    assert restored.state.completed_stories == ["S-1"]
    assert restored.state.active_story == "S-2"
    assert restored.state.story_outputs == {"S-1": "impl S-1"}

    restored.resume()
    second = await restored.run_step(_story_callback([]), stories=STORIES)
    assert second.status is WorkflowStatus.COMPLETED
    assert restored.state.outputs["step-06-implement.md"] == "impl S-1\n\n---\n\nimpl S-2"


@pytest.mark.asyncio
async def test_story_loop_requires_a_story_list() -> None:
    runner = WorkflowRunner(_story_workflow())

    result = await runner.run_step(_story_callback([]), stories=None)
    assert result.status is WorkflowStatus.BLOCKED
    assert "requires a story list" in result.reason

    result = await runner.run_step(_story_callback([]), stories=[])
    assert result.status is WorkflowStatus.BLOCKED


@pytest.mark.asyncio
async def test_story_loop_rejects_single_argument_callback() -> None:
    runner = WorkflowRunner(_story_workflow())

    def bad_callback(step):
        return WorkflowStepResult(output="x")

    with pytest.raises(TypeError, match="must accept"):
        await runner.run_step(bad_callback, stories=STORIES)


@pytest.mark.asyncio
async def test_non_story_step_checkpoint_id_is_unchanged(tmp_path) -> None:
    workflow = WorkflowResource(
        name="demo",
        instructions="",
        steps=[
            WorkflowStepResource(index=1, name="step-01.md", instructions="", checkpoint="user"),
            WorkflowStepResource(index=2, name="step-02.md", instructions=""),
        ],
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    assert (await runner.run_step(lambda _: WorkflowStepResult(output="ok"))).status is WorkflowStatus.WAITING_USER
    runner.resume()
    await runner.persist_state()

    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert any(c.checkpoint_id == "goal-run-step-2-active-1-pending" for c in checkpoints)


@pytest.mark.asyncio
async def test_story_loop_interruption_keeps_active_story(tmp_path) -> None:
    workflow = _story_workflow()
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    async def interrupt(step, story):
        return WorkflowStepResult(status=WorkflowStatus.WAITING_USER, reason="interrupted")

    result = await runner.run_step(interrupt, stories=STORIES)
    assert result.status is WorkflowStatus.WAITING_USER

    checkpoint = (await store.list_checkpoints(goal_id="goal"))[-1]
    assert checkpoint.active_story == "S-1"
    assert checkpoint.story_index == 0
    assert checkpoint.completed_stories == []

    runner.resume()
    result = await runner.run_step(_story_callback([]), stories=STORIES)
    assert result.story_id == "S-1"


@pytest.mark.asyncio
async def test_story_loop_resume_does_not_conflict_with_previous_step_advance(tmp_path) -> None:
    """A resumed story and an unentered story may not share one checkpoint id.

    Regression: advancing into a story-loop step writes a pending snapshot for
    ``(step, story_index=0)`` with no active story. Resuming an interrupted first
    story then re-issued the very same id carrying ``active_story="S-1"``, so the
    store rejected the write as a bogus conflict and ``/goal resume`` failed.
    """
    workflow = WorkflowResource(
        name="demo",
        instructions="",
        steps=[
            WorkflowStepResource(index=1, name="step-01.md", instructions="", checkpoint="user"),
            WorkflowStepResource(index=2, name="step-02.md", instructions="", story_loop="epics.md", checkpoint="user"),
        ],
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    assert (await runner.run_step(lambda _: WorkflowStepResult(output="ok"))).status is WorkflowStatus.WAITING_USER
    runner.resume()
    await runner.persist_state()  # step-02 entered, no story started yet

    async def interrupt(step, story):
        return WorkflowStepResult(status=WorkflowStatus.WAITING_USER, reason="interrupted")

    interrupted = await runner.run_step(interrupt, stories=STORIES)
    assert interrupted.status is WorkflowStatus.WAITING_USER

    runner.resume()
    await runner.persist_state()  # must not raise WorkflowCheckpointError

    checkpoints = await store.list_checkpoints(goal_id="goal")
    ids = {checkpoint.checkpoint_id for checkpoint in checkpoints}
    assert "goal-run-step-2-story-0-S-1-active-1-waiting_user" in ids
    assert "goal-run-step-2-story-0-S-1-active-1-pending" in ids
    assert "goal-run-step-2-story-0-active-1-pending" in ids
    restored = WorkflowRunner.from_checkpoint(workflow, checkpoints[-1], checkpoint_store=store)
    assert restored.state.active_story == "S-1"
    assert restored.state.story_index == 0


def test_story_artifact_routes_into_per_story_subdirectory(tmp_path) -> None:
    step = WorkflowStepResource(index=6, name="step-06-implement-and-verify.md", instructions="")
    story = StorySpec(id="S-1", summary="Scene rendering")

    story_path = _goal_step_artifact_path(tmp_path, step, story)
    assert story_path == tmp_path / "step-06-implement-and-verify" / "s-1" / "report.md"

    # 非 story step 仍平铺在 goal 根目录（向后兼容）
    plain_path = _goal_step_artifact_path(tmp_path, step)
    assert plain_path == tmp_path / "step-06-implement-and-verify.md"


def test_parse_story_list_keeps_the_flat_shape_without_epic_grouping() -> None:
    """Sources without grouping must keep the pre-Epic behaviour (epic stays empty)."""
    stories = parse_story_list("- [ ] S-1 Scene rendering\n- [ ] S-2 Input routing\n")
    assert [(story.id, story.epic) for story in stories] == [("S-1", ""), ("S-2", "")]


def test_parse_story_list_groups_stories_by_epic_heading() -> None:
    text = """# 02-epics.md - plan

## E1 Core engine

### S-1 Skeleton

## Epic 2: Loop

### S-2 Input routing
"""
    stories = parse_story_list(text)
    assert [(story.id, story.epic) for story in stories] == [("S-1", "E1"), ("S-2", "E2")]


def test_parse_story_list_prefers_explicit_parent_epic_field() -> None:
    text = """## E1 Core engine

### S-1 Skeleton
- **父 Epic**: E3
- **优先级**: P0

### S-2 Input routing
- **父 Epic**: E3
"""
    stories = parse_story_list(text)
    assert [(story.id, story.epic) for story in stories] == [("S-1", "E3"), ("S-2", "E3")]


def test_parse_story_list_ignores_numeric_and_sprint_headings() -> None:
    """A document title, a sprint heading and a table row's 父 Epic mention are not grouping."""
    text = """# 02-epics.md - plan

## Sprint Plan

### Sprint 1 - first

- S-1 Skeleton
- S-2 Input routing
"""
    assert [story.epic for story in parse_story_list(text)] == ["", ""]
    table = """## E2 Loop

| S-3 | Input routing | 父 Epic: E9 |
"""
    assert [(story.id, story.epic) for story in parse_story_list(table)] == [("S-3", "E2")]


def test_story_artifact_routes_into_epic_subdirectory(tmp_path) -> None:
    """A story with Epic grouping lands in <step-dir>/epic-<eN>/s-<n>/report.md."""
    step = WorkflowStepResource(index=7, name="step-07-implement-story.md", instructions="")

    grouped = _goal_step_artifact_path(tmp_path, step, StorySpec(id="S-3", summary="x", epic="E3"))
    assert grouped == tmp_path / "step-07-implement-story" / "epic-e3" / "s-3" / "report.md"

    # 无 Epic 分组时保持平铺（向后兼容既有 goal 的产物布局）
    flat = _goal_step_artifact_path(tmp_path, step, StorySpec(id="S-3", summary="x"))
    assert flat == tmp_path / "step-07-implement-story" / "s-3" / "report.md"
