"""WebSocket run 订阅端点适配器（Epic 54）。

只依赖 WebSocket 结构协议与注入的服务回调，不导入 Starlette/Uvicorn 或 HTTP 实现模块。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from heagent.network.http_protocol import HttpErrorCode, RunEventPayload, error_envelope
from heagent.network.ws_protocol import (
    WS_CLOSE_GOING_AWAY,
    WS_CLOSE_POLICY,
    WS_CLOSE_TOO_LARGE,
    WsAckFrame,
    WsCliAckFrame,
    WsCliEventFrame,
    WsCommand,
    WsErrorFrame,
    WsEventFrame,
    WsFrameError,
    WsFrameErrorKind,
    parse_command_frame,
)

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from heagent.network.cli_event_hub import CliEventHub, CliSubscription


class WebSocketLike(Protocol):
    """Starlette WebSocket 的最小结构化接口。"""

    scope: dict[str, Any]
    path_params: dict[str, Any]
    query_params: Any

    async def accept(self) -> None: ...
    async def close(self, code: int = 1000) -> None: ...
    async def receive_text(self) -> str: ...
    async def send_text(self, data: str) -> None: ...


OriginCheck = Callable[[dict[str, Any]], str | None]


class RunWebSocketService(Protocol):
    """ws_server 所需的最小运行服务端口。

    Epic 56 D1：WS 连接额度自 ``HttpServerConfig`` 迁入 ``WsServerConfig``，经
    :func:`build_ws_endpoint` 的 ``max_connections`` 参数注入——端点因此不感知任何配置类。
    """

    _closing: bool

    def run(self, run_id: str) -> Any | None: ...
    def needs_resync(self, record: Any, last_event_id: int | None) -> bool: ...
    async def cancel_run(self, run_id: str) -> Any | None: ...
    def register_ws(self, connection_id: str, run_id: str, websocket: WebSocketLike) -> None: ...
    def unregister_ws(self, connection_id: str) -> None: ...


async def _send_error_frame(websocket: WebSocketLike, code: HttpErrorCode, message: str) -> None:
    """只发一条错误帧、**不关闭**连接（客户端可以继续发命令后重试）。"""
    envelope = error_envelope(code, message)
    await websocket.send_text(WsErrorFrame(error=envelope).model_dump_json())


async def _send_error(websocket: WebSocketLike, code: HttpErrorCode, message: str, *, close_code: int) -> None:
    await _send_error_frame(websocket, code, message)
    await websocket.close(code=close_code)


async def _send_event_stream(
    websocket: WebSocketLike,
    record: Any,
    queue: asyncio.Queue[RunEventPayload | None],
    cursor: int | None,
) -> None:
    """按游标先重放 ring buffer，再写实时队列事件。"""
    for event in tuple(record.events):
        if cursor is None or event.seq > cursor:
            await websocket.send_text(WsEventFrame(event=event).model_dump_json())
    if record.is_terminal:
        return
    while True:
        event = await queue.get()
        if event is None:
            return
        if cursor is None or event.seq > cursor:
            await websocket.send_text(WsEventFrame(event=event).model_dump_json())


async def _handle_commands(websocket: WebSocketLike, service: RunWebSocketService, run_id: str) -> None:
    """处理 cancel/ping 两条命令；断线异常由调用方收敛为连接结束。"""
    while True:
        try:
            text = await websocket.receive_text()
        except Exception as exc:
            if type(exc).__name__ == "WebSocketDisconnect":
                return
            raise
        try:
            command = parse_command_frame(text).command
        except WsFrameError as exc:
            if exc.kind is WsFrameErrorKind.TOO_LARGE:
                await websocket.close(code=WS_CLOSE_TOO_LARGE)
            else:
                await _send_error(
                    websocket,
                    HttpErrorCode.INVALID_REQUEST,
                    "invalid WebSocket command",
                    close_code=WS_CLOSE_POLICY,
                )
            return

        if command is WsCommand.CANCEL:
            current = await service.cancel_run(run_id)
        else:
            current = service.run(run_id)
        if current is None:
            await _send_error(websocket, HttpErrorCode.UNKNOWN_RUN, "no such run", close_code=WS_CLOSE_POLICY)
            return
        await websocket.send_text(WsAckFrame(command=command, run_id=run_id, status=current.status).model_dump_json())


async def _run_connection_tasks(
    websocket: WebSocketLike,
    service: RunWebSocketService,
    record: Any,
    queue: asyncio.Queue[RunEventPayload | None],
    cursor: int | None,
    run_id: str,
) -> None:
    """双向读写并发运行；任一路结束即取消另一侧并收尾。"""
    await _supervise(
        _send_event_stream(websocket, record, queue, cursor),
        _handle_commands(websocket, service, run_id),
    )


async def _supervise(*coros: Any) -> None:
    """并发跑两条协程，任一路结束即取消另一侧；先结束那一路的异常原样上抛。

    ``/api/runs/{id}/ws`` 与 CLI 旁路（``/api/cli/ws``）共用这一份收尾语义——两处各写一遍
    「cancel 剩下的 + 取回异常」很容易在其中一处漏掉 ``gather`` 回收，留下
    「Task exception was never retrieved」。
    """
    tasks = {asyncio.create_task(coro) for coro in coros}
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        exception = task.exception()
        if exception is not None:
            raise exception


def _parse_cursor(websocket: WebSocketLike) -> tuple[int | None, bool]:
    """解析可选游标；非法或超 int64 形态返回错误标记。"""
    raw = websocket.query_params.get("last_event_id")
    if raw is None:
        return None, False
    if not raw.isascii() or not raw.isdigit() or len(raw) > 19:
        return None, True
    return int(raw), False


async def _prepare_subscription(
    websocket: WebSocketLike,
    service: RunWebSocketService,
    run_id: str,
    max_connections: int,
) -> tuple[Any | None, int | None, asyncio.Queue[RunEventPayload | None] | None]:
    """验证运行与游标并原子登记独立 WS 配额。"""
    record = service.run(run_id)
    if record is None:
        await _send_error(websocket, HttpErrorCode.UNKNOWN_RUN, "no such run", close_code=WS_CLOSE_POLICY)
        return None, None, None
    cursor, invalid = _parse_cursor(websocket)
    if invalid:
        await _send_error(websocket, HttpErrorCode.INVALID_REQUEST, "invalid event cursor", close_code=WS_CLOSE_POLICY)
        return None, None, None
    if service.needs_resync(record, cursor):
        await _send_error(
            websocket,
            HttpErrorCode.RESYNC_REQUIRED,
            "event cursor is older than the buffered window; reload the session snapshot",
            close_code=WS_CLOSE_POLICY,
        )
        return None, None, None
    queue: asyncio.Queue[RunEventPayload | None] = asyncio.Queue(maxsize=record.subscriber_queue_size)
    if not record.try_add_ws_subscriber(queue, max_connections):
        await _send_error(
            websocket,
            HttpErrorCode.RATE_LIMITED,
            "too many WebSocket connections for this run",
            close_code=WS_CLOSE_POLICY,
        )
        return None, None, None
    return record, cursor, queue


def build_ws_endpoint(
    service: RunWebSocketService,
    *,
    origin_violation: OriginCheck,
    max_connections: int,
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造单 run WebSocket endpoint；Origin 规则与连接额度由宿主（ws_host/http_server 时代为后者）单点注入。"""

    async def endpoint(websocket: WebSocketLike) -> None:
        started = time.perf_counter()
        connection_id = uuid.uuid4().hex[:12]
        run_id = str(websocket.path_params.get("run_id", ""))
        if await _reject_bad_origin(websocket, origin_violation, run_id):
            return
        await websocket.accept()
        record: Any | None = None
        queue: asyncio.Queue[RunEventPayload | None] | None = None
        registered = False
        try:
            if service._closing:
                await _send_error(
                    websocket,
                    HttpErrorCode.SHUTTING_DOWN,
                    "server is shutting down",
                    close_code=WS_CLOSE_GOING_AWAY,
                )
                return
            record, cursor, queue = await _prepare_subscription(websocket, service, run_id, max_connections)
            if record is None or queue is None:
                return
            service.register_ws(connection_id, run_id, websocket)
            registered = True
            logger.info("http event=ws_open run_id=%s connection_id=%s", run_id, connection_id)
            await _run_connection_tasks(websocket, service, record, queue, cursor, run_id)
            with contextlib.suppress(Exception):
                await websocket.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("http event=ws_failed run_id=%s connection_id=%s", run_id, connection_id)
            with contextlib.suppress(Exception):
                await _send_error(
                    websocket,
                    HttpErrorCode.SERVER_ERROR,
                    "internal server error",
                    close_code=1011,
                )
        finally:
            if record is not None and queue is not None:
                record.ws_subscribers.discard(queue)
            if registered:
                service.unregister_ws(connection_id)
            logger.info(
                "http event=ws_close run_id=%s connection_id=%s elapsed_ms=%d",
                run_id,
                connection_id,
                int((time.perf_counter() - started) * 1000),
            )

    return endpoint


