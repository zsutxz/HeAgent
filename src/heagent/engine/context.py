"""Per-run runtime context and status models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def iso_now() -> str:
    """Return the current local timestamp in ISO-8601 seconds precision."""
    return datetime.now().isoformat(timespec="seconds")


class RunStatus(StrEnum):
    """Lifecycle state of a single agent run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunContext(BaseModel):
    """Mutable metadata associated with a single loop execution."""

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str | None = None
    parent_run_id: str | None = None
    workspace_root: str = Field(default_factory=lambda: str(Path.cwd().resolve()))
    started_at: str = Field(default_factory=iso_now)
    updated_at: str = Field(default_factory=iso_now)
    status: RunStatus = RunStatus.RUNNING
    iteration: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(
        self,
        *,
        iteration: int | None = None,
        status: RunStatus | None = None,
    ) -> None:
        """Advance the context clock and optionally update state fields."""
        if iteration is not None:
            self.iteration = iteration
        if status is not None:
            self.status = status
        self.updated_at = iso_now()
