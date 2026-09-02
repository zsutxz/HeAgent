"""Declarative /goal routing and checkpoint recovery contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from heagent.cli import _goal_cron_advance, _goal_runner
from heagent.cron.jobs import JobStore
from heagent.engine import GoalArtifact, parse_artifact
from heagent.engine.workflow import WorkflowCheckpointStore


@pytest.fixture()
def declarative_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    workflow_root = tmp_path / ".heagent" / "workflows"
    workflow_root.mkdir(parents=True)
    (workflow_root / "workflow.md").write_text(
        "---\nname: test-development\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\nworkflow instructions\n\n"
        "## Step 01: plan\noutput: plan\ncheckpoint: true\n\nplan the story\n\n"
        "## Step 02: build\ninput: plan\noutput: implementation\ncheckpoint: true\n\nbuild the story\n",
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
    await _goal_runner(SimpleNamespace(), None, "new ship the workflow")
    goal_id = (declarative_cwd / ".heagent" / "goals" / "current").read_text(encoding="utf-8")
    goal_dir = declarative_cwd / ".heagent" / "goals" / goal_id
    goal_document = goal_dir / "GOAL.md"
    assert goal_document.exists()
    assert not (goal_dir / "goal.txt").exists()
    assert isinstance(parse_artifact(goal_document), GoalArtifact)
    assert len(successful_step) == 1
    checkpoints = await WorkflowCheckpointStore(str(goal_dir / "checkpoints")).list_checkpoints(goal_id=goal_id)
    assert len(checkpoints) == 1
    assert checkpoints[0].completed_steps == [0]
    assert checkpoints[0].active_skill == "test-development"

    await _goal_runner(SimpleNamespace(), None, "status")
    assert "declarative progress: 1/2" in capsys.readouterr().err

    await _goal_runner(SimpleNamespace(), None, "pause")
    await _goal_runner(SimpleNamespace(), None, "resume")
    await _goal_runner(SimpleNamespace(), None, "next")
    assert len(successful_step) == 2
    persisted = await WorkflowCheckpointStore(str(goal_dir / "checkpoints")).list_checkpoints(goal_id=goal_id)
    assert len({checkpoint.checkpoint_id for checkpoint in persisted}) == len(persisted)

    await _goal_runner(SimpleNamespace(), None, "run")
    assert len(successful_step) == 2

    await _goal_runner(SimpleNamespace(), None, "audit")
    assert "audit unavailable without engine" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_declarative_auto_uses_same_completed_checkpoint(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new scheduled workflow")
    await _goal_runner(SimpleNamespace(), None, "pause")
    await _goal_runner(SimpleNamespace(), None, "resume")
    await _goal_runner(SimpleNamespace(), None, "next")
    goal_id = (declarative_cwd / ".heagent" / "goals" / "current").read_text(encoding="utf-8")
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
