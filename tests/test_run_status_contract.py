"""Run 终态转换契约（Phase 2 C2）：终态只能经 ``RunContext.mark_terminal`` 唯一写入。

钉死三件事：
1. 合法转换仅 RUNNING→COMPLETED / RUNNING→FAILED，各恰好一次；
2. 终态再写（COMPLETED→FAILED 等）显性失败，不静默覆盖；
3. 取消路径（CancelledError）不写终态：status 保持 RUNNING，run 仍可 resume 续跑
   （现状语义显性化——取消 ≠ 失败，与 resume「恢复未完成运行」的设计一致）。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import pytest

from heagent.agent.loop import AgentLoop
from heagent.config import reset_settings
from heagent.engine import RunStatus
from heagent.engine.context import RunContext
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    """隔离 Settings 单例（Phase 1 构造期解析契约）。"""
    reset_settings()
    yield
    reset_settings()


class _TerminalRecorder:
    """包裹 ``RunContext.touch``，记录每次状态写入的次序。"""

    def __init__(self) -> None:
        self.status_writes: list[RunStatus] = []
        self._real_touch = RunContext.touch

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        def spy_touch(self_ctx: RunContext, **kwargs):  # noqa: ANN003
            if kwargs.get("status") is not None:
                recorder.status_writes.append(kwargs["status"])
            return recorder._real_touch(self_ctx, **kwargs)

        monkeypatch.setattr(RunContext, "touch", spy_touch)


class StubProvider:
    """可编程 provider：正常返回 / 抛错 / 挂起三模式。"""

    def __init__(self, *, error: Exception | None = None, hang: bool = False) -> None:
        self._error = error
        self._hang = hang

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        if self._hang:
            await asyncio.Event().wait()  # 永不设置：只能被取消
        if self._error is not None:
            raise self._error
        return ProviderResponse(
            content="ok",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> AsyncIterator[object]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _terminal_events(loop: AgentLoop) -> list[str]:
    return [e.event_type for e in loop.engine.events.recent_events if e.event_type in ("run_completed", "run_failed")]


# ----------------------------------------------------------------------
# reducer 单元契约
# ----------------------------------------------------------------------


class TestMarkTerminalContract:
    def test_running_to_completed_is_legal(self) -> None:
        ctx = RunContext()
        ctx.mark_terminal(RunStatus.COMPLETED, iteration=3)
        assert ctx.status is RunStatus.COMPLETED
        assert ctx.iteration == 3

    def test_running_to_failed_is_legal(self) -> None:
        ctx = RunContext()
        ctx.mark_terminal(RunStatus.FAILED, iteration=2)
        assert ctx.status is RunStatus.FAILED

    def test_non_terminal_argument_is_rejected(self) -> None:
        ctx = RunContext()
        with pytest.raises(ValueError, match="terminal"):
            ctx.mark_terminal(RunStatus.RUNNING)
        assert ctx.status is RunStatus.RUNNING  # 状态未被破坏

    def test_double_terminal_write_fails_loud(self) -> None:
        ctx = RunContext()
        ctx.mark_terminal(RunStatus.COMPLETED)
        with pytest.raises(RuntimeError, match="already terminal"):
            ctx.mark_terminal(RunStatus.FAILED)
        with pytest.raises(RuntimeError, match="already terminal"):
            ctx.mark_terminal(RunStatus.COMPLETED)
        assert ctx.status is RunStatus.COMPLETED  # 首个终态不被改写


# ----------------------------------------------------------------------
# 真实 loop 行为契约
# ----------------------------------------------------------------------


class TestLoopTerminalWriteContract:
    async def test_successful_run_writes_completed_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _TerminalRecorder()
        recorder.install(monkeypatch)
        loop = AgentLoop(StubProvider(), max_iterations=3)
        answer = await loop.run("hello")

        assert answer == "ok"
        assert loop.last_run_context is not None
        assert loop.last_run_context.status is RunStatus.COMPLETED
        assert recorder.status_writes == [RunStatus.COMPLETED]  # 恰好一次终态写点
        assert _terminal_events(loop) == ["run_completed"]

    async def test_failed_run_writes_failed_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = _TerminalRecorder()
        recorder.install(monkeypatch)
        loop = AgentLoop(StubProvider(error=RuntimeError("boom")), max_iterations=3)

        with pytest.raises(RuntimeError, match="boom"):
            await loop.run("hello")

        assert loop.last_run_context is not None
        assert loop.last_run_context.status is RunStatus.FAILED
        assert recorder.status_writes == [RunStatus.FAILED]  # 恰好一次终态写点
        assert _terminal_events(loop) == ["run_failed"]

    async def test_cancelled_run_keeps_running_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """取消不写终态：status 保持 RUNNING（可 resume），不发 run_completed/run_failed。"""
        recorder = _TerminalRecorder()
        recorder.install(monkeypatch)
        loop = AgentLoop(StubProvider(hang=True), max_iterations=3)

        task = asyncio.create_task(loop.run("hello"))
        for _ in range(20):  # 让 loop 进入 provider 调用
            await asyncio.sleep(0)
            if loop.engine.events.recent_events:
                break
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert loop.last_run_context is not None
        assert loop.last_run_context.status is RunStatus.RUNNING  # 未写终态
        assert recorder.status_writes.count(RunStatus.COMPLETED) == 0
        assert recorder.status_writes.count(RunStatus.FAILED) == 0
        assert _terminal_events(loop) == []
