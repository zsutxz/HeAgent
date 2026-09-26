"""HTTP 网页入口的协议模型与稳定错误码（Epic 49）。

本模块是 HTTP 传输层的**协议契约**：请求/响应/错误/事件模型 + 稳定错误码 + 文案净化。
它只依赖 Pydantic 与标准库，不导入任何 ``heagent`` 运行时模块（``tests/test_architecture_contracts.py``
的可执行断言），因此可以被 ``network/http_server.py``、入口层 ``cli/http.py`` 与测试共用。

两条贯穿全 Epic 的协议纪律：

- **稳定错误码**：``HttpErrorCode`` 是客户端可见的封闭集合；新增语义要加成员并同步
  ``docs/frame.md`` 4.17 的错误码表，不能悄悄复用别的码「凑合」。
- **文案有界且脱敏**：客户端只收到 :func:`sanitize_message` 收敛后的单行文本（折叠空白 +
  截断），不含 traceback、异常类名、绝对路径或凭据；诊断细节只进服务端日志（AD-9）。
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# HTTP API 的信封版本：出现在健康检查响应里，供客户端判断兼容性（不随 HeAgent 版本走）。
HTTP_SCHEMA_VERSION = "1"

# 服务标识：与 ``heagent tcp-server`` 的协议名区分，便于浏览器侧做「连对服务了没」的判据。
HTTP_SERVICE_NAME = "heagent-http"

# 单条客户端可见文案的上限（字符）。客户端文案是项目自产的短句，截断只为兜住上游异常文本。
MAX_ERROR_MESSAGE_CHARS = 500

# 单条提示词上限（字符）。请求体上限由 ``HTTP_MAX_REQUEST_BYTES`` 在传输层另外把关
# （字节级），此处是模型级上限，保证「有界」在两层都成立。
MAX_PROMPT_CHARS = 32_768

# JSON 信封余量（键名、引号、逗号与结构性开销；prompt 之外的字节都算这里）。
JSON_ENVELOPE_ALLOWANCE_BYTES = 1_024

# **传输层上限必须容纳协议允许的最大 prompt**，否则两层口径互相矛盾：32768 个中文字按 UTF-8
# 就是 98 304 字节，而旧默认值 65 536 ⇒ 中文用户实际只能用到约 2.18 万字就撞
# ``request_too_large``（远未触及这里写明的字符上限）。
#
# 按「每字符最坏 12 字节」取上界：非 BMP 字符（emoji 等）UTF-8 占 4 字节，经 ``ensure_ascii``
# 类客户端转义后是两个 ``\uXXXX`` 共 12 字节；ASCII 控制字符 6 字节（``\u0001``）；CJK 3 字节。
# 于是任何合法 prompt 在任何客户端编码下都发得进来。394 240 字节仍小于 TCP 入口的
# ``TCP_MAX_REQUEST_BYTES``（1 MiB），量级一致、不构成新的资源面。
MAX_REQUEST_BYTES_FOR_MAX_PROMPT = 12 * MAX_PROMPT_CHARS + JSON_ENVELOPE_ALLOWANCE_BYTES

# 兜底文案：上游异常没有可用 message 时使用（绝不回吐异常类型名）。
GENERIC_ERROR_MESSAGE = "request failed"


class HttpErrorCode(StrEnum):
    """客户端可见的稳定错误码（封闭集合，见 ``docs/frame.md`` 4.17 的错误码表）。

    语义分组（同一分组内的码可被客户端用同一套文案处理）：

    - **输入类**：``invalid_request`` / ``empty_prompt`` / ``request_too_large``；
    - **项目与会话类**：``unknown_project`` / ``invalid_project_path`` / ``project_unavailable`` /
      ``project_not_removable`` / ``project_busy`` / ``project_limit_reached`` / ``unknown_session`` /
      ``invalid_session_id`` / ``session_conflict`` / ``session_busy`` / ``session_unreadable``；
    - **原生选择类**：``dialog_unavailable``（无图形后端 / 被 ``--dialog-backend none`` 禁用）/
      ``dialog_busy``（已有一次选择在途）——「用户取消」与「超时」都用成功响应里的
      ``cancelled=true`` 表达，不占用错误码；
    - **运行类**：``run_conflict`` / ``unknown_run`` / ``resync_required``；
    - **资源类**：``rate_limited`` / ``timeout``；
    - **边界类**：``origin_forbidden`` / ``not_found`` / ``method_not_allowed``；
    - **服务类**：``agent_error`` / ``shutting_down`` / ``server_error``。
    """

    INVALID_REQUEST = "invalid_request"
    EMPTY_PROMPT = "empty_prompt"
    REQUEST_TOO_LARGE = "request_too_large"
    RUN_CONFLICT = "run_conflict"
    UNKNOWN_RUN = "unknown_run"
    UNKNOWN_PROJECT = "unknown_project"
    INVALID_PROJECT_PATH = "invalid_project_path"
    PROJECT_UNAVAILABLE = "project_unavailable"
    PROJECT_NOT_REMOVABLE = "project_not_removable"
    PROJECT_BUSY = "project_busy"
    PROJECT_LIMIT_REACHED = "project_limit_reached"
    UNKNOWN_SESSION = "unknown_session"
    INVALID_SESSION_ID = "invalid_session_id"
    SESSION_CONFLICT = "session_conflict"
    SESSION_BUSY = "session_busy"
    SESSION_UNREADABLE = "session_unreadable"
    CONFIRM_REQUIRED = "confirm_required"
    LOOPBACK_REQUIRED = "loopback_required"
    # 原生目录选择（Epic 50 Story 50-8）：后端不可用 / 已有一次在途。
    DIALOG_UNAVAILABLE = "dialog_unavailable"
    DIALOG_BUSY = "dialog_busy"
    # 配置写入通道（Epic 50 Story 50-5）：闸门关 / 键只读 / 值非法 / 指纹冲突 / 写失败。
    WRITE_DISABLED = "write_disabled"
    FIELD_NOT_WRITABLE = "field_not_writable"
    INVALID_VALUE = "invalid_value"
    CONFIG_CONFLICT = "config_conflict"
    CONFIG_WRITE_FAILED = "config_write_failed"
    RESYNC_REQUIRED = "resync_required"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    ORIGIN_FORBIDDEN = "origin_forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    AGENT_ERROR = "agent_error"
    SHUTTING_DOWN = "shutting_down"
    SERVER_ERROR = "server_error"


class HttpErrorDetail(BaseModel):
    """错误正文：``code`` 是稳定判据，``message`` 是有界的人类可读文案。"""

    model_config = ConfigDict(extra="forbid")

    code: HttpErrorCode
    message: str = Field(min_length=1, max_length=MAX_ERROR_MESSAGE_CHARS)


class HttpErrorEnvelope(BaseModel):
    """所有非 2xx 响应的统一信封：``{"error": {"code": ..., "message": ...}}``（AD-8）。"""

    model_config = ConfigDict(extra="forbid")

    error: HttpErrorDetail


class HealthResponse(BaseModel):
    """``GET /api/health`` 的稳定响应（字段封闭，天然不含密钥/路径/traceback）。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    # 字面量而非 `Literal[HTTP_SERVICE_NAME]`：``Literal`` 只接受字面量（mypy valid-type）。
    # 常量与这里的取值必须一致——由
    # ``tests/network/test_http_protocol.py::test_defaults_match_the_public_contract`` 钉住。
    service: Literal["heagent-http"] = "heagent-http"
    version: str = Field(min_length=1, max_length=64)
    schema_version: Literal["1"] = "1"


