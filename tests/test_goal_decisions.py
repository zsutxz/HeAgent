"""Story 51-5：步骤级审批与决策记录的契约。

四组判据：声明门（runner 只认 ``approval:`` 声明，``src/`` 无步骤名 / 序号判断）、
决策事件语义（approve / reject / amend / resume 互不顶替）、追加式决策日志（重跑不覆盖
历史）、应用服务与 CLI（resume 不等于 approve、cron 不自动批准人工 Gate）。

负向验证锚点（变异即红）：

- 把 resume 当 approve 用：``test_resume_at_an_approval_gate_is_refused`` /
  ``test_resume_via_pause_resume_cannot_approve`` / CLI 版 ``test_goal_resume_at_the_gate_*``；
- cron 自动批准：``test_auto_advance_never_approves_the_gate``；
- 历史被覆盖：``test_decision_store_refuses_to_overwrite_the_same_id`` /
  ``test_history_survives_reject_rerun_and_a_second_decision``。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import heagent.cli.goal as cli_goal
import heagent.goal.application as goal_application
import heagent.goal.mutex as goal_mutex
from heagent.cli.goal import _goal_declarative_runner, _goal_declarative_workflow, _goal_runner
from heagent.engine.checkpoint import (
    WorkflowCheckpoint,
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    WorkflowStatus,
)
from heagent.engine.workflow_resource import StepApproval, WorkflowResource, WorkflowStepResource
from heagent.engine.workflow_runner import StorySpec, WorkflowGateError, WorkflowRunner, WorkflowStepResult
from heagent.goal.application import (
    DecisionStatus,
    GoalAdvanceStatus,
    PauseResumeStatus,
    _GoalAdvanceContext,
    advance,
    checkpoint_store,
    pause_resume,
    record_decision,
    restore_runner,
)
from heagent.goal.decisions import (
    DECISION_SCHEMA_VERSION,
    DecisionAction,
    DecisionError,
    DecisionRecord,
    DecisionStore,
    decision_store,
    new_decision_id,
)


def _workflow(*steps: WorkflowStepResource) -> WorkflowResource:
    return WorkflowResource(name="demo", instructions="", steps=list(steps))


def _approval_step(index: int = 1, **kwargs: object) -> WorkflowStepResource:
    return WorkflowStepResource(
        index=index, name=f"step-{index:02d}.md", instructions="", approval=StepApproval(required=True), **kwargs
    )


def _plain_step(index: int = 1, **kwargs: object) -> WorkflowStepResource:
    return WorkflowStepResource(index=index, name=f"step-{index:02d}.md", instructions="", **kwargs)


async def _complete(_step, *_rest):  # noqa: ANN001, ANN202 - 测试回调形状由 run_step 契约固定
    return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output="out")


async def _refuse_execution(_inputs, _step, _story=None):
    raise AssertionError("a gated step must not re-execute while it awaits a decision")


async def _gate_runner(workflow: WorkflowResource, goal_dir: Path | None = None) -> WorkflowRunner:
    """把 runner 推进到审批门挂起（带 checkpoint store 时同时落盘）。"""
    runner = WorkflowRunner(
        workflow,
        goal_id=goal_dir.name if goal_dir is not None else None,
        checkpoint_store=checkpoint_store(goal_dir) if goal_dir is not None else None,
    )
    await runner.run_step(_complete)
    assert runner.state.awaiting_approval is True
    return runner


def _brief(goal_dir: Path) -> Path:
    document = goal_dir / "brief.md"
    document.write_text(
        "---\nid: goal-demo\ntype: requirement\ntitle: demo\n---\n\n## 原始需求（Original Request）\n\nship it\n",
        encoding="utf-8",
    )
    return document


# ---- runner：审批门挂起与三种决策 -----------------------------------------------


@pytest.mark.asyncio
async def test_approval_gated_step_waits_without_completing() -> None:
    """声明 ``approval: required`` 的步骤做完工作后挂起：状态 WAITING_USER、步骤未标记完成。"""
    runner = WorkflowRunner(_workflow(_approval_step(), _plain_step(2)))

    result = await runner.run_step(_complete)

    assert result.status is WorkflowStatus.WAITING_USER
    assert runner.state.status is WorkflowStatus.WAITING_USER
    assert runner.state.awaiting_approval is True
    assert runner.state.completed_steps == []
    assert runner.state.active_step == 0
    assert runner.state.pending_output == "out"


@pytest.mark.asyncio
async def test_step_without_approval_declaration_completes_as_before() -> None:
    """未声明的步骤零行为变化：直接完成并推进。"""
    runner = WorkflowRunner(_workflow(_plain_step(), _plain_step(2)))

    result = await runner.run_step(_complete)

    assert result.status is WorkflowStatus.PENDING
    assert runner.state.awaiting_approval is False
    assert runner.state.completed_steps == [0]


@pytest.mark.asyncio
async def test_approve_completes_the_step_and_advances() -> None:
    """approve 是唯一把挂起步骤标记完成的路径；产物来自挂起期间保存的输出。"""
    runner = await _gate_runner(_workflow(_approval_step(), _plain_step(2)))

    runner.approve()

    assert runner.state.status is WorkflowStatus.PENDING
    assert runner.state.awaiting_approval is False
    assert runner.state.pending_output is None
    assert runner.state.completed_steps == [0]
    assert runner.state.active_step == 1
    assert runner.state.outputs["step-01.md"] == "out"


@pytest.mark.asyncio
async def test_approve_on_the_final_step_completes_the_workflow() -> None:
    runner = await _gate_runner(_workflow(_approval_step()))

    runner.approve()

    assert runner.state.status is WorkflowStatus.COMPLETED
    assert runner.state.completed_steps == [0]


@pytest.mark.asyncio
async def test_approve_without_a_gate_fails_loudly() -> None:
    runner = WorkflowRunner(_workflow(_plain_step()))

    with pytest.raises(WorkflowGateError, match="no step is awaiting an approval decision"):
        runner.approve()


@pytest.mark.asyncio
async def test_reject_blocks_the_step_without_completing_it() -> None:
    """reject 驳回工作：落 BLOCKED、理由进状态，步骤保持未完成。"""
    runner = await _gate_runner(_workflow(_approval_step(), _plain_step(2)))

    runner.reject("验收标准不可判定")

    assert runner.state.status is WorkflowStatus.BLOCKED
    assert runner.state.reason == "验收标准不可判定"
    assert runner.state.awaiting_approval is False
    assert runner.state.pending_output is None
    assert runner.state.completed_steps == []
    assert runner.state.active_step == 0


@pytest.mark.asyncio
async def test_rejected_step_is_redone_after_resume_and_gates_again() -> None:
    """拒绝后重跑：resume 恢复执行同一步，重做完再次挂起等决策（不跳过门）。"""
    runner = await _gate_runner(_workflow(_approval_step(), _plain_step(2)))
    runner.reject("验收标准不可判定")

    runner.resume()
    result = await runner.run_step(_complete)

    assert result.status is WorkflowStatus.WAITING_USER
    assert runner.state.awaiting_approval is True
    assert runner.state.completed_steps == []
    runner.approve()
    assert runner.state.completed_steps == [0]


@pytest.mark.asyncio
async def test_amend_returns_to_pending_without_completing() -> None:
    """amend 带补充重跑：落 PENDING、步骤未完成，下一条 next/run 即重做。"""
    runner = await _gate_runner(_workflow(_approval_step(), _plain_step(2)))

    runner.amend("请补充成本估算")

    assert runner.state.status is WorkflowStatus.PENDING
    assert runner.state.awaiting_approval is False
    assert runner.state.pending_output is None
    assert runner.state.completed_steps == []
    result = await runner.run_step(_complete)
    assert result.status is WorkflowStatus.WAITING_USER


@pytest.mark.asyncio
async def test_resume_at_an_approval_gate_is_refused() -> None:
    """负向验证（resume 当 approve 即红）：审批门挂起时 resume 显性拒绝、状态不动。"""
    runner = await _gate_runner(_workflow(_approval_step(), _plain_step(2)))

    with pytest.raises(WorkflowGateError, match="resume does not approve it"):
        runner.resume()

    assert runner.state.status is WorkflowStatus.WAITING_USER
    assert runner.state.awaiting_approval is True
    assert runner.state.completed_steps == []


@pytest.mark.asyncio
async def test_story_loop_step_gates_after_its_last_story() -> None:
    """story-loop 步骤的审批门在末条 Story 之后挂起；挂起时 story 簿记已复位。"""
    step = _approval_step(story_loop="stories")
    runner = WorkflowRunner(_workflow(step, _plain_step(2)))
    stories = [StorySpec(id="S-1"), StorySpec(id="S-2")]

    await runner.run_step(_complete, stories=stories)
    assert runner.state.status is WorkflowStatus.PENDING
    assert runner.state.completed_stories == ["S-1"]

    await runner.run_step(_complete, stories=stories)
    assert runner.state.status is WorkflowStatus.WAITING_USER
    assert runner.state.awaiting_approval is True
    assert runner.state.completed_steps == []
    assert runner.state.completed_stories == []

    runner.approve()
    assert runner.state.completed_steps == [0]
    assert runner.state.outputs["step-01.md"]


@pytest.mark.asyncio
async def test_gate_state_survives_a_checkpoint_roundtrip(tmp_path: Path) -> None:
    """审批门挂起跨进程可恢复：awaiting_approval 与挂起产物都进 checkpoint。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_workflow(_approval_step(), _plain_step(2)), goal_id="goal", checkpoint_store=store)

    await runner.run_step(_complete)

    checkpoint = await store.load_latest_unfinished("goal")
    assert checkpoint is not None and checkpoint.awaiting_approval is True
    restored = WorkflowRunner.from_checkpoint(_workflow(_approval_step(), _plain_step(2)), checkpoint)
    assert restored.state.awaiting_approval is True
    assert restored.state.pending_output == "out"
    restored.approve()
    assert restored.state.completed_steps == [0]


