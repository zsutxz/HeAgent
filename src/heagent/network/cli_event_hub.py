"""CLI 终端运行的旁路事件中枢（Epic 55）。

**定位**：CLI（单次 / 交互）里那一轮 run 由**终端**持有——不为它建 ``_RunRecord``、不占
``HTTP_MAX_INFLIGHT_RUNS`` 名额、不写 HTTP 会话历史、不开取消通道。本模块只把这一轮的事件按
同一套 ``RunEventPayload`` 契约广播给旁路订阅者（``WS /api/cli/ws``），因此客户端拿到的是
「观众席」而不是「控制台」。

三条不变量：

- **写侧同步、无 ``await``**：``begin_run`` / ``publish_*`` / ``end_run`` 都在事件循环线程里同步
  执行，与 ``_RunRecord.append`` 同口径，所以 seq 分配、入缓冲、扇出不需要锁。
- **``publish_*`` 绝不抛**：旁路是可观测面，故障只该降级成「少一条事件」。字段校验失败、扇出异常
  一律 warning 后丢弃——**不得**打断终端正在跑的 run。
- **背压与 SSE/WS 同语义**：订阅队列满 = 该订阅者落后整整一个窗口 ⇒ 踢掉它并结束其流，客户端带
  游标重连即可补齐或收 ``resync_required``；既不无界堆内存，也不静默跳过事件。

依赖边界：只依赖标准库 + ``network`` 同层协议模型（``network/`` 不得伸手进运行栈）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any

from heagent.network.http_protocol import HttpErrorCode, RunEventKind, RunEventPayload, clip_text
from heagent.network.ws_protocol import WS_CLOSE_GOING_AWAY, WsErrorFrame, error_envelope
from heagent.pub.safe_logging import safe_log

logger = logging.getLogger(__name__)

# 环形缓冲条数：与 ``HTTP_EVENT_BUFFER_SIZE``(512) 同量级但更小——CLI 一轮的事件量远少于
# 网页 run（无审批 / 无项目会话 API），且旁路订阅者通常在本机。
CLI_EVENT_BUFFER_SIZE = 256

# 队列条数与缓冲同界：落后一整个窗口的订阅者无论如何都要走 resync 路径。
_CLI_SUBSCRIBER_QUEUE_SIZE = CLI_EVENT_BUFFER_SIZE

# 缓冲里的一条：(run_id, payload)。run_id 逐条携带是旁路流的定义（跨轮次）。
CliBufferedEvent = tuple[str, RunEventPayload]


def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """记一条日志，**绝不让观测故障影响事件发布**。"""
    safe_log(logger, level, message, *args, exc_info=exc_info)


@dataclass(frozen=True)
class CliSubscription:
    """一次订阅：先在 ``open_subscription`` 的同步临界段里取到的重放片段 + 后续实时队列。

    两者必须在**同一个同步调用**里产出，否则「重放」与「开始收实时事件」之间的窗口会丢事件。
    """

    backlog: tuple[CliBufferedEvent, ...]
    queue: asyncio.Queue[CliBufferedEvent | None]


class CliEventHub:
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
        if max_connections < 1:
            raise ValueError("max_connections must be >= 1")
        if buffer_size < 1:
            raise ValueError("buffer_size must be >= 1")
        self.max_connections = max_connections
        self._buffer: deque[CliBufferedEvent] = deque(maxlen=buffer_size)
        self._next_seq = 1
        self._active_run_id: str | None = None
        self._subscribers: set[asyncio.Queue[CliBufferedEvent | None]] = set()
        # connection_id → (run_id, websocket)：关停时按连接关闭，与 run_service 同形态。
        self._ws_connections: dict[str, tuple[str, Any]] = {}
        self._closing = False

    # ---- 查询 ----

    @property
    def closing(self) -> bool:
        """服务是否正在关闭（新连接直接收 ``shutting_down``）。"""
        return self._closing

    @property
    def active_run_id(self) -> str:
        """当前正在跑的轮次 id；没有运行时空串（ack 帧用）。"""
        return self._active_run_id or ""

    @property
    def subscriber_count(self) -> int:
        """当前订阅者数（限额判定与测试用）。"""
        return len(self._subscribers)

    @property
    def connection_count(self) -> int:
        """当前登记的 WS 连接数（关停与测试用）。"""
        return len(self._ws_connections)

    @property
    def oldest_seq(self) -> int | None:
        """缓冲里最老一条的 seq；空缓冲为 ``None``。"""
        return self._buffer[0][1].seq if self._buffer else None

    @property
    def published_events(self) -> tuple[CliBufferedEvent, ...]:
        """当前缓冲的只读快照（诊断与测试用；不在热路径上）。"""
        return tuple(self._buffer)

    def needs_resync(self, cursor: int | None) -> bool:
        """游标是否已落在窗口之外（与 :meth:`HttpRunService.needs_resync` 同一语义）。

        没有游标等价于「从头读」：若窗口已淘汰开头（``oldest_seq > 1``），同样要求重新同步。
        """
        oldest = self.oldest_seq
        if oldest is None:
            return False
        effective = 0 if cursor is None else max(0, cursor)
        return effective < oldest - 1

    # ---- 写侧（CLI 调用；同步、不抛）----

    def begin_run(self) -> str:
        """开始一轮旁路流，返回该轮 id。上一轮未 ``end_run`` 时静默接续（终端是唯一写者）。"""
        run_id = uuid.uuid4().hex
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
        """分配 seq、入环形缓冲、扇出；**任何异常都收敛为一条 warning**。"""
        run_id = self._active_run_id
        if run_id is None:
            _safe_log(logging.DEBUG, "cli_ws event=dropped reason=no_active_run kind=%s", kind.value)
            return
        try:
            payload = RunEventPayload(kind=kind, seq=self._next_seq, **self._clip(fields))
        except Exception:
            # 字段有界化 / 校验失败：旁路少一条事件，绝不打断终端 run。
            _safe_log(logging.WARNING, "cli_ws event=publish_failed kind=%s", kind.value, exc_info=True)
            return
        self._next_seq += 1
        self._buffer.append((run_id, payload))
        for queue in list(self._subscribers):
            try:
                queue.put_nowait((run_id, payload))
            except asyncio.QueueFull:
                self._drop_lagging_subscriber(queue)

    @staticmethod
    def _clip(fields: dict[str, Any]) -> dict[str, Any]:
        """文本字段在入缓冲前截断（与 HTTP/SSE 同一 ``clip_text`` 口径）。"""
        clipped = dict(fields)
        for key in ("text", "tool_target", "tool_output", "message"):
            value = clipped.get(key)
            if isinstance(value, str):
                clipped[key] = clip_text(value)
        return clipped

    # ---- 读侧（WS 端点调用）----

    def open_subscription(self, cursor: int | None) -> CliSubscription | None:
        """限额检查 + 重放片段 + 登记订阅者，**在同一个同步调用**里完成。

        返回 ``None`` 表示已达连接上限（调用方回 ``rate_limited`` 错误帧并关闭）。
        """
        if len(self._subscribers) >= self.max_connections:
            return None
        backlog: tuple[CliBufferedEvent, ...] = ()
        if cursor is None:
            backlog = tuple(self._buffer)
        else:
            backlog = tuple(item for item in self._buffer if item[1].seq > max(0, cursor))
        queue: asyncio.Queue[CliBufferedEvent | None] = asyncio.Queue(maxsize=_CLI_SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        return CliSubscription(backlog=backlog, queue=queue)

    def remove_subscriber(self, queue: asyncio.Queue[CliBufferedEvent | None]) -> None:
        """注销订阅者（断线 / 收尾）；重复调用幂等。"""
        self._subscribers.discard(queue)

    def _drop_lagging_subscriber(self, queue: asyncio.Queue[CliBufferedEvent | None]) -> None:
        """背压与 SSE/WS 同语义：结束该流，让客户端按游标续传。"""
        self._subscribers.discard(queue)
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(None)
        _safe_log(logging.WARNING, "cli_ws event=subscriber_dropped reason=queue_full")

    # ---- 关停 ----

    def register_ws(self, connection_id: str, run_id: str, websocket: Any) -> None:
        """登记已通过限额的 WS 连接，供有界关停关闭。"""
        self._ws_connections[connection_id] = (run_id, websocket)

    def unregister_ws(self, connection_id: str) -> None:
        """移除断线或已关闭的 WS 连接登记。"""
        self._ws_connections.pop(connection_id, None)

    def close(self) -> None:
        """置「停止接收」标记（幂等）；之后的新连接直接收 ``shutting_down``。"""
        self._closing = True

    def reopen(self) -> None:
        """重新武装（``close()`` 之后再次 ``start()`` 时用，与 ``HttpRunService.reopen`` 同形态）。"""
        self._closing = False

    async def close_websockets(self, *, timeout: float = 5.0) -> None:
        """通知所有已登记连接服务关闭，并有界收尾。"""
        connections = tuple(self._ws_connections.items())
        if not connections:
            return

        async def close_one(connection_id: str, run_id: str, websocket: Any) -> None:
            with contextlib.suppress(Exception):
                # 与 HTTP/WS 既有口径一致：关停用 shutting_down + 1001。
                envelope = error_envelope(HttpErrorCode.SHUTTING_DOWN, "server is shutting down")
                await websocket.send_text(WsErrorFrame(error=envelope).model_dump_json())
                await websocket.close(code=WS_CLOSE_GOING_AWAY)
            self.unregister_ws(connection_id)
            _safe_log(logging.INFO, "cli_ws event=ws_close run_id=%s connection_id=%s", run_id, connection_id)

        await asyncio.wait_for(
            asyncio.gather(*(close_one(key, run_id, websocket) for key, (run_id, websocket) in connections)),
            timeout=timeout,
        )


__all__ = ["CLI_EVENT_BUFFER_SIZE", "CliEventHub", "CliSubscription"]
