"""CLI 旁路的入口侧契约（Epic 55）：终端一轮 run 的事件镜像与**故障隔离**。

判据的重心不是「事件长什么样」（那是 ``network`` 侧的事），而是两条入口层不变量：

- 一轮交互 = 一个旁路 run（``begin_run`` … ``end_run`` 恰好一次，取消 / 报错也收尾）；
- 旁路坏了**不得**影响终端：它抛异常最坏只是「外部看不到」，stdout 与退出行为必须逐字不变。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from heagent.cli import interactive
from heagent.cli.display import _LineState
from heagent.pub.exceptions import HeAgentError
from heagent.pub.types import StreamEvent


class _RecordingHub:
    """记录调用序列的替身（形状对齐 ``CliEventHub``，只实现入口层会调的方法）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.active: str | None = None

    def begin_run(self) -> str:
        self.calls.append(("begin_run",))
        self.active = "run-1"
        return "run-1"

    def end_run(self) -> None:
        self.calls.append(("end_run",))
        self.active = None

    def publish_text(self, text: str) -> None:
        self.calls.append(("text", text))

    def publish_tool_call(self, name: str, target: str) -> None:
        self.calls.append(("tool_call", name, target))

    def publish_tool_result(self, name: str, output: str, *, is_error: bool) -> None:
        self.calls.append(("tool_result", name, output, is_error))

    def publish_done(self, answer: str) -> None:
        self.calls.append(("done", answer))

    def publish_error(self, message: str) -> None:
        self.calls.append(("error", message))

    def publish_cancelled(self, message: str = "run interrupted") -> None:
        self.calls.append(("cancelled", message))


class _ExplodingHub:
    """每个方法都炸：用来证明旁路故障被入口层吞掉。"""

    def __getattr__(self, name: str) -> Any:
        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError(f"hub exploded in {name}")

        return _boom


class _StubLoop:
    def __init__(self, events: list[StreamEvent], *, error: BaseException | None = None) -> None:
        self._events = events
        self._error = error
        self.last_usage = None
        self.provider = SimpleNamespace(get_metadata=lambda: SimpleNamespace(model="stub"))

    async def run_stream(self, prompt: str, *, system: str | None = None, session_id: str | None = None) -> Any:
        for event in self._events:
            yield event
        if self._error is not None:
            raise self._error


async def _consume(hub: Any, loop: _StubLoop) -> None:
    token = interactive._CLI_HUB.set(hub)
    try:
        await interactive._consume_stream(loop, "prompt", None, "session", _LineState())
    finally:
        interactive._CLI_HUB.reset(token)


def test_every_stream_event_kind_is_mirrored_and_the_run_is_bracketed() -> None:
    hub = _RecordingHub()
    loop = _StubLoop(
        [
            StreamEvent(type="text", text="hello"),
            StreamEvent(type="tool_call", tool_name="shell", tool_target="echo hi"),
            StreamEvent(type="tool_result", tool_name="shell", tool_result_content="hi", tool_error=False),
            StreamEvent(type="done", final_answer="finished"),
        ]
    )
    asyncio.run(_consume(hub, loop))

    assert hub.calls == [
        ("begin_run",),
        ("text", "hello"),
        ("tool_call", "shell", "echo hi"),
        ("tool_result", "shell", "hi", False),
        ("done", "finished"),
        ("end_run",),
    ]
    assert hub.active is None


def test_business_failure_is_mirrored_and_the_run_still_closes() -> None:
    hub = _RecordingHub()
    loop = _StubLoop([StreamEvent(type="text", text="partial")], error=HeAgentError("provider down"))
    asyncio.run(_consume(hub, loop))

    assert hub.calls[0] == ("begin_run",)
    assert ("error", "provider down") in hub.calls
    assert hub.calls[-1] == ("end_run",)


def test_cancellation_is_mirrored_and_the_run_still_closes() -> None:
    hub = _RecordingHub()
    loop = _StubLoop([], error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_consume(hub, loop))

    assert hub.calls == [("begin_run",), ("cancelled", "run interrupted"), ("end_run",)]


def test_broken_hub_does_not_disturb_the_terminal_output(capsys: pytest.CaptureFixture[str]) -> None:
    loop = _StubLoop(
        [
            StreamEvent(type="text", text="terminal output survives"),
            StreamEvent(type="done", final_answer="finished"),
        ]
    )
    asyncio.run(_consume(_ExplodingHub(), loop))

    captured = capsys.readouterr()
    assert "terminal output survives" in captured.out


def test_hub_scope_sets_and_resets_the_contextvar() -> None:
    hub = _RecordingHub()

    async def scenario() -> tuple[Any, Any]:
        async with interactive._cli_hub_scope(SimpleNamespace(cli_hub=hub)):
            inside = interactive._CLI_HUB.get()
        return inside, interactive._CLI_HUB.get()

    inside, outside = asyncio.run(scenario())
    assert inside is hub
    assert outside is None


def test_hub_scope_is_a_no_op_for_a_service_without_the_attribute() -> None:
    """测试替身 / 未开启旁路时内嵌服务没有 ``cli_hub``：作用域里必须是 ``None`` 而不是 AttributeError。"""

    async def scenario() -> Any:
        async with interactive._cli_hub_scope(SimpleNamespace()):
            return interactive._CLI_HUB.get()

    assert asyncio.run(scenario()) is None


def test_mirror_is_a_no_op_without_a_hub() -> None:
    interactive._mirror_stream_event(None, StreamEvent(type="text", text="ignored"))


def test_scope_propagates_into_the_stream_mirror() -> None:
    """``_cli_hub_scope`` 的作用域必须真的到达 ``_consume_stream``（contextvar 传播判据）。"""
    hub = _RecordingHub()
    loop = _StubLoop(
        [StreamEvent(type="text", text="hi"), StreamEvent(type="done", final_answer="ok")]
    )

    async def scenario() -> None:
        async with interactive._cli_hub_scope(SimpleNamespace(cli_hub=hub)):
            await interactive._consume_stream(loop, "prompt", None, "session", _LineState())

    asyncio.run(scenario())
    assert hub.calls == [("begin_run",), ("text", "hi"), ("done", "ok"), ("end_run",)]
