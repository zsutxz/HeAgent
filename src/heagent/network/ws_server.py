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
    replay_then_follow,
)
from heagent.network.ws_auth import client_source
from heagent.network.ws_protocol import (
    WS_CLOSE_GOING_AWAY,
    WS_CLOSE_POLICY,
    WS_CLOSE_TOO_LARGE,
    WsAckFrame,
    WsCliAckFrame,
    WsCliEventFrame,
    WsCommand,
    WsCommandFrame,
    WsErrorFrame,
    WsEventFrame,
    WsFrameError,
    WsFrameErrorKind,
    WsHelloFrame,
    WsNotificationFrame,
    parse_command_frame,
)

# int64 的十进制最大位数（越长即非合法事件 id，不必再解析）。
_MAX_EVENT_ID_DIGITS = 19

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from heagent.network.cli_event_hub import CliEventHub, CliSubscription
    from heagent.network.notification_hub import NotificationHub, NotificationSubscription


class WebSocketLike(Protocol):
    """Starlette WebSocket 的最小结构化接口。"""

    scope: dict[str, Any]
    path_params: dict[str, Any]
    query_params: Any

    async def accept(self) -> None:
        """实现方在此完成握手（对应真实 websocket 的 `accept`）。"""

    ...

    async def close(self, code: int = 1000) -> None:
        """实现方以给定关闭码结束连接（认证失败用 1008）。"""

    ...

    async def receive_text(self) -> str:
        """实现方读一条文本帧；超长帧由实现方按 `WS_MAX_INBOUND_CHARS` 拒绝。"""

    ...

    async def send_text(self, data: str) -> None:
        """实现方发一条文本帧（服务端到客户端的唯一出口）。"""

    ...


OriginCheck = Callable[[dict[str, Any]], str | None]
#: 认证回调：``None`` = 通过，否则是拒绝原因。accept **之前**执行。
AuthCheck = Callable[[Mapping[str, Any]], str | None]


class RunWebSocketService(Protocol):
    """ws_server 所需的最小运行服务端口。

    Epic 56 D1：WS 连接额度自 ``HttpServerConfig`` 迁入 ``WsServerConfig``，经
    :func:`build_ws_endpoint` 的 ``max_connections`` 参数注入——端点因此不感知任何配置类。
    Epic 56 D2：``start_run`` 是**集合级端点**（经 WS 提交 run）的入口，与 ``POST /api/runs``
    共用同一个实现（名额判定/记录/任务生成只有一处）。
    """

    _closing: bool

    def run(self, run_id: str) -> Any | None:
        """按 run_id 取 run 记录；不存在返回 `None`（与「已结束但记录还在」区分开）。"""

    ...

    def needs_resync(self, record: Any, last_event_id: int | None) -> bool:
        """判断客户端是否需要重置：`last_event_id` 落后于记录的可回放窗口时为真。"""

    ...

    async def start_run(self, prompt: str) -> Any:
        """为一条 prompt 起 run 并返回记录（提交端点背后的一次调用）。"""

    ...

    async def cancel_run(self, run_id: str) -> Any | None:
        """取消指定 run；不存在或已终止返回 `None`。"""

    ...

    def register_ws(self, connection_id: str, run_id: str, websocket: WebSocketLike) -> None:
        """登记一个 WS 连接与 run 的绑定（推送与断线清理都靠这张表）。"""

    ...

    def unregister_ws(self, connection_id: str) -> None:
        """注销连接绑定；对未知 id 幂等无操作。"""

    ...


async def _send_error_frame(websocket: WebSocketLike, code: HttpErrorCode, message: str) -> None:
    """只发一条错误帧、**不关闭**连接（客户端可以继续发命令后重试）。"""
    envelope = error_envelope(code, message)
    await websocket.send_text(WsErrorFrame(error=envelope).model_dump_json())


async def _send_error(websocket: WebSocketLike, code: HttpErrorCode, message: str, *, close_code: int) -> None:
    await _send_error_frame(websocket, code, message)
    await websocket.close(code=close_code)


