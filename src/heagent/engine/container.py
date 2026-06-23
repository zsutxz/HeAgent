"""Dependency container for P0 runtime services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from heagent.engine.context import RunContext
from heagent.engine.executor import ToolExecutor
from heagent.engine.ledger import ExecutionLedger
from heagent.engine.observability import EventBus, LoggingObserver
from heagent.engine.policy import PolicyEngine
from heagent.engine.store import RunStore


@dataclass
class EngineContainer:
    """Shared runtime services used across loop executions."""

    policy: PolicyEngine = field(default_factory=PolicyEngine)
    executor: ToolExecutor = field(default_factory=ToolExecutor)
    run_store: RunStore = field(default_factory=RunStore)
    ledger: ExecutionLedger = field(default_factory=ExecutionLedger)
    events: EventBus = field(default_factory=lambda: EventBus([LoggingObserver()]))
    workspace_root: str | None = None

    @classmethod
    def default(cls, *, workspace_root: str | None = None) -> EngineContainer:
        """Create a default container configured for the current workspace."""
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
        """Construct a fresh per-run context bound to this container."""
        root = workspace_root or self.workspace_root or self.policy.workspace_root or str(Path.cwd().resolve())
        return RunContext(
            session_id=session_id,
            parent_run_id=parent_run_id,
            workspace_root=root,
            metadata=dict(metadata or {}),
        )
