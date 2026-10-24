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
    assert WS_MAX_INBOUND_CHARS == 4096
    assert WS_MAX_FRAME_BYTES == 64 * 1024
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

    # 字符上限不是 UTF-8 字节上限：恰好上限长度的多字节 JSON 仍进入 JSON 校验。
    text = json.dumps({"command": "ping", "x": "你" * (WS_MAX_INBOUND_CHARS - 30)}, ensure_ascii=False)
    assert len(text) <= WS_MAX_INBOUND_CHARS
    with pytest.raises(WsFrameError) as boundary_error:
        parse_command_frame(text)
    assert boundary_error.value.kind is WsFrameErrorKind.MALFORMED


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
