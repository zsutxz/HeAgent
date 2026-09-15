"""CLI/GUI 启动时的运行时产物回收（日志 / 会话 / 编辑快照）。

**为什么单独放这里**：``.heagent/runs`` 与 ``.heagent/ledger`` 属 engine 的 run 级治理，
由 ``EngineContainer.prune_*_once`` 在全新 run 启动时回收；而**日志**、**会话**
（``.heagent/sessions/``）、**编辑快照**（``.heagent/tmp/edit-snapshots/``）是 CLI / 工具层
直接落盘的产物，此前**没有任何回收方**——实测 84 天后 logs 21 MiB / 722 个文件、
sessions 83 MiB / 409 个文件（最老 101 天）、edit-snapshots 只增不减。它们不依赖 engine
（会话与快照在 CLI 启动时即为已知目录），故统一在本模块回收，由 CLI/GUI 启动时调用一次。

全部 **best-effort**：任何失败只记日志，绝不阻断启动——清理是维护动作，不是功能；
保留期设为 ``*_RETENTION_DAYS=0`` 即整类禁用。

属于 CLI 辅助层（与 ``cli.py`` 同侧），不参与 engine 依赖 DAG。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.config import get_settings
from heagent.context.session import SessionStore
from heagent.engine.persist import delete_entries, prune_stamp_path, scan_dir, stamp_is_recent, touch_prune_stamp
from heagent.tools.edits import prune_snapshots

if TYPE_CHECKING:
    from heagent.config import Settings

logger = logging.getLogger(__name__)


async def prune_logs(log_dir: Path, retention_days: int, *, min_interval_seconds: int = 0) -> int:
    """回收 ``log_dir`` 下超过保留期的日志文件（按 mtime），返回删除数。

    每次启动都会新建 ``heagent-<时间戳>.log``，而日志含完整 prompt / 工具 JSON（单个可达
    数十 MB），不回收会随使用无限增长。``retention_days <= 0`` 禁用。
    """
    if retention_days <= 0:
        return 0
    stamp = prune_stamp_path(log_dir)
    if await asyncio.to_thread(stamp_is_recent, stamp, min_interval_seconds):
        return 0
    entries = await asyncio.to_thread(scan_dir, log_dir)
    cutoff = time.time() - retention_days * 86_400
    stale = [e.path for e in entries if not e.is_dir and e.path.name.endswith(".log") and e.mtime < cutoff]
    deleted, _ = await asyncio.to_thread(delete_entries, stale, [])
    await asyncio.to_thread(touch_prune_stamp, stamp)
    return deleted


async def run_housekeeping(
    *, settings: Settings | None = None, workspace: Path | None = None, log_dir: Path | None = None
) -> dict[str, int]:
    """按 Settings 的保留期回收日志 / 会话 / 编辑快照，返回各目标删除数。

    三类各自独立 try：某一类失败（权限、路径不存在）不影响其余，也不影响启动流程。
    节流复用 ``PRUNE_MIN_INTERVAL_SECONDS``（与 runs/ledger 同一开关，各自独立标记文件）——
    短命 CLI 进程在间隔内启动时几乎零清理成本。
    """
    conf = settings or get_settings()
    interval = conf.prune_min_interval_seconds
    root = workspace or Path.cwd()
    targets: dict[str, int] = {"logs": 0, "sessions": 0, "snapshots": 0}

    try:
        targets["logs"] = await prune_logs(
            log_dir or Path(conf.log_dir), conf.log_retention_days, min_interval_seconds=interval
        )
    except Exception:
        logger.warning("log retention cleanup failed", exc_info=True)

    try:
        session_store = SessionStore(str(root / ".heagent" / "sessions"))
        targets["sessions"] = await session_store.prune(conf.session_retention_days, min_interval_seconds=interval)
    except Exception:
        logger.warning("session retention cleanup failed", exc_info=True)

    try:
        targets["snapshots"] = await prune_snapshots(
            conf.edit_snapshot_retention_days, workspace=root, min_interval_seconds=interval
        )
    except Exception:
        logger.warning("edit snapshot retention cleanup failed", exc_info=True)

    if any(targets.values()):
        logger.info("housekeeping pruned %s", ", ".join(f"{k}={v}" for k, v in targets.items() if v))
    return targets


def prune_runtime_artifacts_sync(
    settings: Settings | None = None, *, workspace: Path | None = None, log_dir: Path | None = None
) -> dict[str, int]:
    """``run_housekeeping`` 的同步包装（CLI/GUI 启动入口都是同步函数）。

    - 三类保留期全为 0（如测试环境）时**直接返回**，不进事件循环；
    - 已在事件循环中调用（测试用 CliRunner 直接驱动入口）时 ``asyncio.run`` 会抛
      ``RuntimeError``——此时只记 ``debug`` 跳过：启动路径不应因清理动作出问题。
    """
    conf = settings or get_settings()
    if not (conf.log_retention_days or conf.session_retention_days or conf.edit_snapshot_retention_days):
        return {"logs": 0, "sessions": 0, "snapshots": 0}
    try:
        return asyncio.run(run_housekeeping(settings=conf, workspace=workspace, log_dir=log_dir))
    except RuntimeError:
        logger.debug("housekeeping skipped: running inside an event loop", exc_info=True)
        return {"logs": 0, "sessions": 0, "snapshots": 0}
