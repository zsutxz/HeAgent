"""SOUL.md 人格系统测试 — memory/soul.py"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.memory.soul import SoulStore

if TYPE_CHECKING:
    from pathlib import Path


class TestSoulStore:
    """SoulStore 两级加载测试。"""

    def test_no_files_returns_none(self, tmp_path: Path) -> None:
        """两个文件都不存在时返回 None。"""
        store = SoulStore(
            global_path=str(tmp_path / "global" / "SOUL.md"),
            project_path=str(tmp_path / "project" / "SOUL.md"),
        )
        assert store.load() is None

    def test_global_only(self, tmp_path: Path) -> None:
        """只有全局 SOUL.md 时返回全局内容。"""
        global_file = tmp_path / "global" / "SOUL.md"
        global_file.parent.mkdir(parents=True)
        global_file.write_text("I am a helpful assistant.", encoding="utf-8")

        store = SoulStore(
            global_path=str(global_file),
            project_path=str(tmp_path / "project" / "SOUL.md"),
        )
        assert store.load() == "I am a helpful assistant."

    def test_project_overrides_global(self, tmp_path: Path) -> None:
        """项目级 SOUL.md 存在时覆盖全局。"""
        global_file = tmp_path / "global" / "SOUL.md"
        global_file.parent.mkdir(parents=True)
        global_file.write_text("Global personality", encoding="utf-8")

        project_file = tmp_path / "project" / "SOUL.md"
        project_file.parent.mkdir(parents=True)
        project_file.write_text("Project personality", encoding="utf-8")

        store = SoulStore(
            global_path=str(global_file),
            project_path=str(project_file),
        )
        assert store.load() == "Project personality"

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        """空文件视为不存在。"""
        project_file = tmp_path / "SOUL.md"
        project_file.write_text("   \n\n  ", encoding="utf-8")

        store = SoulStore(
            global_path=str(tmp_path / "none.md"),
            project_path=str(project_file),
        )
        assert store.load() is None

    def test_project_only_no_global(self, tmp_path: Path) -> None:
        """只有项目级 SOUL.md 时返回项目内容。"""
        project_file = tmp_path / "SOUL.md"
        project_file.write_text("Project only", encoding="utf-8")

        store = SoulStore(
            global_path=str(tmp_path / "none.md"),
            project_path=str(project_file),
        )
        assert store.load() == "Project only"