# ---- 决策日志：追加式存储 -------------------------------------------------------


def _record(**overrides: object) -> DecisionRecord:
    fields: dict[str, str] = {
        "decision_id": new_decision_id(),
        "goal_id": "goal",
        "action": "approve",
        "step": "step-01.md",
        "raw_text": "",
        "workflow_status": "pending",
    }
    fields.update(overrides)  # type: ignore[arg-type]
    return DecisionRecord(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_decision_records_roundtrip_in_order(tmp_path: Path) -> None:
    store = DecisionStore(tmp_path / "decisions")
    first = _record(action="reject", raw_text="第一版不行", workflow_status="blocked")
    second = _record(action="approve", workflow_status="completed")

    await store.append(first)
    await store.append(second)

    records = await store.list_records(goal_id="goal")
    assert [record.decision_id for record in records] == [first.decision_id, second.decision_id]
    assert [record.action for record in records] == [DecisionAction.REJECT, DecisionAction.APPROVE]
    assert records[0].raw_text == "第一版不行"
    assert records[0].workflow_status is WorkflowStatus.BLOCKED
    assert records[0].schema_version == DECISION_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_decision_store_refuses_to_overwrite_the_same_id(tmp_path: Path) -> None:
    """负向验证（历史被覆盖即红）：同 id 二次写显性报错，原记录原样保留。"""
    store = DecisionStore(tmp_path / "decisions")
    record = _record()
    await store.append(record)

    with pytest.raises(DecisionError, match="append-only"):
        await store.append(_record(decision_id=record.decision_id, action="reject"))

    records = await store.list_records()
    assert len(records) == 1
    assert records[0].action is DecisionAction.APPROVE


@pytest.mark.asyncio
async def test_decision_store_reports_corrupt_records_loudly(tmp_path: Path) -> None:
    store = DecisionStore(tmp_path / "decisions")
    (tmp_path / "decisions").mkdir()
    (tmp_path / "decisions" / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(DecisionError, match="corrupted"):
        await store.list_records()


def test_exclusive_create_closes_the_race_window(tmp_path: Path) -> None:
    """独占创建是跨进程竞态的后盾：exists 检查与创建之间出现的文件同样拒绝写入。

    负向锚（把 ``open("x")`` 换成可覆盖的写法，此测试变红）——store 不持锁（审查 #15），
    这一步是 append-only 的最后防线。
    """
    store = DecisionStore(tmp_path / "decisions")
    record = _record(decision_id="race")
    path = store._path(record.decision_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        store._create_exclusive(path, "{}")
    assert path.read_text(encoding="utf-8") == "{}"  # 原内容未被覆盖


@pytest.mark.asyncio
async def test_decision_store_rejects_foreign_schema_versions(tmp_path: Path) -> None:
    store = DecisionStore(tmp_path / "decisions")
    record = _record()
    await store.append(record)
    path = store._path(record.decision_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = "999"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DecisionError, match="schema version"):
        await store.list_records()


@pytest.mark.parametrize("bad_id", ["..", "a/b", "con", ""])
async def test_decision_ids_must_be_path_safe(tmp_path: Path, bad_id: str) -> None:
    store = DecisionStore(tmp_path / "decisions")
    with pytest.raises(DecisionError, match="decision id"):
        # model_copy 绕过模型侧 min_length：这里专测 store 的路径安全守卫。
        await store.append(_record().model_copy(update={"decision_id": bad_id}))


def test_decision_store_location_is_the_goal_directory() -> None:
    assert decision_store(Path("goal")).root == Path("goal") / "decisions"


# ---- 应用服务：record_decision / pause_resume / 自动推进 ------------------------


@pytest.fixture()
def gated_goal(tmp_path: Path) -> tuple[WorkflowResource, Path]:
    """一个带审批步骤的 workflow 与已挂起在门上的 goal 目录（含 brief.md）。"""
    workflow = _workflow(_approval_step(), _plain_step(2))
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    _brief(goal_dir)
    return workflow, goal_dir


@pytest.mark.asyncio
async def test_record_decision_approve_advances_and_appends_one_record(gated_goal) -> None:
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)

    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.APPROVE)

    assert outcome.status is DecisionStatus.RECORDED
    assert outcome.proceed is True
    records = await decision_store(goal_dir).list_records(goal_id=goal_dir.name)
    assert len(records) == 1
    assert records[0].action is DecisionAction.APPROVE
    assert records[0].step == "step-01.md"
    assert records[0].workflow_status is WorkflowStatus.PENDING
    runner = await restore_runner(workflow, goal_dir)
    assert runner.state.completed_steps == [0]
    assert "用户补充" not in (goal_dir / "brief.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_record_decision_reject_blocks_and_keeps_the_reason(gated_goal) -> None:
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)

    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.REJECT, text="验收标准不可判定")

    assert outcome.status is DecisionStatus.RECORDED
    assert outcome.proceed is False
    records = await decision_store(goal_dir).list_records(goal_id=goal_dir.name)
    assert [record.action for record in records] == [DecisionAction.REJECT]
    assert records[0].raw_text == "验收标准不可判定"
    assert records[0].workflow_status is WorkflowStatus.BLOCKED
    runner = await restore_runner(workflow, goal_dir)
    assert runner.state.status is WorkflowStatus.BLOCKED
    assert runner.state.completed_steps == []
    brief = (goal_dir / "brief.md").read_text(encoding="utf-8")
    assert "## 用户补充（User Responses）" in brief
    assert "验收标准不可判定" in brief


