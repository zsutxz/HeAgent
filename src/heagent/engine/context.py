"""单次运行的运行时上下文与状态模型。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12），定义
:class:`~heagent.agent.loop.AgentLoop` 每次 ``run()`` 期间随迭代演进的**可变元数据**：

- :class:`RunContext` —— 一次 run 的上下文（run_id / session_id / parent_run_id /
  workspace_root / iteration / status / metadata），由
  :meth:`EngineContainer.create_run_context` 产出；每轮迭代经 :meth:`RunContext.touch`
  推进，:class:`~heagent.engine.store.RunStore` 据此持久化快照。
- :class:`RunStatus` —— run 生命周期状态枚举（running / completed / failed）。

设计要点：``RunContext`` 为 Pydantic ``BaseModel``（项目硬约束：跨模块数据用 Pydantic）。
其中 ``metadata`` 字段是策略层与执行层之间的「运行态授权通道」—— :class:`PolicyEngine`
读取其中的 ``approved_tools`` / ``sandboxed_tools`` / ``sandbox_profiles`` /
``sandbox_active`` 判断审批与沙箱授权是否已授予（见 ``policy.py``）。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def iso_now() -> str:
    """返回当前本地时间的 ISO-8601 字符串（秒精度）。

    统一为各模型的时间戳字段（``started_at`` / ``updated_at`` 等）提供一致格式，
    秒精度足够运行记录与租约过期判断使用。
    """
    return datetime.now().isoformat(timespec="seconds")


class RunStatus(StrEnum):
    """单次 agent run 的生命周期状态。

    ``StrEnum`` 使序列化到 JSON 快照时直接得到字符串值（``"running"`` 等）。
    """

    RUNNING = "running"        # 运行中：AgentLoop 正在迭代
    COMPLETED = "completed"    # 已完成：正常产出最终答案
    FAILED = "failed"          # 已失败：抛出异常或被门控终止


class RunContext(BaseModel):
    """与单次 loop 执行关联的可变元数据。

    每次 :meth:`~heagent.agent.loop.AgentLoop.run` 调用持有一个 ``RunContext``，
    随迭代推进（iteration / updated_at / status），并作为运行态授权与持久化的载体。
    """

    # 本 run 唯一标识（uuid4 十六进制）；亦作 RunStore 快照文件名与 ledger 幂等键组成部分。
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    # 会话 id（跨轮对话历史）；交互模式按此自动保存 / 恢复消息。
    session_id: str | None = None
    # 父 run 的 run_id；子 Agent 经此挂到父 run 树（build_run_tree 聚合依据）。
    parent_run_id: str | None = None
    # 工作区根目录（绝对路径）；PolicyEngine 路径围栏与 file 工具的基线。
    workspace_root: str = Field(default_factory=lambda: str(Path.cwd().resolve()))
    # 创建时间戳（ISO-8601 秒精度）。
    started_at: str = Field(default_factory=iso_now)
    # 最近一次 touch 的时间戳；随每次迭代刷新。
    updated_at: str = Field(default_factory=iso_now)
    # 生命周期状态；初始 RUNNING，结束时置 COMPLETED / FAILED。
    status: RunStatus = RunStatus.RUNNING
    # 当前迭代轮次（0 起，每轮 +1）。
    iteration: int = 0
    # 运行态元数据：策略层读 approved_tools / sandboxed_tools / sandbox_profiles /
    # sandbox_active 判断授权；亦承载子 Agent 角色、cron 等附加信息。
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(
        self,
        *,
        iteration: int | None = None,
        status: RunStatus | None = None,
    ) -> None:
        """推进上下文时钟，可选更新迭代号 / 状态。

        每轮迭代末尾由 AgentLoop 调用：把 ``updated_at`` 刷新为当前时间，便于 RunStore
        快照体现最新进度。``iteration`` / ``status`` 为 ``None`` 时保持原值不变。
        """
        if iteration is not None:
            self.iteration = iteration
        if status is not None:
            self.status = status
        self.updated_at = iso_now()
