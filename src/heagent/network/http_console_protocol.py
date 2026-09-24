"""Bounded console request models and the injected project-handler contract.

网络层（``network/``）**不认识项目、会话或配置的实现**（脊柱 I1）：所有能力都经本模块的
Pydantic 模型 + :class:`ConsoleHandler` Protocol 注入，``http_server.py`` 只做路由与错误映射。
因此这里只依赖标准库、Pydantic 与同层协议模型（``http_protocol``）。

两条与 ``context/session.py`` 的**常量镜像**（网络层不得 import 运行时模块，故只能各自持有）：
:data:`MAX_SESSION_TITLE_CHARS` 与 :data:`MAX_SESSION_LIST_ENTRIES` 必须与
``heagent.context.session`` 的同名常量一致——由 ``tests/network/test_http_console_sessions.py``
的可执行断言钉住，避免两处漂移。
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from heagent.network.http_protocol import MAX_PROMPT_CHARS, RunStatus, SessionMessage

MAX_PROJECT_NAME_CHARS = 64
MAX_PROJECT_PATH_CHARS = 4096

# 会话相关上限（镜像 ``heagent.context.session``；见模块 docstring）。
MAX_SESSION_ID_CHARS = 128
MAX_SESSION_TITLE_CHARS = 120
MAX_SESSION_LIST_ENTRIES = 200
MAX_SESSION_MESSAGES_IN_RESPONSE = 500

# session_id 的字符集与长度（与 ``context/session.py`` 的 ``_SESSION_ID_RE`` 同义）。
# 网络层先用它做**第一道**校验：非法 id 直接回 ``invalid_session_id``，**不触碰文件系统**
# （入口层的 ``SessionStore`` 仍会再校验一次，两点各自 fail-closed）。
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def is_valid_session_id(value: str) -> bool:
    """会话 id 是否合法（路径遍历 / 超长 / 空值一律不合法）。"""
    return bool(SESSION_ID_PATTERN.match(value))


class ProjectEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_CHARS)
    path: str = Field(min_length=1, max_length=MAX_PROJECT_PATH_CHARS)
    available: bool
    last_opened_at: str | None = None
    is_default: bool


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectEntryResponse] = Field(max_length=32)


class ProjectRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=MAX_PROJECT_PATH_CHARS)
    name: str | None = Field(default=None, max_length=MAX_PROJECT_NAME_CHARS)

    @field_validator("path", "name", mode="before")
    @classmethod
    def _strip_string(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_CHARS)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SessionEntryResponse(BaseModel):
    """会话列表里的一条（有界；不含消息正文）。

    ``message_count=None`` 表示「本次未统计」（会话过大，按 D6 退化为详情才给），不是 0。
    ``unreadable=True`` 表示文件存在但无法解析——列表**仍列出它**（不静默消失），详情会回
    ``session_unreadable``。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_CHARS)
    title: str = Field(min_length=1, max_length=MAX_SESSION_TITLE_CHARS)
    message_count: int | None = Field(default=None, ge=0)
    version: int = Field(default=0, ge=0)
    updated_at: str | None = None
    unreadable: bool = False


class SessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionEntryResponse] = Field(max_length=MAX_SESSION_LIST_ENTRIES)


class SessionCreateRequest(BaseModel):
    """``POST /api/projects/{id}/sessions`` 的请求体：只允许（可选）标题。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=MAX_SESSION_TITLE_CHARS)

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("title must not be blank")
        return collapsed


class SessionRenameRequest(BaseModel):
    """``PATCH /api/projects/{id}/sessions/{sid}`` 的请求体。

    ``fingerprint`` 是客户端**持有的会话版本号**（即详情响应里的 ``version``）：与磁盘不一致时
    服务端回 ``session_conflict`` 且不改文件（脊柱 I11 的显式冲突语义）。缺省 ``None`` = 不做
    冲突检查（与 CLI 的 last-write-wins 同档，由调用方决定是否依赖它）。
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_SESSION_TITLE_CHARS)
    fingerprint: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("title must not be blank")
        return collapsed


