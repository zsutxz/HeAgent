"""Goal 写集审计测试的共享基建（评审 P22：三份拷贝收敛为一份）。

_git/_commit_all/_tracked 是最小 git 夹具操作；StubGitEngine 是带事件总线的最小
engine 替身（workspace_root=None → cwd 为验证工作区）。test_git_tools.py 的 inline
惯例保持独立（它是 git 端口专属判据文件，不共享此模块）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace


def git(*args: str, cwd: Path) -> None:
    """一条受控字面量 git 命令（测试夹具专用）。"""

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603


def commit_all(cwd: Path, message: str) -> None:
    git("add", "-A", cwd=cwd)
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-m", message, cwd=cwd)


def tracked(path: Path, rel: str, content: str) -> None:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class StubGitEngine:
    """带事件总线的最小 engine 替身（workspace_root=None → cwd 为验证工作区）。"""

    def __init__(self) -> None:
        self.workspace_root = None
        self.published: list[tuple[str, dict]] = []

        class _Bus:
            def publish(self, kind: str, details: dict | None = None) -> None:
                self.owner.published.append((kind, details or {}))

        self.events = _Bus()
        self.events.owner = self


def make_story_stub(story_id: str) -> SimpleNamespace:
    """最小鸭子 story（goal_step_artifact_path 只消费 id）。"""
    return SimpleNamespace(id=story_id)
