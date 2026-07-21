"""运行时服务的依赖注入（DI）容器。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``EngineContainer``
把全部运行时服务（策略 / 执行器 / 运行快照 / 幂等账本 / 事件总线）聚合到一个对象，
经 :meth:`EngineContainer.default` 装配后注入 :class:`~heagent.agent.loop.AgentLoop`：

- 主 Agent 经 ``engine=EngineContainer.default()`` 持有；
- 子 Agent 经 ``parent_run_id`` **继承父 engine**（运行时服务复用，仅按角色替换 PolicyEngine，
  见 ``docs/frame.md`` 4.2 / D4）。

V2 新增：``enable_file_locks`` 参数——开启后 ``RunStore``/``ExecutionLedger`` 的写操作
自动获取跨进程文件锁，防止多进程并发写 ``.heagent/`` 时数据损坏。
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


@dataclass
class EngineContainer:
    """跨多次 loop 执行共享的运行时服务集合。"""

    policy: PolicyEngine = field(default_factory=PolicyEngine)
    executor: ToolExecutor = field(default_factory=ToolExecutor)
    run_store: RunStore = field(default_factory=RunStore)
    ledger: ExecutionLedger = field(default_factory=ExecutionLedger)
    events: EventBus = field(default_factory=lambda: EventBus([LoggingObserver()]))
    workspace_root: str | None = None
    command_runner: CommandRunner | None = None
    enable_file_locks: bool = False

    def __post_init__(self) -> None:
        # 注入 cross-process file locks（V2）
        if self.enable_file_locks:
            self.run_store._enable_locks = True
            self.ledger._enable_locks = True

        # P1-22 修复：仅在 executor 未显式设置 sandbox_runner 时注入（含显式 None），
        # 避免覆盖调用方「禁用沙箱」的意图。command_runner 非 None 而 executor 已有
        # runner 时记 warning，使运营方可感知配置冲突。
        if self.command_runner is not None:
            if self.executor.sandbox_runner is not None:
                logger.warning(
                    "command_runner is set but executor.sandbox_runner is already %s; "
                    "command_runner is ignored",
                    type(self.executor.sandbox_runner).__name__,
                )
            else:
                self.executor.sandbox_runner = self.command_runner

    @classmethod
    def default(cls, *, workspace_root: str | None = None, sandbox_backend: str | None = None) -> EngineContainer:
        """为当前工作区创建默认装配的容器。

        读取 ``Settings.sandbox_backend`` 自动构造对应的 ``CommandRunner``（FR-S4）：
        - ``"passthrough"`` → ``command_runner=None``（透传快速路径）
        - ``"firejail"`` → ``FirejailBackend`` 实例
        - ``"winjob"`` → ``WinJobBackend`` 实例（FR-A3，Windows Job Objects）

        ``sandbox_backend`` 显式传入时优先于 Settings。
        """
        from heagent.config import get_settings

        settings = get_settings()
        backend = sandbox_backend if sandbox_backend is not None else settings.sandbox_backend
        command_runner = None
        if backend == "firejail":
            from heagent.tools.sandbox import FirejailBackend

            command_runner = FirejailBackend(
                firejail_path=settings.sandbox_firejail_path,
                workspace_root=workspace_root,
            )
        elif backend == "winjob":
            from heagent.tools.sandbox import WinJobBackend

            if WinJobBackend.available():
                command_runner = WinJobBackend()
            else:
                logger.warning("WinJobBackend requested but not available; falling back to Passthrough")

        container = cls(workspace_root=workspace_root, command_runner=command_runner)
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
        root: str | None = workspace_root
        if root is None:
            root = self.workspace_root
        if root is None:
            root = self.policy.workspace_root
        if root is None:
            root = str(Path.cwd().resolve())
        return RunContext(
            session_id=session_id,
            parent_run_id=parent_run_id,
            workspace_root=root,
            metadata=dict(metadata or {}),
        )
