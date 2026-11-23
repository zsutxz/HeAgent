"""WebSocket 帧协议模型（Epic 54）。

本模块只定义 WS 传输层的纯数据契约，不执行 I/O，也不导入运行栈。
事件与错误负载复用 HTTP/SSE 的公开模型，避免两条入口产生漂移。
"""

from __future__ import annotations

import json
from enum import StrEnum

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
    """

    HELLO = "hello"
    EVENT = "event"
    ACK = "ack"
    ERROR = "error"
    NOTIFICATION = "notification"


class WsCommand(StrEnum):
    """客户端允许的封闭命令集合。

    ``run`` 只在**集合级**端点 ``WS /api/runs/ws`` 上有效（Epic 56 D2：经 WS 提交 run）；
    单 run 端点与 CLI 旁路收到它一律回 ``invalid_request``（提交能力不外溢）。
    """

    CANCEL = "cancel"
    PING = "ping"
    RUN = "run"


#: 命令 → **允许出现**的键（字段白名单）。解析器与模型校验器共读这一张表：新增命令不登记即
#: 被 ``set(_FRAME_FIELDS) == set(WsCommand)`` 判据拦下，「按命令判字段」的规则因此只有一份。
_FRAME_FIELDS: dict[WsCommand, frozenset[str]] = {
    WsCommand.RUN: frozenset({"command", "prompt", "project_id"}),
    WsCommand.CANCEL: frozenset({"command"}),
    WsCommand.PING: frozenset({"command"}),
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
    """

    model_config = ConfigDict(extra="forbid")

    command: WsCommand
    prompt: str | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=16)

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


def parse_command_frame(text: str) -> WsCommandFrame:
    """解析并校验一条客户端命令帧。

    长度检查先于 JSON 解析，避免把超限输入交给解析器。两级上限：``WS_MAX_INBOUND_CHARS``
    是总闸（含 prompt），``WS_MAX_COMMAND_CHARS`` 再把非 ``run`` 命令钉回小上限——解析出命令
    之后才知道该用哪一档，因此这一档检查只能在 JSON 解析之后做。字段判定与模型共用
    :data:`_FRAME_FIELDS`：不在白名单的键、以及白名单内未出现的必带键，都判 ``malformed``。
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
    "parse_command_frame",
    "required_frame_fields",
    "error_envelope",
]
