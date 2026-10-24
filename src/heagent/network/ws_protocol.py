"""WebSocket 帧协议模型（Epic 54）。

本模块只定义 WS 传输层的纯数据契约，不执行 I/O，也不导入运行栈。
事件与错误负载复用 HTTP/SSE 的公开模型，避免两条入口产生漂移。
"""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from heagent.network.http_protocol import (
    SSE_HEARTBEAT_SECONDS,
    HttpErrorEnvelope,
    RunEventPayload,
    RunStatus,
    error_envelope,
)

# 应用层命令按字符数限制；底层 uvicorn 另有字节级帧上限。
WS_MAX_INBOUND_CHARS = 4096
WS_PING_INTERVAL_SECONDS = SSE_HEARTBEAT_SECONDS
WS_PING_TIMEOUT_SECONDS = 20.0
WS_MAX_FRAME_BYTES = 64 * 1024

# WebSocket close-code 的单一来源，供端点和测试复用。
WS_CLOSE_POLICY = 1008
WS_CLOSE_TOO_LARGE = 1009
WS_CLOSE_INTERNAL = 1011
WS_CLOSE_GOING_AWAY = 1001


class WsFrameType(StrEnum):
    """服务端输出帧的封闭类型集合。"""

    EVENT = "event"
    ACK = "ack"
    ERROR = "error"


class WsCommand(StrEnum):
    """客户端首期允许的封闭命令集合。"""

    CANCEL = "cancel"
    PING = "ping"


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


class WsErrorFrame(BaseModel):
    """错误帧；错误码和文案统一来自 HTTP 错误信封。"""

    model_config = ConfigDict(extra="forbid")

    type: WsFrameType = WsFrameType.ERROR
    error: HttpErrorEnvelope


class WsCommandFrame(BaseModel):
    """客户端发来的命令帧。"""

    model_config = ConfigDict(extra="forbid")

    command: WsCommand


def parse_command_frame(text: str) -> WsCommandFrame:
    """解析并校验一条客户端命令帧。

    长度检查先于 JSON 解析，避免把超限输入交给解析器。
    """

    if len(text) > WS_MAX_INBOUND_CHARS:
        raise WsFrameError(WsFrameErrorKind.TOO_LARGE)

    try:
        raw = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        raise WsFrameError(WsFrameErrorKind.MALFORMED) from None

    if not isinstance(raw, dict) or set(raw) != {"command"}:
        raise WsFrameError(WsFrameErrorKind.MALFORMED)

    command = raw.get("command")
    if not isinstance(command, str) or command not in {item.value for item in WsCommand}:
        raise WsFrameError(WsFrameErrorKind.UNKNOWN_COMMAND)

    try:
        return WsCommandFrame.model_validate(raw)
    except ValidationError:
        raise WsFrameError(WsFrameErrorKind.MALFORMED) from None


__all__ = [
    "WS_CLOSE_GOING_AWAY",
    "WS_CLOSE_INTERNAL",
    "WS_CLOSE_POLICY",
    "WS_CLOSE_TOO_LARGE",
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
    "parse_command_frame",
    "error_envelope",
]
