"""WebSocket run 订阅端点适配器（Epic 54）。

只依赖 WebSocket 结构协议与注入的服务回调，不导入 Starlette/Uvicorn 或 HTTP 实现模块。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import ValidationError

from heagent.network.http_protocol import (
    HttpErrorCode,
    HttpRunConflictError,
    RunEventPayload,
    RunRequest,
    error_envelope,
)
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
    WsNotificationFrame,
    parse_command_frame,
)

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from heagent.network.cli_event_hub import CliEventHub, CliSubscription
    from heagent.network.notification_hub import NotificationHub, NotificationSubscription


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
#: 认证回调：``None`` = 通过，否则是拒绝原因（Epic 56 D3）。accept **之前**执行。
AuthCheck = Callable[[Mapping[str, Any]], str | None]


class RunWebSocketService(Protocol):
    """ws_server 所需的最小运行服务端口。

    Epic 56 D1：WS 连接额度自 ``HttpServerConfig`` 迁入 ``WsServerConfig``，经
    :func:`build_ws_endpoint` 的 ``max_connections`` 参数注入——端点因此不感知任何配置类。
    Epic 56 D2：``start_run`` 是**集合级端点**（经 WS 提交 run）的入口，与 ``POST /api/runs``
    共用同一个实现（名额判定/记录/任务生成只有一处）。
    """

    _closing: bool

    def run(self, run_id: str) -> Any | None: ...
    def needs_resync(self, record: Any, last_event_id: int | None) -> bool: ...
    async def start_run(self, prompt: str) -> Any: ...
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


async def _handle_commands(
    websocket: WebSocketLike,
    service: RunWebSocketService,
    run_id: str,
    *,
    readonly: bool = False,
) -> None:
    """处理 cancel/ping 两条命令；断线异常由调用方收敛为连接结束。

    ``readonly``（只读旁观 listener）只禁**控制面**命令：``cancel`` 回 ``invalid_request`` 且
    **不断连**（订阅者继续收事件），``ping`` 照常。用「不支持」而不是「静默忽略」——客户端必须
    知道它连的是观众席。
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

        if command is WsCommand.RUN:
            # 提交能力只在集合级端点（D2）：这条连接早已绑定某个 run，回错误帧但**不断连**。
            await _send_error_frame(
                websocket,
                HttpErrorCode.INVALID_REQUEST,
                "the run command is only accepted on the run collection endpoint",
            )
            continue

        if command is WsCommand.CANCEL:
            if readonly:
                await _send_error_frame(
                    websocket,
                    HttpErrorCode.INVALID_REQUEST,
                    "this listener is read-only; cancel is not available",
                )
                continue
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
    *,
    readonly: bool = False,
) -> None:
    """双向读写并发运行；任一路结束即取消另一侧并收尾。"""
    await _supervise(
        _send_event_stream(websocket, record, queue, cursor),
        _handle_commands(websocket, service, run_id, readonly=readonly),
    )


