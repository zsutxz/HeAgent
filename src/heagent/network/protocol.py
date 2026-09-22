"""TCP protocol models and bounded JSON Lines codecs."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class TcpErrorCode(StrEnum):
    """Stable error codes exposed by the TCP protocol."""

    INVALID_JSON = "invalid_json"
    INVALID_REQUEST = "invalid_request"
    EMPTY_PROMPT = "empty_prompt"
    REQUEST_TOO_LARGE = "request_too_large"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    AGENT_ERROR = "agent_error"
    SERVER_ERROR = "server_error"


class ProtocolError(ValueError):
    """A client-facing protocol error with a stable error code."""

    def __init__(self, code: TcpErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TcpRequest(BaseModel):
    """The first-version stateless TCP request."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("id must not be blank")
        return value

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


class TcpError(BaseModel):
    """A sanitized client-facing error."""

    model_config = ConfigDict(extra="forbid")

    code: TcpErrorCode
    message: str = Field(min_length=1)


class TcpUsage(BaseModel):
    """Optional usage metadata returned by a TCP request."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class TcpResponse(BaseModel):
    """A single final TCP response."""

    model_config = ConfigDict(extra="forbid")

    id: str
    ok: bool
    result: str | None = None
    error: TcpError | None = None
    model: str | None = None
    usage: TcpUsage | None = None

    @model_validator(mode="after")
    def _validate_success_or_error(self) -> TcpResponse:
        if self.ok and (self.result is None or self.error is not None):
            raise ValueError("successful response requires result and forbids error")
        if not self.ok and (self.error is None or self.result is not None):
            raise ValueError("error response requires error and forbids result")
        return self


def _decode_json(raw: bytes) -> object:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(TcpErrorCode.INVALID_JSON, "request must be valid UTF-8 JSON") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(TcpErrorCode.INVALID_JSON, "request must be valid JSON") from exc


def decode_request(raw: bytes, *, max_bytes: int = 1_048_576) -> TcpRequest:
    """Decode one complete JSON Lines payload without accepting an oversized message."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    if len(raw) > max_bytes:
        raise ProtocolError(TcpErrorCode.REQUEST_TOO_LARGE, "request exceeds maximum size")
    if not raw.endswith(b"\n"):
        raise ProtocolError(TcpErrorCode.INVALID_REQUEST, "request must end with LF")
    payload = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1]
    if b"\n" in payload or b"\r" in payload:
        raise ProtocolError(TcpErrorCode.INVALID_REQUEST, "request must contain one JSON line")
    if not payload:
        raise ProtocolError(TcpErrorCode.INVALID_REQUEST, "request must not be empty")
    value = _decode_json(payload)
    if not isinstance(value, dict):
        raise ProtocolError(TcpErrorCode.INVALID_REQUEST, "request must be a JSON object")

    try:
        return TcpRequest.model_validate(value)
    except ValidationError as exc:
        messages = [str(error.get("msg", "invalid request")) for error in exc.errors()]
        if any("prompt" in message and "blank" in message for message in messages):
            code = TcpErrorCode.EMPTY_PROMPT
        else:
            code = TcpErrorCode.INVALID_REQUEST
        raise ProtocolError(code, "request fields are invalid") from exc


def encode_response(response: TcpResponse) -> bytes:
    """Serialize one response as UTF-8 JSON Lines with a single LF terminator."""
    return response.model_dump_json(exclude_none=True, ensure_ascii=False).encode("utf-8") + b"\n"


def success_response(
    request_id: str,
    result: str,
    *,
    model: str | None = None,
    usage: TcpUsage | None = None,
) -> TcpResponse:
    """Build a successful response; ``model`` / ``usage`` are optional metadata."""
    return TcpResponse(id=request_id, ok=True, result=result, model=model, usage=usage)


def error_response(
    request_id: str,
    code: TcpErrorCode,
    message: str,
) -> TcpResponse:
    """Build a sanitized error response."""
    return TcpResponse(id=request_id, ok=False, error=TcpError(code=code, message=message))


def response_from_protocol_error(request_id: str, error: ProtocolError) -> TcpResponse:
    """Convert a protocol exception into a stable response."""
    return error_response(request_id, error.code, error.message)


__all__ = [
    "ProtocolError",
    "TcpError",
    "TcpErrorCode",
    "TcpRequest",
    "TcpResponse",
    "TcpUsage",
    "decode_request",
    "encode_response",
    "error_response",
    "response_from_protocol_error",
    "success_response",
]
