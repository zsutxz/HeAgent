import json

import pytest

from heagent.network.protocol import (
    ProtocolError,
    TcpErrorCode,
    TcpRequest,
    TcpResponse,
    decode_request,
    encode_response,
    error_response,
    success_response,
)


def test_decode_request_accepts_utf8_jsonl_and_preserves_whitespace() -> None:
    request = decode_request('{"id":"r1","prompt":"  你好\\nworld  "}\n'.encode())

    assert request == TcpRequest(id="r1", prompt="  你好\nworld  ")


@pytest.mark.parametrize("suffix", [b"\n", b"\r\n"])
def test_decode_request_accepts_line_terminators(suffix: bytes) -> None:
    assert decode_request(b'{"id":"r1","prompt":"hello"}' + suffix).id == "r1"


def test_decode_request_is_independent_of_tcp_fragmentation() -> None:
    fragments = [b'{"id":"r1",', b'"prompt":"hello"}', b"\n"]

    assert decode_request(b"".join(fragments)).prompt == "hello"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"not-json\n", TcpErrorCode.INVALID_JSON),
        (b"[]\n", TcpErrorCode.INVALID_REQUEST),
        (b'{"id":"r1","prompt":"   "}\n', TcpErrorCode.EMPTY_PROMPT),
        (b'{"id":"r1","prompt":"hello","system":"unsafe"}\n', TcpErrorCode.INVALID_REQUEST),
        (b'{"id":"r1","prompt":"hello"}', TcpErrorCode.INVALID_REQUEST),
        (b'{"id":"r1","prompt":"hello"}\n\n', TcpErrorCode.INVALID_REQUEST),
    ],
)
def test_decode_request_rejects_invalid_payloads(raw: bytes, code: TcpErrorCode) -> None:
    with pytest.raises(ProtocolError) as raised:
        decode_request(raw)

    assert raised.value.code == code
    assert "traceback" not in raised.value.message.casefold()


def test_decode_request_rejects_invalid_utf8() -> None:
    with pytest.raises(ProtocolError) as raised:
        decode_request(b'{"id":"r1","prompt":"\xff"}\n')

    assert raised.value.code == TcpErrorCode.INVALID_JSON


def test_decode_request_rejects_oversized_payload_before_parsing() -> None:
    with pytest.raises(ProtocolError) as raised:
        decode_request(b"{" + b"x" * 20, max_bytes=10)

    assert raised.value.code == TcpErrorCode.REQUEST_TOO_LARGE


def test_decode_request_rejects_invalid_max_bytes() -> None:
    with pytest.raises(ValueError, match="positive"):
        decode_request(b"{}\n", max_bytes=0)


def test_encode_success_response_is_one_utf8_json_line() -> None:
    payload = encode_response(success_response("r1", "第一行\n第二行"))

    assert payload.endswith(b"\n")
    assert payload.count(b"\n") == 1
    decoded = json.loads(payload)
    assert decoded == {"id": "r1", "ok": True, "result": "第一行\n第二行"}


def test_success_and_error_response_invariants() -> None:
    success = success_response("r1", "ok", model="stub")
    failure = error_response("r1", TcpErrorCode.AGENT_ERROR, "agent failed")

    assert success.ok is True
    assert success.error is None
    assert failure.ok is False
    assert failure.result is None
    assert failure.error is not None
    assert failure.error.code == TcpErrorCode.AGENT_ERROR

    with pytest.raises(ValueError):
        TcpResponse(id="r1", ok=True, error=failure.error)
    with pytest.raises(ValueError):
        TcpResponse(id="r1", ok=False, result="must be absent")