class _SubmissionSlots:
    """提交连接席位的**原子**计数（检查 + 登记在同一个同步方法内完成，A9③ 口径）。

    提交端点不订阅事件、不建 run 记录，因此它没有 run 端点那种「按 run 计」的额度；但一条
    空闲连接同样占着内存与文件描述符，且 Uvicorn 的 ``limit_concurrency`` **不约束 WS 连接**
    （Epic 54 实测）。对外模式下这等于「拿着 token 就能开无限条空闲连接」——所以这里补一个与
    ``ws_max_connections`` 同额度的席位池：检查与登记不可分割，绝不用「先查后加」两段代码
    （并发握手能一起穿过限额，活动台账 A9③ 的老坑）。
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._in_use = 0

    @property
    def in_use(self) -> int:
        """当前占用的席位（诊断与判据用）。"""
        return self._in_use

    def try_acquire(self) -> bool:
        """原子地占一个席位；满则返回 ``False``（调用方回 ``rate_limited`` 并关闭连接）。"""
        if self._in_use >= self._limit:
            return False
        self._in_use += 1
        return True

    def release(self) -> None:
        """归还一个席位（下限守 0，重复归还不放大额度）。"""
        if self._in_use > 0:
            self._in_use -= 1


def _is_blank_prompt(error: ValidationError) -> bool:
    """``RunRequest`` 的「非空」校验失败 ⇒ ``empty_prompt``（与 HTTP 400 的分类口径一致）。"""
    return any("blank" in str(item.get("msg", "")) for item in error.errors())


async def _submit_run(websocket: WebSocketLike, service: RunWebSocketService, prompt: str) -> None:
    """提交一次运行：校验复用 ``RunRequest``，创建复用 ``HttpRunService.start_run``。

    错误一律走错误帧且**不断连**（客户端可继续提交）：输入类 ``empty_prompt`` / ``invalid_request``、
    名额类 ``run_conflict`` / ``total_inflight_limit`` / 关停 ``shutting_down``——与
    ``POST /api/runs`` 的状态码语义一一对应，只是换了传输层。
    """
    try:
        request = RunRequest.model_validate({"prompt": prompt})
    except ValidationError as exc:
        code = HttpErrorCode.EMPTY_PROMPT if _is_blank_prompt(exc) else HttpErrorCode.INVALID_REQUEST
        await _send_error_frame(websocket, code, "prompt is invalid")
        return
    try:
        record = await service.start_run(request.prompt)
    except HttpRunConflictError as exc:
        await _send_error_frame(websocket, exc.code, str(exc))
        return
    await websocket.send_text(
        WsAckFrame(command=WsCommand.RUN, run_id=record.run_id, status=record.status).model_dump_json()
    )


async def _handle_submit_commands(websocket: WebSocketLike, service: RunWebSocketService) -> None:
    """集合级连接的命令循环：``run``（提交）与 ``ping``；``cancel`` 明确拒绝且不断连。

    这条连接**不绑定任何 run**（D2 的期一形状：提交连接不转事件流）。客户端拿到 ack 里的
    ``run_id`` 后经既有 ``/api/runs/{run_id}/ws`` 订阅——单 run 端点形状因此保持不变。
    """
    while True:
        try:
            text = await websocket.receive_text()
        except Exception as exc:
            if type(exc).__name__ == "WebSocketDisconnect":
                return
            raise
        try:
            frame = parse_command_frame(text)
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

        if frame.command is WsCommand.RUN:
            await _submit_run(websocket, service, frame.prompt or "")
            continue
        if frame.command is WsCommand.CANCEL:
            # 没有 run 绑定就没有可取消对象：与 CLI 旁路的处理同形（显式不支持，不静默忽略）。
            await _send_error_frame(
                websocket,
                HttpErrorCode.INVALID_REQUEST,
                "cancel requires a run subscription (use /api/runs/{run_id}/ws)",
            )
            continue
        # ping：连接级 ack（不带 RunStatus，run_id 为空串 = 此刻无绑定）。
        await websocket.send_text(WsCliAckFrame(command=frame.command, run_id="").model_dump_json())


def build_runs_collection_endpoint(
    service: RunWebSocketService,
    *,
    origin_violation: OriginCheck,
    max_connections: int,
    authorize: AuthCheck | None = None,
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造**集合级**端点（``WS /api/runs/ws``）：经 WS 提交 run（Epic 56 D2）。

    与 ``build_ws_endpoint`` 的关键差异：路径里没有 ``run_id``，因此不查询 run、不订阅事件、
    不占 WS 订阅名额——它只是「提交 + ack」的命令通道。提交出的运行仍归 ``HttpRunService``
    所有（名额 / 记录 / 任务生成全部复用），所以 D6 的单用户共享语义自动成立。

    ``max_connections`` 是这条**连接**面自己的席位池（见 :class:`_SubmissionSlots`）：额度取
    ``WsServerConfig.ws_max_connections``，与 run 订阅额度同值但各自计数（一条连接只做提交、
    不订阅，混在一个池里会让调订阅额度意外地限制提交通道）。
    """
    slots = _SubmissionSlots(max_connections)

    async def endpoint(websocket: WebSocketLike) -> None:
        started = time.perf_counter()
        connection_id = uuid.uuid4().hex[:12]
        if await _reject_unauthenticated(websocket, authorize, transport="runs_submit"):
            return
        if await _reject_bad_origin(websocket, origin_violation, "-"):
            return
        await websocket.accept()
        if not slots.try_acquire():
            await _send_error(
                websocket,
                HttpErrorCode.RATE_LIMITED,
                "too many WebSocket submit connections",
                close_code=WS_CLOSE_POLICY,
            )
            return
        try:
            if service._closing:
                await _send_error(
                    websocket,
                    HttpErrorCode.SHUTTING_DOWN,
                    "server is shutting down",
                    close_code=WS_CLOSE_GOING_AWAY,
                )
                return
            logger.info("ws event=submit_open connection_id=%s", connection_id)
            await _handle_submit_commands(websocket, service)
            with contextlib.suppress(Exception):
                await websocket.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ws event=submit_failed connection_id=%s", connection_id)
            with contextlib.suppress(Exception):
                await _send_error(
                    websocket,
                    HttpErrorCode.SERVER_ERROR,
                    "internal server error",
                    close_code=1011,
                )
        finally:
            slots.release()
            logger.info(
                "ws event=submit_close connection_id=%s elapsed_ms=%d",
                connection_id,
                int((time.perf_counter() - started) * 1000),
            )

    return endpoint


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
    authorize: AuthCheck | None = None,
    readonly: bool = False,
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造单 run WebSocket endpoint；Origin 规则、连接额度与认证由宿主单点注入。

    ``readonly`` 透传给命令处理：只读 listener 上 ``cancel`` 被拒绝、事件流照常。
    """

    async def endpoint(websocket: WebSocketLike) -> None:
        started = time.perf_counter()
        connection_id = uuid.uuid4().hex[:12]
        run_id = str(websocket.path_params.get("run_id", ""))
        if await _reject_unauthenticated(websocket, authorize, transport="runs"):
            return
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
            await _run_connection_tasks(websocket, service, record, queue, cursor, run_id, readonly=readonly)
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


async def _reject_unauthenticated(websocket: WebSocketLike, authorize: AuthCheck | None, *, transport: str) -> bool:
    """握手前认证（Epic 56 D3）：失败时**未 accept 即 close(1008)**，不发错误信封。

    与 Origin 拒绝的区别：Origin 违规是「配置不符」（本机模式），认证失败是「凭证不对」
    （对外模式）。两者都在 accept 之前完成，因此客户端拿到的都是 HTTP 403（无 body）——
    对探测者而言，「没有这个端点」与「token 错」不可区分。
    """
    if authorize is None:
        return False
    reason = authorize(websocket.scope)
    if reason is None:
        return False
    logger.warning("ws event=auth_rejected transport=%s reason=%s", transport, reason)
    await websocket.close(code=WS_CLOSE_POLICY)
    return True


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
        if command is WsCommand.RUN:
            await _send_error_frame(
                websocket,
                HttpErrorCode.INVALID_REQUEST,
                "the run command is only accepted on the run collection endpoint",
            )
            continue
        await websocket.send_text(WsCliAckFrame(command=command, run_id=hub.active_run_id).model_dump_json())


def build_cli_ws_endpoint(
    hub: CliEventHub,
    *,
    origin_violation: OriginCheck,
    authorize: AuthCheck | None = None,
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造 CLI 旁路端点（``WS /api/cli/ws``）：只读观众席，跨轮次。

    与 :func:`build_ws_endpoint` 的三处差异都是**刻意的**：不按 ``run_id`` 路由（一条流看所有轮）、
    拒绝 ``cancel``（终端独占取消通道）、额度按 hub 计而不是按 run 计。认证门与 run 端点同源
    （D7：旁路随迁进 WS server，对外模式下同样要 token）。
    """

    async def endpoint(websocket: WebSocketLike) -> None:
        started = time.perf_counter()
        connection_id = uuid.uuid4().hex[:12]
        if await _reject_unauthenticated(websocket, authorize, transport="cli_ws"):
            return
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


