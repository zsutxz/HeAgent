from __future__ import annotations

import pytest

from heagent.engine.workflow import (
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    TokenBudgetError,
    TokenBudgetManager,
    RolloverCoordinator,
    build_recovery_envelope,
    WorkflowOrchestrator,
    WorkflowPhase,
    WorkflowRoute,
    WorkflowStatus,
    WorkflowTransitionError,
)


def test_initial_state_owns_runtime_metadata_only() -> None:
    state = GoalWorkflowState(goal_id="goal-1", active_story="43.1")

    assert state.phase is WorkflowPhase.DISCOVERY
    assert state.status is WorkflowStatus.PENDING
    assert state.artifact_refs == []
    assert "checkbox" not in state.model_dump()


def test_valid_transition_is_deterministic_and_preserves_story_reference() -> None:
    state = GoalWorkflowState(goal_id="goal-1", active_story="43.1")

    next_state = WorkflowOrchestrator.transition(
        state,
        WorkflowPhase.PLANNING,
        reason="requirements confirmed",
    )

    assert next_state.phase is WorkflowPhase.PLANNING
    assert next_state.status is WorkflowStatus.RUNNING
    assert next_state.active_story == "43.1"
    assert next_state.transition_reason == "requirements confirmed"
    assert state.phase is WorkflowPhase.DISCOVERY


def test_illegal_transition_and_missing_precondition_fail_loudly() -> None:
    state = GoalWorkflowState()

    with pytest.raises(WorkflowTransitionError, match="illegal workflow transition"):
        WorkflowOrchestrator.transition(state, WorkflowPhase.REVIEW, reason="skip")
    with pytest.raises(WorkflowTransitionError, match="preconditions"):
        WorkflowOrchestrator.transition(
            state,
            WorkflowPhase.PLANNING,
            reason="missing artifacts",
            preconditions_met=False,
        )


def test_blocked_and_failed_states_cannot_be_advanced() -> None:
    blocked = WorkflowOrchestrator.block(GoalWorkflowState(), "missing PRD")
    failed = WorkflowOrchestrator.fail(GoalWorkflowState(), "provider unavailable")

    assert blocked.status is WorkflowStatus.BLOCKED
    assert failed.status is WorkflowStatus.FAILED
    for state in (blocked, failed):
        assert not WorkflowOrchestrator.can_transition(state, WorkflowPhase.PLANNING)
        with pytest.raises(WorkflowTransitionError, match="cannot transition"):
            WorkflowOrchestrator.transition(state, WorkflowPhase.PLANNING, reason="retry")


def test_done_is_terminal() -> None:
    state = GoalWorkflowState(phase=WorkflowPhase.REVIEW)
    done = WorkflowOrchestrator.transition(state, WorkflowPhase.DONE, reason="review passed")

    assert done.status is WorkflowStatus.COMPLETED
    assert not WorkflowOrchestrator.can_transition(done, WorkflowPhase.REVIEW)
    for operation in (WorkflowOrchestrator.block, WorkflowOrchestrator.fail):
        with pytest.raises(WorkflowTransitionError, match="terminal"):
            operation(done, "must remain terminal")


def test_waiting_user_and_invalid_targets_cannot_bypass_gate() -> None:
    waiting = GoalWorkflowState(status=WorkflowStatus.WAITING_USER)

    assert not WorkflowOrchestrator.can_transition(waiting, WorkflowPhase.PLANNING)
    with pytest.raises(WorkflowTransitionError, match="cannot transition"):
        WorkflowOrchestrator.transition(waiting, WorkflowPhase.PLANNING, reason="bypass")
    with pytest.raises(WorkflowTransitionError, match="unknown target"):
        WorkflowOrchestrator.transition(GoalWorkflowState(), "not-a-phase", reason="invalid")  # type: ignore[arg-type]


