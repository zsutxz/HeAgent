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
        (S.RUNNING, E.APPROVAL_REQUIRED, S.WAITING_USER),
        (S.RUNNING, E.GATE_FAILED, S.BLOCKED),
        (S.RUNNING, E.EXECUTOR_FAILED, S.FAILED),
        (S.RUNNING, E.CANCELLED, S.PENDING),
        (S.RUNNING, E.FINAL_STEP_COMPLETED, S.COMPLETED),
        (S.WAITING_USER, E.USER_RESUME, S.PENDING),
        (S.WAITING_USER, E.USER_APPROVE, S.RUNNING),
        (S.WAITING_USER, E.USER_REJECT, S.BLOCKED),
        (S.WAITING_USER, E.USER_AMEND, S.PENDING),
        (S.BLOCKED, E.USER_RESUME, S.PENDING),
        (S.FAILED, E.USER_RESUME, S.PENDING),
        (S.PENDING, E.USER_PAUSE, S.WAITING_USER),
        (S.RUNNING, E.USER_PAUSE, S.WAITING_USER),
    ],
)
def test_legal_transition(source: S, event: E, target: S) -> None:
    assert transition(source, event) is target


@pytest.mark.parametrize("source", [status for status in S if status is not S.RUNNING])
def test_undefined_transition_fails(source: S) -> None:
    with pytest.raises(WorkflowTransitionError, match="illegal workflow transition"):
        transition(source, E.CANCELLED)


def test_approval_gate_decisions_are_distinct_events() -> None:
    """approve / reject / amend / resume 是四个不同事件（AD-3），不得互相顶替。"""
    decisions = {E.USER_APPROVE, E.USER_REJECT, E.USER_AMEND, E.USER_RESUME}
    assert {event for event in E if event.value.startswith("user_")} - {E.USER_PAUSE} == decisions
    targets = {
        event: transition(S.WAITING_USER, event)
        for event in (E.USER_APPROVE, E.USER_REJECT, E.USER_AMEND, E.USER_RESUME)
    }
    assert targets[E.USER_APPROVE] is S.RUNNING  # approve 后由既有完成事件落定终点
    assert targets[E.USER_REJECT] is S.BLOCKED
    assert targets[E.USER_AMEND] is S.PENDING
    assert targets[E.USER_RESUME] is S.PENDING
