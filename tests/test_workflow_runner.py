from __future__ import annotations

import asyncio
import json

import pytest

from heagent.engine.checkpoint import WorkflowCheckpoint, WorkflowCheckpointStore, WorkflowPhase, WorkflowStatus
from heagent.engine.workflow_events import WorkflowEvent
from heagent.engine.workflow_runner import (
    StorySpec,
    WorkflowGateError,
    WorkflowRunResult,
    WorkflowRunner,
    WorkflowStepResult,
    _bounded_reason,
    _emit_step_event,
    required_sections,
)
from heagent.goal.workflow_loader import parse_story_list
from heagent.engine.workflow_resource import StepApproval, WorkflowResource, WorkflowStepResource


def _workflow(*steps: WorkflowStepResource) -> WorkflowResource:
    return WorkflowResource(name="demo", instructions="", steps=list(steps))


@pytest.mark.asyncio
async def test_callback_exception_transitions_to_failed_without_fake_pending() -> None:
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)

    async def callback(_step):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await runner.run_step(callback)
    assert runner.state.status is WorkflowStatus.FAILED
    assert runner.state.reason == "boom"


@pytest.mark.asyncio
async def test_callback_cancellation_uses_cancelled_transition() -> None:
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)

    async def callback(_step):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await runner.run_step(callback)
    assert runner.state.status is WorkflowStatus.PENDING
    assert runner.state.reason == "cancelled"


async def _cancelled_story_callback(_step, _story):
    raise asyncio.CancelledError()


class _BatchInterrupt(BaseException):
    """非取消类 BaseException 的替身（走 EXECUTOR_FAILED）。

    不用真实 KeyboardInterrupt：asyncio 任务内的 KI 会被事件循环直接上抛打断 loop，
    无法在 await 处断言；且 KI / SystemExit 自 A39（2026-10-23）起与 CancelledError
    同路落 PENDING——本替身刻意不属于该类，用于锁定「其余 BaseException 仍落 FAILED」。
    """


async def _interrupted_story_callback(_step, _story):
    raise _BatchInterrupt()


@pytest.mark.asyncio
async def test_single_story_cancellation_transitions_to_pending() -> None:
    """单 story 批（= 串行路径）取消语义锁定：CancelledError 经 CANCELLED 落 PENDING
    （51-2 Review P2；Epic 52 改名保留）。"""
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", story_loop="epics.md", max_parallel_stories=2)
    )
    runner = WorkflowRunner(workflow)

    with pytest.raises(asyncio.CancelledError):
        await runner.run_step(_cancelled_story_callback, stories=[StorySpec(id="S-1", summary="One", epic="E1")])
    assert runner.state.status is WorkflowStatus.PENDING
    assert runner.state.reason == "cancelled"


@pytest.mark.asyncio
async def test_single_story_non_cancellation_baseexception_transitions_to_failed() -> None:
    """单 story 批（= 串行路径）非取消 BaseException 经 EXECUTOR_FAILED 落 FAILED（Review P2；Epic 52 改名保留）。"""
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", story_loop="epics.md", max_parallel_stories=2)
    )
    runner = WorkflowRunner(workflow)

    with pytest.raises(_BatchInterrupt):
        await runner.run_step(_interrupted_story_callback, stories=[StorySpec(id="S-1", summary="One", epic="E1")])
    assert runner.state.status is WorkflowStatus.FAILED
    assert runner.state.reason == "executor_failed"


