"""send_accounted 旁路调用记账的单元测试。"""

import logging

import pytest

from heagent.context import sidecall
from heagent.context.sidecall import send_accounted
from heagent.pub.types import Message, ProviderResponse, Role, TokenUsage


class StubProvider:
    """最小 stub：返回预设响应或抛预设异常（同 tests/ 各文件 StubProvider 先例）。"""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def send(self, messages, *, tools=None):
        if self.error is not None:
            raise self.error
        return self.response


def _resp(*, prompt=10, completion=5, model="gpt-4o-mini", finish="stop", with_usage=True):
    if with_usage:
        usage = TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )
    else:
        # providers 以零值 TokenUsage 表示「无 usage」（usage 字段非可选）
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    return ProviderResponse(content="ok", usage=usage, model=model, finish_reason=finish)


async def test_send_accounted_logs_and_calibrates(caplog, monkeypatch):
    recorded = []
    monkeypatch.setattr(
        sidecall,
        "note_actual_usage",
        lambda model, *, estimated, actual: recorded.append((model, estimated, actual)),
    )
    stub = StubProvider(response=_resp(prompt=10, completion=5))
    caplog.set_level(logging.INFO, logger="heagent.context.sidecall")
    resp = await send_accounted(
        stub,
        [Message(role=Role.USER, content="hello accounting test")],
        caller="compressor",
    )
    assert resp.content == "ok"
    logs = [r.getMessage() for r in caplog.records]
    assert any("[compressor] Calling provider" in m for m in logs)
    assert any("Provider response: 15 actual tokens" in m for m in logs)
    assert any("provider call completed" in m and "model=gpt-4o-mini" in m and "duration_ms=" in m for m in logs)
    assert len(recorded) == 1
    model_name, estimated, actual = recorded[0]
    assert model_name == "gpt-4o-mini"
    assert estimated > 0
    assert actual == 10


async def test_zero_usage_warns_without_calibration(caplog, monkeypatch):
    recorded = []
    monkeypatch.setattr(
        sidecall,
        "note_actual_usage",
        lambda model, *, estimated, actual: recorded.append((model, estimated, actual)),
    )
    stub = StubProvider(response=_resp(with_usage=False))
    caplog.set_level(logging.INFO, logger="heagent.context.sidecall")
    resp = await send_accounted(
        stub,
        [Message(role=Role.USER, content="zero usage case")],
        caller="window_reset",
    )
    assert resp.content == "ok"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("carries no usage" in r.getMessage() for r in warnings)
    logs = [r.getMessage() for r in caplog.records]
    assert any("total_tokens=0" in m for m in logs)
    assert recorded == []


async def test_error_propagates_and_start_is_logged(caplog):
    stub = StubProvider(error=RuntimeError("boom"))
    caplog.set_level(logging.INFO, logger="heagent.context.sidecall")
    with pytest.raises(RuntimeError, match="boom"):
        await send_accounted(
            stub,
            [Message(role=Role.USER, content="will fail")],
            caller="goal_naming",
        )
    assert any("[goal_naming] Calling provider" in r.getMessage() for r in caplog.records)
