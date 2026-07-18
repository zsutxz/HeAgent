"""Git 内置工具测试 — 在真实 git 仓库中验证 git_status/diff/log/blame。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from heagent.tools.path_safety import reset_workspace_root, set_workspace_root

if TYPE_CHECKING:
    from pathlib import Path


def _init_git_repo(tmp_path: Path) -> Path:
    """在临时目录初始化 git 仓库并写入测试文件，返回仓库根路径。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Test Repo\n\nHello world.\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "src" / "utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@heagent.local"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "HeAgent Test"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo, check=True, capture_output=True,
    )
    # 第二次提交以产生历史
    (repo / "README.md").write_text("# Test Repo\n\nHello world.\n\nMore content.\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "update readme"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


# ── helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """提供临时 git 仓库路径，并设置 workspace root。"""
    repo = _init_git_repo(tmp_path)
    set_workspace_root(repo)
    yield repo
    reset_workspace_root()


@pytest.fixture()
def dirty_repo(git_repo: Path) -> Path:
    """在干净仓库基础上制造未暂存变更。"""
    (git_repo / "src" / "main.py").write_text("print('hello world')\n", encoding="utf-8")
    (git_repo / "new_file.txt").write_text("untracked\n", encoding="utf-8")
    return git_repo


# ── git_status ───────────────────────────────────────────────────────────────


class TestGitStatus:
    @pytest.mark.asyncio
    async def test_clean_repo(self, git_repo: Path) -> None:
        """干净仓库返回 '(clean)'。"""
        from heagent.tools.builtins.git import git_status

        result = await git_status()
        assert result == "(clean)"

    @pytest.mark.asyncio
    async def test_dirty_repo(self, dirty_repo: Path) -> None:
        """有变更时返回 --porcelain 输出。"""
        from heagent.tools.builtins.git import git_status

        result = await git_status()
        # git status --porcelain 格式: XY path（X=staging, Y=worktree）
        # Windows/git 版本差异：可能是 " M" 或 "M " 或 "M" 前缀
        assert "src/main.py" in result or "src\\main.py" in result
        assert "new_file.txt" in result

    @pytest.mark.asyncio
    async def test_filter_by_path(self, dirty_repo: Path) -> None:
        """path 参数过滤输出。"""
        from heagent.tools.builtins.git import git_status

        result = await git_status(path="src/main.py")
        assert "main.py" in result
        assert "new_file.txt" not in result

    @pytest.mark.asyncio
    async def test_filter_nonexistent_path(self, git_repo: Path) -> None:
        """不存在的路径返回空结果。"""
        from heagent.tools.builtins.git import git_status

        (git_repo / "sub").mkdir()
        result = await git_status(path="sub")
        assert result == "(clean)"


# ── git_diff ─────────────────────────────────────────────────────────────────


class TestGitDiff:
    @pytest.mark.asyncio
    async def test_clean_repo_no_diff(self, git_repo: Path) -> None:
        """干净仓库无差异。"""
        from heagent.tools.builtins.git import git_diff

        result = await git_diff()
        assert result == "(no changes)"

    @pytest.mark.asyncio
    async def test_unstaged_diff(self, dirty_repo: Path) -> None:
        """未暂存变更在 diff 中出现。"""
        from heagent.tools.builtins.git import git_diff

        result = await git_diff()
        assert "hello world" in result
        assert "print('hello')" in result  # 原行

    @pytest.mark.asyncio
    async def test_staged_diff_empty_when_no_staged(self, dirty_repo: Path) -> None:
        """staged=True 但无暂存文件时返回空。"""
        from heagent.tools.builtins.git import git_diff

        result = await git_diff(staged=True)
        assert result == "(no changes)"

    @pytest.mark.asyncio
    async def test_staged_diff_shows_staged(self, dirty_repo: Path) -> None:
        """暂存后 staged=True 显示差异。"""
        import subprocess

        from heagent.tools.builtins.git import git_diff

        subprocess.run(["git", "add", "src/main.py"], cwd=dirty_repo, check=True, capture_output=True)
        result = await git_diff(staged=True)
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_filter_by_path(self, dirty_repo: Path) -> None:
        """path 参数过滤 diff 输出。"""
        from heagent.tools.builtins.git import git_diff

        result = await git_diff(path="src/main.py")
        # diff header 以 a/ b/ 或 ---/+++ 开头，含文件名
        assert "main.py" in result
        assert "new_file" not in result


# ── git_log ──────────────────────────────────────────────────────────────────


class TestGitLog:
    @pytest.mark.asyncio
    async def test_shows_commits(self, git_repo: Path) -> None:
        """返回 oneline 提交历史。"""
        from heagent.tools.builtins.git import git_log

        result = await git_log()
        lines = result.split("\n")
        assert len(lines) == 2  # initial + update readme
        assert "update readme" in result
        assert "initial commit" in result

    @pytest.mark.asyncio
    async def test_limits_max_count(self, git_repo: Path) -> None:
        """max_count 限制返回行数。"""
        from heagent.tools.builtins.git import git_log

        result = await git_log(max_count=1)
        lines = result.split("\n")
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_clamps_max_count_to_100(self, git_repo: Path) -> None:
        """max_count > 100 钳位到 100。"""
        from heagent.tools.builtins.git import git_log

        result = await git_log(max_count=999)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_clamps_min_count_to_1(self, git_repo: Path) -> None:
        """max_count <= 0 钳位到 1。"""
        from heagent.tools.builtins.git import git_log

        result = await git_log(max_count=0)
        lines = result.split("\n")
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_filter_by_path(self, git_repo: Path) -> None:
        """path 参数过滤：仅显示涉及该文件的提交。"""
        from heagent.tools.builtins.git import git_log

        result = await git_log(path="src/utils.py")
        lines = result.split("\n")
        assert len(lines) == 1
        assert "initial commit" in lines[0]

    @pytest.mark.asyncio
    async def test_filter_nonexistent_path(self, git_repo: Path) -> None:
        """不存在的路径返回空。"""
        from heagent.tools.builtins.git import git_log

        result = await git_log(path="nonexistent.py")
        assert result == "(no commits)"


# ── git_blame ────────────────────────────────────────────────────────────────


class TestGitBlame:
    @pytest.mark.asyncio
    async def test_blame_readme(self, git_repo: Path) -> None:
        """blame 返回含作者和行内容的结果。"""
        from heagent.tools.builtins.git import git_blame

        result = await git_blame(file_path="README.md")
        assert "HeAgent Test" in result
        assert "Test Repo" in result or "# Test Repo" in result

    @pytest.mark.asyncio
    async def test_blame_src_file(self, git_repo: Path) -> None:
        """blame 返回源文件的行归属。"""
        from heagent.tools.builtins.git import git_blame

        result = await git_blame(file_path="src/main.py")
        assert "HeAgent Test" in result
        assert "print" in result

    @pytest.mark.asyncio
    async def test_empty_path_raises(self, git_repo: Path) -> None:
        """空 file_path 抛 ValueError。"""
        from heagent.tools.builtins.git import git_blame

        with pytest.raises(ValueError, match="required"):
            await git_blame(file_path="")

    @pytest.mark.asyncio
    async def test_nonexistent_file_raises(self, git_repo: Path) -> None:
        """未跟踪文件 git blame 抛 RuntimeError。"""
        from heagent.tools.builtins.git import git_blame

        (git_repo / "subdir").mkdir()
        (git_repo / "subdir" / "not_tracked.py").write_text("x=1\n", encoding="utf-8")
        with pytest.raises(RuntimeError):
            await git_blame(file_path="subdir/not_tracked.py")


# ── workspace 路径围栏 ───────────────────────────────────────────────────────


class TestGitPathSafety:
    @pytest.mark.asyncio
    async def test_path_escape_blocked(self, git_repo: Path) -> None:
        """路径越狱被拒绝。"""
        from heagent.tools.builtins.git import git_status
        from heagent.tools.path_safety import WorkspacePathError

        with pytest.raises(WorkspacePathError):
            await git_status(path="../outside")

    @pytest.mark.asyncio
    async def test_absolute_path_in_workspace_ok(self, git_repo: Path) -> None:
        """工作区内的绝对路径可通过。"""
        from heagent.tools.builtins.git import git_status

        abs_path = str(git_repo / "src" / "main.py")
        result = await git_status(path=abs_path)
        assert result == "(clean)"

    @pytest.mark.asyncio
    async def test_absolute_path_outside_blocked(self, git_repo: Path) -> None:
        """工作区外的绝对路径被拒绝。"""
        from heagent.tools.builtins.git import git_status
        from heagent.tools.path_safety import WorkspacePathError

        with pytest.raises(WorkspacePathError):
            await git_status(path="/etc/passwd")


# ── 工具 schema 注册 ─────────────────────────────────────────────────────────


class TestGitToolRegistration:
    def test_all_git_tools_registered(self) -> None:
        """4 个 git 工具均已在全局 registry 单例中注册。"""
        import heagent.tools.builtins.git  # noqa: F401 — 触发 @tool 注册
        from heagent.tools.registry import ToolRegistry

        reg = ToolRegistry.get()
        names = reg.list_names()
        assert "git_status" in names
        assert "git_diff" in names
        assert "git_log" in names
        assert "git_blame" in names

    def test_git_tools_readonly(self) -> None:
        """所有 git 工具标记 readOnlyHint=True。"""
        import heagent.tools.builtins.git  # noqa: F401 — 触发 @tool 注册
        from heagent.tools.registry import ToolRegistry

        reg = ToolRegistry.get()
        for name in ["git_status", "git_diff", "git_log", "git_blame"]:
            schema = reg.get_schema(name)
            assert schema is not None, f"schema for {name} is None"
            assert schema.annotations is not None, f"annotations for {name} is None"
            assert schema.annotations.readOnlyHint is True, f"{name} 应为 readOnlyHint"
            assert schema.annotations.destructiveHint is None or schema.annotations.destructiveHint is False
