"""后台任务进度的进程内注册表（四态 + 单调百分比 + 终态短保留）。

用途：让「后台还在做的事」（当前生产者 = 上下文压缩）对查询方可见，且查询**只读内存**——
一次查询是一次 dict 迭代 + 定长模型序列化，不做磁盘扫描、不做 ``await``，因此端点耗时与
任务规模无关（毫秒级）。

四条不变量：

- **状态机单向**：``pending → running → completed | failed``。终态不可回到 ``running``，
  :meth:`TaskRegistry.report` 对终态任务是 no-op——已收尾的进度不会被迟到的上报改回「进行中」。
- **percent 单调不减**：上报值先夹到 ``0..100`` 再与当前值取 ``max``；``fail`` 保留末次 percent
  （失败不等于「走完了 100%」）。
- **终态短保留**：终态条目按 ``retention_seconds``（TTL，自 ``updated_at`` 起算）与
  ``max_finished``（只留最近 N 条）淘汰，淘汰发生在读取/收尾时的 :meth:`TaskRegistry.prune`；
  **在途任务永不被淘汰**（淘汰在途会让「查询正在跑的任务」变成 404）。
- **单写者模型**：注册表是进程内、事件循环单线程使用；所有方法同步、内部无 ``await``，
  因此每次状态更新对读者是原子的，不需要锁。

跨模块边界：本模块只依赖标准库与 Pydantic，**不导入** ``network/``（网络层用
``endpoints_tasks.RegistryTaskSource`` 适配，方向是入口层注入而非引擎反向依赖）。
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from heagent.pub.persist import atomic_write_text

logger = logging.getLogger(__name__)

# 字段上界：任务由本仓生产者创建，长度只用来兜住「有人把整段 prompt 当 message 传进来」。
MAX_TASK_ID_CHARS = 64
MAX_TASK_KIND_CHARS = 32
MAX_TASK_MESSAGE_CHARS = 200

# 终态默认保留 5 分钟（够网页端在一次压缩结束后回看结果），且最多留最近 32 条终态。
DEFAULT_RETENTION_SECONDS = 300.0
DEFAULT_MAX_FINISHED_TASKS = 32
# 单次快照的默认条目上限（与网络层响应上界一致；条目按 ``updated_at`` 倒序取前 N 条）。
DEFAULT_QUERY_LIMIT = 64

# 进度上报回调的签名：(percent, message)。生产者侧只需提供这两个参数的可调用对象。
ProgressReporter = Callable[[int, str], None]


class TaskStatus(StrEnum):
    """任务四态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


#: 终态集合：进入即不再接受进度上报，并参与 TTL / 条数淘汰。
TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED})


def _utc_now() -> datetime:
    """默认时钟（注入点：测试用可控时钟验证 TTL）。"""
    return datetime.now(UTC)


