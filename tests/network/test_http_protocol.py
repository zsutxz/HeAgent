"""HTTP 协议模型测试（Epic 49 Story 49-1）。

协议模型是跨模块契约（传输层、入口层、测试共用），因此这里钉住的是**形状与边界**：
错误码集合、文案净化、健康响应字段封闭性、以及「页面上限与协议上限一致」这类容易漂移的值。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from heagent.network.http_protocol import (
    GENERIC_ERROR_MESSAGE,
    HTTP_SCHEMA_VERSION,
    HTTP_SERVICE_NAME,
    MAX_ERROR_MESSAGE_CHARS,
    MAX_PROMPT_CHARS,
    HealthResponse,
    HttpErrorCode,
    HttpErrorDetail,
    HttpErrorEnvelope,
    error_envelope,
    sanitize_message,
)
from heagent.network.http_server import read_web_asset


class TestErrorCodes:
    def test_codes_are_unique_lowercase_tokens(self) -> None:
        values = [code.value for code in HttpErrorCode]

        assert len(values) == len(set(values))
        assert all(value.islower() for value in values)
        assert all(" " not in value and "/" not in value for value in values)

    def test_story_contract_codes_are_present(self) -> None:
        """错误码表（``docs/frame.md`` 4.17）覆盖本 Epic 全部故事需要的语义。"""
        expected = {
            "invalid_request",
            "empty_prompt",
            "request_too_large",
            "run_conflict",
            "unknown_run",
            "resync_required",
            "rate_limited",
            "timeout",
            "origin_forbidden",
            "not_found",
            "method_not_allowed",
            "agent_error",
            "shutting_down",
            "server_error",
        }

        assert {code.value for code in HttpErrorCode} == expected


class TestSanitizeMessage:
    def test_collapses_whitespace_and_newlines(self) -> None:
        assert sanitize_message("a\n  b\tc\r\nd") == "a b c d"

    def test_truncates_to_the_bound(self) -> None:
        sanitized = sanitize_message("x" * (MAX_ERROR_MESSAGE_CHARS + 50))

        # 返回长度**不超过**上限本身（截断到上限-1 再补省略号）：模型字段 max_length 与净化
        # 同界，否则净化后的文案反而通不过自己的校验。
        assert len(sanitized) == MAX_ERROR_MESSAGE_CHARS
        assert sanitized.endswith("…")

    def test_blank_message_falls_back(self) -> None:
        assert sanitize_message("   \n ") == GENERIC_ERROR_MESSAGE

    def test_custom_fallback_is_used(self) -> None:
        assert sanitize_message("", fallback="nothing here") == "nothing here"

    def test_non_ascii_text_survives(self) -> None:
        assert sanitize_message("运行失败：端口被占用") == "运行失败：端口被占用"


class TestErrorEnvelope:
    def test_envelope_shape_is_stable(self) -> None:
        envelope = error_envelope(HttpErrorCode.NOT_FOUND, "no such endpoint")

        dumped = envelope.model_dump(mode="json")
        assert set(dumped) == {"error"}
        assert dumped["error"] == {"code": "not_found", "message": "no such endpoint"}

    def test_message_is_sanitized_and_bounded(self) -> None:
        envelope = error_envelope(HttpErrorCode.SERVER_ERROR, "a" * (MAX_ERROR_MESSAGE_CHARS * 2))

        assert len(envelope.error.message) <= MAX_ERROR_MESSAGE_CHARS

    def test_detail_rejects_blank_message(self) -> None:
        with pytest.raises(ValidationError):
            HttpErrorDetail(code=HttpErrorCode.SERVER_ERROR, message="")

    def test_extra_fields_are_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            HttpErrorEnvelope.model_validate({"error": {"code": "not_found", "message": "x", "debug": "traceback"}})


class TestHealthResponse:
    def test_defaults_match_the_public_contract(self) -> None:
        health = HealthResponse(version="1.2.3")

        assert health.status == "ok"
        assert health.service == HTTP_SERVICE_NAME == "heagent-http"
        assert health.schema_version == HTTP_SCHEMA_VERSION == "1"
        assert set(health.model_dump()) == {"status", "service", "version", "schema_version"}

    @pytest.mark.parametrize("version", ["", "x" * 65])
    def test_version_is_required_and_bounded(self, version: str) -> None:
        with pytest.raises(ValidationError):
            HealthResponse(version=version)

    def test_extra_fields_are_forbidden(self) -> None:
        """健康响应不接受额外字段：这是「不泄露内部信息」的机械保证之一。"""
        with pytest.raises(ValidationError):
            HealthResponse.model_validate({"version": "1.0", "workspace": "C:/secret"})


class TestPromptBound:
    def test_page_maxlength_matches_the_protocol_bound(self) -> None:
        """页面的输入上限与协议常量必须一致：两处各写一个数迟早漂移。"""
        page = read_web_asset("index.html").decode("utf-8")

        assert f'maxlength="{MAX_PROMPT_CHARS}"' in page

    def test_bound_is_meaningful(self) -> None:
        assert 1024 <= MAX_PROMPT_CHARS <= 1_000_000
