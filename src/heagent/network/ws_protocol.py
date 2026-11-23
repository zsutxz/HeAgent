"""WebSocket 帧协议模型与传输端口（Epic 54）。

本模块只定义 WS 传输层的纯数据契约——帧模型、命令枚举与注入端口的 Protocol——不执行 I/O，
也不导入运行栈。事件与错误负载复用 HTTP/SSE 的公开模型，避免两条入口产生漂移。
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from heagent.network.http_protocol import (
    JSON_ENVELOPE_ALLOWANCE_BYTES,
    MAX_PROMPT_CHARS,
    MAX_REQUEST_BYTES_FOR_MAX_PROMPT,
    SSE_HEARTBEAT_SECONDS,
    HttpErrorEnvelope,
    NotificationPayload,
    RunEventPayload,
    RunStatus,
    error_envelope,
)

# 应用层命令按字符数限制；底层 uvicorn 另有字节级帧上限。
# 三条上限：
# - ``WS_MAX_FRAME_BYTES`` = uvicorn ``ws_max_size``（字节）：必须**容得下协议允许的最大 prompt**
#   （与 HTTP 的请求体上限同源，见 ``MAX_REQUEST_BYTES_FOR_MAX_PROMPT``），否则会出现「字符上限
#   远未到、传输层先把连接掐了」的口径矛盾；它对出站帧同样生效（服务端事件帧远小于此）。
# - ``WS_MAX_INBOUND_CHARS`` = 入站文本的**廉价预检**上限（字符）。按**最坏 JSON 转义**推算：
#   ``ensure_ascii=True``（多数 JSON 库的默认）下每个中日韩字符变成 ``\uXXXX``（6 个 ASCII 字符），
#   于是协议允许的最大 prompt 会产生约 197 K 字符的文本。上限若按原始字符数（32 K）来定，
#   **合法**的最大 prompt 会被协议层挡在门外（实现期实测踩到 1009），所以这里按转义后的最坏值算。
# - ``WS_MAX_COMMAND_CHARS`` = **非 run** 帧（cancel / ping）的上限（字符）：命令面刻意保持最小，
#   不给「用 300 KiB 的 ping 让服务端解析」留口子。
WS_MAX_FRAME_BYTES = MAX_REQUEST_BYTES_FOR_MAX_PROMPT
WS_MAX_INBOUND_CHARS = 6 * MAX_PROMPT_CHARS + JSON_ENVELOPE_ALLOWANCE_BYTES
WS_MAX_COMMAND_CHARS = 4096
WS_PING_INTERVAL_SECONDS = SSE_HEARTBEAT_SECONDS
WS_PING_TIMEOUT_SECONDS = 20.0

# WebSocket close-code 的单一来源，供端点和测试复用。
WS_CLOSE_POLICY = 1008
WS_CLOSE_TOO_LARGE = 1009
WS_CLOSE_INTERNAL = 1011
WS_CLOSE_GOING_AWAY = 1001


class WsFrameType(StrEnum):
    """服务端输出帧的封闭类型集合（Epic 58 起多了只读通知流的一档）。

    ``hello`` 是**连接首帧**（56-9）：``accept()`` 成功后立即下发、先于任何 event / ack /
    error / notification 帧，内容只有服务端版本。它不属于任何一条流（没有 ``run_id``、没有
    ``seq``、不可续传）——客户端据此判断对端版本与协议兼容性，连「随后被配额 / 游标 / 关停
    判据拒绝」的连接也能先拿到它。

    ``projects``（E75）是 ``projects`` 命令的**响应**帧，与 ``notification`` 同档（一问一答的
    非流式结果）。不塞进 ``event`` 是刻意的：事件信封（``{type,event}``）与负载模型已被逐字节
    golden 钉死，项目列表既不是 run 事件、也没有 ``run_id`` / ``seq``，借道 ``event`` 会同时
    破坏那两个契约。新增一档的代价只是客户端要多认一个类型，不认识时可跳过。
    """

    HELLO = "hello"
    EVENT = "event"
    ACK = "ack"
    ERROR = "error"
    NOTIFICATION = "notification"
    PROJECTS = "projects"


class WsCommand(StrEnum):
    """客户端允许的封闭命令集合。

    ``run`` 只在**集合级**端点 ``WS /api/runs/ws`` 上有效（Epic 56 D2：经 WS 提交 run）；
    单 run 端点与 CLI 旁路收到它一律回 ``invalid_request``（提交能力不外溢）。

    ``cancel_run`` 是 ``run`` 的对偶：目标 run 写在帧里（``run_id`` 必带），因此集合级端点能取消
    任意一条运行；单 run 端点只接受「等于本连接绑定的 run」的目标，只读 listener 一律拒绝。
    它与 ``cancel`` 复用**同一个** ``service.cancel_run(run_id)`` 端口——取消实现只有一份，两处
    差别仅在目标的来源（连接绑定 vs 帧字段）。

    ``projects`` 是**集合级端点**的项目列表查询（E75）：只带 ``command``，没有目标字段——项目
    归属由客户端拿响应帧里的 ``id`` 自行记住，服务端不维护「这条连接在看哪个项目」。
    """

    CANCEL = "cancel"
    CANCEL_RUN = "cancel_run"
    PING = "ping"
    PROJECTS = "projects"
    RUN = "run"


#: 命令 → **允许出现**的键（字段白名单）。解析器与模型校验器共读这一张表：新增命令不登记即
#: 被 ``set(_FRAME_FIELDS) == set(WsCommand)`` 判据拦下，「按命令判字段」的规则因此只有一份。
_FRAME_FIELDS: dict[WsCommand, frozenset[str]] = {
    WsCommand.RUN: frozenset({"command", "prompt", "project_id"}),
    WsCommand.CANCEL: frozenset({"command"}),
    WsCommand.CANCEL_RUN: frozenset({"command", "run_id"}),
    WsCommand.PING: frozenset({"command"}),
    WsCommand.PROJECTS: frozenset({"command"}),
}

#: 允许**缺席**（一旦出现仍须合法）的字段：只有 ``run`` 的 ``project_id``——缺省即「启动工作区」，
#: 与这条字段出现之前的旧路径逐字等价。白名单内其余键一律必带，所以不需要第二张「必带表」，
#: 也就没有两表漂移的余地。
_OPTIONAL_FRAME_FIELDS: frozenset[str] = frozenset({"project_id"})


def required_frame_fields(command: WsCommand) -> frozenset[str]:
    """按白名单推出**必带**键：命令允许出现的键里，除可选字段外都要出现。"""
    return _FRAME_FIELDS[command] - _OPTIONAL_FRAME_FIELDS


def _unexpected_fields(command: WsCommand, present: frozenset[str]) -> frozenset[str]:
    """出现在帧里、但不属于该命令白名单的键。"""
    return present - _FRAME_FIELDS[command]


class WsFrameErrorKind(StrEnum):
    """命令帧解析失败的稳定分类。"""

    TOO_LARGE = "too_large"
    MALFORMED = "malformed"
    UNKNOWN_COMMAND = "unknown_command"


class WsFrameError(ValueError):
    """命令帧不符合协议时抛出的有界异常。"""

    def __init__(self, kind: WsFrameErrorKind) -> None:
        self.kind = kind
        super().__init__(kind.value)


class WsHelloFrame(BaseModel):
    """连接首帧：服务端当前版本（``heagent.__version__``，由入口层注入）。

    与其余四类帧**分开**定义而不是给它们加字段：它描述的是「这条连接的两端」，不是任何一条
    流的内容——不带 ``run_id`` / ``seq`` / 事件载荷，也不进入环形缓冲，因此续传
    （``?last_event_id``）与游标语义逐字不变。客户端应把它当作「可忽略的类型」处理
    （不认识就跳过），版本号是唯一语义内容。生产装配（入口层 ``cli/http``）注入 ``heagent.__version__``，由 wiring 测试钉死；空版本=测试
    装配形态，端点侧跳过并记 debug（不静默）。
    """

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.HELLO
    version: str


class WsEventFrame(BaseModel):
    """事件帧；事件负载保持嵌套，直接复用 SSE 模型。"""

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.EVENT
    event: RunEventPayload


class WsAckFrame(BaseModel):
    """命令处理成功的确认帧。"""

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.ACK
    command: WsCommand
    run_id: str
    status: RunStatus


class WsCliEventFrame(BaseModel):
    """CLI 旁路事件帧（Epic 55）：跨轮次的事件流。

    与 :class:`WsEventFrame` **分开**而不是给它加字段：``/api/runs/{run_id}/ws`` 一个连接只对应
    一个 run，``run_id`` 由 URL 承担，既有契约因此逐字不变；CLI 旁路是一条跨轮次的流，
    ``run_id`` 必须逐帧携带，订阅者才能把「终端里的不同轮」区分开。
    """

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.EVENT
    run_id: str = ""
    event: RunEventPayload


class WsCliAckFrame(BaseModel):
    """CLI 旁路的命令确认帧。

    **不带** ``RunStatus``：旁路不拥有运行（终端才是所有者），把 HTTP 运行状态机搬过来会给客户端
    一个「这个连接能控制运行」的假象。``run_id`` 为空串表示「此刻终端没有在跑的轮次」。
    """

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.ACK
    command: WsCommand
    run_id: str = ""


class WsNotificationFrame(BaseModel):
    """通知流帧（Epic 58）：一次 cron 执行的结果。

    与 :class:`WsEventFrame` 分开而不是复用：通知不是 run 的事件（没有 ``run_id``、不能取消、
    没有终态状态机），把它塞进 run 的事件契约会让客户端误以为能订阅/控制一条运行。
    """

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.NOTIFICATION
    notification: NotificationPayload


class ProjectChannelEntry(BaseModel):
    """项目列表帧里的一条：客户端能操作这个项目所需的**全部**信息。

    恰三项、``extra="forbid"``：``path`` / ``session_id`` / 历史统计一类的东西都不能进来——
    帧面越宽，客户端与服务端就越容易在「谁维护项目元数据」上打架。``available`` 是注册表探针的
    结论（目录是否在盘上），不可用不等于「不存在」：客户端应把它显示成禁用项而不是删掉。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=16)
    name: str
    available: bool


