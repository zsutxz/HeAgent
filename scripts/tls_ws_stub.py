"""最小 WS stub：只回 ack 帧，用于自证 ``scripts/ws_manual_probe.py``（含 ``--insecure``）。

不给证书起明文 ``ws``（对照组）；给一对自签证书起 ``wss``：

  openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=127.0.0.1" ^
      -addext "subjectAltName=IP:127.0.0.1" -keyout key.pem -out cert.pem
  .venv\\Scripts\\python.exe scripts\\tls_ws_stub.py 9443 --cert cert.pem --key key.pem

它不实现任何业务语义（不改 run 状态、不建 record），只用来验证客户端侧的握手与帧收发。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl

from websockets.asyncio.server import serve


def ack(command: str | None) -> str:
    return json.dumps({"type": "ack", "command": command, "run_id": "", "status": "running"})


async def handler(websocket) -> None:
    async for raw in websocket:
        try:
            command = json.loads(raw).get("command")
        except (json.JSONDecodeError, AttributeError):
            command = None
        await websocket.send(ack(command))


async def main() -> None:
    parser = argparse.ArgumentParser(description="WS/wss ack stub")
    parser.add_argument("port", type=int, help="监听端口（回环 127.0.0.1）")
    parser.add_argument("--cert", default=None, help="证书 PEM；与 --key 成对给出即启用 TLS")
    parser.add_argument("--key", default=None, help="私钥 PEM")
    args = parser.parse_args()
    if (args.cert is None) != (args.key is None):
        parser.error("--cert 与 --key 必须成对给出")

    context = None
    if args.cert is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)

    async with serve(handler, "127.0.0.1", args.port, ssl=context):
        scheme = "wss" if context is not None else "ws"
        print(f"stub {scheme} listening on 127.0.0.1:{args.port}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