async def _send_hello(websocket: WebSocketLike, version: str) -> None:
    """accept() 后的**连接首帧**（56-9）：先于任何流帧，让客户端先拿到服务端版本。

    空版本（测试装配形态未注入）跳过并记 debug——生产装配恒注入（``cli/http`` 传
    ``heagent.__version__``），跳过可循证不静默。认证 / Origin 拒绝发生在 accept 之前，
    被拒连接不经 hello（协议面不扩）。
    """
    if not version:
        logger.debug("ws event=hello_skipped reason=version_not_injected")
        return
    await websocket.send_text(WsHelloFrame(version=version).model_dump_json())


async def _send_event_stream(
    websocket: WebSocketLike,
    record: Any,
    queue: asyncio.Queue[RunEventPayload | None],
    cursor: int | None,
) -> None:
    """按游标先重放 ring buffer，再写实时队列事件（重放/去重/终态语义单源 ``replay_then_follow``）。

    快照与终态在同一同步段内读出（无 ``await``），终态事件先于流结束（AD-4）；协议级 ping
    已由 Uvicorn 负责，这里不发应用层心跳。
    """
    snapshot = tuple(record.events)
    is_terminal = record.is_terminal
    async for event in replay_then_follow(snapshot, cursor=cursor, is_terminal=is_terminal, queue=queue):
        await websocket.send_text(WsEventFrame(event=event).model_dump_json())


async def _next_command(websocket: WebSocketLike) -> WsCommandFrame | None:
    """命令循环前导（四条 listener 共用）：收一帧并解析，异常一律收敛为「连接结束」信号。

    返回 ``None`` = 连接到此为止，调用方直接 ``return``：对端断开（``WebSocketDisconnect``）
    静默结束；帧违规则已按口径处置——``TOO_LARGE`` 以 ``1009`` close，其余回
    ``invalid_request`` 错误帧并以 ``WS_CLOSE_POLICY`` close。四条命令循环曾各抄一份
    这段前导（逐字重复），收单处后协议变化只改这里。
    """
    try:
        text = await websocket.receive_text()
    except Exception as exc:
        if type(exc).__name__ == "WebSocketDisconnect":
            return None
        raise
    try:
        return parse_command_frame(text)
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
        return None


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
        frame = await _next_command(websocket)
        if frame is None:
            return
        command = frame.command

        if command is WsCommand.RUN:
            # 提交能力只在集合级端点：这条连接早已绑定某个 run，回错误帧但**不断连**。
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
        frame = await _next_command(websocket)
        if frame is None:
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


