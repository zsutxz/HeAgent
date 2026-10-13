"""BaseProvider 协议 — LLM Provider 的统一接口定义。

使用 typing.Protocol 实现结构化子类型（鸭子类型），
Provider 无需继承此类，只需实现 send/stream/get_metadata 三个方法即可。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.pub.types import Message, ProviderResponse, ToolSchema


def parse_tool_arguments(raw: str) -> dict[str, object]:
    """把 tool call 的 ``arguments`` 字符串反序列化为参数 dict。

    各 provider 的统一口径：空串 / 非 JSON / 非 JSON 对象的畸形输入一律退化为空
    dict，绝不抛错——上游服务器偶发坏的 arguments 不应中断整轮对话。
    """
    if not raw:
        return {}
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class ProviderMetadata(BaseModel):
    """Provider 能力描述元数据。"""

    name: str  # Provider 名称（如 openai, anthropic）
    model: str  # 当前使用的模型名称
    supports_streaming: bool = False  # 是否支持流式输出
    supports_tools: bool = False  # 是否支持 function calling


class ProviderSummary(BaseModel):
    """SwitchableProvider.info() 返回的单个 provider 摘要（/model 列表展示用）。

    跨模块数据用 Pydantic 模型（禁原始 dict），使 CLI 调用方可类型安全地属性访问。
    """

    model: str
    streaming: bool
    tools: bool
    active: bool


@runtime_checkable
class BaseProvider(Protocol):
    """LLM Provider 统一协议。

    所有 Provider（OpenAI/Anthropic/Chain）必须实现这三个方法。
    通过 @runtime_checkable 支持 isinstance() 检查。
    无需继承——只要实现了这些方法即被视为合法 Provider。
    """

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """单次调用 LLM，返回完整响应。"""
        ...

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式调用 LLM，逐步返回响应片段。

        声明为普通函数返回 AsyncIterator（不带 ``async``）——async generator function
        的类型签名即「调用返回 AsyncIterator」（非 coroutine），这样 Protocol 才能与
        各 provider 的 ``async def stream``（含 yield）实现结构化匹配。
        """
        ...

    def get_metadata(self) -> ProviderMetadata:
        """返回 Provider 的能力描述。"""
        ...
