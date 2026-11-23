"""74.1 · 命令帧字段白名单单一映射表与可选 ``project_id``。

钉住四件事：① ``_FRAME_FIELDS`` 覆盖 ``WsCommand`` 全部成员（新增命令不登记即红）；
② ``run`` 帧的 ``project_id`` 可带、原样不 strip、空串判 ``malformed``；
③ 未登记键仍判 ``malformed``（白名单语义没被放宽）；
④ 未装配项目通道（``project_service=None``）时带 ``project_id`` 的提交回
``invalid_request`` 且**不**触达 ``service.start_run``——静默按启动工作区执行是禁止的。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from heagent.network.http_protocol import HttpErrorCode
from heagent.network.ws_protocol import (
    WsCommand,
    WsCommandFrame,
    WsFrameError,
    WsFrameErrorKind,
    _FRAME_FIELDS,
    parse_command_frame,
)
from heagent.network.ws_server import build_runs_collection_endpoint

_ORIGIN_OK = lambda _scope: None  # noqa: E731 - OriginCheck 替身，同步口径


class WebSocketDisconnect(Exception):
    """与 Starlette 同名：``_next_command`` 按类型名判「对端断开」。"""


class _QueueWebSocket:
    """按队列返回入站帧的 ``WebSocketLike`` 替身，队列空后抛断开。"""

    def __init__(self, frames: list[str]) -> None:
        self.scope: dict[str, Any] = {}
        self.path_params: dict[str, Any] = {}
        self.query_params: dict[str, Any] = {}
        self._frames = list(frames)
        self.sent: list[str] = []
        self.accepted = False
        self.closed_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    async def receive_text(self) -> str:
        if not self._frames:
            raise WebSocketDisconnect()
        return self._frames.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


class _NeverCalledRunService:
    """``RunWebSocketService`` 替身：任何提交都算违约（74.1 的 ``None`` 护栏不该走到这里）。"""

    _closing = False

    def __init__(self) -> None:
        self.start_run_calls = 0

    async def start_run(self, prompt: str) -> Any:  # pragma: no cover - 只做计数断言
        self.start_run_calls += 1
        raise AssertionError("start_run must not be reached when project addressing is unavailable")

    def register_ws(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None

    def unregister_ws(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None

    def run(self, run_id: str) -> None:  # pragma: no cover
        return None


def test_frame_fields_cover_every_command() -> None:
    """白名单表必须覆盖 ``WsCommand`` 全部成员：新增命令不登记即在这里红。"""
    assert set(_FRAME_FIELDS) == set(WsCommand)


def test_run_frame_carries_project_id_verbatim() -> None:
    """``project_id`` 原样保留（不做 strip）：前后空格也是客户端传什么就该是什么。"""
    frame = parse_command_frame(json.dumps({"command": "run", "prompt": "hi", "project_id": " p1234abcd "}))

    assert isinstance(frame, WsCommandFrame)
    assert frame.command is WsCommand.RUN
    assert frame.project_id == " p1234abcd "


def test_blank_project_id_is_malformed() -> None:
    """空串不满足 ``min_length=1`` ⇒ 与「字段拼错」同档的 ``malformed``。"""
    with pytest.raises(WsFrameError) as excinfo:
        parse_command_frame(json.dumps({"command": "run", "prompt": "hi", "project_id": ""}))

    assert excinfo.value.kind is WsFrameErrorKind.MALFORMED


def test_unknown_field_is_still_malformed() -> None:
    """白名单收紧没有放松：不在表里的键仍判 ``malformed``。"""
    with pytest.raises(WsFrameError) as excinfo:
        parse_command_frame(json.dumps({"command": "run", "prompt": "hi", "project": "p1"}))

    assert excinfo.value.kind is WsFrameErrorKind.MALFORMED


@pytest.mark.asyncio
async def test_project_id_without_project_service_is_rejected_without_starting_run() -> None:
    """未装配项目通道：带 ``project_id`` 的提交回 ``invalid_request`` 且一次都不触达 ``start_run``。"""
    service = _NeverCalledRunService()
    endpoint = build_runs_collection_endpoint(
        service,
        origin_violation=_ORIGIN_OK,
        max_connections=4,
        version="v74-test",
    )
    ws = _QueueWebSocket([json.dumps({"command": "run", "prompt": "hi", "project_id": "p1234abcd"})])

    await endpoint(ws)

    types = [json.loads(frame)["type"] for frame in ws.sent]
    assert types == ["hello", "error"]
    assert json.loads(ws.sent[1])["error"]["error"]["code"] == HttpErrorCode.INVALID_REQUEST.value
    assert service.start_run_calls == 0
