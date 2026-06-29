"""运行时引擎（loop engine）公开 API。

本包是 epic 收尾后引入的 P0 运行时治理层（见 ``docs/frame.md`` 4.12），围绕
:class:`~heagent.agent.loop.AgentLoop` 提供策略门控、工具分发、运行快照、幂等账本与
事件总线，经 :class:`EngineContainer` 注入主循环。此处统一导出对外公开的类型。
"""

from heagent.engine.container import EngineContainer
from heagent.engine.context import RunContext, RunStatus
from heagent.engine.executor import ToolExecutor
from heagent.engine.ledger import ExecutionLedger, ExecutionRecord, ExecutionStatus, LedgerClaim
from heagent.engine.observability import EngineEvent, EventBus, LoggingObserver
from heagent.engine.policy import PolicyEngine, PolicyVerdict, ToolExecutionMode
from heagent.engine.store import RunSnapshot, RunStore

__all__ = [
    "EngineContainer",
    "EngineEvent",
    "EventBus",
    "ExecutionLedger",
    "ExecutionRecord",
    "ExecutionStatus",
    "ToolExecutor",
    "LedgerClaim",
    "LoggingObserver",
    "PolicyEngine",
    "PolicyVerdict",
    "ToolExecutionMode",
    "RunContext",
    "RunSnapshot",
    "RunStatus",
    "RunStore",
]
