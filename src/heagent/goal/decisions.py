"""步骤级人工决策日志：版本化模型 + 追加式存储（Story 51-5）。

**为什么在引擎而非声明**（AD-14 证明，与 51-3 证据同款论证）：决策记录是**运行期事实**
——含时间、原文（拒绝理由 / 修订补充 / resume 回复）与影响范围；Markdown 声明只能表达
「这一步要不要人工确认」（``approval: required``），承载不了记录本体。模型因此落在本模块，
词汇保持通用：不认识任何具体 Epic / Story / 步骤（AD-13）——「第几步需要审批」只存在于
该步的 ``approval:`` 声明里，``src/`` 不出现任何按步骤名 / 序号的审批判断。

两条硬边界：

1. **决策是工作流产物，不写进 workflow 包**：记录落 ``<goal_dir>/decisions/``，随 goal
   一起持久化与恢复；approve / reject / amend / resume 每次一条，重跑不覆盖历史。
2. **追加式**：:class:`DecisionStore` 对同一 ``decision_id`` 的第二次写入显性报错（独占
   创建，并发写只有一家成功），重跑不得覆盖历史；``schema_version`` 不为当前版本同样拒绝。

四个动作语义独立（AD-3）：approve 接受并推进、reject 驳回（步骤未完成、BLOCKED 等待重做）、
amend 带补充重跑（步骤未完成）、resume 仅恢复执行——**resume 不是 approve**，审批门挂起时
被 :meth:`heagent.engine.workflow_runner.WorkflowRunner.resume` 显性拒绝。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from heagent.engine.checkpoint import WorkflowStatus
from heagent.pub.persist import load_json_model

DECISION_SCHEMA_VERSION = "1"

# decision id 白名单：与 goal/evidence.py 的 evidence id 同规（单个路径安全名，charset 已排除
# 路径分隔符与 ``.``；Windows 保留设备名提前显性报错）。两处「同规的独立实现」刻意不共享——
# 耦合一个跨模块公共模块比复制一个 10 行守卫更贵（架构判据「同格式独立实现」先例）。
_DECISION_ID_PATTERN = re.compile(r"[0-9A-Za-z_-]+")
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{index}" for index in range(1, 10)), *(f"lpt{index}" for index in range(1, 10))}
)


class DecisionAction(StrEnum):
    """一次人工决策的动作（ approve / reject / amend / resume 语义独立，AD-3）。"""

    APPROVE = "approve"
    REJECT = "reject"
    AMEND = "amend"
    RESUME = "resume"


class DecisionError(ValueError):
    """Raised when a decision cannot be recorded, located, or listed."""


def _utc_now_iso() -> str:
    """UTC 微秒 ISO 时间戳（``+00:00`` 后缀恒定，字典序 = 时间序）。"""
    return datetime.now(UTC).isoformat(timespec="microseconds")


class DecisionRecord(BaseModel):
    """一条人工决策的追加式记录（id、步骤、原文、时间、影响范围、结果）。

    - ``step`` / ``story_id`` 是**影响范围**：决策落在哪个声明步骤（与 story，story 级为空
      = 步骤级决策）；名字来自声明的步骤，不是代码里判定的步骤（AD-13）。
    - ``raw_text`` 是**原文**：拒绝理由 / 修订补充 / resume 回复逐字保存（audit 面的事实）；
      approve 无执行语义文本，原值为空。
    - ``workflow_status`` 是**结果**：决策落定后的 workflow 状态（approve → pending /
      waiting_user / completed；reject → blocked；amend → pending；resume → pending）。
    - ``approval_round`` 是决策发生时的审批门轮次（runner 状态的单调计数）：reject → 重跑 →
      再挂门后的记录可与轮次关联（审查 #17）。
    - ``created_at`` 用 **UTC** ISO：字典序 = 时间序，:meth:`DecisionStore.list_records` 的
      ``(created_at, decision_id)`` 排序因此单调。
    """

    schema_version: str = DECISION_SCHEMA_VERSION
    decision_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    action: DecisionAction
    step: str = ""
    story_id: str = ""
    raw_text: str = ""
    workflow_status: WorkflowStatus = WorkflowStatus.PENDING
    approval_round: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=_utc_now_iso)


def new_decision_id() -> str:
    """Fresh decision id（``[0-9A-Za-z_-]`` 白名单内的 hex，见 ``DecisionStore._path``）。"""
    return uuid4().hex


class DecisionStore:
    """追加式决策存取：一次决策一个 JSON 文件，独占创建、绝不覆盖历史。

    与 :class:`~heagent.goal.evidence.EvidenceStore` 同款实现立场：append-only 靠
    **独占创建**（``open("x")``）——同 id 二次写、跨进程并发同 id 写都只有一家成功；崩溃
    中断只留半截文件，读取时按「损坏」显性报错（不静默）；读取侧拒绝一切 ``schema_version``
    不等于当前版本的记录（版本化有门）。

    并发立场的如实声明（审查 #15）：本类**不持锁**——每实例 ``asyncio.Lock`` 挡不住跨进程
    （甚至挡不住同进程的另一个实例），真实的互斥保证全部来自 ``open("x")`` 的独占创建与
    goal 域锁（:func:`heagent.goal.mutex.goal_mutex`，台账 A32② 起：变更内核
    ``advance`` / ``pause_resume`` / ``record_decision`` 自持该锁，不再依赖入口层）。
    直接经本类的读路径（如 ``/goal status`` 的快照读）**不在锁内**——半截文件按
    「损坏」显性报错，不静默。
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """Directory this store reads and writes."""
        return self._root

    def _path(self, decision_id: str) -> Path:
        if (
            not decision_id
            or not _DECISION_ID_PATTERN.fullmatch(decision_id)
            or decision_id.casefold() in _WINDOWS_DEVICE_NAMES
        ):
            raise DecisionError("decision id must match [0-9A-Za-z_-]+ and must not be a reserved device name")
        return self._root / f"{decision_id}.json"

    @staticmethod
    def _require_current_schema(record: DecisionRecord) -> None:
        if record.schema_version != DECISION_SCHEMA_VERSION:
            raise DecisionError(
                f"decision schema version {record.schema_version!r} is not supported "
                f"(expected {DECISION_SCHEMA_VERSION!r})"
            )

    async def append(self, record: DecisionRecord) -> Path:
        """持久化一条新决策；同 id 已存在（或损坏残留）即显性报错，绝不覆盖。"""
        self._require_current_schema(record)
        path = self._path(record.decision_id)
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2)
        if await asyncio.to_thread(path.exists):
            existing = await asyncio.to_thread(load_json_model, path, DecisionRecord)
            if existing is None:
                raise DecisionError(f"decision record is corrupted: {path}")
            raise DecisionError(f"decision record already exists (append-only): {record.decision_id}")
        try:
            await asyncio.to_thread(self._create_exclusive, path, payload)
        except FileExistsError as exc:  # 跨进程并发同 id 写：独占创建只有一家成功
            raise DecisionError(f"decision record already exists (append-only): {record.decision_id}") from exc
        return path

    @staticmethod
    def _create_exclusive(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)  # 写者是 store 自身：首次 append 建自己的目录
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)

    async def load(self, decision_id: str) -> DecisionRecord | None:
        """按 id 取回；不存在返回 ``None``，存在但损坏或版本不符显性报错。"""
        path = self._path(decision_id)
        record = await asyncio.to_thread(load_json_model, path, DecisionRecord)
        if path.exists() and record is None:
            raise DecisionError(f"decision record is corrupted: {path}")
        if record is not None:
            self._require_current_schema(record)
        return record

    async def list_records(self, *, goal_id: str | None = None) -> list[DecisionRecord]:
        """按 ``(created_at, decision_id)`` 列出决策（UTC 时间戳，字典序单调）；损坏 / 版本不符显性报错。

        ``goal_id`` 给出时只取该 goal 的记录（决策目录本身按 goal 划分，此过滤防御误指向的
        根目录）；目录不存在 = 还没有任何决策，返回空表（不是错误）。
        """
        if not await asyncio.to_thread(self._root.exists):
            return []
        records: list[DecisionRecord] = []
        for path in sorted(await asyncio.to_thread(lambda: list(self._root.glob("*.json")))):
            record = await asyncio.to_thread(load_json_model, path, DecisionRecord)
            if record is None:
                raise DecisionError(f"decision record is corrupted: {path}")
            self._require_current_schema(record)
            if goal_id is not None and record.goal_id != goal_id:
                continue
            records.append(record)
        return sorted(records, key=lambda item: (item.created_at, item.decision_id))


def decision_store(goal_dir: Path) -> DecisionStore:
    """决策存取的**唯一位置解析点**（与 ``application.checkpoint_store`` / ``evidence_store``
    同款先例）：``<goal_dir>/decisions/``。预检 / 展示方不得另算一份路径。"""
    return DecisionStore(goal_dir / "decisions")