class SessionDetailResponse(BaseModel):
    """``GET /api/projects/{id}/sessions/{sid}`` 的响应：会话文件是**唯一权威**的对话历史。

    ``messages`` 超长时只回**最后** :data:`MAX_SESSION_MESSAGES_IN_RESPONSE` 条并把
    ``messages_truncated`` 置真（显式标注，绝不静默截断）。``run_id`` / ``status`` 与该会话当前
    （或最近）的在途运行对齐——失败 / 取消的运行也**已写进会话文件**（用户看到过那些消息），
    状态字段如实报告，两者不构成矛盾（story 50-3 的 T9b 口径）。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_CHARS)
    title: str = Field(min_length=1, max_length=MAX_SESSION_TITLE_CHARS)
    version: int = Field(ge=0)
    messages: list[SessionMessage] = Field(max_length=MAX_SESSION_MESSAGES_IN_RESPONSE)
    messages_truncated: bool = False
    run_id: str | None = None
    status: RunStatus | None = None


class ProjectRunRequest(BaseModel):
    """``POST /api/projects/{id}/runs`` 的请求体。

    ``session_id`` 缺省 = 该项目「当前会话」（最近一次会话，无则新建）；给了就必须存在
    （否则回 ``unknown_session``）。
    """

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    session_id: str | None = Field(default=None, max_length=MAX_SESSION_ID_CHARS)

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


class ProjectRunResponse(BaseModel):
    """项目内运行的创建结果：``run_id`` 复用既有 SSE/取消端点（``/api/runs/{id}/…``）。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_CHARS)
    status: RunStatus


class ConsoleOperationError(Exception):
    """Expected handler failure with a stable client-visible code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConsoleHandler(Protocol):
    """Project operations supplied by the entry layer; network knows no registry."""

    async def list_projects(self) -> ProjectListResponse: ...

    async def register_project(self, request: ProjectRegisterRequest) -> ProjectEntryResponse: ...

    async def rename_project(self, project_id: str, request: ProjectRenameRequest) -> ProjectEntryResponse: ...

    async def project_has_inflight_run(self, project_id: str) -> bool: ...

    async def remove_project(self, project_id: str) -> None: ...

    # ── 会话与项目内运行（Story 50-3） ──

    async def list_sessions(self, project_id: str) -> SessionListResponse: ...

    async def create_session(self, project_id: str, request: SessionCreateRequest) -> SessionEntryResponse: ...

    async def get_session(self, project_id: str, session_id: str) -> SessionDetailResponse: ...

    async def rename_session(
        self, project_id: str, session_id: str, request: SessionRenameRequest
    ) -> SessionEntryResponse: ...

    async def delete_session(self, project_id: str, session_id: str) -> None: ...

    async def start_project_run(self, project_id: str, request: ProjectRunRequest) -> ProjectRunResponse: ...


__all__ = [
    "MAX_PROJECT_NAME_CHARS",
    "MAX_PROJECT_PATH_CHARS",
    "MAX_SESSION_ID_CHARS",
    "MAX_SESSION_LIST_ENTRIES",
    "MAX_SESSION_MESSAGES_IN_RESPONSE",
    "MAX_SESSION_TITLE_CHARS",
    "SESSION_ID_PATTERN",
    "ConsoleHandler",
    "ConsoleOperationError",
    "ProjectEntryResponse",
    "ProjectListResponse",
    "ProjectRegisterRequest",
    "ProjectRenameRequest",
    "ProjectRunRequest",
    "ProjectRunResponse",
    "SessionCreateRequest",
    "SessionDetailResponse",
    "SessionEntryResponse",
    "SessionListResponse",
    "SessionRenameRequest",
    "is_valid_session_id",
]