@pytest.mark.asyncio
async def test_pause_and_resume_emit_transition_events_fail_soft() -> None:
    """pause / resume 经转换表并发射观测事件；sink 失败不改变状态机结果（51-2 Review P7）。"""
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)
    events: list[tuple[str, dict]] = []

    def emit(kind, *, details=None):
        events.append((kind, details or {}))
        if kind == "workflow_paused":
            raise RuntimeError("sink failure must not change state")

    runner.pause(emit=emit)
    assert runner.state.status is WorkflowStatus.WAITING_USER
    assert events == [
        (
            "workflow_paused",
            {
                "step": "step-01.md",
                "story": "",
                "duration_ms": 0,
                "error_kind": "",
                "transition_event": WorkflowEvent.USER_PAUSE.value,
            },
        )
    ]

    runner.resume(emit=emit)
    assert runner.state.status is WorkflowStatus.PENDING
    assert [kind for kind, _ in events] == ["workflow_paused", "workflow_resumed"]


@pytest.mark.asyncio
async def test_pause_from_running_goes_through_the_transition_table() -> None:
    """RUNNING 态暂停走 (RUNNING, USER_PAUSE) 表项，非法来源仍 fail-loud。"""
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)
    runner.state = runner.state.model_copy(update={"status": WorkflowStatus.RUNNING})

    paused = runner.pause()

    assert paused.status is WorkflowStatus.WAITING_USER
    assert paused.reason == "user requested pause; resume to continue"


@pytest.mark.asyncio
async def test_runner_executes_one_declared_step_in_order() -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01-first.md", instructions="first"),
        WorkflowStepResource(index=2, name="step-02-second.md", instructions="second"),
    )
    runner = WorkflowRunner(workflow)
    seen: list[str] = []

    async def callback(step):
        seen.append(step.name)
        return WorkflowStepResult(output=step.name)

    first = await runner.run_step(callback)
    assert first.status is WorkflowStatus.PENDING
    assert first.step_index == 1
    assert seen == ["step-01-first.md"]
    second = await runner.run_step(callback)
    assert second.status is WorkflowStatus.COMPLETED
    assert runner.done
    assert seen == ["step-01-first.md", "step-02-second.md"]


@pytest.mark.asyncio
async def test_missing_input_and_invalid_output_block_without_advancing() -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", input="brief", output="plan"),
    )
    runner = WorkflowRunner(workflow)
    result = await runner.run_step(lambda _: WorkflowStepResult(output=None))
    assert result.status is WorkflowStatus.BLOCKED
    assert result.missing == ["brief"]
    assert runner.state.active_step == 0
    runner.resume()
    result = await runner.run_step(lambda _: WorkflowStepResult(output={"other": "x"}), inputs={"brief": "x"})
    assert result.status is WorkflowStatus.BLOCKED
    assert "missing" in result.reason


@pytest.mark.asyncio
async def test_checkpoint_waits_then_resume_advances_and_persists_state(tmp_path) -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", checkpoint="user"),
        WorkflowStepResource(index=2, name="step-02.md", instructions=""),
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)
    result = await runner.run_step(lambda _: WorkflowStepResult(output="ok"))
    assert result.status is WorkflowStatus.WAITING_USER
    assert runner.state.active_step == 1
    state = await store.load_state()
    assert state is not None
    assert state.active_step == 1
    assert state.status is WorkflowStatus.WAITING_USER
    runner.resume()
    result = await runner.run_step(lambda _: WorkflowStepResult(output="done"))
    assert result.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_final_checkpoint_completes_instead_of_waiting(tmp_path) -> None:
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions="", checkpoint="true"))
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    result = await runner.run_step(lambda _: WorkflowStepResult(output="done"))

    assert result.status is WorkflowStatus.COMPLETED
    assert runner.done
    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert checkpoints[-1].status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_failed_step_is_retryable_without_fake_completion() -> None:
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)
    result = await runner.run_step(lambda _: WorkflowStepResult(status=WorkflowStatus.FAILED, reason="provider"))
    assert isinstance(result, WorkflowRunResult)
    assert result.status is WorkflowStatus.FAILED
    assert not runner.done
    runner.resume()
    result = await runner.run_step(lambda _: WorkflowStepResult(output="ok"))
    assert result.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_checkpoint_restore_keeps_zero_based_completed_steps(tmp_path) -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions=""),
        WorkflowStepResource(index=2, name="step-02.md", instructions=""),
    )
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="goal-run-step-2",
        goal_id="goal",
        phase=WorkflowPhase.IMPLEMENTATION,
        status=WorkflowStatus.PENDING,
        run_id="run",
        active_step=1,
        completed_steps=[0],
    )
    store = WorkflowCheckpointStore(str(tmp_path))
    runner = WorkflowRunner.from_checkpoint(workflow, checkpoint, checkpoint_store=store)
    assert runner.state.completed_steps == [0]
    result = await runner.run_step(lambda _: WorkflowStepResult(output="ok"))
    assert result.status is WorkflowStatus.COMPLETED
    assert runner.state.completed_steps == [0, 1]


