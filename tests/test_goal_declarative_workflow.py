"""Declarative /goal routing and checkpoint recovery contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import heagent.cli as cli
from heagent.cli import (
    _goal_cron_advance,
    _goal_declarative_runner,
    _goal_declarative_workflow,
    _goal_project_id,
    _goal_runner,
)
from heagent.cron.jobs import JobStore
from heagent.config import reset_settings
from heagent.engine import GoalArtifact, parse_artifact
from heagent.engine.workflow import WorkflowCheckpointStore, WorkflowStatus


@pytest.fixture()
def declarative_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    workflow_root = tmp_path / ".heagent" / "workflows"
    workflow_root.mkdir(parents=True)
    (workflow_root / "workflow.md").write_text(
        "---\nname: test-development\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\nworkflow instructions\n\n"
        "## Step 01: plan\ninput: user intent, existing project context\n"
        "output: requirements brief, story breakdown\ncheckpoint: true\n\nplan the story\n\n"
        "## Step 02: build\ninput: requirements brief\noutput: implementation\ncheckpoint: true\n\nbuild the story\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def successful_step(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(prompt)
        return SimpleNamespace(success=True, output=f"output-{len(calls)}")

    monkeypatch.setattr("heagent.cli._goal_session", run_step)
    return calls


@pytest.mark.asyncio
async def test_declarative_commands_checkpoint_and_no_duplicate_completion(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new ship   the workflow")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    goal_document = goal_dir / "GOAL.md"
    assert goal_document.exists()
    goal_text = goal_document.read_text(encoding="utf-8")
    assert "## 原始需求（Original Request）" in goal_text
    assert "ship   the workflow" in goal_text
    assert not (goal_dir / "ORIGINAL_REQUEST.md").exists()
    assert not (goal_dir / "goal.txt").exists()
    assert (goal_dir / "step-01-plan.md").read_text(encoding="utf-8") == "output-1"
    assert isinstance(parse_artifact(goal_document), GoalArtifact)
    assert len(successful_step) == 1
    assert "## user intent\nship   the workflow" in successful_step[0]
    assert "## existing project context" in successful_step[0]
    assert f"Project output root: {declarative_cwd / '_he-output'}" in successful_step[0]
    checkpoints = await WorkflowCheckpointStore(str(goal_dir / "checkpoints")).list_checkpoints(goal_id=goal_id)
    assert len(checkpoints) == 1
    assert checkpoints[0].completed_steps == [0]
    assert checkpoints[0].active_skill == "test-development"

    await _goal_runner(SimpleNamespace(), None, "status")
    assert "declarative progress: 1/2" in capsys.readouterr().err

    await _goal_runner(SimpleNamespace(), None, "resume confirmed: use the requested scope")
    assert len(successful_step) == 2
    assert "## requirements brief\noutput-1" in successful_step[1]
    assert "## user responses" in successful_step[1]
    assert "confirmed: use the requested scope" in successful_step[1]
    persisted_goal = goal_document.read_text(encoding="utf-8")
    assert "## 用户补充（User Responses）" in persisted_goal
    assert "confirmed: use the requested scope" in persisted_goal
    persisted = await WorkflowCheckpointStore(str(goal_dir / "checkpoints")).list_checkpoints(goal_id=goal_id)
    assert len({checkpoint.checkpoint_id for checkpoint in persisted}) == len(persisted)

    await _goal_runner(SimpleNamespace(), None, "run")
    assert len(successful_step) == 2

    await _goal_runner(SimpleNamespace(), None, "audit")
    assert "audit unavailable without engine" in capsys.readouterr().err


def test_goal_project_id_uses_english_letters_without_numeric_suffix() -> None:
    assert _goal_project_id("继续开发 MCP 安全功能 2026") == "continue-development-mcp-security-feature"
    assert _goal_project_id("Build MCP security 2026") == "build-mcp-security"


@pytest.mark.asyncio
async def test_declarative_resume_advances_once_under_goal_lock(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new locked resume workflow")
    observed: list[bool] = []
    original = cli._goal_declarative_advance

    async def observe_advance(provider, engine, workflow):
        observed.append(cli._goal_auto_lock.locked())
        return await original(provider, engine, workflow)

    monkeypatch.setattr(cli, "_goal_declarative_advance", observe_advance)
    await _goal_runner(SimpleNamespace(), None, "resume")

    assert len(successful_step) == 2
    assert observed == [True]


@pytest.mark.asyncio
async def test_declarative_auto_uses_same_completed_checkpoint(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new scheduled workflow")
    await _goal_runner(SimpleNamespace(), None, "pause")
    await _goal_runner(SimpleNamespace(), None, "resume")
    await _goal_runner(SimpleNamespace(), None, "next")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    store = JobStore(str(declarative_cwd / "jobs.json"))
    await _goal_runner(SimpleNamespace(), None, "auto", cron_store=store)

    await _goal_cron_advance(SimpleNamespace(), None, store, goal_id)
    assert len(successful_step) == 2
    assert store.list_jobs() == []


@pytest.mark.asyncio
async def test_declarative_goal_rejects_unknown_workflow_declarations(
    declarative_cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        "---\nname: invalid\nentrypoint: unsupported\n---\n\n## Step 01: plan\noutput: plan\n\nPlan the work.\n",
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new rejected")

    assert "unsupported goal workflow entrypoint" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_goal_requires_workflow_instead_of_falling_back_to_legacy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    await _goal_runner(SimpleNamespace(), None, "legacy goal")
    assert "workflow.md is required" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_declarative_resume_retries_a_blocked_step(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new blocked workflow")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    workflow = _goal_declarative_workflow()
    assert workflow is not None
    runner = await _goal_declarative_runner(workflow, goal_dir)
    runner.state = runner.state.model_copy(update={"status": WorkflowStatus.BLOCKED, "reason": "missing evidence"})
    await runner.persist_state()

    await _goal_runner(SimpleNamespace(), None, "resume")

    resumed = await _goal_declarative_runner(workflow, goal_dir)
    assert resumed.state.status is WorkflowStatus.COMPLETED
    assert resumed.state.completed_steps == [0, 1]


@pytest.mark.asyncio
async def test_declarative_next_rejects_waiting_checkpoint(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new checkpoint workflow")
    await _goal_runner(SimpleNamespace(), None, "next")
    assert len(successful_step) == 1
    assert "use /goal resume first" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_final_checkpoint_persists_completed_state(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        "---\nname: final-checkpoint\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\nworkflow instructions\n\n"
        "## Step 01: finish\ninput: user intent, existing project context\n"
        "output: implementation\ncheckpoint: true\n\nfinish the story\n",
        encoding="utf-8",
    )
    await _goal_runner(SimpleNamespace(), None, "new final workflow")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    runner = await _goal_declarative_runner(_goal_declarative_workflow(), goal_dir)  # type: ignore[arg-type]
    assert runner.done
    assert runner.state.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_checkpoint_auto_mode_advances_until_completion(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\ncheckpoint_mode: auto\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new auto workflow")

    assert len(successful_step) == 2
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    runner = await _goal_declarative_runner(  # type: ignore[arg-type]
        _goal_declarative_workflow(), declarative_cwd / "_he-output" / "goals" / goal_id
    )
    assert runner.done


@pytest.mark.asyncio
async def test_checkpoint_mode_env_applies_when_workflow_omits_declaration(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOAL_CHECKPOINT_MODE", "auto")
    reset_settings()

    await _goal_runner(SimpleNamespace(), None, "new env auto workflow")

    assert len(successful_step) == 2


@pytest.mark.asyncio
async def test_workflow_checkpoint_mode_overrides_environment(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOAL_CHECKPOINT_MODE", "auto")
    reset_settings()
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\ncheckpoint_mode: prompt\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new explicit prompt workflow")

    assert len(successful_step) == 1


@pytest.mark.asyncio
async def test_checkpoint_prompt_accepts_and_advances(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    confirmations: list[bool] = []

    def confirm(_message: str, *, default: bool = False) -> bool:
        confirmations.append(default)
        return True

    monkeypatch.setattr(cli.click, "confirm", confirm)

    await _goal_runner(SimpleNamespace(), None, "new prompt workflow")

    assert len(successful_step) == 2
    assert confirmations == [False]


@pytest.mark.asyncio
async def test_checkpoint_prompt_rejection_keeps_waiting_user(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli.click, "confirm", lambda _message, default=False: False)

    await _goal_runner(SimpleNamespace(), None, "new paused workflow")

    assert len(successful_step) == 1
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    runner = await _goal_declarative_runner(
        _goal_declarative_workflow(), declarative_cwd / "_he-output" / "goals" / goal_id
    )  # type: ignore[arg-type]
    assert runner.state.status is WorkflowStatus.WAITING_USER


@pytest.mark.asyncio
async def test_invalid_checkpoint_mode_fails_workflow_load(
    declarative_cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\ncheckpoint_mode: always\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new invalid mode")

    assert "invalid checkpoint_mode 'always'" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_empty_subagent_output_fails_without_persisting_empty_artifact(
    declarative_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty_goal_session(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        del provider, engine, prompt, kwargs
        return SimpleNamespace(success=True, output="  \n")

    monkeypatch.setattr(cli, "_goal_session", empty_goal_session)

    await _goal_runner(SimpleNamespace(), None, "new empty output workflow")

    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    runner = await _goal_declarative_runner(
        _goal_declarative_workflow(), goal_dir
    )  # type: ignore[arg-type]
    assert runner.state.status is WorkflowStatus.FAILED
    assert "produced empty output" in runner.state.reason
    assert not (goal_dir / "step-01-plan.md").exists()
