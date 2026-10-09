"""Epic 52 Story 52-2：批次调度器与 Runner 并行执行语义（AD-16..19）。

覆盖：七条件批派生正反矩阵、并发执行与峰值并发、按声明序记账/合并、批=单 checkpoint
单元（RUNNING 中间快照 + 单次终态转换）、批内失败不连坐、步骤级取消整批 PENDING、
write_violation 撤销闩持久化、`workflow_story_batch_scheduled` 事件、老回调/限 1 步骤零变化。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from heagent.engine.checkpoint import (
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.engine.workflow_runner import WorkflowRunner, WorkflowRunnerState, WorkflowStepResult
from heagent.goal.workflow_loader import parse_story_list

if TYPE_CHECKING:
    from heagent.pub.types import StoryExecutionContext

# 三条互相写集不相交、同组、无依赖的 story：limit≥3 时构成一个完整批。
DISJOINT = """## E1
### S-1 First
- depends_on: []
- parallel_group: g
- write_set: [src/a.py]
### S-2 Second
- depends_on: []
- parallel_group: g
- write_set: [src/b.py]
### S-3 Third
- depends_on: []
- parallel_group: g
- write_set: [src/c.py]
"""


def _workflow(limit: int = 3, *, checkpoint_declared: bool = False) -> WorkflowResource:
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
                checkpoint="true" if checkpoint_declared else "",
            )
        ],
    )


def _store(tmp_path: Any) -> WorkflowCheckpointStore:
    return WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))


def _stats() -> dict[str, int]:
    return {"active": 0, "peak": 0}


def _parallel_callback(stats: dict[str, int], *, seen: list[str] | None = None, dwell: float = 0.01):
    """三参回调：记录峰值并发与进入序；execution 缺省 None 兼容串行调用。"""

    async def callback(step: Any, story: Any, execution: StoryExecutionContext | None = None) -> WorkflowStepResult:
        stats["active"] += 1
        stats["peak"] = max(stats["peak"], stats["active"])
        if seen is not None:
            seen.append(story.id)
        await asyncio.sleep(dwell)
        stats["active"] -= 1
        return WorkflowStepResult(output=story.id)

    return callback


def _variant(replacement: str, count: int = 1) -> str:
    text = DISJOINT
    for _ in range(count):
        text = text.replace("- write_set: [src/b.py]", replacement, 1)
    return text


# ── 正路：授权批真实并发 + 按声明序记账 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_disjoint_batch_runs_parallel_and_books_in_declaration_order(tmp_path) -> None:
    store = _store(tmp_path)
    runner = WorkflowRunner(_workflow(limit=3), goal_id="goal", run_id="run", checkpoint_store=store)
    stats = _stats()
    seen: list[str] = []
    write_of = {"S-1": "src/a.py", "S-2": "src/b.py", "S-3": "src/c.py"}

    async def callback(step: Any, story: Any, execution: StoryExecutionContext | None) -> WorkflowStepResult:
        stats["active"] += 1
        stats["peak"] = max(stats["peak"], stats["active"])
        seen.append(story.id)
        # S-1 最慢：完成序 S-2 → S-3 → S-1，合并序仍必须是声明序。
        await asyncio.sleep(0.05 if story.id == "S-1" else 0.0)
        stats["active"] -= 1
        assert execution is not None
        assert execution.parallel is True
        assert execution.batch_members == ["S-1", "S-2", "S-3"]
        assert execution.write_allowlist == [write_of[story.id]]
        return WorkflowStepResult(output=story.id)

    stories = parse_story_list(DISJOINT)
    result = await runner.run_step(callback, stories=stories)

    assert stats["peak"] == 3
    assert runner.done
    assert result.executed_stories == ["S-1", "S-2", "S-3"]
    assert result.output == "S-1\n\n---\n\nS-2\n\n---\n\nS-3"
    assert result.status is WorkflowStatus.COMPLETED
    assert runner.state.completed_stories == []  # 步骤收口后 story 簿记清场
    assert runner.state.outputs["implement"] == "S-1\n\n---\n\nS-2\n\n---\n\nS-3"


@pytest.mark.asyncio
async def test_batch_intermediate_checkpoints_and_declared_order_outputs(tmp_path) -> None:
    """批=单 checkpoint 单元：成员按声明序逐个落 RUNNING 快照，终态只转换一次。"""
    store = _store(tmp_path)
    runner = WorkflowRunner(
        _workflow(limit=2, checkpoint_declared=True), goal_id="goal", run_id="run", checkpoint_store=store
    )
    stories = parse_story_list(DISJOINT)
    stats = _stats()
    await runner.run_step(_parallel_callback(stats), stories=stories)

    # limit=2：第一批 [S-1, S-2]（S-3 下轮）。快照链：S-1、S-2 各一条 RUNNING 中间快照，
    # 末条是批终态（checkpoint 声明 → WAITING_USER，每批一次人工确认）。
    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert [checkpoint.completed_stories for checkpoint in checkpoints] == [
        ["S-1"],
        ["S-1", "S-2"],
        ["S-1", "S-2"],
    ]
    assert [checkpoint.status for checkpoint in checkpoints] == [
        WorkflowStatus.RUNNING,
        WorkflowStatus.RUNNING,
        WorkflowStatus.WAITING_USER,
    ]
    assert runner.state.status is WorkflowStatus.WAITING_USER
    assert runner.state.story_index == 2
    runner.resume()
    stats2 = _stats()
    await runner.run_step(_parallel_callback(stats2), stories=stories)
    assert stats2["peak"] == 1  # S-3 单条：串行路径
    assert runner.done


@pytest.mark.asyncio
async def test_batch_scheduled_event_carries_members_and_limit(tmp_path) -> None:
    store = _store(tmp_path)
    runner = WorkflowRunner(_workflow(limit=2), goal_id="goal", run_id="run", checkpoint_store=store)
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(kind: str, *, details: dict[str, Any] | None = None) -> None:
        events.append((kind, details or {}))

    await runner.run_step(_parallel_callback(_stats()), stories=parse_story_list(DISJOINT), emit=emit)
    scheduled = [details for kind, details in events if kind == "workflow_story_batch_scheduled"]
    assert scheduled and scheduled[0]["members"] == ["S-1", "S-2"]
    assert scheduled[0]["limit"] == 2


@pytest.mark.asyncio
async def test_batch_scheduled_event_isolation(tmp_path) -> None:
    """观测 sink 故障不得改变业务控制流（既有 emit 隔离契约在批事件上同样成立）。"""

    def emit(kind: str, *, details: dict[str, Any] | None = None) -> None:
        raise RuntimeError("sink down")

    runner = WorkflowRunner(_workflow(limit=3), goal_id="goal", run_id="run")
    result = await runner.run_step(_parallel_callback(_stats()), stories=parse_story_list(DISJOINT), emit=emit)
    assert result.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_execution_context_carries_sibling_write_sets(tmp_path) -> None:
    captured: dict[str, StoryExecutionContext | None] = {}

    async def callback(step: Any, story: Any, execution: StoryExecutionContext | None) -> WorkflowStepResult:
        captured[story.id] = execution
        await asyncio.sleep(0)
        return WorkflowStepResult(output=story.id)

    await WorkflowRunner(_workflow(limit=3)).run_step(callback, stories=parse_story_list(DISJOINT))
    assert captured["S-1"] is not None
    assert captured["S-1"].sibling_write_sets == {"S-2": ["src/b.py"], "S-3": ["src/c.py"]}
    assert captured["S-2"] is not None
    assert captured["S-2"].sibling_write_sets == {"S-1": ["src/a.py"], "S-3": ["src/c.py"]}


# ── 七条件反例：任一不满足 → 峰值并发 1（fail-closed 串行） ────────────────────


@pytest.mark.asyncio
async def test_limit_one_step_keeps_serial_path_and_none_execution(tmp_path) -> None:
    """限 1 步骤走既有串行路径：三参回调收到的 execution 是 None（零变化）。"""
    captured: list[StoryExecutionContext | None] = []

    async def callback(step: Any, story: Any, execution: StoryExecutionContext | None = None) -> WorkflowStepResult:
        captured.append(execution)
        await asyncio.sleep(0)
        return WorkflowStepResult(output=story.id)

    stats = _stats()
    stories = parse_story_list(DISJOINT)
    runner = WorkflowRunner(_workflow(limit=1))
    for _ in stories:
        await runner.run_step(_wrap_stats(callback, stats), stories=stories)
    assert stats["peak"] == 1
    assert captured == [None, None, None]


def _wrap_stats(callback: Any, stats: dict[str, int]):
    async def wrapped(step: Any, story: Any, execution: StoryExecutionContext | None = None) -> WorkflowStepResult:
        stats["active"] += 1
        stats["peak"] = max(stats["peak"], stats["active"])
        try:
            return await callback(step, story, execution)
        finally:
            stats["active"] -= 1

    return wrapped


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stories_text",
    [
        # 写集相同（直接相交）
        _variant("- write_set: [src/a.py]"),
        # 写集包含（目录含文件：src 覆盖 src/a.py）
        _variant("- write_set: [src]"),
        # parallel_group 不同
        DISJOINT.replace(
            "- parallel_group: g\n- write_set: [src/b.py]", "- parallel_group: h\n- write_set: [src/b.py]"
        ),
        # 第二条缺 write_set（写集未知 = 串行）
        DISJOINT.replace("- parallel_group: g\n- write_set: [src/b.py]", "- parallel_group: g"),
        # 依赖批内成员（依赖并发中的 Story 不可证安全）
        DISJOINT.replace("### S-2 Second\n- depends_on: []", "### S-2 Second\n- depends_on: [S-1]"),
    ],
)
async def test_non_conforming_declarations_degrade_to_serial(stories_text: str, tmp_path) -> None:
    """反例只保留两条 story：S-2 不合规 ⇒ 批止步于 [S-1]，全程串行。

    （不裁第三条的话，S-2/S-3 在后续轮次合法成批、峰值会到 2——那是授权语义的正确
    行为，不是本用例的对象。）
    """
    runner = WorkflowRunner(_workflow(limit=3), goal_id="goal", run_id="run")
    stats = _stats()
    seen: list[str] = []
    callback = _parallel_callback(stats, seen=seen, dwell=0.0)
    stories = parse_story_list(stories_text)[:2]
    for _ in stories:
        await runner.run_step(callback, stories=stories)
    assert stats["peak"] == 1
    assert seen == ["S-1", "S-2"]


@pytest.mark.asyncio
async def test_revoked_latch_forces_serial_until_recovered(tmp_path) -> None:
    store = _store(tmp_path)
    state = WorkflowRunnerState(story_parallel_revoked=True)
    runner = WorkflowRunner(_workflow(limit=3), state=state, goal_id="goal", run_id="run", checkpoint_store=store)
    stats = _stats()
    seen: list[str] = []
    callback = _parallel_callback(stats, seen=seen, dwell=0.0)
    stories = parse_story_list(DISJOINT)
    for _ in stories:
        await runner.run_step(callback, stories=stories)
    assert stats["peak"] == 1
    assert seen == ["S-1", "S-2", "S-3"]


@pytest.mark.asyncio
async def test_legacy_two_param_callback_stays_serial(tmp_path) -> None:
    """两参老回调 = 未实现围栏+审计契约 → fail-closed 串行（授权条件 3）。"""
    runner = WorkflowRunner(_workflow(limit=3), goal_id="goal", run_id="run")
    stats = _stats()

    async def callback(step: Any, story: Any) -> WorkflowStepResult:
        stats["active"] += 1
        stats["peak"] = max(stats["peak"], stats["active"])
        await asyncio.sleep(0.01)
        stats["active"] -= 1
        return WorkflowStepResult(output=story.id)

    stories = parse_story_list(DISJOINT)
    for _ in stories:
        await runner.run_step(callback, stories=stories)
    assert stats["peak"] == 1


@pytest.mark.asyncio
async def test_limit_caps_batch_size(tmp_path) -> None:
    """limit=2 时三条合规 story 分两轮：峰值 2，不是 3。"""
    runner = WorkflowRunner(_workflow(limit=2), goal_id="goal", run_id="run")
    stats = _stats()
    callback = _parallel_callback(stats, dwell=0.01)
    stories = parse_story_list(DISJOINT)
    while not runner.done:
        await runner.run_step(callback, stories=stories)
        suspended = runner.state.status in {WorkflowStatus.PENDING, WorkflowStatus.WAITING_USER, WorkflowStatus.FAILED}
        if suspended and not runner.done:
            runner.resume()
    assert stats["peak"] == 2


# ── 批内失败 / 取消 / 撤销闩 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_failure_does_not_cancel_batch_and_resume_rederives(tmp_path) -> None:
    store = _store(tmp_path)
    runner = WorkflowRunner(_workflow(limit=2), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = parse_story_list(DISJOINT)

    async def callback(step: Any, story: Any, execution: StoryExecutionContext | None) -> WorkflowStepResult:
        await asyncio.sleep(0)
        if story.id == "S-2":
            raise RuntimeError("story S-2 exploded")
        return WorkflowStepResult(output=story.id)

    with pytest.raises(RuntimeError, match="S-2"):
        await runner.run_step(callback, stories=stories)

    assert runner.state.status is WorkflowStatus.FAILED
    # 完成者入账（事实就是事实，允许有洞），失败者如实记 failed，位置停首个未完成。
    assert runner.state.completed_stories == ["S-1"]
    assert runner.state.story_outputs == {"S-1": "S-1"}
    assert runner.state.story_statuses == {"S-1": "completed", "S-2": "failed"}
    assert runner.state.story_index == 1

    # 恢复：重推导跳过已完成成员（S-1 不重跑）；S-2/S-3 合规 ⇒ 组成新批并发跑完并收口。
    checkpoints = await store.list_checkpoints(goal_id="goal")
    failed = next(checkpoint for checkpoint in checkpoints if checkpoint.status is WorkflowStatus.FAILED)
    resumed = WorkflowRunner.from_checkpoint(_workflow(limit=2), failed)
    resumed.resume()
    seen: list[str] = []
    result = await resumed.run_step(_parallel_callback(_stats(), seen=seen, dwell=0.0), stories=stories)
    assert seen == ["S-2", "S-3"]
    assert result.status is WorkflowStatus.COMPLETED
    assert resumed.done
    assert resumed.state.outputs["implement"] == "S-1\n\n---\n\nS-2\n\n---\n\nS-3"


@pytest.mark.asyncio
async def test_step_cancel_puts_whole_batch_pending_and_records_cancelled(tmp_path) -> None:
    runner = WorkflowRunner(_workflow(limit=3), goal_id="goal", run_id="run")
    entered = asyncio.Event()

    async def callback(step: Any, story: Any, execution: StoryExecutionContext | None) -> WorkflowStepResult:
        entered.set()
        await asyncio.sleep(5)

    task = asyncio.ensure_future(runner.run_step(callback, stories=parse_story_list(DISJOINT)))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runner.state.status is WorkflowStatus.PENDING
    assert set(runner.state.story_statuses.values()) == {"cancelled"}


@pytest.mark.asyncio
async def test_write_violation_latches_and_persists(tmp_path) -> None:
    store = _store(tmp_path)
    runner = WorkflowRunner(_workflow(limit=2), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = parse_story_list(DISJOINT)

    async def callback(step: Any, story: Any, execution: StoryExecutionContext | None) -> WorkflowStepResult:
        await asyncio.sleep(0)
        if story.id == "S-1":
            return WorkflowStepResult(
                status=WorkflowStatus.FAILED,
                reason="write outside the declared write set: docs/leak.md",
                write_violation=True,
            )
        return WorkflowStepResult(output=story.id)

    result = await runner.run_step(callback, stories=stories)
    assert result.status is WorkflowStatus.FAILED
    assert runner.state.story_parallel_revoked is True

    checkpoints = await store.list_checkpoints(goal_id="goal")
    failed = next(checkpoint for checkpoint in checkpoints if checkpoint.status is WorkflowStatus.FAILED)
    assert failed.story_parallel_revoked is True

    # 恢复后闩仍生效：同 Goal 不再并行（撤销的是并发授权；围栏由宿主按声明继续生效）。
    # 串行重跑从首个未完成（S-1，违规者本身）开始，跳过批内已完成的 S-2。
    resumed = WorkflowRunner.from_checkpoint(_workflow(limit=2), failed)
    assert resumed.state.story_parallel_revoked is True
    resumed.resume()
    stats = _stats()
    seen: list[str] = []
    for _ in stories:
        await resumed.run_step(_parallel_callback(stats, seen=seen, dwell=0.01), stories=stories)
    assert stats["peak"] == 1
    assert seen == ["S-1", "S-3"]


# ── 兼容性：老 checkpoint 形态 + 签名探测 ─────────────────────────────────────


def test_from_checkpoint_defaults_revoked_latch_false() -> None:
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="c1", goal_id="g", phase=WorkflowPhase.IMPLEMENTATION, status=WorkflowStatus.PENDING, run_id="r"
    )
    runner = WorkflowRunner.from_checkpoint(_workflow(limit=2), checkpoint)
    assert runner.state.story_parallel_revoked is False


def test_accepts_execution_probe() -> None:
    def two(step: Any, story: Any) -> WorkflowStepResult:  # pragma: no cover - signature probe
        raise NotImplementedError

    def three(step: Any, story: Any, execution: StoryExecutionContext | None) -> WorkflowStepResult:  # pragma: no cover
        raise NotImplementedError

    def varargs(*args: Any) -> WorkflowStepResult:  # pragma: no cover - signature probe
        raise NotImplementedError

    assert WorkflowRunner._accepts_execution(two) is False
    assert WorkflowRunner._accepts_execution(three) is True
    # *args 宽签名不算实现契约（fail-closed：测试桩不得借 varargs 意外获得并发授权）。
    assert WorkflowRunner._accepts_execution(varargs) is False


@pytest.mark.asyncio
async def test_legacy_parallel_checkpoint_id_still_recovers(tmp_path) -> None:
    """51-8 的兼容锚点保持：批次恢复不按 id 找快照（回归保护）。"""
    store = _store(tmp_path)
    runner = WorkflowRunner(
        _workflow(limit=2, checkpoint_declared=True), goal_id="goal", run_id="run", checkpoint_store=store
    )
    stories = parse_story_list(DISJOINT)
    await runner.run_step(_parallel_callback(_stats()), stories=stories)
    checkpoints = await store.list_checkpoints(goal_id="goal")
    restored = WorkflowRunner.from_checkpoint(_workflow(limit=2, checkpoint_declared=True), checkpoints[-1])
    assert restored.state.story_index == 2
    assert restored.state.completed_stories == ["S-1", "S-2"]


@pytest.mark.asyncio
async def test_serial_context_violation_also_latches(tmp_path) -> None:
    """串行-with-context 的审计判负同样置闩（评审 P7，AD-18 Goal 级语义）。

    写集相交声明 → 批派生坍缩 [S-1] → 串行分支仍带 execution；判负 FAILED 经串行收口
    （非批结算路径）也必须撤销并发授权，否则后续可并发的兄弟不受该违规约束。"""
    store = _store(tmp_path)
    runner = WorkflowRunner(_workflow(limit=2), goal_id="goal", run_id="run", checkpoint_store=store)
    overlapped = DISJOINT.replace("- write_set: [src/b.py]", "- write_set: [src/a.py]")
    contexts: list[StoryExecutionContext | None] = []

    async def callback(step: Any, story: Any, execution: StoryExecutionContext | None = None) -> WorkflowStepResult:
        contexts.append(execution)
        if story.id == "S-1":
            return WorkflowStepResult(status=WorkflowStatus.FAILED, reason="out of set", write_violation=True)
        return WorkflowStepResult(output=story.id)

    result = await runner.run_step(callback, stories=parse_story_list(overlapped))

    assert result.status is WorkflowStatus.FAILED
    assert runner.state.story_parallel_revoked is True
    assert contexts[0] is not None and contexts[0].parallel is False


@pytest.mark.asyncio
async def test_violation_latch_keeps_execution_on_serial_rerun(tmp_path) -> None:
    """闩只撤销批派生、不撤销执行上下文（评审 P1，AD-18「闩不撤销围栏」）。

    闩置位后重推：批恒空（peak 1），但宿主仍收非 None execution（围栏输入 + 审计通道）。"""
    store = _store(tmp_path)
    runner = WorkflowRunner(_workflow(limit=2), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = parse_story_list(DISJOINT)

    async def violator(step: Any, story: Any, execution: StoryExecutionContext | None = None) -> WorkflowStepResult:
        return WorkflowStepResult(status=WorkflowStatus.FAILED, reason="violation", write_violation=True)

    await runner.run_step(violator, stories=stories)
    assert runner.state.story_parallel_revoked is True

    checkpoints = await store.list_checkpoints(goal_id="goal")
    failed = next(checkpoint for checkpoint in checkpoints if checkpoint.status is WorkflowStatus.FAILED)
    resumed = WorkflowRunner.from_checkpoint(_workflow(limit=2), failed, checkpoint_store=store)
    resumed.resume()
    stats = _stats()
    contexts: list[StoryExecutionContext | None] = []

    async def probe(step: Any, story: Any, execution: StoryExecutionContext | None = None) -> WorkflowStepResult:
        contexts.append(execution)
        stats["active"] += 1
        stats["peak"] = max(stats["peak"], stats["active"])
        await asyncio.sleep(0.0)
        stats["active"] -= 1
        return WorkflowStepResult(output=story.id)

    for _ in stories:
        await resumed.run_step(probe, stories=stories)

    assert stats["peak"] == 1  # 闩后批派生恒空 → 串行
    assert all(context is not None for context in contexts)  # 但执行上下文不撤（围栏+审计继续）
