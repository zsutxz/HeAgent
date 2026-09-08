"""运行时引擎（loop engine）公开 API。

本包是 epic 收尾后引入的 P0 运行时治理层（见 ``docs/frame.md`` 4.12），围绕
:class:`~heagent.agent.loop.AgentLoop` 提供策略门控、工具分发、运行快照、幂等账本与
事件总线，经 :class:`EngineContainer` 注入主循环。此处统一导出对外公开的类型。
"""

from heagent.engine.approval import (
    ApprovalDecision,
    ApprovalHandler,
    ApprovalRequest,
    ConsoleApprovalHandler,
    DenyAllApprovalHandler,
)
from heagent.engine.artifacts import (
    ArtifactContract,
    ArtifactContractError,
    ArtifactKind,
    ArtifactStatus,
    EpicArtifact,
    Frontmatter,
    GoalArtifact,
    StoryArtifact,
    assert_sprint_status_authority,
    parse_artifact,
    parse_frontmatter,
    validate_hierarchy,
    validate_sprint_status_path,
)
from heagent.engine.container import EngineContainer
from heagent.engine.context import RunContext, RunStatus
from heagent.engine.executor import ToolExecutor
from heagent.engine.hooks import HookConfig, HookManager, HookResult
from heagent.engine.ledger import ExecutionLedger, ExecutionRecord, ExecutionStatus, LedgerClaim
from heagent.engine.observability import EngineEvent, EventBus, LoggingObserver
from heagent.engine.policy import PolicyEngine, PolicyVerdict, ToolExecutionMode
from heagent.engine.store import RunSnapshot, RunStore
from heagent.engine.workflow import (
    GoalWorkflowState,
    RecoveryEnvelope,
    RolloverCoordinator,
    RolloverResult,
    TokenBudgetError,
    TokenBudgetManager,
    TokenBudgetState,
    WorkflowCheckpoint,
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    WorkflowOrchestrator,
    WorkflowPhase,
    WorkflowRoute,
    WorkflowStatus,
    build_recovery_envelope,
)
from heagent.engine.workflow_runner import (
    StorySpec,
    WorkflowGateError,
    WorkflowRunner,
    WorkflowRunnerState,
    WorkflowRunResult,
    WorkflowStepResult,
    parse_story_list,
)

__all__ = [
    "ArtifactContract",
    "ArtifactContractError",
    "ArtifactKind",
    "ArtifactStatus",
    "EpicArtifact",
    "Frontmatter",
    "GoalArtifact",
    "StoryArtifact",
    "assert_sprint_status_authority",
    "parse_artifact",
    "parse_frontmatter",
    "validate_hierarchy",
    "validate_sprint_status_path",
    "ApprovalDecision",
    "ApprovalHandler",
    "ApprovalRequest",
    "ConsoleApprovalHandler",
    "DenyAllApprovalHandler",
    "EngineContainer",
    "EngineEvent",
    "EventBus",
    "ExecutionLedger",
    "HookConfig",
    "HookManager",
    "HookResult",
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
    "GoalWorkflowState",
    "WorkflowCheckpoint",
    "WorkflowCheckpointError",
    "WorkflowCheckpointStore",
    "TokenBudgetError",
    "TokenBudgetManager",
    "TokenBudgetState",
    "RolloverCoordinator",
    "RolloverResult",
    "RecoveryEnvelope",
    "build_recovery_envelope",
    "WorkflowOrchestrator",
    "WorkflowPhase",
    "WorkflowRoute",
    "WorkflowStatus",
    "StorySpec",
    "parse_story_list",
    "WorkflowGateError",
    "WorkflowRunResult",
    "WorkflowRunner",
    "WorkflowRunnerState",
    "WorkflowStepResult",
]
