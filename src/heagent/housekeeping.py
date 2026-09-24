"""CLI/GUI 启动时的运行时产物回收（日志 / 会话 / 编辑快照 / 沙箱会话目录）。

**为什么单独放这里**：``.heagent/runs`` 与 ``.heagent/ledger`` 属 engine 的 run 级治理，
由 ``EngineContainer.prune_*_once`` 在全新 run 启动时回收；而**日志**、**会话**
（``.heagent/sessions/``）、**编辑快照**（``.heagent/tmp/edit-snapshots/``）、
**沙箱会话目录**（``.heagent/sandboxes/<run_id>/``）是 CLI / 工具层直接落盘的产物，
此前**没有任何回收方**——实测 84 天后 logs 21 MiB / 722 个文件、sessions 83 MiB / 409 个
文件（最老 101 天）、edit-snapshots 只增不减；沙箱会话目录则由 run 正常结束的 teardown
删除，**崩溃 / SIGKILL 的 run 会留下孤儿目录**（E40-D1）。它们不依赖 engine（四类目录在
CLI 启动时即为已知），故统一在本模块回收，由 CLI/GUI 启动时调用一次。

全部 **best-effort**：任何失败只记日志，绝不阻断启动——清理是维护动作，不是功能；
保留期设为 ``*_RETENTION_DAYS=0`` 即整类禁用。

属于 CLI 辅助层（与 ``cli.py`` 同侧），不参与 engine 依赖 DAG。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.config import get_settings
from heagent.context.session import SessionStore
from heagent.persist import (
    delete_entries,
    prune_entries_by_mtime,
    prune_stamp_path,
    scan_dir,
    stamp_is_recent,
    touch_prune_stamp,
)
from heagent.tools.edits import prune_snapshots
from heagent.tools.sandbox import sandbox_sessions_root

if TYPE_CHECKING:
    from heagent.config import Settings

logger = logging.getLogger(__name__)


async def prune_logs(
    log_dir: Path, retention_days: int, *, min_interval_seconds: int = 0, stamp_root: Path | None = None
) -> int:
    """回收 ``log_dir`` 下超过保留期的日志文件（按 mtime），返回删除数。

    每次启动都会新建 ``heagent-<时间戳>.log``，而日志含完整 prompt / 工具 JSON（单个可达
    数十 MB），不回收会随使用无限增长。``retention_days <= 0`` 禁用。

    ``stamp_root`` 用来把节流标记收进 ``.heagent/``：``logs/`` 的父目录是仓库根，默认落点
    会在仓库根留下未跟踪文件（``.logs.prune-stamp``）。序列实现在
    ``prune_entries_by_mtime``（与 sessions / edit-snapshots 共用，仅后缀不同）。
    """
    return await prune_entries_by_mtime(
        log_dir,
        retention_days=retention_days,
        suffix=".log",
        min_interval_seconds=min_interval_seconds,
        stamp_root=stamp_root,
    )


# 沙箱会话目录清理的单趟上限：崩溃孤儿可能一次积压成千上万，单趟全删会让启动抖动
# （rmtree 同步 I/O）；每趟最多删这么多，其余留待后续启动收敛（截断时记 warning）。
_SANDBOX_PRUNE_MAX_PER_PASS = 256


@dataclass(frozen=True)
class SandboxPruneOutcome:
    """一次沙箱会话目录回收的结果（供日志与测试断言；``deleted`` 是可观测的主指标）。"""

    deleted: int = 0
    retained_active: int = 0
    skipped_malformed: int = 0
    failed: int = 0
    capped: bool = False


def _sandbox_dir_activity(path: Path) -> tuple[float, bool]:
    """返回 ``(最新 mtime, 是否可安全回收)``；只扫一层子项，符号链接一律不回收。

    活跃度取「目录自身 + 直接子项」中最新的 mtime：正在使用的 run 写文件即刷新子项
    mtime，因此保留期内的目录不会被误删（这是「不删正在跑的 run」的判活依据）。
    只扫一层是有意为之——判定成本有界且可预测，不递归整棵目录树。

    符号链接返回 ``(0.0, False)``：回收方**绝不穿透链接**（``rmtree`` 对符号链接会拒绝，
    但显式判定更早、更清楚），链接目标不属于本模块的清理范围。
    """
    try:
        if path.is_symlink():
            logger.warning("sandbox prune: refusing to reclaim symlinked entry %s", path)
            return 0.0, False
        newest = path.stat().st_mtime
        with os.scandir(path) as it:
            for child in it:
                try:
                    newest = max(newest, child.stat().st_mtime)
                except OSError:
                    # 单个子项读不到（权限 / 读取中被删）不影响其余判定：保守地忽略它。
                    logger.debug("sandbox prune: stat failed on %s; ignoring it", child.path, exc_info=True)
        return newest, True
    except OSError:
        # 目录读不出来（权限 / 竞态）：保守跳过，宁可留到下次启动也不误删。
        logger.debug("sandbox prune: cannot inspect %s; skipping it", path, exc_info=True)
        return 0.0, False


def _prune_sandbox_dirs_sync(base: Path, *, cutoff: float, max_per_pass: int) -> SandboxPruneOutcome:
    """同步实现：单次目录扫描 + 逐条判活 + 批量删除（经 ``asyncio.to_thread`` 调用，一次线程跳转）。"""
    candidates: list[Path] = []
    retained_active = 0
    skipped_malformed = 0
    for entry in scan_dir(base):
        if not entry.is_dir:
            # 畸形条目（散落文件 / 临时文件）：不动它——回收方只清理自己创建的目录形态。
            logger.debug("sandbox prune: skipping non-directory entry %s", entry.path)
            skipped_malformed += 1
            continue
        newest, reclaimable = _sandbox_dir_activity(entry.path)
        if not reclaimable:
            skipped_malformed += 1
            continue
        if newest >= cutoff:
            retained_active += 1
            continue
        candidates.append(entry.path)

    limit = max(max_per_pass, 0)
    to_delete = candidates[:limit]
    deleted = 0
    if to_delete:
        _, deleted = delete_entries([], to_delete)
    return SandboxPruneOutcome(
        deleted=deleted,
        retained_active=retained_active,
        skipped_malformed=skipped_malformed,
        failed=len(to_delete) - deleted,
        capped=len(candidates) > limit,
    )


async def prune_sandbox_dirs(
    workspace: Path,
    retention_days: int,
    *,
    min_interval_seconds: int = 0,
    stamp_root: Path | None = None,
    now: float | None = None,
    max_per_pass: int = _SANDBOX_PRUNE_MAX_PER_PASS,
) -> int:
    """回收崩溃 run 遗留的沙箱会话目录（``<workspace>/.heagent/sandboxes/<run_id>/``），返回删除数。

    **为什么需要**：正常结束的 run 由 ``EngineContainer.close_run`` → ``SandboxSession.close``
    删除自己的目录，但进程崩溃 / 被 SIGKILL 不走该路径，目录会留在磁盘上（E40-D1）。
    本函数是唯一回收方，由 CLI/GUI 启动时调用一次（``retention_days <= 0`` 禁用）。

    判活规则（不删正在跑的 run）：以「目录自身与其直接子项中最新的 mtime」为活跃度，
    落在保留期内即跳过；只扫一层，成本有界。畸形条目（散落文件）与符号链接一律不回收。

    有界与可观测：单趟删除数受 ``max_per_pass`` 限制（截断时记 warning）；删除失败的条目
    记 warning 并留待下次启动，不影响其余；``retained_active`` / ``skipped_malformed``
    计数在 debug 日志中可见。``min_interval_seconds`` 复用 ``PRUNE_MIN_INTERVAL_SECONDS``
    节流（自己的标记文件，落在 ``.heagent/.sandboxes.prune-stamp``）。
    """
    if retention_days <= 0:
        return 0
    base = sandbox_sessions_root(workspace)
    stamp = prune_stamp_path(base, stamp_root=stamp_root if stamp_root is not None else workspace / ".heagent")
    if await asyncio.to_thread(stamp_is_recent, stamp, min_interval_seconds):
        return 0
    cutoff = (now if now is not None else time.time()) - retention_days * 86_400
    outcome = await asyncio.to_thread(_prune_sandbox_dirs_sync, base, cutoff=cutoff, max_per_pass=max_per_pass)
    await asyncio.to_thread(touch_prune_stamp, stamp)

    if outcome.deleted:
        logger.info("Sandbox session dirs pruned %d (retention=%dd)", outcome.deleted, retention_days)
    if outcome.failed:
        logger.warning(
            "Sandbox prune: %d of %d candidate dirs could not be removed (in use/locked?); "
            "they will be retried on a later startup",
            outcome.failed,
            outcome.deleted + outcome.failed,
        )
    if outcome.capped:
        logger.warning(
            "Sandbox prune hit the per-pass cap (%d); remaining orphans will be reclaimed by later startups",
            max_per_pass,
        )
    if outcome.retained_active or outcome.skipped_malformed:
        logger.debug(
            "Sandbox prune: retained %d active, skipped %d malformed entries",
            outcome.retained_active,
            outcome.skipped_malformed,
        )
    return outcome.deleted


async def run_housekeeping(
    *, settings: Settings | None = None, workspace: Path | None = None, log_dir: Path | None = None
) -> dict[str, int]:
    """按 Settings 的保留期回收日志 / 会话 / 编辑快照 / 沙箱会话目录，返回各目标删除数。

    四类各自独立 try：某一类失败（权限、路径不存在）不影响其余，也不影响启动流程。
    节流复用 ``PRUNE_MIN_INTERVAL_SECONDS``（与 runs/ledger 同一开关，各自独立标记文件）——
    短命 CLI 进程在间隔内启动时几乎零清理成本。
    """
    conf = settings or get_settings()
    interval = conf.prune_min_interval_seconds
    root = workspace or Path.cwd()
    targets: dict[str, int] = {"logs": 0, "sessions": 0, "snapshots": 0, "sandboxes": 0}

    try:
        targets["logs"] = await prune_logs(
            log_dir or Path(conf.log_dir),
            conf.log_retention_days,
            min_interval_seconds=interval,
            # 节流标记收进 .heagent/：logs/ 的父目录就是仓库根，会给 git status 留未跟踪文件。
            stamp_root=root / ".heagent",
        )
    except Exception:
        logger.warning("log retention cleanup failed", exc_info=True)

    try:
        from heagent.workspace import WorkspacePaths

        session_store = SessionStore(str(WorkspacePaths.from_root(root).sessions))
        targets["sessions"] = await session_store.prune(conf.session_retention_days, min_interval_seconds=interval)
    except Exception:
        logger.warning("session retention cleanup failed", exc_info=True)

    try:
        targets["snapshots"] = await prune_snapshots(
            conf.edit_snapshot_retention_days, workspace=root, min_interval_seconds=interval
        )
    except Exception:
        logger.warning("edit snapshot retention cleanup failed", exc_info=True)

    try:
        targets["sandboxes"] = await prune_sandbox_dirs(
            root, conf.sandbox_dir_retention_days, min_interval_seconds=interval
        )
    except Exception:
        logger.warning("sandbox session dir cleanup failed", exc_info=True)

    if any(targets.values()):
        logger.info("housekeeping pruned %s", ", ".join(f"{k}={v}" for k, v in targets.items() if v))
    return targets


def prune_runtime_artifacts_sync(
    settings: Settings | None = None, *, workspace: Path | None = None, log_dir: Path | None = None
) -> dict[str, int]:
    """``run_housekeeping`` 的同步包装（CLI/GUI 启动入口都是同步函数）。

    - 四类保留期全为 0（如测试环境）时**直接返回**，不进事件循环；
    - 已在事件循环中调用（测试用 CliRunner 直接驱动入口）时 ``asyncio.run`` 会抛
      ``RuntimeError``——此时只记 ``debug`` 跳过：启动路径不应因清理动作出问题。
    """
    conf = settings or get_settings()
    if not (
        conf.log_retention_days
        or conf.session_retention_days
        or conf.edit_snapshot_retention_days
        or conf.sandbox_dir_retention_days
    ):
        return {"logs": 0, "sessions": 0, "snapshots": 0, "sandboxes": 0}
    try:
        return asyncio.run(run_housekeeping(settings=conf, workspace=workspace, log_dir=log_dir))
    except RuntimeError:
        logger.debug("housekeeping skipped: running inside an event loop", exc_info=True)
        return {"logs": 0, "sessions": 0, "snapshots": 0, "sandboxes": 0}
