"""CLI 终端运行的旁路事件中枢（Epic 55；Epic 58 D3 起是本模块对通用核的薄适配）。

**定位**：CLI（单次 / 交互）里那一轮 run 由**终端**持有——不为它建 ``_RunRecord``、不占
``HTTP_MAX_INFLIGHT_RUNS`` 名额、不写 HTTP 会话历史、不开取消通道。本模块只把这一轮的事件按
同一套 ``RunEventPayload`` 契约广播给旁路订阅者（``WS /api/cli/ws``），因此客户端拿到的是
「观众席」而不是「控制台」。

三层语义分工：

- **通用核** :class:`~heagent.network.event_stream_hub.EventStreamHub` —— seq / 环形缓冲 /
  游标 / 背压踢人 / 有界关停（两条只读流共用，不复制第二份实现）；
- **本模块** —— 「当前轮次」语义（``begin_run`` / ``end_run`` / ``active_run_id``）与
  ``RunEventPayload`` 的字段有界化；
- **端点** —— ``ws_server.build_cli_ws_endpoint``（只读、拒绝 ``cancel``、额度按整条流计）。

三条不变量（与通用核一致）：写侧同步无 ``await``；``publish_*`` 绝不抛；背压与 SSE/WS 同语义。

依赖边界：只依赖标准库 + ``network`` 同层协议模型（``network/`` 不得伸手进运行栈）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from heagent.network.event_stream_hub import (
    STREAM_BUFFER_SIZE,
    EventStreamHub,
    StreamSubscription,
)
from heagent.network.http_protocol import RunEventKind, RunEventPayload, clip_text

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# 环形缓冲条数：与 ``HTTP_EVENT_BUFFER_SIZE``(512) 同量级但更小——CLI 一轮的事件量远少于
# 网页 run（无审批 / 无项目会话 API），且旁路订阅者通常在本机。
CLI_EVENT_BUFFER_SIZE = STREAM_BUFFER_SIZE

# 缓冲里的一条：(run_id, payload)。run_id 逐条携带是旁路流的定义（跨轮次）。
CliBufferedEvent = tuple[str, RunEventPayload]

# 订阅形状（通用核的 ``StreamSubscription`` 在 ``RunEventPayload`` 上的实例化）。
CliSubscription = StreamSubscription[RunEventPayload]


class CliEventHub(EventStreamHub[RunEventPayload]):
    """CLI 旁路事件的唯一状态源（seq / 缓冲 / 订阅者 / 关停）。

    ``max_connections`` 是**整个旁路流**的连接上限（不是每 run）：旁路只有一条流，与
    ``/api/runs/{id}/ws`` 的「每 run 一份额度」是不同口径，故从 ``WS_MAX_CONNECTIONS``
    取值但语义按 hub 计。
    """

    def __init__(
        self,
        *,
        max_connections: int = 16,
        buffer_size: int = CLI_EVENT_BUFFER_SIZE,
    ) -> None:
        super().__init__(
            buffer_size=buffer_size,
            log_prefix="cli_ws",
            stream_label="run_id",
            max_connections=max_connections,
        )
        self._active_run_id: str | None = None

    # ---- 查询 ----

    @property
    def active_run_id(self) -> str:
        """当前正在跑的轮次 id；没有运行时空串（ack 帧用）。"""
        return self._active_run_id or ""

    # ---- 写侧（CLI 调用；同步、不抛）----

    def begin_run(self) -> str:
        """开始一轮旁路流，返回该轮 id。上一轮未 ``end_run`` 时静默接续（终端是唯一写者）。"""
        run_id = self.new_stream_id()
        self._active_run_id = run_id
        return run_id

    def end_run(self) -> None:
        """结束当前轮次：之后到达的事件（若有）被丢弃，而不是挂到新一轮上。"""
        self._active_run_id = None

    def publish_text(self, text: str) -> None:
        """回答文本增量。"""
        self._append(RunEventKind.TEXT, text=text)

    def publish_tool_call(self, name: str, target: str) -> None:
        """工具开始执行（``target`` 是单行作用对象摘要）。"""
        self._append(RunEventKind.TOOL_CALL, tool_name=name, tool_target=target)

    def publish_tool_result(self, name: str, output: str, *, is_error: bool) -> None:
        """工具执行完成；``is_error`` 让展示层把失败归因到具体调用。"""
        self._append(RunEventKind.TOOL_RESULT, tool_name=name, tool_output=output, tool_error=is_error)

    def publish_done(self, answer: str) -> None:
        """本轮完成（携带完整回答）。"""
        self._append(RunEventKind.DONE, text=answer)

    def publish_error(self, message: str) -> None:
        """本轮以业务失败收场。"""
        self._append(RunEventKind.ERROR, message=message)

    def publish_cancelled(self, message: str = "run interrupted") -> None:
        """本轮被用户中断（Ctrl+C / 双击 Esc）。"""
        self._append(RunEventKind.CANCELLED, message=message)

    def _append(self, kind: RunEventKind, **fields: Any) -> None:
        """按「当前轮次」路由一条事件；没有活动轮次时按既有口径丢弃（DEBUG 一行）。"""
        run_id = self._active_run_id
        if run_id is None:
            logger.debug("cli_ws event=dropped reason=no_active_run kind=%s", kind.value)
            return
        clipped = self._clip(fields)
        self._emit(run_id, _payload_builder(kind, clipped))

    @staticmethod
    def _clip(fields: dict[str, Any]) -> dict[str, Any]:
        """文本字段在入缓冲前截断（与 HTTP/SSE 同一 ``clip_text`` 口径）。"""
        clipped = dict(fields)
        for key in ("text", "tool_target", "tool_output", "message"):
            value = clipped.get(key)
            if isinstance(value, str):
                clipped[key] = clip_text(value)
        return clipped


def _payload_builder(kind: RunEventKind, fields: dict[str, Any]) -> Callable[[int], RunEventPayload]:
    """把 ``(kind, 已截断字段)`` 绑成一个「给 seq 就能造载荷」的回调（通用核的 build 形参）。"""

    def build(seq: int) -> RunEventPayload:
        return RunEventPayload(kind=kind, seq=seq, **fields)

    return build


__all__ = ["CLI_EVENT_BUFFER_SIZE", "CliBufferedEvent", "CliEventHub", "CliSubscription"]
