"""只读通知流中枢的单元契约（Epic 58）：一次执行一条、seq 跨作业单调、文本有界。

端点侧的契约在 ``test_notification_ws_e2e.py``（真实 TCP）；这里只钉载荷与中枢语义，
发布接线（谁在 cron 跑完后调用它）在入口层测试里钉。
"""

from __future__ import annotations

import asyncio

import pytest

from heagent.network.http_protocol import (
    MAX_EVENT_TEXT_CHARS,
    CronResultStatus,
    NotificationKind,
    NotificationPayload,
)
from heagent.network.notification_hub import NOTIFICATION_BUFFER_SIZE, NotificationHub


def test_publishes_one_bounded_payload_per_cron_result() -> None:
    hub = NotificationHub()
    hub.publish_cron_result(job_id="job-1", status=CronResultStatus.COMPLETED, text="hello", cron="* * * * *")

    published = hub.published_events
    assert len(published) == 1
    _stream_id, payload = published[0]
    assert isinstance(payload, NotificationPayload)
    assert payload.kind is NotificationKind.CRON_RESULT
    assert payload.seq == 1
    assert payload.job_id == "job-1"
    assert payload.cron == "* * * * *"
    assert payload.status is CronResultStatus.COMPLETED
    assert payload.text == "hello"


def test_seq_is_monotonic_across_jobs_and_stream_ids_differ_per_execution() -> None:
    hub = NotificationHub()
    hub.publish_cron_result(job_id="job-a", status=CronResultStatus.COMPLETED, text="first")
    hub.publish_cron_result(job_id="job-b", status=CronResultStatus.FAILED, text="boom")
    hub.publish_cron_result(job_id="job-a", status=CronResultStatus.COMPLETED, text="second")

    published = hub.published_events
    assert [payload.seq for _, payload in published] == [1, 2, 3]
    assert [payload.job_id for _, payload in published] == ["job-a", "job-b", "job-a"]
    # 每次执行的 stream id 都不同（客户端不依赖它，但它必须能区分「两轮」）。
    assert len({stream_id for stream_id, _ in published}) == 3
    assert hub.oldest_seq == 1


def test_failed_status_is_preserved() -> None:
    hub = NotificationHub()
    hub.publish_cron_result(job_id="job-1", status=CronResultStatus.FAILED, text="provider exploded")
    _stream_id, payload = hub.published_events[0]
    assert payload.status is CronResultStatus.FAILED
    assert payload.text == "provider exploded"


def test_text_is_clipped_to_the_event_budget() -> None:
    """超长回答不得撑爆缓冲：与 SSE/WS 事件同一 ``clip_text`` 口径，截断必须显式标记。"""
    hub = NotificationHub()
    hub.publish_cron_result(job_id="job-1", status=CronResultStatus.COMPLETED, text="x" * (MAX_EVENT_TEXT_CHARS + 50))

    _stream_id, payload = hub.published_events[0]
    assert len(payload.text) > MAX_EVENT_TEXT_CHARS  # 上限 + 后缀
    assert payload.text.endswith("…[truncated]")
    assert payload.text.startswith("x" * 100)


def test_backlog_replays_from_the_beginning_without_a_cursor() -> None:
    hub = NotificationHub()
    hub.publish_cron_result(job_id="job-0", status=CronResultStatus.COMPLETED, text="first")
    hub.publish_cron_result(job_id="job-1", status=CronResultStatus.COMPLETED, text="second")

    subscription = hub.open_subscription(None)
    assert subscription is not None
    assert [payload.seq for _, payload in subscription.backlog] == [1, 2]


@pytest.mark.asyncio
async def test_subscribers_receive_live_notifications() -> None:
    hub = NotificationHub()
    hub.publish_cron_result(job_id="job-0", status=CronResultStatus.COMPLETED, text="before")

    subscription = hub.open_subscription(1)  # 游标 1 ⇒ 只收之后发布的
    assert subscription is not None
    assert subscription.backlog == ()

    hub.publish_cron_result(job_id="job-1", status=CronResultStatus.COMPLETED, text="live")
    stream_id, payload = await asyncio.wait_for(subscription.queue.get(), timeout=1)
    assert stream_id != ""
    assert payload.seq == 2
    assert payload.text == "live"


def test_default_buffer_matches_the_bypass_window() -> None:
    """两条只读流共用同一个核，窗口大小也共用一个量级（256）：不另立一套默契。"""
    assert NOTIFICATION_BUFFER_SIZE == 256
    hub = NotificationHub(buffer_size=3)
    for index in range(4):
        hub.publish_cron_result(job_id="job", status=CronResultStatus.COMPLETED, text=str(index))
    assert hub.oldest_seq == 2
    assert hub.needs_resync(None) is True
    assert hub.needs_resync(3) is False
