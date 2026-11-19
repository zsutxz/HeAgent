"""HTTP 网页入口的协议模型与稳定错误码（Epic 49）。

本模块是 HTTP 传输层的**协议契约**：请求/响应/错误/事件模型 + 稳定错误码 + 文案净化。
它只依赖 Pydantic 与标准库，不导入任何 ``heagent`` 运行时模块（``tests/test_architecture_contracts.py``
的可执行断言），因此可以被 ``network/http_server/`` 子包、入口层 ``cli/http.py`` 与测试共用。

两条贯穿全 Epic 的协议纪律：

- **稳定错误码**：``HttpErrorCode`` 是客户端可见的封闭集合；新增语义要加成员并同步
  ``docs/frame.md`` 4.17 的错误码表，不能悄悄复用别的码「凑合」。
- **文案有界且脱敏**：客户端只收到 :func:`sanitize_message` 收敛后的单行文本（折叠空白 +
  截断），不含 traceback、异常类名、绝对路径或凭据；诊断细节只进服务端日志（AD-9）。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime  # noqa: TC003 - pydantic 需要在运行期解析该注解
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, overload

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

# HTTP API 的信封版本：出现在健康检查响应里，供客户端判断兼容性（不随 HeAgent 版本走）。
HTTP_SCHEMA_VERSION = "1"

# 服务标识：便于浏览器侧做「连对服务了没」的判据。
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
# 于是任何合法 prompt 在任何客户端编码下都发得进来。394 240 字节在 1 MiB 量级之内，
# 不构成新的资源面。
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
    - **运行类**：``run_conflict`` / ``total_inflight_limit`` / ``unknown_run`` / ``resync_required``；
    - **资源类**：``rate_limited`` / ``timeout``；
    - **边界类**：``origin_forbidden`` / ``not_found`` / ``method_not_allowed``；
    - **服务类**：``agent_error`` / ``shutting_down`` / ``server_error``。
    """

    INVALID_REQUEST = "invalid_request"
    EMPTY_PROMPT = "empty_prompt"
    REQUEST_TOO_LARGE = "request_too_large"
    RUN_CONFLICT = "run_conflict"
    # 服务级在途总额（跨项目共享的可选 ``HTTP_MAX_TOTAL_INFLIGHT``）已满：与「本项目已有运行」是
    # 不同语义（等**任何**一次运行结束 vs 等本项目/本会话），故独立成码。
    TOTAL_INFLIGHT_LIMIT = "total_inflight_limit"
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
    # 原生目录选择：后端不可用 / 已有一次在途。
    DIALOG_UNAVAILABLE = "dialog_unavailable"
    DIALOG_BUSY = "dialog_busy"
    # 配置写入通道：闸门关 / 键只读 / 值非法 / 指纹冲突 / 写失败。
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
    （与 ``http_server.service._client_error_message`` 同一立场，两处刻意各自持有，避免网络层内部互相导入）。
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


# ── 运行与事件 ──

# 单条事件文本字段的上限（字符）。工具输出可以是几十 KB（例如 pytest 日志），而 SSE 是给浏览器
# 逐帧看的：截断保证「有界」，并在末尾显式标记，绝不静默丢内容。
MAX_EVENT_TEXT_CHARS = 16_384
_TRUNCATION_SUFFIX = "…[truncated]"

# SSE 活跃流的心跳间隔（秒）：`id:` 与事件 ID 之外的注释帧（`: ping`），只用来保活连接、
# 不占事件序号、不改变客户端游标。
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


class NotificationKind(StrEnum):
    """只读通知流的稳定类型名（客户端按它分派渲染；开集处理未知值）。"""

    CRON_RESULT = "cron_result"


class CronResultStatus(StrEnum):
    """一次 cron 执行的终局（成功携带最终答案，失败携带错误首行）。"""

    COMPLETED = "completed"
    FAILED = "failed"


class NotificationPayload(BaseModel):
    """通知流里的一条（``WS /api/notifications/ws`` 的事件负载）。

    ``seq`` 由中枢统一分配、**跨作业跨执行单调**（客户端只用它做游标）；文本字段在入缓冲前
    由 :func:`clip_text` 截断——与 ``RunEventPayload`` 同一有界口径。
    """

    model_config = ConfigDict(extra="forbid")

    kind: NotificationKind
    seq: int = Field(ge=1)
    job_id: str = ""
    cron: str = ""
    status: CronResultStatus = CronResultStatus.COMPLETED
    text: str = ""


