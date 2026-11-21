"""并行 Story 的物理隔离层（AD-20 / A41 裁定「物理隔离」）：git worktree 生命周期。

三条契约：

- **路径可预测**：``<repo>/.heagent/worktrees/<goal_id>/<story_id>``——残留物集中在同一处，
  ``git worktree prune`` 一网打尽；
- **detached HEAD**：不占分支名（同一 base 可并发派生多个 worktree，也不会因分支被占用而失败）；
- **失败显性**：创建失败抛 :class:`WorktreeError`，**不**静默回落到共享工作区——回落等于偷偷
  取消隔离，而调用方仍以为自己被隔离（静默降级比失败更危险）。

移除失败只记 WARNING：worktree 残留是可回收的磁盘占用，不是数据损坏。

本模块只做**生命周期**，不决定「哪个故事在哪个 worktree 跑」——那是执行器（cli/goal）的接线，
依赖 `SubAgent` 的 per-run 工作区根（``context_dir``）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

#: worktree 根目录名（相对仓库根）：与运行态目录同处 ``.heagent/``，便于统一清理。
WORKTREE_DIRNAME = ".heagent/worktrees"

#: ``git worktree`` 子命令超时（秒）：创建要检出整棵树，给比普通查询更宽的预算。
_GIT_TIMEOUT_SECONDS = 120.0

#: promote（cherry-pick 到主工作区）的**进程内**串行门：并行批里多个 story 同时结束时，
#: 两个 ``git cherry-pick`` 会抢 ``.git/index.lock`` 而互相失败。跨进程不必再加锁——goal 域
#: 本就有 ``.heagent/goal.lock`` 保证同一时刻只有一个推进者（``goal/mutex.py``）。
_MERGE_LOCK = asyncio.Lock()


class WorktreeError(RuntimeError):
    """worktree 创建 / 移除失败（携带 git 的原始 stderr 首行）。"""


def worktree_root(repo_root: str | Path) -> Path:
    """worktree 根目录（``<repo>/.heagent/worktrees``）。"""
    return Path(repo_root).resolve() / WORKTREE_DIRNAME


def worktree_path(repo_root: str | Path, goal_id: str, story_id: str) -> Path:
    """单个故事 worktree 的确定性路径（不做任何 I/O、不校验存在性）。"""
    return worktree_root(repo_root) / _safe_segment(goal_id) / _safe_segment(story_id)


def _safe_segment(value: str) -> str:
    """把 goal / story 标识收敛成单层目录名（拒绝空串、分隔符与 ``..``）。"""
    text = value.strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise WorktreeError(f"invalid worktree path segment: {value!r}")
    return text


async def create_worktree(
    repo_root: str | Path,
    goal_id: str,
    story_id: str,
    *,
    base_rev: str = "HEAD",
) -> Path:
    """为 ``story_id`` 建一个 detached worktree 并返回路径；失败抛 :class:`WorktreeError`。

    已存在（重复调用 / 上一轮残留）时先移除再重建——残留的旧检出比直接复用更危险（它可能
    带着上一轮的工作树改动）。
    """
    target = worktree_path(repo_root, goal_id, story_id)
    if target.exists():
        await remove_worktree(repo_root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    await _git(repo_root, "worktree", "add", "--detach", str(target), base_rev)
    return target


async def remove_worktree(repo_root: str | Path, target: str | Path) -> None:
    """移除一个 worktree（``--force``：工作树可能有未提交改动）；失败只 WARNING。"""
    try:
        await _git(repo_root, "worktree", "remove", "--force", str(target))
    except WorktreeError as exc:
        logger.warning("worktree remove failed for %s: %s", target, exc)
        return
    # ``git worktree remove`` 之后目录通常已空，顺手清掉可能残留的空父目录（失败无意义）。
    with contextlib.suppress(OSError):
        Path(target).rmdir()


async def head_commit(worktree: str | Path, *, rev: str = "HEAD") -> str:
    """worktree（或任意仓库路径）的提交 SHA。"""
    return (await _git(worktree, "rev-parse", rev)).strip()


def story_ref(story_id: str) -> str:
    """临时引用名：``refs/heagent/stories/<story>``（防止 detached 提交被 gc 回收）。"""
    return f"refs/heagent/stories/{story_id}"


async def promote_story_commit(repo_root: str | Path, story_id: str, *, commit: str) -> str:
    """把一个 story 提交**搬回主工作区分支**（cherry-pick），返回新提交 SHA。

    流程与失败语义：

    1. 先建临时引用 ``refs/heagent/stories/<story>`` 指向该提交——detached HEAD 的提交一旦失去
       引用，``git gc`` 可能把它回收；pick 成功后再删引用。
    2. ``git cherry-pick`` 到主工作区当前分支；冲突时 ``cherry-pick --abort`` 恢复干净工作区，
       再抛 :class:`WorktreeError`（**不**留下半合并状态）。
    """
    ref = story_ref(story_id)
    async with _MERGE_LOCK:
        await _git(repo_root, "update-ref", ref, commit)
        try:
            await _git(repo_root, "cherry-pick", commit)
        except WorktreeError:
            with contextlib.suppress(WorktreeError):
                await _git(repo_root, "cherry-pick", "--abort")
            raise
        finally:
            with contextlib.suppress(WorktreeError):
                await _git(repo_root, "update-ref", "-d", ref)
        return await head_commit(repo_root)


async def list_worktrees(repo_root: str | Path) -> list[str]:
    """``git worktree list --porcelain`` 里的全部路径（诊断 / 残留清点用）。"""
    output = await _git(repo_root, "worktree", "list", "--porcelain")
    return [line.removeprefix("worktree ").strip() for line in output.splitlines() if line.startswith("worktree ")]


async def _git(repo_root: str | Path, *args: str) -> str:
    """跑一条写形态的 git 子命令，返回 stdout；非零退出抛 :class:`WorktreeError`。"""
    command = ["git", "-C", str(repo_root), *args]

    def _invoke() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  # nosec B603 - 固定模板，参数不含外部输入
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )

    try:
        result = await asyncio.to_thread(_invoke)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorktreeError(f"git {' '.join(args)} failed to run: {exc}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise WorktreeError(f"git {' '.join(args)} failed ({result.returncode}): {detail[0] if detail else ''}")
    return result.stdout


__all__ = [
    "WORKTREE_DIRNAME",
    "WorktreeError",
    "create_worktree",
    "head_commit",
    "list_worktrees",
    "promote_story_commit",
    "remove_worktree",
    "story_ref",
    "worktree_path",
    "worktree_root",
]
