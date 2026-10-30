"""cron 结果「从执行到帧」的端到端契约（Epic 58 story 58-2）。

链路全用真实实现，只有 provider 是 stub：

``AgentLoop.run``（真）→ ``build_cron_job_runner``（真）→ 入口层 ``_build_cron_notifier``（真）
→ ``NotificationHub``（真）→ 真实 TCP 上的 ``/api/notifications/ws`` → 真实 ``websockets`` 客户端。

这就是用户当初报的「cron 每分钟跑、客户端零帧」的正面判据：修复前断在
「runner 丢弃 ``loop.run`` 返回值」与「中枢从未装配」两处，任何一处回退这条断言就会红。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

from heagent.cli.interactive import _build_cron_notifier
from heagent.cli.wiring import build_cron_job_runner
from heagent.config import Settings, reset_settings, resolve_runtime_config
from heagent.cron.jobs import JobStore
from heagent.engine import EngineContainer
from heagent.network.notification_hub import NotificationHub
from heagent.network.ws_host import WsServer, WsServerConfig

if TYPE_CHECKING:
    from pathlib import Path

websockets = pytest.importorskip("websockets")

JOB_ID = "1661798f"


class _StubProvider:
    """最小 provider：``send`` 返回固定答案，或按需抛异常（不打任何网络）。"""

    error: BaseException | None = None

    async def send(self, messages: Any, *, tools: Any = None) -> Any:
        if type(self).error is not None:
            raise type(self).error
        from heagent.pub.types import ProviderResponse, TokenUsage

        return ProviderResponse(
            content="hello",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: Any, *, tools: Any = None) -> Any:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> Any:
        from heagent.providers.base import ProviderMetadata

        return ProviderMetadata(name="stub", model="stub")


class _Service:
    """``EmbeddedHttpService`` 的最小替身：只暴露 notifier 需要的属性。"""

    def __init__(self, hub: NotificationHub) -> None:
        self.notification_hub = hub


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    reset_settings()
    _StubProvider.error = None
    yield
    reset_settings()
    _StubProvider.error = None


async def _start(hub: NotificationHub) -> tuple[WsServer, asyncio.Task[None]]:
    server = WsServer(WsServerConfig(port=0, shutdown_timeout=1), notification_hub=hub)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    await asyncio.sleep(0)
    return server, task


async def _stop(server: WsServer, task: asyncio.Task[None]) -> None:
    await server.close()
    await asyncio.wait_for(task, timeout=5)


def _runner(engine: EngineContainer, notifier: Any) -> Any:
    return build_cron_job_runner(
        _StubProvider(),
        engine,
        resolve_runtime_config(),
        JobStore(),
        skills=None,
        facts=None,
        profile=None,
        retry_mw=lambda request, next_handler: next_handler(request),
        cron_notifier=notifier,
    )


@pytest.mark.asyncio
async def test_a_real_cron_execution_reaches_a_real_client(tmp_path: Path) -> None:
    hub = NotificationHub(max_connections=2, buffer_size=8)
    notifier = _build_cron_notifier(_Service(hub), resolve_runtime_config(Settings(cron_push_enabled=True)))
    assert notifier is not None

    engine = EngineContainer.default(workspace_root=str(tmp_path))
    runner = _runner(engine, notifier)
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    try:
        async with websockets.connect(uri) as ws:
            run_context = engine.create_run_context(
                metadata={"kind": "cron", "job_id": JOB_ID}, workspace_root=str(tmp_path)
            )
            await runner("说 hello", run_context)
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    finally:
        await _stop(server, task)

    assert frame["type"] == "notification"
    payload = frame["notification"]
    assert payload["kind"] == "cron_result"
    assert payload["job_id"] == JOB_ID
    assert payload["status"] == "completed"
    assert payload["text"] == "hello"


@pytest.mark.asyncio
async def test_a_failing_execution_reaches_the_client_as_failed(tmp_path: Path) -> None:
    """失败也是「一条通知」：客户端据此知道「跑了，但没结果」，而不是永远等下去。"""
    _StubProvider.error = RuntimeError("provider exploded\nstack line two")
    hub = NotificationHub(max_connections=2, buffer_size=8)
    notifier = _build_cron_notifier(_Service(hub), resolve_runtime_config(Settings(cron_push_enabled=True)))
    assert notifier is not None

    engine = EngineContainer.default(workspace_root=str(tmp_path))
    runner = _runner(engine, notifier)
    server, task = await _start(hub)
    uri = f"ws://127.0.0.1:{server.port}/api/notifications/ws"
    try:
        async with websockets.connect(uri) as ws:
            run_context = engine.create_run_context(
                metadata={"kind": "cron", "job_id": JOB_ID}, workspace_root=str(tmp_path)
            )
            with pytest.raises(RuntimeError, match="provider exploded"):
                await runner("说 hello", run_context)
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    finally:
        await _stop(server, task)

    payload = frame["notification"]
    assert payload["status"] == "failed"
    assert payload["text"] == "provider exploded"  # 只带异常首行，不把多行消息灌进流里
    assert "\n" not in payload["text"]