@pytest.mark.asyncio
async def test_runner_persists_each_declared_output_reference_across_recovery(tmp_path) -> None:
    workflow = _workflow(
        WorkflowStepResource(
            index=1,
            name="step-01.md",
            instructions="",
            output="requirements brief, story breakdown",
        ),
        WorkflowStepResource(index=2, name="step-02.md", instructions="", input="requirements brief"),
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    assert (await runner.run_step(lambda _: WorkflowStepResult(output="analysis"))).status is WorkflowStatus.PENDING
    checkpoint = (await store.list_checkpoints(goal_id="goal"))[-1]
    restored = WorkflowRunner.from_checkpoint(workflow, checkpoint, checkpoint_store=store)

    assert restored.state.outputs["requirements brief"] == "analysis"
    assert restored.state.outputs["story breakdown"] == "analysis"
    result = await restored.run_step(lambda _: WorkflowStepResult(output="done"), inputs=restored.state.outputs)
    assert result.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_resume_reegress_same_pending_checkpoint_is_idempotent(tmp_path) -> None:
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", checkpoint="user"),
        WorkflowStepResource(index=2, name="step-02.md", instructions=""),
    )
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    assert (await runner.run_step(lambda _: WorkflowStepResult(output="ok"))).status is WorkflowStatus.WAITING_USER
    runner.resume()
    await runner.persist_state()  # first write of step-2-active-1-pending

    runner.state = runner.state.model_copy(update={"status": WorkflowStatus.WAITING_USER, "reason": "interrupted"})
    await runner.persist_state()  # step-2-active-1-waiting_user

    runner.resume()
    await runner.persist_state()  # re-issues step-2-active-1-pending; must not conflict

    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert any(c.checkpoint_id == "goal-run-step-2-active-1-pending" for c in checkpoints)


def test_section_gate_requires_standalone_headings() -> None:
    """A ``section:`` rule only accepts ``## <title>`` on its own line, nothing else."""
    step = WorkflowStepResource(
        index=1,
        name="step-01.md",
        instructions="",
        validation_rules="section: 实现摘要; section: 测试证据; section: 验证结论",
    )
    WorkflowRunner.validate_output(step, "## 实现摘要\n\n## 测试证据\n\n## 验证结论\n")
    with pytest.raises(WorkflowGateError):
        WorkflowRunner.validate_output(step, "## 实现摘要（S-1）\n\n## 测试证据\n\n## 验证结论\n")
    with pytest.raises(WorkflowGateError):
        WorkflowRunner.validate_output(step, "## 实现摘要\n\n## 测试证据\n")


def test_required_sections_ignores_case_and_keeps_authored_names() -> None:
    """``Section:`` spelling keeps working, and the message keeps the authored casing."""
    assert required_sections("Section: Implementation Summary; section: Verification Verdict") == [
        "Implementation Summary",
        "Verification Verdict",
    ]
    assert required_sections("") == []
    assert required_sections(None) == []
    assert required_sections("given when then only") == []
    step = WorkflowStepResource(
        index=1,
        name="step-01.md",
        instructions="",
        validation_rules="Section: Implementation Summary",
    )
    WorkflowRunner.validate_output(step, "## implementation summary\n")


