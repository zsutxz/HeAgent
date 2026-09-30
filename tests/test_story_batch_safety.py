"""Conservative story batch declarations and restart decisions."""

from __future__ import annotations

import asyncio

import pytest

from heagent.engine.checkpoint import WorkflowCheckpointStore, WorkflowStatus
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.engine.workflow_runner import WorkflowGateError, WorkflowRunner, WorkflowStepResult, parse_story_list


def _workflow(limit: int = 3) -> WorkflowResource:
    return WorkflowResource(
        name="sample",
        instructions="",
        steps=[
            WorkflowStepResource(
                index=1,
                name="implement",
                instructions="run",
                story_loop="epics.md",
                max_parallel_stories=limit,
            )
        ],
    )


BASE = """## E1
### S-1 First
- depends_on: []
- parallel_group: group
- write_set: [src/a.py]
### S-2 Second
- depends_on: []
- parallel_group: group
- write_set: [src/b.py]
### S-3 Third
- depends_on: [S-1]
- parallel_group: group
- write_set: [src/c.py]
"""


def test_metadata_is_owned_by_story_heading() -> None:
    stories = parse_story_list(BASE)
    assert stories[0].write_set == ["src/a.py"]
    assert stories[2].depends_on == ["S-1"]
    assert stories[1].parallel_group == "group"
    assert parse_story_list("## E1\n- S-1 First\n- write_set: [src/a.py]")[0].write_set == []


@pytest.mark.asyncio
async def test_only_declared_disjoint_ready_stories_run_together() -> None:
    runner = WorkflowRunner(_workflow())
    active = 0
    peak = 0
    seen: list[str] = []
    events: list[tuple[str, dict]] = []

    async def callback(step, story):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        seen.append(story.id)
        await asyncio.sleep(0)
        active -= 1
        return WorkflowStepResult(output=story.id)

    def emit(kind, *, details=None):
        events.append((kind, details or {}))

    stories = parse_story_list(BASE)
    await runner.run_step(callback, stories=stories, emit=emit)
    assert seen == ["S-1"]
    assert peak == 1
    assert runner.state.story_batches["S-1"] == ["S-1"]
    assert next(data for kind, data in events if kind == "workflow_story_batch_decided")["selected"] == ["S-1"]
    await runner.run_step(callback, stories=stories)
    assert seen == ["S-1", "S-2"]
    await runner.run_step(callback, stories=stories)
    assert runner.done
    assert seen == ["S-1", "S-2", "S-3"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second",
    [
        "- write_set: [src/a.py]",
        "- write_set: [src/a.py/sub]",
        "- write_set: [src/../src/a.py]",
        "- write_set: [src\\a.py]",
        "- write_set: []",
        "- depends_on: [S-1]",
        "- parallel_group: different",
    ],
)
async def test_conflict_or_unknown_serializes(second: str) -> None:
    text = BASE.split("### S-3", maxsplit=1)[0].replace("- write_set: [src/b.py]", second)
    if second.startswith("- depends_on:"):
        text = text.replace("### S-2 Second\n- depends_on: []\n", "### S-2 Second\n")
    if second.startswith("- parallel_group:"):
        text = text.replace(
            "### S-2 Second\n- depends_on: []\n- parallel_group: group\n",
            "### S-2 Second\n- depends_on: []\n",
        )
    runner = WorkflowRunner(_workflow())
    seen: list[str] = []

    async def callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=story.id)

    await runner.run_step(callback, stories=parse_story_list(text))
    assert seen == ["S-1"]


@pytest.mark.asyncio
async def test_checkpoint_keeps_approved_batch_when_limit_grows(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_workflow(2), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = parse_story_list(BASE.replace("- depends_on: [S-1]", "- depends_on: []"))

    async def callback(step, story):
        return WorkflowStepResult(output=story.id)

    await runner.run_step(callback, stories=stories)
    checkpoint = (await store.list_checkpoints(goal_id="goal"))[-1]
    assert checkpoint.story_batches["S-1"] == ["S-1"]
    restored = WorkflowRunner.from_checkpoint(_workflow(3), checkpoint, checkpoint_store=store)
    assert restored.state.story_batches["S-1"] == ["S-1"]
    assert (await restored.run_step(callback, stories=stories)).status is WorkflowStatus.PENDING
    assert (await restored.run_step(callback, stories=stories)).status is WorkflowStatus.COMPLETED
    assert restored.state.completed_stories == ["S-1", "S-2", "S-3"]
    assert restored.done


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 3])
async def test_unknown_dependency_blocks_without_running(tmp_path, limit: int) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_workflow(limit), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = parse_story_list(BASE.replace("- depends_on: []", "- depends_on: [S-99]", 1))
    seen: list[str] = []

    async def callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=story.id)

    result = await runner.run_step(callback, stories=stories)
    assert result.status is WorkflowStatus.BLOCKED
    assert "dependencies" in result.reason
    assert seen == []


@pytest.mark.asyncio
async def test_pending_batch_restore_never_expands_when_limit_grows(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_workflow(2), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = parse_story_list(BASE.replace("- depends_on: [S-1]", "- depends_on: []"))
    seen: list[str] = []

    async def callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=story.id)

    pending_snapshots = []
    original_save = store.save

    async def capture_save(checkpoint, workflow_state=None):
        if checkpoint.active_stories:
            pending_snapshots.append(checkpoint.model_copy(deep=True))
        return await original_save(checkpoint, workflow_state)

    store.save = capture_save
    await runner.run_step(callback, stories=stories)
    assert seen == ["S-1"]
    pending = pending_snapshots[0]
    assert pending.story_batches["S-1"] == ["S-1"]
    restored = WorkflowRunner.from_checkpoint(_workflow(3), pending, checkpoint_store=store)
    seen.clear()
    await restored.run_step(callback, stories=stories)
    assert seen == ["S-1"]


def test_duplicate_dependency_declaration_fails_loud() -> None:
    with pytest.raises(WorkflowGateError, match="duplicate story declaration: depends_on"):
        parse_story_list(BASE.replace("- depends_on: []", "- depends_on: [S-99]\n- depends_on: []", 1))


@pytest.mark.asyncio
async def test_missing_epic_serial_path_still_enforces_dependencies() -> None:
    stories = parse_story_list("### S-1 First\n- depends_on: [S-99]\n### S-2 Second\n")
    runner = WorkflowRunner(_workflow(3))
    seen: list[str] = []

    async def callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=story.id)

    result = await runner.run_step(callback, stories=stories)
    assert result.status is WorkflowStatus.BLOCKED
    assert seen == []


@pytest.mark.asyncio
async def test_disjoint_declarations_cannot_overlap_shared_writer(tmp_path) -> None:
    """Actual callbacks may both write an undeclared single-writer artifact."""
    runner = WorkflowRunner(_workflow(3))
    stories = parse_story_list(BASE.replace("- depends_on: [S-1]", "- depends_on: []"))
    shared = tmp_path / "workflow.json"
    active = 0
    peak = 0

    async def callback(step, story):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        old = shared.read_text() if shared.exists() else ""
        await asyncio.sleep(0)
        shared.write_text(old + story.id + "\n", encoding="utf-8")
        active -= 1
        return WorkflowStepResult(output=story.id, evidence=[story.id])

    for _ in stories:
        await runner.run_step(callback, stories=stories)
    assert peak == 1
    assert shared.read_text(encoding="utf-8").splitlines() == ["S-1", "S-2", "S-3"]
    assert runner.state.acceptance_evidence == ["S-1", "S-2", "S-3"]
