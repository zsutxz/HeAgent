"""WS 命令循环与提交分支（Epic 74 自 ``ws_server`` 拆出）。

本模块只负责「收一帧命令 → 回 ack / 错误帧」这一簇：单 run 端点的 cancel / cancel_run / ping
与只读口径、集合级端点的提交与按 id 取消。连接骨架（会话前导、订阅、推送、CLI 旁路、通知流）
留在 ``ws_server``；依赖方向单向 ``ws_server → ws_commands → ws_protocol``，本模块不得反向导入
``ws_server``，也不导入 ``http_server``（共享契约住 ``http_protocol``）。
"""

from __future__ import annotations

from pydantic import ValidationError

from heagent.network.http_protocol import HttpErrorCode, HttpRunConflictError, RunRequest, error_envelope
from heagent.network.ws_protocol import (
    WS_CLOSE_POLICY,
    WS_CLOSE_TOO_LARGE,
    ProjectChannelService,
    RunWebSocketService,
    SubmittedRun,
    WebSocketLike,
    WsAckFrame,
    WsCliAckFrame,
    WsCommand,
    WsCommandFrame,
    WsErrorFrame,
    WsFrameError,
    WsFrameErrorKind,
    parse_command_frame,
)


async def _send_error_frame(websocket: WebSocketLike, code: HttpErrorCode, message: str) -> None:
    """只发一条错误帧、**不关闭**连接（客户端可以继续发命令后重试）。"""
    envelope = error_envelope(code, message)
    await websocket.send_text(WsErrorFrame(error=envelope).model_dump_json())