@pytest.mark.asyncio
async def test_record_decision_amend_keeps_the_supplement_and_the_step_open(gated_goal) -> None:
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)

    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.AMEND, text="请补充成本估算")

    assert outcome.status is DecisionStatus.RECORDED
    assert outcome.proceed is True
    records = await decision_store(goal_dir).list_records(goal_id=goal_dir.name)
    assert [record.action for record in records] == [DecisionAction.AMEND]
    assert records[0].raw_text == "请补充成本估算"
    runner = await restore_runner(workflow, goal_dir)
    assert runner.state.status is WorkflowStatus.PENDING
    assert runner.state.completed_steps == []
    assert "请补充成本估算" in (goal_dir / "brief.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_record_decision_without_a_gate_changes_nothing(tmp_path: Path) -> None:
    """没有步骤在等决策时决策命令是显性 no-op：状态不动、不落任何记录。"""
    workflow = _workflow(_plain_step(), _plain_step(2))
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    _brief(goal_dir)
    runner = WorkflowRunner(workflow, goal_id=goal_dir.name, checkpoint_store=checkpoint_store(goal_dir))
    await runner.run_step(_complete)  # 无审批声明的首步：直接完成

    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.APPROVE)

    assert outcome.status is DecisionStatus.UNCHANGED
    assert await decision_store(goal_dir).list_records() == []


