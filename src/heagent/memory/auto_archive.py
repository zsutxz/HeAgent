"""MEMORY.md 自动归档机制 — 定期将旧条目归档以保持预算内。

在 CLI 启动时调用 `maybe_archive_old_facts()`，根据配置自动归档超过指定天数的事实条目。
归档文件按月存储在 `.heagent/memory/archive/<YYYY-MM>.md`，保留文件头部的核心约定。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from heagent.config import Settings, get_settings

logger = logging.getLogger(__name__)

# 归档时保留的核心约定条目数（文件头部的前 N 条事实）
CORE_FACTS_TO_KEEP = 20

# 归档标记文件（记录上次归档时间戳，用于跨进程节流）
_ARCHIVE_STAMP_FILE = ".heagent/memory/.archive-stamp"


def _should_skip_prune(stamp_path: Path, min_interval_seconds: int) -> bool:
    """检查是否应该跳过清理（基于上次清理时间戳和最小间隔）。"""
    if min_interval_seconds <= 0:
        return False
    if not stamp_path.exists():
        return False
    try:
        last_prune = float(stamp_path.read_text(encoding="utf-8").strip())
        elapsed = time.time() - last_prune
        return elapsed < min_interval_seconds
    except (ValueError, OSError):
        return False


def maybe_archive_old_facts(  # noqa: C901 - 线性流水线（解析 → 筛选 → 分月 → 写归档 → 更新）
    memory_path: Path | str = ".heagent/memory/MEMORY.md",
    settings: Settings | None = None,
) -> dict[str, int]:
    """在启动时检查并归档旧的事实条目（跨进程节流、fail-soft）。

    归档策略：
    1. 检查距上次归档是否已超过 memory_archive_min_interval_seconds（默认 1 天）
    2. 解析 MEMORY.md，提取所有事实条目
    3. 识别超过 memory_auto_archive_days（默认 90 天）的条目（基于添加时间估算）
    4. 保留文件头部的前 CORE_FACTS_TO_KEEP 条（核心约定）
    5. 将其余旧条目移动到 `.heagent/memory/archive/<YYYY-MM>.md`
    6. 更新 MEMORY.md，只保留核心约定和近期条目

    Returns:
        统计信息字典：
        - archived: 归档的条目数
        - kept: 保留的条目数
        - skipped: 因节流跳过（返回全 0）

    失败时 fail-soft：记录 WARNING 并返回全 0 统计，不中断启动流程。
    """
    settings = settings or get_settings()

    # 检查是否启用自动归档
    if settings.memory_auto_archive_days <= 0:
        return {"archived": 0, "kept": 0, "skipped": True}

    # 跨进程节流：检查距上次归档是否足够久
    stamp_path = Path(_ARCHIVE_STAMP_FILE)
    if _should_skip_prune(stamp_path, settings.memory_archive_min_interval_seconds):
        logger.debug("Skipping memory auto-archive (last run was too recent)")
        return {"archived": 0, "kept": 0, "skipped": True}

    memory_path = Path(memory_path)
    if not memory_path.exists():
        logger.debug("MEMORY.md does not exist, skipping auto-archive")
        return {"archived": 0, "kept": 0, "skipped": True}

    try:
        # 读取当前 MEMORY.md
        content = memory_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        # 提取标题部分和事实部分
        header_lines = []
        facts = []
        fact_start_idx = -1

        for i, line in enumerate(lines):
            if line.strip().startswith("- "):
                if fact_start_idx == -1:
                    fact_start_idx = i
                facts.append(line)
            elif fact_start_idx == -1:
                header_lines.append(line)

        if not facts:
            logger.debug("No facts found in MEMORY.md")
            return {"archived": 0, "kept": 0, "skipped": True}

        # 估算每条事实的年龄：假设条目按时间顺序添加，越靠后越新
        # 使用文件 mtime 作为最新条目的时间戳，向前推算
        file_mtime = memory_path.stat().st_mtime
        total_facts = len(facts)

        # 简化策略：保留前 CORE_FACTS_TO_KEEP 条（核心约定）+ 最近的条目
        # 中间的旧条目才归档
        cutoff_timestamp = time.time() - (settings.memory_auto_archive_days * 86400)

        # 判断哪些条目需要归档：
        # - 前 CORE_FACTS_TO_KEEP 条：永久保留（核心约定）
        # - 其余条目：如果估算时间早于 cutoff，则归档

        # 估算每条的时间戳（线性分布假设：最后一条 = file_mtime，第一条 = 更早）
        # 假设平均每 7 天添加 1 条事实
        DAYS_PER_FACT = 7
        estimated_timestamps = []
        for i in range(total_facts):
            # 从后往前推算：最后一条是 file_mtime，越靠前越老
            days_ago = (total_facts - 1 - i) * DAYS_PER_FACT
            estimated_ts = file_mtime - (days_ago * 86400)
            estimated_timestamps.append(estimated_ts)

        # 分类条目
        to_keep = []
        to_archive = []

        for i, (fact, est_ts) in enumerate(zip(facts, estimated_timestamps, strict=False)):
            # 前 CORE_FACTS_TO_KEEP 条永久保留
            if i < CORE_FACTS_TO_KEEP:
                to_keep.append(fact)
            # 其余条目：旧的归档，新的保留
            elif est_ts < cutoff_timestamp:
                to_archive.append((fact, est_ts))
            else:
                to_keep.append(fact)

        if not to_archive:
            logger.info("No old facts to archive (all within %d days)", settings.memory_auto_archive_days)
            # 更新标记文件
            stamp_path.parent.mkdir(parents=True, exist_ok=True)
            stamp_path.write_text(str(time.time()), encoding="utf-8")
            return {"archived": 0, "kept": len(to_keep), "skipped": False}

        # 按月份分组归档文件
        archive_by_month: dict[str, list[str]] = {}
        for fact, est_ts in to_archive:
            month_key = datetime.fromtimestamp(est_ts, tz=UTC).strftime("%Y-%m")
            if month_key not in archive_by_month:
                archive_by_month[month_key] = []
            archive_by_month[month_key].append(fact)

        # 写入归档文件
        archive_dir = memory_path.parent / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        for month_key, month_facts in archive_by_month.items():
            archive_file = archive_dir / f"{month_key}.md"

            # 如果归档文件已存在，追加；否则创建新文件
            if archive_file.exists():
                existing = archive_file.read_text(encoding="utf-8")
                new_content = existing.rstrip() + "\n\n" + "\n".join(month_facts) + "\n"
            else:
                new_content = (
                    f"# MEMORY.md 归档 - {month_key}\n\n"
                    f"> 本文件包含从 MEMORY.md 自动归档的旧事实条目。\n"
                    f"> 归档时间：{datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                    + "\n".join(month_facts)
                    + "\n"
                )

            archive_file.write_text(new_content, encoding="utf-8")
            logger.info("Archived %d facts to %s", len(month_facts), archive_file)

        # 更新 MEMORY.md（只保留 header + to_keep）
        new_content = "\n".join(header_lines) + "\n" + "\n".join(to_keep)
        memory_path.write_text(new_content, encoding="utf-8")

        # 更新标记文件
        stamp_path.parent.mkdir(parents=True, exist_ok=True)
        stamp_path.write_text(str(time.time()), encoding="utf-8")

        logger.info(
            "Memory auto-archive completed: %d facts archived, %d kept (budget: %d bytes)",
            len(to_archive),
            len(to_keep),
            settings.memory_inject_max_bytes,
        )

        return {"archived": len(to_archive), "kept": len(to_keep), "skipped": False}

    except Exception as exc:
        # Fail-soft：记录错误但不中断启动
        logger.warning(
            "Memory auto-archive failed (%s: %s); continuing without archiving",
            type(exc).__name__,
            exc,
        )
        return {"archived": 0, "kept": 0, "skipped": True}
