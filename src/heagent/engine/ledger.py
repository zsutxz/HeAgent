"""Idempotency and lease ledger for scheduled or long-running work."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from heagent.engine.context import iso_now


class ExecutionStatus(StrEnum):
    """Execution state stored in the ledger."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionRecord(BaseModel):
    """Persisted execution record keyed by idempotency key."""

    key: str
    scope: str = ""
    status: ExecutionStatus = ExecutionStatus.RUNNING
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: str = Field(default_factory=iso_now)
    updated_at: str = Field(default_factory=iso_now)
    finished_at: str | None = None
    lease_expires_at: str | None = None
    error: str | None = None


class LedgerClaim(BaseModel):
    """Result of trying to acquire one execution key."""

    acquired: bool
    reason: str = ""
    record: ExecutionRecord


class ExecutionLedger:
    """JSON-backed ledger that prevents duplicate execution."""

    def __init__(self, base_dir: str = ".heagent/ledger") -> None:
        self._base = Path(base_dir)

    def acquire(
        self,
        key: str,
        *,
        scope: str = "",
        lease_seconds: int = 120,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> LedgerClaim:
        """Acquire a key if it is not already completed or actively leased."""
        existing = self.get(key)
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
        self._save(record)
        return LedgerClaim(acquired=True, record=record)

    def complete(self, key: str, *, metadata: dict[str, Any] | None = None) -> ExecutionRecord:
        """Mark a key as completed."""
        record = self.get(key) or ExecutionRecord(key=key)
        record.status = ExecutionStatus.COMPLETED
        record.updated_at = iso_now()
        record.finished_at = record.updated_at
        record.lease_expires_at = None
        if metadata is not None:
            record.metadata = dict(metadata)
        self._save(record)
        return record

    def fail(self, key: str, error: str, *, metadata: dict[str, Any] | None = None) -> ExecutionRecord:
        """Mark a key as failed."""
        record = self.get(key) or ExecutionRecord(key=key)
        record.status = ExecutionStatus.FAILED
        record.updated_at = iso_now()
        record.finished_at = record.updated_at
        record.lease_expires_at = None
        record.error = error
        if metadata is not None:
            record.metadata = dict(metadata)
        self._save(record)
        return record

    def heartbeat(self, key: str, *, lease_seconds: int = 120) -> ExecutionRecord | None:
        """Extend the lease of a running record."""
        record = self.get(key)
        if record is None or record.status != ExecutionStatus.RUNNING:
            return None
        record.updated_at = iso_now()
        record.lease_expires_at = (datetime.now() + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        self._save(record)
        return record

    def get(self, key: str) -> ExecutionRecord | None:
        """Load one record by idempotency key."""
        path = self._path(key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ExecutionRecord.model_validate(payload)

    def list_records(self) -> list[ExecutionRecord]:
        """Return all known records."""
        if not self._base.exists():
            return []
        records: list[ExecutionRecord] = []
        for path in self._base.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            records.append(ExecutionRecord.model_validate(payload))
        return sorted(records, key=lambda r: (r.scope, r.key))

    def _save(self, record: ExecutionRecord) -> None:
        self._base.mkdir(parents=True, exist_ok=True)
        payload = record.model_dump(mode="json")
        self._path(record.key).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self._base / f"{digest}.json"

    @staticmethod
    def _is_expired(record: ExecutionRecord) -> bool:
        if not record.lease_expires_at:
            return False
        return datetime.fromisoformat(record.lease_expires_at) <= datetime.now()