class RunOutcome(BaseModel):
    """入口层交回的运行结果（服务层据此写终态记录与会话投影）。

    只带**该次运行**的答案与元数据：共享 provider 的路由状态是实例级「最近一次决策」，并发下会
    串味（故只带**本次运行**的元数据）。
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


class RunStatusCounts(BaseModel):
    """保留窗口内运行记录按状态分布（只计数，不携带任何 run 标识）。"""

    model_config = ConfigDict(extra="forbid")

    running: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    cancelled: int = Field(default=0, ge=0)
    timed_out: int = Field(default=0, ge=0)


class WsConnectionCounts(BaseModel):
    """三条 WS 流当前的已登记连接数。

    ``runs`` 是 ``/api/runs/{run_id}/ws`` 的订阅连接（跨 run 合计），``cli`` 是终端旁路
    ``/api/cli/ws``，``notifications`` 是只读通知流 ``/api/notifications/ws``。未注册的流恒为 0。
    """

    model_config = ConfigDict(extra="forbid")

    runs: int = Field(default=0, ge=0)
    cli: int = Field(default=0, ge=0)
    notifications: int = Field(default=0, ge=0)


class ListenerMode(StrEnum):
    """listener 的暴露模式（与 WS 侧 ``WsServerConfig.mode`` 同名同义）。

    ``local`` = 回环绑定（无认证）；``lan`` = 非回环 + ``WS_LAN_NO_AUTH``（内网免认证，只接受私有
    地址字面量）；``external`` = 其余非回环绑定（强制 Bearer）。
    """

    LOCAL = "local"
    LAN = "lan"
    EXTERNAL = "external"


class TlsIdentityInfo(BaseModel):
    """一条 listener 的 TLS 身份面：客户端该 pin 什么、证书还能用多久。

    值的唯一实现源是 :func:`heagent.network.tls_identity.certificate_info`（``heagent tls
    fingerprint`` 打印的也是它），因此状态面与 CLI 逐字一致。

    未启用 TLS：``enabled=false`` 且其余四项一律 ``null``——**不是空串、也不是空列表**。留空值
    会让前端读成「有身份但取不到」，而事实是这条 listener 没有身份可谈（模型级校验钉死）。
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # 长度与 ``TlsCertificateInfo`` 同界（64 位小写 hex / `XXXX-XXXX-XXXX`）：值由 tls_identity
    # 产出，这里只防畸形串进契约。
    spki_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    short_fingerprint: str | None = Field(default=None, min_length=14, max_length=14)
    not_after: datetime | None = None
    san: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _state_is_coherent(self) -> TlsIdentityInfo:
        """「启用 ⇔ 四项齐全」是结构不变量，不靠调用方自觉（半填状态等于在状态面编造身份）。"""
        values = (self.spki_sha256, self.short_fingerprint, self.not_after, self.san)
        if not self.enabled:
            if any(value is not None for value in values):
                raise ValueError("disabled TLS must leave every identity field null")
            return self
        if any(value is None for value in values):
            raise ValueError("enabled TLS requires spki_sha256 / short_fingerprint / not_after / san")
        return self


class ListenerInfo(BaseModel):
    """一条已装配 listener 的事实（地址、实际端口、模式、TLS 身份面）。

    端口取**运行中的** listener（`port=0` 经顺延后只有绑定完成才知道真实值），因此这里不是
    配置回显。``tls`` 只对 WS 有真值：HTTP listener 在产品里恒为明文（身份面恒为未启用）。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["http", "ws"]
    label: str = Field(min_length=1, max_length=32)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=0, le=65535)
    mode: ListenerMode
    tls: TlsIdentityInfo = Field(default_factory=TlsIdentityInfo)


class RoutingPoolInfo(BaseModel):
    """一个路由池的档位名清单（池内名即 ``/model`` 接受的名字）。

    **不含模型名与 base_url**：状态面只回答「有哪些档位」，不回答「档位指向哪个供应商 / 地址」。
    """

    model_config = ConfigDict(extra="forbid")

    pool: str = Field(min_length=1, max_length=64)
    tiers: list[str] = Field(default_factory=list, max_length=64)


class CronJobInfo(BaseModel):
    """一条 cron 作业的**定义与最近一次执行**（不报「下次触发」）。

    网页入口进程**不启动调度器**（``cli/http_console`` 构造后即丢弃），所以「下次触发时刻」在本
    进程里不存在——把它写进模型就是在编造。这里只报落盘事实：作业定义、``last_run`` 与
    ``last_status``。
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=64)
    cron: str = Field(min_length=1, max_length=128)
    last_run: datetime | None = None
    last_status: str = Field(default="", max_length=32)


