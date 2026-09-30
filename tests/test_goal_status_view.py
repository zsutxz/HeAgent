"""The shared Goal status projection rendered by the CLI, GUI and cron entry points."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from heagent.cli import goal as goal_cli
from heagent.engine.checkpoint import WorkflowCheckpointStore, WorkflowStatus
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.engine.workflow_runner import (
    WorkflowRunner,
    WorkflowRunnerState,
    WorkflowStepResult,
    parse_story_list,
)
from heagent.goal.status_view import project_status_view


def _workflow() -> WorkflowResource:
    return WorkflowResource(
        name="example",
        instructions="",
        steps=[
            WorkflowStepResource(index=1, name="step-01-plan.md", instructions=""),
            WorkflowStepResource(index=2, name="step-02-build.md", instructions=""),
        ],
    )


def test_status_view_reports_progress_and_current_step() -> None:
    state = WorkflowRunnerState(active_step=1, status=WorkflowStatus.PENDING, completed_steps=[1])
    view = project_status_view(state, _workflow(), goal_id="demo")
    assert view.goal_id == "demo"
    assert view.workflow == "example"
    assert view.progress == "1/2"
    assert view.active_step_name == "step-02-build.md"
    assert view.recommended_commands == ["/goal next"]
    assert view.render()[0] == "[goal] declarative progress: 1/2 status=pending step=1"


def test_status_view_surfaces_failed_stories_and_resume_guidance() -> None:
    state = WorkflowRunnerState(
        active_step=1,
        status=WorkflowStatus.WAITING_USER,
        completed_steps=[1],
        story_statuses={"S-2": "failed", "S-1": "completed"},
        reason="test evidence is incomplete",
    )
    view = project_status_view(state, _workflow())
    assert view.recent_failures == ["S-2 (failed)"]
    assert view.reason == "test evidence is incomplete"
    lines = view.render()
    assert "[goal] recent failures: S-2 (failed)" in lines
    assert "[goal] reason: test evidence is incomplete" in lines
    assert "[goal] next: /goal resume <answer> | /goal status" in lines


def test_an_approval_gate_recommends_decisions_never_resume() -> None:
    """审批门挂起（Story 51-5）：status 只推荐显式决策，resume 不在其列（不能隐式批准）。"""
    state = WorkflowRunnerState(status=WorkflowStatus.WAITING_USER, awaiting_approval=True)
    view = project_status_view(state, _workflow())
    assert view.recommended_commands == [
        "/goal approve",
        "/goal reject <原因>",
        "/goal amend <补充>",
        "/goal decisions",
    ]
    assert "/goal resume" not in view.recommended_commands


def test_status_view_reports_blocked_recommendations() -> None:
    view = project_status_view(WorkflowRunnerState(status=WorkflowStatus.BLOCKED, reason="gate failed"), _workflow())
    assert view.recommended_commands == ["/goal resume <说明>", "/goal doctor"]
    assert "[goal] next: /goal resume <说明> | /goal doctor" in view.render()


def test_status_view_never_infers_open_decisions_from_the_reason() -> None:
    state = WorkflowRunnerState(status=WorkflowStatus.BLOCKED, reason="choose a storage backend")
    assert project_status_view(state, _workflow()).open_decisions == []
    injected = project_status_view(state, _workflow(), open_decisions=["choose a storage backend"])
    assert "[goal] open decisions: choose a storage backend" in injected.render()


def test_status_view_ignores_an_active_step_beyond_the_workflow() -> None:
    state = WorkflowRunnerState(active_step=9, status=WorkflowStatus.COMPLETED)
    view = project_status_view(state, _workflow())
    assert view.active_step_name == ""
    assert view.recommended_commands == ["/goal status"]


@pytest.mark.asyncio
async def test_cli_status_renders_the_shared_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``/goal status`` must render the projection, not re-derive its own fields."""
    captured: list[str] = []
    state = WorkflowRunnerState(active_step=1, status=WorkflowStatus.WAITING_USER, completed_steps=[1])

    async def _runner(_workflow: WorkflowResource, _goal_dir: Path) -> SimpleNamespace:
        return SimpleNamespace(state=state)

    monkeypatch.setattr(goal_cli, "_echo", lambda message, *, err=True: captured.append(message))
    monkeypatch.setattr(goal_cli, "_goal_declarative_active_dir", lambda: tmp_path / "demo")
    monkeypatch.setattr(goal_cli, "_goal_declarative_runner", _runner)

    await goal_cli._goal_declarative_status(_workflow())

    assert captured[0] == "[goal] declarative progress: 1/2 status=waiting_user step=1"
    assert "[goal] current step: step-02-build.md" in captured
    assert "[goal] next: /goal resume <answer> | /goal status" in captured


def _story_workflow() -> WorkflowResource:
    """Workflow whose second step runs the story loop declared in ``02-epics.md``."""
    return WorkflowResource(
        name="example",
        instructions="",
        steps=[
            WorkflowStepResource(index=1, name="step-01-plan.md", instructions=""),
            WorkflowStepResource(index=2, name="step-02-build.md", instructions="", story_loop="02-epics.md"),
        ],
    )


