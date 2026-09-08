"""Token 估算 — 基于 CJK 感知字符启发式的消息 token 数计算。

提供本地 token 估算能力，无需外部依赖（tiktoken 等），
用于发送前上下文预算管理和日志记录。

估算策略：
  - CJK 字符（中日韩）：~1 token/字符
  - 其他字符（英文/代码等）：~4 字符/token
  - 每条消息结构开销：+3 tokens（角色标签、分隔符）
  - 回复预填充开销：+3 tokens

与 LangChain 的 count_tokens_approximately 策略一致，
适用于所有 LLM provider（OpenAI、Anthropic 等）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heagent.types import Message, TokenUsage, ToolCall

# 消息结构开销常量（与 OpenAI/LangChain 对齐）
_TOKENS_PER_MESSAGE = 3  # 每条消息的角色标签、分隔符开销
_TOKENS_REPLY_PRIMING = 3  # 回复预填充 "<|assistant|/>" 开销
_CHARS_PER_TOKEN = 4.0  # 非CJK文本的字符/token比


def count_tokens(messages: list[Message]) -> int:
    """估算消息列表的总 token 数。

    参数：
        messages: 对话消息列表
    返回：
        估算的 token 总数
    """
    total = 0
    for msg in messages:
        total += _TOKENS_PER_MESSAGE
        # 内容 token
        if msg.content:
            total += _estimate_text_tokens(msg.content)
        # 工具调用 token（序列化参数）
        if msg.tool_calls:
            for tc in msg.tool_calls:
                total += _estimate_text_tokens(tc.name)
                total += _estimate_text_tokens(str(tc.arguments))
        # 工具调用 ID
        if msg.tool_call_id:
            total += _estimate_text_tokens(msg.tool_call_id)
    total += _TOKENS_REPLY_PRIMING
    return total


def estimate_completion_tokens(content: str, tool_calls: list[ToolCall] | None = None) -> int:
    """估算一次 LLM 输出的 token 数（文本 + 工具调用参数）。

    与 :func:`count_tokens` 相同的 CJK 感知启发式，但只算「输出侧」：
    纯文本内容 + 每个工具调用的名称与序列化参数。用于流式 Provider
    不返回 usage 时的 completion token 兜底（避免 out=0 的失真显示）。
    """
    total = _estimate_text_tokens(content) if content else 0
    for call in tool_calls or []:
        total += _estimate_text_tokens(call.name)
        total += _estimate_text_tokens(str(call.arguments))
    return total


def estimate_cost(usage: TokenUsage, model: str, pricing: dict[str, dict[str, float]]) -> float | None:
    """按模型价格估算一次使用的美元成本；无该模型价格则返回 None。

    参数：
        usage: 一次 provider 调用的 token 用量（prompt/completion）。
        model: 实际使用的模型名（``ProviderMetadata.model``）。
        pricing: 价格表 ``{"<model>": {"input": $/M tok, "output": $/M tok}}``。

    返回：美元成本（input + output）；模型不在价格表返回 None。
    """
    prices = pricing.get(model)
    if prices is None:
        return None
    in_cost = usage.prompt_tokens / 1_000_000.0 * prices.get("input", 0.0)
    out_cost = usage.completion_tokens / 1_000_000.0 * prices.get("output", 0.0)
    return in_cost + out_cost


def _estimate_text_tokens(text: str) -> int:
    """估算文本的 token 数，CJK 感知。

    CJK 字符（中日韩统一表意文字）：~1 token/字符
    其他字符（英文、数字、标点、代码）：~4 字符/token
    """
    if not text:
        return 1  # 非空文本至少 1 token
    cjk_count = 0
    other_count = 0
    for ch in text:
        cp = ord(ch)
        # CJK 统一表意文字 + 扩展区 + CJK 兼容 + 假名 + 韩文
        if (
            0x4E00 <= cp <= 0x9FFF  # CJK 统一表意文字
            or 0x3400 <= cp <= 0x4DBF  # CJK 扩展 A
            or 0x20000 <= cp <= 0x2A6DF  # CJK 扩展 B
            or 0x2A700 <= cp <= 0x2B73F  # CJK 扩展 C
            or 0xF900 <= cp <= 0xFAFF  # CJK 兼容表意文字
            or 0x3040 <= cp <= 0x309F  # 平假名
            or 0x30A0 <= cp <= 0x30FF  # 片假名
            or 0xAC00 <= cp <= 0xD7AF  # 韩文音节
        ):
            cjk_count += 1
        else:
            other_count += 1
    # CJK：1 token/字符；其他：4 字符/token；非空文本至少 1 token
    other_tokens = int(other_count / _CHARS_PER_TOKEN) if other_count > 0 else 0
    return max(1, cjk_count + other_tokens)
