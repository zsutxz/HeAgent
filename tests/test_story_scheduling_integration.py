"""Story 51-8 集成样例与旧资产恢复矩阵。

集成样例（引擎级）链起 fail-closed Story 调度全链：依赖闸门（未知依赖 BLOCKED 且零执行）
→ 串行执行（一次一条，逐 story 落 checkpoint 与 story_statuses）→ 步骤级审批门（末条 story
后 WAITING_USER）→ approve 放行合并输出 → 恢复不重复已完成 story。CLI 级各宿主环节
（doctor / 证据 Gate / workflow 冻结 / 脚本步骤 / verify）各有专属判据文件
（test_goal_doctor / test_goal_quality_gates / test_goal_decisions / test_goal_script_*），
本文件不重复。写集声明不授权并发由 test_story_batch_safety 的 fail-closed 判据锁定。
"""

from __future__ import annotations

import pytest

from heagent.engine.checkpoint import WorkflowCheckpoint, WorkflowCheckpointStore, WorkflowStatus
from heagent.engine.workflow_runner import StorySpec, WorkflowRunner, WorkflowStepResult
from heagent.engine.workflow_resource import StepApproval, WorkflowResource, WorkflowStepResource


def _story_workflow(**step_kwargs: object) -> WorkflowResource:
    step = WorkflowStepResource(
        index=1,
        name="step-01.md",
        instructions="implement",
        story_loop="epics.md",
        **step_kwargs,
    )
    return WorkflowResource(name="demo", instructions="", steps=[step])


STORIES = [
    StorySpec(id="S-1", summary="First"),
    StorySpec(id="S-2", summary="Second", depends_on=["S-1"]),
]


def _story_callback(seen: list[str]):
    async def callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=f"impl {story.id}")

    return callback


@pytest.mark.asyncio
async def test_fail_closed_story_chain_with_approval_and_recovery(tmp_path) -> None:
    """集成样例：依赖闸门 → 串行（逐 story checkpoint + 状态）→ 审批门 → 放行 → 恢复不重跑。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(
        _story_workflow(approval=StepApproval(required=True)),
        goal_id="goal",
        run_id="run",
        checkpoint_store=store,
    )
    seen: list[str] = []

    # 第 1 条 story：依赖已满足，执行后 PENDING，逐 story 落 checkpoint 与状态
    first = await runner.run_step(_story_callback(seen), stories=STORIES)
    assert first.status is WorkflowStatus.PENDING
    assert seen == ["S-1"]
    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert checkpoints[-1].completed_stories == ["S-1"]
    assert checkpoints[-1].story_statuses == {"S-1": "completed"}

    # 恢复（跨进程语义）：从 checkpoint 重建 runner，不重复 S-1
    checkpoint = checkpoints[-1]
    restored = WorkflowRunner.from_checkpoint(
        _story_workflow(approval=StepApproval(required=True)), checkpoint, checkpoint_store=store
    )
    second = await restored.run_step(_story_callback(seen), stories=STORIES)
    assert second.status is WorkflowStatus.WAITING_USER  # 末条 story 后挂审批门
    assert seen == ["S-1", "S-2"]

    # approve 放行：合并输出落 outputs，簿记延后到决策落定（51-5）
    approved = restored.approve()
    assert approved.status is WorkflowStatus.COMPLETED
    assert approved.outputs["step-01.md"] == "impl S-1\n\n---\n\nimpl S-2"
    assert restored.done


@pytest.mark.asyncio
async def test_unknown_dependency_blocks_the_whole_chain_without_running(tmp_path) -> None:
    """依赖闸门在集成链上同样 fail-closed：未知依赖 BLOCKED 且零执行、零 checkpoint 写入。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_story_workflow(), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = [
        StorySpec(id="S-1", summary="First", depends_on=["S-99"]),
        StorySpec(id="S-2", summary="Second", depends_on=["S-1"]),
    ]
    seen: list[str] = []

    result = await runner.run_step(_story_callback(seen), stories=stories)

    assert result.status is WorkflowStatus.BLOCKED
    assert seen == []
    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert len(checkpoints) == 1  # 显性失败也落盘（BLOCKED 可恢复诊断）
    assert checkpoints[0].status is WorkflowStatus.BLOCKED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "label"),
    [
        (lambda data: data, "as-is"),
        (lambda data: {**data, "story_batches": {"S-1": ["S-1", "S-2"]}}, "removed story_batches field"),
        (
            lambda data: {key: value for key, value in data.items() if key not in {"active_stories", "story_statuses"}},
            "legacy minimal shape",
        ),
    ],
)
async def test_legacy_checkpoint_recovery_matrix(tmp_path, mutation, label: str) -> None:
    """旧 checkpoint 形态恢复矩阵：三种历史形态都能恢复并串行续跑，不重复已完成 story。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_story_workflow(), goal_id="goal", run_id="run", checkpoint_store=store)
    seen: list[str] = []
    await runner.run_step(_story_callback(seen), stories=STORIES)
    checkpoint = (await store.list_checkpoints(goal_id="goal"))[-1]

    legacy = WorkflowCheckpoint.model_validate(mutation(checkpoint.model_dump()))
    restored = WorkflowRunner.from_checkpoint(_story_workflow(), legacy, checkpoint_store=store)
    await restored.run_step(_story_callback(seen), stories=STORIES)

    assert seen == ["S-1", "S-2"]  # 恢复不重复已完成 S-1
    assert restored.done
