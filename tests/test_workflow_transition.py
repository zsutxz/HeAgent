"""Contract for the Goal runner's legal and illegal status changes."""

import pytest

from heagent.engine.checkpoint import WorkflowStatus as S
from heagent.engine.workflow_events import WorkflowEvent as E
from heagent.engine.workflow_transition import WorkflowTransitionError, transition


@pytest.mark.parametrize(
    ("source", "event", "target"),
    [
        (S.PENDING, E.START, S.RUNNING),
        (S.PENDING, E.INPUT_MISSING, S.BLOCKED),
        (S.RUNNING, E.STEP_COMPLETED, S.PENDING),
        (S.RUNNING, E.CHECKPOINT_REQUIRED, S.WAITING_USER),
        (S.RUNNING, E.GATE_FAILED, S.BLOCKED),
        (S.RUNNING, E.EXECUTOR_FAILED, S.FAILED),
        (S.RUNNING, E.FINAL_STEP_COMPLETED, S.COMPLETED),
        (S.WAITING_USER, E.USER_RESUME, S.PENDING),
        (S.BLOCKED, E.USER_RESUME, S.PENDING),
        (S.FAILED, E.USER_RESUME, S.PENDING),
        (S.PENDING, E.USER_PAUSE, S.WAITING_USER),
        (S.RUNNING, E.USER_PAUSE, S.WAITING_USER),
    ],
)
def test_legal_transition(source: S, event: E, target: S) -> None:
    assert transition(source, event) is target


@pytest.mark.parametrize("source", list(S))
def test_undefined_transition_fails(source: S) -> None:
    with pytest.raises(WorkflowTransitionError, match="illegal workflow transition"):
        transition(source, E.CANCELLED)