class TaskProgress(BaseModel):
    """一条任务进度（不可变快照）。

    ``message`` 是给人看的一句当前动作（如 ``summarizing 12 messages``），不含路径与凭据；
    时间戳都是带时区的 UTC，序列化为 ISO 8601。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1, max_length=MAX_TASK_ID_CHARS)
    kind: str = Field(min_length=1, max_length=MAX_TASK_KIND_CHARS)
    status: TaskStatus
    percent: int = Field(ge=0, le=100)
    message: str | None = Field(default=None, max_length=MAX_TASK_MESSAGE_CHARS)
    started_at: datetime
    updated_at: datetime

    @field_validator("task_id", "kind", "message", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @property
    def finished(self) -> bool:
        """是否已进入终态（终态条目只在保留期内可查）。"""
        return self.status in TERMINAL_STATUSES


class TaskProjection:
    """任务进度的**落盘投影**：让另一个进程（独立 ``http-server`` / cron 子进程）看到本进程的后台任务。

    一条任务一个文件 ``<root>/<task_id>.json``（原子写；``task_id`` 是 uuid ⇒ 无同 id 写冲突）。
    投影是**观测面**：任何 I/O 失败只记 WARNING，绝不影响生产者；读取侧对损坏文件同样静默跳过。

    扫描有界：``load_all`` 最多读 ``_MAX_PROJECTION_FILES`` 个文件（目录被外部塞满时不至于拖死查询）。
    """

    _MAX_PROJECTION_FILES = 256

    def __init__(self, root: str | Path, *, retention_seconds: float = DEFAULT_RETENTION_SECONDS) -> None:
        self._root = Path(root)
        self._retention = timedelta(seconds=retention_seconds)

    @property
    def root(self) -> Path:
        """投影目录（跨进程共享的落点）。"""
        return self._root

    def write(self, progress: TaskProgress) -> None:
        """把一条进度原子写到投影目录（失败只 WARNING）。"""
        try:
            atomic_write_text(self._root / f"{progress.task_id}.json", progress.model_dump_json())
        except OSError as exc:
            logger.warning("Task projection write failed for %s: %s", progress.task_id, exc)

    def discard(self, task_id: str) -> None:
        """删除一条投影文件（不存在即 no-op）。"""
        with contextlib.suppress(OSError):
            (self._root / f"{task_id}.json").unlink()

    def load_all(self, *, now: datetime) -> list[TaskProgress]:
        """读出全部仍有效的投影条目（过期终态跳过；损坏文件静默跳过）。"""
        try:
            paths = sorted(self._root.glob("*.json"))[: self._MAX_PROJECTION_FILES]
        except OSError:
            return []
        entries: list[TaskProgress] = []
        for path in paths:
            progress = self._read(path)
            if progress is None:
                continue
            if progress.finished and now - progress.updated_at > self._retention:
                continue
            entries.append(progress)
        return entries

    def prune(self, *, now: datetime) -> int:
        """删除过期的终态投影文件，返回删除数。"""
        removed = 0
        try:
            paths = list(self._root.glob("*.json"))
        except OSError:
            return 0
        for path in paths:
            progress = self._read(path)
            if progress is None or not progress.finished:
                continue
            if now - progress.updated_at <= self._retention:
                continue
            with contextlib.suppress(OSError):
                path.unlink()
                removed += 1
        return removed

    def load_one(self, task_id: str, *, now: datetime) -> TaskProgress | None:
        """读单条投影（过期终态 / 缺失 / 损坏都返回 ``None``）。"""
        progress = self._read(self._root / f"{task_id}.json")
        if progress is None:
            return None
        if progress.finished and now - progress.updated_at > self._retention:
            return None
        return progress

    @staticmethod
    def _read(path: Path) -> TaskProgress | None:
        try:
            return TaskProgress.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


class TaskRegistry:
    """任务进度的唯一所有者：注册、上报、收尾、读取与淘汰。

    ``clock`` 可注入（返回带时区的 ``datetime``），TTL 判据全部走它，测试无需真实等待。
    ``projection``（A56）是**跨进程**的落盘投影：本进程的写入同步投影到磁盘，读取时与内存
    条目合并（同 id 取 ``updated_at`` 新者）⇒ 独立 ``http-server`` / cron 子进程也能看到本进程
    正在跑的后台任务。``None`` = 纯进程内（默认，既有行为逐字不变）。
    """

    def __init__(
        self,
        *,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
        max_finished: int = DEFAULT_MAX_FINISHED_TASKS,
        clock: Callable[[], datetime] | None = None,
        projection: TaskProjection | None = None,
    ) -> None:
        if retention_seconds < 0:
            raise ValueError("retention_seconds must not be negative")
        if max_finished < 0:
            raise ValueError("max_finished must not be negative")
        self._retention = timedelta(seconds=retention_seconds)
        self._max_finished = max_finished
        self._clock = clock or _utc_now
        self._tasks: dict[str, TaskProgress] = {}
        self._projection = projection

    def attach_projection(self, projection: TaskProjection | None) -> None:
        """绑定 / 解绑落盘投影（幂等：同一目录重复绑定是 no-op，内存条目不受影响）。"""
        if projection is None:
            self._projection = None
            return
        current = self._projection
        if current is not None and current.root == projection.root:
            return
        self._projection = projection

    # ---- 写入（生产者） ----

    def start(self, kind: str, *, task_id: str | None = None, message: str | None = None) -> str:
        """注册一个 ``pending`` 任务并返回其 id（未给 id 时生成 uuid4 hex）。

        同一 id 重复注册会覆盖旧条目（生产者的 id 冲突属编程错误，这里留 WARNING 而不是抛
        ——后台进度上报失败不该让主流程崩）。
        """
        now = self._clock()
        progress = TaskProgress(
            task_id=task_id or uuid.uuid4().hex,
            kind=kind,
            status=TaskStatus.PENDING,
            percent=0,
            message=message,
            started_at=now,
            updated_at=now,
        )
        if progress.task_id in self._tasks:
            logger.warning("Task progress re-registered for id=%s (previous state overwritten)", progress.task_id)
        self._tasks[progress.task_id] = progress
        self._project(progress)
        self.prune()
        return progress.task_id

    def begin(self, task_id: str, *, message: str | None = None) -> TaskProgress | None:
        """把 ``pending`` 任务切到 ``running``；未知 id 返回 ``None``，终态任务原样返回。"""
        current = self._tasks.get(task_id)
        if current is None or current.finished:
            return current
        return self._write(current, status=TaskStatus.RUNNING, message=message)

    def report(self, task_id: str, percent: int, *, message: str | None = None) -> TaskProgress | None:
        """上报进度：夹到 ``0..100`` 并与当前值取 ``max``（单调不减），同时切到 ``running``。

        未知 id 或终态任务一律不改状态（终态返回当前快照），生产者无需自己判断是否已收尾。
        """
        current = self._tasks.get(task_id)
        if current is None or current.finished:
            return current
        return self._write(
            current,
            status=TaskStatus.RUNNING,
            percent=max(current.percent, min(100, max(0, int(percent)))),
            message=message,
        )

    def finish(self, task_id: str, *, message: str | None = None) -> TaskProgress | None:
        """收尾为 ``completed``（percent 归 100）；未知 id 返回 ``None``，已是终态则原样返回。"""
        current = self._tasks.get(task_id)
        if current is None or current.finished:
            return current
        return self._write(current, status=TaskStatus.COMPLETED, percent=100, message=message)

    def fail(self, task_id: str, *, message: str | None = None) -> TaskProgress | None:
        """收尾为 ``failed``，保留末次 percent（失败不冒充「走完 100%」）；已是终态则原样返回。"""
        current = self._tasks.get(task_id)
        if current is None or current.finished:
            return current
        return self._write(current, status=TaskStatus.FAILED, message=message)

    # ---- 读取（查询方） ----

    def get(self, task_id: str) -> TaskProgress | None:
        """按 id 读一条（先淘汰过期终态，因此保留期外/未知都返回 ``None``）。

        绑定了跨进程投影时，磁盘条目与内存条目合并（同 id 取 ``updated_at`` 新者）。
        """
        self.prune()
        current = self._tasks.get(task_id)
        if self._projection is None:
            return current
        from_projection = self._projection.load_one(task_id, now=self._clock())
        if from_projection is None:
            return current
        if current is None or from_projection.updated_at > current.updated_at:
            return from_projection
        return current

    def snapshot(self, *, limit: int = DEFAULT_QUERY_LIMIT) -> list[TaskProgress]:
        """按 ``updated_at`` 倒序返回至多 ``limit`` 条（最近有动静的排前面）。

        绑定了跨进程投影时把磁盘条目并进来（同 id 取 ``updated_at`` 新者）⇒ 另一个进程的任务
        出现在同一次查询里。未绑定投影时行为与改造前逐字一致。
        """
        self.prune()
        merged: dict[str, TaskProgress] = dict(self._tasks)
        if self._projection is not None:
            for progress in self._projection.load_all(now=self._clock()):
                current = merged.get(progress.task_id)
                if current is None or progress.updated_at > current.updated_at:
                    merged[progress.task_id] = progress
        ordered = sorted(merged.values(), key=lambda item: (item.updated_at, item.task_id), reverse=True)
        return ordered[: max(0, limit)]

    def discard(self, task_id: str) -> bool:
        """直接摘除一条（**不**写终态），返回是否真的删掉了。

        给「开了 scope 才发现这次什么都没做」的生产者用：调用方按正常路径进来、事后才知道
        该动作并不存在，此时留一条 ``completed 100%`` 是噪声，而留 ``failed`` 又是谎报。
        """
        removed = self._tasks.pop(task_id, None) is not None
        if self._projection is not None:
            self._projection.discard(task_id)
        return removed

    def prune(self) -> int:
        """淘汰过期/超额的**终态**条目，返回删除条数（在途任务永不被删）。"""
        now = self._clock()
        removed = 0
        for task_id, progress in list(self._tasks.items()):
            if progress.finished and now - progress.updated_at > self._retention:
                del self._tasks[task_id]
                removed += 1
        finished = sorted(
            (progress for progress in self._tasks.values() if progress.finished),
            key=lambda item: (item.updated_at, item.task_id),
        )
        for progress in finished[: max(0, len(finished) - self._max_finished)]:
            del self._tasks[progress.task_id]
            removed += 1
        if self._projection is not None:
            removed += self._projection.prune(now=now)
        return removed

    def scope(self, kind: str, *, task_id: str | None = None, message: str | None = None) -> TaskScope:
        """开一个 :class:`TaskScope` 句柄（生产者侧的主要用法）。"""
        return TaskScope(self, kind, task_id=task_id, message=message)

    # ---- 内部 ----

    def _project(self, progress: TaskProgress) -> None:
        """把一次状态变更投影到磁盘（未绑定投影时 no-op）。"""
        if self._projection is not None:
            self._projection.write(progress)

    def _write(
        self,
        current: TaskProgress,
        *,
        status: TaskStatus,
        percent: int | None = None,
        message: str | None = None,
    ) -> TaskProgress:
        """以「当前快照 + 变更字段」重建一条（走模型校验，越界值在写入点就暴露）。

        ``message`` 不给时**沿用上一条**：生产者通常只在关键节点写文案，收尾时清空会让查询方
        失去「它最后在干什么」这个信息。
        """
        changes: dict[str, object] = {"status": status}
        if percent is not None:
            changes["percent"] = percent
        if message is not None:
            changes["message"] = message
        payload = {**current.model_dump(), **changes, "updated_at": self._clock()}
        updated = TaskProgress.model_validate(payload)
        self._tasks[updated.task_id] = updated
        self._project(updated)
        if updated.finished:
            self.prune()
        return updated


class TaskScope:
    """一次后台任务的进度句柄：``with registry.scope("context_compression") as task: …``。

    进入即注册并置 ``running``；``__exit__`` 在未显式收尾时按「正常 → ``completed`` /
    异常 → ``failed``」收尾，因此生产者不必写 ``try/finally``，也不会留下永远 ``running``
    的僵尸条目。异常**照原样向外传播**（本类不吞异常）。
    """

    def __init__(
        self,
        registry: TaskRegistry,
        kind: str,
        *,
        task_id: str | None = None,
        message: str | None = None,
    ) -> None:
        self._registry = registry
        self._kind = kind
        self._requested_id = task_id
        self._message = message
        self.task_id: str = task_id or ""
        self._closed = False

    def __enter__(self) -> TaskScope:
        self.task_id = self._registry.start(self._kind, task_id=self._requested_id, message=self._message)
        self._registry.begin(self.task_id)
        return self

    def report(self, percent: int, message: str | None = None) -> None:
        """上报进度（签名与 :data:`ProgressReporter` 兼容，可直接当回调传入生产者）。"""
        self._registry.report(self.task_id, percent, message=message)

    def finish(self, message: str | None = None) -> None:
        """显式收尾为 ``completed``（幂等：已收尾后再次调用无副作用）。"""
        if self._closed:
            return
        self._closed = True
        self._registry.finish(self.task_id, message=message)

    def fail(self, message: str | None = None) -> None:
        """显式收尾为 ``failed``（幂等）。"""
        if self._closed:
            return
        self._closed = True
        self._registry.fail(self.task_id, message=message)

    def discard(self) -> None:
        """把本条任务从注册表摘除（幂等）：用于「进 scope 后发现根本没有活要干」的场景。

        与 :meth:`finish` / :meth:`fail` 的区别是**不留任何终态**——既不冒充完成，也不谎报失败。
        """
        if self._closed:
            self._registry.discard(self.task_id)
            return
        self._closed = True
        self._registry.discard(self.task_id)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._closed:
            return
        if exc_type is None:
            self.finish()
        else:
            self.fail(str(exc) if exc is not None else None)


_default_registry: TaskRegistry | None = None


def default_task_registry() -> TaskRegistry:
    """进程内共享注册表：生产者与查询端点必须看到**同一实例**（跨进程经落盘投影共享，见下）。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = TaskRegistry()
    return _default_registry


def configure_task_projection(root: str | Path | None) -> TaskRegistry:
    """给进程内默认注册表绑定落盘投影目录（A56：跨进程可见），``None`` = 解绑。

    幂等：同一目录重复调用不改内存状态。装配点在 ``EngineContainer.default()``——
    四个入口（run / 交互 / http-server / gui）构造引擎时都会走到，故同工作区的多个进程
    天然共享同一个 ``<状态根>/tasks/``。
    """
    registry = default_task_registry()
    registry.attach_projection(None if root is None else TaskProjection(root))
    return registry


__all__ = [
    "DEFAULT_MAX_FINISHED_TASKS",
    "DEFAULT_QUERY_LIMIT",
    "DEFAULT_RETENTION_SECONDS",
    "MAX_TASK_ID_CHARS",
    "MAX_TASK_KIND_CHARS",
    "MAX_TASK_MESSAGE_CHARS",
    "TERMINAL_STATUSES",
    "ProgressReporter",
    "TaskProgress",
    "TaskProjection",
    "TaskRegistry",
    "TaskScope",
    "TaskStatus",
    "configure_task_projection",
    "default_task_registry",
]
