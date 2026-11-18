"""示例：自定义工具（`@tool` 自动注册 → Agent 调用 → 结果回到模型）。

跑法（仓库根）：

    python examples/custom-tool/main.py

不需要网络，也不需要 API key：这里用 `TurnScriptProvider` 按轮次返回固定响应，
第一轮要求调用 `word_count`，第二轮给出最终答案。把它换成真实 Provider 只需要改
最后一行的构造（见 `examples/custom-provider/`）。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from heagent import Agent, tool
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import ProviderResponse, TokenUsage, ToolCall

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# ── 1. 定义一个工具：装饰即注册 ──────────────────────────────────────────
# docstring 首行会成为工具描述，类型注解会成为 JSON Schema。
# read_only=True 让 PolicyEngine 知道它不写数据（read-only 模式下也能放行）。
@tool(read_only=True)
def word_count(text: str) -> str:
    """统计一段文本的字符数与词数。"""
    return f"chars={len(text)} words={len(text.split())}"


# ── 2. 一个按轮次返回固定响应的 Provider（示例用，勿用于生产）────────────
class TurnScriptProvider:
    """第一轮要求调用工具，第二轮返回最终答案。"""

    def __init__(self) -> None:
        self.turns = 0

    async def send(
        self,
        messages: list[object],
        *,
        tools: list[object] | None = None,
        **_kwargs: object,
    ) -> ProviderResponse:
        self.turns += 1
        usage = TokenUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18)
        if self.turns == 1:
            return ProviderResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="word_count", arguments={"text": "hello heagent world"})],
                usage=usage,
                model="turn-script",
                finish_reason="tool_calls",
            )
        # `messages` 是 pydantic 的 Message 列表（不是 dict）：按属性访问
        tool_outputs = [m for m in messages if m.role == "tool"]
        return ProviderResponse(
            content=f"工具返回了 {len(tool_outputs)} 条结果。",
            usage=usage,
            model="turn-script",
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: list[object],
        *,
        tools: list[object] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        # 契约：必须是 async generator（有 yield）；返回 coroutine 的普通函数不符合 Protocol。
        # 本示例只走非流式路径，这里把 send 的结果一次性 yield 出去。
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="turn-script", model="turn-script")


# ── 3. 跑一轮 ───────────────────────────────────────────────────────────
async def main() -> None:
    agent = Agent(TurnScriptProvider())
    answer = await agent.run("统计 'hello heagent world' 的字数")
    print("最终答案:", answer)
    print("直接调用工具:", word_count("hello heagent world"))


if __name__ == "__main__":
    asyncio.run(main())