def test_transition_deep_copies_mutable_fields_and_reaches_retrospective() -> None:
    state = GoalWorkflowState(phase=WorkflowPhase.REVIEW, artifact_refs=["prd.md"])
    retrospective = WorkflowOrchestrator.transition(state, WorkflowPhase.RETROSPECTIVE, reason="review passed")

    retrospective.artifact_refs.append("architecture.md")
    assert state.artifact_refs == ["prd.md"]
    done = WorkflowOrchestrator.transition(retrospective, WorkflowPhase.DONE, reason="retro complete")
    assert done.status is WorkflowStatus.COMPLETED


def test_route_blocks_missing_planning_artifacts_and_waits_for_user() -> None:
    state = GoalWorkflowState(phase=WorkflowPhase.PLANNING)

    blocked = WorkflowOrchestrator.route(state, available_artifacts=["brief.md"])
    waiting = WorkflowOrchestrator.route(
        GoalWorkflowState(phase=WorkflowPhase.DISCOVERY), waiting_for_user=True
    )

    assert blocked.status is WorkflowStatus.BLOCKED
    assert blocked.missing_artifacts == ["PRD or Spec", "architecture"]
    assert waiting.status is WorkflowStatus.WAITING_USER


def test_route_resolves_explicit_alias_and_prefers_it() -> None:
    class _Package:
        metadata = type("Metadata", (), {"canonical_id": "he-prd"})()

    class _Resolver:
        def __init__(self) -> None:
            self.requested: str | None = None

        def resolve(self, skill_id: str) -> _Package:
            self.requested = skill_id
            return _Package()

    resolver = _Resolver()
    route = WorkflowOrchestrator.route(
        GoalWorkflowState(phase=WorkflowPhase.DISCOVERY), resolver=resolver, requested_skill="bmad-prd"
    )

    assert isinstance(route, WorkflowRoute)
    assert resolver.requested == "bmad-prd"
    assert route.skill_id == "he-prd"


def test_route_review_defaults_to_retrospective_not_implementation_loop() -> None:
    route = WorkflowOrchestrator.route(
        GoalWorkflowState(phase=WorkflowPhase.REVIEW),
        available_artifacts=["test-results"],
    )

    assert route.target_phase is WorkflowPhase.RETROSPECTIVE


def test_wait_for_user_retains_step_and_prompt() -> None:
    state = GoalWorkflowState(active_skill="he-build", active_step=3, active_story="43.2")

    waiting = WorkflowOrchestrator.wait_for_user(state, "请确认 Epic 边界后继续")

    assert waiting.status is WorkflowStatus.WAITING_USER
    assert waiting.active_step == 3
    assert waiting.active_story == "43.2"
    assert waiting.next_action == "请确认 Epic 边界后继续"
    route = WorkflowOrchestrator.route(waiting)
    assert route.status is WorkflowStatus.WAITING_USER
    assert route.active_step == 3
    assert route.next_action == "请确认 Epic 边界后继续"


@pytest.mark.asyncio
async def test_checkpoint_save_is_atomic_and_idempotent(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"))
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="goal1-run1-step0",
        goal_id="goal1",
        phase=WorkflowPhase.PLANNING,
        status=WorkflowStatus.COMPLETED,
        run_id="run1",
        next_action="await user",
    )

    first = await store.save(checkpoint)
    second = await store.save(checkpoint.model_copy(deep=True))
    assert first == second
    loaded = await store.load(checkpoint.checkpoint_id)
    assert loaded is not None
    assert loaded.next_action == "await user"
    workflow = await store.load_workflow()
    assert workflow is not None
    assert workflow.goal_id == "goal1"
    assert (tmp_path / "workflow.json").exists()


