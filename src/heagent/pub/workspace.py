"""Canonical paths derived from one explicit HeAgent workspace root."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


class WorkspacePaths(BaseModel):
    """All durable runtime paths for a project, derived from ``root``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: Path

    @field_validator("root", mode="before")
    @classmethod
    def _resolve_root(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    @classmethod
    def from_root(cls, root: str | Path) -> WorkspacePaths:
        return cls(root=Path(root))

    @property
    def state_dir(self) -> Path:
        return self.root / ".heagent"

    @property
    def sessions(self) -> Path:
        return self.state_dir / "sessions"

    @property
    def skills(self) -> Path:
        return self.state_dir / "skills"

    @property
    def memory_file(self) -> Path:
        return self.state_dir / "memory/MEMORY.md"

    @property
    def profile_file(self) -> Path:
        return self.state_dir / "user/USER.md"

    @property
    def cron_file(self) -> Path:
        return self.state_dir / "cron/jobs.json"

    @property
    def runs(self) -> Path:
        return self.state_dir / "runs"

    @property
    def ledger(self) -> Path:
        return self.state_dir / "ledger"

    @property
    def checkpoints(self) -> Path:
        return self.state_dir / "checkpoints"

    @property
    def sandboxes(self) -> Path:
        return self.state_dir / "sandboxes"

    @property
    def edit_snapshots(self) -> Path:
        return self.state_dir / "tmp/edit-snapshots"

    @property
    def console_dir(self) -> Path:
        return self.state_dir / "console"

    @property
    def env_file(self) -> Path:
        """项目级 ``.env`` —— 配置写入通道**唯一**的目的地（I4：全局 ``~/.heagent/.env`` 永久只读）。"""
        return self.root / ".env"

    @property
    def config_backups(self) -> Path:
        return self.state_dir / "backups"

    @property
    def projects_file(self) -> Path:
        return self.state_dir / "console/projects.json"
