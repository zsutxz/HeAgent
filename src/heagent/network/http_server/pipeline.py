"""请求管线：有界读体、校验、错误信封与 SSE 编码（Story 62.1 自 ``network/http_server.py`` 拆出）。

端点闭包共用的 helper 收在这里：``_read_model`` / ``_json_error`` / ``_sse_stream`` /
``_parse_last_event_id``；``_CONSOLE_ERROR_STATUS`` 是控制台稳定错误码 → HTTP 状态的集中
声明表（``scripts/contract_snapshot.py`` 按名提取，因此必须保持模块级字面量 dict）。

``__all__`` 显式列出包内公开名：包级再导出（``__init__.py``）与 exception 快照
（``scripts/contract_snapshot.py``）都以「定义模块的 ``__all__``」为收录依据。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from heagent.network.http_console_protocol import ConsoleOperationError
from heagent.network.http_protocol import (
    SSE_HEARTBEAT_FRAME,
    SSE_HEARTBEAT_SECONDS,
    HttpErrorCode,
    error_envelope,
)
from heagent.pub.safe_logging import safe_log

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncIterator

    from heagent.network.http_protocol import RunEventPayload

    from .config import HttpServerConfig
    from .records import _RunRecord
    from .service import HttpRunService

logger = logging.getLogger("heagent.network.http_server")

__all__ = ["HttpRequestTooLargeError"]

# ``Last-Event-ID`` 的最大位数：够放 int64，且远小于 CPython 对 ``int()`` 的位数上限（3.11+ 起
# 超长数字串会直接 ValueError）。位数为界既是语义约束也是拒绝面约束。
_MAX_EVENT_ID_DIGITS = 19


def _json_error(responses: Any, code: HttpErrorCode, message: str, *, status_code: int) -> Any:
    """统一的 JSON 错误响应（有界、脱敏、结构稳定，AD-8）。"""
    return responses.JSONResponse(
        error_envelope(code, message).model_dump(mode="json"),
        status_code=status_code,
    )


class HttpRequestTooLargeError(RuntimeError):
    """请求体超过 ``max_request_bytes``（**未读完**即拒绝）。"""


async def _read_body(request: Any, *, limit: int) -> bytes:
    """按块读取请求体；超限立即中断。

    **不能**用 Starlette 的 ``request.body()``：它会把整个 body 读进内存再交给我们——对不可信
    客户端这等于把「有界」交给对方决定。
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HttpRequestTooLargeError(f"request body exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_model(
    request: Any,
    *,
    model: Any,
    config: HttpServerConfig,
    responses: Any,
    blank_code: HttpErrorCode | None = None,
) -> tuple[Any, Any | None]:
    """读请求体并校验为 ``model``：返回 ``(parsed, error_response)``（恰有一个非 ``None``）。

    把「有界读 + Pydantic 校验 + 统一错误信封」收在一处：``POST /api/runs`` 与三条控制台写路由
    因此共用同一套 413/400 语义（取值与 49-3 一致，不因重构而漂移）。

    ``parsed`` 的类型是 ``Any`` 而不是 ``| None``：契约是「要么拿到了模型、要么调用方已经被
    ``if error is not None: return error`` 短路掉」。让类型带上 ``| None`` 只会逼 9 处调用点重复同一句
    收窄断言，换不来任何真实保证（错误路径返回的 ``None`` 永远到不了使用点）。
    """
    try:
        raw = await _read_body(request, limit=config.max_request_bytes)
    except HttpRequestTooLargeError:
        return None, _json_error(
            responses,
            HttpErrorCode.REQUEST_TOO_LARGE,
            "request body exceeds the configured limit",
            status_code=413,
        )
    try:
        return model.model_validate_json(raw), None
    except ValidationError as exc:
        code = HttpErrorCode.INVALID_REQUEST
        if blank_code is not None and any("blank" in str(error.get("msg", "")) for error in exc.errors()):
            code = blank_code
        return None, _json_error(responses, code, "request body is invalid", status_code=400)


