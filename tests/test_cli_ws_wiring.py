"""CLI 旁路的**装配**契约：``build_http_service`` → ``WsServer`` → 路由 → 中枢（Epic 56 D7）。

为什么单独一个文件：其余用例都直接构造 ``WsServer(cli_hub=...)``，因此「真实入口忘了把中枢
传下去」这类漏接不会变红（``EmbeddedHttpService.cli_hub`` 有值、路由却没注册）。这里从**入口函数**
起步，用真 TCP 连一次 ``/api/cli/ws``（9001 侧）。
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
websockets = pytest.importorskip("websockets")

from heagent.cli.http import build_http_service  # noqa: E402
from heagent.config import Settings  # noqa: E402

pytestmark = pytest.mark.embedded_http_service


@pytest.mark.asyncio
async def test_service_built_from_settings_serves_the_cli_event_stream() -> None:
    service = build_http_service(Settings(ws_cli_bypass_enabled=True), executor=None)
    assert service.cli_hub is not None
    await service.start()
    try:
        hub = service.cli_hub
        uri = f"ws://{service.ws_address}/api/cli/ws"
        async with websockets.connect(uri) as ws:
            hub.begin_run()
            hub.publish_text("from the terminal")
            hub.end_run()
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert frame["type"] == "event"
        assert frame["event"]["kind"] == "text"
        assert frame["event"]["text"] == "from the terminal"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_disabled_switch_leaves_the_route_unregistered() -> None:
    service = build_http_service(Settings(ws_cli_bypass_enabled=False), executor=None)
    assert service.cli_hub is None
    await service.start()
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
            async with websockets.connect(f"ws://{service.address}/api/cli/ws"):
                pass
        assert rejected.value.response.status_code == 403
    finally:
        await service.close()
