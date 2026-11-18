"""后台任务进度查询端点：``GET /api/tasks`` 与 ``GET /api/tasks/{task_id}``（Story 64.11）。

网络层只认**注入的进度来源**（:class:`TaskProgressSource`）：它不认识 ``heagent.engine.tasks``、
不读磁盘、也不等待任何在途工作。因此两条查询恒为「内存读取 + 定长模型序列化」，耗时与任务
规模、与生产者是否在跑都无关（验收要求的「响应 <100ms」由这条结构保证，而不是靠调优）。

生产者侧实现由入口层注入；:class:`RegistryTaskSource` 是给 ``engine.tasks.TaskRegistry`` 用的
现成适配器（鸭子类型：只要求 ``snapshot(limit=...)`` 与 ``get(task_id)`` 两个同步方法），
因此本模块不需要 import 运行栈，依赖边界（AD-1）保持不变。

404 语义：未知 / 已被保留期淘汰的 ``task_id`` 一律 ``not_found`` + 404（不区分「从未存在」与
「已过期」——那差异对客户端没有可用动作）。
"""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 - Pydantic 字段注解需运行期导入以构建 schema
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from heagent.network.http_protocol import HttpErrorCode
from heagent.pub.safe_logging import safe_log

from .pipeline import _json_error

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger("heagent.network.http_server")

# 响应上界（条目数）。镜像 ``heagent.engine.tasks`` 的同名字段上界，但网络层不得 import 它，
# 故各自持有；由 ``tests/network/test_http_tasks.py`` 的可执行断言钉住不漂移。
MAX_TASK_LIST_ENTRIES = 64
MAX_TASK_ID_CHARS = 64
MAX_TASK_KIND_CHARS = 32
MAX_TASK_MESSAGE_CHARS = 200

__all__ = [
    "MAX_TASK_LIST_ENTRIES",
    "RegistryTaskSource",
    "TaskListResponse",
    "TaskProgressSource",
    "TaskProgressView",
    "TaskStatusView",
]


class TaskStatusView(StrEnum):
    """任务四态（镜像 ``heagent.engine.tasks.TaskStatus`` 的取值，测试钉住一致性）。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskProgressView(BaseModel):
    """一条任务进度的响应投影（字段封闭：多出的字段在适配处即被丢弃）。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=MAX_TASK_ID_CHARS)
    kind: str = Field(min_length=1, max_length=MAX_TASK_KIND_CHARS)
    status: TaskStatusView
    percent: int = Field(ge=0, le=100)
    message: str | None = Field(default=None, max_length=MAX_TASK_MESSAGE_CHARS)
    started_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    """``GET /api/tasks`` 的响应：至多 :data:`MAX_TASK_LIST_ENTRIES` 条，最近的排前面。"""

    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskProgressView] = Field(default_factory=list, max_length=MAX_TASK_LIST_ENTRIES)


class TaskProgressSource(Protocol):
    """注入的进度来源（**同步**：只读内存，端点因此不 ``await``、不做磁盘扫描）。"""

    def list_tasks(self) -> Sequence[TaskProgressView]: ...

    def task(self, task_id: str) -> TaskProgressView | None: ...


def _view(progress: Any) -> TaskProgressView:
    """把生产方的同形进度转成网络层视图（字段集合与取值由本模型重新校验）。"""
    return TaskProgressView.model_validate(progress.model_dump(mode="python"))


class RegistryTaskSource:
    """把「进度注册表」适配为网络层来源。

    要求（鸭子类型，避免网络层 import ``heagent.engine.tasks``）：注册表提供同步的
    ``snapshot(*, limit: int)`` 与 ``get(task_id)``，返回对象可 ``model_dump()`` 且字段同名。
    适配只做类型转换——不裁剪语义、不补默认值；字段缺失/越界在这里 fail-loud（端点收敛为 500）。
    """

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def list_tasks(self) -> list[TaskProgressView]:
        return [_view(progress) for progress in self._registry.snapshot(limit=MAX_TASK_LIST_ENTRIES)]

    def task(self, task_id: str) -> TaskProgressView | None:
        progress = self._registry.get(task_id)
        return None if progress is None else _view(progress)


def _build_task_endpoints(responses: Any, source: TaskProgressSource) -> tuple[Any, Any]:
    """构造两条只读端点闭包（列表 / 单条）。

    注入方抛任何异常都收敛为 500 + 固定文案（诊断只进服务端日志）：任务进度是辅助信息，
    它的失败不该把客户端文案变成内部细节的出口。
    """

    async def list_tasks(request: Any) -> Any:  # noqa: ARG001 - 端点的固定签名
        try:
            views = list(source.list_tasks())[:MAX_TASK_LIST_ENTRIES]
        except Exception:
            safe_log(logger, logging.ERROR, "http event=task_list_failed", exc_info=True)
            return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=500)
        return responses.JSONResponse(TaskListResponse(tasks=views).model_dump(mode="json"))

    async def get_task(request: Any) -> Any:
        task_id = str(request.path_params.get("task_id", ""))
        try:
            view = source.task(task_id)
        except Exception:
            safe_log(logger, logging.ERROR, "http event=task_read_failed", exc_info=True)
            return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=500)
        if view is None:
            return _json_error(responses, HttpErrorCode.NOT_FOUND, "no such task", status_code=404)
        return responses.JSONResponse(view.model_dump(mode="json"))

    return list_tasks, get_task
