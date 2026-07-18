"""上下文压缩器 — 当 Token 用量接近上限时，通过 LLM 摘要旧消息。

压缩策略：
  1. 将消息分为三组：系统消息 / 旧消息 / 最近 N 条消息
  2. 调用 LLM 对旧消息生成摘要
  3. 返回：[系统消息, 摘要消息, 最近消息]

触发条件：token_count / max_tokens >= threshold（默认 80%）

已接入 AgentLoop：每轮响应后按 token 使用率检查，超阈值时摘要旧消息释放空间。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.types import Message, ProviderResponse, Role

if TYPE_CHECKING:
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# 摘要提示词：指导 LLM 提取关键信息
_DEFAULT_PROMPT = (
    "Summarize the following conversation so far in a concise paragraph. "
    "Preserve key facts, decisions, and any important context."
)

# 摘要请求本身的安全缓冲区：预留足够的 token 空间给摘要提示词 + 回复
# （提示词约 30 tokens，回复预留 512 tokens，简单旧消息不会用完）
_SUMMARY_SAFETY_MARGIN = 1024  # tokens，为摘要提示词 + LLM 回复保底


class ContextCompressor:
    """上下文压缩器，使用 LLM 摘要旧的对话消息以释放 Token 空间。"""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        threshold: float = 0.8,  # 触发压缩的 Token 使用率阈值
        keep_recent: int = 4,  # 保留最近 N 条消息不参与压缩
        max_summary_tokens: int = 4096,  # 摘要输入截断上限
    ) -> None:
        self.provider = provider
        self.threshold = threshold
        self.keep_recent = keep_recent
        self.max_summary_tokens = max_summary_tokens

    async def compress(
        self,
        messages: list[Message],
        token_count: int,
        max_tokens: int,
    ) -> list[Message]:
        """根据 Token 用量决定是否压缩消息列表。

        参数：
            messages: 当前对话消息列表
            token_count: 已使用的 Token 数
            max_tokens: 最大 Token 上限
        返回：
            压缩后的消息列表（未超阈值则原样返回）
        """
        # 安全检查：max_tokens 为 0 或未超阈值 → 不压缩
        if max_tokens == 0:
            return messages
        if token_count / max_tokens < self.threshold:
            return messages

        # 分离消息：系统消息 / 对话消息
        system_msgs: list[Message] = []
        conversation: list[Message] = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system_msgs.append(m)
            else:
                conversation.append(m)

        # 消息太少不值得压缩
        if len(conversation) <= self.keep_recent:
            return messages

        # 分割：旧消息（需要摘要）/ 最近消息（保留原文）。
        # 切分点必须落在「安全边界」上：recent 的首条不能是 TOOL——否则其对应的
        # assistant(tool_calls) 已落入 old 被摘要抹平，recent 里出现无主 tool 结果，
        # OpenAI 会以 400「tool must follow tool_calls」拒绝。故把 recent 开头的孤儿
        # TOOL 并入 old 一同摘要（内容进入摘要、不静默丢弃，既保压缩意图又不破坏不变量）。
        # 「越过开头 TOOL」即足：AgentLoop 固定先追加 assistant(tool_calls)、再紧随追加其全部
        # TOOL 结果（见 loop.py，无交错），故 recent 中段不会有无主 TOOL；若日后有中间件在
        # 二者间插入消息，该前提失效，此处须重新评估。
        split = len(conversation) - self.keep_recent
        while split < len(conversation) and conversation[split].role == Role.TOOL:
            split += 1
        # 极端情形：recent 全是 TOOL（无可安全保留的窗口）→ 放弃本轮压缩，原样返回。
        if split >= len(conversation):
            return messages
        old = conversation[:split]
        recent = conversation[split:]

        # 调用 LLM 生成旧消息摘要（带截断保护，防超出上下文窗口）
        summary = await self._summarize(old, max_tokens=max_tokens)

        # 组装压缩后的消息列表
        compressed = [
            *system_msgs,
            Message(role=Role.SYSTEM, content=f"[Conversation summary]\n{summary}"),
            *recent,
        ]
        logger.info(
            "Compressed %d messages into summary (threshold=%.0f%%)",
            len(old),
            self.threshold * 100,
        )
        return compressed

    async def _summarize(self, messages: list[Message], max_tokens: int = 0) -> str:
        """调用 LLM 对旧消息生成摘要，带截断保护。

        如果旧消息的估算 token 数超过安全阈值（``max_tokens - SAFETY_MARGIN``），
        会从末尾截断保留最重要的部分，避免摘要请求本身超出上下文窗口。

        当 ``max_tokens <= SAFETY_MARGIN`` 导致安全空间不足以承载摘要请求本身时，
        不调 LLM 直接返回占位符——避免浪费一次注定失败的 API 调用。

        参数：
            messages: 需要摘要的旧消息列表
            max_tokens: 原始上下文窗口上限；为 0 时不截断（纯兼容）
        返回：
            摘要文本
        """
        # 安全空间不足以承载摘要请求本身 → 不调 LLM，直接返回占位符。
        # 调用方（compress）下次迭代若 token 仍超阈值会再次进入此地。
        safety_limit = max_tokens - _SUMMARY_SAFETY_MARGIN
        if max_tokens > 0 and safety_limit <= 0:
            logger.warning(
                "Context window too small for summarization (max_tokens=%d, safety_margin=%d)",
                max_tokens,
                _SUMMARY_SAFETY_MARGIN,
            )
            return "(conversation content omitted - context window too small to summarize by LLM)"

        prompt_parts: list[str] = []
        estimated = 0
        per_message_overhead = 3  # 每条消息角色标签开销
        should_truncate = max_tokens > 0 and safety_limit > 0

        # 从末尾向前取消息（最新消息最重要），直到接近安全阈值（或不截断时全部取出）
        for m in reversed(messages):
            text = f"{m.role.value}: {m.content}" if m.content else ""
            if not text and not m.tool_calls:
                continue
            if m.tool_calls:
                for tc in m.tool_calls:
                    tool_text = f"tool_call: {tc.name}({tc.arguments})"
                    if m.content:
                        tool_text = f"{m.content}\n{tool_text}"
                    text = tool_text if not text else f"{text}\n{tool_text}"

            msg_tokens = per_message_overhead + _estimate_tokens(text)
            if should_truncate and estimated + msg_tokens > safety_limit:
                # 超过安全阈值——此条及更早的消息被截断
                logger.debug(
                    "Summary input truncated at ~%d tokens (max=%d, safety=%d)",
                    estimated,
                    max_tokens,
                    safety_limit,
                )
                break
            estimated += msg_tokens
            prompt_parts.insert(0, text)  # 因为是从后向前遍历，插到头部恢复原序

        # 如果一条消息都没保留，则强制包含最近一条（避免无意义的占位符）
        if not prompt_parts and messages:
            m = messages[-1]  # 至少保留最近消息
            text = f"{m.role.value}: {m.content}" if m.content else "(empty)"
            prompt_parts.append(text)

        # 极少数情况：输入完全为空（不应发生）
        if not prompt_parts:
            return "(conversation content omitted - too large to summarize)"

        prompt = "\n".join(prompt_parts)
        try:
            resp: ProviderResponse = await self.provider.send(
                [Message(role=Role.USER, content=f"{_DEFAULT_PROMPT}\n\n{prompt}")]
            )
        except Exception:
            # 摘要失败时不抛异常、不中断主循环：返回简短占位符，
            # 下次迭代若 token 仍超阈值会再次尝试压缩。
            logger.exception("Summary generation failed; returning placeholder")
            return "(summary unavailable - conversation history preserved in recent messages)"

        return resp.content


def _estimate_tokens(text: str) -> int:
    """快速 token 估算（不含消息结构开销）。"""
    cjk = sum(
        1
        for ch in text
        if (
            0x4E00 <= (cp := ord(ch)) <= 0x9FFF
            or 0x3400 <= cp <= 0x4DBF
            or 0x3040 <= cp <= 0x309F
            or 0x30A0 <= cp <= 0x30FF
            or 0xAC00 <= cp <= 0xDFFF
        )
    )
    other = len(text) - cjk
    return max(1, cjk + int(other / 4.0))