async def _reject_bad_origin(websocket: WebSocketLike, origin_violation: OriginCheck, run_id: str) -> bool:
    violation = origin_violation(websocket.scope)
    if violation is None:
        return False
    logger.warning("http event=origin_rejected transport=ws run_id=%s reason=%s", run_id, violation)
    # 在 accept 前 close：客户端拿 HTTP 403；不透出 host allow-list 或错误信封。
    await websocket.close()
    return True


async def _cli_send_events(websocket: WebSocketLike, subscription: CliSubscription) -> None:
    """先重放 backlog，再写实时队列；``None`` 哨兵表示「服务端结束该流」。"""
    for run_id, payload in subscription.backlog:
        await websocket.send_text(WsCliEventFrame(run_id=run_id, event=payload).model_dump_json())
    while True:
        item = await subscription.queue.get()
        if item is None:
            return
        run_id, payload = item
        await websocket.send_text(WsCliEventFrame(run_id=run_id, event=payload).model_dump_json())


async def _cli_handle_commands(websocket: WebSocketLike, hub: CliEventHub) -> None:
    """CLI 旁路的命令面：``ping`` 回 ack；``cancel`` 明确拒绝且**不断连接**。

    旁路不拥有运行——终端才是所有者，取消通道仍然是 Ctrl+C / 双击 Esc。把 ``cancel`` 做成
    「不支持」而不是「静默忽略」，是为了让客户端**知道**它连的是观众席。
    """
    while True:
        try:
            text = await websocket.receive_text()
        except Exception as exc:
            if type(exc).__name__ == "WebSocketDisconnect":
                return
            raise
        try:
            command = parse_command_frame(text).command
        except WsFrameError as exc:
            if exc.kind is WsFrameErrorKind.TOO_LARGE:
                await websocket.close(code=WS_CLOSE_TOO_LARGE)
            else:
                await _send_error(
                    websocket,
                    HttpErrorCode.INVALID_REQUEST,
                    "invalid WebSocket command",
                    close_code=WS_CLOSE_POLICY,
                )
            return

        if command is WsCommand.CANCEL:
            await _send_error_frame(
                websocket,
                HttpErrorCode.INVALID_REQUEST,
                "cancel is not supported on the CLI event stream",
            )
            continue
        await websocket.send_text(WsCliAckFrame(command=command, run_id=hub.active_run_id).model_dump_json())


