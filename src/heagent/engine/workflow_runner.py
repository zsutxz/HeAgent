"""声明式 Markdown 工作流的确定性单步 runner。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any
from uuid import uuid4

from heagent.engine.checkpoint import (
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)
from heagent.engine.observability import _emit_step_event, elapsed_ms
from heagent.engine.state_machine import (
    _CANCEL_EXCEPTIONS,
    _MAX_REASON_CHARS,
    WorkflowGateError,
    WorkflowRunnerState,
    WorkflowRunResult,
    WorkflowStepResult,
    _approval_gate_update,
    _approve_state,
    _bounded_reason,
    _callback_event,
    _cancel_or_failure_event,
    _checkpoint_declared,
    _combine_story_outputs,
    _completion_update,
    _decision_state,
    _is_done,
    _pause_state,
    _references,
    _resume_update,
    _step_advance_update,
    _stop_event,
    _story_reset_update,
    _transition_fields,
    _validate_state,
)
from heagent.engine.story_batch import (
    _accepts_execution,
    _execution_context,
    _gather_story_batch,
    _invoke_callback,
    _parallel_batch,
    write_set_entries_overlap,
    write_set_parts,
)
from heagent.engine.workflow_events import WorkflowEvent
from heagent.engine.workflow_resource import (
    WorkflowResource,
    WorkflowStepResource,
    output_contains_section,
    section_titles,
)
from heagent.events.protocol import error_kind_for
from heagent.pub.exceptions import WorkflowExecutionError
from heagent.pub.safe_logging import safe_log
from heagent.pub.types import StoryExecutionContext, StorySpec

__all__ = [
    "_CANCEL_EXCEPTIONS",
    "_MAX_REASON_CHARS",
    "_emit_step_event",
    "write_set_entries_overlap",
    "write_set_parts",
    "WorkflowGateError",
    "WorkflowRunner",
    "WorkflowRunnerState",
    "WorkflowRunResult",
    "WorkflowStepResult",
    "StorySpec",
    "required_sections",
]

logger = logging.getLogger(__name__)


def required_sections(validation_rules: str | None) -> list[str]:
    """Return the ``section:`` headings a step output must contain.

    Single parser shared by the post-step output gate and the pre-step prompt: an
    executor has to be told the exact headings it will be judged on, otherwise a
    long step can finish all its work and still be blocked on a heading it never
    saw. 实现委托给 :func:`heagent.engine.workflow_resource.section_titles`（单一真源，
    ``goal/workflow_loader`` 的子句解析同源），本函数保留为既有公开 API。
    """
    return section_titles(validation_rules)


WorkflowCallback = Callable[[WorkflowStepResource], WorkflowStepResult | Awaitable[WorkflowStepResult]]
StoryWorkflowCallback = Callable[[WorkflowStepResource, StorySpec], WorkflowStepResult | Awaitable[WorkflowStepResult]]
CheckpointCallback = Callable[[WorkflowRunnerState], Awaitable[None] | None]


class WorkflowRunner:
    """只运行一个 workflow 步骤，且绝不合成「完成」状态。

    步骤声明是权威。回调返回非完成结果时活动步保持不变，调用方因此可在 checkpoint
    之后恢复。

    一个步骤可以声明 ``story_loop: <artifact>``；这样的步骤会展开成「每个 story 调用
    一次回调」（每次都是可独立 checkpoint 的增量），并且只有在全部 story 完成后才推进该步。
    """

    def __init__(
        self,
        workflow: WorkflowResource,
        state: WorkflowRunnerState | None = None,
        *,
        goal_id: str | None = None,
        run_id: str | None = None,
        checkpoint_store: WorkflowCheckpointStore | None = None,
        phase: WorkflowPhase = WorkflowPhase.IMPLEMENTATION,
    ) -> None:
        if not workflow.steps:
            raise WorkflowExecutionError("workflow requires at least one step")
        self.workflow = workflow
        self.state = state or WorkflowRunnerState()
        self.goal_id = goal_id or uuid4().hex[:8]
        self.run_id = run_id or uuid4().hex
        self.checkpoint_store = checkpoint_store
        self.phase = phase
        _validate_state(self.state, self.workflow)

    @classmethod
    def from_checkpoint(
        cls, workflow: WorkflowResource, checkpoint: WorkflowCheckpoint, **kwargs: Any
    ) -> WorkflowRunner:
        """Restore runner progress from a persisted checkpoint.

        RUNNING 快照归一化为 PENDING（Epic 52 Story 52-5）：RUNNING 只在步骤执行中存在，
        而能落盘的 RUNNING 只可能来自批结算中段的逐成员快照（崩溃/取消路径在落盘前已按
        转换表收敛到 PENDING/FAILED，见 ``_absorb_step_exception``）——盘上见到 RUNNING 即
        「进程死在步骤中段」。转换表没有 RUNNING 的再入口（``START`` 只接 PENDING），
        唯一可恢复语义是重新驱动本步骤：归一化为 PENDING 后由批派生跳过已完成成员续跑。
        显性注释而非静默兜底：这是确定性的崩溃恢复语义，不是吞错。
        """
        restored_status = (
            checkpoint.status if checkpoint.status is not WorkflowStatus.RUNNING else WorkflowStatus.PENDING
        )
        state = WorkflowRunnerState(
            active_step=checkpoint.active_step if checkpoint.active_step is not None else len(workflow.steps),
            status=restored_status,
            completed_steps=list(checkpoint.completed_steps),
            # `outputs` 是产物键表的唯一载体；旧字段的 `{reference: None}` 兜底在「artifact_refs
            # 恒等于 list(outputs)」不变量下不可达且等值（两边同空），随镜像派生化一并删除。
            outputs=dict(checkpoint.outputs),
            acceptance_evidence=list(checkpoint.acceptance_evidence),
            reason=_bounded_reason(checkpoint.next_action),
            active_story=checkpoint.active_story,
            active_epic=checkpoint.active_epic,
            story_index=checkpoint.story_index if checkpoint.story_index is not None else 0,
            completed_stories=list(checkpoint.completed_stories),
            story_outputs=dict(checkpoint.story_outputs),
            story_statuses=dict(checkpoint.story_statuses),
            awaiting_approval=checkpoint.awaiting_approval,
            pending_output=checkpoint.pending_output,
            approval_round=checkpoint.approval_round,
            requested_steps=list(checkpoint.requested_steps),
            story_parallel_revoked=checkpoint.story_parallel_revoked,
            last_event=checkpoint.last_event,
            transition_reason=checkpoint.transition_reason,
        )
        kwargs.setdefault("phase", checkpoint.phase)
        return cls(workflow, state, goal_id=checkpoint.goal_id, run_id=checkpoint.run_id, **kwargs)

    @property
    def done(self) -> bool:
        """工作流是否已真正走完：状态为 completed **且** 步骤游标已越过最后一步。

        两个条件缺一不可——只看状态会在「最后一步完成但游标未推进」时提前收尾，只看
        游标会把被取消/失败的工作流也当完成。只读投影，不触发跃迁。
        """
        return _is_done(self.state, len(self.workflow.steps))

    async def run_step(  # noqa: C901 - story-loop safety gates share the single runner transition point
        self,
        callback: WorkflowCallback | StoryWorkflowCallback,
        *,
        inputs: Mapping[str, Any] | Iterable[str] | None = None,
        artifacts: Mapping[str, Any] | Iterable[str] | None = None,
        checkpoint: CheckpointCallback | None = None,
        stories: Iterable[StorySpec] | None = None,
        emit: Callable[..., None] | None = None,
    ) -> WorkflowRunResult:
        """Invoke the callback once for the active step (or the active story).

        ``emit``（Phase 5 C1，可选注入）：``emit(kind, *, details=None)`` 形状的观测端口，
        步骤粒度发 ``workflow_step_started/completed/failed``（``duration_ms`` / ``error_kind``
        经 details 由传输层提升）。缺省 ``None`` = 零行为变化（既有调用方/测试不动）；
        emit 内部异常隔离（对齐 sink 先例：可观测性不得改变业务控制流）。
        """
        if not callable(callback):
            raise TypeError("step callback must be callable")
        if self.done:
            return WorkflowRunResult(status=WorkflowStatus.COMPLETED, step_index=None, reason="workflow is complete")
        if self.state.status in {WorkflowStatus.WAITING_USER, WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
            return WorkflowRunResult(
                status=self.state.status, step_index=self.state.active_step, reason=self.state.reason
            )
        step = self.workflow.steps[self.state.active_step]
        missing = self._missing_inputs(step, inputs or artifacts or {})
        if missing:
            return await self._stop(
                WorkflowStatus.BLOCKED, step, "missing required inputs: " + ", ".join(missing), missing, checkpoint
            )
        is_story_loop = self._is_story_step(step)
        try:
            story_specs = self._resolve_stories(step, stories)
        except WorkflowGateError as exc:
            return await self._stop(WorkflowStatus.BLOCKED, step, str(exc), [], checkpoint)
        active_story: StorySpec | None = None
        batch: list[StorySpec] = []
        execution: StoryExecutionContext | None = None
        if is_story_loop:
            blocked = await self._blocked_story_dependency(step, story_specs, checkpoint)
            if blocked is not None:
                return blocked
            active_story = story_specs[self.state.story_index]
            self.state = self.state.model_copy(
                update={
                    "active_story": active_story.id,
                    "active_epic": active_story.epic,
                }
            )
            # 声明门控并行：上限 >1 且回调实现执行上下文契约才构造
            # execution；撤销闩只撤销**批派生**（batch 置空），不撤销 execution——闩后串行
            # 重跑仍带围栏输入与审计（闩撤销的是并发授权，不撤销围栏）。
            # 未声明 max_parallel_stories>1 或老回调时 execution 为 None——串行路径与既有串行语义
            # 逐字节一致（派生结果长度 1 时同样走串行分支，见下方 ``len(batch) > 1`` 分叉）。
            if step.max_parallel_stories > 1 and _accepts_execution(callback):
                batch = [] if self.state.story_parallel_revoked else _parallel_batch(self.state, step, story_specs)
                execution = _execution_context(active_story, batch)

        started = time.perf_counter()
        _emit_step_event(emit, "workflow_step_started", step=step, story=active_story)
        self.state = self.state.model_copy(update=_transition_fields(self.state, WorkflowEvent.START))
        results: list[Any] = []
        try:
            if len(batch) > 1:
                results = await _gather_story_batch(step, batch, callback, emit)
            else:
                result = _invoke_callback(callback, step, active_story, execution)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, WorkflowStepResult):
                    raise TypeError("step callback must return WorkflowStepResult")
        except BaseException as exc:
            # 批的取消窗口覆盖整段并发执行：步骤级取消传播取消整批，未落账成员如实记
            # cancelled（不谎报 failed）；串行成员维持既有语义（取消/失败二分）。
            transition_event = self._absorb_step_exception(exc)
            cancelled = transition_event is WorkflowEvent.CANCELLED
            if active_story is not None:
                if len(batch) > 1:
                    for member in batch:
                        self._record_story_status(member.id, WorkflowEvent.CANCELLED.value)
                else:
                    # 取消（可恢复，步骤落 PENDING）与失败（FAILED）的 story 状态如实区分，
                    # 不与步骤状态表矛盾；取消没有独立状态值，用事件词汇表。
                    # 判定口径与 _absorb_step_exception 同源：KI / SystemExit 也算取消。
                    story_status = WorkflowEvent.CANCELLED.value if cancelled else WorkflowStatus.FAILED.value
                    self._record_story_status(active_story.id, story_status)
            _emit_step_event(
                emit,
                "workflow_step_failed",
                step=step,
                story=active_story,
                duration_ms=elapsed_ms(started),
                error_kind=error_kind_for(exc),
                error=_bounded_reason(str(exc)),
                transition_event=transition_event.value,
            )
            await self._persist_interrupted(step, checkpoint)
            raise
        if len(batch) > 1:
            return await self._settle_story_batch(step, story_specs, batch, results, emit, started, checkpoint)
        _emit_step_event(
            emit,
            "workflow_step_completed",
            step=step,
            story=active_story,
            duration_ms=elapsed_ms(started),
            result=result.status.value,
        )
        # 异常路径在上方 except 分支落 "failed"；这里收口正常路径的结果状态。
        if active_story is not None:
            self._record_story_status(active_story.id, result.status.value)

        executed_story_id: str | None = None
        executed_story_index: int | None = None
        if result.status is WorkflowStatus.COMPLETED:
            try:
                self._validate_output(step, result.output)
            except WorkflowGateError as exc:
                return await self._stop(WorkflowStatus.BLOCKED, step, str(exc), [], checkpoint)
            # 脚本声明的后续步骤计划：累计计划不得超过本 workflow 的声明步骤数。
            if len(self.state.requested_steps) + len(result.requested_steps) > len(self.workflow.steps):
                return await self._refuse_oversized_plan(step, len(result.requested_steps), "step", checkpoint)
            executed_story_id = active_story.id if active_story is not None else None
            executed_story_index = self.state.story_index if is_story_loop else None
            update: dict[str, Any] = {
                "acceptance_evidence": [*self.state.acceptance_evidence, *result.evidence],
                # FIFO 追加：本步声明的后续步骤排在已有计划之后（先来先执行，顺序可预期）。
                "requested_steps": [*self.state.requested_steps, *result.requested_steps],
            }
            update.update(
                _completion_update(
                    self.state,
                    step,
                    story_specs,
                    len(self.workflow.steps),
                    result.output,
                    is_story_loop=is_story_loop,
                    reason=result.reason,
                )
            )
            self.state = self.state.model_copy(update=update)
        else:
            update = {
                **_transition_fields(self.state, _callback_event(result.status), reason=result.reason),
                "reason": _bounded_reason(result.reason),
            }
            if result.write_violation:
                # 串行-with-context 的审计判负同样撤销并发授权（Goal 级语义；
                # 批路径在 _settle_story_batch 置闩，此处是串行收口的对称写点）。
                update["story_parallel_revoked"] = True
            self.state = self.state.model_copy(update=update)

        checkpoint_id = await self._persist(step, checkpoint)
        return WorkflowRunResult(
            status=self.state.status,
            step_index=step.index,
            output=result.output,
            reason=result.reason,
            acceptance_evidence=result.evidence,
            checkpoint_id=checkpoint_id,
            story_id=executed_story_id,
            story_index=executed_story_index,
            executed_stories=([active_story.id] if active_story is not None else []),
            # 计划只在步骤**真的完成**时透传：失败 / 阻断的步骤不能把后续步骤交给调用方执行。
            requested_steps=(list(result.requested_steps) if result.status is WorkflowStatus.COMPLETED else []),
        )

    def _record_story_status(self, story_id: str, status: str) -> None:
        """逐 Story 状态的唯一写点（批次机制移除后）：status_view 与恢复诊断依赖它，字段永空等于静默失明（Story 51-8）。"""
        self.state = self.state.model_copy(update={"story_statuses": {**self.state.story_statuses, story_id: status}})

    async def _validate_batch_outputs(
        self,
        step: WorkflowStepResource,
        batch: list[StorySpec],
        results: list[Any],
        checkpoint: CheckpointCallback | None,
    ) -> WorkflowRunResult | None:
        """COMPLETED 成员输出校验先于任何簿记（与串行同序：校验不过 → BLOCKED 零簿记）。"""
        for member, outcome in zip(batch, results, strict=True):
            if isinstance(outcome, WorkflowStepResult) and outcome.status is WorkflowStatus.COMPLETED:
                try:
                    self._validate_output(step, outcome.output)
                except WorkflowGateError as exc:
                    return await self._stop(
                        WorkflowStatus.BLOCKED,
                        step,
                        f"story '{member.id}' output was rejected: {exc}",
                        [],
                        checkpoint,
                    )
        return None

    async def _settle_story_batch(
        self,
        step: WorkflowStepResource,
        specs: list[StorySpec],
        batch: list[StorySpec],
        results: list[Any],
        emit: Callable[..., None] | None,
        started: float,
        checkpoint: CheckpointCallback | None,
    ) -> WorkflowRunResult:
        """批后处理（AD-19：批 = 单 checkpoint 单元）。

        顺序：COMPLETED 成员输出校验（先于任何簿记，与串行同序）→ 按声明序逐成员记账 +
        逐成员 RUNNING 中间快照（全程不做终态转换）→ 位置校正（越过已完成的洞）→ **单次**
        终态转换（转换表 RUNNING 终态单向，逐成员转换会在第二个成员处抛
        ``WorkflowTransitionError``）→ 终态持久化。manual 模式的 checkpoint 确认因此从
        「每 Story 一次」收紧为「每批一次」——批已并发跑完，逐条确认无意义。

        聚合规则：存在异常 → EXECUTOR_FAILED + 重抛声明序首个异常（完成者已入账，事实就是
        事实）；存在非 COMPLETED 结果 → ``_callback_event`` 映射；全部完成且收口 → 审批门
        或步骤推进；否则批间推进（checkpoint 声明则挂起等确认）。

        取消窗口与串行路径同构：本方法的持久化点可被取消打断（既有暴露面，不放大也不收敛）。
        """
        blocked = await self._validate_batch_outputs(step, batch, results, checkpoint)
        if blocked is not None:
            return blocked
        index_by_id = {spec.id: index for index, spec in enumerate(specs)}
        evidence: list[str] = []
        follow_ups: list[str] = []
        first_failure: BaseException | None = None
        first_incomplete: WorkflowStepResult | None = None
        violation = False
        for member, outcome in zip(batch, results, strict=True):
            if isinstance(outcome, BaseException):
                if not isinstance(outcome, asyncio.CancelledError):
                    self._record_story_status(member.id, WorkflowStatus.FAILED.value)
                    if first_failure is None:
                        first_failure = outcome
                continue
            if not isinstance(outcome, WorkflowStepResult):
                outcome = WorkflowStepResult(
                    status=WorkflowStatus.FAILED, reason="step callback must return WorkflowStepResult"
                )
            self._record_story_status(member.id, outcome.status.value)
            violation = violation or outcome.write_violation
            if outcome.status is WorkflowStatus.COMPLETED:
                evidence.extend(outcome.evidence)
                follow_ups.extend(outcome.requested_steps)
                self.state = self.state.model_copy(
                    update={
                        "completed_stories": [*self.state.completed_stories, member.id],
                        "story_outputs": {**self.state.story_outputs, member.id: outcome.output},
                        "acceptance_evidence": [*self.state.acceptance_evidence, *outcome.evidence],
                        "story_index": index_by_id[member.id] + 1,
                        "active_story": member.id,
                        "active_epic": member.epic,
                    }
                )
                await self._persist(step, checkpoint)
            elif first_incomplete is None:
                first_incomplete = outcome
        if violation:
            # 闩置位先于一切早退：follow-up 超限等 BLOCK 不得把已检出
            # 的 write_violation 丢弃一轮。
            self.state = self.state.model_copy(update={"story_parallel_revoked": True})
        if len(self.state.requested_steps) + len(follow_ups) > len(self.workflow.steps):
            return await self._refuse_oversized_plan(step, len(follow_ups), "stories in step", checkpoint)
        # 位置校正（有洞恢复的关键）：批内失败允许「completed 有洞」，story_index 必须落在
        # **首个未完成** Story 上——洞在中间时这是回摆（如 S-2✓/S-1✗ ⇒ 回到 S-1），不是单调
        # 前进。无洞历史下该值与单调推进一致。
        first_open = next(
            (index for index, spec in enumerate(specs) if spec.id not in self.state.completed_stories),
            len(specs),
        )
        open_story = specs[first_open] if first_open < len(specs) else None
        self.state = self.state.model_copy(
            update={
                "story_index": first_open,
                "active_story": open_story.id if open_story is not None else None,
                "active_epic": open_story.epic if open_story is not None else "",
            }
        )
        all_done = all(spec.id in self.state.completed_stories for spec in specs)
        combined = _combine_story_outputs(specs, self.state.story_outputs)
        if first_failure is not None:
            self.state = self.state.model_copy(
                update={
                    **_transition_fields(
                        self.state,
                        WorkflowEvent.EXECUTOR_FAILED,
                        reason=str(first_failure) or WorkflowEvent.EXECUTOR_FAILED.value,
                    ),
                    "reason": _bounded_reason(str(first_failure) or WorkflowEvent.EXECUTOR_FAILED.value),
                }
            )
            _emit_step_event(
                emit,
                "workflow_step_failed",
                step=step,
                story=None,
                duration_ms=elapsed_ms(started),
                error_kind=error_kind_for(first_failure),
                error=_bounded_reason(str(first_failure)),
                transition_event=WorkflowEvent.EXECUTOR_FAILED.value,
            )
            await self._persist_interrupted(step, checkpoint)
            raise first_failure
        if first_incomplete is not None:
            self.state = self.state.model_copy(
                update={
                    **_transition_fields(self.state, _callback_event(first_incomplete.status)),
                    "reason": _bounded_reason(first_incomplete.reason),
                }
            )
        elif all_done:
            if step.approval.required:
                update = _approval_gate_update(self.state, step, combined)
            else:
                update = _step_advance_update(self.state, step, len(self.workflow.steps), combined)
                update.update(_story_reset_update())
            update["requested_steps"] = [*self.state.requested_steps, *follow_ups]
            self.state = self.state.model_copy(update=update)
        else:
            event = WorkflowEvent.CHECKPOINT_REQUIRED if _checkpoint_declared(step) else WorkflowEvent.STEP_COMPLETED
            self.state = self.state.model_copy(
                update={
                    **_transition_fields(self.state, event),
                    "requested_steps": [*self.state.requested_steps, *follow_ups],
                }
            )
        checkpoint_id = await self._persist(step, checkpoint)
        _emit_step_event(
            emit,
            "workflow_step_completed",
            step=step,
            story=None,
            duration_ms=elapsed_ms(started),
            result=self.state.status.value,
        )
        return WorkflowRunResult(
            status=self.state.status,
            step_index=step.index,
            output=combined if all_done else None,
            reason=self.state.reason,
            acceptance_evidence=evidence,
            checkpoint_id=checkpoint_id,
            story_index=self.state.story_index,
            executed_stories=[member.id for member in batch],
            # 计划只在步骤**真的完成**时透传（与串行同口径）。
            requested_steps=(list(follow_ups) if all_done else []),
        )

    def _consume_requested_step(self, name: str) -> None:
        """计划队首若是 ``name`` 就出队：一次提交只消费一次（幂等跳过的请求也算已满足）。"""
        if self.state.requested_steps and self.state.requested_steps[0] == name:
            self.state = self.state.model_copy(update={"requested_steps": list(self.state.requested_steps[1:])})

    async def run_declared_step(
        self,
        name: str,
        callback: WorkflowCallback | StoryWorkflowCallback,
        *,
        inputs: Mapping[str, Any] | Iterable[str] | None = None,
        artifacts: Mapping[str, Any] | Iterable[str] | None = None,
        checkpoint: CheckpointCallback | None = None,
        emit: Callable[..., None] | None = None,
    ) -> WorkflowRunResult:
        """Run one **named declared** step on request（Story 51-7 的 A1 端口）。

        与 :meth:`run_step` 的唯一差别是「跑哪一步」：``run_step`` 跑 ``state.active_step``
        （声明顺序），本方法跑调用方**指名**的已声明步骤——脚本据此条件性地选择后续步骤。
        状态机仍完全归 Runner（AD-1），本方法不做任何自己的状态推进：

        - 名字不在本 workflow 的声明里 → ``ValueError``（显性，不猜、不静默忽略）；
        - 已完成的步骤 → **幂等跳过**（不重跑、不产生新 checkpoint、不改状态），返回当前
          状态 + 一条说明理由的结果，调用方可据此继续；
        - 只允许**向前**选择：目标在本步之前且未完成 = 该步已被跳过/尚未执行 → ``ValueError``
          （活动步保持单调，恢复语义不引入回退）；
        - workflow 已完成，或状态挂起（WAITING_USER / BLOCKED / FAILED）→ 不改状态，按现状返回。
        """
        target = next((step for step in self.workflow.steps if step.name == name), None)
        if target is None:
            raise WorkflowExecutionError(f"not a declared workflow step: {name}")
        if self.state.status in {WorkflowStatus.WAITING_USER, WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
            return WorkflowRunResult(status=self.state.status, step_index=target.index, reason=self.state.reason)
        if target.index - 1 in self.state.completed_steps:
            self._consume_requested_step(name)
            return WorkflowRunResult(
                status=self.state.status,
                step_index=target.index,
                reason=f"step '{name}' is already completed; skipped (idempotent)",
                skipped=True,
            )
        if self.done or target.index - 1 < self.state.active_step:
            raise WorkflowExecutionError(
                f"step '{name}' cannot be selected: it is behind the active step "
                f"({self.workflow.steps[self.state.active_step].name}); a script may only select "
                f"subsequent declared steps"
            )
        previous = self.state.active_step
        self._consume_requested_step(name)
        self.state = self.state.model_copy(update={"active_step": target.index - 1})
        try:
            return await self.run_step(callback, inputs=inputs, artifacts=artifacts, checkpoint=checkpoint, emit=emit)
        except BaseException:
            # Runner 自身的异常不留下「活动步被改过」的假状态；业务回调的失败由 run_step
            # 落成状态（那是合法推进），这里只兜住抛异常路径。
            self.state = self.state.model_copy(update={"active_step": previous})
            raise

    def _absorb_step_exception(self, exc: BaseException) -> WorkflowEvent:
        """异常/取消经唯一转换表落状态，不用直写掩盖（51-2）。

        取消语义（A39，2026-10-23 裁定）：``CancelledError`` / ``KeyboardInterrupt`` /
        ``SystemExit`` 一律视为用户取消，经 CANCELLED 落 PENDING（可恢复）；其余
        ``BaseException`` 走 EXECUTOR_FAILED 落 FAILED。``str(exc)`` 为空（无参
        CancelledError、KeyboardInterrupt）时以事件名兜底，避免空 reason 抹掉可追溯性。
        返回值是该次转换所用事件，供调用方发射 ``transition_event`` 与判定 story 状态。
        """
        event = _cancel_or_failure_event(exc)
        reason = str(exc) or event.value
        self.state = self.state.model_copy(
            update={**_transition_fields(self.state, event, reason=reason), "reason": _bounded_reason(reason)}
        )
        return event

    async def _persist_interrupted(self, step: WorkflowStepResource, checkpoint: CheckpointCallback | None) -> None:
        """异常路径转换后的状态落盘（51-2 评审递延，51-8 收口）。

        转换只改内存时，最后一个 checkpoint 仍是 PENDING/RUNNING——重启 restore 会把
        FAILED/CANCELLED「复活」成可继续的状态。best-effort：落盘失败（含取消打断）只记
        日志、不替换原异常（观测与恢复不得改变业务控制流）；``asyncio.shield`` 让取消
        场景下落盘仍在后台尝试完成。
        """
        try:
            await asyncio.shield(self._persist(step, checkpoint))
        except asyncio.CancelledError:
            safe_log(
                logger,
                logging.WARNING,
                "checkpoint persistence after interruption was cancelled; state may resurrect on restore",
            )
        except Exception as exc:  # noqa: BLE001
            safe_log(logger, logging.WARNING, f"checkpoint persistence after interruption failed: {exc}", exc_info=True)

    def _active_step_resource(self) -> WorkflowStepResource:
        return self.workflow.steps[min(self.state.active_step, len(self.workflow.steps) - 1)]

    @property
    def current_step(self) -> WorkflowStepResource:
        """活动步资源（越界安全：已完成 / 越界的 goal 收敛到最后一步）。

        公共只读访问器：入口层与 use-case 取「当前步」经这里，不再各自复算一遍
        ``min(active_step, len-1)``（Story 51-5 审查 #16）。
        """
        return self._active_step_resource()

    def pause(self, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """用户请求的暂停，经唯一转换表落状态（51-2 Review P7）。"""
        self.state = _pause_state(self.state)
        _emit_step_event(
            emit,
            "workflow_paused",
            step=self._active_step_resource(),
            story=None,
            transition_event=WorkflowEvent.USER_PAUSE.value,
        )
        return self.state.model_copy(deep=True)

    def resume(self, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """Explicitly resume a paused, blocked, or failed active step.

        审批门挂起（``awaiting_approval``）时显性拒绝（Story 51-5）：resume 只恢复执行，
        不顶替人工批准（AD-3）——先做显式决策（approve / reject / amend）再 resume。
        """
        if self.done:
            return self.state.model_copy(deep=True)
        update = _resume_update(self.state)
        if update:
            self.state = self.state.model_copy(update=update)
            _emit_step_event(
                emit,
                "workflow_resumed",
                step=self._active_step_resource(),
                story=None,
                transition_event=WorkflowEvent.USER_RESUME.value,
            )
        return self.state.model_copy(deep=True)

    def approve(self, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """人工批准（Story 51-5）：接受挂起步骤的工作并落定完成簿记。

        这是审批门离开 ``WAITING_USER`` 且步骤被标记完成的**唯一**路径。门先经 USER_APPROVE
        抬回 RUNNING，随后完成簿记与普通步骤路径共用状态机的 :func:`_step_advance_update`
        （末步 → COMPLETED、声明 checkpoint 的再挂起、普通步 → PENDING），不另写一份完成语义。
        """
        step = self._require_approval_decision()
        self.state = _approve_state(self.state, step, len(self.workflow.steps))
        _emit_step_event(
            emit,
            "workflow_approved",
            step=step,
            story=None,
            transition_event=WorkflowEvent.USER_APPROVE.value,
        )
        return self.state.model_copy(deep=True)

    def reject(self, reason: str, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """人工拒绝（Story 51-5）：驳回挂起的工作；步骤保持未完成、必须重做。

        落 ``BLOCKED``（与声明门未过同一恢复语义：``/goal resume`` 重跑该步）；拒绝理由经
        :func:`_bounded_reason` 收敛后进状态 ``reason`` 并随事件携带同值。reject **不**发生
        完成簿记——步骤不被标记完成。
        """
        step = self._require_approval_decision()
        self.state = _decision_state(self.state, WorkflowEvent.USER_REJECT, reason, bounded=True)
        _emit_step_event(
            emit,
            "workflow_rejected",
            step=step,
            story=None,
            reason=_bounded_reason(reason),
            transition_event=WorkflowEvent.USER_REJECT.value,
        )
        return self.state.model_copy(deep=True)

    def amend(self, supplement: str, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """人工修订（Story 51-5）：工作不获接受、带补充直接重跑；步骤保持未完成。

        落 ``PENDING``（下一条 next/run 即以补充重跑该步，恢复无需再敲 resume）；与 reject
        的语义差别在恢复方式与决策记录的 action，两者都不推进、各记一条（AD-3：独立事件，
        不互相顶替）。
        """
        step = self._require_approval_decision()
        self.state = _decision_state(self.state, WorkflowEvent.USER_AMEND, supplement, bounded=False)
        _emit_step_event(
            emit,
            "workflow_amended",
            step=step,
            story=None,
            reason=supplement,
            transition_event=WorkflowEvent.USER_AMEND.value,
        )
        return self.state.model_copy(deep=True)

    def _require_approval_decision(self) -> WorkflowStepResource:
        """审批决策的前置：必须真的有步骤在等决策，否则显性失败（不静默无操作）。"""
        if not self.state.awaiting_approval:
            raise WorkflowGateError("no step is awaiting an approval decision")
        return self._active_step_resource()

    async def persist_state(self) -> str | None:
        """持久化命令边界处的状态变化，不调用任何回调。

        pause 与 resume 是 CLI 的状态变化、不是 workflow 步骤。把该操作留在 Runner 上，
        调用方就不必自己重建 checkpoint 载荷，也不会在恢复时意外丢掉已完成步骤的历史。
        """
        return await self._persist(self._active_step_resource(), None)

    async def _refuse_oversized_plan(
        self,
        step: WorkflowStepResource,
        declared: int,
        subject: str,
        checkpoint: CheckpointCallback | None,
    ) -> WorkflowRunResult:
        """后续步骤计划超限（Story 51-7）：累计计划不得超过本 workflow 的声明步骤数。
        无界声明是脚本缺陷，**有界失败**（BLOCKED + 落 checkpoint）比静默截断诚实。
        """
        return await self._stop(
            WorkflowStatus.BLOCKED,
            step,
            f"{subject} '{step.name}' declared {declared} follow-up step(s), exceeding "
            f"the workflow's {len(self.workflow.steps)} declared step(s); the plan is refused",
            [],
            checkpoint,
        )

    async def _stop(
        self,
        status: WorkflowStatus,
        step: WorkflowStepResource,
        reason: str,
        missing: list[str],
        checkpoint: CheckpointCallback | None,
    ) -> WorkflowRunResult:
        event = _stop_event(self.state.status)
        fields = _transition_fields(self.state, event)
        if fields["status"] is not status:
            raise WorkflowExecutionError(f"stop status {status} disagrees with {event}")
        bounded_reason = _bounded_reason(reason)
        self.state = self.state.model_copy(update={**fields, "reason": bounded_reason})
        checkpoint_id = await self._persist(step, checkpoint)
        return WorkflowRunResult(
            status=status,
            step_index=step.index,
            reason=bounded_reason,
            missing=missing,
            checkpoint_id=checkpoint_id,
        )

    def _resolve_stories(self, step: WorkflowStepResource, stories: Iterable[StorySpec] | None) -> list[StorySpec]:
        if not self._is_story_step(step):
            return []
        specs = list(stories or [])
        if not specs:
            raise WorkflowGateError(f"story-loop step '{step.name}' requires a story list")
        if self.state.story_index >= len(specs):
            raise WorkflowGateError(
                f"story index {self.state.story_index} is out of range for {len(specs)} story/stories"
            )
        return specs

    async def _blocked_story_dependency(
        self, step: WorkflowStepResource, specs: list[StorySpec], checkpoint: CheckpointCallback | None
    ) -> WorkflowRunResult | None:
        current = specs[self.state.story_index]
        if all(dependency in self.state.completed_stories for dependency in current.depends_on):
            return None
        return await self._stop(
            WorkflowStatus.BLOCKED,
            step,
            f"story '{current.id}' has incomplete or unknown dependencies",
            [],
            checkpoint,
        )

    @staticmethod
    def _is_story_step(step: WorkflowStepResource) -> bool:
        return bool(step.story_loop and step.story_loop.strip())

    async def _persist(self, step: WorkflowStepResource, callback: CheckpointCallback | None) -> str | None:
        if callback:
            result = callback(self.state.model_copy(deep=True))
            if inspect.isawaitable(result):
                await result
        if self.checkpoint_store is None:
            return None
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=self._checkpoint_id(step),
            goal_id=self.goal_id,
            phase=self.phase,
            status=self.state.status,
            run_id=self.run_id,
            active_skill=self.workflow.name,
            active_step=self.state.active_step,
            active_story=self.state.active_story,
            active_epic=self.state.active_epic,
            story_statuses=dict(self.state.story_statuses),
            story_index=self.state.story_index if self._is_story_step(step) else None,
            completed_stories=list(self.state.completed_stories),
            story_outputs=dict(self.state.story_outputs),
            awaiting_approval=self.state.awaiting_approval,
            pending_output=self.state.pending_output,
            approval_round=self.state.approval_round,
            requested_steps=list(self.state.requested_steps),
            story_parallel_revoked=self.state.story_parallel_revoked,
            outputs=dict(self.state.outputs),
            acceptance_evidence=list(self.state.acceptance_evidence),
            completed_steps=list(self.state.completed_steps),
            last_event=self.state.last_event,
            transition_reason=self.state.transition_reason,
            next_action=_bounded_reason(self.state.reason),
        )
        aggregate_status = self.state.status
        if aggregate_status is WorkflowStatus.COMPLETED and self.phase is not WorkflowPhase.DONE:
            aggregate_status = WorkflowStatus.RUNNING
        # `active_stories` / `artifact_refs` 已派生化删除：前者恒等于
        # `[active_story]`，后者恒等于 `outputs` 键表——两处都是纯镜像，写点同步即税。
        workflow_state = GoalWorkflowState(
            goal_id=self.goal_id,
            phase=self.phase,
            active_skill=self.workflow.name,
            active_step=self.state.active_step,
            active_story=self.state.active_story,
            story_statuses=dict(self.state.story_statuses),
            status=aggregate_status,
            next_action=_bounded_reason(self.state.reason),
        )
        await self.checkpoint_store.save(checkpoint, workflow_state)
        return checkpoint.checkpoint_id

    def _checkpoint_id(self, step: WorkflowStepResource) -> str:
        """构造一个 logical checkpoint 位置所需的幂等键。

        id 必须是该位置的完全函数，因为 store 把「同一 id 第二次写入不同内容」视为冲突。
        对 story 循环步骤而言，位置包含当前 story：同一个 ``(step, story_index)`` 槽位
        合法地持有两个快照——「该步尚未进入它的 story」（没有活动 story，写于上一步推进
        进入本步时）与「story S-1 待执行」（runner 恢复进被打断的 story 时写入）。省略
        story 会让第二次写入与第一次撞车，抛出一个假冲突。
        """
        story_part = ""
        if self._is_story_step(step):
            # 批次机制（max_parallel_stories>1 的 `-parallel-` 后缀）已随串行化删除
            # ——恢复路径从不按重建 id 找快照（restore_runner 按内容位匹配、load_latest_unfinished
            # 按创建序扫描），旧格式文件天然容忍读，id 格式变更因此兼容。
            story_part = f"-story-{self.state.story_index}"
            # Story id 在上游已规范化；这里再做一次防御性清洗，
            # 确保手工构造的 spec 也无法产出路径不安全的 checkpoint id。
            label = re.sub(r"[^0-9A-Za-z]+", "-", self.state.active_story or "").strip("-")
            if label:
                story_part += f"-{label}"
        # 审批门让「同一位置合法地写入多次」成为常态：轮次单调递增且永不回零，所以只要
        # 发生过审批门（approval_round > 0，含 reject / amend 后的非挂起持久化）就带轮次后缀
        # ——第二轮的 blocked 与第一轮的 blocked 内容合法地不同，缺后缀会让 store 以
        # 「同 id 不同内容」拒绝（实证死锁：/goal new → reject → resume 重挂门 → 二次 reject
        # 报 checkpoint conflict）。
        gate_part = f"-gate-{self.state.approval_round}" if self.state.approval_round else ""
        return (
            f"{self.goal_id}-{self.run_id}-step-{step.index}{story_part}"
            f"-active-{self.state.active_step}-{self.state.status.value}{gate_part}"
        )

    @staticmethod
    def _missing_inputs(step: WorkflowStepResource, values: Mapping[str, Any] | Iterable[str]) -> list[str]:
        required = _references(step.input)
        available = set(values)
        lowered = {str(key).lower() for key in available}
        return [item for item in required if item not in available and item.lower() not in lowered]

    @staticmethod
    def validate_output(step: WorkflowStepResource, output: Any) -> None:
        """按步骤的输出与 validation 声明校验步骤输出。"""
        WorkflowRunner._validate_output(step, output)

    @staticmethod
    def _validate_output(step: WorkflowStepResource, output: Any) -> None:
        if step.output and (output is None or output == ""):
            raise WorkflowGateError(f"step '{step.name}' requires output: {step.output}")
        text = output if isinstance(output, str) else ""
        if step.validation_rules:
            rules = step.validation_rules.casefold()
            if "given" in rules and not re.search(r"given.*when.*then", text, re.I | re.S):
                raise WorkflowGateError(f"step '{step.name}' output failed validation: {step.validation_rules}")
            for section in required_sections(step.validation_rules):
                if not output_contains_section(text, section):
                    present = [item.strip() for item in re.findall(r"^##\s+(.+?)\s*$", text, re.M)][:8]
                    found = ", ".join(present) if present else "none"
                    raise WorkflowGateError(
                        f"step '{step.name}' output is missing section: {section} (present H2 headings: {found})"
                    )
        if step.output and isinstance(output, Mapping):
            names = _references(step.output)
            missing = [name for name in names if name not in output]
            if missing:
                raise WorkflowGateError("step output is missing: " + ", ".join(missing))
