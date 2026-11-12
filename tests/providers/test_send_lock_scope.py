"""send 路径锁范围护栏：锁只罩索引读写，不罩网络 I/O（与 stream 的 P1-3/P1-11/P2-2 同口径）。

旧实现在 ``async with self._lock`` 内 ``await provider.send``：一个慢调用会把同一实例上
所有并发 send 串行化。本测试让第一个 send 卡在 provider 内，断言第二个 send 仍能进入
provider——锁罩住网络 I/O 时第二个调用永远进不去，``wait_for`` 超时即红。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

from heagent.providers.base import ProviderMetadata
from heagent.providers.chain import ProviderChain
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.switchable import SwitchableProvider
from heagent.pub.types import Message, ProviderResponse, Role, TokenUsage, ToolSchema


class _GatedProvider:
    """每次 send 先登记进入，再等闸门放行。"""

    def __init__(self) -> None:
        self.entered = 0
        self.both_entered = asyncio.Event()
        self.release = asyncio.Event()

    async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
        self.entered += 1
        if self.entered >= 2:
            self.both_entered.set()
        await self.release.wait()
        return ProviderResponse(
            content="ok",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="gated",
            finish_reason="stop",
        )

    async def stream(
        self, messages: list[Message], *, tools: list[ToolSchema] | None = None
    ) -> AsyncIterator[ProviderResponse]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="gated", model="gated", supports_streaming=True, supports_tools=True)


_WRAPPERS: dict[str, Callable[[_GatedProvider], object]] = {
    "chain": lambda p: ProviderChain([p]),  # type: ignore[list-item]
    "key_rotation": lambda p: KeyRotatingProvider([p]),  # type: ignore[list-item]
    "switchable": lambda p: SwitchableProvider({"a": p}, default="a"),  # type: ignore[dict-item]
}


@pytest.mark.parametrize("kind", sorted(_WRAPPERS))
async def test_concurrent_send_is_not_serialized_by_lock(kind: str) -> None:
    inner = _GatedProvider()
    wrapper = _WRAPPERS[kind](inner)
    msgs = [Message(role=Role.USER, content="hi")]

    t1 = asyncio.create_task(wrapper.send(msgs))  # type: ignore[attr-defined]
    t2 = asyncio.create_task(wrapper.send(msgs))  # type: ignore[attr-defined]
    try:
        await asyncio.wait_for(inner.both_entered.wait(), timeout=1.0)
    finally:
        inner.release.set()
        results = await asyncio.gather(t1, t2, return_exceptions=True)

    assert inner.entered == 2
    assert all(isinstance(r, ProviderResponse) and r.content == "ok" for r in results), results