def build_cli_ws_endpoint(
    hub: CliEventHub,
    *,
    origin_violation: OriginCheck,
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造 CLI 旁路端点（``WS /api/cli/ws``）：只读观众席，跨轮次。

    与 :func:`build_ws_endpoint` 的三处差异都是**刻意的**：不按 ``run_id`` 路由（一条流看所有轮）、
    拒绝 ``cancel``（终端独占取消通道）、额度按 hub 计而不是按 run 计。
    """

    async def endpoint(websocket: WebSocketLike) -> None:
        started = time.perf_counter()
        connection_id = uuid.uuid4().hex[:12]
        violation = origin_violation(websocket.scope)
        if violation is not None:
            logger.warning("http event=origin_rejected transport=cli_ws reason=%s", violation)
            # 在 accept 前 close：客户端拿 HTTP 403；不透出 host allow-list 或错误信封。
            await websocket.close()
            return
        await websocket.accept()
        subscription: CliSubscription | None = None
        registered = False
        try:
            if hub.closing:
                await _send_error(
                    websocket,
                    HttpErrorCode.SHUTTING_DOWN,
                    "server is shutting down",
                    close_code=WS_CLOSE_GOING_AWAY,
                )
                return
            cursor, invalid = _parse_cursor(websocket)
            if invalid:
                await _send_error(
                    websocket,
                    HttpErrorCode.INVALID_REQUEST,
                    "invalid event cursor",
                    close_code=WS_CLOSE_POLICY,
                )
                return
            if hub.needs_resync(cursor):
                await _send_error(
                    websocket,
                    HttpErrorCode.RESYNC_REQUIRED,
                    "event cursor is older than the buffered window; reconnect without a cursor",
                    close_code=WS_CLOSE_POLICY,
                )
                return
            subscription = hub.open_subscription(cursor)
            if subscription is None:
                await _send_error(
                    websocket,
                    HttpErrorCode.RATE_LIMITED,
                    "too many WebSocket connections",
                    close_code=WS_CLOSE_POLICY,
                )
                return
            hub.register_ws(connection_id, hub.active_run_id, websocket)
            registered = True
            logger.info("http event=cli_ws_open connection_id=%s", connection_id)
            await _supervise(
                _cli_send_events(websocket, subscription),
                _cli_handle_commands(websocket, hub),
            )
            with contextlib.suppress(Exception):
                await websocket.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("http event=cli_ws_failed connection_id=%s", connection_id)
            with contextlib.suppress(Exception):
                await _send_error(
                    websocket,
                    HttpErrorCode.SERVER_ERROR,
                    "internal server error",
                    close_code=1011,
                )
        finally:
            if subscription is not None:
                hub.remove_subscriber(subscription.queue)
            if registered:
                hub.unregister_ws(connection_id)
            logger.info(
                "http event=cli_ws_close connection_id=%s elapsed_ms=%d",
                connection_id,
                int((time.perf_counter() - started) * 1000),
            )

    return endpoint


__all__ = [
    "RunWebSocketService",
    "WebSocketLike",
    "build_cli_ws_endpoint",
    "build_ws_endpoint",
]