class WsProjectsFrame(BaseModel):
    """``projects`` 命令的响应帧：项目列表 + 注册表健康态。

    ``registry_state`` 是**两值**（``ok`` / ``unreadable``），刻意不复用 HTTP 的细分错误码：注册表
    读不出来时客户端能做的只有一件事——提示「项目列表可能不完整」，此时把 ``projects`` 当空表
    展示、把状态说清楚，比回一条错误帧更有用（``projects`` 字段因此仍是一条合法列表）。
    """

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.PROJECTS
    projects: list[ProjectChannelEntry]
    registry_state: Literal["ok", "unreadable"]


class WsErrorFrame(BaseModel):
    """错误帧；错误码和文案统一来自 HTTP 错误信封。"""

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.ERROR
    error: HttpErrorEnvelope


class WsCommandFrame(BaseModel):
    """客户端发来的命令帧。

    字段规则由 :data:`_FRAME_FIELDS` 单一映射表决定：``prompt`` 与 ``project_id`` **只对**
    ``run`` 有效，其中 ``prompt`` 必带、``project_id`` 可选（缺省 = 启动工作区，旧路径逐字不变）。
    规则放在模型里而不是只放解析器里，是为了让运行时与测试共用同一份；解析器另在 JSON 层先按
    同一张表判一次，好让「字段拼错」在进模型之前就是 ``malformed``。

    ``project_id`` **不做 strip**：它由项目注册表的 ``project_id_for()``（``"p" + sha256[:8]``）
    或字面量 ``"default"`` 产出，客户端必须原样回传——strip 会造出第二个合法拼写。

    ``run_id`` 与 ``project_id`` 相反：它只对 ``cancel_run`` 有效且**必带**（``cancel`` 沿用连接
    绑定，多带一个目标字段即 ``malformed``），取消目标由客户端显式给出。它同样**不做 strip**：
    run id 是服务端签发的 opaque 短 id，客户端必须原样回传。
    """

    model_config = ConfigDict(extra="forbid")

    command: WsCommand
    prompt: str | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=16)
    run_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _validate_fields_per_command(self) -> WsCommandFrame:
        # 显式 null 与缺席同义（值为 None 不计入「出现」）：``{"command":"run","prompt":null}``
        # 因此按「缺 prompt」处理，与 ``_FRAME_FIELDS`` 的白名单语义保持一致。
        present = frozenset(self.model_dump(exclude_none=True))
        missing = required_frame_fields(self.command) - present
        if missing:
            raise ValueError(f"the {self.command.value} command requires {', '.join(sorted(missing))}")
        unexpected = _unexpected_fields(self.command, present)
        if unexpected:
            raise ValueError(f"{', '.join(sorted(unexpected))} is not valid for the {self.command.value} command")
        return self