def test_status_view_renders_the_epic_recorded_in_the_runner_state() -> None:
    state = WorkflowRunnerState(active_step=1, active_story="S-3", active_stories=["S-3"], active_epic="E2")
    assert "[goal] current epic: E2" in project_status_view(state, _story_workflow()).render()

    idle = WorkflowRunnerState(active_step=1, active_story="S-3", active_stories=["S-3"])
    assert "[goal] current epic:" not in project_status_view(idle, _story_workflow()).render()


@pytest.mark.asyncio
async def test_story_loop_records_the_epic_and_a_checkpoint_restores_it(tmp_path: Path) -> None:
    """The Epic is a runner fact: recorded where the story is scheduled, restored on resume."""
    workflow = WorkflowResource(
        name="example",
        instructions="",
        steps=[WorkflowStepResource(index=1, name="step-01-build.md", instructions="", story_loop="02-epics.md")],
    )
    store = WorkflowCheckpointStore(str(tmp_path / "cp"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="demo", checkpoint_store=store)
    stories = parse_story_list("## E2 Search\n\n- [ ] S-1 index\n- [ ] S-2 rank\n")

    result = await runner.run_step(lambda step, story: WorkflowStepResult(output="ok"), stories=stories)

    assert result.status is WorkflowStatus.PENDING
    assert runner.state.active_story == "S-2"
    assert runner.state.active_epic == "E2"

    checkpoints = await store.list_checkpoints(goal_id="demo")
    restored = WorkflowRunner.from_checkpoint(workflow, checkpoints[-1])
    assert restored.state.active_epic == "E2", "a resume must not lose the Epic"


@pytest.mark.asyncio
async def test_cli_status_shows_the_epic_without_reading_any_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A status read is a projection of persisted state: no story document is opened."""
    goal_dir = tmp_path / "demo"
    goal_dir.mkdir()
    captured: list[str] = []
    state = WorkflowRunnerState(
        active_step=1,
        status=WorkflowStatus.PENDING,
        active_story="S-3",
        active_stories=["S-3"],
        active_epic="E2",
    )

    async def _runner(_workflow: WorkflowResource, _goal_dir: Path) -> SimpleNamespace:
        return SimpleNamespace(state=state)

    monkeypatch.setattr(goal_cli, "_echo", lambda message, *, err=True: captured.append(message))
    monkeypatch.setattr(goal_cli, "_goal_declarative_active_dir", lambda: goal_dir)
    monkeypatch.setattr(goal_cli, "_goal_declarative_runner", _runner)

    await goal_cli._goal_declarative_status(_story_workflow())

    assert "[goal] current epic: E2" in captured
    assert "[goal] current stories: S-3" in captured
    assert not (goal_dir / "02-epics.md").exists(), "the status render must not depend on a story document"


def test_only_the_status_view_produces_the_progress_line() -> None:
    """Every entry point renders ``GoalStatusView``; none re-derives the progress line.

    This is the mechanical form of "CLI, GUI and cron consume the same status model":
    a second renderer has to import the projection instead of rebuilding the line, and
    this assertion is what makes that visible in a diff.
    """
    source_root = Path(__file__).resolve().parents[1] / "src" / "heagent"
    hits = sorted(
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.py")
        if "declarative progress:" in path.read_text(encoding="utf-8")
    )
    assert hits == ["goal/status_view.py"], f"the goal progress line must come from GoalStatusView.render(): {hits}"


def test_gui_and_interactive_cli_use_the_shared_goal_entry_point() -> None:
    """Both entry points must go through ``cli.goal._goal_runner`` (and its ``_echo`` funnel)."""
    source_root = Path(__file__).resolve().parents[1] / "src" / "heagent"
    for relative in ("gui/screens/chat.py", "cli/interactive.py"):
        source = (source_root / relative).read_text(encoding="utf-8")
        assert "heagent.cli.goal import _goal_runner" in source, (
            f"{relative} must dispatch /goal through the shared goal runner"
        )


@pytest.mark.asyncio
async def test_cron_goal_job_drives_the_shared_advance_use_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The scheduler must not fork its own advance logic: cron runs ``/goal next``'s use case."""
    calls: list[str] = []

    async def _advance(_provider: object, _engine: object, _workflow: WorkflowResource) -> str:
        calls.append("advance")
        return goal_cli._GOAL_ADVANCED

    monkeypatch.setattr(goal_cli, "_goal_declarative_advance", _advance)
    # Story 51-6：cron 与手动命令同一解析口径——推进 goal 冻结绑定的 workflow。
    monkeypatch.setattr(goal_cli, "resolve_bound_workflow", lambda _goal_dir, _default: _workflow())
    monkeypatch.setattr(goal_cli, "_goal_active_md", lambda: tmp_path / "demo" / "brief.md")

    await goal_cli._goal_cron_advance(provider=None, engine=None, store=None, goal_id="demo")

    assert calls == ["advance"]
