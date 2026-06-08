"""CronJob 模型与持久化 — 定时任务的定义和 JSON 文件存储。

遵循与 SessionStore 相同的 JSON 持久化模式。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from pydantic import BaseModel


class CronJob(BaseModel):
    """定时任务定义。"""

    id: str                          # 唯一标识符
    prompt: str                      # 要执行的任务提示词
    cron: str                        # 5-field cron 表达式
    recurring: bool = True           # True=循环，False=一次性
    created: str                     # ISO 时间戳
    last_run: str | None = None      # 上次执行时间
    enabled: bool = True


class JobStore:
    """JSON 文件持久化的定时任务存储。"""

    def __init__(self, path: str = ".heagent/cron/jobs.json") -> None:
        self._path = Path(path)

    def add(self, job: CronJob) -> None:
        """添加一个定时任务。"""
        jobs = self._load_all()
        jobs.append(job)
        self._save_all(jobs)

    def remove(self, job_id: str) -> bool:
        """删除指定任务。返回是否成功删除。"""
        jobs = self._load_all()
        before = len(jobs)
        jobs = [j for j in jobs if j.id != job_id]
        if len(jobs) < before:
            self._save_all(jobs)
            return True
        return False

    def list_jobs(self) -> list[CronJob]:
        """返回所有任务。"""
        return self._load_all()

    def get(self, job_id: str) -> CronJob | None:
        """按 ID 查找任务。"""
        for job in self._load_all():
            if job.id == job_id:
                return job
        return None

    def update(self, job_id: str, **fields: object) -> bool:
        """更新指定任务的字段。返回是否找到并更新。"""
        jobs = self._load_all()
        for i, job in enumerate(jobs):
            if job.id == job_id:
                updated = job.model_copy(update=fields)
                jobs[i] = updated
                self._save_all(jobs)
                return True
        return False

    def create_job(self, prompt: str, cron: str, *, recurring: bool = True) -> CronJob:
        """工厂方法：创建新 CronJob 实例。"""
        return CronJob(
            id=uuid.uuid4().hex[:8],
            prompt=prompt,
            cron=cron,
            recurring=recurring,
            created=_iso_now(),
        )

    # ---- 内部方法 ----

    def _load_all(self) -> list[CronJob]:
        """从 JSON 文件加载所有任务。"""
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return [CronJob(**j) for j in data]

    def _save_all(self, jobs: list[CronJob]) -> None:
        """将所有任务保存到 JSON 文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [j.model_dump() for j in jobs]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _iso_now() -> str:
    """当前时间的 ISO 格式字符串。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S")
