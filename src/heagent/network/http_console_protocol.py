"""Bounded console request models and the injected project-handler contract.

网络层（``network/``）**不认识项目、会话或配置的实现**（脊柱 I1）：所有能力都经本模块的
Pydantic 模型 + :class:`ConsoleHandler` Protocol 注入，``http_server.py`` 只做路由与错误映射。
因此这里只依赖标准库、Pydantic 与同层协议模型（``http_protocol``）。

两条与 ``context/session.py`` 的**常量镜像**（网络层不得 import 运行时模块，故只能各自持有）：
:data:`MAX_SESSION_TITLE_CHARS` 与 :data:`MAX_SESSION_LIST_ENTRIES` 必须与
``heagent.context.session`` 的同名常量一致——由 ``tests/network/test_http_console_sessions.py``
的可执行断言钉住，避免两处漂移。同理 :data:`MAX_CONFIG_UNKNOWN_KEYS` 与
:data:`MAX_CONFIG_FILE_DIAGNOSTIC_KEYS` 镜像 ``heagent.config.catalog`` 的同名常量（配置面板的
条目也来自文件内容，必须有界），由 ``tests/network/test_http_console_config.py`` 钉住。
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from heagent.network.http_protocol import MAX_PROMPT_CHARS, RunStatus, SessionMessage

MAX_PROJECT_NAME_CHARS = 64
MAX_PROJECT_PATH_CHARS = 4096

# 配置面板的上界（镜像 ``heagent.config.catalog`` 的同名常量；由
# ``tests/network/test_http_console_config.py`` 的可执行断言钉住）。条目本身来自文件内容
# （未知键 / 重复键 / 空值键），因此必须有界——响应体不得随 `.env` 内容膨胀。
MAX_CONFIG_UNKNOWN_KEYS = 64
MAX_CONFIG_FILE_DIAGNOSTIC_KEYS = 64

# 写入通道的上界（镜像 ``heagent.config.write`` / ``heagent.config.envfile`` 的同名常量；网络层不得
# import 它们，故各自持有并由 ``tests/network/test_http_console_config.py`` 钉住一致性）。
# 一次请求的键数、键名长度、值长度都来自客户端 ⇒ 必须有界（请求体与写锁持有时间都不随输入膨胀）。
MAX_CONFIG_WRITE_CHANGES = 64
MAX_CONFIG_KEY_CHARS = 64
MAX_CONFIG_VALUE_CHARS = 8192
# sha256 十六进制（64 字符）是唯一合法形态，留一点余量以便未来换算法时前后端不致同时改动。
MAX_CONFIG_FINGERPRINT_CHARS = 128

# 会话相关上限（镜像 ``heagent.context.session``；见模块 docstring）。
MAX_SESSION_ID_CHARS = 128
MAX_SESSION_TITLE_CHARS = 120
MAX_SESSION_LIST_ENTRIES = 200
MAX_SESSION_MESSAGES_IN_RESPONSE = 500

# session_id 的字符集与长度（与 ``context/session.py`` 的 ``_SESSION_ID_RE`` 同义）。
# 网络层先用它做**第一道**校验：非法 id 直接回 ``invalid_session_id``，**不触碰文件系统**
# （入口层的 ``SessionStore`` 仍会再校验一次，两点各自 fail-closed）。
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}\Z")


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


class ConfigSourceValue(StrEnum):
    """有效值的来源层（镜像 ``heagent.config.catalog.ConfigSource`` 的取值）。"""

    DEFAULT = "default"
    GLOBAL_ENV = "global_env"
    PROJECT_ENV = "project_env"
    SYSTEM_ENV = "system_env"


class ConfigGuardResponse(BaseModel):
    """某项的合法约束（枚举集合或上下界），供 UI 提示与写通道复用。

    ``kind="enum"`` 时看 ``values``（``allow_empty`` 表示「空 = 回退」也合法）；
    ``kind="range"`` 时看 ``minimum`` / ``maximum``（``exclusive_*`` 表示开区间）与 ``min_length``。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["enum", "range"]
    values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False
    min_length: int | None = None
    allow_empty: bool = False


class RoutingPoolResponse(BaseModel):
    """一条**有效**路由池（池名 / 档位映射 / 角色映射 / 默认档 / 追加关键词）。"""

    model_config = ConfigDict(extra="forbid")

    entry: str = Field(min_length=1)
    tiers: dict[str, str] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)
    default: str | None = None
    keywords: dict[str, str] = Field(default_factory=dict)


class RoutingPoolsResponse(BaseModel):
    """``ROUTING_POOLS`` 的**有效**结果：非法 JSON / 被整条忽略的条目不再是「只有一串 JSON」。"""

    model_config = ConfigDict(extra="forbid")

    declared_entries: tuple[str, ...] = ()
    effective: tuple[RoutingPoolResponse, ...] = ()
    ignored_entries: tuple[str, ...] = ()
    invalid_json: bool = False


