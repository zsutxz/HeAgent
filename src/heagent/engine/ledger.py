"""调度 / 长时任务的幂等与租约账本（ledger）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``ExecutionLedger`` 以
**幂等键**为粒度防止同一工作被重复执行，并把进行中的执行以**租约**（lease）占位，避免并发
重复。记录写到 ``.heagent/ledger/<sha1(key)>.json``。

两类使用场景：

- **AgentLoop._execute_one**（P4）：key = ``run_id:call.id``。在 window_reset（上下文压缩）
  后模型可能重发相同 ``tool_call.id``；账本使 COMPLETED 的调用短路返回缓存、避免重复执行。
- **cron 调度**：key = ``cron:{job_id}:{分钟时间戳}``，经 acquire / complete / fail 防同一
  逻辑分钟的 job 被重复执行（租约靠 ``lease_seconds`` 设足覆盖执行）。``heartbeat`` 为
  预留续租接口，当前无调用方——上层自定义长时 job_runner 跑超租约任务时可周期续租。

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
from heagent.engine.persist import atomic_write_text, load_json_model

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
            record.lease_expires_at = (datetime.now(tz=UTC) + timedelta(seconds=lease_seconds)).isoformat(
                timespec="seconds"
            )
            await self._save(record)
            return LedgerClaim(acquired=True, record=record)

    async def complete(self, key: str, *, metadata: dict[str, Any] | None = None) -> ExecutionRecord:
        """标记一个键为 COMPLETED（幂等短路的最终态）。

        仅在记录已存在且状态为 RUNNING 时操作（P1-8 修复：防止误调 complete("wrong_key")
        凭空创建记录，导致该 key 被永久阻塞）。
        """
        async with self._lock:
            record = await self.get(key)
            if record is None:
                raise ValueError(f"Cannot complete non-existent key: {key!r}")
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
                raise ValueError(f"Cannot fail non-existent key: {key!r}")
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
        """为进行中的记录续租；非 RUNNING（已完成 / 失败 / 不存在）返回 None。"""
        async with self._lock:
            record = await self.get(key)
            if record is None or record.status != ExecutionStatus.RUNNING:
                return None
            record.updated_at = iso_now()
            record.lease_expires_at = (datetime.now(tz=UTC) + timedelta(seconds=lease_seconds)).isoformat(
                timespec="seconds"
            )
            await self._save(record)
            return record

    async def get(self, key: str) -> ExecutionRecord | None:
        """按幂等键加载一条记录；不存在或损坏则返回 None。"""
        return await asyncio.to_thread(load_json_model, self._path(key), ExecutionRecord)

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
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
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

    async def prune(self, *, retention_days: int, before: datetime | None = None) -> int:
        """删除过期记录，返回删除数。``retention_days <= 0`` 时直接返回 0（禁用清理）。

        删除：``COMPLETED``/``FAILED`` 中 ``finished_at`` 早于 cutoff 的终态死记录，
        以及 ``RUNNING`` 且租约已过期的孤儿（``heartbeat`` 无调用方，过期即死）。
        保留：未过期 ``RUNNING``（在途，防误删导致重复执行副作用工具）。

        P1-23 重写：不再经 ``list_records``（7152 次 Pydantic ``model_validate``），
        改为直接 glob → 逐文件轻量 ``json.loads`` 取 ``status``/``finished_at``/
        ``lease_expires_at`` 判定过期性，大幅降低 prune 启动成本。
        单条 JSON 解析 / 删除失败不中断整批。
        """
        if retention_days <= 0:
            return 0
        cutoff = before if before is not None else datetime.now(tz=UTC) - timedelta(days=retention_days)
        cutoff_naive = cutoff.replace(tzinfo=None)

        if not await asyncio.to_thread(self._base.exists):
            return 0
        paths = await asyncio.to_thread(lambda: list(self._base.glob("*.json")))
        total = len(paths)
        deleted = 0

        for i, path in enumerate(paths):
            if i > 0 and i % _PRUNE_PROGRESS_INTERVAL == 0:
                logger.info("ledger prune: scanned %d/%d files, deleted %d so far", i, total, deleted)
            try:
                if not await self._is_path_stale(path, cutoff_naive):
                    continue
            except Exception:
                logger.debug("ledger prune: staleness check failed on %s; skipping", path, exc_info=True)
                continue
            try:
                if await asyncio.to_thread(path.exists):
                    await asyncio.to_thread(path.unlink)
                    deleted += 1
            except Exception:
                logger.debug("ledger prune: unlink failed on %s; continuing", path, exc_info=True)

        if total >= _PRUNE_PROGRESS_INTERVAL:
            logger.info("ledger prune: done — deleted %d stale of %d files", deleted, total)
        return deleted

    async def _is_path_stale(self, path: Path, cutoff_naive: datetime) -> bool:
        """轻量判定一个 ledger 文件是否过期可删。

        不实例化 ``ExecutionRecord``——只做 ``json.loads`` 取必需字段。
        JSON 解析 / 日期解析失败视为不可删（保守保留）。
        ``cutoff_naive`` 已去除 tzinfo，可直接比较。
        """
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