# ---------------------------------------------------------------------------
# 传输端口：适配器与注入的服务回调之间的最小契约。
# 与帧模型同属「纯契约」——只声明签名，不执行 I/O，也不认识项目目录或运行栈。
# ---------------------------------------------------------------------------


class WebSocketLike(Protocol):
    """Starlette WebSocket 的最小结构化接口。"""

    scope: dict[str, Any]
    path_params: dict[str, Any]
    query_params: Any

    async def accept(self) -> None:
        """实现方在此完成握手（对应真实 websocket 的 `accept`）。"""

    ...

    async def close(self, code: int = 1000) -> None:
        """实现方以给定关闭码结束连接（认证失败用 1008）。"""

    ...

    async def receive_text(self) -> str:
        """实现方读一条文本帧；超长帧由实现方按 `WS_MAX_INBOUND_CHARS` 拒绝。"""

    ...

    async def send_text(self, data: str) -> None:
        """实现方发一条文本帧（服务端到客户端的唯一出口）。"""

    ...


class RunWebSocketService(Protocol):
    """ws_server 所需的最小运行服务端口。

    Epic 56 D1：WS 连接额度自 ``HttpServerConfig`` 迁入 ``WsServerConfig``，经
    :func:`build_ws_endpoint` 的 ``max_connections`` 参数注入——端点因此不感知任何配置类。
    Epic 56 D2：``start_run`` 是**集合级端点**（经 WS 提交 run）的入口，与 ``POST /api/runs``
    共用同一个实现（名额判定/记录/任务生成只有一处）。
    """

    _closing: bool

    def run(self, run_id: str) -> Any | None:
        """按 run_id 取 run 记录；不存在返回 `None`（与「已结束但记录还在」区分开）。"""

    ...

    def needs_resync(self, record: Any, last_event_id: int | None) -> bool:
        """判断客户端是否需要重置：`last_event_id` 落后于记录的可回放窗口时为真。"""

    ...

    async def start_run(self, prompt: str) -> Any:
        """为一条 prompt 起 run 并返回记录（提交端点背后的一次调用）。"""

    ...

    async def cancel_run(self, run_id: str) -> Any | None:
        """取消指定 run 并返回记录（幂等：已终止的 run 仍回它的终态记录）；不存在返回 `None`。"""

    ...

    def register_ws(self, connection_id: str, run_id: str, websocket: WebSocketLike) -> None:
        """登记一个 WS 连接与 run 的绑定（推送与断线清理都靠这张表）。"""

    ...

    def unregister_ws(self, connection_id: str) -> None:
        """注销连接绑定；对未知 id 幂等无操作。"""

    ...