STORY_DOC = "\n".join(
    [
        "# epics.md",
        "",
        "| 编号 | 父 Epic | 优先级 | 依赖 | 单一用户可见目标 |",
        "|------|---------|--------|------|------------------|",
        "| S-1 | E1 | P0 | none | 打开网页即可完整玩一局 |",
        "| S-2 | E2 | P1 | S-1 | 最高分跨会话记住 |",
        "",
        "## E1 — 经典玩法核心",
        "### S-1 经典玩法核心（可玩一局）",
        "",
        "- **父 Epic**：E1",
        "",
        "## E2 — 本地最高分与游戏控制",
        "### S-2 本地最高分",
        "",
        "- **父 Epic**：E2",
    ]
)


def test_story_headings_win_over_the_overview_table() -> None:
    """A doc with story sections plus an overview table must not read the table."""
    stories = parse_story_list(STORY_DOC)
    assert [story.id for story in stories] == ["S-1", "S-2"]
    assert [story.epic for story in stories] == ["E1", "E2"]
    assert stories[0].summary == "经典玩法核心（可玩一局）"


def test_story_table_alone_reads_the_epic_column_and_last_cell() -> None:
    """Tables without story sections keep working, with the Epic read from its column."""
    table = "\n".join(
        [
            "| 编号 | 父 Epic | 优先级 | 依赖 | 单一用户可见目标 |",
            "|------|---------|--------|------|------------------|",
            "| S-1 | E1 | P0 | none | 打开网页即可完整玩一局 |",
            "| S-2 | E2 | P1 | S-1 | 最高分跨会话记住 |",
            "",
            "## Sprint 计划",
            "",
            "### Sprint 1 — 可玩闭环",
            "",
            "### Sprint 2 — 体验收口",
        ]
    )
    stories = parse_story_list(table)
    assert [story.epic for story in stories] == ["E1", "E2"]
    assert stories[1].summary == "最高分跨会话记住"


def test_gate_error_names_the_headings_that_are_present() -> None:
    """A blocked step must show what its output actually contained."""
    step = WorkflowStepResource(index=1, name="step-07.md", instructions="", validation_rules="section: 实现摘要")
    with pytest.raises(WorkflowGateError, match="present H2 headings: 3. 本轮实现动作"):
        WorkflowRunner.validate_output(step, "## 3. 本轮实现动作\n\ntext\n")


# --- Phase 5 C1：步骤粒度观测事件（emit 注入端口）---


