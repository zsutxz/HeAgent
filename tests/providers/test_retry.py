"""Tests for error classification and retry logic."""

from __future__ import annotations

import pytest

from heagent.exceptions import ProviderError
from heagent.providers.retry import (
    ErrorCategory,
    classify_error,
    classify_exception,
    is_pool_fallback_error,
    retry_with_backoff,
)


class _FakeSdkError(Exception):
    """模拟 OpenAI/Anthropic SDK 的 APIStatusError：带 status_code 与 message。"""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TestClassifyError:
    def test_rate_limited_429(self) -> None:
        e = ProviderError("Rate limited")
        e.status_code = 429
        assert classify_error(e) == ErrorCategory.RATE_LIMITED

    def test_rate_limited_message(self) -> None:
        assert classify_error(ProviderError("rate limit exceeded")) == ErrorCategory.RATE_LIMITED

    def test_auth_failed_401(self) -> None:
        e = ProviderError("Unauthorized")
        e.status_code = 401
        assert classify_error(e) == ErrorCategory.AUTH_FAILED

    def test_transient_503(self) -> None:
        e = ProviderError("Service unavailable")
        e.status_code = 503
        assert classify_error(e) == ErrorCategory.TRANSIENT

    def test_transient_timeout(self) -> None:
        assert classify_error(ProviderError("connection timeout")) == ErrorCategory.TRANSIENT

    def test_non_transient(self) -> None:
        e = ProviderError("Bad request")
        e.status_code = 400
        assert classify_error(e) == ErrorCategory.NON_TRANSIENT


class TestClassifyException:
    """classify_exception 对原始 SDK 异常（非 ProviderError）的分类。"""

    def test_rate_limited_429(self) -> None:
        assert classify_exception(_FakeSdkError("rate limited", 429)) == ErrorCategory.RATE_LIMITED

    def test_auth_failed_401(self) -> None:
        assert classify_exception(_FakeSdkError("unauthorized", 401)) == ErrorCategory.AUTH_FAILED

    def test_transient_503(self) -> None:
        assert classify_exception(_FakeSdkError("overloaded", 503)) == ErrorCategory.TRANSIENT

    def test_client_error_400_non_transient(self) -> None:
        assert classify_exception(_FakeSdkError("bad request", 400)) == ErrorCategory.NON_TRANSIENT

    def test_unprocessable_422_non_transient(self) -> None:
        assert classify_exception(_FakeSdkError("unprocessable", 422)) == ErrorCategory.NON_TRANSIENT

    def test_bare_exception_non_transient(self) -> None:
        """无状态码、无可识别关键词的异常默认归为 NON_TRANSIENT（不盲目回退）。"""
        assert classify_exception(RuntimeError("boom")) == ErrorCategory.NON_TRANSIENT

    def test_timeout_message_transient(self) -> None:
        assert classify_exception(RuntimeError("connection timeout")) == ErrorCategory.TRANSIENT

    def test_openai_timeout_phrase_transient(self) -> None:
        """OpenAI SDK APITimeoutError.message='Request timed out.'（无 status_code）应判为 TRANSIENT。"""
        assert classify_exception(RuntimeError("Request timed out.")) == ErrorCategory.TRANSIENT

    def test_connection_error_transient(self) -> None:
        """APIConnectionError.message='Connection error.' 应判为 TRANSIENT。"""
        assert classify_exception(RuntimeError("Connection error.")) == ErrorCategory.TRANSIENT


class TestRetryWithBackoff:
    async def test_success_no_retry(self) -> None:
        result = await retry_with_backoff(lambda: _async_ok("done"))
        assert result == "done"

    async def test_transient_retries_then_succeeds(self) -> None:
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                e = ProviderError("timeout")
                e.status_code = 503
                raise e
            return "ok"

        result = await retry_with_backoff(flaky, base_delay=0.01, max_delay=0.02)
        assert result == "ok"
        assert call_count == 3

    async def test_non_transient_fails_immediately(self) -> None:
        call_count = 0

        async def fail():
            nonlocal call_count
            call_count += 1
            e = ProviderError("Bad request")
            e.status_code = 400
            raise e

        with pytest.raises(ProviderError):
            await retry_with_backoff(fail, base_delay=0.01)
        assert call_count == 1

    async def test_rate_limited_no_retry(self) -> None:
        call_count = 0

        async def fail():
            nonlocal call_count
            call_count += 1
            e = ProviderError("Rate limited")
            e.status_code = 429
            raise e

        with pytest.raises(ProviderError):
            await retry_with_backoff(fail, base_delay=0.01)
        assert call_count == 1

    async def test_exhausted_raises(self) -> None:
        async def always_fail():
            e = ProviderError("timeout")
            e.status_code = 503
            raise e

        with pytest.raises(ProviderError, match="timeout"):
            await retry_with_backoff(always_fail, max_attempts=2, base_delay=0.01)


class TestRetryContract:
    async def test_bare_sdk_error_not_retried(self) -> None:
        """retry_with_backoff 只捕获 ProviderError；fn 直接抛原始 SDK 风格异常（未包装）
        时不重试、立即抛出。这界定了：异常包装必须发生在 provider 源头（wrap_provider_error）。"""
        calls = {"n": 0}

        async def fn() -> object:
            calls["n"] += 1
            raise _FakeSdkError("overloaded", 503)  # 非 ProviderError

        with pytest.raises(_FakeSdkError):
            await retry_with_backoff(fn, base_delay=0.01)
        assert calls["n"] == 1  # 未重试


async def _async_ok(val: str) -> str:
    return val


class TestPoolFallbackPolicy:
    """池内换档判据（``is_pool_fallback_error``）是 RoutingProvider / SwitchableProvider 的**唯一**来源。

    与另两方**有意不同**（见 retry.py 模块 docstring 的策略矩阵）：ProviderChain 回退 AUTH_FAILED
    （``tests/providers/test_chain.py`` 的 401 跨 provider 用例），KeyRotatingProvider 也回退
    AUTH_FAILED（换一把密钥正是解）。本类把这套分歧钉死，避免后人误当漂移而「顺手统一」。
    """

    @pytest.mark.parametrize(
        ("status", "message", "expected"),
        [
            (429, "Rate limited", True),
            (503, "overloaded", True),
            (0, "connection timeout", True),
            (401, "Unauthorized", False),
            (403, "Forbidden", False),
            (400, "bad request", False),
            (422, "unprocessable", False),
        ],
    )
    def test_policy_matrix(self, status: int, message: str, expected: bool) -> None:
        assert is_pool_fallback_error(_FakeSdkError(message, status)) is expected

    def test_auth_failed_excluded_even_though_chain_falls_back_on_it(self) -> None:
        auth = _FakeSdkError("Unauthorized", 401)
        assert classify_exception(auth) is ErrorCategory.AUTH_FAILED  # 非 NON_TRANSIENT：chain 的判据会放行
        assert is_pool_fallback_error(auth) is False  # 池内换档不放行

    def test_predicate_has_a_single_implementation(self) -> None:
        """护栏：router / switchable 不得再各持一份私有判据副本（曾逐字重复，只靠 docstring 互指对齐）。"""
        from heagent.providers import router as router_module
        from heagent.providers import switchable as switchable_module

        assert not hasattr(router_module.RoutingProvider, "_is_fallback_error")
        assert not hasattr(switchable_module.SwitchableProvider, "_is_fallback_error")
