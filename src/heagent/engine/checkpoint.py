"""Goal 级工作流状态与 checkpoint 持久化。

``GoalWorkflowState`` 是单个 goal 的可序列化编排元数据；``WorkflowCheckpointStore``
负责持久化原子、可恢复的 checkpoint。现行声明式 runner 住在 ``workflow_runner.py``。
旧版阶段机（``WorkflowOrchestrator`` / ``TokenBudgetManager`` / ``RolloverCoordinator`` /
``RecoveryEnvelope`` / ``WorkflowRoute``）已在 2026-09 移除——与 ``cli/goal.py`` 里退役
旧版 GOAL.md Story 流程是同一次清理。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from heagent.engine.workflow_events import WorkflowEvent
from heagent.pub.persist import atomic_write_text, load_json_model

#: ``last_event`` 的封闭词汇表：取值只能是 ``WorkflowEvent`` 的一员或空串。
#: 空串 = 旧 checkpoint 未记录该字段（只追加口径），不是非法值。
_WORKFLOW_EVENT_VALUES: frozenset[str] = frozenset(event.value for event in WorkflowEvent)


def _iso_now() -> str:
    """当前**本地时间**的 ISO-8601 字符串（微秒精度、无时区后缀）。

    与 ``engine.context.iso_now``（秒精度）、``goal.decisions._utc_now_iso``（UTC 微秒）刻意不同：
    checkpoint 时间戳只服务同机内的写入顺序与新鲜度判断，换来「不带时区后缀、旧文件可直接比较」
    的兼容面；跨机器或跨时区比对前必须先确认双方时区口径。
    """
    return datetime.now().isoformat(timespec="microseconds")


class WorkflowPhase(StrEnum):
    """goal 工作流状态的各个阶段。"""

    DISCOVERY = "discovery"
    PLANNING = "planning"
    SPRINT = "sprint"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    RETROSPECTIVE = "retrospective"
    DONE = "done"


class WorkflowStatus(StrEnum):
    """当前 goal 工作单元的运行时状态。"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


class WorkflowCheckpoint(BaseModel):
    """单个已完成工作流单元的原子、可恢复快照。"""

    checkpoint_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    phase: WorkflowPhase
    status: WorkflowStatus
    run_id: str = Field(min_length=1)
    active_skill: str | None = None
    active_step: int | None = Field(default=None, ge=0)
    active_story: str | None = None
    # 当前 Story 所属 Epic（runner 在 story 循环处记录）。可选字段：旧 checkpoint 缺它就为空，
    # 由视图显示「未知」，绝不回读 story 文档去猜（只追加口径允许追加可选字段）。
    active_epic: str = ""
    # 旧盘文件可能仍带 `artifact_refs` / `active_stories` 两个已派生化删除的镜像字段：
    # 前者恒等于 `outputs` 键表、后者恒等于 `[active_story]`，
    # pydantic 默认 extra='ignore' 容忍读，恢复一律从 `outputs` / `active_story` 现场派生。
    outputs: dict[str, Any] = Field(default_factory=dict)
    acceptance_evidence: list[str] = Field(default_factory=list)
    completed_steps: list[int] = Field(default_factory=list)
    story_index: int | None = Field(default=None, ge=0)
    completed_stories: list[str] = Field(default_factory=list)
    story_outputs: dict[str, Any] = Field(default_factory=dict)
    story_statuses: dict[str, str] = Field(default_factory=dict)
    # 步骤级审批门：True = 活动步做完工作、挂起等一个人工决策。可选字段：
    # 旧 checkpoint 缺它读作 False（只追加口径允许追加可选字段，active_epic 同款先例）。
    awaiting_approval: bool = False
    # 审批门挂起期间步骤的产物：approve 落定完成簿记时的输出来源（不进 completed 的 outputs，
    # 因为步骤此刻还没被标记完成）。
    pending_output: Any = None
    # 审批门发生轮次（参与 checkpoint 幂等键，见 WorkflowRunner._checkpoint_id）。
    approval_round: int = Field(default=0, ge=0)
    # 脚本步骤声明的后续声明步骤计划：可选字段，旧 checkpoint 缺它读作空计划
    # （只追加口径允许追加可选字段，active_epic / awaiting_approval 同款先例）。**必须持久化**：
    # 分支选择若只活在内存里，进程重启后会退回声明顺序，「可确定恢复」就此失效。
    requested_steps: list[str] = Field(default_factory=list)
    # 写集违规撤销闩：宿主审计判负后置 True，单向不可复位——撤销的是
    # 并发授权（批派生恒串行），不撤销围栏。可选字段，旧 checkpoint 缺它读作 False
    # （只追加口径允许追加可选字段，requested_steps 同款先例）。checkpoint 唯一新增字段。
    story_parallel_revoked: bool = False
    # 驱动本次转换的事件：取值为 `WorkflowEvent` 的字符串形态。可选字段，
    # 旧 checkpoint 缺它读作空串（只追加口径允许追加可选字段，active_epic / requested_steps
    # 同款先例）——`next_action` 只说明理由，说明不了「经哪个事件落到这个状态」。
    last_event: str = ""
    # 发那个事件的**理由**：自由文本，与 `last_event` 正交——后者答「经哪个
    # 事件」，本字段答「为什么发它」，`next_action` 答「下一步做什么」。可选字段带默认值，旧
    # checkpoint 缺它读作空串（只追加口径允许追加可选字段，`last_event` 同款先例）。
    transition_reason: str = ""
    next_action: str = ""
    tool_in_flight: bool = False
    created_at: str = Field(default_factory=_iso_now)

    @field_validator("last_event")
    @classmethod
    def _last_event_in_vocabulary(cls, value: str) -> str:
        """I-3：驱动事件必须闭集内（空串表示旧档案未记录，合法）。

        非法取值一律 fail-loud 并**点名**该值——驱动事件决定状态归因，猜错会把人引向
        错误结论；静默接受等于让「经哪个事件落到这个状态」这项审计失去意义。
        """
        if value and value not in _WORKFLOW_EVENT_VALUES:
            raise WorkflowCheckpointError(
                f"checkpoint last_event {value!r} is not a WorkflowEvent value; "
                f"legal values: {sorted(_WORKFLOW_EVENT_VALUES)}"
            )
        return value