# 宿主绝对路径的掩码（协议承诺：客户端文案不含绝对路径，见 ``docs/frame.md`` 4.17）。
#
# 刻意只认「几乎不可能是自然语言」的形态——宁可漏网，也不误伤正常文案：
#
# - Windows 盘符路径（``C:\\…``）与 UNC（``\\\\host\\share``）：形态唯一，且用
#   ``(?<![\w])`` 排除 ``http://`` 这类伪命中（其 ``p`` 前是词字符，故整个 ``://`` 不参与匹配）；
# - POSIX 绝对路径要求**至少三段**（``/a/b/c``）且斜杠前不是词字符/冒号/斜杠：``and/or``
#   （只有一个斜杠、斜杠前是词字符）、``/api/health``（两段路由）、``http://…`` 都不会命中。
#
# 与 ``safe_logging`` 的脱敏同一立场：启发式、非安全边界。掩码只兜住「宿主目录结构外泄」这一条
# 有明确承诺的形态；上游文案本身仍应是面向用户的文本。
_ABS_PATH_RE = re.compile(
    r"(?<![\w])[A-Za-z]:[\\/][^\s\"'<>|]*"
    r"|\\\\[^\s\"'<>|]+"
    r"|(?<![\w:/])/(?:[\w.\-]+/){2,}[\w.\-]*"
)
_MASKED_PATH = "<path>"


def sanitize_message(message: str, *, fallback: str = GENERIC_ERROR_MESSAGE) -> str:
    """把内部错误文案收敛为单行、有界、非空、**不含宿主绝对路径**的客户端文案。

    只做「折叠空白 + 掩码绝对路径 + 截断」，**不做**通用脱敏——上游文案应当是项目自产的面向
    用户文本，凭据类信息由 ``safe_logging`` 负责（那是日志通道）；这里只兜住有明确承诺的那一条
    （见 :data:`_ABS_PATH_RE` 的说明）。协议边界不能假设上游永远干净
    （与 ``cli.tcp._client_error_message`` 同一立场，两处刻意各自持有，避免入口层互相导入）。
    """
    collapsed = " ".join(message.split())
    if not collapsed:
        return fallback
    collapsed = _ABS_PATH_RE.sub(_MASKED_PATH, collapsed)
    if len(collapsed) > MAX_ERROR_MESSAGE_CHARS:
        # 截断到「上限 - 1」再补省略号，保证**返回长度不超过上限本身**——模型字段的
        # ``max_length`` 与这里必须同界，否则净化后的文案反而通不过自己的校验。
        return collapsed[: MAX_ERROR_MESSAGE_CHARS - 1] + "…"
    return collapsed