@pytest.mark.asyncio
async def test_run_step_emits_started_and_completed_with_duration() -> None:
    """emit 注入 → started/completed 各一条（step/story/result + duration_ms）。"""
    from typing import Any

    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(kind: str, *, details: dict[str, Any] | None = None) -> None:
        events.append((kind, details or {}))

    async def callback(step):
        return WorkflowStepResult(output={"plan": "x"})

    await runner.run_step(callback, inputs={"brief": "x"}, emit=emit)
    kinds = [kind for kind, _ in events]
    assert kinds == ["workflow_step_started", "workflow_step_completed"]
    started_details = events[0][1]
    assert started_details["step"] == "step-01.md"
    assert started_details["story"] == ""
    assert isinstance(started_details["duration_ms"], int)
    completed_details = events[1][1]
    assert completed_details["result"] == "completed"
    assert completed_details["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_run_step_emits_failed_and_reraises() -> None:
    """回调抛异常 → workflow_step_failed（error_kind=exception）且异常原样上抛。"""
    from typing import Any

    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(kind: str, *, details: dict[str, Any] | None = None) -> None:
        events.append((kind, details or {}))

    async def callback(step):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await runner.run_step(callback, emit=emit)
    kinds = [kind for kind, _ in events]
    assert kinds == ["workflow_step_started", "workflow_step_failed"]
    failed = events[1][1]
    assert failed["error_kind"] == "exception"
    assert "boom" in failed["error"]
    assert failed["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_run_step_without_emit_is_unchanged_and_emit_failure_isolated() -> None:
    """emit=None 零行为变化；emit 抛异常被隔离（warning）且步骤结果不受影响。"""
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow)

    async def callback(step):
        return WorkflowStepResult(output={"plan": "x"})

    # emit=None：与既有行为一致（不发事件、不抛；单步工作流执行完即 COMPLETED）
    result = await runner.run_step(callback, inputs={"brief": "x"})
    assert result.status is WorkflowStatus.COMPLETED

    # emit 抛异常 → 隔离
    def bad_emit(kind: str, *, details=None) -> None:
        raise RuntimeError("observer down")

    runner2 = WorkflowRunner(workflow)
    result2 = await runner2.run_step(callback, inputs={"brief": "x"}, emit=bad_emit)
    assert result2.status is WorkflowStatus.COMPLETED


def test_emit_isolation_covers_hostile_duck_step_and_story() -> None:
    """A27：payload 构造在隔离内——鸭子对象属性访问故障与 emit 故障同不被传播。

    `_emit_step_event` 是全仓唯一观测隔离包装（CLI 质量门事件共用）；宿主鸭子契约的
    step/story 属性访问抛错时只记 warning，绝不进业务控制流。
    """
    from types import SimpleNamespace
    from typing import Any

    class _Hostile:
        def __getattr__(self, name: str) -> Any:
            raise RuntimeError(f"hostile attribute: {name}")

    events: list[tuple[str, dict[str, Any]]] = []

    def emit(kind: str, *, details: dict[str, Any] | None = None) -> None:
        events.append((kind, details or {}))

    # 属性访问故障 → 隔离（不抛、零事件）
    _emit_step_event(emit, "workflow_step_started", step=_Hostile(), story=_Hostile())
    assert events == []

    # 同一包装的正常路径不受影响（payload 形状不变）
    _emit_step_event(emit, "workflow_step_completed", step=SimpleNamespace(name="step-01.md"), story=None)
    assert events[-1][0] == "workflow_step_completed"
    assert events[-1][1]["step"] == "step-01.md"
    assert events[-1][1]["story"] == ""


def test_bounded_reason_keeps_boundary_text_and_truncates_beyond_it() -> None:
    """A37：恰好 2000 字符不截断，超出 1 字符即截断并标记省略。

    2000 是行为契约（落盘体积上限），故意写成字面量而不是引用被测常量——改上限时
    本用例必须显式跟着改，否则等于把判据交给被测对象自己声明。
    """
    assert _bounded_reason("x" * 2000) == "x" * 2000
    truncated = _bounded_reason("x" * 2001)
    assert len(truncated) == 2000
    assert truncated.endswith("...")


@pytest.mark.asyncio
async def test_oversized_failure_reason_is_bounded_in_state_and_checkpoint(tmp_path) -> None:
    """A37：超长异常文本不得整段进 checkpoint（内存状态与落盘 next_action 都有硬上限）。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    async def callback(_step):
        raise RuntimeError("boom " + "x" * 5000)

    with pytest.raises(RuntimeError):
        await runner.run_step(callback)
    assert len(runner.state.reason) <= 2000
    assert runner.state.reason.startswith("boom ")
    assert runner.state.reason.endswith("...")
    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert checkpoints, "failure must persist a checkpoint"
    assert len(checkpoints[-1].next_action) <= 2000


def test_keyboard_interrupt_is_treated_as_user_cancellation() -> None:
    """A39：KI 与 CancelledError 同路（CANCELLED → PENDING，可恢复），不再落 FAILED。

    直接测吸收点：真实 KI 在 asyncio 任务内会被 ``Task.__step`` 重抛进事件循环，
    无法在 await 处断言终态（同 ``_BatchInterrupt`` 的既有说明）。
    """
    runner = WorkflowRunner(_workflow(WorkflowStepResource(index=1, name="step-01.md", instructions="")))
    runner.state = runner.state.model_copy(update={"status": WorkflowStatus.RUNNING})
    event = runner._absorb_step_exception(KeyboardInterrupt())
    assert event is WorkflowEvent.CANCELLED
    assert runner.state.status is WorkflowStatus.PENDING
    assert runner.state.reason == "cancelled"


def test_system_exit_is_treated_as_user_cancellation() -> None:
    """A39：SystemExit 同为用户取消（落 PENDING 可恢复），不被当成执行器故障。"""
    runner = WorkflowRunner(_workflow(WorkflowStepResource(index=1, name="step-01.md", instructions="")))
    runner.state = runner.state.model_copy(update={"status": WorkflowStatus.RUNNING})
    event = runner._absorb_step_exception(SystemExit(0))
    assert event is WorkflowEvent.CANCELLED
    assert runner.state.status is WorkflowStatus.PENDING


def _approval_step(index: int) -> WorkflowStepResource:
    return WorkflowStepResource(
        index=index, name=f"step-{index:02d}.md", instructions="", approval=StepApproval(required=True)
    )


@pytest.mark.asyncio
async def test_every_transition_records_the_event_that_drove_it(tmp_path) -> None:
    """A38：``last_event`` 与 ``status`` 同源写入，并随 checkpoint 落盘、可跨恢复读回。

    没有它，审计只能看到「状态不是 RUNNING」，看不到是完成、被取消还是执行器失败。
    """
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)

    await runner.run_step(lambda _: WorkflowStepResult(output="ok"))

    assert runner.state.status is WorkflowStatus.COMPLETED
    assert runner.state.last_event == WorkflowEvent.FINAL_STEP_COMPLETED.value
    checkpoint = (await store.list_checkpoints(goal_id="goal"))[-1]
    assert checkpoint.last_event == WorkflowEvent.FINAL_STEP_COMPLETED.value
    restored = WorkflowRunner.from_checkpoint(workflow, checkpoint, checkpoint_store=store)
    assert restored.state.last_event == WorkflowEvent.FINAL_STEP_COMPLETED.value


@pytest.mark.asyncio
async def test_old_checkpoint_without_last_event_still_loads(tmp_path) -> None:
    """AD-2：``last_event`` 是**追加的可选**字段——盘上没有该键的旧 checkpoint 照常加载。

    兼容性判据刻意手写一份「旧形状」JSON（而不是存一份新 checkpoint 再删键）：它钉的是
    「字段缺失」这一形态，任何把该字段改成必填的改动都会在这里变红。
    """
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    payload = {
        "checkpoint_id": "goal-run-step-1",
        "goal_id": "goal",
        "phase": WorkflowPhase.IMPLEMENTATION.value,
        "status": WorkflowStatus.PENDING.value,
        "run_id": "run",
        "active_step": 0,
        "completed_steps": [],
        "next_action": "legacy",
        "created_at": "2026-01-01T00:00:00.000000",
    }
    (checkpoint_dir / "goal-run-step-1.json").write_text(json.dumps(payload), encoding="utf-8")
    store = WorkflowCheckpointStore(str(checkpoint_dir), workflow_path=str(tmp_path / "workflow.json"))

    checkpoints = await store.list_checkpoints(goal_id="goal")

    assert len(checkpoints) == 1
    assert checkpoints[0].last_event == ""
    restored = WorkflowRunner.from_checkpoint(workflow, checkpoints[0], checkpoint_store=store)
    assert restored.state.last_event == ""


@pytest.mark.asyncio
async def test_failure_and_cancellation_events_name_their_transition_event() -> None:
    """A38：两种「非 RUNNING」终态事件各自标明驱动事件（失败与取消可区分）。"""
    workflow = _workflow(WorkflowStepResource(index=1, name="step-01.md", instructions=""))
    events: list[tuple[str, dict]] = []

    def emit(kind, *, details=None):
        events.append((kind, details or {}))

    async def boom(_step):
        raise RuntimeError("boom")

    runner = WorkflowRunner(workflow)
    with pytest.raises(RuntimeError):
        await runner.run_step(boom, emit=emit)
    assert events[-1][0] == "workflow_step_failed"
    assert events[-1][1]["transition_event"] == WorkflowEvent.EXECUTOR_FAILED.value
    assert runner.state.last_event == WorkflowEvent.EXECUTOR_FAILED.value

    async def cancel(_step):
        raise asyncio.CancelledError()

    runner = WorkflowRunner(workflow)
    events.clear()
    with pytest.raises(asyncio.CancelledError):
        await runner.run_step(cancel, emit=emit)
    assert events[-1][1]["transition_event"] == WorkflowEvent.CANCELLED.value
    assert runner.state.last_event == WorkflowEvent.CANCELLED.value


@pytest.mark.asyncio
async def test_approval_decisions_record_their_events_and_bound_the_note() -> None:
    """A38 + A37：挂门/批准/拒绝各自留痕；超长拒绝理由截断而不整段进状态。"""
    workflow = _workflow(_approval_step(1), WorkflowStepResource(index=2, name="step-02.md", instructions=""))

    events: list[tuple[str, dict]] = []

    def emit(kind, *, details=None):
        events.append((kind, details or {}))

    runner = WorkflowRunner(workflow)
    await runner.run_step(lambda _: WorkflowStepResult(output="draft"))
    assert runner.state.last_event == WorkflowEvent.APPROVAL_REQUIRED.value

    runner.approve(emit=emit)
    # 状态里留的是**最后**一次转换（批准后紧接完成簿记推进，落到 step_completed）；
    # 批准这个事件本身由观测事件承载——两处合起来才没有信息缺口。
    assert [kind for kind, _ in events] == ["workflow_approved"]
    assert events[0][1]["transition_event"] == WorkflowEvent.USER_APPROVE.value
    assert runner.state.last_event == WorkflowEvent.STEP_COMPLETED.value

    rejected = WorkflowRunner(workflow)
    await rejected.run_step(lambda _: WorkflowStepResult(output="draft"))
    rejected.reject("x" * 5000)
    assert rejected.state.last_event == WorkflowEvent.USER_REJECT.value
    assert rejected.state.status is WorkflowStatus.BLOCKED
    assert len(rejected.state.reason) == 2000
    assert rejected.state.reason.endswith("...")


@pytest.mark.asyncio
async def test_batch_failure_reason_is_bounded_and_records_the_event() -> None:
    """A37 补漏 + A38：批结算失败路径同样截断，并记录 executor_failed。

    批路径的 ``reason`` 与串行路径同属「状态写点」，漏了它就等于给长 traceback 留了
    一条绕过上限的通道。
    """
    workflow = _workflow(
        WorkflowStepResource(index=1, name="step-01.md", instructions="", story_loop="epics.md", max_parallel_stories=2)
    )
    stories = [
        StorySpec(id="S-1", summary="One", epic="E1", parallel_group="g", write_set=["src/a.py"]),
        StorySpec(id="S-2", summary="Two", epic="E1", parallel_group="g", write_set=["src/b.py"]),
    ]

    async def callback(_step, story, _execution):
        if story.id == "S-2":
            raise RuntimeError("boom " + "x" * 5000)
        return WorkflowStepResult(output=story.id)

    runner = WorkflowRunner(workflow)
    with pytest.raises(RuntimeError, match="boom"):
        await runner.run_step(callback, stories=stories)

    assert runner.state.status is WorkflowStatus.FAILED
    assert runner.state.last_event == WorkflowEvent.EXECUTOR_FAILED.value
    assert len(runner.state.reason) == 2000
    assert runner.state.reason.startswith("boom ")
    assert runner.state.reason.endswith("...")