# 控制台稳定错误码 → HTTP 状态码（未列出的码按 400 处理；未知码由下面的函数降级为 500）。
_CONSOLE_ERROR_STATUS: dict[HttpErrorCode, int] = {
    HttpErrorCode.INVALID_REQUEST: 400,
    HttpErrorCode.INVALID_PROJECT_PATH: 400,
    HttpErrorCode.INVALID_SESSION_ID: 400,
    HttpErrorCode.CONFIRM_REQUIRED: 400,
    HttpErrorCode.UNKNOWN_PROJECT: 404,
    HttpErrorCode.UNKNOWN_SESSION: 404,
    HttpErrorCode.PROJECT_UNAVAILABLE: 409,
    HttpErrorCode.PROJECT_NOT_REMOVABLE: 409,
    HttpErrorCode.PROJECT_BUSY: 409,
    HttpErrorCode.PROJECT_LIMIT_REACHED: 409,
    HttpErrorCode.SESSION_CONFLICT: 409,
    HttpErrorCode.SESSION_BUSY: 409,
    HttpErrorCode.SESSION_UNREADABLE: 409,
    HttpErrorCode.RUN_CONFLICT: 409,
    # 服务级总额（跨项目共享）已满：同样是「等一次运行结束」，但等的是**任何**一次运行。
    HttpErrorCode.TOTAL_INFLIGHT_LIMIT: 409,
    HttpErrorCode.LOOPBACK_REQUIRED: 403,
    # 原生目录选择：后端不可用 → 503（不是客户端错误）；已有一次在途 → 409。
    HttpErrorCode.DIALOG_UNAVAILABLE: 503,
    HttpErrorCode.DIALOG_BUSY: 409,
    # 配置写入通道：闸门关 / 键只读 → 403；值非法 → 400；指纹冲突 → 409；写失败 → 500。
    HttpErrorCode.WRITE_DISABLED: 403,
    HttpErrorCode.FIELD_NOT_WRITABLE: 400,
    HttpErrorCode.INVALID_VALUE: 400,
    HttpErrorCode.CONFIG_CONFLICT: 409,
    HttpErrorCode.CONFIG_WRITE_FAILED: 500,
    # 服务端状态类失败（如注册表内容无法解析 ⇒ 拒绝改写）：显式 500，别落到默认 400。
    HttpErrorCode.SERVER_ERROR: 500,
}


def _console_error_response(responses: Any, exc: BaseException, *, event: str) -> Any:
    """注入的控制台失败时的统一响应。

    ``ConsoleOperationError`` 携带**稳定码**，映射为固定状态码；其它异常一律 500 + 固定文案，
    诊断细节只进服务端日志（AD-8/AD-9）。码不在闭集内（入口层写错）时降级为 500 并留下 ERROR，
    绝不把未知码原样回给客户端。
    """
    if isinstance(exc, ConsoleOperationError):
        try:
            code = HttpErrorCode(exc.code)
        except ValueError:
            safe_log(logger, logging.ERROR, "http event=%s unknown_console_code=%s", event, exc.code)
            return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=500)
        return _json_error(responses, code, str(exc), status_code=_CONSOLE_ERROR_STATUS.get(code, 400))
    safe_log(logger, logging.ERROR, "http event=%s handler_failed", event, exc_info=True)
    return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=500)


def format_sse(payload: RunEventPayload) -> bytes:
    """把一条事件编码为 SSE 帧（``id`` / ``event`` / ``data``，以空行结束）。

    ``data`` 是单行 JSON（``json`` 转义会吃掉换行），因此整帧不会出现「意外的多行 data」。
    """
    data = payload.model_dump_json(exclude_none=True, ensure_ascii=False)
    return f"id: {payload.seq}\nevent: {payload.kind.value}\ndata: {data}\n\n".encode()


async def _sse_stream(
    service: HttpRunService,
    record: _RunRecord,
    last_event_id: int | None = None,
    *,
    queue: asyncio.Queue[RunEventPayload | None] | None = None,
    heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
) -> AsyncIterator[bytes]:
    """SSE 响应体：只读订阅运行事件；``None`` 转成心跳注释帧；断线即回收订阅者（生成器 finally）。"""
    async for payload in service.stream_events(record, last_event_id, queue=queue, heartbeat_seconds=heartbeat_seconds):
        yield SSE_HEARTBEAT_FRAME if payload is None else format_sse(payload)


async def _replay_stream(payloads: list[RunEventPayload]) -> AsyncIterator[bytes]:
    """历史上的一次性回放流（A35）：按序吐完即结束，不发心跳、不跟随（读侧只读）。"""
    for payload in payloads:
        yield format_sse(payload)


def _parse_last_event_id(request: Any) -> int | None:
    """解析 ``Last-Event-ID`` 请求头（SSE 规范里是字符串）。

    非数字 / 负数 / 空值一律当作「没有游标」（不报错）：游标只是客户端自述的进度，格式可疑时
    按「从头读」处理并由 ``needs_resync`` 决定是否需要重新同步，**不**把畸形头变成 400——
    否则一个坏游标会让客户端再也订阅不上。

    判据必须是「ASCII 十进制 + 位数有界」，不能只用 ``str.isdigit()``：它对 Unicode 数字
    （``'²'`` 这类 latin-1 单字节就能塞进请求头的字符）为真，而 ``int()`` 会抛 ``ValueError``
    → 客户端可控的 500；超长数字串还会撞 CPython 3.11+ 的 ``int()`` 位数上限，同样 500。
    """
    raw = getattr(request, "headers", None)
    if raw is None:
        return None
    value = raw.get("last-event-id")
    if value is None:
        return None
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or len(text) > _MAX_EVENT_ID_DIGITS:
        return None
    return int(text)
