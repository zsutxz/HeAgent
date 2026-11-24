"""由单一显式 HeAgent 工作区根派生的规范路径。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


class WorkspacePaths(BaseModel):
    """一个项目的全部持久运行时路径，由 ``root`` 派生。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: Path

    @field_validator("root", mode="before")
    @classmethod
    def _resolve_root(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    @classmethod
    def from_root(cls, root: str | Path) -> WorkspacePaths:
        """由工作区根构造路径对象；只做字符串拼接，不建目录、不做 IO。"""
        return cls(root=Path(root))

    @property
    def state_dir(self) -> Path:
        """状态根 `<root>/.heagent`：所有运行产物都在它下面，便于整体清理与备份。"""
        return self.root / ".heagent"

    @property
    def sessions(self) -> Path:
        """会话 JSON 目录（每个会话一个文件）。"""
        return self.state_dir / "sessions"

    @property
    def skills(self) -> Path:
        """项目级技能根；全局根 `~/.heagent/skills` 同名时优先于这里。"""
        return self.state_dir / "skills"

    @property
    def memory_file(self) -> Path:
        """长期记忆 `MEMORY.md` 的位置。"""
        return self.state_dir / "memory/MEMORY.md"

    @property
    def profile_file(self) -> Path:
        """用户画像 `USER.md` 的位置。"""
        return self.state_dir / "user/USER.md"

    @property
    def cron_file(self) -> Path:
        """cron 作业定义 `jobs.json` 的位置。"""
        return self.state_dir / "cron/jobs.json"

    @property
    def runs(self) -> Path:
        """run 快照目录（每个 run 一个 JSON，runtime_stats 的数据源之一）。"""
        return self.state_dir / "runs"

    @property
    def ledger(self) -> Path:
        """幂等账本目录（键的 sha1 作文件名，防同一工作被执行两次）。"""
        return self.state_dir / "ledger"

    @property
    def checkpoints(self) -> Path:
        """工作流检查点目录（步骤级断点续跑用）。"""
        return self.state_dir / "checkpoints"

    @property
    def sandboxes(self) -> Path:
        """沙箱会话状态目录（容器名/句柄等跨调用状态）。"""
        return self.state_dir / "sandboxes"

    @property
    def edit_snapshots(self) -> Path:
        """编辑快照目录（写文件前的留底，误改后悔药）。"""
        return self.state_dir / "tmp/edit-snapshots"

    @property
    def console_dir(self) -> Path:
        """网页控制台状态目录（审计、项目登记、配置备份索引都在其下）。"""
        return self.state_dir / "console"

    @property
    def env_file(self) -> Path:
        """项目级 ``.env`` —— 配置写入通道**唯一**的目的地（I4：全局 ``~/.heagent/.env`` 永久只读）。"""
        return self.root / ".env"

    @property
    def config_backups(self) -> Path:
        """配置写入前的备份目录（时间戳 + 指纹前缀）。"""
        return self.state_dir / "backups"

    @property
    def projects_file(self) -> Path:
        """网页控制台的项目登记表 `projects.json`。"""
        return self.state_dir / "console/projects.json"
