"""HTTP 网页入口的协议模型与稳定错误码（Epic 49）。

本模块是 HTTP 传输层的**协议契约**：请求/响应/错误/事件模型 + 稳定错误码 + 文案净化。
它只依赖 Pydantic 与标准库，不导入任何 ``heagent`` 运行时模块（``tests/test_architecture_contracts.py``
的可执行断言），因此可以被 ``network/http_server.py``、入口层 ``cli_http.py`` 与测试共用。

两条贯穿全 Epic 的协议纪律：

- **稳定错误码**：``HttpErrorCode`` 是客户端可见的封闭集合；新增语义要加成员并同步
  ``docs/frame.md`` 4.17 的错误码表，不能悄悄复用别的码「凑合」。
- **文案有界且脱敏**：客户端只收到 :func:`sanitize_message` 收敛后的单行文本（折叠空白 +
  截断），不含 traceback、异常类名、绝对路径或凭据；诊断细节只进服务端日志（AD-9）。
"""

from __future__ import annotations

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

# 兜底文案：上游异常没有可用 message 时使用（绝不回吐异常类型名）。
GENERIC_ERROR_MESSAGE = "request failed"


class HttpErrorCode(StrEnum):
    """客户端可见的稳定错误码（封闭集合，见 ``docs/frame.md`` 4.17 的错误码表）。

    语义分组（同一分组内的码可被客户端用同一套文案处理）：

    - **输入类**：``invalid_request`` / ``empty_prompt`` / ``request_too_large``；
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


def sanitize_message(message: str, *, fallback: str = GENERIC_ERROR_MESSAGE) -> str:
    """把内部错误文案收敛为单行、有界、非空的客户端文案。

    只做「折叠空白 + 截断」，**不做**路径/凭据净化——上游文案应当是项目自产的面向用户文本。
    若将来出现带路径或类名的上游文案，净化必须加在这里：协议边界不能假设上游永远干净
    （与 ``cli_tcp._client_error_message`` 同一立场，两处刻意各自持有，避免入口层互相导入）。
    """
    collapsed = " ".join(message.split())
    if not collapsed:
        return fallback
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


class RunCreatedResponse(BaseModel):
    """``POST /api/runs`` 的成功响应。"""

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
    串味（与 ``cli_tcp._resolve_model`` 同一立场）。
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
    "MAX_ERROR_MESSAGE_CHARS",
    "MAX_EVENT_TEXT_CHARS",
    "MAX_PROMPT_CHARS",
    "TERMINAL_RUN_STATUSES",
    "HealthResponse",
    "HttpErrorCode",
    "HttpErrorDetail",
    "HttpErrorEnvelope",
    "HttpUsage",
    "RunCreatedResponse",
    "RunEventKind",
    "RunEventPayload",
    "RunOutcome",
    "RunRequest",
    "RunStatus",
    "SessionMessage",
    "SessionResponse",
    "clip_text",
    "error_envelope",
    "sanitize_message",
]
