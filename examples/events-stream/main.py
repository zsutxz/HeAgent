"""示例：订阅事件流。

`Agent` 的运行时事件（provider 调用、工具调用、run 生命周期）都经 `EngineContainer.events`
（`EventBus`）同步派发。订阅一个观察者就能拿到整轮 run 的结构化轨迹。

跑法（仓库根）：

    python examples/events-stream/main.py

不需要网络。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from heagent import Agent, EngineContainer
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import ProviderResponse, TokenUsage, ToolCall
from heagent.tools.decorator import tool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.engine.observability import EngineEvent


@tool(read_only=True)
def add(a: int, b: int) -> str:
    """把两个整数相加。"""
    return str(a + b)


class Collector:
    """最小观察者：只把事件收进列表，不做 I/O。

    契约：`handle` 在调用方协程里**同步派发**，不得做阻塞 I/O 或重 CPU——否则会拖慢主循环。
    要写盘就给队列投递、另起消费者。
    """

    def __init__(self) -> None:
        self.events: list[EngineEvent] = []

    def handle(self, event: EngineEvent) -> None:
        self.events.append(event)


class TwoTurnProvider:
    """第一轮要求调 add，第二轮给最终答案。"""

    def __init__(self) -> None:
        self.turns = 0

    async def send(self, messages: list[object], *, tools: list[object] | None = None) -> ProviderResponse:
        self.turns += 1
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        if self.turns == 1:
            return ProviderResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="add", arguments={"a": 2, "b": 3})],
                usage=usage,
                model="events-demo",
                finish_reason="tool_calls",
            )
        return ProviderResponse(
            content="2 + 3 = 5",
            usage=usage,
            model="events-demo",
            finish_reason="stop",
        )

    async def stream(
        self, messages: list[object], *, tools: list[object] | None = None
    ) -> AsyncIterator[ProviderResponse]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="events-demo", model="events-demo")


async def main() -> None:
    collector = Collector()
    engine = EngineContainer()
    engine.events.subscribe(collector)

    agent = Agent(TwoTurnProvider(), engine=engine)
    answer = await agent.run("2 加 3 等于几")
    print("答案:", answer)

    print(f"收到 {len(collector.events)} 条事件：")
    for event in collector.events:
        detail = ""
        if "duration_ms" in event.details:
            detail = f" duration_ms={event.details['duration_ms']}"
        print(f"  - {event.event_type} iter={event.iteration} tool={event.tool_name or '-'}{detail}")


if __name__ == "__main__":
    asyncio.run(main())