class ConfigItemResponse(BaseModel):
    """配置面板里的一条。

    - ``value``：有效值（取自 ``Settings`` 快照）。**凭证项恒为 ``None``**。
    - ``source``：最后写入层；``configured`` = 有非默认来源提供了值。
    - ``writable`` / ``read_only_reason``：``False`` 时原因必非空（UX-DR5：只读必须给原因）。
    - ``is_secret`` / ``masked``：凭证只回 ``configured`` + **定长**掩码（常量、零信息量）。
    - ``read_only_reason`` 与 ``notes`` 都是**稳定码**；中文文案见响应里的 ``labels``。
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    group: str = Field(min_length=1)
    value: Any = None
    source: ConfigSourceValue
    writable: bool
    read_only_reason: str | None = None
    is_secret: bool = False
    configured: bool = False
    masked: str | None = None
    guards: ConfigGuardResponse | None = None
    notes: tuple[str, ...] = ()
    routing: RoutingPoolsResponse | None = None


class ConfigGroupResponse(BaseModel):
    """一组配置项（分组由后端声明式常量驱动，UI 不做任何猜测）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    items: tuple[ConfigItemResponse, ...] = ()


class EnvFileStatusResponse(BaseModel):
    """项目 ``.env`` 的文件状态与文件级诊断（``fingerprint`` = 内容 sha256，写通道的冲突判据）。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    exists: bool
    readable: bool
    fingerprint: str | None = None
    has_bom: bool = False
    line_count: int = Field(default=0, ge=0)
    duplicate_keys: tuple[str, ...] = Field(default=(), max_length=MAX_CONFIG_FILE_DIAGNOSTIC_KEYS)
    blank_keys: tuple[str, ...] = Field(default=(), max_length=MAX_CONFIG_FILE_DIAGNOSTIC_KEYS)


class UnknownKeyResponse(BaseModel):
    """未知 / 拼错的键（不生效，单列——**不并入**有效值列表）。"""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    source: ConfigSourceValue


class ProjectConfigResponse(BaseModel):
    """``GET /api/projects/{id}/config`` 的响应：分组条目 + 文件状态 + 未知键 + 文案表。

    ``write_enabled`` 是**服务启动时**解析的写闸门（``HTTP_CONSOLE_WRITE_ENABLED``，D4）：闸门关着时
    条目上的 ``writable`` 仍然是「白名单 + 非系统环境变量」的判定结果，因此 UI **不能**只靠 ``writable``
    决定「可编辑」——否则会出现「面板显示可编辑、保存必被拒」（AC5 要求闸门关闭时所有可写项显示为不可
    编辑并说明原因）。该字段由**持有闸门的入口层**填写（不是传输层、也不是 ``config_catalog`` 的第二份
    副本），与 ``PUT`` 的裁决**同一事实源**；它是给 UI 的**提示**，服务端仍逐次 fail-closed 校验。
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    field_count: int = Field(ge=0)
    write_enabled: bool
    groups: tuple[ConfigGroupResponse, ...] = ()
    env_file: EnvFileStatusResponse
    unknown_keys: tuple[UnknownKeyResponse, ...] = Field(default=(), max_length=MAX_CONFIG_UNKNOWN_KEYS)
    labels: dict[str, str] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()


