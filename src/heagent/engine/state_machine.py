"""Goal workflow 状态机：状态模型 + 唯一状态写点 + update 推导 + 决策内核。

从 workflow_runner 拆出的纯推导层：本模块只做「状态 → 状态」的纯函数推导与模型定义，
零 I/O、零 emit（观测在调用方经 ``_emit_step_event`` 注入，住 observability）。唯一状态
写点是 :func:`_transition_fields`——所有 ``status`` / ``last_event`` / ``transition_reason``
写点都必须经它（契约判据 ``test_transition_fields_helper_is_the_only_status_writer``
钉住，AST 直读本模块）。纯转换表本体住 :mod:`heagent.engine.workflow_transition`
（单一真源，本模块经 ``transition()`` 消费）。
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from heagent.engine.checkpoint import WorkflowStatus
from heagent.engine.workflow_events import WorkflowEvent
from heagent.engine.workflow_transition import transition

if TYPE_CHECKING:
    from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
    from heagent.pub.types import StorySpec

#: 状态 reason / checkpoint next_action 的字符上限：只限制落盘与展示体积，
#: 语义是**截断不抛**——截断不得改变控制流，超长异常文本也不该把 checkpoint 撑爆。
_MAX_REASON_CHARS = 2000

#: 视为「用户取消」的异常：一律经 CANCELLED 落 PENDING
#: （可恢复，resume 即重跑）。KeyboardInterrupt / SystemExit 与 CancelledError 同路——
#: Ctrl-C 的语义是「先停下、稍后重来」，落 FAILED 会让重启后必须显式 resume 才能继续。
_CANCEL_EXCEPTIONS: tuple[type[BaseException], ...] = (
    asyncio.CancelledError,
    KeyboardInterrupt,
    SystemExit,
)


def _bounded_reason(text: str) -> str:
    """把状态 reason 截到 :data:`_MAX_REASON_CHARS`（A37）：尾部标记省略，绝不抛异常。"""
    if len(text) <= _MAX_REASON_CHARS:
        return text
    return text[: _MAX_REASON_CHARS - 3] + "..."


class WorkflowGateError(ValueError):
    """步骤无法满足其声明契约时抛出。"""


class WorkflowRunnerState(BaseModel):
    """声明式工作流的可序列化进度。"""

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
    # `active_stories` 已派生化删除：串行化后它恒等于 `[active_story]`（无活动 story
    # 时空表），每个写点都只是镜像同步税。消费方（checkpoint / status_view）一律由
    # ``active_story`` 现场派生。
    story_statuses: dict[str, str] = Field(default_factory=dict)
    # 步骤级审批门：True = 活动步做完工作、挂起等一个人工决策（approve /
    # reject / amend）；普通 resume 在此状态被拒绝，不能隐式顶替批准。
    awaiting_approval: bool = False
    # 审批门挂起期间的步骤产物：approve 落定完成簿记时的输出来源（步骤此刻未标记完成，
    # 所以还不进 ``outputs``）。
    pending_output: Any = None
    # 审批门在该 goal 上的第几次发生（单调递增，gate 每次挂起 +1）。参与 checkpoint 幂等键：
    # reject / amend 重跑会把同一 (step, active, status) 位置再次挂门，而内容合法地不同——
    # 缺这个区分位会让第二次挂门撞上第一次的 checkpoint conflict。
    approval_round: int = Field(default=0, ge=0)
    # 脚本步骤声明的后续声明步骤计划：FIFO，由 run_declared_step 消费。持久化
    # 进 checkpoint，使「条件选择了哪些后续步骤」在进程重启后仍可确定恢复。
    requested_steps: list[str] = Field(default_factory=list)
    # 写集违规撤销闩：宿主审计判负（write_violation）后置 True，**单向不可
    # 复位**——撤销的是并发授权（此后批派生恒串行），不撤销围栏（串行重跑仍带 allowlist）。
    # 随 checkpoint 持久化，重启后仍生效；恢复只能由人改 checkpoint 或开新 goal。
    story_parallel_revoked: bool = False
    # 驱动最近一次状态转换的事件：取值 = `WorkflowEvent`。与 ``status`` 由**同一个**
    # event 同源写入（唯一写点是 ``_transition_fields``），审计因此能区分「被取消」「执行器
    # 失败」「人工拒绝」这些最终都表现为非 RUNNING 的转换。
    last_event: str = ""
    # 发那个事件的**理由**：自由文本、经 ``_bounded_reason`` 收敛，与 ``last_event`` 正交——
    # 后者答「经哪个事件」，本字段答「为什么发它」，``next_action`` 答「下一步做什么」。
    # 可选字段带默认值，旧 checkpoint 缺它读作空串（只追加口径允许追加可选字段）。
    transition_reason: str = ""


class WorkflowStepResult(BaseModel):
    """执行单个步骤后返回的回调结果。"""

    status: WorkflowStatus = WorkflowStatus.COMPLETED
    output: Any = None
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""
    #: 该步**声明**的后续声明步骤名（缺省空 = 老回调零行为变化）。
    #: 只有 ``COMPLETED`` 的结果才会被采纳——失败 / 阻断的步骤不能把计划交给 Runner。
    requested_steps: list[str] = Field(default_factory=list)
    #: True = 宿主审计判负：该 Story 实际写越声明写集。Runner 据此置撤销闩。
    write_violation: bool = False


class WorkflowRunResult(BaseModel):
    """一次 runner 调用的已校验公开结果。"""

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
    #: 本次调用实际执行的 story id（按声明序；非 story 步骤为空）。供宿主/视图按批呈现。
    executed_stories: list[str] = Field(default_factory=list)


def _checkpoint_declared(step: WorkflowStepResource) -> bool:
    return step.checkpoint.strip().casefold() in {"true", "user", "human", "checkpoint", "waiting_user"}


def _references(declaration: str) -> list[str]:
    """解析工作流显式声明的、逗号或换行分隔的产物引用。"""
    return [item.strip() for item in re.split(r"[,\n]", declaration) if item.strip()]


def _combine_story_outputs(specs: list[StorySpec], outputs: dict[str, Any]) -> str:
    """按声明序合并 story 输出（AD-19）：跨批有洞恢复时 ``outputs`` 的 dict 插入序是
    完成序，必须按 ``specs`` 声明序重排（批内记账序碰巧一致，洞场景不成立）。
    空值条目剔除（None / 空串不进合并结果）。
    """
    return "\n\n---\n\n".join(
        str(outputs[spec.id])
        for spec in specs
        if outputs.get(spec.id) is not None and str(outputs.get(spec.id, "")) != ""
    )


def _story_reset_update() -> dict[str, Any]:
    """story 清场五连：``active_story`` 归位、索引回零、清空已完成簿记——重跑从第一条 story 开始。"""
    return {
        "active_story": None,
        "active_epic": "",
        "story_index": 0,
        "completed_stories": [],
        "story_outputs": {},
    }


def _validate_state(state: WorkflowRunnerState, workflow: WorkflowResource) -> None:
    if state.active_step > len(workflow.steps):
        raise ValueError("active step is out of range")
    if len(set(state.completed_steps)) != len(state.completed_steps):
        raise ValueError("completed step indexes must be unique")
    if any(index < 0 or index >= len(workflow.steps) for index in state.completed_steps):
        raise ValueError("completed step index is out of range")
    if len(set(state.completed_stories)) != len(state.completed_stories):
        raise ValueError("completed story ids must be unique")


def _is_done(state: WorkflowRunnerState, total_steps: int) -> bool:
    return state.status is WorkflowStatus.COMPLETED and state.active_step >= total_steps


def _transition_fields(state: WorkflowRunnerState, event: WorkflowEvent, *, reason: str = "") -> dict[str, Any]:
    """经唯一转换表推进状态，并把驱动事件与其理由记进 ``last_event`` / ``transition_reason``。

    状态与事件由**同一个** ``event`` 派生，因此不存在「改了状态却留着上一个事件」的
    半更新路径：所有状态写点都返回本函数的 dict（``{**fields, ...}``），不得在别处
    再单独写 ``status`` / ``last_event`` / ``transition_reason``。

    ``reason`` 缺省空串 = 调用点未声明理由（此时 ``transition_reason`` 如实置空，不沿用
    上一次转换的理由——那会把旧理由错挂到新事件上）。长度只由 :func:`_bounded_reason`
    收敛，写入路径永不抛异常（观测不得反噬主流程）。
    """
    return {
        "status": transition(state.status, event),
        "last_event": event.value,
        "transition_reason": _bounded_reason(reason),
    }


def _callback_event(status: WorkflowStatus) -> WorkflowEvent:
    """回调给出的终态 → 驱动事件（A38：``status`` 与 ``last_event`` 必须同源）。"""
    event = {
        WorkflowStatus.FAILED: WorkflowEvent.EXECUTOR_FAILED,
        WorkflowStatus.WAITING_USER: WorkflowEvent.USER_PAUSE,
        WorkflowStatus.BLOCKED: WorkflowEvent.GATE_FAILED,
    }.get(status)
    if event is None:
        raise ValueError(f"unsupported callback status: {status}")
    return event


def _cancel_or_failure_event(exc: BaseException) -> WorkflowEvent:
    """执行异常 → 驱动事件：取消簇（见 :data:`_CANCEL_EXCEPTIONS` 注释）走 CANCELLED。"""
    return WorkflowEvent.CANCELLED if isinstance(exc, _CANCEL_EXCEPTIONS) else WorkflowEvent.EXECUTOR_FAILED


def _stop_event(status: WorkflowStatus) -> WorkflowEvent:
    """_stop 的终态事件选择：PENDING 走 INPUT_MISSING（输入缺口），其余走 GATE_FAILED。"""
    return WorkflowEvent.INPUT_MISSING if status is WorkflowStatus.PENDING else WorkflowEvent.GATE_FAILED


def _completion_update(
    state: WorkflowRunnerState,
    step: WorkflowStepResource,
    story_specs: list[StorySpec],
    total_steps: int,
    output: Any,
    *,
    is_story_loop: bool,
    reason: str = "",
) -> dict[str, Any]:
    """**非 story 循环**步骤完成后的状态更新：审批门挂起或完成簿记。

    审批门的判定仅有两处（「声明说了算」）：本函数（非 story 步骤）与
    :func:`_story_advance_update` 的末条 Story。两处都只在 ``step.approval.required`` 时挂门，
    挂起形态由 :func:`_approval_gate_update` 单点产出。
    """
    if is_story_loop:
        return _story_advance_update(state, step, story_specs, total_steps, output)
    if step.approval.required:
        return _approval_gate_update(state, step, output)
    return _step_advance_update(state, step, total_steps, output, reason=reason)


def _approval_gate_update(state: WorkflowRunnerState, step: WorkflowStepResource, output: Any) -> dict[str, Any]:
    """审批门挂起更新（Story 51-5）：步骤做完了工作，但声明了 ``approval: required``。

    完成簿记（``completed_steps`` / ``active_step`` / ``outputs``）**延后**到 approve 落定
    ——「reject / amend 不把步骤标记完成」由「先挂起、后落定」直接保证，不需要任何回滚。
    挂起产物存 ``pending_output``（此刻步骤未完成，不能进 ``outputs``）；状态经唯一转换表
    落 ``WAITING_USER``，只有 approve / reject / amend 三种人工决策能离开。story 簿记在此
    **单点清场**：门挂起后步骤未完成，重跑从第一条 story 开始，决策记录也不会把步骤级
    决策错误归因到某条 story（审查 #7）。
    """
    gate_reason = step.approval.note or "step work is done; it awaits a human approval decision"
    return {
        **_transition_fields(state, WorkflowEvent.APPROVAL_REQUIRED, reason=gate_reason),
        "awaiting_approval": True,
        "pending_output": output,
        "approval_round": state.approval_round + 1,
        "reason": _bounded_reason(gate_reason),
        **_story_reset_update(),
    }


def _step_advance_update(
    state: WorkflowRunnerState, step: WorkflowStepResource, total_steps: int, output: Any, *, reason: str = ""
) -> dict[str, Any]:
    # 完成簿记按**本步**的声明序号推进（``step.index`` 1-based），不按 ``state.active_step``：
    # 两者在「按声明顺序线性推进」时恒等；但 :meth:`run_declared_step` 会让活动步跳到脚本
    # 指名的后续步骤，此时只有 step.index 能给出正确的下一位置。
    completed = [*state.completed_steps, step.index - 1]
    final = step.index >= total_steps
    event = (
        WorkflowEvent.FINAL_STEP_COMPLETED
        if final
        else WorkflowEvent.CHECKPOINT_REQUIRED
        if _checkpoint_declared(step)
        else WorkflowEvent.STEP_COMPLETED
    )
    outputs = {**state.outputs, step.name: output}
    for reference in _references(step.output):
        outputs[reference] = output
    return {
        **_transition_fields(state, event, reason=reason),
        "active_step": state.active_step + 1,
        "completed_steps": completed,
        "outputs": outputs,
    }


def _story_advance_update(
    state: WorkflowRunnerState,
    step: WorkflowStepResource,
    story_specs: list[StorySpec],
    total_steps: int,
    output: Any,
) -> dict[str, Any]:
    current = story_specs[state.story_index]
    completed_stories = [*state.completed_stories, current.id]
    story_outputs = {**state.story_outputs, current.id: output}
    # 有洞恢复（批内部分失败后串行重跑）：越过已完成成员，不把活动位定到已完成
    # Story 上（否则会重复执行并制造重复 completed id）。无洞历史下循环零迭代，
    # 行为与既有串行路径逐字节一致。
    next_index = state.story_index + 1
    while next_index < len(story_specs) and story_specs[next_index].id in completed_stories:
        next_index += 1
    if next_index >= len(story_specs) or all(spec.id in completed_stories for spec in story_specs):
        # 合并序 = 声明序（同 _settle_story_batch）：有洞历史下插入序是完成序。
        combined = _combine_story_outputs(story_specs, story_outputs)
        if step.approval.required:
            # 挂门含 story 清场（_approval_gate_update 单点）：重跑从第一条 story 开始。
            return _approval_gate_update(state, step, combined)
        update = _step_advance_update(state, step, total_steps, combined)
        update.update(_story_reset_update())
        return update
    next_story = story_specs[next_index]
    event = WorkflowEvent.CHECKPOINT_REQUIRED if _checkpoint_declared(step) else WorkflowEvent.STEP_COMPLETED
    return {
        **_transition_fields(state, event),
        "story_index": next_index,
        "completed_stories": completed_stories,
        "story_outputs": story_outputs,
        "active_story": next_story.id,
        "active_epic": next_story.epic,
    }


def _pause_state(state: WorkflowRunnerState) -> WorkflowRunnerState:
    """用户暂停的状态落点：经唯一转换表落 WAITING_USER，理由固定；emit 与 deep copy 在调用方。"""
    return state.model_copy(
        update={
            **_transition_fields(state, WorkflowEvent.USER_PAUSE, reason="user requested pause; resume to continue"),
            "reason": "user requested pause; resume to continue",
        }
    )


def _resume_update(state: WorkflowRunnerState) -> dict[str, Any]:
    """resume 的状态推导：挂门显性拒绝（raise 留内核）；可恢复态返回转换 fields，其余空 dict = 无操作。"""
    if state.awaiting_approval:
        raise WorkflowGateError(
            "the active step awaits an approval decision (/goal approve | /goal reject | /goal amend); "
            "resume does not approve it"
        )
    if state.status in {WorkflowStatus.WAITING_USER, WorkflowStatus.BLOCKED, WorkflowStatus.FAILED}:
        return {**_transition_fields(state, WorkflowEvent.USER_RESUME), "reason": ""}
    return {}


def _approve_state(state: WorkflowRunnerState, step: WorkflowStepResource, total_steps: int) -> WorkflowRunnerState:
    """approve 的状态落点：门抬回 RUNNING + 完成簿记（共用 _step_advance_update）+ 门字段清零。"""
    state = state.model_copy(update=_transition_fields(state, WorkflowEvent.USER_APPROVE))
    update = _step_advance_update(state, step, total_steps, state.pending_output)
    update.update({"awaiting_approval": False, "pending_output": None})
    return state.model_copy(update=update)


def _decision_state(
    state: WorkflowRunnerState, event: WorkflowEvent, reason: str, *, bounded: bool
) -> WorkflowRunnerState:
    """reject/amend 的共同决策流（require 校验、emit、deep copy 都在调用方）。"""
    return state.model_copy(
        update={
            **_transition_fields(state, event, reason=reason),
            "awaiting_approval": False,
            "pending_output": None,
            "reason": _bounded_reason(reason) if bounded else "",
        }
    )