def error_envelope(code: HttpErrorCode, message: str) -> HttpErrorEnvelope:
    """构造净化后的错误信封（客户端可见文案的唯一出口）。"""
    return HttpErrorEnvelope(error=HttpErrorDetail(code=code, message=sanitize_message(message)))


# ── 运行与事件（Story 49-3 起） ──

# 单条事件文本字段的上限（字符）。工具输出可以是几十 KB（例如 pytest 日志），而 SSE 是给浏览器
# 逐帧看的：截断保证「有界」，并在末尾显式标记，绝不静默丢内容。
MAX_EVENT_TEXT_CHARS = 16_384
_TRUNCATION_SUFFIX = "…[truncated]"

# SSE 活跃流的心跳间隔（秒）：`id:` 与事件 ID 之外的注释帧（`: ping`），只用来保活连接、
# 不占事件序号、不改变客户端游标（AD-4）。
SSE_HEARTBEAT_SECONDS = 15.0

# SSE 心跳帧（注释行；客户端按 SSE 规范忽略，仅用于探测连接是否还活着）。
SSE_HEARTBEAT_FRAME = b": ping\n\n"


class RunStatus(StrEnum):
    """一次网页 Agent 运行的状态机取值（49-4 起其中四个为终态）。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}
)


class RunEventKind(StrEnum):
    """SSE 事件的稳定类型名（小写；客户端按它分派渲染）。"""

    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class HttpUsage(BaseModel):
    """用量元数据（仅来自**该次运行**，不读共享 provider 的最近状态）。"""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class RunRequest(BaseModel):
    """``POST /api/runs`` 的请求体。

    ``extra="forbid"`` 是安全边界的一部分（AD-7）：请求体**不能**携带 provider / system / model /
    工具策略 / 沙箱 / 迭代预算——那些一律取自服务端配置，多一个字段即 400 而不是被静默忽略。
    """

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


class RunStatusResponse(BaseModel):
    """运行状态响应（``POST /api/runs`` 创建成功、``DELETE /api/runs/{id}`` 取消结果共用）。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    status: RunStatus


class RunEventPayload(BaseModel):
    """一条 SSE 事件的负载（``data:`` 的内容，也是 ring buffer 里的元素）。

    ``seq`` 从 1 开始单调递增（AD-4）；同一事件的所有字段都**有界**：文本类字段在写入缓冲前
    由 :func:`clip_text` 截断。
    """

    model_config = ConfigDict(extra="forbid")

    kind: RunEventKind
    seq: int = Field(ge=1)
    text: str = ""
    tool_name: str = ""
    tool_target: str = ""
    tool_output: str = ""
    tool_error: bool = False
    message: str = ""
    model: str | None = None
    usage: HttpUsage | None = None


class RunOutcome(BaseModel):
    """入口层交回的运行结果（服务层据此写终态记录与会话投影）。

    只带**该次运行**的答案与元数据：共享 provider 的路由状态是实例级「最近一次决策」，并发下会
    串味（与 ``cli.tcp._resolve_model`` 同一立场）。
    """

    model_config = ConfigDict(extra="forbid")

    answer: str = ""
    model: str | None = None
    usage: HttpUsage | None = None


class SessionMessage(BaseModel):
    """会话快照里的一条可展示历史（只含已完成运行的 prompt 与最终回答）。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text: str


class SessionResponse(BaseModel):
    """``GET /api/session`` 的响应：进程内单用户会话的当前可展示状态。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    run_id: str | None = None
    status: RunStatus | None = None
    messages: list[SessionMessage]


def clip_text(value: str, *, limit: int = MAX_EVENT_TEXT_CHARS) -> str:
    """把事件文本字段截断到上限，并在末尾显式标记（绝不静默丢内容）。"""
    if len(value) <= limit:
        return value
    return value[:limit] + _TRUNCATION_SUFFIX


__all__ = [
    "GENERIC_ERROR_MESSAGE",
    "HTTP_SCHEMA_VERSION",
    "HTTP_SERVICE_NAME",
    "JSON_ENVELOPE_ALLOWANCE_BYTES",
    "MAX_ERROR_MESSAGE_CHARS",
    "MAX_EVENT_TEXT_CHARS",
    "MAX_PROMPT_CHARS",
    "MAX_REQUEST_BYTES_FOR_MAX_PROMPT",
    "SSE_HEARTBEAT_FRAME",
    "SSE_HEARTBEAT_SECONDS",
    "TERMINAL_RUN_STATUSES",
    "HealthResponse",
    "HttpErrorCode",
    "HttpErrorDetail",
    "HttpErrorEnvelope",
    "HttpUsage",
    "RunEventKind",
    "RunEventPayload",
    "RunOutcome",
    "RunRequest",
    "RunStatus",
    "RunStatusResponse",
    "SessionMessage",
    "SessionResponse",
    "clip_text",
    "error_envelope",
    "sanitize_message",
]
