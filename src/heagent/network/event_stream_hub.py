"""通用只读事件流中枢（Epic 58 D3）：seq / 环形缓冲 / 游标 / 背压 / 关停的**唯一**实现。

两条只读流共用本核，差异只在「载荷怎么造」与「日志前缀」：

- :class:`~heagent.network.cli_event_hub.CliEventHub` —— 终端旁路（``/api/cli/ws``），
  载荷是 ``RunEventPayload``，条目带 ``run_id``（终端一轮 run）；
- :class:`~heagent.network.notification_hub.NotificationHub` —— cron 结果通知
  （``/api/notifications/ws``），载荷是 ``NotificationPayload``，条目带内部 stream id。

为什么抽出来而不是各写一份：游标 / 环形缓冲 / 背压踢人 / 有界关停这四件事一旦有两份实现，
迟早漂移（Epic 55 与 Epic 56 已有同类教训）。抽出来的硬约束是 **CliEventHub 的公共面与行为
逐字不变**——既有 41 例是这次重构的验收线。

三条不变量（沿用 CliEventHub 的既有立场）：

- **写侧同步、无 ``await``**：``_emit`` 在事件循环线程里同步执行，seq 分配、入缓冲、扇出因此不需要锁。
- **发布绝不抛**：载荷构造失败 / 扇出异常一律 warning 后丢弃——只读流是可观测面，故障只该降级成
  「少一条事件」，不得打断正在跑的 run 或 cron 作业。
- **背压与 SSE/WS 同语义**：订阅队列满 = 该订阅者落后整整一个窗口 ⇒ 踢掉它并结束其流，客户端带
  游标重连即可补齐（或收 ``resync_required``）；既不无界堆内存，也不静默跳过事件。

依赖边界：只依赖标准库 + ``network`` 同层协议模型（``network/`` 不得伸手进运行栈）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

from heagent.network.http_protocol import HttpErrorCode
from heagent.network.ws_protocol import WS_CLOSE_GOING_AWAY, WsErrorFrame, error_envelope
from heagent.pub.safe_logging import safe_log

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# 环形缓冲条数：与 ``HTTP_EVENT_BUFFER_SIZE``(512) 同量级但更小——只读流的订阅者通常在本机，
# 单轮事件量远小于网页 run（无审批 / 无项目会话 API）。订阅队列与缓冲同界：落后一整个窗口的
# 订阅者无论如何都要走 resync 路径。
STREAM_BUFFER_SIZE = 256


def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """记一条日志，**绝不让观测故障影响事件发布**。"""
    safe_log(logger, level, message, *args, exc_info=exc_info)


class SequencedPayload(Protocol):
    """流内载荷的最小结构面：一个单调序号即可（游标只依赖它）。"""

    seq: int


PayloadT = TypeVar("PayloadT", bound=SequencedPayload)


@dataclass(frozen=True)
class StreamSubscription(Generic[PayloadT]):
    """一次订阅：重放片段 + 后续实时队列。

    两者必须在**同一个同步调用**里产出，否则「重放」与「开始收实时事件」之间的窗口会丢事件。
    """

    backlog: tuple[tuple[str, PayloadT], ...]
    queue: asyncio.Queue[tuple[str, PayloadT] | None]


class EventStreamHub(Generic[PayloadT]):
    """只读事件流的状态源：seq / 缓冲 / 订阅者 / 关停。

    ``max_connections`` 是**整条流**的连接上限（不是每轮）：只读流只有一条，与
    ``/api/runs/{id}/ws`` 的「每 run 一份额度」是不同口径。

    子类负责三件事：载荷构造（``_emit`` 的 ``build`` 回调）、字段有界化、日志前缀与 stream 标签。
    """

    def __init__(
        self,
        *,
        buffer_size: int,
        log_prefix: str,
        stream_label: str = "run_id",
        max_connections: int = 16,
    ) -> None:
        if max_connections < 1:
            raise ValueError("max_connections must be >= 1")
        if buffer_size < 1:
            raise ValueError("buffer_size must be >= 1")
        self.max_connections = max_connections
        self._buffer_size = buffer_size
        self._log_prefix = log_prefix
        self._stream_label = stream_label
        self._buffer: deque[tuple[str, PayloadT]] = deque(maxlen=buffer_size)
        self._next_seq = 1
        self._subscribers: set[asyncio.Queue[tuple[str, PayloadT] | None]] = set()
        # connection_id → (stream_id, websocket)：关停时按连接关闭，与 run_service 同形态。
        self._ws_connections: dict[str, tuple[str, Any]] = {}
        self._closing = False

    # ---- 查询 ----

    @property
    def closing(self) -> bool:
        """服务是否正在关闭（新连接直接收 ``shutting_down``）。"""
        return self._closing

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
    def published_events(self) -> tuple[tuple[str, PayloadT], ...]:
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

    # ---- 写侧（子类调用；同步、不抛）----

    @staticmethod
    def new_stream_id() -> str:
        """分配一个 stream id（子类用它把「一轮」串起来：终端一轮 run / 一次 cron 执行）。"""
        return uuid.uuid4().hex

    def _emit(self, stream_id: str, build: Callable[[int], PayloadT]) -> None:
        """分配 seq、入环形缓冲、扇出；**任何异常都收敛为一条 warning**。

        ``build`` 是唯一知道载荷形状的东西——子类在其中做字段有界化与模型校验。
        """
        try:
            payload: PayloadT = build(self._next_seq)
        except Exception:
            # 字段有界化 / 校验失败：只读流少一条事件，绝不打断正在跑的那一轮。
            _safe_log(logging.WARNING, "%s event=publish_failed", self._log_prefix, exc_info=True)
            return
        self._next_seq += 1
        self._buffer.append((stream_id, payload))
        for queue in list(self._subscribers):
            try:
                queue.put_nowait((stream_id, payload))
            except asyncio.QueueFull:
                self._drop_lagging_subscriber(queue)

    # ---- 读侧（WS 端点调用）----

    def open_subscription(self, cursor: int | None) -> StreamSubscription[PayloadT] | None:
        """限额检查 + 重放片段 + 登记订阅者，**在同一个同步调用**里完成。

        返回 ``None`` 表示已达连接上限（调用方回 ``rate_limited`` 错误帧并关闭）。
        """
        if len(self._subscribers) >= self.max_connections:
            return None
        backlog: tuple[tuple[str, PayloadT], ...] = ()
        if cursor is None:
            backlog = tuple(self._buffer)
        else:
            backlog = tuple(item for item in self._buffer if item[1].seq > max(0, cursor))
        queue: asyncio.Queue[tuple[str, PayloadT] | None] = asyncio.Queue(maxsize=self._buffer_size)
        self._subscribers.add(queue)
        return StreamSubscription(backlog=backlog, queue=queue)

    def remove_subscriber(self, queue: asyncio.Queue[tuple[str, PayloadT] | None]) -> None:
        """注销订阅者（断线 / 收尾）；重复调用幂等。"""
        self._subscribers.discard(queue)

    def _drop_lagging_subscriber(self, queue: asyncio.Queue[tuple[str, PayloadT] | None]) -> None:
        """背压与 SSE/WS 同语义：结束该流，让客户端按游标续传。"""
        self._subscribers.discard(queue)
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(None)
        _safe_log(logging.WARNING, "%s event=subscriber_dropped reason=queue_full", self._log_prefix)

    # ---- 关停 ----

    def register_ws(self, connection_id: str, stream_id: str, websocket: Any) -> None:
        """登记已通过限额的 WS 连接，供有界关停关闭。"""
        self._ws_connections[connection_id] = (stream_id, websocket)

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

        async def close_one(connection_id: str, stream_id: str, websocket: Any) -> None:
            with contextlib.suppress(Exception):
                # 与 HTTP/WS 既有口径一致：关停用 shutting_down + 1001。
                envelope = error_envelope(HttpErrorCode.SHUTTING_DOWN, "server is shutting down")
                await websocket.send_text(WsErrorFrame(error=envelope).model_dump_json())
                await websocket.close(code=WS_CLOSE_GOING_AWAY)
            self.unregister_ws(connection_id)
            _safe_log(
                logging.INFO,
                "%s event=ws_close %s=%s connection_id=%s",
                self._log_prefix,
                self._stream_label,
                stream_id,
                connection_id,
            )

        await asyncio.wait_for(
            asyncio.gather(*(close_one(key, stream_id, websocket) for key, (stream_id, websocket) in connections)),
            timeout=timeout,
        )


__all__ = ["STREAM_BUFFER_SIZE", "EventStreamHub", "SequencedPayload", "StreamSubscription"]
