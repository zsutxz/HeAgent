"""Deterministic one-step runner for declarative Markdown workflows."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from heagent.engine.checkpoint import (
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)
from heagent.engine.observability import elapsed_ms
from heagent.engine.workflow_events import WorkflowEvent
from heagent.engine.workflow_resource import (
    WorkflowResource,
    WorkflowStepResource,
    output_contains_section,
    section_titles,
)
from heagent.engine.workflow_transition import transition
from heagent.events.protocol import error_kind_for
from heagent.pub.safe_logging import safe_log
from heagent.pub.types import StorySpec

logger = logging.getLogger(__name__)


def _emit_step_event(
    emit: Callable[..., None] | None,
    kind: str,
    *,
    step: Any,
    story: Any,
    duration_ms: int = 0,
    error_kind: str = "",
    **extra: Any,
) -> None:
    """工作流观测事件的**唯一**隔离包装（Phase 5 C1；A27 统一）：emit-None 早退 + try/except
    + ``safe_log`` 忽略——可观测性不得改变业务控制流。

    ``step`` / ``story`` 是鸭子契约（引擎侧传 ``WorkflowStepResource`` / ``StorySpec``，CLI
    质量门传宿主对象）：属性访问故障与 emit 异常同在隔离内，绝不传播进业务流，payload
    构造因此也在隔离内。``duration_ms`` / ``error_kind`` 进 details，由传输层
    ``from_engine_event`` 提升到 RunEvent 顶层（EngineEvent 模型与 GUI 消费面不动）。
    ``**extra`` 的取值在调用方实参处求值——调用方只应传自有类型化模型字段或字面量。
    """
    if emit is None:
        return
    try:
        payload: dict[str, Any] = {
            "step": step.name,
            "story": story.id if story is not None else "",
            "duration_ms": duration_ms,
            "error_kind": error_kind,
            **extra,
        }
        emit(kind, details=payload)
    except Exception:  # noqa: BLE001 - 观测失败仅告警
        safe_log(logger, logging.WARNING, "workflow step event %r emit failed; ignored", kind, exc_info=True)


def required_sections(validation_rules: str | None) -> list[str]:
    """Return the ``section:`` headings a step output must contain.

    Single parser shared by the post-step output gate and the pre-step prompt: an
    executor has to be told the exact headings it will be judged on, otherwise a
    long step can finish all its work and still be blocked on a heading it never
    saw. 实现委托给 :func:`heagent.engine.workflow_resource.section_titles`（单一真源，
    ``goal/workflow_loader`` 的子句解析同源），本函数保留为既有公开 API。
    """
    return section_titles(validation_rules)


class WorkflowGateError(ValueError):
    """Raised when a step cannot satisfy its declared contract."""


class WorkflowRunnerState(BaseModel):
    """Serializable progress for a declarative workflow."""

    active_step: int = Field(default=0, ge=0)
    status: WorkflowStatus = WorkflowStatus.PENDING
    completed_steps: list[int] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    acceptance_evidence: list[str] = Field(default_factory=list)
    reason: str = ""
    active_story: str | None = None
    # 当前 Story 所属 Epic：runner 在 story 循环处从已解析的 Story 记录里取值（不读文档、不猜层级）。
    active_epic: str = ""
    story_index: int = Field(default=0, ge=0)
    completed_stories: list[str] = Field(default_factory=list)
    story_outputs: dict[str, Any] = Field(default_factory=dict)
    # `active_stories` 已派生化删除（A26）：串行化后它恒等于 `[active_story]`（无活动 story
    # 时空表），每个写点都只是镜像同步税。消费方（checkpoint / status_view）一律由
    # ``active_story`` 现场派生。
    story_statuses: dict[str, str] = Field(default_factory=dict)
    # 步骤级审批门（Story 51-5）：True = 活动步做完工作、挂起等一个人工决策（approve /
    # reject / amend）；普通 resume 在此状态被拒绝，不能隐式顶替批准。
    awaiting_approval: bool = False
    # 审批门挂起期间的步骤产物：approve 落定完成簿记时的输出来源（步骤此刻未标记完成，
    # 所以还不进 ``outputs``）。
    pending_output: Any = None
    # 审批门在该 goal 上的第几次发生（单调递增，gate 每次挂起 +1）。参与 checkpoint 幂等键：
    # reject / amend 重跑会把同一 (step, active, status) 位置再次挂门，而内容合法地不同——
    # 缺这个区分位会让第二次挂门撞上第一次的 checkpoint conflict。
    approval_round: int = Field(default=0, ge=0)
    # 脚本步骤声明的后续声明步骤计划（Story 51-7）：FIFO，由 run_declared_step 消费。持久化
    # 进 checkpoint，使「条件选择了哪些后续步骤」在进程重启后仍可确定恢复。
    requested_steps: list[str] = Field(default_factory=list)


class WorkflowStepResult(BaseModel):
    """Callback result returned after executing one step."""

    status: WorkflowStatus = WorkflowStatus.COMPLETED
    output: Any = None
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""
    #: 该步**声明**的后续声明步骤名（Story 51-7 的 A1 端口入口；缺省空 = 老回调零行为变化）。
    #: 只有 ``COMPLETED`` 的结果才会被采纳——失败 / 阻断的步骤不能把计划交给 Runner。
    requested_steps: list[str] = Field(default_factory=list)


class WorkflowRunResult(BaseModel):
    """Validated public result of one runner invocation."""

    status: WorkflowStatus
    step_index: int | None = None
    output: Any = None
    reason: str = ""
    missing: list[str] = Field(default_factory=list)
    acceptance_evidence: list[str] = Field(default_factory=list)
    checkpoint_id: str | None = None
    story_id: str | None = None
    story_index: int | None = None
    #: 本步声明的后续步骤名（透传自 :class:`WorkflowStepResult`；由调用方按序提交）。
    requested_steps: list[str] = Field(default_factory=list)
    #: True = 本次调用**没有执行任何步骤**（:meth:`WorkflowRunner.run_declared_step` 的幂等跳过）。
    #: 调用方据此区分「真的推进了」与「这个请求已被满足过」，不去猜 ``reason`` 文案。
    skipped: bool = False


WorkflowCallback = Callable[[WorkflowStepResource], WorkflowStepResult | Awaitable[WorkflowStepResult]]
StoryWorkflowCallback = Callable[[WorkflowStepResource, StorySpec], WorkflowStepResult | Awaitable[WorkflowStepResult]]
CheckpointCallback = Callable[[WorkflowRunnerState], Awaitable[None] | None]


class WorkflowRunner:
    """Run exactly one workflow step and never synthesize completion.

    Step declarations are authoritative. A non-completed callback result leaves
    the active step unchanged, allowing callers to resume after checkpoints.

    A step may declare ``story_loop: <artifact>``; such a step expands into one
    callback invocation per story (each an independently checkpointable
    increment), advancing the step only after every story has completed.
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
            raise ValueError("workflow requires at least one step")
        self.workflow = workflow
        self.state = state or WorkflowRunnerState()
        self.goal_id = goal_id or uuid4().hex[:8]
        self.run_id = run_id or uuid4().hex
        self.checkpoint_store = checkpoint_store
        self.phase = phase
        self._validate_state()

    @classmethod
    def from_checkpoint(
        cls, workflow: WorkflowResource, checkpoint: WorkflowCheckpoint, **kwargs: Any
    ) -> WorkflowRunner:
        """Restore runner progress from a persisted checkpoint."""
        state = WorkflowRunnerState(
            active_step=checkpoint.active_step if checkpoint.active_step is not None else len(workflow.steps),
            status=checkpoint.status,
            completed_steps=list(checkpoint.completed_steps),
            # `outputs` 是产物键表的唯一载体；旧字段的 `{reference: None}` 兜底在「artifact_refs
            # 恒等于 list(outputs)」不变量下不可达且等值（两边同空），随镜像派生化一并删除（A33①）。
            outputs=dict(checkpoint.outputs),
            acceptance_evidence=list(checkpoint.acceptance_evidence),
            reason=checkpoint.next_action,
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
        )
        kwargs.setdefault("phase", checkpoint.phase)
        return cls(workflow, state, goal_id=checkpoint.goal_id, run_id=checkpoint.run_id, **kwargs)

    @property
    def done(self) -> bool:
        return self.state.status is WorkflowStatus.COMPLETED and self.state.active_step >= len(self.workflow.steps)

    def _validate_state(self) -> None:
        if self.state.active_step > len(self.workflow.steps):
            raise ValueError("active step is out of range")
        if len(set(self.state.completed_steps)) != len(self.state.completed_steps):
            raise ValueError("completed step indexes must be unique")
        if any(index < 0 or index >= len(self.workflow.steps) for index in self.state.completed_steps):
            raise ValueError("completed step index is out of range")
        if len(set(self.state.completed_stories)) != len(self.state.completed_stories):
            raise ValueError("completed story ids must be unique")

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

        started = time.perf_counter()
        _emit_step_event(emit, "workflow_step_started", step=step, story=active_story)
        self.state = self.state.model_copy(update={"status": transition(self.state.status, WorkflowEvent.START)})
        try:
            result = self._invoke_callback(callback, step, active_story)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, WorkflowStepResult):
                raise TypeError("step callback must return WorkflowStepResult")
        except BaseException as exc:
            self._absorb_step_exception(exc)
            if active_story is not None:
                # 取消（可恢复，步骤落 PENDING）与失败（FAILED）的 story 状态如实区分，
                # 不与步骤状态表矛盾（评审 LOW）；取消没有独立状态值，用事件词汇表。
                story_status = (
                    WorkflowEvent.CANCELLED.value
                    if isinstance(exc, asyncio.CancelledError)
                    else WorkflowStatus.FAILED.value
                )
                self._record_story_status(active_story.id, story_status)
            _emit_step_event(
                emit,
                "workflow_step_failed",
                step=step,
                story=active_story,
                duration_ms=elapsed_ms(started),
                error_kind=error_kind_for(exc),
                error=str(exc),
            )
            await self._persist_interrupted(step, checkpoint)
            raise
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
            # 脚本声明的后续步骤计划（Story 51-7）：累计计划不得超过本 workflow 的声明步骤数。
            # 无界声明是脚本缺陷，**有界失败**（BLOCKED + 落 checkpoint）比静默截断诚实。
            if len(self.state.requested_steps) + len(result.requested_steps) > len(self.workflow.steps):
                return await self._stop(
                    WorkflowStatus.BLOCKED,
                    step,
                    f"step '{step.name}' declared {len(result.requested_steps)} follow-up step(s), exceeding "
                    f"the workflow's {len(self.workflow.steps)} declared step(s); the plan is refused",
                    [],
                    checkpoint,
                )
            executed_story_id = active_story.id if active_story is not None else None
            executed_story_index = self.state.story_index if is_story_loop else None
            update: dict[str, Any] = {
                "acceptance_evidence": [*self.state.acceptance_evidence, *result.evidence],
                # FIFO 追加：本步声明的后续步骤排在已有计划之后（先来先执行，顺序可预期）。
                "requested_steps": [*self.state.requested_steps, *result.requested_steps],
            }
            update.update(self._completion_update(step, story_specs, result.output, is_story_loop=is_story_loop))
            self.state = self.state.model_copy(update=update)
        else:
            self.state = self.state.model_copy(
                update={"status": self._callback_status(result.status), "reason": result.reason}
            )

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
            # 计划只在步骤**真的完成**时透传：失败 / 阻断的步骤不能把后续步骤交给调用方执行。
            requested_steps=(list(result.requested_steps) if result.status is WorkflowStatus.COMPLETED else []),
        )

    def _record_story_status(self, story_id: str, status: str) -> None:
        """逐 Story 状态的唯一写点（批次机制移除后）：status_view 与恢复诊断依赖它，字段永空等于静默失明（Story 51-8）。"""
        self.state = self.state.model_copy(update={"story_statuses": {**self.state.story_statuses, story_id: status}})

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
            raise ValueError(f"not a declared workflow step: {name}")
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
            raise ValueError(
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

    def _absorb_step_exception(self, exc: BaseException) -> None:
        """异常/取消经唯一转换表落状态，不用直写掩盖（51-2）。

        串行 story 路径使用：取消走 CANCELLED，
        其余 BaseException 走 EXECUTOR_FAILED；``str(exc)`` 为空（如无参
        CancelledError）时以事件名兜底，避免空 reason 抹掉可追溯性。
        """
        event = WorkflowEvent.CANCELLED if isinstance(exc, asyncio.CancelledError) else WorkflowEvent.EXECUTOR_FAILED
        self.state = self.state.model_copy(
            update={"status": transition(self.state.status, event), "reason": str(exc) or event.value}
        )

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
        """User-requested pause through the single transition table (51-2 Review P7)."""
        self.state = self.state.model_copy(
            update={
                "status": transition(self.state.status, WorkflowEvent.USER_PAUSE),
                "reason": "user requested pause; resume to continue",
            }
        )
        _emit_step_event(emit, "workflow_paused", step=self._active_step_resource(), story=None)
        return self.state.model_copy(deep=True)

    run = run_step

    def _callback_status(self, status: WorkflowStatus) -> WorkflowStatus:
        event = {
            WorkflowStatus.FAILED: WorkflowEvent.EXECUTOR_FAILED,
            WorkflowStatus.WAITING_USER: WorkflowEvent.USER_PAUSE,
            WorkflowStatus.BLOCKED: WorkflowEvent.GATE_FAILED,
        }.get(status)
        if event is None:
            raise ValueError(f"unsupported callback status: {status}")
        return transition(self.state.status, event)

    def resume(self, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """Explicitly resume a paused, blocked, or failed active step.

        审批门挂起（``awaiting_approval``）时显性拒绝（Story 51-5）：resume 只恢复执行，
        不顶替人工批准（AD-3）——先做显式决策（approve / reject / amend）再 resume。
        """
        if self.done:
            return self.state.model_copy(deep=True)
        if self.state.awaiting_approval:
            raise WorkflowGateError(
                "the active step awaits an approval decision (/goal approve | /goal reject | /goal amend); "
                "resume does not approve it"
            )
        if self.state.status in {WorkflowStatus.WAITING_USER, WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
            self.state = self.state.model_copy(
                update={"status": transition(self.state.status, WorkflowEvent.USER_RESUME), "reason": ""}
            )
            _emit_step_event(emit, "workflow_resumed", step=self._active_step_resource(), story=None)
        return self.state.model_copy(deep=True)

    def approve(self, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """人工批准（Story 51-5）：接受挂起步骤的工作并落定完成簿记。

        这是审批门离开 ``WAITING_USER`` 且步骤被标记完成的**唯一**路径。门先经 USER_APPROVE
        抬回 RUNNING，随后完成簿记与普通步骤路径共用 :meth:`_step_advance_update`（末步 →
        COMPLETED、声明 checkpoint 的再挂起、普通步 → PENDING），不另写一份完成语义。
        """
        step = self._require_approval_decision()
        self.state = self.state.model_copy(update={"status": transition(self.state.status, WorkflowEvent.USER_APPROVE)})
        update = self._step_advance_update(step, self.state.pending_output)
        update.update({"awaiting_approval": False, "pending_output": None})
        self.state = self.state.model_copy(update=update)
        _emit_step_event(emit, "workflow_approved", step=step, story=None)
        return self.state.model_copy(deep=True)

    def reject(self, reason: str, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """人工拒绝（Story 51-5）：驳回挂起的工作；步骤保持未完成、必须重做。

        落 ``BLOCKED``（与声明门未过同一恢复语义：``/goal resume`` 重跑该步）；拒绝理由进
        状态 ``reason``。reject **不**发生完成簿记——步骤不被标记完成。
        """
        step = self._require_approval_decision()
        self.state = self.state.model_copy(
            update={
                "status": transition(self.state.status, WorkflowEvent.USER_REJECT),
                "awaiting_approval": False,
                "pending_output": None,
                "reason": reason,
            }
        )
        _emit_step_event(emit, "workflow_rejected", step=step, story=None, reason=reason)
        return self.state.model_copy(deep=True)

    def amend(self, supplement: str, *, emit: Callable[..., None] | None = None) -> WorkflowRunnerState:
        """人工修订（Story 51-5）：工作不获接受、带补充直接重跑；步骤保持未完成。

        落 ``PENDING``（下一条 next/run 即以补充重跑该步，恢复无需再敲 resume）；与 reject
        的语义差别在恢复方式与决策记录的 action，两者都不推进、各记一条（AD-3：独立事件，
        不互相顶替）。
        """
        step = self._require_approval_decision()
        self.state = self.state.model_copy(
            update={
                "status": transition(self.state.status, WorkflowEvent.USER_AMEND),
                "awaiting_approval": False,
                "pending_output": None,
                "reason": "",
            }
        )
        _emit_step_event(emit, "workflow_amended", step=step, story=None, reason=supplement)
        return self.state.model_copy(deep=True)

    def _require_approval_decision(self) -> WorkflowStepResource:
        """审批决策的前置：必须真的有步骤在等决策，否则显性失败（不静默无操作）。"""
        if not self.state.awaiting_approval:
            raise WorkflowGateError("no step is awaiting an approval decision")
        return self._active_step_resource()

    async def persist_state(self) -> str | None:
        """Persist a command-boundary state change without invoking a callback.

        Pause and resume are CLI state changes, not workflow steps. Keeping this
        operation on the Runner prevents callers from rebuilding checkpoint
        payloads and accidentally losing completed-step history on recovery.
        """
        return await self._persist(self._active_step_resource(), None)

    async def _stop(
        self,
        status: WorkflowStatus,
        step: WorkflowStepResource,
        reason: str,
        missing: list[str],
        checkpoint: CheckpointCallback | None,
    ) -> WorkflowRunResult:
        event = (
            WorkflowEvent.INPUT_MISSING if self.state.status is WorkflowStatus.PENDING else WorkflowEvent.GATE_FAILED
        )
        next_status = transition(self.state.status, event)
        if next_status is not status:
            raise ValueError(f"stop status {status} disagrees with {event}")
        self.state = self.state.model_copy(update={"status": next_status, "reason": reason})
        checkpoint_id = await self._persist(step, checkpoint)
        return WorkflowRunResult(
            status=status, step_index=step.index, reason=reason, missing=missing, checkpoint_id=checkpoint_id
        )

    def _completion_update(
        self,
        step: WorkflowStepResource,
        story_specs: list[StorySpec],
        output: Any,
        *,
        is_story_loop: bool,
    ) -> dict[str, Any]:
        """**非 story 循环**步骤完成后的状态更新：审批门挂起或完成簿记。

        审批门的判定仅有两处（「声明说了算」）：本方法（非 story 步骤）与
        :meth:`_story_advance_update` 的末条 Story。两处都只在 ``step.approval.required`` 时挂门，
        挂起形态由 :meth:`_approval_gate_update` 单点产出。
        """
        if is_story_loop:
            return self._story_advance_update(step, story_specs, output)
        if step.approval.required:
            return self._approval_gate_update(step, output)
        return self._step_advance_update(step, output)

    def _approval_gate_update(self, step: WorkflowStepResource, output: Any) -> dict[str, Any]:
        """审批门挂起更新（Story 51-5）：步骤做完了工作，但声明了 ``approval: required``。

        完成簿记（``completed_steps`` / ``active_step`` / ``outputs``）**延后**到 approve 落定
        ——「reject / amend 不把步骤标记完成」由「先挂起、后落定」直接保证，不需要任何回滚。
        挂起产物存 ``pending_output``（此刻步骤未完成，不能进 ``outputs``）；状态经唯一转换表
        落 ``WAITING_USER``，只有 approve / reject / amend 三种人工决策能离开。story 簿记在此
        **单点清场**：门挂起后步骤未完成，重跑从第一条 story 开始，决策记录也不会把步骤级
        决策错误归因到某条 story（审查 #7）。
        """
        return {
            "status": transition(self.state.status, WorkflowEvent.APPROVAL_REQUIRED),
            "awaiting_approval": True,
            "pending_output": output,
            "approval_round": self.state.approval_round + 1,
            "reason": step.approval.note or "step work is done; it awaits a human approval decision",
            "active_story": None,
            "active_epic": "",
            "story_index": 0,
            "completed_stories": [],
            "story_outputs": {},
        }

    def _step_advance_update(self, step: WorkflowStepResource, output: Any) -> dict[str, Any]:
        # 完成簿记按**本步**的声明序号推进（``step.index`` 1-based），不按 ``state.active_step``：
        # 两者在「按声明顺序线性推进」时恒等；但 :meth:`run_declared_step` 会让活动步跳到脚本
        # 指名的后续步骤，此时只有 step.index 能给出正确的下一位置（Story 51-7 A1）。
        completed = [*self.state.completed_steps, step.index - 1]
        final = step.index >= len(self.workflow.steps)
        event = (
            WorkflowEvent.FINAL_STEP_COMPLETED
            if final
            else WorkflowEvent.CHECKPOINT_REQUIRED
            if self._checkpoint_declared(step)
            else WorkflowEvent.STEP_COMPLETED
        )
        next_status = transition(self.state.status, event)
        outputs = {**self.state.outputs, step.name: output}
        for reference in self._references(step.output):
            outputs[reference] = output
        return {
            "active_step": self.state.active_step + 1,
            "status": next_status,
            "completed_steps": completed,
            "outputs": outputs,
        }

    def _story_advance_update(
        self, step: WorkflowStepResource, story_specs: list[StorySpec], output: Any
    ) -> dict[str, Any]:
        current = story_specs[self.state.story_index]
        completed_stories = [*self.state.completed_stories, current.id]
        story_outputs = {**self.state.story_outputs, current.id: output}
        if self.state.story_index + 1 >= len(story_specs):
            combined = "\n\n---\n\n".join(
                str(value) for value in story_outputs.values() if value is not None and str(value) != ""
            )
            if step.approval.required:
                # 挂门含 story 清场（_approval_gate_update 单点）：重跑从第一条 story 开始。
                return self._approval_gate_update(step, combined)
            update = self._step_advance_update(step, combined)
            update.update(
                {
                    "active_story": None,
                    "active_epic": "",
                    "story_index": 0,
                    "completed_stories": [],
                    "story_outputs": {},
                }
            )
            return update
        next_story = story_specs[self.state.story_index + 1]
        next_status = transition(
            self.state.status,
            WorkflowEvent.CHECKPOINT_REQUIRED if self._checkpoint_declared(step) else WorkflowEvent.STEP_COMPLETED,
        )
        return {
            "story_index": self.state.story_index + 1,
            "status": next_status,
            "completed_stories": completed_stories,
            "story_outputs": story_outputs,
            "active_story": next_story.id,
            "active_epic": next_story.epic,
        }

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

    @staticmethod
    def _invoke_callback(callback: Callable[..., Any], step: WorkflowStepResource, story: StorySpec | None) -> Any:
        if story is not None:
            if not WorkflowRunner._accepts_story(callback):
                raise TypeError("story-loop step callback must accept (step, story)")
            return callback(step, story)
        return callback(step)

    @staticmethod
    def _accepts_story(callback: Callable[..., Any]) -> bool:
        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            return False
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD, parameter.VAR_POSITIONAL)
        ]
        return len(positional) >= 2

    @staticmethod
    def _checkpoint_declared(step: WorkflowStepResource) -> bool:
        return step.checkpoint.strip().casefold() in {"true", "user", "human", "checkpoint", "waiting_user"}

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
            outputs=dict(self.state.outputs),
            acceptance_evidence=list(self.state.acceptance_evidence),
            completed_steps=list(self.state.completed_steps),
            next_action=self.state.reason,
        )
        aggregate_status = self.state.status
        if aggregate_status is WorkflowStatus.COMPLETED and self.phase is not WorkflowPhase.DONE:
            aggregate_status = WorkflowStatus.RUNNING
        # `active_stories` / `artifact_refs` 已派生化删除（A26 / A33①）：前者恒等于
        # `[active_story]`，后者恒等于 `outputs` 键表——两处都是纯镜像，写点同步即税。
        workflow_state = GoalWorkflowState(
            goal_id=self.goal_id,
            phase=self.phase,
            active_skill=self.workflow.name,
            active_step=self.state.active_step,
            active_story=self.state.active_story,
            story_statuses=dict(self.state.story_statuses),
            status=aggregate_status,
            next_action=self.state.reason,
        )
        await self.checkpoint_store.save(checkpoint, workflow_state)
        return checkpoint.checkpoint_id

    def _checkpoint_id(self, step: WorkflowStepResource) -> str:
        """Build the idempotency key for one logical checkpoint position.

        The id must be a total function of the position, because the store treats
        a second write of the same id with different content as a conflict. For a
        story-loop step the position includes the active story: the same
        ``(step, story_index)`` slot legitimately holds two snapshots -- "the step
        has not entered its story yet" (no active story, written while the previous
        step advanced into this one) and "story S-1 is pending" (written when the
        runner resumed into an interrupted story). Omitting the story made the
        second write collide with the first and raise a bogus conflict.
        """
        story_part = ""
        if self._is_story_step(step):
            # 批次机制（max_parallel_stories>1 的 `-parallel-` 后缀）已随 Story 51-8 串行化删除
            # ——恢复路径从不按重建 id 找快照（restore_runner 按内容位匹配、load_latest_unfinished
            # 按创建序扫描），旧格式文件天然容忍读，id 格式变更因此兼容（A25）。
            story_part = f"-story-{self.state.story_index}"
            # Story ids are normalized upstream; sanitize defensively so a
            # hand-built spec can never produce a path-unsafe checkpoint id.
            label = re.sub(r"[^0-9A-Za-z]+", "-", self.state.active_story or "").strip("-")
            if label:
                story_part += f"-{label}"
        # 审批门让「同一位置合法地写入多次」成为常态：轮次单调递增且永不回零，所以只要
        # 发生过审批门（approval_round > 0，含 reject / amend 后的非挂起持久化）就带轮次后缀
        # ——第二轮的 blocked 与第一轮的 blocked 内容合法地不同，缺后缀会让 store 以
        # 「同 id 不同内容」拒绝（实证死锁：/goal new → reject → resume 重挂门 → 二次 reject
        # 报 checkpoint conflict，Story 51-5 审查 #1）。
        gate_part = f"-gate-{self.state.approval_round}" if self.state.approval_round else ""
        return (
            f"{self.goal_id}-{self.run_id}-step-{step.index}{story_part}"
            f"-active-{self.state.active_step}-{self.state.status.value}{gate_part}"
        )

    @staticmethod
    def _missing_inputs(step: WorkflowStepResource, values: Mapping[str, Any] | Iterable[str]) -> list[str]:
        required = WorkflowRunner._references(step.input)
        available = set(values)
        lowered = {str(key).lower() for key in available}
        return [item for item in required if item not in available and item.lower() not in lowered]

    @staticmethod
    def _references(declaration: str) -> list[str]:
        """Parse the workflow's explicit comma/newline-delimited artifact references."""
        return [item.strip() for item in re.split(r"[,\n]", declaration) if item.strip()]

    @staticmethod
    def validate_output(step: WorkflowStepResource, output: Any) -> None:
        """Validate a step output against its output and validation declarations."""
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
            names = WorkflowRunner._references(step.output)
            missing = [name for name in names if name not in output]
            if missing:
                raise WorkflowGateError("step output is missing: " + ", ".join(missing))
