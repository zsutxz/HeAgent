"""补 tools/builtins/search.py 未覆盖行。"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from heagent.tools.builtins.search import content_search, file_search, _resolve_dir
from heagent.tools.path_safety import reset_workspace_root, set_workspace_root

if TYPE_CHECKING:
    pass


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path) -> Generator[None, None, None]:
    """Set workspace root to tmp_path for each test."""
    set_workspace_root(tmp_path.resolve())
    yield
    reset_workspace_root()


class TestResolveDirErrors:
    """_resolve_dir 错误处理。"""

    def test_directory_not_found(self, tmp_path):
        """目录不存在→返回 Error 消息。"""
        nonexistent = str(tmp_path / "nonexistent")
        result = _resolve_dir(nonexistent)
        assert isinstance(result, str)
        assert "Error: directory not found" in result

    def test_path_is_file_not_directory(self, tmp_path):
        """路径是文件不是目录→返回 Error 消息。"""
        f = tmp_path / "a_file.txt"
        f.write_text("hello")
        result = _resolve_dir(str(f))
        assert isinstance(result, str)
        assert "Error: path is not a directory" in result


class TestFileSearchEdgeCases:
    """file_search 边缘路径。"""

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        """空目录无匹配→返回 no files 消息。"""
        result = await file_search("*.py", str(tmp_path))
        assert "No files matching" in result

    @pytest.mark.asyncio
    async def test_max_results_truncation(self, tmp_path):
        """文件超过 max_results→截断。"""
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text("data")

        result = await file_search("*.txt", str(tmp_path), max_results=3)
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) <= 3


class TestContentSearchEdgeCases:
    """content_search 边缘路径。"""

    @pytest.mark.asyncio
    async def test_invalid_regex(self, tmp_path):
        """无效正则→返回 Error 消息。"""
        result = await content_search("[invalid", str(tmp_path), file_pattern="*.txt")
        assert "Error: invalid regex" in result

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        """无匹配→No matches 消息。"""
        (tmp_path / "test.txt").write_text("hello world")
        result = await content_search("NOMATCH_zzz", str(tmp_path), file_pattern="*.txt")
        assert "No matches for" in result

    @pytest.mark.asyncio
    async def test_large_file_skipped(self, tmp_path, monkeypatch):
        """超大文件被跳过。"""
        import heagent.tools.builtins.search as s

        monkeypatch.setattr(s, "_MAX_FILE_SIZE", 10)
        (tmp_path / "big.txt").write_text("x" * 100)

        result = await content_search("x", str(tmp_path), file_pattern="*.txt")
        # big.txt should be skipped due to size
        assert "skipped" in result.lower() or "No matches" in result

    @pytest.mark.asyncio
    async def test_normal_match_found(self, tmp_path):
        """正常匹配内容搜索结果。"""
        (tmp_path / "code.py").write_text("def hello(): return 42")
        result = await content_search("hello", str(tmp_path), file_pattern="*.py")
        assert "hello" in result
