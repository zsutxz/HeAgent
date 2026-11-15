"""单次运行的记录与事件出口（Story 62.1 自 ``network/http_server.py`` 拆出）。

``_RunRecord`` 是 AD-3/AD-4 的唯一状态源：状态、有界事件缓冲、订阅者、终态转换；写者只有
运行任务（经 :class:`RunEventPublisher` 追加事件）与终态转换，读者是 SSE 订阅者与会话快照。

``__all__`` 显式列出包内公开名：包级再导出（``__init__.py``）与 exception 快照
（``scripts/contract_snapshot.py``）都以「定义模块的 ``__all__``」为收录依据。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from typing import Any

from heagent.network.http_protocol import (
    TERMINAL_RUN_STATUSES,
    RunEventKind,
    RunEventPayload,
    RunOutcome,
    RunStatus,
    clip_text,
)

__all__ = ["RunEventPublisher"]


class _RunRecord:
    """单次运行的记录：状态、有界事件缓冲、订阅者、终态结果（AD-3/AD-4 的唯一状态源）。

    写者只有两个：运行任务（经 :class:`RunEventPublisher` 追加事件）与终态转换（
    :meth:`claim_terminal` + :meth:`close_subscribers`）。读者是 SSE 订阅者与会话快照。
    本对象**不**持有 ``AgentLoop``，也不碰 Provider——那些属于入口层注入的 executor。
    """

    # SSE 与 WS 订阅者队列的共用类型：两个订阅管理助手的签名用。
    _SubscriberQueue = asyncio.Queue[RunEventPayload | None]

    def __init__(
        self,
        run_id: str,
        prompt: str,
        *,
        buffer_size: int,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.prompt = prompt
        # 不透明的归属 id（入口层在建立运行时注入）：供「项目 / 会话是否有在途运行」与「会话最近
        # 一次运行状态」查询使用。传输层不解释它们的语义，只做字符串比对。
        self.project_id = project_id
        self.session_id = session_id
        self.status = RunStatus.RUNNING
        self.outcome: RunOutcome | None = None
        self.error_message: str | None = None
        self.created_at = time.perf_counter()
        # 最近一次「有进展」的时刻与在途工具数：:meth:`append` 是唯一写者，看门狗只读。
        # 「在途工具」（tool_call 已发、tool_result 未到）同样算进展——一次长的 shell / 子代理调用
        # 期间没有事件，但运行并没有卡死；漏配对时最坏也只是回到「纯事件判定」。
        self.last_activity_at = self.created_at
        self.tools_in_flight = 0
        # 第一条在途工具的时刻（None = 当前无在途工具）：看门狗据此把「工具卡死」也判进静默
        # 上限——只数「有没有在途工具」会让永不返回的工具把名额无界占住。
        self.tools_in_flight_since: float | None = None
        # 看门狗终结本次运行的原因（"idle" / "tool" / "hard" / None）：终态归因与文案据此
        # 区分「卡死」「工具卡死」与「超过运维设的总时长上限」。字段**不清空**（终态文案、
        # 日志与测试都要读它），「是否已被那次取消消费」由 :attr:`deadline_consumed` 表达。
        self.deadline_reason: str | None = None
        self.deadline_consumed = False
        # 用户显式 DELETE 的取消：取消可能被 executor 吞过一次，那时
        # ``deadline_reason`` 仍在——归因必须看「谁发的取消」，不能只看它。
        self.user_cancel_requested = False
        # 有界 ring buffer：越过窗口的重连据此判定 resync_required。
        self.events: deque[RunEventPayload] = deque(maxlen=buffer_size)
        self.subscribers: set[asyncio.Queue[RunEventPayload | None]] = set()
        self.ws_subscribers: set[asyncio.Queue[RunEventPayload | None]] = set()
        # 订阅者队列与事件窗口**同界**：消费端（SSE 响应写 socket）被背压卡住时不能无限堆积，
        # 到界即结束该订阅者的流（见 :meth:`_drop_lagging_subscriber`）。
        self.subscriber_queue_size = buffer_size
        self._next_seq = 1

    def elapsed_ms(self) -> int:
        """自创建起的整数毫秒（终态日志用；不含任何内容字段）。"""
        return int((time.perf_counter() - self.created_at) * 1000)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    @property
    def oldest_seq(self) -> int | None:
        """缓冲里最老事件的序号（空缓冲 → ``None``）——``resync`` 判定的下界。"""
        return self.events[0].seq if self.events else None

    def append(self, kind: RunEventKind, **fields: Any) -> RunEventPayload:
        """追加一条事件：分配单调 ``seq``、入缓冲、广播给当前订阅者（同步，无 ``await``）。

        全程只在事件循环线程里执行，故顺带维护看门狗读的「有进展」信号（:attr:`last_activity_at`
        与 :attr:`tools_in_flight`）无需加锁：事件本身就是进展的证据。
        """
        self.last_activity_at = time.perf_counter()
        if kind is RunEventKind.TOOL_CALL:
            if self.tools_in_flight == 0:
                self.tools_in_flight_since = self.last_activity_at
            self.tools_in_flight += 1
        elif kind is RunEventKind.TOOL_RESULT:
            self.tools_in_flight = max(0, self.tools_in_flight - 1)
            if self.tools_in_flight == 0:
                self.tools_in_flight_since = None
        payload = RunEventPayload(kind=kind, seq=self._next_seq, **fields)
        self._next_seq += 1
        self.events.append(payload)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                self._drop_lagging_subscriber(self.subscribers, queue)
        for queue in list(self.ws_subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                self._drop_lagging_subscriber(self.ws_subscribers, queue)
        return payload

    def consume_deadline_reason(self) -> str | None:
        """返回看门狗写入的原因并标记**已消费**（一次性）；已消费则回 ``None``。

        旧实现把 ``deadline_reason`` 当常驻标记：一旦看门狗写过，**之后**任何取消（用户的
        ``DELETE`` 或关停）都会被归因成 ``timed_out`` 并把取消吞掉（活动台账 A9①）。
        ``deadline_reason`` **不清空**——终态文案 / 日志 / 测试仍要读它。
        """
        if self.deadline_consumed:
            return None
        self.deadline_consumed = True
        return self.deadline_reason

    def try_add_subscriber(self, queue: asyncio.Queue[RunEventPayload | None], limit: int) -> bool:
        """检查限额与登记订阅者**同一步**完成（同步、无 ``await`` ⇒ 事件循环里原子）。

        旧实现「先查后加」跨两处（端点数、生成器登记）⇒ 并发 ``GET .../events`` 能一起
        穿过限额，每个订阅者还驻留一个事件队列（活动台账 A9③）。返回 ``False`` 表示已满。
        """
        return self._try_add_subscriber(self.subscribers, queue, limit)

    def try_add_ws_subscriber(self, queue: asyncio.Queue[RunEventPayload | None], limit: int) -> bool:
        """WS 订阅限额检查与登记在同步临界段内完成，且与 SSE 池完全独立。"""
        return self._try_add_subscriber(self.ws_subscribers, queue, limit)

    def _try_add_subscriber(self, subscribers: set[_SubscriberQueue], queue: _SubscriberQueue, limit: int) -> bool:
        if len(subscribers) >= limit:
            return False
        subscribers.add(queue)
        return True

    def _drop_lagging_subscriber(self, subscribers: set[_SubscriberQueue], queue: _SubscriberQueue) -> None:
        """订阅者跟不上（有界队列已满）：**结束它的流**，而不是无限堆积或静默丢事件。

        SSE 与 WS 队列背压同语义：结束该流，让客户端按游标续传。队列与事件窗口同界，因此
        「队列满」等价于「该订阅者落后整整一个窗口」——它无论如何都要走重新同步路径，此时丢掉
        队列里的旧事件并不可惜：客户端会带 ``Last-Event-ID`` 重连，服务端按 ring buffer 补齐；
        若游标已越出窗口，``needs_resync`` 回 409，客户端拉 ``/api/session`` 快照收敛（AD-4 的
        既有恢复路径）。哨兵 ``None`` 让生成器**立即**结束该流（客户端据此重连），而不是干等
        心跳超时。规则：宁可让客户端重连，也不静默跳过事件。
        """
        subscribers.discard(queue)
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(None)

    def claim_terminal(self, status: RunStatus) -> bool:
        """抢占终态转换：**第一个调用者获胜**（AD-10），后续调用是 no-op 并返回 ``False``。

        只置状态、不写事件——获胜者随后自己 append 唯一的终态事件，再 :meth:`close_subscribers`，
        保证「终态事件先于流结束标记」的顺序。
        """
        if self.is_terminal:
            return False
        self.status = status
        return True

    def close_subscribers(self) -> None:
        """终态事件写完后通知 SSE 与 WS 订阅者「流到此结束」。"""
        for queue in (*self.subscribers, *self.ws_subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)


class RunEventPublisher:
    """入口层的事件出口：只暴露「发什么」，``seq`` 分配、截断与广播都在服务层。

    截断在这里做（而不是让入口层自己裁）：事件大小必须有界，而入口层只管把
    ``StreamEvent`` 映射过来。
    """

    def __init__(self, record: _RunRecord) -> None:
        self._record = record

    def text(self, text: str) -> None:
        """回答文本增量。"""
        self._record.append(RunEventKind.TEXT, text=clip_text(text))

    def tool_call(self, name: str, target: str) -> None:
        """工具开始执行（``target`` 是单行作用对象摘要，由 ``tools.call_summary`` 产出）。"""
        self._record.append(RunEventKind.TOOL_CALL, tool_name=name, tool_target=clip_text(target))

    def tool_result(self, name: str, output: str, *, is_error: bool) -> None:
        """工具执行完成；``is_error`` 让展示层把失败归因到具体调用。"""
        self._record.append(
            RunEventKind.TOOL_RESULT,
            tool_name=name,
            tool_output=clip_text(output),
            tool_error=is_error,
        )
