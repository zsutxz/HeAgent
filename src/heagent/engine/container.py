"""运行时服务的依赖注入（DI）容器。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``EngineContainer``
把全部运行时服务（策略 / 执行器 / 运行快照 / 幂等账本 / 事件总线）聚合到一个对象，
经 :meth:`EngineContainer.default` 装配后注入 :class:`~heagent.agent.loop.AgentLoop`：

- 主 Agent 经 ``engine=EngineContainer.default()`` 持有；
- 子 Agent 经 ``parent_run_id`` **继承父 engine**（运行时服务复用，仅按角色替换 PolicyEngine，
  见 ``docs/frame.md`` 4.2 / D4）。

为何用 ``@dataclass``：本类是**装配容器**（持有协作对象），并非跨模块传输的数据模型，
故不套用 Pydantic ``BaseModel``（项目硬约束的 Pydantic 例外仅限数据模型，见 CLAUDE.md）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heagent.engine.context import RunContext
from heagent.engine.executor import ToolExecutor
from heagent.engine.ledger import ExecutionLedger
from heagent.engine.observability import EventBus, LoggingObserver
from heagent.engine.policy import PolicyEngine
from heagent.engine.store import RunStore

if TYPE_CHECKING:
    from heagent.tools.sandbox import CommandRunner


@dataclass
class EngineContainer:
    """跨多次 loop 执行共享的运行时服务集合。"""

    # 工具准入 / 审批 / 沙箱裁决（policy.py）。
    policy: PolicyEngine = field(default_factory=PolicyEngine)
    # 按 PolicyVerdict 分发工具调用（executor.py）。
    executor: ToolExecutor = field(default_factory=ToolExecutor)
    # 运行快照持久化（store.py，.heagent/runs/）。
    run_store: RunStore = field(default_factory=RunStore)
    # 幂等与租约账本（ledger.py，.heagent/ledger/）。
    ledger: ExecutionLedger = field(default_factory=ExecutionLedger)
    # 事件总线，默认带一个日志观察者（observability.py）。
    events: EventBus = field(default_factory=lambda: EventBus([LoggingObserver()]))
    # 工作区根目录（绝对路径）；为 None 时由 create_run_context 兜底到 cwd。
    workspace_root: str | None = None
    # SANDBOX_REQUIRED 路径用的子进程沙箱后端（None = 透传）；__post_init__ 注入 executor。
    command_runner: CommandRunner | None = None

    def __post_init__(self) -> None:
        """把 container 级 command_runner 注入 executor（SANDBOX_REQUIRED 路径后端）。

        仅当 container 显式持有 runner 且 executor 尚未自带后端时才注入——
        避免覆写 executor 显式指定的后端（如
        ``EngineContainer(executor=ToolExecutor(sandbox_runner=backend))``）。
        若 executor 已持有 sandbox_runner，container 级的 command_runner 不会
        静默覆盖（executor 的显式后端优先）。
        """
        if self.command_runner is not None and self.executor.sandbox_runner is None:
            self.executor.sandbox_runner = self.command_runner

    @classmethod
    def default(cls, *, workspace_root: str | None = None) -> EngineContainer:
        """为当前工作区创建默认装配的容器。

        把 ``workspace_root`` 同步到 ``policy.workspace_root``（路径围栏基线）以保持一致；
        若 policy 已自带 root 则不覆盖。
        """
        container = cls(workspace_root=workspace_root)
        if workspace_root and not container.policy.workspace_root:
            container.policy.workspace_root = workspace_root
        return container

    def create_run_context(
        self,
        *,
        session_id: str | None = None,
        parent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        workspace_root: str | None = None,
    ) -> RunContext:
        """构造一个绑定到本容器的全新单次运行上下文。

        工作区根解析优先级：显式参数 > 容器 > policy > 当前工作目录（cwd）。
        ``metadata`` 做浅拷贝，避免外部字典被 run 侧修改反向污染。
        """
        root = workspace_root or self.workspace_root or self.policy.workspace_root or str(Path.cwd().resolve())
        return RunContext(
            session_id=session_id,
            parent_run_id=parent_run_id,
            workspace_root=root,
            metadata=dict(metadata or {}),
        )
