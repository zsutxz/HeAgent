"""运行 API 端点装配：创建 / SSE 订阅 / 取消 / 会话快照（Story 62.1 自 ``network/http_server.py`` 拆出）。

四个端点闭包只消费注入的 :class:`~heagent.network.http_server.service.HttpRunService` 与管线 helper。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from heagent.network.http_protocol import (
    HttpErrorCode,
    HttpRunConflictError,
    RunRequest,
    RunStatusResponse,
)

from .pipeline import _json_error, _parse_last_event_id, _read_model, _replay_stream, _sse_stream

if TYPE_CHECKING:
    from heagent.network.http_protocol import RunEventPayload

    from .config import HttpServerConfig
    from .service import HttpRunService


RunHistorySource = Callable[[str], "list[RunEventPayload] | None"]


def _build_run_endpoints(
    responses: Any,
    config: HttpServerConfig,
    service: HttpRunService,
    history: RunHistorySource | None = None,
) -> tuple[Any, Any, Any, Any]:
    """构造运行 API 的四个端点（创建 / 事件流 / 取消 / 会话快照）。

    以**具体类型**的 ``service`` 为参数（而不是让端点闭包捕获 ``Optional`` 再在体内断言）：
    「路由只在注入 service 时注册」这条前提写在签名里比写在断言里可靠，也让
    :func:`build_http_app` 的复杂度只反映路由装配本身（C901 的判据）。
    """

    async def create_run(request: Any) -> Any:
        """``POST /api/runs``：有界非空 prompt → 创建一次运行（单运行约束，不排队）。"""
        parsed, error = await _read_model(
            request,
            model=RunRequest,
            config=config,
            responses=responses,
            blank_code=HttpErrorCode.EMPTY_PROMPT,
        )
        if error is not None:
            return error
        try:
            record = await service.start_run(parsed.prompt)
        except HttpRunConflictError as exc:
            return _json_error(responses, exc.code, str(exc), status_code=409)
        return responses.JSONResponse(
            RunStatusResponse(run_id=record.run_id, status=record.status).model_dump(mode="json"),
            status_code=201,
        )

    async def run_events(request: Any) -> Any:
        """``GET /api/runs/{run_id}/events``：SSE 订阅（只读；断线不取消运行）。"""
        run_id = str(request.path_params.get("run_id", ""))
        record = service.run(run_id)
        if record is None:
            # 进程内没有该 run（典型 = 重启后刷新页面）：有注入的历史来源就回放 rollout，
            # 否则维持 404。回放是**一次性**流（读侧只读，不重跑、不跟随），客户端拿到终态即关闭。
            replayed = history(run_id) if history is not None else None
            if replayed is None:
                return _json_error(responses, HttpErrorCode.UNKNOWN_RUN, "no such run", status_code=404)
            cursor = _parse_last_event_id(request)
            pending = [payload for payload in replayed if cursor is None or payload.seq > cursor]
            return responses.StreamingResponse(
                _replay_stream(pending),
                media_type="text/event-stream",
                headers={
                    "cache-control": "no-store",
                    "x-accel-buffering": "no",
                    "x-heagent-replay": "rollout",
                },
            )
        cursor = _parse_last_event_id(request)
        if service.needs_resync(record, cursor):
            # 游标早于缓冲窗口：**不**发一条「看起来连续」的流，明确要求重新同步。
            # 客户端应改拉 `/api/session` 快照，而不是把缺口当作没发生。
            return _json_error(
                responses,
                HttpErrorCode.RESYNC_REQUIRED,
                "event cursor is older than the buffered window; reload the session snapshot",
                status_code=409,
            )
        # 限额检查与登记**同一步**完成（同步、无 await ⇒ 事件循环里原子）：旧实现把「先查后加」
        # 拆在端点与生成器两处，并发 GET /events 能一起穿过限额。
        queue: asyncio.Queue[RunEventPayload | None] = asyncio.Queue(maxsize=record.subscriber_queue_size)
        # 上限取自**订阅面自己的旋钮**：此前复用 `max_connections`，而连接额度由 Uvicorn
        # 在进 ASGI 之前拒绝 ⇒ 这条 429 分支实际不可达、客户端只拿到裸 503。
        if not record.try_add_subscriber(queue, config.max_subscribers):
            return _json_error(
                responses,
                HttpErrorCode.RATE_LIMITED,
                "too many event subscribers for this run",
                status_code=429,
            )
        return responses.StreamingResponse(
            _sse_stream(service, record, cursor, queue=queue),
            media_type="text/event-stream",
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )

    async def cancel_run(request: Any) -> Any:
        """``DELETE /api/runs/{run_id}``：协作式取消指定运行（幂等；不触碰其它运行）。"""
        run_id = str(request.path_params.get("run_id", ""))
        record = await service.cancel_run(run_id)
        if record is None:
            return _json_error(responses, HttpErrorCode.UNKNOWN_RUN, "no such run", status_code=404)
        return responses.JSONResponse(
            RunStatusResponse(run_id=record.run_id, status=record.status).model_dump(mode="json")
        )

    async def session(request: Any) -> Any:  # noqa: ARG001
        """``GET /api/session``：进程内单用户会话的可展示快照（刷新后恢复用）。"""
        return responses.JSONResponse(service.session_snapshot().model_dump(mode="json"))

    return create_run, run_events, cancel_run, session
