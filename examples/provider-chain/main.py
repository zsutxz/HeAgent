"""示例：ProviderChain 故障转移。

`ProviderChain` 按顺序尝试 Provider，前者抛错时自动切换后者；全部失败则重置并抛出最后一个异常。

跑法（仓库根）：

    python examples/provider-chain/main.py

不需要网络：两个 stub Provider 里第一个必定抛错，用来观察回退行为。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from heagent import Agent, ProviderChain
from heagent.providers.base import ProviderMetadata
from heagent.pub.exceptions import ProviderError
from heagent.pub.types import ProviderResponse, TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class BrokenProvider:
    """总是失败的 Provider：抛 503（TRANSIENT），这是**会被回退**的类别。

    换成 `RuntimeError("boom")` 就不会回退——分类器把它判成 NON_TRANSIENT，
    理由是「切 Provider 不会让坏请求变好」（判据见 `providers/retry.py`）。
    """

    def __init__(self, name: str = "broken") -> None:
        self._name = name
        self.attempts = 0

    async def send(self, messages: list[object], *, tools: list[object] | None = None) -> ProviderResponse:
        self.attempts += 1
        raise ProviderError(f"{self._name} is down", status_code=503)

    async def stream(
        self, messages: list[object], *, tools: list[object] | None = None
    ) -> AsyncIterator[ProviderResponse]:
        # 先 yield 再抛：让它是真正的 async generator（Protocol 要求），而不是返回 coroutine 的普通函数。
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name=self._name, model=self._name)


class HealthyProvider:
    """接住回退的那个 Provider。"""

    def __init__(self, name: str = "healthy") -> None:
        self._name = name
        self.calls = 0

    async def send(self, messages: list[object], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls += 1
        usage = TokenUsage(prompt_tokens=8, completion_tokens=4, total_tokens=12)
        return ProviderResponse(
            content=f"[{self._name}] 我接住了这次调用（第 {self.calls} 次）。",
            usage=usage,
            model=self._name,
            finish_reason="stop",
        )

    async def stream(
        self, messages: list[object], *, tools: list[object] | None = None
    ) -> AsyncIterator[ProviderResponse]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name=self._name, model=self._name, supports_tools=True)


async def main() -> None:
    broken = BrokenProvider()
    healthy = HealthyProvider()
    chain = ProviderChain([broken, healthy])

    agent = Agent(chain)
    print("回答:", await agent.run("你好"))

    print("当前生效 Provider:", type(chain.current).__name__)
    print("broken 尝试次数:", broken.attempts)
    print("healthy 调用次数:", healthy.calls)


if __name__ == "__main__":
    asyncio.run(main())
