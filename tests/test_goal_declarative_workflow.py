"""Declarative /goal routing and checkpoint recovery contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from heagent.cli import _goal_cron_advance, _goal_runner
from heagent.cron.jobs import JobStore
from heagent.engine.workflow import WorkflowCheckpointStore


@pytest.fixture()
def declarative_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    workflow_root = tmp_path / ".heagent" / "workflows" / "bmad-development"
    workflow_root.mkdir(parents=True)
    (workflow_root / "workflow.md").write_text(
        "---\nname: test-development\nsteps: [step-01-plan.md, step-02-build.md]\n---\n\nworkflow instructions\n",
        encoding="utf-8",
    )
    (workflow_root / "step-01-plan.md").write_text(
        "---\noutput: plan\nnext: step-02-build.md\n---\n\nplan the story\n",
        encoding="utf-8",
    )
    (workflow_root / "step-02-build.md").write_text(
        "---\noutput: implementation\ncheckpoint: true\n---\n\nbuild the story\n",
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
    assert not (goal_dir / "GOAL.md").exists()
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
async def test_legacy_goal_path_remains_active_without_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    skill = tmp_path / ".heagent" / "skills" / "goal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("legacy skill", encoding="utf-8")

    async def legacy_session(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        goal_md = next((tmp_path / ".heagent" / "goals").glob("*/goal.txt")).parent / "GOAL.md"
        goal_md.write_text("status: executing\n\n- [ ] S1: legacy\n", encoding="utf-8")
        return SimpleNamespace(success=True, output="planned")

    monkeypatch.setattr("heagent.cli._goal_session", legacy_session)
    await _goal_runner(SimpleNamespace(), None, "legacy goal")
    assert list((tmp_path / ".heagent" / "goals").glob("*/GOAL.md"))