class WorkflowCheckpointError(ValueError):
    """checkpoint 无法安全持久化时抛出。"""


class WorkflowCheckpointStore:
    """文件落盘的 checkpoint 存储，保证幂等性确定可复现。"""

    def __init__(self, base_dir: str = ".heagent/checkpoints", *, workflow_path: str | None = None) -> None:
        self._base = Path(base_dir)
        self._workflow_path = Path(workflow_path) if workflow_path is not None else self._base.parent / "workflow.json"
        self._lock = asyncio.Lock()

    @property
    def base_dir(self) -> Path:
        """本存储读写的目录。

        唯一的路径解析点：预检探测的目录与写入方使用的目录不一致，比完全没有预检更糟，
        所以调用方一律向本存储索取，而不是自己再推导一遍路径。
        """
        return self._base

    async def save(self, checkpoint: WorkflowCheckpoint, workflow_state: GoalWorkflowState | None = None) -> str:
        """原子写入一份 checkpoint 与随附的聚合进度，返回 checkpoint 落盘路径。

        三条硬约束：工具在飞时拒绝（``tool_in_flight`` 为真即抛，恢复时无法重建那半个
        调用）；同一 id 只可写一次且内容须逐字段一致（不同即判冲突，避免静默覆盖历史）；
        已有文件解析失败视为损坏、显性报错而非重建。``workflow_state`` 缺省时由
        checkpoint 反推，显式给出则其 ``goal_id`` 必须一致。
        """
        if checkpoint.tool_in_flight:
            raise WorkflowCheckpointError("cannot checkpoint a workflow with a tool in flight")
        path = self._path(checkpoint.checkpoint_id)
        state = workflow_state or self._state_from_checkpoint(checkpoint)
        if state.goal_id != checkpoint.goal_id:
            raise WorkflowCheckpointError("checkpoint and workflow state belong to different goals")
        async with self._lock:
            existing_workflow = await asyncio.to_thread(load_json_model, self._workflow_path, GoalWorkflowState)
            if self._workflow_path.exists() and existing_workflow is None:
                raise WorkflowCheckpointError(f"workflow state is corrupted: {self._workflow_path}")
            existing = await asyncio.to_thread(load_json_model, path, WorkflowCheckpoint)
            if path.exists() and existing is None:
                raise WorkflowCheckpointError(f"checkpoint is corrupted: {path}")
            if existing is not None:
                if self._logical_dump(existing) != self._logical_dump(checkpoint):
                    raise WorkflowCheckpointError(f"checkpoint conflict: {checkpoint.checkpoint_id}")
            else:
                payload = json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=False, indent=2)
                await asyncio.to_thread(atomic_write_text, path, payload)
            workflow_payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2)
            await asyncio.to_thread(atomic_write_text, self._workflow_path, workflow_payload)
        return str(path)

    async def load(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """按 id 读回一份 checkpoint；不存在返回 ``None``，存在但解析失败即抛。

        「不存在」与「读不出来」必须区分：前者是正常的首次运行，后者若也被当成
        ``None`` 会让调用方以为「没有进度」并从零重启，静默丢掉已完成的步骤。
        """
        path = self._path(checkpoint_id)
        checkpoint = await asyncio.to_thread(load_json_model, path, WorkflowCheckpoint)
        if path.exists() and checkpoint is None:
            raise WorkflowCheckpointError(f"checkpoint is corrupted: {path}")
        return checkpoint

    async def load_state(self) -> GoalWorkflowState | None:
        """Load the persisted aggregate run state (progress); corruption is an explicit failure.

        2026-09-20 自 ``load_workflow`` 改名：旧名与 ``goal/workflow_loader.read_workflow``
        （装载 workflow.md 声明）撞车，易误读为「加载工作流定义」。本方法只恢复运行时进度。
        """
        state = await asyncio.to_thread(load_json_model, self._workflow_path, GoalWorkflowState)
        if self._workflow_path.exists() and state is None:
            raise WorkflowCheckpointError(f"workflow state is corrupted: {self._workflow_path}")
        return state

    async def list_checkpoints(self, *, goal_id: str | None = None) -> list[WorkflowCheckpoint]:
        """按确定的创建时刻/id 顺序返回有效 checkpoint。"""
        if not await asyncio.to_thread(self._base.exists):
            return []
        checkpoints: list[WorkflowCheckpoint] = []
        for path in sorted(await asyncio.to_thread(lambda: list(self._base.glob("*.json")))):
            checkpoint = await asyncio.to_thread(load_json_model, path, WorkflowCheckpoint)
            if checkpoint is None:
                raise WorkflowCheckpointError(f"checkpoint is corrupted: {path}")
            if goal_id is None or checkpoint.goal_id == goal_id:
                checkpoints.append(checkpoint)
        return sorted(checkpoints, key=lambda item: (item.created_at, item.checkpoint_id))

    async def load_latest_unfinished(self, goal_id: str) -> WorkflowCheckpoint | None:
        """装载最近一份尚未走完其工作流单元的 checkpoint。"""
        checkpoints = await self.list_checkpoints(goal_id=goal_id)
        for checkpoint in reversed(checkpoints):
            if checkpoint.status is not WorkflowStatus.COMPLETED:
                return checkpoint
        return None

    @staticmethod
    def _state_from_checkpoint(checkpoint: WorkflowCheckpoint) -> GoalWorkflowState:
        aggregate_status = checkpoint.status
        if aggregate_status is WorkflowStatus.COMPLETED and checkpoint.phase is not WorkflowPhase.DONE:
            # 一个 checkpoint 完成一个工作单元；只有 done 阶段才代表 goal 完成。
            aggregate_status = WorkflowStatus.RUNNING
        return GoalWorkflowState(
            goal_id=checkpoint.goal_id,
            phase=checkpoint.phase,
            active_skill=checkpoint.active_skill,
            active_step=checkpoint.active_step,
            active_story=checkpoint.active_story,
            story_statuses=dict(checkpoint.story_statuses),
            status=aggregate_status,
            next_action=checkpoint.next_action,
            updated_at=checkpoint.created_at,
        )

    @staticmethod
    def _logical_dump(checkpoint: WorkflowCheckpoint) -> dict[str, Any]:
        """序列化 checkpoint 的身份，不含落盘时刻戳。

        ``created_at`` 在同一逻辑快照的两次写入之间本就允许不同（例如 pause/resume 周期
        重新签发同一份待恢复 checkpoint），因此不得参与冲突判定。
        """
        return checkpoint.model_dump(mode="json", exclude={"created_at"})

    def _path(self, checkpoint_id: str) -> Path:
        if not checkpoint_id or Path(checkpoint_id).name != checkpoint_id or checkpoint_id in {".", ".."}:
            raise WorkflowCheckpointError("checkpoint id must be a single path-safe name")
        return self._base / f"{checkpoint_id}.json"


class GoalWorkflowState(BaseModel):
    """单个 goal 的可序列化运行时元数据。

    工作流自身的产物仍是真源（请求看 ``brief.md``，Epic/Story 列表看 ``epics.md``）。
    本模型只存编排元数据，因此永不镜像或改写它们。
    """

    model_config = ConfigDict(frozen=True, validate_assignment=True)

    goal_id: str = Field(default_factory=lambda: uuid4().hex[:8], min_length=1)
    phase: WorkflowPhase = WorkflowPhase.DISCOVERY
    active_skill: str | None = None
    active_step: int | None = Field(default=None, ge=0)
    active_story: str | None = None
    # 旧 workflow.json 可能仍带 `active_stories` / `artifact_refs` 两个已派生化删除的镜像
    # 字段：容忍读（extra='ignore'），聚合态不再复制它们。
    story_statuses: dict[str, str] = Field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.PENDING
    next_action: str = ""
    updated_at: str = Field(default_factory=_iso_now)

    @model_validator(mode="after")
    def validate_terminal_status(self) -> GoalWorkflowState:
        """校验「终止态」两个字段互相自洽，返回自身以便链式调用。

        ``phase=done`` 与 ``status=completed`` 必须成对出现（任一单边都说明状态机跑
        到了不该有的组合）；非法组合抛 ``ValueError`` 而非改正——猜测哪一侧才是真
        意图会掩盖状态机的 bug。非终止态一律放行。
        """
        if self.phase is WorkflowPhase.DONE and self.status is not WorkflowStatus.COMPLETED:
            raise ValueError("done phase requires completed status")
        if self.status is WorkflowStatus.COMPLETED and self.phase is not WorkflowPhase.DONE:
            raise ValueError("completed status requires done phase")
        return self
