"""CronJob 模型与持久化 — 定时任务的定义和 JSON 文件存储。

遵循与 SessionStore 相同的 JSON 持久化模式。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ValidationError

from heagent.pub.persist import atomic_write_text

logger = logging.getLogger(__name__)


class CronRunStatus(StrEnum):
    """``CronJob.last_status`` 的**落盘值域**——只有这三个会被写入 ``jobs.json``。

    只描述「一次执行到哪一步」，不描述「有没有到过」：从未执行是 ``last_status is None``，
    展示侧的完整状态（never / unknown / interrupted 等）由
    :mod:`heagent.cron.status` 依时间戳派生，不回写本字段。
    """

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class CronJob(BaseModel):
    """定时任务定义。

    所有执行状态字段都是**可选**：旧版 ``jobs.json`` 缺这些键时照常加载（缺 = 未记录），
    新版文件被旧版读取时多出的键被忽略（pydantic 默认 ``extra="ignore"``）。
    """

    id: str  # 唯一标识符
    prompt: str  # 要执行的任务提示词
    cron: str  # 5-field cron 表达式
    recurring: bool = True  # True=循环，False=一次性
    created: str  # ISO 时间戳
    last_run: str | None = None  # 上次执行**结束**时间（UTC ISO）
    enabled: bool = True
    # ``CronRunStatus`` 的值；用 ``str`` 而非枚举类型是为了容错——未知取值（手改/未来版本）
    # 只让「状态展示」降级成 unknown，不得让整条 job 被当成损坏条目丢弃。
    last_status: str | None = None  # running / success / failed
    last_started: str | None = None  # 最近一次执行**开始**时间（UTC ISO，判「卡住的 running」）
    last_success: str | None = None  # 最近一次成功时间（UTC ISO）
    last_error: str | None = None  # 最近一次失败的「异常类型: 首行消息」（成功即清空）


class JobStore:
    """JSON 文件持久化的定时任务存储。"""

    def __init__(self, path: str = ".heagent/cron/jobs.json") -> None:
        self._path = Path(path)
        self._corruption_count: int = 0  # 最近一次 _load_all 跳过的损坏条目数

    @property
    def corruption_count(self) -> int:
        """最近一次加载时跳过的损坏/非法条目数（供 cron_list 等工具展示提示）。"""
        return self._corruption_count

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
        """从 JSON 文件加载所有任务。

        损坏的 JSON 或字段不匹配的条目会被跳过并记录警告——避免整个 tick 因一条
        损坏数据而跳过所有 job（参见 scheduler._check_and_execute 的调用链）。

        P0-3：累加 _corruption_count 供 cron_list 等工具向用户提示损坏条目数。
        """
        self._corruption_count = 0  # 每次加载重置计数
        if not self._path.exists():
            return []
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Failed to read cron jobs file; returning empty list", exc_info=True)
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Corrupted cron jobs JSON; returning empty list", exc_info=True)
            self._corruption_count = -1  # 特殊值：整个文件损坏
            return []
        if not isinstance(data, list):
            logger.warning("Cron jobs JSON is not a list; returning empty list")
            self._corruption_count = -1
            return []
        jobs: list[CronJob] = []
        for j in data:
            if not isinstance(j, dict):
                # 顶层是列表但元素不是对象（手改文件 / 写坏的 JSON）：按损坏条目计数，
                # 不当成致命错误——否则一次读状态就把整个 jobs 面拖崩。
                logger.warning("Skipping non-object cron job entry: %r", j)
                self._corruption_count += 1
                continue
            try:
                jobs.append(CronJob(**j))
            except ValidationError:
                logger.warning("Skipping invalid cron job entry: %s", j)
                self._corruption_count += 1
        return jobs

    def _save_all(self, jobs: list[CronJob]) -> None:
        """将所有任务保存到 JSON 文件（原子写，防崩溃中途截断 JSON）。"""
        data = [j.model_dump() for j in jobs]
        atomic_write_text(self._path, json.dumps(data, ensure_ascii=False, indent=2))


def _iso_now() -> str:
    """当前时间的 UTC ISO-8601 格式字符串（无时区后缀，分钟精度）。

    P0-1 修复：此前 jobs.py 用本地时间（time.strftime）、scheduler.py 用 UTC
    （datetime.now(tz=UTC)），同一 job 的 created 和 last_run 差 8 小时且均无
    时区标记，格式相同无法区分语义。现统一为 UTC 单一真源，调度器从本模块导入。
    """
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
