"""Fail-closed story scheduling declarations."""

from __future__ import annotations

import asyncio

import pytest

from heagent.engine.checkpoint import WorkflowCheckpointStore, WorkflowStatus
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.engine.workflow_runner import WorkflowGateError, WorkflowRunner, WorkflowStepResult
from heagent.goal.workflow_loader import parse_story_list


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
async def test_declared_disjoint_stories_run_parallel_and_checkpointed(tmp_path) -> None:
    """52-2 语义翻转：写集不相交 + 同组 + 依赖已完成 + 三参契约 ⇒ 真实并发（峰值 2）。

    S-3 依赖 S-1（依赖批内成员不可证安全）⇒ 批止步 [S-1, S-2]，S-3 串行收尾。
    """
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_workflow(), goal_id="goal", run_id="run", checkpoint_store=store)
    active = 0
    peak = 0
    seen: list[str] = []

    async def callback(step, story, execution=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        seen.append(story.id)
        await asyncio.sleep(0.01)
        active -= 1
        return WorkflowStepResult(output=story.id)

    stories = parse_story_list(BASE)
    while not runner.done:
        await runner.run_step(callback, stories=stories)

    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert peak == 2
    assert seen == ["S-1", "S-2", "S-3"]
    # 快照链：S-1、S-2 各一条 RUNNING 中间快照 → 批终态（PENDING）→ S-3 串行收口（簿记清场）。
    assert [checkpoint.completed_stories for checkpoint in checkpoints] == [
        ["S-1"],
        ["S-1", "S-2"],
        ["S-1", "S-2"],
        [],
    ]
    assert checkpoints[-1].completed_steps == [0]
    assert checkpoints[-1].outputs["implement"] == "S-1\n\n---\n\nS-2\n\n---\n\nS-3"
    assert runner.done


@pytest.mark.asyncio
async def test_unknown_dependency_blocks_without_running() -> None:
    runner = WorkflowRunner(_workflow())
    stories = parse_story_list(BASE.replace("- depends_on: []", "- depends_on: [S-99]", 1))
    seen: list[str] = []

    async def callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=story.id)

    result = await runner.run_step(callback, stories=stories)
    assert result.status is WorkflowStatus.BLOCKED
    assert "dependencies" in result.reason
    assert seen == []


def test_duplicate_dependency_declaration_fails_loud() -> None:
    with pytest.raises(WorkflowGateError, match="duplicate story declaration: depends_on"):
        parse_story_list(BASE.replace("- depends_on: []", "- depends_on: [S-99]\n- depends_on: []", 1))


@pytest.mark.asyncio
async def test_legacy_two_param_callback_cannot_overlap_shared_writer(tmp_path) -> None:
    """老回调（两参）未实现围栏+审计契约 ⇒ fail-closed 串行（Epic 52 授权条件 3 的反例锚点）。

    47-9 时代本用例论证「声明不能授权并发」；52 起并发授权由三参契约 + 围栏 + 审批链
    承担，本用例保留为「未实现契约者不得并发」的共享写者语义锁定。
    """
    runner = WorkflowRunner(_workflow())
    stories = parse_story_list(BASE.replace("- depends_on: [S-1]", "- depends_on: []"))
    shared = tmp_path / "workflow.json"

    async def callback(step, story):
        old = shared.read_text() if shared.exists() else ""
        await asyncio.sleep(0)
        shared.write_text(old + story.id + "\n", encoding="utf-8")
        return WorkflowStepResult(output=story.id, evidence=[story.id])

    for _ in stories:
        await runner.run_step(callback, stories=stories)
    assert shared.read_text(encoding="utf-8").splitlines() == ["S-1", "S-2", "S-3"]
    assert runner.state.acceptance_evidence == ["S-1", "S-2", "S-3"]