async def _send_error(websocket: WebSocketLike, code: HttpErrorCode, message: str, *, close_code: int) -> None:
    await _send_error_frame(websocket, code, message)
    await websocket.close(code=close_code)


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
    """处理单 run 连接上的 cancel / cancel_run / ping 三条命令（run / projects 一律拒绝）；断线异常由调用方收敛为连接结束。

    ``projects`` 与 ``run`` 同属集合级能力，在这条连接上一律 ``invalid_request`` 且**不断连**。

    ``readonly``（只读旁观 listener）只禁**控制面**命令：``cancel`` / ``cancel_run`` 回
    ``invalid_request`` 且**不断连**（订阅者继续收事件），``ping`` 照常。用「不支持」而不是
    「静默忽略」——客户端必须知道它连的是观众席。

    ``cancel_run`` 与 ``cancel`` **同源**（同一个 ``service.cancel_run(run_id)`` 端口），差别只在
    目标从哪儿来：``cancel`` 恒指本连接绑定的 run，``cancel_run`` 的目标写在帧里，所以先与绑定
    run 比对——不等即 ``invalid_request``（一条连接只能控制它订阅的那条运行），同样**不断连**。
    目标已终止不算错误：``cancel_run`` 幂等返回当时的记录，ack 带的是端口**当时**返回的状态
    ——已终止即终态，仍在跑即 ``running``（取消是协作式的，不保证立即生效）。
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

        if command is WsCommand.PROJECTS:
            # 项目列表同属集合级能力：单 run 连接不持有项目视角，回错误帧但**不断连**。
            await _send_error_frame(
                websocket,
                HttpErrorCode.INVALID_REQUEST,
                "the projects command is only accepted on the run collection endpoint",
            )
            continue

        if command is WsCommand.CANCEL_RUN:
            if readonly:
                await _send_error_frame(
                    websocket,
                    HttpErrorCode.INVALID_REQUEST,
                    "this listener is read-only; cancel_run is not available",
                )
                continue
            if frame.run_id != run_id:
                await _send_error_frame(
                    websocket,
                    HttpErrorCode.INVALID_REQUEST,
                    "cancel_run may only target the run bound to this connection",
                )
                continue
            current = await service.cancel_run(run_id)
        elif command is WsCommand.CANCEL:
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


def _is_blank_prompt(error: ValidationError) -> bool:
    """``RunRequest`` 的「非空」校验失败 ⇒ ``empty_prompt``（与 HTTP 400 的分类口径一致）。"""
    return any("blank" in str(item.get("msg", "")) for item in error.errors())


async def _start_project_run(
    websocket: WebSocketLike,
    project_service: ProjectChannelService | None,
    project_id: str,
    prompt: str,
    request_id: str | None = None,
) -> SubmittedRun | None:
    """带 ``project_id`` 的提交分支（未装配护栏**唯一**一处）：先 ``ensure_available`` 后提交。

    ``project_service`` 为 ``None`` 时回 ``project_channel_unavailable`` 并返回 ``None``——静默按
    启动工作区执行会把「装配漏了」变成「跑错项目」；用独立码而不是 ``invalid_request``，客户端才能
    把「环境没装好、重试无用」与「我的帧写错了」分开处置（Epic 77 D2）。前置校验不占名额，其返回值
    才是后续用的 ``project_id``。

    ``request_id`` 原样透传给端口（Epic 77 D1）：幂等表住实现方，传输层不认识也不缓存提交结果。
    它只在**项目径**（``project_id`` 非空）被传下去——启动工作区径没有幂等窗口，该键在此被忽略。
    """
    if project_service is None:
        await _send_error_frame(
            websocket,
            HttpErrorCode.PROJECT_CHANNEL_UNAVAILABLE,
            "project addressing is not available on this listener",
        )
        return None
    resolved = await project_service.ensure_available(project_id)
    return await project_service.start_project_run(resolved, prompt, request_id)


async def _send_projects_frame(
    websocket: WebSocketLike,
    project_service: ProjectChannelService | None,
) -> None:
    """``projects`` 命令：把已投影的项目列表帧原样发给客户端。

    ``project_service`` 为 ``None`` 时回 ``project_channel_unavailable`` 且**不断连**——与带
    ``project_id`` 的提交同一个护栏口径：不静默回一张空表（客户端会把「没装配」误读成「一个项目都
    没有」），也不复用 ``invalid_request``（那是「你的帧写错了」的码，Epic 77 D2）。
    端口抛 ``HttpRunConflictError`` 时代码逐字透传；其余异常不在此兜，由连接骨架收敛为
    ``server_error`` + 断连（漏译必须显性，与提交分支同档）。
    """
    if project_service is None:
        await _send_error_frame(
            websocket,
            HttpErrorCode.PROJECT_CHANNEL_UNAVAILABLE,
            "project addressing is not available on this listener",
        )
        return
    try:
        frame = await project_service.list_projects()
    except HttpRunConflictError as exc:
        await _send_error_frame(websocket, exc.code, str(exc))
        return
    await websocket.send_text(frame.model_dump_json())


async def _submit_run(
    websocket: WebSocketLike,
    service: RunWebSocketService,
    prompt: str,
    *,
    project_id: str | None = None,
    project_service: ProjectChannelService | None = None,
    request_id: str | None = None,
) -> None:
    """提交一次运行：校验复用 ``RunRequest``，创建复用 ``HttpRunService.start_run``。

    错误一律走错误帧且**不断连**（客户端可继续提交）：输入类 ``empty_prompt`` / ``invalid_request``、
    名额类 ``run_conflict`` / ``total_inflight_limit`` / 关停 ``shutting_down``——与
    ``POST /api/runs`` 的状态码语义一一对应，只是换了传输层。项目径另有 ``timeout``（适配器上界，
    见 ``cli/ws_project_adapter``）与项目侧具名码，两者都由端口抛 ``HttpRunConflictError`` 逐字透传。
    ``project_id`` 缺省时创建路径逐字不变；带值时改走 :func:`_start_project_run`（项目端口），
    ``RunRequest`` 校验两条路径共用。
    """
    try:
        request = RunRequest.model_validate({"prompt": prompt})
    except ValidationError as exc:
        code = HttpErrorCode.EMPTY_PROMPT if _is_blank_prompt(exc) else HttpErrorCode.INVALID_REQUEST
        await _send_error_frame(websocket, code, "prompt is invalid")
        return
    try:
        if project_id is None:
            record = await service.start_run(request.prompt)
        else:
            record = await _start_project_run(websocket, project_service, project_id, request.prompt, request_id)
    except HttpRunConflictError as exc:
        await _send_error_frame(websocket, exc.code, str(exc))
        return
    if record is None:
        return
    await websocket.send_text(
        WsAckFrame(command=WsCommand.RUN, run_id=record.run_id, status=record.status).model_dump_json()
    )


async def _handle_submit_commands(
    websocket: WebSocketLike,
    service: RunWebSocketService,
    project_service: ProjectChannelService | None = None,
) -> None:
    """集合级连接的命令循环：``run``（提交）、``cancel_run``（按 id 取消）、``projects`` 与 ``ping``。

    这条连接**不绑定任何 run**（D2 的期一形状：提交连接不转事件流）。客户端拿到 ack 里的
    ``run_id`` 后经既有 ``/api/runs/{run_id}/ws`` 订阅——单 run 端点形状因此保持不变。

    ``cancel`` 在这一侧仍是「显式不支持」（没有绑定就没有默认目标）；``cancel_run`` 才是无绑定
    连接的取消形态：目标写在帧里，取消走与单 run 端点**同一个** ``service.cancel_run`` 端口。
    未知 id 回 ``unknown_run`` 错误帧、已终止的目标拿终态 ack（幂等）——两者都**不断连**，错的
    是这一帧的 id 而不是这条连接。

    ``project_service`` 是项目端口的注入点：提交侧原样转发给 :func:`_submit_run`（「未装配却带
    ``project_id``」的护栏住在 :func:`_start_project_run`，单处），``projects`` 侧交给
    :func:`_send_projects_frame`。本循环只做分派，不重复判装配态。
    """
    while True:
        frame = await _next_command(websocket)
        if frame is None:
            return

        if frame.command is WsCommand.RUN:
            await _submit_run(
                websocket,
                service,
                frame.prompt or "",
                project_id=frame.project_id,
                project_service=project_service,
                request_id=frame.request_id,
            )
            continue
        if frame.command is WsCommand.PROJECTS:
            await _send_projects_frame(websocket, project_service)
            continue
        if frame.command is WsCommand.CANCEL_RUN:
            # 必带字段已在解析期校验过；``or ""`` 只是让类型收窄，空 id 必然落到 ``unknown_run``。
            target = frame.run_id or ""
            record = await service.cancel_run(target)
            if record is None:
                await _send_error_frame(websocket, HttpErrorCode.UNKNOWN_RUN, "no such run")
                continue
            await websocket.send_text(
                WsAckFrame(command=WsCommand.CANCEL_RUN, run_id=target, status=record.status).model_dump_json()
            )
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