@pytest.mark.asyncio
async def test_checkpoint_store_loads_latest_unfinished_and_rejects_corruption(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"))
    await store.save(
        WorkflowCheckpoint(
            checkpoint_id="goal1-step1",
            goal_id="goal1",
            phase=WorkflowPhase.PLANNING,
            status=WorkflowStatus.COMPLETED,
            run_id="run1",
            created_at="2026-09-01T10:00:00",
        )
    )
    await store.save(
        WorkflowCheckpoint(
            checkpoint_id="goal1-step2",
            goal_id="goal1",
            phase=WorkflowPhase.SPRINT,
            status=WorkflowStatus.WAITING_USER,
            run_id="run2",
            active_step=2,
            created_at="2026-09-01T10:01:00",
        )
    )
    latest = await store.load_latest_unfinished("goal1")
    assert latest is not None
    assert latest.checkpoint_id == "goal1-step2"

    (tmp_path / "checkpoints" / "broken.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(WorkflowCheckpointError, match="corrupted"):
        await store.load("broken")


@pytest.mark.asyncio
async def test_checkpoint_rejects_in_flight_conflicts_and_unsafe_ids(tmp_path) -> None:
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"))
    in_flight = WorkflowCheckpoint(
        checkpoint_id="goal1-run1-step0",
        goal_id="goal1",
        phase=WorkflowPhase.PLANNING,
        status=WorkflowStatus.RUNNING,
        run_id="run1",
        tool_in_flight=True,
    )
    with pytest.raises(WorkflowCheckpointError, match="in flight"):
        await store.save(in_flight)

    checkpoint = in_flight.model_copy(update={"tool_in_flight": False, "status": WorkflowStatus.COMPLETED})
    await store.save(checkpoint)
    with pytest.raises(WorkflowCheckpointError, match="conflict"):
        await store.save(checkpoint.model_copy(update={"next_action": "different"}))
    with pytest.raises(WorkflowCheckpointError, match="path-safe"):
        await store.load("../escape")


def test_token_budget_tracks_segment_and_cumulative_counters() -> None:
    manager = TokenBudgetManager(segment_limit=100, rollover_threshold=0.8)

    assert manager.should_rollover(79) is False
    manager.record(prompt_tokens=50, completion_tokens=25)
    assert manager.should_rollover(5) is True
    state = manager.rollover()
    assert state.segment_index == 1
    assert state.segment_tokens == 0
    assert state.cumulative_tokens == 75


def test_token_budget_rejects_invalid_counts_and_configuration() -> None:
    with pytest.raises(TokenBudgetError):
        TokenBudgetManager(segment_limit=0)
    manager = TokenBudgetManager(segment_limit=100)
    with pytest.raises(TokenBudgetError, match="non-negative"):
        manager.record(prompt_tokens=-1, completion_tokens=0)
    with pytest.raises(TokenBudgetError, match="non-negative"):
        manager.should_rollover(-1)


@pytest.mark.asyncio
async def test_rollover_checkpoints_before_reset_and_starts_fresh_run() -> None:
    manager = TokenBudgetManager(segment_limit=100)
    events: list[str] = []

    async def checkpoint(run_id: str) -> None:
        events.append(f"checkpoint:{run_id}")

    async def start_run(parent_run_id: str) -> str:
        events.append(f"start:{parent_run_id}")
        return "run2"

    result = await RolloverCoordinator(checkpoint, start_run).rollover(manager, run_id="run1")

    assert events == ["checkpoint:run1", "start:run1"]
    assert result.new_segment == 1
    assert result.new_run_id == "run2"


@pytest.mark.asyncio
async def test_rollover_rejects_in_flight_without_callbacks() -> None:
    manager = TokenBudgetManager(segment_limit=100)
    called = False

    async def callback(_: str) -> None:
        nonlocal called
        called = True

    with pytest.raises(TokenBudgetError, match="in flight"):
        await RolloverCoordinator(callback, callback).rollover(manager, run_id="run1", tool_in_flight=True)
    assert called is False


def test_recovery_envelope_is_bounded_and_has_deterministic_summary_fallback() -> None:
    state = GoalWorkflowState(active_story="43.3", artifact_refs=["checkpoint.json"])
    envelope = build_recovery_envelope(
        state,
        acceptance_evidence=["checkpoint written"],
        summary_error="summary timeout",
        next_action="resume step",
    )

    assert envelope.version == 1
    assert envelope.checkpoint_summary.startswith("goal=")
    assert envelope.summary_error == "summary timeout"
    assert not hasattr(envelope, "messages")