@pytest.mark.asyncio
async def test_a_second_decision_after_the_gate_lifted_records_nothing(gated_goal) -> None:
    """门已离开后再敲决策：UNCHANGED、不产生重复记录（重跑不膨胀决策日志）。"""
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)
    await record_decision(workflow, goal_dir, action=DecisionAction.APPROVE)

    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.APPROVE)

    assert outcome.status is DecisionStatus.UNCHANGED
    assert len(await decision_store(goal_dir).list_records()) == 1


@pytest.mark.asyncio
async def test_history_survives_reject_rerun_and_a_second_decision(gated_goal) -> None:
    """拒绝 → 重跑 → 再挂起 → 二次拒绝 → 恢复：四条记录都在，先来后到（历史不被覆盖）。

    store 级二轮回归锚（审查 #1）：二轮 reject 在同一 ``(step, active, status)`` 位置再次
    持久化——审批轮次进 checkpoint 幂等键后不再撞 conflict（收敛前实测死锁：
    ``checkpoint conflict: …-step-1-active-0-blocked``，此后 /goal run 永久失败）。
    """
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)
    await record_decision(workflow, goal_dir, action=DecisionAction.REJECT, text="第一版不行")
    runner = await restore_runner(workflow, goal_dir)
    runner.resume()
    await runner.run_step(_complete)
    assert runner.state.awaiting_approval is True

    second = await record_decision(workflow, goal_dir, action=DecisionAction.REJECT, text="第二版还不行")

    assert second.status is DecisionStatus.RECORDED  # 二轮 reject 落账且持久化成功
    runner = await restore_runner(workflow, goal_dir)
    assert runner.state.status is WorkflowStatus.BLOCKED

    outcome = await pause_resume(workflow, goal_dir, resume=True)
    assert outcome.status is PauseResumeStatus.RESUMED  # 其后的 resume 也成功
    runner = await restore_runner(workflow, goal_dir)
    await runner.run_step(_complete)
    amended = await record_decision(workflow, goal_dir, action=DecisionAction.AMEND, text="补充后再来")
    assert amended.status is DecisionStatus.RECORDED

    records = await decision_store(goal_dir).list_records(goal_id=goal_dir.name)
    assert [record.action for record in records] == [
        DecisionAction.REJECT,
        DecisionAction.REJECT,
        DecisionAction.RESUME,
        DecisionAction.AMEND,
    ]
    assert [record.raw_text for record in records[:2]] == ["第一版不行", "第二版还不行"]
    runner = await restore_runner(workflow, goal_dir)
    assert runner.state.completed_steps == []


