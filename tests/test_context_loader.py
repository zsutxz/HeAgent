"""上下文文件扫描器测试 — context/loader.py"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.context.loader import load_context_files

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestLoadContextFiles:
    """load_context_files 的各种场景测试。"""

    def test_no_files_returns_none(self, tmp_path: Path) -> None:
        """目录中无上下文文件时返回 None。"""
        assert load_context_files(str(tmp_path)) is None

    def test_single_claude_md(self, tmp_path: Path) -> None:
        """只有 CLAUDE.md 时正确加载。"""
        (tmp_path / "CLAUDE.md").write_text("# Project\n\nHello world", encoding="utf-8")
        result = load_context_files(str(tmp_path))
        assert result is not None
        assert "## CLAUDE.md" in result
        assert "Hello world" in result

    def test_single_agents_md(self, tmp_path: Path) -> None:
        """只有 AGENTS.md 时正确加载。"""
        (tmp_path / "AGENTS.md").write_text("# Agents\n\nUse Python 3.11+", encoding="utf-8")
        result = load_context_files(str(tmp_path))
        assert result is not None
        assert "## AGENTS.md" in result

    def test_single_context_md(self, tmp_path: Path) -> None:
        """只有 .heagent/CONTEXT.md 时正确加载。"""
        context_dir = tmp_path / ".heagent"
        context_dir.mkdir()
        (context_dir / "CONTEXT.md").write_text("# Context\n\nCustom context", encoding="utf-8")
        result = load_context_files(str(tmp_path))
        assert result is not None
        assert "## .heagent/CONTEXT.md" in result

    def test_priority_order(self, tmp_path: Path) -> None:
        """多个文件时按优先级排列：CONTEXT.md > AGENTS.md > CLAUDE.md。"""
        (tmp_path / "CLAUDE.md").write_text("Claude content", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("Agents content", encoding="utf-8")
        context_dir = tmp_path / ".heagent"
        context_dir.mkdir()
        (context_dir / "CONTEXT.md").write_text("Custom content", encoding="utf-8")

        result = load_context_files(str(tmp_path))
        assert result is not None
        # 确认所有三个文件都被加载
        assert "## .heagent/CONTEXT.md" in result
        assert "## AGENTS.md" in result
        assert "## CLAUDE.md" in result
        # 确认优先级顺序
        assert result.index(".heagent/CONTEXT.md") < result.index("AGENTS.md")
        assert result.index("AGENTS.md") < result.index("CLAUDE.md")

    def test_empty_file_ignored(self, tmp_path: Path) -> None:
        """空文件（仅空白字符）视为不存在。"""
        (tmp_path / "CLAUDE.md").write_text("   \n\n  ", encoding="utf-8")
        assert load_context_files(str(tmp_path)) is None

    def test_default_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """不传 cwd 时使用当前工作目录。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CLAUDE.md").write_text("Test content", encoding="utf-8")
        result = load_context_files()
        assert result is not None
        assert "Test content" in result
