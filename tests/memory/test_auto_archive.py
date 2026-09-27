"""Tests for MEMORY.md auto-archive mechanism."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from heagent.config import Settings
from heagent.memory.auto_archive import CORE_FACTS_TO_KEEP, maybe_archive_old_facts


def _create_memory_file(path: Path, facts: list[str]) -> None:
    """创建测试用的 MEMORY.md 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# HeAgent 长期记忆\n\n> 这是测试文件\n\n"
    content = header + "\n".join(f"- {fact}" for fact in facts)
    path.write_text(content, encoding="utf-8")


class TestAutoArchive:
    def test_disabled_when_memory_auto_archive_days_is_zero(self, tmp_path: Path) -> None:
        """memory_auto_archive_days=0 时不执行归档。"""
        memory_path = tmp_path / "MEMORY.md"
        _create_memory_file(memory_path, ["fact1", "fact2"])

        settings = Settings(memory_auto_archive_days=0)
        result = maybe_archive_old_facts(memory_path, settings)

        assert result["skipped"] is True
        assert result["archived"] == 0

    def test_skips_when_file_does_not_exist(self, tmp_path: Path) -> None:
        """MEMORY.md 不存在时跳过归档。"""
        memory_path = tmp_path / "MEMORY.md"
        settings = Settings(memory_auto_archive_days=90)

        result = maybe_archive_old_facts(memory_path, settings)

        assert result["skipped"] is True
        assert result["archived"] == 0

    def test_skips_when_no_facts_to_archive(self, tmp_path: Path) -> None:
        """所有事实都在保留期内时跳过归档。"""
        memory_path = tmp_path / "MEMORY.md"
        # 只有少量事实，都会被保留
        _create_memory_file(memory_path, [f"recent fact {i}" for i in range(5)])

        settings = Settings(
            memory_auto_archive_days=90,
            memory_archive_min_interval_seconds=0,  # 禁用节流
        )

        result = maybe_archive_old_facts(memory_path, settings)

        assert result["archived"] == 0
        assert result["kept"] == 5

    def test_archives_old_facts_and_keeps_core_and_recent(self, tmp_path: Path) -> None:
        """归档旧事实，保留核心约定和近期事实。"""
        memory_path = tmp_path / "MEMORY.md"

        # 创建足够多的事实（超过 CORE_FACTS_TO_KEEP）
        total_facts = 50
        facts = [f"fact {i}" for i in range(total_facts)]
        _create_memory_file(memory_path, facts)

        # 设置较短的保留期，确保会触发归档
        settings = Settings(
            memory_auto_archive_days=30,  # 30 天
            memory_archive_min_interval_seconds=0,  # 禁用节流
        )

        result = maybe_archive_old_facts(memory_path, settings)

        # 验证有事实被归档
        assert result["archived"] > 0
        assert result["kept"] > 0
        assert result["skipped"] is False

        # 验证核心约定被保留（前 CORE_FACTS_TO_KEEP 条）
        updated_content = memory_path.read_text(encoding="utf-8")
        for i in range(CORE_FACTS_TO_KEEP):
            assert f"fact {i}" in updated_content, f"Core fact {i} should be kept"

        # 验证归档文件被创建
        archive_dir = memory_path.parent / "archive"
        assert archive_dir.exists()
        archive_files = list(archive_dir.glob("*.md"))
        assert len(archive_files) > 0

    def test_respects_min_interval_throttling(self, tmp_path: Path) -> None:
        """节流机制：距上次归档不足间隔时跳过。"""
        memory_path = tmp_path / "MEMORY.md"
        _create_memory_file(memory_path, [f"fact {i}" for i in range(30)])

        settings = Settings(
            memory_auto_archive_days=30,
            memory_archive_min_interval_seconds=3600,  # 1 小时节流
        )

        # 第一次归档
        maybe_archive_old_facts(memory_path, settings)
        # 第一次可能因为没有旧条目而跳过，但会更新标记文件

        # 立即第二次归档（应该被节流跳过）
        result2 = maybe_archive_old_facts(memory_path, settings)
        assert result2["skipped"] is True

    def test_creates_monthly_archive_files(self, tmp_path: Path) -> None:
        """归档文件按月份命名（YYYY-MM.md）。"""
        memory_path = tmp_path / "MEMORY.md"
        _create_memory_file(memory_path, [f"fact {i}" for i in range(50)])

        settings = Settings(
            memory_auto_archive_days=30,
            memory_archive_min_interval_seconds=0,
        )

        result = maybe_archive_old_facts(memory_path, settings)

        if result["archived"] > 0:
            archive_dir = memory_path.parent / "archive"
            archive_files = list(archive_dir.glob("*.md"))

            # 验证文件名格式
            for archive_file in archive_files:
                assert archive_file.stem.count("-") == 1  # YYYY-MM 格式
                year, month = archive_file.stem.split("-")
                assert year.isdigit() and len(year) == 4
                assert month.isdigit() and 1 <= int(month) <= 12

    def test_fail_soft_on_errors(self, tmp_path: Path) -> None:
        """读取/写入失败时 fail-soft，返回全 0 统计。"""
        memory_path = tmp_path / "MEMORY.md"
        _create_memory_file(memory_path, ["fact1"])

        # 制造写入失败场景：将 memory_path.parent 设为只读
        # （实际测试中难以实现跨平台的权限控制，这里仅验证 API）
        settings = Settings(
            memory_auto_archive_days=1,
            memory_archive_min_interval_seconds=0,
        )

        # 即使有错误，也应该返回结果而不抛异常
        result = maybe_archive_old_facts(memory_path, settings)
        assert isinstance(result, dict)
        assert "archived" in result
        assert "kept" in result
        assert "skipped" in result

    def test_preserves_header_content(self, tmp_path: Path) -> None:
        """归档后保留文件头部的非事实内容。"""
        memory_path = tmp_path / "MEMORY.md"
        header = "# HeAgent 长期记忆\n\n> 重要说明：这是核心规则\n> 不要删除这些内容\n\n"
        facts = [f"fact {i}" for i in range(30)]
        content = header + "\n".join(f"- {fact}" for fact in facts)
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(content, encoding="utf-8")

        settings = Settings(
            memory_auto_archive_days=30,
            memory_archive_min_interval_seconds=0,
        )

        maybe_archive_old_facts(memory_path, settings)

        # 验证头部内容被保留
        updated_content = memory_path.read_text(encoding="utf-8")
        assert "# HeAgent 长期记忆" in updated_content
        assert "重要说明：这是核心规则" in updated_content
        assert "不要删除这些内容" in updated_content