@pytest.mark.asyncio
async def test_resume_via_pause_resume_cannot_approve(gated_goal) -> None:
    """负向验证（resume 当 approve 即红）：pause_resume 在门上显性拒绝，状态与日志都不动。"""
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)

    outcome = await pause_resume(workflow, goal_dir, resume=True, response="就当批准了吧")

    assert outcome.status.value == "unchanged"
    assert "cannot approve" in outcome.message
    runner = await restore_runner(workflow, goal_dir)
    assert runner.state.awaiting_approval is True
    assert runner.state.status is WorkflowStatus.WAITING_USER
    assert runner.state.completed_steps == []
    assert "就当批准了吧" not in (goal_dir / "brief.md").read_text(encoding="utf-8")
    assert await decision_store(goal_dir).list_records() == []


@pytest.mark.asyncio
async def test_record_decision_refuses_the_resume_action(gated_goal) -> None:
    """resume 不是决策命令：混进决策入口会被显性拒绝（AD-3 负向锚点）。"""
    workflow, goal_dir = gated_goal

    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.RESUME)

    assert outcome.status is DecisionStatus.FAILED
    assert "resume is not a decision" in outcome.message


@pytest.mark.asyncio
async def test_auto_advance_never_approves_the_gate(gated_goal) -> None:
    """负向验证（cron 自动批准即红）：auto 模式推进在审批门前停下，不 resume、不落记录、不重跑。"""
    workflow, goal_dir = gated_goal
    runner = await _gate_runner(workflow, goal_dir)
    context = _GoalAdvanceContext(runner=runner, mode="auto", description="demo", goal_dir=goal_dir)

    outcome = await advance(
        context,
        _refuse_execution,
        confirm_checkpoint=lambda: True,
        load_project_context=lambda: None,
    )

    assert outcome.status is GoalAdvanceStatus.WAITING
    assert any("awaits a human decision" in message for message in outcome.messages)
    assert runner.state.awaiting_approval is True
    assert runner.state.completed_steps == []
    assert await decision_store(goal_dir).list_records() == []


# ---- 审查回归：并行批次挂门 / checkpoint 组合 / 原子性与兼容性 ------------------


@pytest.mark.asyncio
async def test_parallel_story_batch_gates_after_completing_and_clears_story_fields() -> None:
    """并发批次（审查 #10/#7）：批完挂门、story 簿记清场（决策不归因 story）、approve 放行。"""
    step = _approval_step(story_loop="stories", max_parallel_stories=2)
    runner = WorkflowRunner(_workflow(step, _plain_step(2)))
    stories = [
        StorySpec(id="S-1", epic="E1", parallel_group="g", write_set=["src/a.py"]),
        StorySpec(id="S-2", epic="E1", parallel_group="g", write_set=["src/b.py"]),
    ]

    result = await runner.run_step(_complete, stories=stories)
    assert result.status is WorkflowStatus.PENDING
    result = await runner.run_step(_complete, stories=stories)

    assert result.status is WorkflowStatus.WAITING_USER
    assert runner.state.awaiting_approval is True
    assert runner.state.completed_steps == []
    assert runner.state.completed_stories == []
    assert runner.state.active_story is None
    assert runner.state.story_outputs == {}

    runner.approve()

    assert runner.state.completed_steps == [0]
    assert runner.state.outputs["step-01.md"]
    assert runner.state.active_story is None


@pytest.mark.asyncio
async def test_rejected_parallel_batch_reruns_its_stories_instead_of_skipping_the_gate() -> None:
    """并发批次 reject 后重跑：批次从第一条 story 重新执行，重做完再次挂门（不跳过门）。"""
    step = _approval_step(story_loop="stories", max_parallel_stories=2)
    runner = WorkflowRunner(_workflow(step, _plain_step(2)))
    stories = [
        StorySpec(id="S-1", epic="E1", parallel_group="g", write_set=["src/a.py"]),
        StorySpec(id="S-2", epic="E1", parallel_group="g", write_set=["src/b.py"]),
    ]
    await runner.run_step(_complete, stories=stories)
    await runner.run_step(_complete, stories=stories)
    runner.reject("不行")
    executed: list[str] = []

    async def counting(_step, story, *_rest):  # noqa: ANN001, ANN202
        executed.append(story.id)
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output=f"out-{story.id}")

    runner.resume()
    await runner.run_step(counting, stories=stories)
    await runner.run_step(counting, stories=stories)

    assert sorted(executed) == ["S-1", "S-2"]
    assert runner.state.awaiting_approval is True
    assert runner.state.completed_steps == []


