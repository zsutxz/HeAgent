"""只读通知流中枢（Epic 58）：cron 执行结果的主动投递通道。

**定位**：cron 作业由宿主后台调度器跑（``cron/scheduler.py``），一轮执行只有一个终局答案——
它不是「一条 run」（没有 run 记录、不能取消、没有状态机），因此不复用 ``/api/runs/*``；
它也不是「终端观众席」（旁路按 Epic 56 D9 永不出网），因此单开一条只读流
``WS /api/notifications/ws``。

四条不变量：

- **只读**：本中枢没有任何写方法（不能提交 run、不能取消），命令面只放行 ``ping``。
- **一次执行 = 一条**：``publish_cron_result`` 一次调用进缓冲一条（不逐 token 流式）。
- **seq 跨作业跨执行单调**：客户端只用它做游标，不需要知道 job 的生命周期。
- **绝不抛**：载荷构造失败 / 扇出异常一律 warning 后丢弃（通用核 ``_emit`` 已兜底）。

依赖边界：只依赖标准库 + ``network`` 同层协议模型（``network/`` 不得伸手进运行栈；
发布侧由入口层接线，本模块不认识 ``cron`` 包）。
"""

from __future__ import annotations

from heagent.network.event_stream_hub import STREAM_BUFFER_SIZE, EventStreamHub, StreamSubscription
from heagent.network.http_protocol import (
    CronResultStatus,
    NotificationKind,
    NotificationPayload,
    clip_text,
)

# 缓冲条数：与旁路同量级（256）。cron 的产出频率远低于终端事件，这个窗口足够任何正常重连。
NOTIFICATION_BUFFER_SIZE = STREAM_BUFFER_SIZE

NotificationSubscription = StreamSubscription[NotificationPayload]


class NotificationHub(EventStreamHub[NotificationPayload]):
    """通知流的唯一状态源（seq / 缓冲 / 订阅者 / 关停）；通用核见 ``EventStreamHub``。"""

    def __init__(
        self,
        *,
        max_connections: int = 16,
        buffer_size: int = NOTIFICATION_BUFFER_SIZE,
    ) -> None:
        super().__init__(
            buffer_size=buffer_size,
            log_prefix="notification_ws",
            stream_label="stream_id",
            max_connections=max_connections,
        )

    def publish_cron_result(
        self,
        *,
        job_id: str,
        status: CronResultStatus,
        text: str,
        cron: str = "",
    ) -> None:
        """发布一次 cron 执行的终局（成功带最终答案，失败带错误首行）。

        文本在这里就按 ``clip_text`` 口径截断：通知流与 SSE/WS 事件共用同一有界规则，
        缓冲区不会被一条超长回答撑爆。
        """
        stream_id = self.new_stream_id()
        bounded = clip_text(text)
        self._emit(
            stream_id,
            lambda seq: NotificationPayload(
                kind=NotificationKind.CRON_RESULT,
                seq=seq,
                job_id=job_id,
                cron=cron,
                status=status,
                text=bounded,
            ),
        )


__all__ = ["NOTIFICATION_BUFFER_SIZE", "NotificationHub", "NotificationSubscription"]
