"""Epic 56 Story 56-4：缺 ``websockets`` 时的 WS 升级探针（Epic 54 retro F6 的缺口）。

**为什么要子进程**：``websockets`` 是本机已安装的运行时依赖，在测试进程里「假装它不存在」只能靠
篡改 ``sys.modules``——那会污染同进程其它用例（Uvicorn 的协议选择在 ``Config.load()`` 时缓存）。
所以这里起一个**独立解释器**，在 import 之前把 ``sys.modules["websockets"] = None``（Python 会因此
在 ``import websockets`` 时抛 ``ImportError``），然后真实绑定两个 listener，用**裸 socket** 发一次
WS 升级与一次普通 GET。

判据（Epic 54 判据 8）：缺依赖时 WS 升级回 **404**（不是 500 / 不是挂起），且同一进程的 HTTP 面
照常 200——「可选依赖缺席不得带崩主入口」。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import heagent

CHILD_SCRIPT = r"""
import asyncio, json, socket, sys

sys.modules["websockets"] = None  # 让 uvicorn 的 `import websockets` 抛 ImportError

from heagent.network.http_server import HttpRunService, HttpServer, HttpServerConfig
from heagent.network.ws_host import WsServer, WsServerConfig


async def _raw_get(port: int, request: bytes) -> int:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(request)
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        return int(line.split()[1])
    finally:
        writer.close()


async def main() -> None:
    # 关停预算压到 1s：探针只关心「404 vs 200」，不该为优雅关闭等 5s（否则一个判据要 15s）。
    config = HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0, shutdown_timeout=1)
    service = HttpRunService(config, None)
    http_server = HttpServer(config, version="test", run_service=service)
    ws_server = WsServer(WsServerConfig(port=0, shutdown_timeout=1), run_service=service)
    await http_server.start()
    await ws_server.start()
    http_task = asyncio.create_task(http_server.serve_forever())
    ws_task = asyncio.create_task(ws_server.serve_forever())
    try:
        upgrade = (
            "GET /api/runs/x/ws HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{ws_server.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
        ws_status = await _raw_get(ws_server.port, upgrade)
        health = (
            "GET /api/health HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{http_server.port}\r\nconnection: close\r\n\r\n"
        ).encode()
        http_status = await _raw_get(http_server.port, health)
        print(json.dumps({"ws_status": ws_status, "http_status": http_status}))
    finally:
        await http_server.close()
        await ws_server.close()
        for task in (http_task, ws_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(http_task, ws_task, return_exceptions=True)


asyncio.run(main())
"""


def test_ws_upgrade_returns_404_when_websockets_is_missing(tmp_path: Path) -> None:
    """缺 ``websockets``：WS 升级 404（非 500、非挂起），同进程 HTTP /api/health 仍 200。"""
    script = tmp_path / "probe_missing_websockets.py"
    script.write_text(CHILD_SCRIPT, encoding="utf-8")
    src_root = Path(heagent.__file__).resolve().parents[1]

    result = subprocess.run(  # noqa: S603 - argv 是内部构造的固定列表（本文件的探针脚本），不经 shell
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        # 继承父进程 env 再补 PYTHONPATH：子进程要能 import 到被测包（Windows 下缺 SYSTEMROOT 等会起不来）。
        env={**os.environ, "PYTHONPATH": str(src_root)},
    )

    assert result.returncode == 0, f"子进程失败：stdout={result.stdout!r} stderr={result.stderr!r}"
    # uvicorn 的安装诊断只做**宽松**匹配（措辞随版本变；判据是下面的 404/200，诊断只作旁证）。
    assert "websocket" in result.stderr.lower()
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["ws_status"] == 404
    assert payload["http_status"] == 200
