"""Tests for tokenizer backends and heuristic calibration (P0-3).

三组契约：

1. **后端选择** —— 无 ``tiktoken`` 或 ``TOKENIZER=estimate`` 走启发式；``auto`` + 有依赖走真实
   tokenizer；``tiktoken`` 强制但依赖缺失时告警一次并回退；
2. **在线校准** —— provider 真实 usage 回收为按模型的系数，坏样本（0 / 比值离谱）被丢弃；
3. **接线** —— ``AgentLoop._call_provider`` 是校准的唯一入口（非流式必经此处）。
"""

from __future__ import annotations

import logging
import sys
import types
from typing import TYPE_CHECKING

import pytest

from heagent.agent.loop import AgentLoop, AgentState
from heagent.config import reset_settings
from heagent.context.compressor import _DEFAULT_PROMPT
from heagent.context.tokens import (
    calibration_factor,
    count_tokens,
    note_actual_usage,
    reset_calibration,
    tokenizer_backend,
)
from heagent.engine.container import EngineContainer
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, Role, TokenUsage

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path


class _FakeEncoding:
    """每字符 1 token 的假 encoding —— 与 4 字符/token 的启发式明显可区分。"""

    def encode(self, text: str) -> list[int]:
        return [0] * len(text)


class _FakeTiktoken(types.ModuleType):
    """最小 tiktoken 替身（只实现被用到的两个入口）。"""

    def encoding_for_model(self, model: str) -> _FakeEncoding:
        return _FakeEncoding()

    def get_encoding(self, name: str) -> _FakeEncoding:
        return _FakeEncoding()


class _UsageProvider:
    """返回真实 usage 的假 provider：输入量固定为本地估算的 2 倍（ratio 落在合理区间）。"""

    name = "fake"

    async def send(self, messages: Sequence[Message], tools: object = None) -> ProviderResponse:  # noqa: ANN401
        prompt = count_tokens(list(messages), model="fake-model") * 2
        return ProviderResponse(
            content="ok",
            usage=TokenUsage(prompt_tokens=prompt, completion_tokens=10, total_tokens=prompt + 10),
            model="fake-model",
            finish_reason="stop",
        )


@pytest.fixture(autouse=True)
def _clean() -> Generator[None, None, None]:
    reset_calibration()
    reset_settings()
    yield
    reset_calibration()
    reset_settings()


def _hide_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 ``import tiktoken`` 抛 ImportError（模拟「依赖未安装」）。"""
    monkeypatch.setitem(sys.modules, "tiktoken", None)


def _fake_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "tiktoken", _FakeTiktoken("tiktoken"))


class TestBackendSelection:
    def test_defaults_to_estimation_without_tiktoken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _hide_tiktoken(monkeypatch)
        assert tokenizer_backend("deepseek-v4-pro") == "estimate"

    def test_auto_uses_tiktoken_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_tiktoken(monkeypatch)
        monkeypatch.setenv("TOKENIZER", "auto")
        assert tokenizer_backend("deepseek-v4-pro") == "tiktoken"

    def test_estimate_mode_ignores_available_tiktoken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """显式 estimate 必须压过可用依赖——否则「对齐旧行为/离线复现」无从谈起。"""
        _fake_tiktoken(monkeypatch)
        monkeypatch.setenv("TOKENIZER", "estimate")
        assert tokenizer_backend("deepseek-v4-pro") == "estimate"

    def test_real_encoding_changes_the_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _hide_tiktoken(monkeypatch)
        messages = [Message(role=Role.USER, content="abcdefgh" * 10)]
        estimated = count_tokens(messages, model="m")
        reset_calibration()  # 清 encoding 缓存，让后端按新状态重新探测
        _fake_tiktoken(monkeypatch)
        assert count_tokens(messages, model="m") > estimated  # 每字符 1 token > 4 chars/token

    def test_tiktoken_mode_warns_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _hide_tiktoken(monkeypatch)
        monkeypatch.setenv("TOKENIZER", "tiktoken")
        with caplog.at_level(logging.WARNING, logger="heagent.context.tokens"):
            assert tokenizer_backend("m") == "estimate"
        assert any("tiktoken" in record.message for record in caplog.records)


class TestCalibration:
    def test_sample_scales_estimate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _hide_tiktoken(monkeypatch)
        messages = [Message(role=Role.USER, content="hello world")]
        raw = count_tokens(messages, model="m")
        note_actual_usage("m", estimated=100, actual=200)
        assert calibration_factor("m") == pytest.approx(1.5)
        assert count_tokens(messages, model="m") == round(raw * 1.5)

    def test_zero_and_out_of_range_samples_ignored(self) -> None:
        """坏样本比没有样本更糟：0（无 usage）与离谱比值一律不采纳。"""
        note_actual_usage("m", estimated=100, actual=0)
        note_actual_usage("m", estimated=0, actual=100)
        note_actual_usage("m", estimated=100, actual=100_000)
        assert calibration_factor("m") == 1.0

    def test_calibration_is_per_model(self) -> None:
        note_actual_usage("a", estimated=100, actual=200)
        assert calibration_factor("a") == pytest.approx(1.5)
        assert calibration_factor("b") == 1.0

    def test_reset_clears_samples(self) -> None:
        note_actual_usage("m", estimated=100, actual=200)
        reset_calibration()
        assert calibration_factor("m") == 1.0


class TestStructuredCompactionPrompt:
    def test_prompt_requires_four_sections(self) -> None:
        for section in ("## Goal", "## Changed files", "## Todo", "## Constraints and failures"):
            assert section in _DEFAULT_PROMPT

    def test_prompt_demands_verbatim_details(self) -> None:
        assert "verbatim" in _DEFAULT_PROMPT


class TestLoopWiring:
    async def test_call_provider_feeds_calibration(self, tmp_path: Path) -> None:
        """接线测试：非流式调用完成后，估算系数必须被真实 usage 校正。"""
        loop = AgentLoop(
            _UsageProvider(),
            registry=ToolRegistry(),
            engine=EngineContainer(),
            context_dir=str(tmp_path),
        )
        state = AgentState()
        state.messages.append(Message(role=Role.USER, content="hello"))

        await loop._call_provider(state)

        assert calibration_factor("fake-model") == pytest.approx(1.5)
