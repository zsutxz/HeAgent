import json

import pytest

from heagent.network.protocol import (
    ProtocolError,
    TcpError,
    TcpErrorCode,
    TcpRequest,
    TcpResponse,
    TcpUsage,
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


def test_success_response_carries_optional_usage_metadata() -> None:
    """Story 48-3：handler 可把 loop 采集到的用量作为可选字段回传（不下发时字段省略）。"""
    usage = TcpUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    payload = encode_response(success_response("r1", "ok", model="stub", usage=usage))

    decoded = json.loads(payload)
    assert decoded == {
        "id": "r1",
        "ok": True,
        "result": "ok",
        "model": "stub",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    assert json.loads(encode_response(success_response("r1", "ok"))) == {"id": "r1", "ok": True, "result": "ok"}


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


# --- Story 48-5: id 是客户端可控且会被写进日志 → 必须有界、无控制字符 ---


def test_request_id_is_length_bounded() -> None:
    """超长 id 可把服务端日志放大约 3 倍请求体（id 在 3 个日志点出现）。"""
    too_long = "x" * 129
    with pytest.raises(ProtocolError) as excinfo:
        decode_request(json.dumps({"id": too_long, "prompt": "hi"}).encode() + b"\n")

    assert excinfo.value.code is TcpErrorCode.INVALID_REQUEST
    # 边界值仍然接受（128 字符足够表达 UUID / 序号组合）
    assert decode_request(json.dumps({"id": "x" * 128, "prompt": "hi"}).encode() + b"\n").id == "x" * 128


@pytest.mark.parametrize("bad_id", ["a\nb", "a\rb", "a\x00b", "a\x7fb", "a\x85b", "a\tb"])
def test_request_id_rejects_control_characters(bad_id: str) -> None:
    """换行可让客户端在日志里**伪造一条完整记录**（48-5 评审 W-4 实测复现）。"""
    with pytest.raises(ProtocolError) as excinfo:
        decode_request(json.dumps({"id": bad_id, "prompt": "hi"}).encode() + b"\n")

    assert excinfo.value.code is TcpErrorCode.INVALID_REQUEST


# --- Story 48-6: 黄金字段集与黄金报文（防漂移；改这里必须先同步 README / frame 4.16） ---

_GOLDEN_SUCCESS_FIELDS = frozenset({"id", "ok", "result"})
_GOLDEN_SUCCESS_FULL_FIELDS = frozenset({"id", "ok", "result", "model", "usage"})
_GOLDEN_ERROR_FIELDS = frozenset({"id", "ok", "error"})


def test_golden_response_field_sets_are_frozen() -> None:
    """顶层字段集是**对外契约**：加字段 / 改名 / 去字段都先让这条红，再改文档与客户端。"""
    usage = TcpUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    assert set(success_response("r1", "ok").model_dump(exclude_none=True)) == _GOLDEN_SUCCESS_FIELDS
    assert (
        set(success_response("r1", "ok", model="stub", usage=usage).model_dump(exclude_none=True))
        == _GOLDEN_SUCCESS_FULL_FIELDS
    )
    assert set(error_response("r1", TcpErrorCode.AGENT_ERROR, "failed").model_dump(exclude_none=True)) == (
        _GOLDEN_ERROR_FIELDS
    )
    assert set(TcpRequest(id="r1", prompt="hi").model_dump()) == {"id", "prompt"}
    assert set(TcpError(code=TcpErrorCode.TIMEOUT, message="late").model_dump()) == {"code", "message"}
    assert set(usage.model_dump()) == {"prompt_tokens", "completion_tokens", "total_tokens"}


def test_golden_wire_lines_are_byte_stable() -> None:
    """逐字节黄金报文：字段顺序 / 省略规则（``exclude_none``）/ 转义一变就红。

    客户端按行解析，字段静默改名或换序会让它们失配却不报错——这里把线上字节钉死。
    """
    assert encode_response(success_response("r1", "ok")) == b'{"id":"r1","ok":true,"result":"ok"}\n'

    assert (
        encode_response(error_response("r1", TcpErrorCode.RATE_LIMITED, "server is at its limit"))
        == b'{"id":"r1","ok":false,"error":{"code":"rate_limited","message":"server is at its limit"}}\n'
    )

    # 非 ASCII 保真（ensure_ascii=False）+ 内嵌换行按 JSON 规则转义 + 可选字段按声明顺序
    expected = (
        '{"id":"r1","ok":true,"result":"第一行\\n第二行","model":"stub",'
        '"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n'
    ).encode()
    assert (
        encode_response(
            success_response(
                "r1",
                "第一行\n第二行",
                model="stub",
                usage=TcpUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            )
        )
        == expected
    )