@pytest.mark.asyncio
async def test_approve_on_a_step_that_also_declares_a_checkpoint_explains_the_flow(tmp_path: Path) -> None:
    """approve + checkpoint 同步声明（审查 #11）：簿记落定，剩余的是普通检查点等待并有提示。"""
    step = WorkflowStepResource(
        index=1, name="step-01.md", instructions="", checkpoint="user", approval=StepApproval(required=True)
    )
    workflow = _workflow(step, _plain_step(2))
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    _brief(goal_dir)
    await _gate_runner(workflow, goal_dir)

    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.APPROVE)

    assert outcome.status is DecisionStatus.RECORDED
    assert "also declared a checkpoint" in outcome.message
    runner = await restore_runner(workflow, goal_dir)
    assert runner.state.completed_steps == [0]  # 簿记已落定
    assert runner.state.status is WorkflowStatus.WAITING_USER  # 检查点等待，非审批门
    assert runner.state.awaiting_approval is False


@pytest.mark.asyncio
async def test_reject_and_amend_require_a_non_empty_text(gated_goal) -> None:
    """空白理由 / 补充显性拒绝（审查 #8）：不落空 reason 的 BLOCKED、不写空审计记录。"""
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)

    for action in (DecisionAction.REJECT, DecisionAction.AMEND):
        outcome = await record_decision(workflow, goal_dir, action=action, text="   ")
        assert outcome.status is DecisionStatus.FAILED
        assert "requires a non-empty" in outcome.message

    runner = await restore_runner(workflow, goal_dir)
    assert runner.state.awaiting_approval is True  # 门未动
    assert await decision_store(goal_dir).list_records() == []


@pytest.mark.asyncio
async def test_decision_records_carry_the_gate_round(gated_goal) -> None:
    """决策记录带审批轮次（审查 #17）：reject → 重跑 → 再挂门的记录可与轮次关联。"""
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)
    await record_decision(workflow, goal_dir, action=DecisionAction.REJECT, text="r1")
    runner = await restore_runner(workflow, goal_dir)
    runner.resume()
    await runner.run_step(_complete)

    await record_decision(workflow, goal_dir, action=DecisionAction.AMEND, text="r2")

    records = await decision_store(goal_dir).list_records(goal_id=goal_dir.name)
    assert [record.approval_round for record in records] == [1, 2]
    assert [record.action for record in records] == [DecisionAction.REJECT, DecisionAction.AMEND]


@pytest.mark.asyncio
async def test_persist_failure_after_append_is_disclosed(gated_goal, monkeypatch: pytest.MonkeyPatch) -> None:
    """落定次序的失败面（审查 #2）：append 已生效、persist 失败 → FAILED 且披露记录已写。"""
    workflow, goal_dir = gated_goal
    await _gate_runner(workflow, goal_dir)

    async def broken(self):  # noqa: ANN001, ANN202
        raise WorkflowCheckpointError("disk gone")

    monkeypatch.setattr(WorkflowRunner, "persist_state", broken)
    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.REJECT, text="理由")

    assert outcome.status is DecisionStatus.FAILED
    assert "already recorded" in outcome.message
    assert outcome.decision_id
    assert len(await decision_store(goal_dir).list_records()) == 1


@pytest.mark.asyncio
async def test_a_successful_resume_appends_one_resume_record(tmp_path: Path) -> None:
    """resume 每次一条决策记录（审查 #6，引擎面契约）：只标记执行被恢复，不等于批准。"""
    workflow = _workflow(_plain_step(checkpoint="user"), _plain_step(2))
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    _brief(goal_dir)
    runner = WorkflowRunner(workflow, goal_id=goal_dir.name, checkpoint_store=checkpoint_store(goal_dir))
    await runner.run_step(_complete)  # checkpoint 声明 → WAITING_USER（普通检查点，非审批门）
    assert runner.state.awaiting_approval is False

    outcome = await pause_resume(workflow, goal_dir, resume=True, response="继续")

    assert outcome.status is PauseResumeStatus.RESUMED
    records = await decision_store(goal_dir).list_records(goal_id=goal_dir.name)
    assert [record.action for record in records] == [DecisionAction.RESUME]
    assert records[0].raw_text == "继续"
    assert records[0].workflow_status is WorkflowStatus.PENDING


@pytest.mark.asyncio
async def test_record_decision_on_a_completed_workflow_is_unchanged(tmp_path: Path) -> None:
    """已完成的 workflow 上决策命令是 UNCHANGED（审查 #18），不产生记录。"""
    workflow = _workflow(_approval_step())
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    _brief(goal_dir)
    runner = await _gate_runner(workflow, goal_dir)
    runner.approve()
    await runner.persist_state()
    assert runner.done

    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.APPROVE)

    assert outcome.status is DecisionStatus.UNCHANGED
    assert "already complete" in outcome.message
    assert await decision_store(goal_dir).list_records() == []