async def _ws_session(
    websocket: WebSocketLike,
    *,
    transport: str,
    authorize: AuthCheck | None,
    origin_violation: OriginCheck,
    origin_run_id: str,
    version: str,
    log_prefix: str,
    log_name: str,
    log_run_id: str | None,
    closing_probe: Callable[[], bool],
    session: Callable[[WebSocketLike, str], Awaitable[None]],
    finalize: Callable[[str], None],
) -> None:
    """四条 listener 的**会话骨架**（A54①）：握手门 → accept/hello → 会话体 → 异常收敛 → 有界收尾。

    四个端点构造器曾各抄一遍这段骨架（计时/uuid 前导、认证与 Origin 门、accept、hello、关停
    检查、``CancelledError`` 重抛、异常收敛 ``server_error``+1011、finally 清理与 close 日志），
    协议变化要改四处。差异全部参数化：

    - ``origin_run_id``：Origin 拒绝日志里的 run_id 字段（run 端点带真值、集合级提交传 ``"-"``、
      CLI/通知流传空串＝不带字段）；
    - ``log_run_id``：open/failed/close 三条事件日志的 run_id（``None``＝日志不带该字段，区别于
      空串——run 端点即使路径参数为空也按旧口径带 ``run_id=`` 字段）；
    - ``closing_probe``：关停检查（run/提交读 ``service._closing``，只读流读 ``hub.closing``）；
    - ``session``：端点差异本体（限额、订阅、登记、会话循环），首个参数是连接、第二个是
      ``connection_id``（登记与 open 日志都要它）；
    - ``finalize``：finally 清理（归还席位 / 摘订阅 / 注销连接），**幂等且可判「未获得」**
      （提交席位只在真正 acquire 后才归还）。

    日志事件名与字段逐字节保持各自旧口径；骨架内不新增任何日志。
    """
    started = time.perf_counter()
    connection_id = uuid.uuid4().hex[:12]
    if await _reject_unauthenticated(websocket, authorize, transport=transport):
        return
    if await _reject_bad_origin(websocket, origin_violation, transport=transport, run_id=origin_run_id):
        return
    await websocket.accept()
    await _send_hello(websocket, version)
    try:
        if closing_probe():
            await _send_error(
                websocket,
                HttpErrorCode.SHUTTING_DOWN,
                "server is shutting down",
                close_code=WS_CLOSE_GOING_AWAY,
            )
            return
        await session(websocket, connection_id)
        with contextlib.suppress(Exception):
            await websocket.close()
    except asyncio.CancelledError:
        raise
    except Exception:
        if log_run_id is not None:
            logger.exception(
                "%s event=%s_failed run_id=%s connection_id=%s", log_prefix, log_name, log_run_id, connection_id
            )
        else:
            logger.exception("%s event=%s_failed connection_id=%s", log_prefix, log_name, connection_id)
        with contextlib.suppress(Exception):
            await _send_error(
                websocket,
                HttpErrorCode.SERVER_ERROR,
                "internal server error",
                close_code=1011,
            )
    finally:
        finalize(connection_id)
        elapsed = int((time.perf_counter() - started) * 1000)
        if log_run_id is not None:
            logger.info(
                "%s event=%s_close run_id=%s connection_id=%s elapsed_ms=%d",
                log_prefix,
                log_name,
                log_run_id,
                connection_id,
                elapsed,
            )
        else:
            logger.info(
                "%s event=%s_close connection_id=%s elapsed_ms=%d", log_prefix, log_name, connection_id, elapsed
            )


