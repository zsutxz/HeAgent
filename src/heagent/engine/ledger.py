"""调度 / 长时任务的幂等与租约账本（ledger）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``ExecutionLedger`` 以
**幂等键**为粒度防止同一工作被重复执行，并把进行中的执行以**租约**（lease）占位，避免并发
重复。记录写到 ``.heagent/ledger/<sha1(key)>.json``。

两类使用场景：

- **AgentLoop._execute_one**（P4）：key = ``run_id:call.id``。在 window_reset（上下文压缩）
  后模型可能重发相同 ``tool_call.id``；账本使 COMPLETED 的调用短路返回缓存、避免重复执行。
  工具在途期间由 ``agent/tool_execution._renew_ledger_lease`` 周期续租——工具可跑数分钟
  （``shell`` 超时上限），固定租约不足以覆盖，续租是「未过期 RUNNING 即真在途」的前提。
- **cron 调度**：key = ``cron:{job_id}:{分钟时间戳}``，经 acquire / complete / fail 防同一
  逻辑分钟的 job 被重复执行（租约靠 ``lease_seconds`` 设足覆盖执行）。``heartbeat`` 亦可
  由上层长时 job_runner 周期调用续租（同工具在途续租的用法）。

过期记录由 :meth:`prune` 按保留期自动清理（``EngineContainer.prune_ledger_once`` 在全新 run
启动时触发）：保留期外的终态死记录（``COMPLETED``/``FAILED``）与过期孤儿 ``RUNNING`` 才删，
未过期 ``RUNNING``（在途）保留；保留期内不清理。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from heagent.engine.context import iso_now
from heagent.persist import (
    atomic_write_text,
    load_json_model,
    prune_stamp_path,
    scan_dir,
    stamp_is_recent,
    touch_prune_stamp,
)

logger = logging.getLogger(__name__)

# ── prune 进度日志间隔 ───────────────────────────────────────────
_PRUNE_PROGRESS_INTERVAL = 500  # 每处理 500 个文件打一次 info 日志


class ExecutionStatus(StrEnum):
    """账本中记录的执行状态。"""

    RUNNING = "running"  # 进行中（持有租约）
    COMPLETED = "completed"  # 已成功完成（幂等短路依据）
    FAILED = "failed"  # 已失败


class ExecutionRecord(BaseModel):
    """以幂等键索引的持久化执行记录。"""

    # 幂等键（业务侧给出，如 ``run_id:call.id``）。
    key: str
    # 作用域分组（如 cron job 名）；用于 list_records 排序。
    scope: str = ""
    status: ExecutionStatus = ExecutionStatus.RUNNING
    # 关联的 run_id（便于跨表查询）。
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: str = Field(default_factory=iso_now)
    updated_at: str = Field(default_factory=iso_now)
    # 完成时间（COMPLETED / FAILED 时置）。
    finished_at: str | None = None
    # 租约过期时间；RUNNING 期间有效，完成后清空。
    lease_expires_at: str | None = None
    # 失败原因（FAILED 时置）。
    error: str | None = None


class LedgerClaim(BaseModel):
    """尝试获取一个幂等键的结果。"""

    # 是否成功占用（True = 调用方可执行；False = 已完成或租约活跃，应短路）。
    acquired: bool
    # 未占用时的原因（如 "already completed" / "lease active"）。
    reason: str = ""
    record: ExecutionRecord


# ── 日期比较辅助 ─────────────────────────────────────────────────
# 存储的时间戳来源混杂：``iso_now()`` 输出 naive UTC，测试/外部可能
# 用 ``.isoformat()`` 输出 aware（带 +00:00）。Python 禁止 naive 与 aware
# 直接比较（TypeError）——统一 strip tzinfo 后再比。


def _parse_iso_to_naive(raw: str) -> datetime:
    """``datetime.fromisoformat`` → naive UTC（strip 现有 tzinfo）。"""
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


# ── 账本 ─────────────────────────────────────────────────────────


def _lease_deadline(lease_seconds: int) -> str:
    """租约到期时刻（ISO，naive UTC，**微秒精度**）。

    精度必须到微秒：判定侧（``_is_lease_active`` / ``_is_path_stale``）拿微秒精度的
    ``datetime.now(tz=UTC)`` 比较；若这里按秒截断，记录的实际有效期就变成「到下一个整秒边界
    为止」——最多 1s、最少 0s。1s 量级租约（``_LEDGER_LEASE_SECONDS=1`` 的测试场景）下等于把
    窗口吃掉一半以上，续租稍晚即被判成「过期 RUNNING 孤儿」而删掉（实测：整套测试约半数概率红）。
    生产 120s 租约下截断虽只占 <1%，语义同样是错的——记录报的到期时刻比实际早。
    """
    return (datetime.now(tz=UTC) + timedelta(seconds=lease_seconds)).isoformat(timespec="microseconds")


class ExecutionLedger:
    """JSON 文件后端、防重复执行的幂等账本。"""

    def __init__(self, base_dir: str = ".heagent/ledger") -> None:
        # 账本根目录；按需在 _save() 时创建。
        self._base = Path(base_dir)
        # 进程内互斥：串行化 acquire/complete/fail/heartbeat 的「读-改-写」，避免并发
        # 同 key（如 LLM 重发 dup tool_call.id 经 gather）的 TOCTOU 互斥失效。
        # 仅进程内有效；跨进程共享同一 ledger 目录须 OS 级文件锁兜底。
        self._lock = asyncio.Lock()
        # 跨进程文件锁开关（经 EngineContainer.enable_file_locks 注入，V2）。
        self._enable_locks: bool = False

    # ── 公开 API ─────────────────────────────────────────────────

    async def acquire(
        self,
        key: str,
        *,
        scope: str = "",
        lease_seconds: int = 120,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> LedgerClaim:
        """尝试占用一个幂等键。

        短路规则（返回 acquired=False）：
        - 该键已 COMPLETED → ``already completed``（幂等命中，不应重复执行）；
        - 该键 RUNNING 且租约未过期 → ``lease active``（并发重复，应放弃）。

        否则（无记录 / 已失败 / 租约已过期）→ 置 RUNNING、设新租约、返回 acquired=True。
        """
        async with self._lock:
            existing = await self.get(key)
            if existing is not None:
                if existing.status == ExecutionStatus.COMPLETED:
                    return LedgerClaim(acquired=False, reason="already completed", record=existing)
                if existing.status == ExecutionStatus.RUNNING and self._is_lease_active(existing):
                    return LedgerClaim(acquired=False, reason="lease active", record=existing)
                record = existing.model_copy(deep=True)
            else:
                record = ExecutionRecord(key=key, scope=scope)

            now = iso_now()
            record.scope = scope
            record.status = ExecutionStatus.RUNNING
            record.run_id = run_id
            record.started_at = now
            record.updated_at = now
            record.finished_at = None
            record.error = None
            record.metadata = dict(metadata or {})
            record.lease_expires_at = _lease_deadline(lease_seconds)
            await self._save(record)
            return LedgerClaim(acquired=True, record=record)

    async def complete(
        self,
        key: str,
        *,
        metadata: dict[str, Any] | None = None,
        recreate_if_missing: bool = False,
    ) -> ExecutionRecord:
        """标记一个键为 COMPLETED（幂等短路的最终态）。

        仅在记录已存在且状态为 RUNNING 时操作（P1-8 修复：防止误调 complete("wrong_key")
        凭空创建记录，导致该 key 被永久阻塞）——**该严格语义是默认行为**。

        ``recreate_if_missing=True`` 时开一档**容错完成**，仅供工具调用这条链路使用
        （``agent/tool_execution._record_ledger_outcome``）：记录若在工具在途期间被别的
        进程 prune 掉（长时调用跑超租约、crash 后租约过期被清），就按「本次执行确实完成了」
        重建为 COMPLETED——否则模型重发同一 ``tool_call.id`` 时会**重复执行有副作用的工具**，
        幂等缓存的意义就没了。同为已 COMPLETED 的记录也算幂等命中（不报错）。
        两种容错都可在日志中观察到（重建记 warning，已 COMPLETED 幂等命中记 debug）。
        """
        async with self._lock:
            record = await self.get(key)
            if record is None:
                if not recreate_if_missing:
                    raise ValueError(await self._missing_record_message("complete", key))
                now = iso_now()
                logger.warning(
                    "ledger record %r vanished before completion; recreating as COMPLETED to keep idempotency",
                    key,
                )
                record = ExecutionRecord(
                    key=key,
                    status=ExecutionStatus.COMPLETED,
                    metadata=dict(metadata or {}),
                    started_at=now,
                    updated_at=now,
                    finished_at=now,
                )
                await self._save(record)
                return record
            if record.status == ExecutionStatus.COMPLETED and recreate_if_missing:
                logger.debug("ledger record %r already COMPLETED; treating as idempotent", key)
                return record
            if record.status != ExecutionStatus.RUNNING:
                raise RuntimeError(f"Cannot complete key {key!r}: current status is {record.status.value}")
            record.status = ExecutionStatus.COMPLETED
            record.updated_at = iso_now()
            record.finished_at = record.updated_at
            record.lease_expires_at = None
            if metadata is not None:
                record.metadata = dict(metadata)
            await self._save(record)
            return record

    async def fail(self, key: str, error: str, *, metadata: dict[str, Any] | None = None) -> ExecutionRecord:
        """标记一个键为 FAILED 并记录错误（FAILED 可被后续 acquire 重新占用）。

        仅在记录已存在时操作；不存在则抛错（P1-8 修复：防止凭空创建记录）。
        """
        async with self._lock:
            record = await self.get(key)
            if record is None:
                raise ValueError(await self._missing_record_message("fail", key))
            record.status = ExecutionStatus.FAILED
            record.updated_at = iso_now()
            record.finished_at = record.updated_at
            record.lease_expires_at = None
            record.error = error
            if metadata is not None:
                record.metadata = dict(metadata)
            await self._save(record)
            return record

    async def heartbeat(self, key: str, *, lease_seconds: int = 120) -> ExecutionRecord | None:
        """为进行中的记录续租；非 RUNNING（已完成 / 失败 / 不存在）返回 None。

        唯一调用方是工具在途续租（``agent/tool_execution._renew_ledger_lease``）：返回
        ``None`` 即「无需再续租」（记录已终态或被 prune 清掉），调用方应停止续租但不能
        据此判定工具失败——账本只是幂等缓存。
        """
        async with self._lock:
            record = await self.get(key)
            if record is None or record.status != ExecutionStatus.RUNNING:
                return None
            record.updated_at = iso_now()
            record.lease_expires_at = _lease_deadline(lease_seconds)
            await self._save(record)
            return record

    async def get(self, key: str) -> ExecutionRecord | None:
        """按幂等键加载一条记录；不存在或损坏则返回 None。"""
        return await asyncio.to_thread(load_json_model, self._path(key), ExecutionRecord)

    async def _missing_record_message(self, action: str, key: str) -> str:
        """``complete``/``fail`` 找不到记录时的错误文案——区分「真不存在」与「存在但读不出来」。

        后者（文件在、但 JSON 损坏 / 被截断）原先会被报成 ``non-existent key``，把一条
        可诊断的 I/O 事故伪装成「键写错了」（2026-09-15 排障时踩到）。文件存在即如实说明。
        """
        exists = await asyncio.to_thread(self._path(key).exists)
        if exists:
            return f"Cannot {action} key {key!r}: record exists but is unreadable (corrupt JSON?)"
        return f"Cannot {action} non-existent key: {key!r}"

    async def list_records(self) -> list[ExecutionRecord]:
        """返回全部已知记录（按 (scope, key) 排序）；损坏文件跳过不中断。

        P1-23 加固：逐文件 try/except + >500 条时输出进度日志（防假死）。
        """
        if not await asyncio.to_thread(self._base.exists):
            return []
        paths = await asyncio.to_thread(lambda: list(self._base.glob("*.json")))
        total = len(paths)
        records: list[ExecutionRecord] = []
        for i, path in enumerate(paths):
            if i > 0 and i % _PRUNE_PROGRESS_INTERVAL == 0:
                logger.info("list_records: scanned %d/%d files, %d valid so far", i, total, len(records))
            try:
                record = await asyncio.to_thread(load_json_model, path, ExecutionRecord)
            except Exception:
                logger.debug("list_records: unhandled error on %s; skipping", path, exc_info=True)
                continue
            if record is not None:
                records.append(record)
        if total >= _PRUNE_PROGRESS_INTERVAL:
            logger.info("list_records: done — %d valid out of %d files", len(records), total)
        return sorted(records, key=lambda r: (r.scope, r.key))

    # ── 内部 ─────────────────────────────────────────────────────

    async def _save(self, record: ExecutionRecord) -> None:
        """把一条记录原子写到磁盘（tmp + os.replace，防崩溃留半截）。"""
        payload = record.model_dump(mode="json")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        await asyncio.to_thread(atomic_write_text, self._path(record.key), text, lock=self._enable_locks)

    def _path(self, key: str) -> Path:
        """幂等键 → 文件路径：用 sha1(key) 命名，规避 key 中的路径分隔符 / 特殊字符。"""
        # usedforsecurity=False：本哈希只用于「幂等键 → 文件名」的命名（非安全用途），
        # 如实标注可让 Bandit B324 放行，并规避 FIPS 模式下 SHA1 被禁导致的落盘失败。
        digest = hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()
        return self._base / f"{digest}.json"

    @staticmethod
    def _is_lease_active(record: ExecutionRecord) -> bool:
        """租约是否仍有效（RUNNING 且租约未过期）。

        比对前统一经 ``_parse_iso_to_naive`` 去 tzinfo——存储来源混用 naive/aware，
        Python 禁止混比（TypeError）。
        """
        if not record.lease_expires_at:
            return True  # 无租约视为永久有效
        return _parse_iso_to_naive(record.lease_expires_at) > datetime.now(tz=UTC).replace(tzinfo=None)

    # ── prune（轻量文件路径直走，不 load 全量 Pydantic）─────────

    async def prune(self, *, retention_days: int, before: datetime | None = None, min_interval_seconds: int = 0) -> int:
        """删除过期记录，返回删除数。``retention_days <= 0`` 时直接返回 0（禁用清理）。

        ``min_interval_seconds > 0`` 时加一层**跨进程节流**（见 ``persist.stamp_is_recent``）：
        距上次清理不足该间隔直接返回 0，避免每次 CLI 启动重扫万级目录。

        删除：``COMPLETED``/``FAILED`` 中 ``finished_at`` 早于 cutoff 的终态死记录，
        以及 ``RUNNING`` 且租约已过期的孤儿。**在途记录能存活的前提是有调用方周期续租**
        （``agent/tool_execution._renew_ledger_lease`` 覆盖工具在途；无续租的长任务
        跑超 ``lease_seconds`` 后仍会被判为孤儿——这是有意取舍，见 :meth:`heartbeat`）。
        保留：未过期 ``RUNNING``（在途，防误删导致重复执行副作用工具）。

        P1-23 重写：不再经 ``list_records``（7152 次 Pydantic ``model_validate``），
        改为轻量 ``json.loads`` 只取 ``status``/``finished_at``/``lease_expires_at`` 判定过期性。
        单条 JSON 解析 / 删除失败不中断整批。

        万级文件性能（2026-09-15）：扫描、判定、删除各占**一次**线程跳转
        （``persist.scan_dir`` + ``_is_path_stale`` + ``_delete_stale``）。旧实现逐条
        ``await asyncio.to_thread(...)``（2 万条 ≈ 4 万次跳转）+ 在协程里直接 ``read_text``
        阻塞事件循环，实测单次 prune 9.7s → 现约 1s 量级。
        """
        if retention_days <= 0:
            return 0
        stamp = prune_stamp_path(self._base)
        if await asyncio.to_thread(stamp_is_recent, stamp, min_interval_seconds):
            return 0
        cutoff = before if before is not None else datetime.now(tz=UTC) - timedelta(days=retention_days)
        cutoff_naive = cutoff.replace(tzinfo=None)

        if not await asyncio.to_thread(self._base.exists):
            return 0
        entries = await asyncio.to_thread(scan_dir, self._base)
        paths = [e.path for e in entries if not e.is_dir and e.path.name.endswith(".json")]
        total = len(paths)

        # 判定与删除各占**一次**线程跳转（不在事件循环里阻塞、也不逐条起线程）：
        # 逐条 `await asyncio.to_thread(...)` 在万级文件下仅线程跳转就要数秒（实测 2 万条 9.7s），
        # 且旧实现把 `read_text` 直接放在协程里，会阻塞整个事件循环。
        stale = [path for i, path in enumerate(paths) if _is_path_stale(path, cutoff_naive, index=i, total=total)]
        deleted = await asyncio.to_thread(_delete_stale, stale)
        await asyncio.to_thread(touch_prune_stamp, stamp)
        if total >= _PRUNE_PROGRESS_INTERVAL:
            logger.info("ledger prune: done — deleted %d stale of %d files", deleted, total)
        return deleted


def _is_path_stale(path: Path, cutoff_naive: datetime, *, index: int = 0, total: int = 0) -> bool:
    """轻量判定一个 ledger 文件是否过期可删（**同步**，由 :meth:`ExecutionLedger.prune` 批量调用）。

    不实例化 ``ExecutionRecord``——只做 ``json.loads`` 取必需字段。JSON 解析 / 日期解析
    失败视为不可删（保守保留）。``cutoff_naive`` 已去除 tzinfo，可直接比较。
    设计成同步函数是为了让它整批跑在**一个**工作线程里（逐条 ``to_thread`` 的跳转成本
    在万级文件下远高于解析本身）。
    """
    if index > 0 and index % _PRUNE_PROGRESS_INTERVAL == 0:
        logger.info("ledger prune: scanned %d/%d files", index, total)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False

    status = data.get("status", "")
    if status == "running":
        lease_raw = data.get("lease_expires_at")
        if not lease_raw:
            return False
        try:
            now_naive = datetime.now(tz=UTC).replace(tzinfo=None)
            return _parse_iso_to_naive(lease_raw) <= now_naive
        except (ValueError, TypeError):
            return False

    if status in ("completed", "failed"):
        finished_raw = data.get("finished_at")
        if not finished_raw:
            return False
        try:
            return _parse_iso_to_naive(finished_raw) <= cutoff_naive
        except (ValueError, TypeError):
            return False

    # 未知 status → 保守保留
    return False


def _delete_stale(paths: list[Path]) -> int:
    """批量删除判定过期的 ledger 记录（**同步**，批量调用），返回删除数。

    随记录一并清理配套 ``.lock``（``persist.py`` 保留 .lock 以规避 unlink 竞态，此处是
    唯一合法的清理时机：记录已判为过期删除，其锁文件不再有等待者）；锁文件删除失败只记
    ``debug``（不计入返回值——与保留期语义无关）。
    """
    deleted = 0
    for path in paths:
        try:
            path.unlink()
            deleted += 1
        except FileNotFoundError:
            continue  # 竞态下已被删：不计入，也不算失败
        except OSError:
            logger.debug("ledger prune: unlink failed on %s; continuing", path, exc_info=True)
            continue
        lock_path = path.with_name(path.name + ".lock")
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("ledger prune: lock file cleanup failed on %s", lock_path, exc_info=True)
    return deleted
