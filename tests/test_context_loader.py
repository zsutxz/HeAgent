"""上下文文件扫描器测试 — context/loader.py"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.config import get_settings, reset_settings
from heagent.context.loader import collect_context_files, load_context_files

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


# ══════════════════════════════════════════════════════════════════════
# 分层发现（仓库根 → cwd）— 对齐 Codex 的 AGENTS.md 语义
# ══════════════════════════════════════════════════════════════════════


def _make_repo(root: Path) -> Path:
    """把 root 标记为仓库根（建 .git 目录）。"""
    (root / ".git").mkdir(parents=True, exist_ok=True)
    return root


class TestLayeredDiscovery:
    def test_walks_up_to_repo_root_generic_to_specific(self, tmp_path: Path) -> None:
        """仓库根 → 中间目录 → cwd 三层都被纳入，层序由泛到专。"""
        root = _make_repo(tmp_path / "repo")
        middle = root / "svc"
        near = middle / "app"
        (middle / ".heagent").mkdir(parents=True)
        near.mkdir(parents=True)
        (root / "AGENTS.md").write_text("ROOT-CONTEXT", encoding="utf-8")
        (middle / ".heagent" / "CONTEXT.md").write_text("MID-CONTEXT", encoding="utf-8")
        (near / "CLAUDE.md").write_text("NEAR-CONTEXT", encoding="utf-8")

        bundle = collect_context_files(str(near), user_level=False)

        assert [item.label for item in bundle.files] == [
            "AGENTS.md",
            "svc/.heagent/CONTEXT.md",
            "svc/app/CLAUDE.md",
        ]
        rendered = bundle.render()
        assert rendered is not None
        assert rendered.index("ROOT-CONTEXT") < rendered.index("MID-CONTEXT") < rendered.index("NEAR-CONTEXT")
        assert bundle.truncated is False

    def test_stops_at_repo_boundary(self, tmp_path: Path) -> None:
        """仓库根之上的同名文件不被纳入（上溯在仓库标记处停止）。"""
        (tmp_path / "AGENTS.md").write_text("OUTSIDE", encoding="utf-8")
        root = _make_repo(tmp_path / "repo")
        (root / "AGENTS.md").write_text("INSIDE", encoding="utf-8")

        rendered = load_context_files(str(root), user_level=False)

        assert rendered is not None
        assert "INSIDE" in rendered
        assert "OUTSIDE" not in rendered

    def test_without_repo_marker_scans_single_level(self, tmp_path: Path) -> None:
        """无仓库标记时退化为单层扫描：祖先目录的同名文件不被捞入。"""
        (tmp_path / "AGENTS.md").write_text("PARENT", encoding="utf-8")
        child = tmp_path / "child"
        child.mkdir()
        (child / "CLAUDE.md").write_text("CHILD", encoding="utf-8")

        bundle = collect_context_files(str(child), user_level=False)

        assert [item.label for item in bundle.files] == ["CLAUDE.md"]

    def test_max_levels_bounds_the_walk(self, tmp_path: Path) -> None:
        """仓库根超出 max_levels 时退化为单层（不做无界上溯）。"""
        root = _make_repo(tmp_path / "repo")
        near = root / "a" / "b"
        near.mkdir(parents=True)
        (root / "AGENTS.md").write_text("ROOT", encoding="utf-8")
        (near / "CLAUDE.md").write_text("NEAR", encoding="utf-8")

        bundle = collect_context_files(str(near), user_level=False, max_levels=1)

        assert [item.label for item in bundle.files] == ["CLAUDE.md"]

    def test_single_level_output_is_byte_identical_to_legacy(self, tmp_path: Path) -> None:
        """cwd 即仓库根（既有常见形态）时，输出与旧实现逐字节一致。"""
        root = _make_repo(tmp_path)
        (root / "AGENTS.md").write_text("A", encoding="utf-8")
        (root / "CLAUDE.md").write_text("C", encoding="utf-8")

        assert load_context_files(str(root), user_level=False) == "## AGENTS.md\n\nA\n\n---\n\n## CLAUDE.md\n\nC"

    def test_unreadable_context_file_is_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """坏编码（二进制）文件按不可读跳过并告警，不打断扫描。"""
        root = _make_repo(tmp_path)
        (root / "AGENTS.md").write_bytes(b"\xff\xfe\x00bad")
        (root / "CLAUDE.md").write_text("GOOD", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="heagent.context.loader"):
            rendered = load_context_files(str(root), user_level=False)

        assert rendered is not None
        assert "GOOD" in rendered
        assert "AGENTS.md" not in rendered
        assert any("Failed to read context file" in record.message for record in caplog.records)


# ══════════════════════════════════════════════════════════════════════
# 字节预算 — 近端优先 + 省略显式可见
# ══════════════════════════════════════════════════════════════════════


class TestContextBudget:
    def test_nearest_file_wins_budget_and_omissions_are_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """预算不足时保留更靠近 cwd 的文件，远端文件整段丢弃并显式说明。"""
        root = _make_repo(tmp_path / "repo")
        near = root / "app"
        near.mkdir()
        (root / "AGENTS.md").write_text("R" * 3000, encoding="utf-8")
        (near / "CLAUDE.md").write_text("N" * 3000, encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="heagent.context.loader"):
            bundle = collect_context_files(str(near), user_level=False, max_bytes=4000)

        assert [item.label for item in bundle.files] == ["app/CLAUDE.md"]
        assert bundle.omitted == ["AGENTS.md"]
        rendered = bundle.render()
        assert rendered is not None
        assert "context files omitted: 1" in rendered
        assert "CONTEXT_FILES_MAX_BYTES=4000" in rendered
        assert any("exceeded CONTEXT_FILES_MAX_BYTES" in record.message for record in caplog.records)

    def test_oversized_single_file_is_head_truncated_and_fits_budget(self, tmp_path: Path) -> None:
        """单文件超预算时保留头部 + 截断标记，且结果严格不超预算。"""
        root = _make_repo(tmp_path)
        (root / "AGENTS.md").write_text("X" * 5000, encoding="utf-8")

        bundle = collect_context_files(str(root), user_level=False, max_bytes=1500)

        rendered = bundle.render()
        assert rendered is not None
        assert len(rendered.encode("utf-8")) <= 1500
        assert "truncated — kept the first" in rendered
        assert bundle.files[0].truncated is True
        assert bundle.bytes_used == len(rendered.encode("utf-8"))

    def test_budget_below_minimum_omits_whole_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """预算小于最小残片阈值（1024B）时整段丢弃，不产出无意义残片；原因显式可见。"""
        root = _make_repo(tmp_path)
        (root / "AGENTS.md").write_text("Y" * 5000, encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="heagent.context.loader"):
            bundle = collect_context_files(str(root), user_level=False, max_bytes=200)

        assert bundle.files == []
        assert bundle.omitted == ["AGENTS.md"]
        assert bundle.render() is None  # 不注入空块；原因见 warning 与 omitted
        assert bundle.bytes_used == 0
        assert any("exceeded CONTEXT_FILES_MAX_BYTES" in record.message for record in caplog.records)

    def test_large_budget_keeps_everything_untruncated(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        (root / "CLAUDE.md").write_text("Z" * 100_000, encoding="utf-8")

        bundle = collect_context_files(str(root), user_level=False, max_bytes=1_000_000)

        assert [item.truncated for item in bundle.files] == [False]
        assert bundle.omitted == []
        assert bundle.truncated is False


# ══════════════════════════════════════════════════════════════════════
# 用户级文件（~/.heagent/AGENTS.md）— 默认关闭
# ══════════════════════════════════════════════════════════════════════


class TestUserLevelContext:
    def _home_with_global(self, tmp_path: Path) -> Path:
        home = tmp_path / "home"
        (home / ".heagent").mkdir(parents=True)
        (home / ".heagent" / "AGENTS.md").write_text("GLOBAL-CONTEXT", encoding="utf-8")
        return home

    def test_disabled_by_default(self, tmp_path: Path) -> None:
        """缺省不纳入用户级文件（避免全局文件静默影响每个项目）。"""
        reset_settings()
        assert get_settings().context_files_user_level is False

        home = self._home_with_global(tmp_path)
        root = _make_repo(tmp_path / "repo")
        (root / "CLAUDE.md").write_text("LOCAL-CONTEXT", encoding="utf-8")

        bundle = collect_context_files(str(root), user_level=False, home=home)

        assert [item.label for item in bundle.files] == ["CLAUDE.md"]

    def test_included_when_enabled_and_rendered_first(self, tmp_path: Path) -> None:
        """开启后用户级文件排在最前（最泛），且标题不泄露开发机绝对路径。"""
        home = self._home_with_global(tmp_path)
        root = _make_repo(tmp_path / "repo")
        (root / "CLAUDE.md").write_text("LOCAL-CONTEXT", encoding="utf-8")

        bundle = collect_context_files(str(root), user_level=True, home=home)

        assert [item.label for item in bundle.files] == ["~/.heagent/AGENTS.md", "CLAUDE.md"]
        rendered = bundle.render()
        assert rendered is not None
        assert rendered.index("GLOBAL-CONTEXT") < rendered.index("LOCAL-CONTEXT")
        assert str(home) not in rendered

    def test_missing_user_file_is_silent(self, tmp_path: Path) -> None:
        """用户级文件不存在时静默跳过（不算省略、不告警）。"""
        root = _make_repo(tmp_path / "repo")
        (root / "CLAUDE.md").write_text("LOCAL", encoding="utf-8")

        bundle = collect_context_files(str(root), user_level=True, home=tmp_path / "empty-home")

        assert [item.label for item in bundle.files] == ["CLAUDE.md"]
        assert bundle.omitted == []
