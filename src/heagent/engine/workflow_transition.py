"""Single, explicit transition table for the Goal workflow runner."""

from heagent.engine.checkpoint import WorkflowStatus
from heagent.engine.workflow_events import WorkflowEvent


class WorkflowTransitionError(ValueError):
    """An event is illegal for the current workflow status."""


_TRANSITIONS: dict[tuple[WorkflowStatus, WorkflowEvent], WorkflowStatus] = {
    (WorkflowStatus.PENDING, WorkflowEvent.START): WorkflowStatus.RUNNING,
    (WorkflowStatus.PENDING, WorkflowEvent.INPUT_MISSING): WorkflowStatus.BLOCKED,
    (WorkflowStatus.RUNNING, WorkflowEvent.STEP_COMPLETED): WorkflowStatus.PENDING,
    (WorkflowStatus.RUNNING, WorkflowEvent.CHECKPOINT_REQUIRED): WorkflowStatus.WAITING_USER,
    (WorkflowStatus.RUNNING, WorkflowEvent.GATE_FAILED): WorkflowStatus.BLOCKED,
    (WorkflowStatus.RUNNING, WorkflowEvent.EXECUTOR_FAILED): WorkflowStatus.FAILED,
    (WorkflowStatus.RUNNING, WorkflowEvent.FINAL_STEP_COMPLETED): WorkflowStatus.COMPLETED,
    (WorkflowStatus.WAITING_USER, WorkflowEvent.USER_RESUME): WorkflowStatus.PENDING,
    (WorkflowStatus.BLOCKED, WorkflowEvent.USER_RESUME): WorkflowStatus.PENDING,
    (WorkflowStatus.FAILED, WorkflowEvent.USER_RESUME): WorkflowStatus.PENDING,
    (WorkflowStatus.PENDING, WorkflowEvent.USER_PAUSE): WorkflowStatus.WAITING_USER,
    (WorkflowStatus.RUNNING, WorkflowEvent.USER_PAUSE): WorkflowStatus.WAITING_USER,
}


def transition(source: WorkflowStatus, event: WorkflowEvent) -> WorkflowStatus:
    """Return the next status or fail loudly for an undefined transition."""
    try:
        return _TRANSITIONS[(source, event)]
    except KeyError as exc:
        raise WorkflowTransitionError(f"illegal workflow transition: {source.value} + {event.value}") from exc
