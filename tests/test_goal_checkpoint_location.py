from pathlib import Path

import pytest

from heagent.goal.application import checkpoint_store, external_checkpoint_dir, initialize_checkpoint_workspace


def test_existing_goal_keeps_local_checkpoints(tmp_path: Path) -> None:
    goal = tmp_path / "legacy"
    assert checkpoint_store(goal)._base == goal / "checkpoints"


def test_existing_goal_cannot_be_rebound(tmp_path: Path) -> None:
    (tmp_path / "checkpoints").mkdir()
    with pytest.raises(ValueError, match="existing goal"):
        initialize_checkpoint_workspace(tmp_path, tmp_path)
    assert not (tmp_path / "checkpoint-workspace.txt").exists()


def test_new_goal_checkpoint_workspace_survives_cwd_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    goal = tmp_path / "_he-output" / "new-goal"
    initialize_checkpoint_workspace(goal, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert checkpoint_store(goal)._base == tmp_path / ".heagent" / "checkpoints" / "new-goal"


def test_corrupt_workspace_marker_fails_loudly(tmp_path: Path) -> None:
    goal = tmp_path / "goal"
    initialize_checkpoint_workspace(goal, tmp_path)
    (goal / "checkpoint-workspace.txt").write_text("relative-path", encoding="utf-8")
    with pytest.raises(ValueError, match="absolute"):
        checkpoint_store(goal)


def test_external_checkpoint_reserves_reused_goal_name(tmp_path: Path) -> None:
    path = external_checkpoint_dir("same-name", tmp_path)
    path.mkdir(parents=True)
    assert path == tmp_path / ".heagent" / "checkpoints" / "same-name"
