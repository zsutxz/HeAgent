"""A41 / AD-20 判据：Story worktree 的创建、隔离性与清理。

用真实的临时 git 仓库（不替身）：worktree 的行为就是 git 的行为，替身会让「真的隔离了吗」
退化成「函数被调用了吗」。
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from heagent.goal.worktree import (
    WorktreeError,
    create_worktree,
    list_worktrees,
    remove_worktree,
    worktree_path,
    worktree_root,
)

if TYPE_CHECKING:
    from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - 固定调用本地 git，参数来自本文件
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    return root


def test_path_is_predictable_under_state_dir(repo: Path) -> None:
    path = worktree_path(repo, "goal-1", "62.1")
    assert path == repo.resolve() / ".heagent" / "worktrees" / "goal-1" / "62.1"
    assert worktree_root(repo) == repo.resolve() / ".heagent" / "worktrees"


@pytest.mark.parametrize("segment", ["", "  ", "..", "a/b", "a\\b"])
def test_invalid_segments_are_rejected(repo: Path, segment: str) -> None:
    with pytest.raises(WorktreeError):
        worktree_path(repo, "goal-1", segment)


async def test_two_stories_get_isolated_worktrees(repo: Path) -> None:
    first = await create_worktree(repo, "goal-1", "s1")
    second = await create_worktree(repo, "goal-1", "s2")

    assert first.is_dir() and second.is_dir()
    assert first != second
    # 隔离性：一个 worktree 里的新文件不出现在另一个里，也不出现在主工作区。
    (first / "only-in-s1.txt").write_text("x", encoding="utf-8")
    assert not (second / "only-in-s1.txt").exists()
    assert not (repo / "only-in-s1.txt").exists()
    # detached：不占用分支名
    assert _git(first, "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD"


async def test_recreate_replaces_a_stale_checkout(repo: Path) -> None:
    first = await create_worktree(repo, "goal-1", "s1")
    (first / "dirty.txt").write_text("leftover", encoding="utf-8")

    again = await create_worktree(repo, "goal-1", "s1")

    assert again == first
    assert not (first / "dirty.txt").exists(), "残留的旧检出必须先移除再重建"


async def test_remove_cleans_both_directory_and_registration(repo: Path) -> None:
    path = await create_worktree(repo, "goal-1", "s1")
    assert str(path) in await list_worktrees(repo)

    await remove_worktree(repo, path)

    assert not path.exists()
    assert str(path) not in await list_worktrees(repo)


async def test_create_outside_a_repository_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(WorktreeError):
        await create_worktree(tmp_path, "goal-1", "s1")
