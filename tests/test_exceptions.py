"""Tests for HeAgent exception hierarchy."""

import pytest

from heagent.pub.exceptions import (
    BudgetExceeded,
    HeAgentError,
    ProviderError,
    SafetyViolation,
    ToolError,
)


@pytest.mark.parametrize(
    ("exc_cls", "message"),
    [
        pytest.param(HeAgentError, "test error", id="base"),
        pytest.param(ProviderError, "api failed", id="provider"),
        pytest.param(ToolError, "execution failed", id="tool"),
        pytest.param(SafetyViolation, "dangerous command", id="safety"),
        pytest.param(BudgetExceeded, "max iterations reached", id="budget"),
    ],
)
def test_error_carries_message_and_inherits_base(exc_cls: type[HeAgentError], message: str) -> None:
    """五类异常同判据：携带 message、str() 直返原文、继承 HeAgentError。"""
    err = exc_cls(message)
    assert err.message == message
    assert str(err) == message
    assert isinstance(err, HeAgentError)