class ErrorCodeCount(BaseModel):
    """一个稳定错误码及其出现次数（状态面的请求计数分组用）。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    count: int = Field(default=0, ge=0)


class RequestMetricsSummary(BaseModel):
    """请求计数与延迟（本进程自启动以来；延迟是**有界窗口**内的中位数/最大值）。

    计数在响应发出**之后**记账，因此读状态的那一次请求本身不在本次快照里（差一，不是漏计）。
    """

    model_config = ConfigDict(extra="forbid")

    total: int = Field(default=0, ge=0)
    status_2xx: int = Field(default=0, ge=0)
    status_3xx: int = Field(default=0, ge=0)
    status_4xx: int = Field(default=0, ge=0)
    status_5xx: int = Field(default=0, ge=0)
    latency_p50_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    latency_max_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    error_codes: list[ErrorCodeCount] = Field(default_factory=list, max_length=16)


class StatusResponse(BaseModel):
    """``GET /api/status`` 的稳定响应：进程自身状态的只读聚合投影。

    字段封闭且只含枚举 / 非负整数 / 有界文本——**不含**绝对路径、凭据值、traceback（与
    :class:`HealthResponse` 同一立场）。数值一律由入口层注入的来源提供，传输层不扫盘、不采样。
    """

    model_config = ConfigDict(extra="forbid")

    # 字面量而非 `Literal[HTTP_SERVICE_NAME]`：``Literal`` 只接受字面量（mypy valid-type），
    # 常量与这里的取值必须一致（由 ``tests/test_http_status_api.py`` 的同款断言钉住）。
    service: Literal["heagent-http"] = "heagent-http"
    version: str = Field(min_length=1, max_length=64)
    schema_version: Literal["1"] = "1"
    # 作用域**不同**，消费方不得当成比率渲染（``active_runs`` 是服务级、``max_inflight_runs`` 是每项目级）：
    # 两个项目各跑一个 run 时取值为 2 / 1，而单项目上限仍是 1。
    active_runs: int = Field(default=0, ge=0)
    max_inflight_runs: int = Field(default=0, ge=0)
    run_records: int = Field(default=0, ge=0)
    run_status: RunStatusCounts = Field(default_factory=RunStatusCounts)
    ws_connections: WsConnectionCounts = Field(default_factory=WsConnectionCounts)
    background_tasks: int = Field(default=0, ge=0)
    # ---- 部署面（71.2）：只报名字与布尔，不含密钥值、base_url 与绝对路径 ----
    listeners: list[ListenerInfo] = Field(default_factory=list, max_length=4)
    sandbox_backend: str = Field(default="", max_length=32)
    config_write_enabled: bool = False
    active_provider: str = Field(default="", max_length=64)
    routing_pools: list[RoutingPoolInfo] = Field(default_factory=list, max_length=16)
    # ---- 依赖态（71.3）：启动时刻 / 作业定义 / 资产计数 ----
    started_at: datetime | None = None
    uptime_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cron_jobs: list[CronJobInfo] = Field(default_factory=list, max_length=32)
    skill_count: int = Field(default=0, ge=0)
    memory_facts: int = Field(default=0, ge=0)
    # ---- 资源（71.4）：不可得即 null（绝不填 0 冒充），并标注采样通路 ----
    rss_bytes: int | None = Field(default=None, ge=0)
    threads: int | None = Field(default=None, ge=0)
    cpu_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    resource_source: str = Field(default="unavailable", max_length=32)
    # ---- 请求计数与延迟（71.5）：有界窗口内的观测值 ----
    requests: RequestMetricsSummary = Field(default_factory=RequestMetricsSummary)


def clip_text(value: str, *, limit: int = MAX_EVENT_TEXT_CHARS) -> str:
    """把事件文本字段截断到上限，并在末尾显式标记（绝不静默丢内容）。"""
    if len(value) <= limit:
        return value
    return value[:limit] + _TRUNCATION_SUFFIX


def cursor_out_of_window(cursor: int | None, oldest_seq: int | None) -> bool:
    """游标是否已落在事件窗口之外（``resync_required`` 判据的算术**单源**）。

    语义（严格大于）：客户端说「我收到 N」时，只要 ``N >= oldest_seq - 1`` 就能无缝续读；
    更小的 N 意味着中间事件已被 ring buffer 淘汰，**必须**重新同步而不是发一条看似连续的流。
    没有游标等价于「从头读」：若窗口已淘汰开头（``oldest_seq > 1``），同样要求重新同步；
    空缓冲（``oldest_seq is None``）永远不需要。

    WS run 订阅（:mod:`~heagent.network.ws_server`）、SSE（``http_server.stream_events`` 前的
    服务层判定）与两条只读流（:class:`~heagent.network.event_stream_hub.EventStreamHub`）共用
    本函数——三处各写一遍迟早漂移（活动台账 A54⑤）。
    """
    if oldest_seq is None:
        return False
    effective = 0 if cursor is None else max(0, cursor)
    return effective < oldest_seq - 1


@overload
def replay_then_follow(
    snapshot: Sequence[RunEventPayload],
    *,
    cursor: int | None,
    is_terminal: bool,
    queue: asyncio.Queue[RunEventPayload | None],
    heartbeat_seconds: None = None,
) -> AsyncIterator[RunEventPayload]:
    """无心跳形态（WS 用）：输出只含事件，队列的 ``None`` 哨兵仅表示流结束。"""


@overload
def replay_then_follow(
    snapshot: Sequence[RunEventPayload],
    *,
    cursor: int | None,
    is_terminal: bool,
    queue: asyncio.Queue[RunEventPayload | None],
    heartbeat_seconds: float,
) -> AsyncIterator[RunEventPayload | None]:
    """带心跳形态（SSE 用）：空闲超时会额外 ``yield None``，调用方须自行跳过它。"""


async def replay_then_follow(
    snapshot: Sequence[RunEventPayload],
    *,
    cursor: int | None,
    is_terminal: bool,
    queue: asyncio.Queue[RunEventPayload | None],
    heartbeat_seconds: float | None = None,
) -> AsyncIterator[RunEventPayload | None]:
    """「快照重放 + 水位去重」的**唯一**实现：先重放缓冲快照，再跟随实时队列（A54④）。

    WS run 订阅（:mod:`~heagent.network.ws_server`）与 SSE（``http_server.stream_events``）
    曾各抄一份这段循环——登记与快照之间存在真实 ``await`` 窗口：窗口内 emit 的事件会
    「既进重放快照、又进实时队列」，靠**已重放水位**（``replayed_upto = max(cursor, 快照最大
    seq)``）去重才能保证「不重复」契约成立。

    - 重放只发**严格大于** ``cursor`` 的部分（``cursor=None`` = 从头读）；缺口的判定由调用方
      在建立流之前用 :func:`cursor_out_of_window` 做完，这里只管「不重复」；
    - ``is_terminal`` **必须与快照同拍捕获**（调用方在同一个同步段内 ``tuple(缓冲)`` 后立即读
      终态，两读之间不得有 ``await``）——终态事件先于流结束（AD-4）；
    - 队列哨兵 ``None`` = 流到此结束，**绝不**作为事件 ``yield``；
    - ``heartbeat_seconds`` 给定时（SSE 用），队列空闲超时 ``yield None`` 心跳（不占事件 ID、
      不推进游标）；WS 传 ``None``（协议级 ping 已由 Uvicorn 负责，不发应用层心跳）。
    """
    replayed_upto = max(
        cursor if cursor is not None else 0,
        max((payload.seq for payload in snapshot), default=0),
    )
    for payload in snapshot:
        if cursor is None or payload.seq > cursor:
            yield payload
    if is_terminal:
        return
    while True:
        if heartbeat_seconds is None:
            item = await queue.get()
        else:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                # 空闲期的保活帧：客户端（及中间层）据此判定连接仍然活着。超时取消的是
                # ``queue.get()`` 本身，不会丢掉已在队列里的事件。
                yield None
                continue
        if item is None:
            return
        if item.seq <= replayed_upto:
            continue
        yield item


class HttpRunConflictError(RuntimeError):
    """已有在途运行（或服务正在关闭 / **服务级总额已满**），拒绝新运行（AD-3 的单运行约束）。

    ``code`` 是给客户端的稳定码：项目级冲突与服务关闭都是 ``run_conflict``，服务级总额（跨项目
    共享的 ``max_total_inflight``）是 ``total_inflight_limit``——两者「等谁结束」的语义不同。

    **住在协议层**（Epic 56 Story 56-3 自 ``http_server`` 迁入）：经 WS 提交 run 与
    ``POST /api/runs`` 走同一个 ``HttpRunService.start_run``，两条传输层都要把同一个冲突映射成
    错误信封。放在协议模块 ⇒ ``ws_server`` 不必导入 ``http_server``（传输层之间的反向依赖）。
    ``http_server`` 保留 re-export，既有导入点不受影响。
    """

    def __init__(self, message: str, *, code: HttpErrorCode = HttpErrorCode.RUN_CONFLICT) -> None:
        super().__init__(message)
        self.code = code


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
    "HttpRunConflictError",
    "CronJobInfo",
    "ErrorCodeCount",
    "CronResultStatus",
    "HttpUsage",
    "ListenerInfo",
    "ListenerMode",
    "RoutingPoolInfo",
    "NotificationKind",
    "NotificationPayload",
    "RunEventKind",
    "RunEventPayload",
    "RunOutcome",
    "RunRequest",
    "RunStatus",
    "RequestMetricsSummary",
    "RunStatusCounts",
    "RunStatusResponse",
    "SessionMessage",
    "SessionResponse",
    "StatusResponse",
    "TlsIdentityInfo",
    "WsConnectionCounts",
    "clip_text",
    "cursor_out_of_window",
    "error_envelope",
    "replay_then_follow",
    "sanitize_message",
]
