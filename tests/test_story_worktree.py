"""A41 / AD-20 判据：Story worktree 的创建、隔离性与清理。

用真实的临时 git 仓库（不替身）：worktree 的行为就是 git 的行为，替身会让「真的隔离了吗」
退化成「函数被调用了吗」。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from heagent.goal.worktree import (
    WorktreeError,
    create_worktree,
    head_commit,
    list_worktrees,
    promote_goal_products,
    promote_story_commit,
    remove_worktree,
    story_ref,
    worktree_path,
    worktree_root,
)


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


async def test_story_commit_is_cherry_picked_back_and_ref_is_removed(repo: Path) -> None:
    """A41 合并策略（用户裁定 cherry-pick）：worktree 内的提交搬回主工作区，临时引用随即删除。"""
    base = await head_commit(repo)
    path = await create_worktree(repo, "goal-1", "s1")

    (path / "story.txt").write_text("from s1\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "feat: s1")
    story_sha = await head_commit(path)
    assert story_sha != base

    promoted = await promote_story_commit(repo, "goal-1-s1", commit=story_sha)

    assert promoted != base, "主工作区必须前移到新提交"
    assert await head_commit(repo) == promoted
    assert (repo / "story.txt").read_text(encoding="utf-8") == "from s1\n"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() != "HEAD"
    # 临时引用已删除
    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heagent/")
    assert story_ref("goal-1-s1") not in refs


async def test_conflicting_story_commit_aborts_and_fails_loudly(repo: Path) -> None:
    """冲突时：``cherry-pick --abort`` 恢复干净工作区，再显性抛错（不留半合并状态）。"""
    path = await create_worktree(repo, "goal-1", "s1")
    (path / "README.md").write_text("s1 version\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "feat: s1 edits README")
    story_sha = await head_commit(path)

    # 主工作区同时改了同一行 ⇒ pick 必冲突
    (repo / "README.md").write_text("main version\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "main edits README")

    with pytest.raises(WorktreeError):
        await promote_story_commit(repo, "goal-1-s1", commit=story_sha)

    assert (repo / "README.md").read_text(encoding="utf-8") == "main version\n"
    assert not (repo / ".git" / "CHERRY_PICK_HEAD").exists(), "必须已 abort，工作区干净"
    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heagent/")
    assert story_ref("goal-1-s1") not in refs, "失败也必须清掉临时引用"


async def test_concurrent_promotions_do_not_fight_over_the_git_index(repo: Path) -> None:
    """并行批里多个 story 同时收尾：promote 串行化，两个 cherry-pick 都成功（不抢 index.lock）。"""
    import asyncio

    first = await create_worktree(repo, "goal-1", "s1")
    second = await create_worktree(repo, "goal-1", "s2")
    for path, name in ((first, "one.txt"), (second, "two.txt")):
        (path / name).write_text(name, encoding="utf-8")
        _git(path, "add", ".")
        _git(path, "commit", "-q", "-m", f"feat: {name}")

    results = await asyncio.gather(
        promote_story_commit(repo, "goal-1-s1", commit=await head_commit(first)),
        promote_story_commit(repo, "goal-1-s2", commit=await head_commit(second)),
        return_exceptions=True,
    )

    assert [type(item).__name__ for item in results] == ["str", "str"], results
    assert (repo / "one.txt").is_file() and (repo / "two.txt").is_file(), "两个 story 的产出都必须在主工作区"


# ── 产物回写（A41 残余切片）：`_he-output/` 是 gitignore 面，cherry-pick 带不回来 ─────────────────


GOAL_REL = Path("_he-output") / "goals" / "g1"


async def test_goal_products_written_in_the_worktree_are_moved_back(repo: Path) -> None:
    """worktree 里写出的 `_he-output` 产物必须搬回主工作区，否则随目录移除一起消失。"""
    worktree = await create_worktree(repo, "g1", "s1")
    product = worktree / GOAL_REL / "step-01-step" / "epic-e1" / "s-1" / "story.md"
    product.parent.mkdir(parents=True)
    product.write_text("story 报告\n", encoding="utf-8")

    copied = await promote_goal_products(repo, worktree, GOAL_REL)

    assert copied == ["_he-output/goals/g1/step-01-step/epic-e1/s-1/story.md"]
    target = repo / GOAL_REL / "step-01-step" / "epic-e1" / "s-1" / "story.md"
    assert target.read_text(encoding="utf-8") == "story 报告\n"


async def test_ignored_products_are_moved_back_like_the_real_repository(repo: Path) -> None:
    """本仓 `_he-output/` 被 gitignore：忽略态（`!!`）同样要搬回，别只认 untracked。"""
    (repo / ".gitignore").write_text("_he-output/goals/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore goal products")
    worktree = await create_worktree(repo, "g1", "s1")
    product = worktree / GOAL_REL / "brief.md"
    product.parent.mkdir(parents=True)
    product.write_text("需求\n", encoding="utf-8")

    copied = await promote_goal_products(repo, worktree, GOAL_REL)

    assert copied == ["_he-output/goals/g1/brief.md"]
    assert (repo / GOAL_REL / "brief.md").read_text(encoding="utf-8") == "需求\n"


async def test_untouched_tracked_products_never_clobber_the_main_workspace(repo: Path) -> None:
    """`_he-output` 被 tracked 时，worktree 里未改动的旧版本不得覆盖主工作区的新版本。"""
    tracked = repo / GOAL_REL / "epics.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("v1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "track epics")
    worktree = await create_worktree(repo, "g1", "s1")  # 基线 = v1

    tracked.write_text("main v2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "main updates epics")

    assert await promote_goal_products(repo, worktree, GOAL_REL) == []
    assert tracked.read_text(encoding="utf-8") == "main v2\n", "worktree 里的旧版本不得覆盖主工作区"


async def test_a_story_without_products_is_a_no_op(repo: Path) -> None:
    worktree = await create_worktree(repo, "g1", "s1")

    assert await promote_goal_products(repo, worktree, GOAL_REL) == []
    assert not (repo / GOAL_REL).exists(), "源目录不存在时不得凭空建出目标目录"


async def test_goal_dir_outside_the_repository_fails_loudly(repo: Path, tmp_path: Path) -> None:
    worktree = await create_worktree(repo, "g1", "s1")
    with pytest.raises(WorktreeError, match="outside the repository"):
        await promote_goal_products(repo, worktree, tmp_path / "elsewhere" / "g1")