async def _notification_send_events(websocket: WebSocketLike, subscription: NotificationSubscription) -> None:
    """先重放 backlog，再写实时队列；``None`` 哨兵表示「服务端结束该流」。

    stream id 只在中枢内部用于日志与关停：通知帧不带它（客户端按 ``job_id`` + ``seq`` 定位）。
    """
    for _stream_id, payload in subscription.backlog:
        await websocket.send_text(WsNotificationFrame(notification=payload).model_dump_json())
    while True:
        item = await subscription.queue.get()
        if item is None:
            return
        _stream_id, payload = item
        await websocket.send_text(WsNotificationFrame(notification=payload).model_dump_json())


async def _notification_handle_commands(websocket: WebSocketLike) -> None:
    """通知流的命令面：``ping`` 回 ack；``cancel`` / ``run`` 一律拒绝且**不断连接**。

    与 CLI 旁路同口径：只读流不拥有任何东西，把「不支持」说出来（而不是静默忽略），客户端
    才知道它连的是通知流。
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

        if command is WsCommand.RUN:
            await _send_error_frame(
                websocket,
                HttpErrorCode.INVALID_REQUEST,
                "the run command is only accepted on the run collection endpoint",
            )
            continue
        if command is WsCommand.CANCEL:
            await _send_error_frame(
                websocket,
                HttpErrorCode.INVALID_REQUEST,
                "the notification stream is read-only; there is nothing to cancel",
            )
            continue
        await websocket.send_text(WsCliAckFrame(command=command, run_id="").model_dump_json())


def build_notification_ws_endpoint(
    hub: NotificationHub,
    *,
    origin_violation: OriginCheck,
    authorize: AuthCheck | None = None,
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造只读通知流端点（``WS /api/notifications/ws``）：跨作业、跨执行的一条流。

    与 :func:`build_cli_ws_endpoint` 的三处相同点都是刻意的：不按 id 路由（一条流看所有通知）、
    拒绝 ``cancel``（通知流没有可取消的对象）、额度按 hub 计而不是按作业计。差别只有一处：
    旁路的 ``run_id`` 在这里没有意义，ack 帧的 ``run_id`` 恒为空串。
    """

    async def endpoint(websocket: WebSocketLike) -> None:
        started = time.perf_counter()
        connection_id = uuid.uuid4().hex[:12]
        if await _reject_unauthenticated(websocket, authorize, transport="notifications"):
            return
        violation = origin_violation(websocket.scope)
        if violation is not None:
            logger.warning("http event=origin_rejected transport=notifications reason=%s", violation)
            # 在 accept 前 close：客户端拿 HTTP 403；不透出 host allow-list 或错误信封。
            await websocket.close()
            return
        await websocket.accept()
        subscription: NotificationSubscription | None = None
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
            hub.register_ws(connection_id, "", websocket)
            registered = True
            logger.info("http event=notification_ws_open connection_id=%s", connection_id)
            await _supervise(
                _notification_send_events(websocket, subscription),
                _notification_handle_commands(websocket),
            )
            with contextlib.suppress(Exception):
                await websocket.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("http event=notification_ws_failed connection_id=%s", connection_id)
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
                "http event=notification_ws_close connection_id=%s elapsed_ms=%d",
                connection_id,
                int((time.perf_counter() - started) * 1000),
            )

    return endpoint


__all__ = [
    "AuthCheck",
    "RunWebSocketService",
    "WebSocketLike",
    "build_cli_ws_endpoint",
    "build_notification_ws_endpoint",
    "build_runs_collection_endpoint",
    "build_ws_endpoint",
]
