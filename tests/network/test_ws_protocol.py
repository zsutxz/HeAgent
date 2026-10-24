"""Epic 54 Story 54-1：WebSocket 帧协议契约判据。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from heagent.network.http_protocol import (
    HttpErrorCode,
    RunEventKind,
    RunEventPayload,
    RunStatus,
    SSE_HEARTBEAT_SECONDS,
    error_envelope,
)
from heagent.network.ws_protocol import (
    WS_CLOSE_GOING_AWAY,
    WS_CLOSE_INTERNAL,
    WS_CLOSE_POLICY,
    WS_CLOSE_TOO_LARGE,
    WS_MAX_COMMAND_CHARS,
    WS_MAX_FRAME_BYTES,
    WS_MAX_INBOUND_CHARS,
    WS_PING_INTERVAL_SECONDS,
    WS_PING_TIMEOUT_SECONDS,
    WsAckFrame,
    WsCommand,
    WsCommandFrame,
    WsErrorFrame,
    WsEventFrame,
    WsFrameError,
    WsFrameErrorKind,
    WsFrameType,
    parse_command_frame,
)


def test_event_frame_round_trip_preserves_nested_sse_payload() -> None:
    event = RunEventPayload(kind=RunEventKind.TEXT, seq=1, text="hello")
    frame = WsEventFrame(event=event)

    dumped = frame.model_dump(mode="json")

    assert dumped == {
        "type": "event",
        "event": {
            "kind": "text",
            "seq": 1,
            "text": "hello",
            "tool_name": "",
            "tool_target": "",
            "tool_output": "",
            "tool_error": False,
            "message": "",
            "model": None,
            "usage": None,
        },
    }
    assert WsEventFrame.model_validate(dumped) == frame


def test_ack_frame_round_trip_has_closed_shape() -> None:
    frame = WsAckFrame(command=WsCommand.CANCEL, run_id="run-1", status=RunStatus.CANCELLED)
    dumped = frame.model_dump(mode="json")

    assert dumped == {
        "type": "ack",
        "command": "cancel",
        "run_id": "run-1",
        "status": "cancelled",
    }
    assert WsAckFrame.model_validate(dumped) == frame


def test_error_frame_round_trip_reuses_http_error_envelope() -> None:
    for code in HttpErrorCode:
        frame = WsErrorFrame(error=error_envelope(code, "request failed"))
        dumped = frame.model_dump(mode="json")
        assert dumped["type"] == "error"
        assert dumped["error"]["error"]["code"] == code.value
        assert WsErrorFrame.model_validate(dumped) == frame


def test_command_frame_round_trip_and_closed_models_reject_extra_fields() -> None:
    frame = WsCommandFrame(command=WsCommand.PING)
    assert WsCommandFrame.model_validate(frame.model_dump(mode="json")) == frame

    event = RunEventPayload(kind=RunEventKind.TEXT, seq=1)
    with pytest.raises(ValidationError):
        WsEventFrame(event=event, text="flattened")
    with pytest.raises(ValidationError):
        RunEventPayload(kind=RunEventKind.TEXT, seq=1, type="event")
    with pytest.raises(ValidationError):
        WsCommandFrame(command=WsCommand.PING, run_id="run-1")
    with pytest.raises(ValidationError):
        WsErrorFrame.model_validate({"type": "error", "code": "custom", "error": {}})


def test_unknown_frame_types_and_commands_are_rejected() -> None:
    with pytest.raises(ValidationError):
        WsAckFrame.model_validate({"type": "unknown", "command": "ping", "run_id": "run-1", "status": "running"})
    with pytest.raises(ValidationError):
        WsCommandFrame.model_validate({"command": "subscribe"})


def test_protocol_limits_and_close_codes_match_contract() -> None:
    """三条上限口径（Epic 56 Story 56-3 起）：run 帧要装得下协议允许的最大 prompt。"""
    from heagent.network.http_protocol import (
        JSON_ENVELOPE_ALLOWANCE_BYTES,
        MAX_PROMPT_CHARS,
        MAX_REQUEST_BYTES_FOR_MAX_PROMPT,
    )

    # 字符上限按**最坏 JSON 转义**推算（ensure_ascii=True 时 1 个 CJK 字符 → 6 个 ASCII 字符）：
    # 按原始字符数（32 K）定会把合法的最大 prompt 挡在协议层之外（实现期实测 1009）。
    assert WS_MAX_INBOUND_CHARS == 6 * MAX_PROMPT_CHARS + JSON_ENVELOPE_ALLOWANCE_BYTES
    assert WS_MAX_COMMAND_CHARS == 4096
    assert WS_MAX_FRAME_BYTES == MAX_REQUEST_BYTES_FOR_MAX_PROMPT
    assert WS_MAX_FRAME_BYTES >= 4 * MAX_PROMPT_CHARS  # 最坏 UTF-8（4 字节/字符）也装得下
    assert WS_MAX_COMMAND_CHARS < WS_MAX_INBOUND_CHARS <= WS_MAX_FRAME_BYTES
    assert WS_PING_INTERVAL_SECONDS == SSE_HEARTBEAT_SECONDS == 15.0
    assert WS_PING_TIMEOUT_SECONDS == 20.0
    assert (WS_CLOSE_POLICY, WS_CLOSE_TOO_LARGE, WS_CLOSE_INTERNAL, WS_CLOSE_GOING_AWAY) == (
        1008,
        1009,
        1011,
        1001,
    )


def test_parse_command_frame_accepts_cancel_and_ping() -> None:
    assert parse_command_frame('{"command":"cancel"}').command is WsCommand.CANCEL
    assert parse_command_frame('{"command":"ping"}').command is WsCommand.PING


def test_parse_command_frame_accepts_run_with_prompt() -> None:
    frame = parse_command_frame('{"command":"run","prompt":"写一个快速排序"}')
    assert frame.command is WsCommand.RUN
    assert frame.prompt == "写一个快速排序"
    # 最大长度 prompt 必须能通过（HTTP 侧同一条字符上限）。
    from heagent.network.http_protocol import MAX_PROMPT_CHARS

    biggest = json.dumps({"command": "run", "prompt": "中" * MAX_PROMPT_CHARS}, ensure_ascii=False)
    assert parse_command_frame(biggest).command is WsCommand.RUN


@pytest.mark.parametrize(
    "text",
    [
        '{"command":"run"}',  # run 必须带 prompt
        '{"command":"run","prompt":null}',
        '{"command":"run","prompt":"hi","extra":1}',
        '{"command":"ping","prompt":"hi"}',  # prompt 只对 run 有效
        '{"command":"cancel","prompt":""}',
    ],
)
def test_run_and_prompt_are_mutually_bound(text: str) -> None:
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(text)
    assert exc_info.value.kind is WsFrameErrorKind.MALFORMED


def test_non_run_frames_keep_the_small_character_limit() -> None:
    """命令面刻意保持最小：ping 不能借 prompt 那一档上限灌进 30 KiB。"""
    padded = json.dumps({"command": "ping", "pad": "x" * WS_MAX_COMMAND_CHARS})
    assert len(padded) > WS_MAX_COMMAND_CHARS
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(padded)
    assert exc_info.value.kind is WsFrameErrorKind.TOO_LARGE


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("{", WsFrameErrorKind.MALFORMED),
        ('{"command":"subscribe"}', WsFrameErrorKind.UNKNOWN_COMMAND),
        ('{"command":"ping","extra":true}', WsFrameErrorKind.MALFORMED),
    ],
)
def test_parse_command_frame_classifies_invalid_inputs(text: str, kind: WsFrameErrorKind) -> None:
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(text)
    assert exc_info.value.kind is kind


def test_parse_command_frame_checks_character_limit_before_json() -> None:
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame("{" * (WS_MAX_INBOUND_CHARS + 1))
    assert exc_info.value.kind is WsFrameErrorKind.TOO_LARGE

    # 字符上限不是 UTF-8 字节上限：字符数在上限内的多字节帧仍进入结构校验。
    # （`run` 帧不受 WS_MAX_COMMAND_CHARS 约束——那一档只挡 cancel / ping。）
    text = json.dumps({"command": "run", "prompt": "你" * (WS_MAX_INBOUND_CHARS - 60)}, ensure_ascii=False)
    assert WS_MAX_COMMAND_CHARS < len(text) <= WS_MAX_INBOUND_CHARS
    assert len(text.encode()) > WS_MAX_INBOUND_CHARS  # 字节数远超字符上限：两个口径确实不同
    assert parse_command_frame(text).command is WsCommand.RUN


def test_ws_protocol_runtime_imports_stay_within_network_leaf_dependencies() -> None:
    source = Path("src/heagent/network/ws_protocol.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name.split(".", 1)[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    )

    assert imported_modules <= {
        "__future__",
        "json",
        "enum",
        "pydantic",
        "heagent.network.http_protocol",
    }


def test_ws_protocol_does_not_define_duplicate_error_messages() -> None:
    source = Path("src/heagent/network/ws_protocol.py").read_text(encoding="utf-8")
    assert '"invalid_request"' not in source
    assert '"unknown_run"' not in source
    assert '"resync_required"' not in source
    assert "error_envelope" in source
