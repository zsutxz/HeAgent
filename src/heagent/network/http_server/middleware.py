"""ASGI 中间件与安全响应头（Story 62.1 自 ``network/http_server.py`` 拆出）。

同源防线（AD-6）、请求级观测（AD-9）与安全响应头（NFR6/NFR7）；包装顺序（由外到内）：
安全头 → 请求观测 → 同源防线 → 应用路由（装配在 ``app.build_http_app``）。
本模块不设 ``__all__``：中间件类不是包级公开名，也不进 exception 快照。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from heagent.network.http_protocol import HttpErrorCode, error_envelope
from heagent.network.origin import request_origin_violation
from heagent.pub.safe_logging import safe_log

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("heagent.network.http_server")

# 安全响应头（NFR6、NFR7）：严格 CSP + 禁嗅探 + 禁 framing + 不泄露 referrer。
#
# `default-src 'none'` 把所有资源默认关掉，再逐项开同源：页面因此**不能**加载第三方脚本、
# 字体或图片，也不能内联 script/style（`script-src 'self'` 不含 'unsafe-inline'）——
# 这正是「页面不依赖第三方脚本」这条验收项的机械保证。
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (
        b"content-security-policy",
        b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        b"img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    ),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    # 缓存默认不落副本：此前只有 SSE 路径带 `cache-control`，于是
    # `GET /api/session`（进程内会话快照：消息正文、标题、运行状态）与其它 JSON 响应都能被
    # 浏览器 / 中间代理缓存下来。**已显式设置的不覆盖**（中间件的既有语义）：静态资源自带
    # `no-cache`（允许缓存但必须回源校验）、SSE 自带
    # `no-store` + `x-accel-buffering: no` —— 两者都保持原样。
    (b"cache-control", b"no-store"),
)


async def _send_json(
    send: Send, status_code: int, payload: dict[str, Any], *, extra: tuple[tuple[bytes, bytes], ...] = ()
) -> None:
    """在**没有 Starlette 响应对象**的中间件层发一个 JSON 响应（保持错误信封一致）。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        *extra,
    ]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class _OriginGuardMiddleware:
    """同源防线（AD-6）：校验 Host，并在带 Origin 时要求它与 listener 同源。

    **defense-in-depth，不是认证**：能连上回环端口的本机进程可以伪造请求头直接调 API；
    这里的价值是挡住浏览器发起的跨站请求（CSRF）与 Host 伪装（DNS rebinding），并把
    forwarded-* 头这类「代理欺骗」明确拒掉。
    """

    def __init__(self, app: ASGIApp, *, hosts: frozenset[str], ports: frozenset[int] | None) -> None:
        self.app = app
        self.hosts = hosts
        self.ports = ports

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        violation = request_origin_violation(scope, hosts=self.hosts, ports=self.ports)
        if violation is None:
            await self.app(scope, receive, send)
            return
        # 违规原因只进服务端日志；客户端拿固定的脱敏文案（不透露允许的 host 集合）。
        safe_log(
            logger,
            logging.WARNING,
            "http event=origin_rejected method=%s path=%s reason=%s",
            scope.get("method"),
            scope.get("path"),
            violation,
        )
        await _send_json(
            send,
            403,
            error_envelope(HttpErrorCode.ORIGIN_FORBIDDEN, "request origin rejected").model_dump(mode="json"),
        )


class _AccessLogMiddleware:
    """请求级观测（AD-9）：每条请求一条日志 + 响应头 ``x-request-id``。

    只记 **方法 / 路径 / 状态码 / 耗时 / 不透明 request id**；**绝不**记请求体、请求头、
    提示词、回答或工具输出——内容字段一律排除，而不是靠脱敏去打补丁。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        status = 0

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 0))
                raw = list(message.get("headers") or [])
                raw.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": raw}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            safe_log(
                logger,
                logging.INFO if status < 400 else logging.WARNING,
                "http event=request request_id=%s method=%s path=%s status=%s elapsed_ms=%d",
                request_id,
                scope.get("method"),
                scope.get("path"),
                status,
                int((time.perf_counter() - started) * 1000),
            )


class _SecurityHeadersMiddleware:
    """给每个 HTTP 响应补安全头的纯 ASGI 包装（不吃框架内部 API，便于单独测试）。

    已存在的同名响应头**不覆盖**（框架或路由给了更具体取值时以它们为准，避免中间件把
    有意设置的头改回去）。
    """

    def __init__(self, app: ASGIApp, headers: tuple[tuple[bytes, bytes], ...]) -> None:
        self.app = app
        self.headers = headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                raw = list(message.get("headers") or [])
                present = {key.lower() for key, _ in raw}
                raw.extend((key, value) for key, value in self.headers if key.lower() not in present)
                message = {**message, "headers": raw}
            await send(message)

        await self.app(scope, receive, send_with_headers)
