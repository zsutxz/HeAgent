"""A44 判据：**交互 REPL** 也按 ``EVENTS_ROLLOUT_ENABLED`` 挂事件 sink。

背景（活动台账 A44）：``JsonlSink`` 原先只在单次模式路径订阅（``interactive._run_single``），交互
REPL 从不订阅 ⇒ ``EVENTS_ROLLOUT_ENABLED`` 在交互模式是死键（audit 只剩 checkpoint / 快照 / 租约）。

两条判据成对才有意义：

1. **默认（开关关闭）零 rollout 文件**——这是有意设计（rollout 含工具原始输出），不能被这轮改动破坏；
2. **开关打开时 REPL 真的落盘**，且落盘内容是本轮 run 的事件（不是空文件、不是别的来源）。

测试手法与 ``tests/test_cli_http_lifecycle.py`` 一致：替换 provider 而不是替换 ``_run_chat`` /
``_run_prompt``——后者会把被测的订阅路径一并打桩掉。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from click.testing import CliRunner

from heagent.cli.console import main
from heagent.config import reset_settings
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, TokenUsage

if TYPE_CHECKING:  # pytest 只用于注解 ⇒ 放类型检查块（TC002）
    import pytest


class _StubProvider:
    """最小 provider：一次 send 返回固定答案，供真实 loop 跑完一轮。"""

    def __init__(self) -> None:
        self.calls = 0

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(
            content="stub answer",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _drive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider: _StubProvider) -> None:
    """在 tmp 目录里跑默认 CLI（workspace = cwd ⇒ rollout 落在 tmp 下），指向替身 provider。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("heagent.cli.console._build_provider", lambda settings, model: provider)
    reset_settings()


def _rollout_files(root: Path) -> list[Path]:
    return sorted(root.glob(".heagent/runs/*/rollout.jsonl"))


def test_interactive_repl_writes_no_rollout_when_the_switch_is_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """默认关闭 ⇒ 交互一轮跑完也不产生任何 rollout 文件（rollout 含工具原始输出）。"""
    provider = _StubProvider()
    _drive(monkeypatch, tmp_path, provider)

    result = CliRunner().invoke(main, [], input="hi\n")

    assert result.exit_code == 0, result.output
    assert provider.calls == 1  # 前提：真的跑了一轮（否则「没有文件」不能说明任何事）
    assert _rollout_files(tmp_path) == []


def test_interactive_repl_writes_rollout_when_the_switch_is_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """开关打开 ⇒ 交互 REPL 的这轮 run 真的落盘成 ``<rollout_dir>/<run_id>/rollout.jsonl``。"""
    monkeypatch.setenv("EVENTS_ROLLOUT_ENABLED", "true")
    provider = _StubProvider()
    _drive(monkeypatch, tmp_path, provider)

    result = CliRunner().invoke(main, [], input="hi\n")

    assert result.exit_code == 0, result.output
    assert provider.calls == 1
    files = _rollout_files(tmp_path)
    assert len(files) == 1, files
    kinds = [json.loads(line)["kind"] for line in files[0].read_text(encoding="utf-8").splitlines()]
    assert "run_started" in kinds, kinds  # 是本轮 run 的事件，不是别的来源
    assert kinds[-1] == "run_completed", kinds  # 一轮真正跑完（不是半截 rollout）
