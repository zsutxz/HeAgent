"""A35 判据：网页入口（``HttpAgentHandler``）也按 ``EVENTS_ROLLOUT_ENABLED`` 挂事件 sink。

背景（活动台账 A35）：网页入口的 ``HttpAgentHandler`` 自建 engine，但此前从不订阅事件接收器
⇒ ``EVENTS_ROLLOUT_ENABLED`` 在网页入口是死键（与 A44 闭合前的交互 REPL 同款问题）。这是
「重启后从 rollout 回放」的**前置条件**：没有落盘就谈不上回放。

判据成对：

1. **默认关闭零 rollout 文件**（rollout 含工具原始输出，默认不落盘不能被这轮改动破坏）；
2. **开关打开时网页 run 真的落盘**，且落在所属**项目根**下——多项目控制台里进程 cwd 不等于
   项目根，若按 cwd 落盘会把 A 项目的事件写进 B 项目的 ``.heagent/runs``。

测试手法与 ``tests/test_cli_events_rollout.py`` 一致：替换 provider 而不是替换 handler 的
运行路径——后者会把被测的订阅一并打桩掉。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heagent.cli.http_console import HttpAgentHandler
from heagent.config import Settings
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, TokenUsage

if TYPE_CHECKING:  # pytest 只用于注解 ⇒ 放类型检查块（TC002）
    import pytest


class _StubProvider:
    """最小 provider：一次 send 返回固定答案，供真实 ``AgentLoop`` 跑完一轮。"""

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


def _rollout_files(root: Path) -> list[Path]:
    return sorted(root.glob(".heagent/runs/*/rollout.jsonl"))


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    """进程 cwd 与项目根**刻意分开**：两条用例都据此判「落盘按哪个根」。"""
    cwd = tmp_path / "cwd"
    project = tmp_path / "proj"
    cwd.mkdir()
    project.mkdir()
    return cwd, project


async def _drive_once(handler: HttpAgentHandler) -> None:
    loop = handler.new_loop()
    async for _event in loop.run_stream("hi"):
        pass


async def test_web_handler_writes_no_rollout_when_the_switch_is_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """默认关闭 ⇒ 网页跑完一轮也不产生任何 rollout 文件（rollout 含工具原始输出）。"""
    cwd, project = _layout(tmp_path)
    monkeypatch.chdir(cwd)
    provider = _StubProvider()
    handler = HttpAgentHandler(provider, Settings(_env_file=None), workspace_root=project)

    await _drive_once(handler)

    assert provider.calls == 1  # 前提：真的跑了一轮（否则「没有文件」不能说明任何事）
    assert _rollout_files(project) == []
    assert _rollout_files(cwd) == []


async def test_web_handler_writes_rollout_under_project_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """开关打开 ⇒ 网页这次 run 落盘到 ``<项目根>/.heagent/runs/<run_id>/rollout.jsonl``。"""
    cwd, project = _layout(tmp_path)
    monkeypatch.chdir(cwd)
    provider = _StubProvider()
    handler = HttpAgentHandler(
        provider,
        Settings(_env_file=None, events_rollout_enabled=True),
        workspace_root=project,
    )

    await _drive_once(handler)

    assert provider.calls == 1
    files = _rollout_files(project)
    assert len(files) == 1, files
    kinds = [json.loads(line)["kind"] for line in files[0].read_text(encoding="utf-8").splitlines()]
    assert "run_started" in kinds, kinds  # 是本轮 run 的事件，不是别的来源
    assert kinds[-1] == "run_completed", kinds  # 一轮真正跑完（不是半截 rollout）
    assert _rollout_files(cwd) == []  # 按项目根落盘，不是进程 cwd
