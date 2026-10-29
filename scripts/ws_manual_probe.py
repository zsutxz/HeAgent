"""WebSocket 入口的手测探针（真实客户端，只读；不改服务端状态，submit/cancel 除外）。

用法（宿主 Windows，仓库根下；`.venv` 已装 websockets）：

  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py ws://127.0.0.1:9901 ping
  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py ws://127.0.0.1:9901 submit --prompt "写一个快速排序"
  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py ws://127.0.0.1:9901 sub <run_id>
  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py ws://127.0.0.1:9901 cancel <run_id>
  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py ws://127.0.0.1:9901 bad
  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py ws://127.0.0.1:9901 handshake --origin http://127.0.0.1:8766
  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py ws://127.0.0.1:9002 handshake --token "<你的 token>"
  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py wss://127.0.0.1:9901 ping --insecure
  .venv\\Scripts\\python.exe scripts\\ws_manual_probe.py ws://127.0.0.1:9901 cli --seconds 5

端点与入口归属（测之前先对号，否则 `cli` 用例必然 403）：

  /api/runs/ws              提交 run（`WS_ENABLED` 为真即注册）
  /api/runs/{run_id}/ws     订阅/取消（`WS_ENABLED` 为真即注册）
  /api/cli/ws               终端旁路：**只**在 `heagent` / `heagent "<prompt>"` 上挂载，
                            且需 `WS_CLI_BYPASS_ENABLED=true`；`heagent http-server` 显式
                            `cli_bypass=False`（无终端轮次）⇒ 打过去恒为 403。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

TERMINAL_KINDS = {"done", "error", "cancelled"}


def ok(message: str) -> None:
    print(f"PASS  {message}")


def fail(message: str) -> None:
    print(f"FAIL  {message}")


def show(direction: str, payload: object) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    print(f"  {direction} {text}")


def open_ws(args: argparse.Namespace, path: str, query: str = ""):
    kwargs: dict[str, object] = {"open_timeout": 5, "close_timeout": 5}
    if args.insecure:
        # 自签证书的 wss listener：只跳过证书校验，不改其它 TLS 默认（仍走 TLS 握手）。
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        kwargs["ssl"] = context
    if args.origin is not None:
        kwargs["origin"] = args.origin
    if args.token:
        kwargs["additional_headers"] = {"Authorization": f"Bearer {args.token}"}
    return connect(f"{args.base}{path}{query}", **kwargs)


async def recv_json(ws, timeout: float) -> dict | None:
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout)
    except TimeoutError:
        print(f"  .. {timeout:g}s 内没有新帧")
        return None
    except ConnectionClosed as exc:
        code = exc.rcvd.code if exc.rcvd else "?"
        reason = exc.rcvd.reason if exc.rcvd else "?"
        print(f"  -- 连接关闭 code={code} reason={reason}")
        return {"__closed__": True}
    show("<-", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"__notjson__": raw}


async def case_ping(args: argparse.Namespace) -> int:
    async with open_ws(args, "/api/runs/ws") as ws:
        show("->", '{"command":"ping"}')
        await ws.send('{"command":"ping"}')
        frame = await recv_json(ws, 5)
        if frame and frame.get("type") == "ack" and frame.get("command") == "ping":
            ok("集合端点回了 ack 帧（command=ping，run_id 应为空串）")
            return 0
        fail("ping 未回 ack 帧")
        return 1


async def case_submit(args: argparse.Namespace) -> int:
    async with open_ws(args, "/api/runs/ws") as ws:
        body = json.dumps({"command": "run", "prompt": args.prompt}, ensure_ascii=False)
        show("->", body)
        await ws.send(body)
        frame = await recv_json(ws, 10)
        if frame and frame.get("type") == "ack" and frame.get("run_id"):
            ok(f"提交成功，run_id={frame['run_id']} status={frame.get('status')}")
            print(f"RUN_ID={frame['run_id']}")
            return 0
        fail("提交未拿到 ack（看上面的错误帧）")
        return 1


async def case_sub(args: argparse.Namespace) -> int:
    query = f"?last_event_id={args.cursor}" if args.cursor is not None else ""
    path = f"/api/runs/{args.run_id}/ws"
    async with open_ws(args, path, query) as ws:
        print(f"connected: {args.base}{path}{query}")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + args.seconds
        while True:
            frame = await recv_json(ws, max(0.1, deadline - loop.time()))
            if frame is None:
                if loop.time() >= deadline:
                    print("(到达 --seconds 上限，主动退出)")
                    return 0
                continue
            if "__closed__" in frame:
                return 0
            event = frame.get("event") or {}
            if frame.get("type") == "event" and event.get("kind") in TERMINAL_KINDS:
                ok(f"收到终态事件 kind={event.get('kind')}")
                return 0


async def case_cancel(args: argparse.Namespace) -> int:
    async with open_ws(args, f"/api/runs/{args.run_id}/ws") as ws:
        print(f"connected: {args.base}/api/runs/{args.run_id}/ws")
        first = await recv_json(ws, 10)
        if first is None or "__closed__" in first:
            fail("订阅后无法读取帧，不能验证 cancel")
            return 1
        show("->", '{"command":"cancel"}')
        await ws.send('{"command":"cancel"}')
        loop = asyncio.get_running_loop()
        deadline = loop.time() + args.seconds
        while loop.time() < deadline:
            frame = await recv_json(ws, max(0.1, deadline - loop.time()))
            if frame is None or "__closed__" in frame:
                return 0
            event = frame.get("event") or {}
            if event.get("kind") in TERMINAL_KINDS:
                ok(f"取消后收到终态事件 kind={event.get('kind')}")
                return 0
        print("(到达 --seconds 上限，未见到终态事件)")
        return 1


async def case_bad(args: argparse.Namespace) -> int:
    async with open_ws(args, "/api/runs/ws") as ws:
        show("->", "not-json")
        await ws.send("not-json")
        frame = await recv_json(ws, 5)
        if frame and frame.get("type") == "error":
            ok("非法帧回了 error 帧")
        else:
            fail("非法帧未回 error 帧")
            return 1
        tail = await recv_json(ws, 5)
        if tail and "__closed__" in tail:
            ok("随后连接被关闭（期望 1008）")
        else:
            print("  （未观察到关闭，服务端可能仍持有连接）")
        return 0


async def case_handshake(args: argparse.Namespace) -> int:
    path = args.path or "/api/runs/ws"
    try:
        async with open_ws(args, path) as ws:
            print(f"connected: {args.base}{path}")
            await recv_json(ws, 1)
            ok("握手成功")
            return 0
    except InvalidStatus as exc:
        status = exc.response.status_code
        print(f"handshake rejected: HTTP {status}")
        if status == 403:
            ok("预期内的 403（Origin 不符 / token 不对 / 端点不存在，三者不可区分）")
            return 0
        fail(f"意外的握手状态 {status}")
        return 1


async def case_cli(args: argparse.Namespace) -> int:
    try:
        async with open_ws(args, "/api/cli/ws") as ws:
            print(f"connected: {args.base}/api/cli/ws（需要 WS_CLI_BYPASS_ENABLED=true）")
            if args.ping:
                show("->", '{"command":"ping"}')
                await ws.send('{"command":"ping"}')
            loop = asyncio.get_running_loop()
            deadline = loop.time() + args.seconds
            while loop.time() < deadline:
                frame = await recv_json(ws, max(0.1, deadline - loop.time()))
                if frame is not None and "__closed__" in frame:
                    return 0
            print("(到达 --seconds 上限，主动退出)")
            return 0
    except InvalidStatus as exc:
        status = exc.response.status_code
        print(f"handshake rejected: HTTP {status}")
        fail(
            "CLI 旁路不可用（403 = 路由未注册）：WS_CLI_BYPASS_ENABLED 未开 / "
            "当前入口是 http-server（显式 cli_bypass=False）/ 这条 listener 是对外模式"
        )
        return 1


CASES = {
    "ping": case_ping,
    "submit": case_submit,
    "sub": case_sub,
    "cancel": case_cancel,
    "bad": case_bad,
    "handshake": case_handshake,
    "cli": case_cli,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WebSocket 手测探针")
    parser.add_argument("base", help="ws://127.0.0.1:9901")
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("run_id", nargs="?", default=None, help="sub / cancel 需要")
    parser.add_argument("--prompt", default="ping", help="submit 用的 prompt")
    parser.add_argument("--token", default=None, help="对外 listener 的 Bearer token")
    parser.add_argument("--origin", default=None, help="显式发送 Origin 头（浏览器形态）")
    parser.add_argument("--cursor", type=int, default=None, help="订阅游标 ?last_event_id=")
    parser.add_argument("--path", default=None, help="handshake 用的路径")
    parser.add_argument("--seconds", type=float, default=15.0, help="接收窗口")
    parser.add_argument("--ping", action="store_true", help="cli 用例里先发一条 ping")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="wss + 自签证书时跳过证书校验（只影响本进程，不影响服务端）",
    )
    args = parser.parse_args(argv)
    if args.case in {"sub", "cancel"} and not args.run_id:
        parser.error(f"{args.case} 需要 run_id")
    args.base = args.base.rstrip("/")
    return asyncio.run(CASES[args.case](args))


if __name__ == "__main__":
    sys.exit(main())