def build_runs_collection_endpoint(
    service: RunWebSocketService,
    *,
    origin_violation: OriginCheck,
    max_connections: int,
    authorize: AuthCheck | None = None,
    version: str = "",
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
        acquired = False

        async def session(ws: WebSocketLike, connection_id: str) -> None:
            nonlocal acquired
            # 席位 acquire 在关停检查之前（旧口径次序：满额连接先吃 rate_limited，
            # 即使服务同时在关停）；未 acquire 的路径绝不 release（骨架 finally 会调 finalize）。
            if not slots.try_acquire():
                await _send_error(
                    ws,
                    HttpErrorCode.RATE_LIMITED,
                    "too many WebSocket submit connections",
                    close_code=WS_CLOSE_POLICY,
                )
                return
            acquired = True
            if service._closing:
                await _send_error(
                    ws,
                    HttpErrorCode.SHUTTING_DOWN,
                    "server is shutting down",
                    close_code=WS_CLOSE_GOING_AWAY,
                )
                return
            logger.info("ws event=submit_open connection_id=%s", connection_id)
            await _handle_submit_commands(ws, service)

        def finalize(connection_id: str) -> None:
            if acquired:
                slots.release()

        await _ws_session(
            websocket,
            transport="runs_submit",
            authorize=authorize,
            origin_violation=origin_violation,
            origin_run_id="-",
            version=version,
            log_prefix="ws",
            log_name="submit",
            log_run_id=None,
            closing_probe=lambda: False,
            session=session,
            finalize=finalize,
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
    if not raw.isascii() or not raw.isdigit() or len(raw) > _MAX_EVENT_ID_DIGITS:
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
    version: str = "",
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造单 run WebSocket endpoint；Origin 规则、连接额度与认证由宿主单点注入。

    ``readonly`` 透传给命令处理：只读 listener 上 ``cancel`` 被拒绝、事件流照常。
    """

    async def endpoint(websocket: WebSocketLike) -> None:
        run_id = str(websocket.path_params.get("run_id", ""))
        state: dict[str, Any] = {"record": None, "queue": None, "registered": False}

        async def session(ws: WebSocketLike, connection_id: str) -> None:
            record, cursor, queue = await _prepare_subscription(ws, service, run_id, max_connections)
            if record is None or queue is None:
                return
            state["record"] = record
            state["queue"] = queue
            service.register_ws(connection_id, run_id, ws)
            state["registered"] = True
            logger.info("http event=ws_open run_id=%s connection_id=%s", run_id, connection_id)
            await _run_connection_tasks(ws, service, record, queue, cursor, run_id, readonly=readonly)

        def finalize(connection_id: str) -> None:
            record = state["record"]
            queue = state["queue"]
            if record is not None and queue is not None:
                record.ws_subscribers.discard(queue)
            if state["registered"]:
                service.unregister_ws(connection_id)

        await _ws_session(
            websocket,
            transport="runs",
            authorize=authorize,
            origin_violation=origin_violation,
            origin_run_id=run_id,
            version=version,
            log_prefix="http",
            log_name="ws",
            log_run_id=run_id,
            closing_probe=lambda: service._closing,
            session=session,
            finalize=finalize,
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
    # 带上来源地址：三条 listener 共用同一份日志，不带它无法区分「本机自己的客户端忘了带 token」
    # 与「网段里的某个探测者」，而两者处置完全不同（前者改客户端，后者无视或加限速）。
    logger.warning(
        "ws event=auth_rejected transport=%s reason=%s source=%s",
        transport,
        reason,
        client_source(websocket.scope),
    )
    await websocket.close(code=WS_CLOSE_POLICY)
    return True


async def _reject_bad_origin(
    websocket: WebSocketLike,
    origin_violation: OriginCheck,
    *,
    transport: str,
    run_id: str = "",
) -> bool:
    """握手前同源门——四条 listener 共用一份拒绝协议（检查、日志口径、close 协议单处决定）。

    与认证拒绝的区别：Origin 违规是「配置不符」（本机模式），认证失败是「凭证不对」（对外模式）；
    两者都在 accept 之前完成，客户端拿到的都是 HTTP 403（无 body）——对探测者而言，
    「没有这个端点」与「token/配置错」不可区分。日志保持各 listener 旧口径逐字节不变：
    run 端点带 ``run_id=`` 字段（集合级提交传 ``"-"``），CLI/通知流不带。
    """
    violation = origin_violation(websocket.scope)
    if violation is None:
        return False
    if run_id:
        logger.warning("http event=origin_rejected transport=%s run_id=%s reason=%s", transport, run_id, violation)
    else:
        logger.warning("http event=origin_rejected transport=%s reason=%s", transport, violation)
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
        frame = await _next_command(websocket)
        if frame is None:
            return
        command = frame.command

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
    version: str = "",
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造 CLI 旁路端点（``WS /api/cli/ws``）：只读观众席，跨轮次。

    与 :func:`build_ws_endpoint` 的三处差异都是**刻意的**：不按 ``run_id`` 路由（一条流看所有轮）、
    拒绝 ``cancel``（终端独占取消通道）、额度按 hub 计而不是按 run 计。认证门与 run 端点同源
    （D7：旁路随迁进 WS server，对外模式下同样要 token）。
    """

    async def endpoint(websocket: WebSocketLike) -> None:
        state: dict[str, Any] = {"subscription": None, "registered": False}

        async def session(ws: WebSocketLike, connection_id: str) -> None:
            cursor, invalid = _parse_cursor(ws)
            if invalid:
                await _send_error(ws, HttpErrorCode.INVALID_REQUEST, "invalid event cursor", close_code=WS_CLOSE_POLICY)
                return
            if hub.needs_resync(cursor):
                await _send_error(
                    ws,
                    HttpErrorCode.RESYNC_REQUIRED,
                    "event cursor is older than the buffered window; reconnect without a cursor",
                    close_code=WS_CLOSE_POLICY,
                )
                return
            subscription = hub.open_subscription(cursor)
            if subscription is None:
                await _send_error(
                    ws, HttpErrorCode.RATE_LIMITED, "too many WebSocket connections", close_code=WS_CLOSE_POLICY
                )
                return
            state["subscription"] = subscription
            hub.register_ws(connection_id, hub.active_run_id, ws)
            state["registered"] = True
            logger.info("http event=cli_ws_open connection_id=%s", connection_id)
            await _supervise(
                _cli_send_events(ws, subscription),
                _cli_handle_commands(ws, hub),
            )

        def finalize(connection_id: str) -> None:
            subscription = state["subscription"]
            if subscription is not None:
                hub.remove_subscriber(subscription.queue)
            if state["registered"]:
                hub.unregister_ws(connection_id)

        await _ws_session(
            websocket,
            transport="cli_ws",
            authorize=authorize,
            origin_violation=origin_violation,
            origin_run_id="",
            version=version,
            log_prefix="http",
            log_name="cli_ws",
            log_run_id=None,
            closing_probe=lambda: hub.closing,
            session=session,
            finalize=finalize,
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
        frame = await _next_command(websocket)
        if frame is None:
            return
        command = frame.command

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
    version: str = "",
) -> Callable[[WebSocketLike], Awaitable[None]]:
    """构造只读通知流端点（``WS /api/notifications/ws``）：跨作业、跨执行的一条流。

    与 :func:`build_cli_ws_endpoint` 的三处相同点都是刻意的：不按 id 路由（一条流看所有通知）、
    拒绝 ``cancel``（通知流没有可取消的对象）、额度按 hub 计而不是按作业计。差别只有一处：
    旁路的 ``run_id`` 在这里没有意义，ack 帧的 ``run_id`` 恒为空串。
    """

    async def endpoint(websocket: WebSocketLike) -> None:
        state: dict[str, Any] = {"subscription": None, "registered": False}

        async def session(ws: WebSocketLike, connection_id: str) -> None:
            cursor, invalid = _parse_cursor(ws)
            if invalid:
                await _send_error(ws, HttpErrorCode.INVALID_REQUEST, "invalid event cursor", close_code=WS_CLOSE_POLICY)
                return
            if hub.needs_resync(cursor):
                await _send_error(
                    ws,
                    HttpErrorCode.RESYNC_REQUIRED,
                    "event cursor is older than the buffered window; reconnect without a cursor",
                    close_code=WS_CLOSE_POLICY,
                )
                return
            subscription = hub.open_subscription(cursor)
            if subscription is None:
                await _send_error(
                    ws, HttpErrorCode.RATE_LIMITED, "too many WebSocket connections", close_code=WS_CLOSE_POLICY
                )
                return
            state["subscription"] = subscription
            hub.register_ws(connection_id, "", ws)
            state["registered"] = True
            logger.info("http event=notification_ws_open connection_id=%s", connection_id)
            await _supervise(
                _notification_send_events(ws, subscription),
                _notification_handle_commands(ws),
            )

        def finalize(connection_id: str) -> None:
            subscription = state["subscription"]
            if subscription is not None:
                hub.remove_subscriber(subscription.queue)
            if state["registered"]:
                hub.unregister_ws(connection_id)

        await _ws_session(
            websocket,
            transport="notifications",
            authorize=authorize,
            origin_violation=origin_violation,
            origin_run_id="",
            version=version,
            log_prefix="http",
            log_name="notification_ws",
            log_run_id=None,
            closing_probe=lambda: hub.closing,
            session=session,
            finalize=finalize,
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