def test_legacy_checkpoint_without_gate_fields_restores_with_defaults(tmp_path: Path) -> None:
    """旧格式 checkpoint（无 51-5 字段）→ from_checkpoint 取缺省值，零回归（审查 #14）。"""
    legacy = {
        "checkpoint_id": "legacy-cp",
        "goal_id": "goal",
        "phase": "implementation",
        "status": "waiting_user",
        "run_id": "run-1",
        "active_skill": "demo",
        "active_step": 0,
        "created_at": "2026-01-01T00:00:00.000000",
    }
    checkpoint = WorkflowCheckpoint.model_validate(json.loads(json.dumps(legacy)))

    runner = WorkflowRunner.from_checkpoint(_workflow(_approval_step(), _plain_step(2)), checkpoint)

    assert runner.state.awaiting_approval is False
    assert runner.state.pending_output is None
    assert runner.state.approval_round == 0


# ---- CLI：/goal approve | reject | amend | decisions ----------------------------


@pytest.fixture()
def approval_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_workflow_root: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    (goal_workflow_root / "workflow.md").write_text(
        "---\nname: gated\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\nworkflow instructions\n\n"
        "## Step 01: plan\ninput: user intent, existing project context\n"
        "output: requirements brief\napproval: required 架构冻结前需人工确认\n\nplan the story\n\n"
        "## Step 02: build\ninput: requirements brief\noutput: implementation\n\nbuild the story\n",
        encoding="utf-8",
    )
    (tmp_path / "_he-output" / "goals").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def successful_step(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(prompt)
        return SimpleNamespace(success=True, output=f"output-{len(calls)}")

    monkeypatch.setattr("heagent.cli.goal._goal_session", run_step)
    return calls


def _active_goal_dir(cwd: Path) -> Path:
    goal_id = (cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    return cwd / "_he-output" / "goals" / goal_id


@pytest.mark.asyncio
async def test_goal_approve_advances_past_the_gate(
    approval_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new gated demo")
    assert len(successful_step) == 1  # step 01 执行后挂在审批门上

    await _goal_runner(SimpleNamespace(), None, "approve")

    assert len(successful_step) == 2  # approve 落定后推进执行 step 02
    captured = capsys.readouterr()
    assert "approve recorded" in captured.err
    records = await decision_store(_active_goal_dir(approval_cwd)).list_records()
    assert [record.action for record in records] == [DecisionAction.APPROVE]
    workflow = _goal_declarative_workflow()
    assert workflow is not None
    runner = await _goal_declarative_runner(workflow, _active_goal_dir(approval_cwd))
    assert runner.done


@pytest.mark.asyncio
async def test_goal_reject_blocks_then_resume_reruns_and_history_is_kept(
    approval_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new gated demo")
    goal_dir = _active_goal_dir(approval_cwd)

    await _goal_runner(SimpleNamespace(), None, "reject 计划范围太粗")

    assert len(successful_step) == 1  # reject 不推进
    assert "reject recorded" in capsys.readouterr().err
    assert "计划范围太粗" in (goal_dir / "brief.md").read_text(encoding="utf-8")

    await _goal_runner(SimpleNamespace(), None, "resume")

    assert len(successful_step) == 2  # resume 重跑被驳回的步骤（再次挂门）
    assert "计划范围太粗" in successful_step[1]  # 拒绝理由经需求文档「用户补充」进入重跑提示词

    await _goal_runner(SimpleNamespace(), None, "approve")

    assert len(successful_step) == 3  # 第二次决策放行，step 02 执行
    records = await decision_store(goal_dir).list_records()
    # 中间的 /goal resume 也按契约记一条 RESUME（只标记执行被恢复，不等于批准）。
    assert [record.action for record in records] == [
        DecisionAction.REJECT,
        DecisionAction.RESUME,
        DecisionAction.APPROVE,
    ]
    assert records[0].raw_text == "计划范围太粗"


@pytest.mark.asyncio
async def test_goal_amend_reruns_with_the_supplement(
    approval_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new gated demo")

    await _goal_runner(SimpleNamespace(), None, "amend 请补充成本估算")

    assert len(successful_step) == 2  # amend 落定即带补充重跑
    assert "请补充成本估算" in successful_step[1]
    assert "amend recorded" in capsys.readouterr().err
    records = await decision_store(_active_goal_dir(approval_cwd)).list_records()
    assert [record.action for record in records] == [DecisionAction.AMEND]
    assert records[0].raw_text == "请补充成本估算"


@pytest.mark.asyncio
async def test_goal_resume_at_the_gate_points_at_decisions(
    approval_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI 的 resume 在审批门上不再等同批准：显性指向决策命令，不推进。"""
    await _goal_runner(SimpleNamespace(), None, "new gated demo")
    capsys.readouterr()

    await _goal_runner(SimpleNamespace(), None, "resume 就当批准了吧")

    captured = capsys.readouterr()
    assert "cannot approve" in captured.err
    assert len(successful_step) == 1  # 门未动，没有重跑
    assert await decision_store(_active_goal_dir(approval_cwd)).list_records() == []


@pytest.mark.asyncio
async def test_goal_decisions_lists_the_recorded_history(
    approval_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new gated demo")
    await _goal_runner(SimpleNamespace(), None, "reject 第一版不行")
    capsys.readouterr()

    await _goal_runner(SimpleNamespace(), None, "decisions")

    captured = capsys.readouterr()
    assert "1 record(s)" in captured.err
    assert "reject" in captured.err
    assert "第一版不行" in captured.err
    assert "step=step-01-plan.md" in captured.err


@pytest.mark.asyncio
async def test_goal_status_names_the_pending_decision(
    approval_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new gated demo")
    capsys.readouterr()

    await _goal_runner(SimpleNamespace(), None, "status")

    captured = capsys.readouterr()
    assert "awaits a decision" in captured.err


@pytest.mark.asyncio
async def test_goal_next_at_the_gate_names_the_decision_not_resume(
    approval_cwd: Path, successful_step: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """/goal next 在审批门上指向决策而非 resume（审查 #19：删掉 prepare 的分流此测试即红）。"""
    await _goal_runner(SimpleNamespace(), None, "new gated demo")
    capsys.readouterr()

    await _goal_runner(SimpleNamespace(), None, "next")

    captured = capsys.readouterr()
    assert "awaits a human decision" in captured.err
    assert "use /goal resume first" not in captured.err
    assert len(successful_step) == 1  # 门未动


def test_decision_display_text_truncates_long_text() -> None:
    """单条原文回显截断到 120 字符并带省略标记（审查 #18）；空白折叠成单行。"""
    rendered = cli_goal._decision_display_text("x" * 500)
    assert len(rendered) == 120
    assert rendered.endswith("…")
    assert cli_goal._decision_display_text("一  行\n\t两行") == "一 行 两行"


@pytest.mark.asyncio
async def test_goal_approve_and_decisions_reject_stray_arguments(
    approval_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """/goal approve 与 /goal decisions 不收多余参数（审查 #18）：拼错目标时给用法表。"""
    await _goal_runner(SimpleNamespace(), None, "approve 有点多余")
    assert "用法" in capsys.readouterr().err

    await _goal_runner(SimpleNamespace(), None, "decisions all")
    assert "用法" in capsys.readouterr().err


# ---- 内核自锁（台账 A32②）：三写方法的读改写区持 goal 域互斥 --------------------


@pytest.mark.asyncio
async def test_pause_and_decision_run_under_the_domain_lock(gated_goal, monkeypatch) -> None:  # noqa: ANN001
    """pause_resume / record_decision 自持域锁（观察点 = 二者共用的 restore_runner 首站）。

    变异体：撤 ``_pause_resume_unlocked`` / ``_record_decision_unlocked`` 任一外壳的
    ``goal_mutex()`` ⇒ 对应观察点读到 ``False``，本用例变红。
    ``/goal pause`` 此前是入口层不持锁的漏网写路径（A32② 勘察发现），随内核自锁收口。
    """
    workflow, goal_dir = gated_goal
    observations: list[bool] = []
    original_restore = goal_application.restore_runner

    async def observe_restore(wf: WorkflowResource, gd: Path) -> WorkflowRunner:
        observations.append(goal_mutex._auto_lock.locked())
        return await original_restore(wf, gd)

    monkeypatch.setattr(goal_application, "restore_runner", observe_restore)

    paused = await pause_resume(workflow, goal_dir, resume=False)
    assert paused.status is PauseResumeStatus.PAUSED

    await _gate_runner(workflow, goal_dir)  # 推到审批门并落盘（不经 restore_runner）
    outcome = await record_decision(workflow, goal_dir, action=DecisionAction.REJECT, text="not good")
    assert outcome.status is DecisionStatus.RECORDED

    assert observations == [True, True]
    assert goal_mutex._auto_lock.locked() is False


@pytest.mark.asyncio
async def test_advance_runs_under_the_domain_lock(gated_goal) -> None:
    """advance 的推进循环自持域锁（观察点 = 锁内被 await 的 execute_step 端口）。

    变异体：撤 ``advance`` 外壳的 ``goal_mutex()`` ⇒ 观察点读到 ``False``，本用例变红。
    """
    _workflow_resource, goal_dir = gated_goal
    runner = WorkflowRunner(
        _workflow(_plain_step()), goal_id=goal_dir.name, checkpoint_store=checkpoint_store(goal_dir)
    )
    observations: list[bool] = []

    async def observe_step(_inputs: dict[str, object], _step: object, _story: object = None) -> WorkflowStepResult:
        observations.append(goal_mutex._auto_lock.locked())
        return WorkflowStepResult(status=WorkflowStatus.COMPLETED, output="out")

    context = _GoalAdvanceContext(runner=runner, mode="auto", description="demo", goal_dir=goal_dir)
    outcome = await advance(context, observe_step, confirm_checkpoint=lambda: True, load_project_context=lambda: None)

    assert outcome.status is GoalAdvanceStatus.DONE
    assert observations == [True]
    assert goal_mutex._auto_lock.locked() is False
