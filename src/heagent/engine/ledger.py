"""调度 / 长时任务的幂等与租约账本（ledger）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``ExecutionLedger`` 以
**幂等键**为粒度防止同一工作被重复执行，并把进行中的执行以**租约**（lease）占位，避免并发
重复。记录写到 ``.heagent/ledger/<sha1(key)>.json``。

两类使用场景：

- **AgentLoop._execute_one**（P4）：key = ``run_id:call.id``。在 window_reset（上下文压缩）
  后模型可能重发相同 ``tool_call.id``；账本使 COMPLETED 的调用短路返回缓存、避免重复执行。
- **cron 等长时任务**：经 acquire / heartbeat / complete / fail 管理跨周期执行状态。

记录不做自动清理（清理策略交给上层调度器或外部维护脚本决策）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from heagent.engine.context import iso_now
from heagent.engine.persist import atomic_write_text, load_json_model


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


class ExecutionLedger:
    """JSON 文件后端、防重复执行的幂等账本。"""

    def __init__(self, base_dir: str = ".heagent/ledger") -> None:
        # 账本根目录；按需在 _save() 时创建。
        self._base = Path(base_dir)
        # 进程内互斥：串行化 acquire/complete/fail/heartbeat 的「读-改-写」，避免并发
        # 同 key（如 LLM 重发 dup tool_call.id 经 gather）的 TOCTOU 互斥失效。
        # 仅进程内有效；跨进程共享同一 ledger 目录须 OS 级文件锁兜底。
        self._lock = asyncio.Lock()

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
                if existing.status == ExecutionStatus.RUNNING and not self._is_expired(existing):
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
            record.lease_expires_at = (datetime.now() + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
            await self._save(record)
            return LedgerClaim(acquired=True, record=record)

    async def complete(self, key: str, *, metadata: dict[str, Any] | None = None) -> ExecutionRecord:
        """标记一个键为 COMPLETED（幂等短路的最终态）。无记录时自动创建。"""
        async with self._lock:
            record = await self.get(key) or ExecutionRecord(key=key)
            record.status = ExecutionStatus.COMPLETED
            record.updated_at = iso_now()
            record.finished_at = record.updated_at
            record.lease_expires_at = None
            if metadata is not None:
                record.metadata = dict(metadata)
            await self._save(record)
            return record

    async def fail(self, key: str, error: str, *, metadata: dict[str, Any] | None = None) -> ExecutionRecord:
        """标记一个键为 FAILED 并记录错误（FAILED 可被后续 acquire 重新占用）。"""
        async with self._lock:
            record = await self.get(key) or ExecutionRecord(key=key)
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
            record.lease_expires_at = (datetime.now() + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
            await self._save(record)
            return record

    async def get(self, key: str) -> ExecutionRecord | None:
        """按幂等键加载一条记录；不存在或损坏则返回 None。"""
        return await asyncio.to_thread(load_json_model, self._path(key), ExecutionRecord)

    async def list_records(self) -> list[ExecutionRecord]:
        """返回全部已知记录（按 (scope, key) 排序）；损坏文件跳过不中断。"""
        if not await asyncio.to_thread(self._base.exists):
            return []
        paths = await asyncio.to_thread(lambda: list(self._base.glob("*.json")))
        records: list[ExecutionRecord] = []
        for path in paths:
            record = await asyncio.to_thread(load_json_model, path, ExecutionRecord)
            if record is not None:
                records.append(record)
        return sorted(records, key=lambda r: (r.scope, r.key))

    async def _save(self, record: ExecutionRecord) -> None:
        """把一条记录原子写到磁盘（tmp + os.replace，防崩溃留半截）。"""
        payload = record.model_dump(mode="json")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        await asyncio.to_thread(atomic_write_text, self._path(record.key), text)

    def _path(self, key: str) -> Path:
        """幂等键 → 文件路径：用 sha1(key) 命名，规避 key 中的路径分隔符 / 特殊字符。"""
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self._base / f"{digest}.json"

    @staticmethod
    def _is_expired(record: ExecutionRecord) -> bool:
        """该 RUNNING 记录的租约是否已过期（无租约视为未过期）。"""
        if not record.lease_expires_at:
            return False
        return datetime.fromisoformat(record.lease_expires_at) <= datetime.now()