class ConfigWriteChangeRequest(BaseModel):
    """要写入的一个键（``value`` 一律字符串：``.env`` 是文本，类型/范围由服务端校验）。

    ``key`` 归一化为**大写**并去空白（env 键大小写不敏感）；``value`` **不做任何归一化**——
    首尾空白会被服务端显式拒绝（``invalid_value``），静默裁剪会让「写进去的值」与「解析出的值」不一致。
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=MAX_CONFIG_KEY_CHARS)
    value: str = Field(max_length=MAX_CONFIG_VALUE_CHARS)

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class ConfigWriteRequest(BaseModel):
    """``PUT /api/projects/{id}/config`` 的请求体（整批**原子**：任一键被拒则整批拒绝、文件不变）。

    ``fingerprint`` 是客户端**当前持有的项目 ``.env`` 内容指纹**（即配置面板响应里
    ``env_file.fingerprint``）：与盘上不符 → ``config_conflict``，绝不覆盖对方的修改。
    ``None`` 表示「客户端认为文件尚不存在」——此时若盘上确有文件同样是冲突（fail-closed，
    不存在「没给指纹就随便覆盖」的通道）。
    """

    model_config = ConfigDict(extra="forbid")

    changes: list[ConfigWriteChangeRequest] = Field(min_length=1, max_length=MAX_CONFIG_WRITE_CHANGES)
    fingerprint: str | None = Field(default=None, max_length=MAX_CONFIG_FINGERPRINT_CHARS)

    @model_validator(mode="after")
    def _reject_duplicate_keys(self) -> ConfigWriteRequest:
        seen: set[str] = set()
        for change in self.changes:
            if change.key in seen:
                raise ValueError(f"duplicate key {change.key}")
            seen.add(change.key)
        return self


class ConfigWriteResponse(BaseModel):
    """一次成功写入的结果。

    - ``fingerprint``：写入后的项目 ``.env`` 内容指纹（UI 据此刷新冲突判据）；
    - ``changes``：被改键的**写后**条目（与面板同源求解）——``source`` / ``writable`` 供 UI 刷新徽标；
    - ``applied``：恒为 ``next_run`` —— 生效语义是「下一次运行」（I10：在途 run 继续用旧快照）；
    - ``backup``：写前备份的文件名（不含目录；备份无任何网页下载端点）；
    - ``audit_recorded``：审计是否**真的**落盘。``False`` 时 ``notes`` 含 ``audit_not_recorded``——
      绝不让人误以为「已审计」（审计失败不阻断已成功的写，但必须在响应里可见）。
    - ``labels``：``notes`` 稳定码的中文文案表（与配置面板同源），UI 无需硬编码。
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    fingerprint: str
    applied: Literal["next_run"] = "next_run"
    backup: str | None = None
    audit_recorded: bool = False
    changes: tuple[ConfigItemResponse, ...] = ()
    notes: tuple[str, ...] = ()
    labels: dict[str, str] = Field(default_factory=dict)


class DirectoryPickResponse(BaseModel):
    """``POST /api/dialogs/pick-directory`` 的响应：本机原生目录选择的**唯一**回传通道。

    - ``path``：用户选中的绝对路径；取消 / 超时 / 后端回传脏值时**为 ``None``**；
    - ``cancelled``：是否为「未选择」——取消、超时、脏值三种都归为未选择（UI 只需两条分支）；
    - ``backend``：启动配置里的后端取值（``auto`` 原样回传），用于诊断「为什么弹不出来」。

    返回值**不是权限**：拿到路径后仍走 ``POST /api/projects`` 的全套校验（存在 / 是目录 / 规范化 /
    去重 / 上限），选择器不绕过任何既有闸门。
    """

    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, max_length=MAX_PROJECT_PATH_CHARS)
    cancelled: bool = False
    backend: str = Field(min_length=1, max_length=32)


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

    # ── 配置可见性（Story 50-4） ──

    async def get_project_config(self, project_id: str) -> ProjectConfigResponse: ...

    # ── 配置写入（Story 50-5） ──

    async def update_project_config(self, project_id: str, request: ConfigWriteRequest) -> ConfigWriteResponse: ...

    # ── 原生目录选择（Story 50-8） ──

    async def pick_directory(self) -> DirectoryPickResponse: ...


__all__ = [
    "MAX_CONFIG_FILE_DIAGNOSTIC_KEYS",
    "MAX_CONFIG_FINGERPRINT_CHARS",
    "MAX_CONFIG_KEY_CHARS",
    "MAX_CONFIG_UNKNOWN_KEYS",
    "MAX_CONFIG_VALUE_CHARS",
    "MAX_CONFIG_WRITE_CHANGES",
    "MAX_PROJECT_NAME_CHARS",
    "MAX_PROJECT_PATH_CHARS",
    "MAX_SESSION_ID_CHARS",
    "MAX_SESSION_LIST_ENTRIES",
    "MAX_SESSION_MESSAGES_IN_RESPONSE",
    "MAX_SESSION_TITLE_CHARS",
    "SESSION_ID_PATTERN",
    "ConfigGroupResponse",
    "ConfigGuardResponse",
    "ConfigItemResponse",
    "ConfigSourceValue",
    "ConfigWriteChangeRequest",
    "ConfigWriteRequest",
    "ConfigWriteResponse",
    "ConsoleHandler",
    "ConsoleOperationError",
    "DirectoryPickResponse",
    "EnvFileStatusResponse",
    "ProjectConfigResponse",
    "ProjectEntryResponse",
    "ProjectListResponse",
    "ProjectRegisterRequest",
    "ProjectRenameRequest",
    "ProjectRunRequest",
    "ProjectRunResponse",
    "RoutingPoolResponse",
    "RoutingPoolsResponse",
    "SessionCreateRequest",
    "SessionDetailResponse",
    "SessionEntryResponse",
    "SessionListResponse",
    "SessionRenameRequest",
    "UnknownKeyResponse",
    "is_valid_session_id",
]
