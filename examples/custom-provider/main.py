"""示例：扩展一个 Provider。

Provider 是**结构化协议**（`typing.Protocol`），不需要继承任何基类——实现
`send` / `stream` / `get_metadata` 三个方法即可被 `Agent` 接受。

跑法（仓库根）：

    python examples/custom-provider/main.py

不需要网络：`EchoProvider` 把最后一条用户消息原样回声，并给出符合契约的 token 统计。
把它换成真实后端时，只需把 `send` 里的构造换成一个 HTTP 调用（见本目录 README 的
「接到真实后端」段）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from heagent import Agent
from heagent.providers.base import BaseProvider, ProviderMetadata
from heagent.pub.types import ProviderResponse, TokenUsage


class EchoProvider:
    """最小可用 Provider：回声 + 固定 token 统计。"""

    def __init__(self, model: str = "echo-1") -> None:
        self._model = model

    async def send(
        self,
        messages: list[object],
        *,
        tools: list[object] | None = None,
    ) -> ProviderResponse:
        """单次调用：取最后一条 user 消息作为回答。"""
        last_user = ""
        for message in reversed(messages):
            if getattr(message, "role", "") == "user":
                last_user = str(getattr(message, "content", ""))
                break
        # usage 必须给：AgentLoop 用它做 token 校准与运行统计。
        usage = TokenUsage(
            prompt_tokens=max(len(last_user) // 4, 1),
            completion_tokens=max(len(last_user) // 4, 1),
            total_tokens=max(len(last_user) // 2, 2),
        )
        return ProviderResponse(
            content=f"[echo] {last_user}",
            usage=usage,
            model=self._model,
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: list[object],
        *,
        tools: list[object] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式调用：这里退化为一次性返回整段（真实 Provider 应逐块 yield）。"""
        full = await self.send(messages, tools=tools)
        yield full

    def get_metadata(self) -> ProviderMetadata:
        """能力声明：CLI 的 `/provider` 列表与状态行会读它。"""
        return ProviderMetadata(
            name="echo",
            model=self._model,
            supports_streaming=True,
            supports_tools=False,
        )


async def main() -> None:
    provider = EchoProvider()

    # 结构性校验：没有继承任何基类，但满足协议。
    print("isinstance(BaseProvider):", isinstance(provider, BaseProvider))
    print("metadata:", provider.get_metadata().model_dump())

    agent = Agent(provider)
    print("send 路径:", await agent.run("你好，HeAgent"))

    chunks = [chunk.content async for chunk in provider.stream([], tools=None)]
    print("stream 块数:", len(chunks))


if __name__ == "__main__":
    asyncio.run(main())
