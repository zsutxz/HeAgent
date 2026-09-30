"""Story 51-7：脚本声明的后续步骤计划必须**可确定恢复**（进程重启后按同一选择继续）。

只测引擎面（Runner + checkpoint），不经 CLI：这条判据锚的是「计划是不是真的落盘了」，
而不是入口层的渲染。合成 workflow 无 story / 无 approval，回调是纯 stub——不需要 provider。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from heagent.engine import (
    WorkflowCheckpointStore,
    WorkflowRunner,
    WorkflowStatus,
    WorkflowStepResource,
    WorkflowStepResult,
    WorkflowResource,
)


def _workflow() -> WorkflowResource:
    return WorkflowResource(
        name="demo",
        instructions="",
        steps=[
            WorkflowStepResource(index=index, name=f"step-0{index}-s{index}.md", instructions="") for index in (1, 2, 3)
        ],
    )


@pytest.mark.asyncio
async def test_declared_plan_survives_a_restart(tmp_path: Path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    workflow = _workflow()
    runner = WorkflowRunner(workflow, goal_id="g1", run_id="r1", checkpoint_store=store)
    calls: list[str] = []

    async def callback(step: Any, story: Any = None) -> WorkflowStepResult:
        calls.append(step.name)
        if step.name == "step-01-s1.md":
            # 脚本选择**跳过** step 2、直接跑 step 3（条件分支的最小形态）。
            return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output="one", requested_steps=["step-03-s3.md"])
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output=step.name)

    first = await runner.run_step(callback)
    assert calls == ["step-01-s1.md"]
    assert first.requested_steps == ["step-03-s3.md"]

    # 「进程重启」：只用磁盘上的快照恢复，内存计划必须能原样取回。
    checkpoints = await store.list_checkpoints(goal_id="g1")
    assert checkpoints, "unstep must have persisted a checkpoint"
    restored = WorkflowRunner.from_checkpoint(workflow, checkpoints[0], checkpoint_store=store)
    assert restored.state.requested_steps == ["step-03-s3.md"]
    assert restored.state.completed_steps == [0]

    follow = await restored.run_declared_step("step-03-s3.md", callback)
    assert follow.status is WorkflowStatus.COMPLETED
    assert calls == ["step-01-s1.md", "step-03-s3.md"]
    # 计划被消费：同一请求不会被重复提交。
    assert restored.state.requested_steps == []
    assert restored.state.completed_steps == [0, 2]


@pytest.mark.asyncio
async def test_repeated_declared_step_is_skipped_without_rerunning(tmp_path: Path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    workflow = _workflow()
    runner = WorkflowRunner(workflow, goal_id="g2", run_id="r2", checkpoint_store=store)
    calls: list[str] = []

    async def callback(step: Any, story: Any = None) -> WorkflowStepResult:
        calls.append(step.name)
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output=step.name)

    await runner.run_step(callback)
    runner.state = runner.state.model_copy(update={"requested_steps": ["step-03-s3.md", "step-03-s3.md"]})

    await runner.run_declared_step("step-03-s3.md", callback)
    skipped = await runner.run_declared_step("step-03-s3.md", callback)

    assert skipped.skipped is True
    assert calls == ["step-01-s1.md", "step-03-s3.md"]  # 第二次没有重跑
    assert runner.state.requested_steps == []