class SubmittedRun(BaseModel):
    """提交成功的**收窄**结果：刻意不含 ``session_id``。

    入口层的 ``ProjectRunResponse`` 带 ``session_id``；网络层若原样透传，就等于把「这个 run
    接续了服务端的哪个会话」交给远程客户端，而帧面只需要客户端能操作的两项。
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    status: RunStatus


class ProjectChannelService(Protocol):
    """项目通道端口（与 :class:`RunWebSocketService` **并列**，不并入它）。

    实现方住在入口层（``cli/ws_project_adapter``），网络层只按这两个签名调用。签名里没有
    路径 / workspace / session 类参数，``project_id`` 是不透明短 id——「传输层不认识项目目录」
    因此是结构保证，而不是纪律要求。失败一律抛 :class:`HttpRunConflictError`（``code`` 取自
    ``HttpErrorCode``），端点侧只转译错误码、不改写语义。

    三条实现方义务（签名看不出来，但不遵守会变成远程客户端眼里的「卡住」或「重复提交」）：

    - **超时是实现方义务**：端口没有 ``timeout`` 参数，端点不做超时兜底——阻塞多久由实现方保证
      有界。提交连接不订阅事件，端口迟迟不返回时客户端只会看到「一直没有 ack」。
    - **提交失败不做原子性保证、无幂等键**：``start_project_run`` 抛错并不等于「什么都没发生」
      （可能已分配 run id、已占名额），重试可能重复提交；服务端不替客户端去重。
    - **错误消息不含路径**：``HttpRunConflictError`` 的文案会原样进错误帧给远程客户端看，不得
      回显项目目录或绝对路径。
    """

    async def start_project_run(self, project_id: str, prompt: str) -> SubmittedRun:
        """在该项目围栏内起 run 并返回收窄后的提交结果。"""
        ...

    async def ensure_available(self, project_id: str) -> str:
        """提交前置校验（不占名额）：可用时原样返回 ``project_id``，否则抛 ``HttpRunConflictError``。"""
        ...

    async def list_projects(self) -> WsProjectsFrame:
        """列出可提交的项目，组装成**已投影**的响应帧。

        返回帧模型而不是 ``(entries, registry_state)`` 元组：注册表类型（``pub.projects`` 的
        ``ProjectEntry`` / ``ProjectRegistryHealth``）到帧模型的翻译因此全部留在实现方（入口层），
        网络层既不认识注册表、也不持有第二份投影逻辑。
        """
        ...


def parse_command_frame(text: str) -> WsCommandFrame:
    """解析并校验一条客户端命令帧。

    长度检查先于 JSON 解析，避免把超限输入交给解析器。两级上限：``WS_MAX_INBOUND_CHARS`` 是总闸
    （含 prompt），``WS_MAX_COMMAND_CHARS`` 再把非 ``run`` 命令（``cancel`` / ``cancel_run`` /
    ``ping`` / ``projects``）钉回小上限——解析出命令之后才知道该用哪一档，因此这一档检查只能在
    JSON 解析之后做。字段判定与模型共用 :data:`_FRAME_FIELDS`：不在白名单的键、以及白名单内未
    出现的必带键，都判 ``malformed``（``cancel_run`` 因此缺 ``run_id`` 即 ``malformed``、带
    ``project_id`` 也是 ``malformed``）。
    """

    if len(text) > WS_MAX_INBOUND_CHARS:
        raise WsFrameError(WsFrameErrorKind.TOO_LARGE)

    try:
        raw = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        raise WsFrameError(WsFrameErrorKind.MALFORMED) from None

    if not isinstance(raw, dict):
        raise WsFrameError(WsFrameErrorKind.MALFORMED)

    command = raw.get("command")
    if not isinstance(command, str) or command not in {item.value for item in WsCommand}:
        raise WsFrameError(WsFrameErrorKind.UNKNOWN_COMMAND)

    parsed_command = WsCommand(command)
    if parsed_command is not WsCommand.RUN and len(text) > WS_MAX_COMMAND_CHARS:
        # 先判大小再判语义：上限是资源保护，比「字段拼错」更该优先给出。
        raise WsFrameError(WsFrameErrorKind.TOO_LARGE)
    keys = frozenset(raw)
    if _unexpected_fields(parsed_command, keys) or not required_frame_fields(parsed_command) <= keys:
        raise WsFrameError(WsFrameErrorKind.MALFORMED)

    try:
        return WsCommandFrame.model_validate(raw)
    except ValidationError:
        raise WsFrameError(WsFrameErrorKind.MALFORMED) from None


__all__ = [
    "WS_CLOSE_GOING_AWAY",
    "WS_CLOSE_INTERNAL",
    "WS_CLOSE_POLICY",
    "WS_CLOSE_TOO_LARGE",
    "WS_MAX_COMMAND_CHARS",
    "WS_MAX_FRAME_BYTES",
    "WS_MAX_INBOUND_CHARS",
    "WS_PING_INTERVAL_SECONDS",
    "WS_PING_TIMEOUT_SECONDS",
    "ProjectChannelEntry",
    "ProjectChannelService",
    "RunWebSocketService",
    "SubmittedRun",
    "WebSocketLike",
    "WsAckFrame",
    "WsCliAckFrame",
    "WsCliEventFrame",
    "WsCommand",
    "WsCommandFrame",
    "WsErrorFrame",
    "WsEventFrame",
    "WsFrameError",
    "WsFrameErrorKind",
    "WsFrameType",
    "WsNotificationFrame",
    "WsProjectsFrame",
    "parse_command_frame",
    "required_frame_fields",
    "error_envelope",
]
