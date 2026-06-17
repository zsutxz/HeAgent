"""上下文压缩器 — 当 Token 用量接近上限时，通过 LLM 摘要旧消息。

压缩策略：
  1. 将消息分为三组：系统消息 / 旧消息 / 最近 N 条消息
  2. 调用 LLM 对旧消息生成摘要
  3. 返回：[系统消息, 摘要消息, 最近消息]

触发条件：token_count / max_tokens >= threshold（默认 80%）

当前状态：已实现但未接入 AgentLoop。
"""

from __future__ import annotations

import logging

from heagent.providers.base import BaseProvider
from heagent.types import Message, ProviderResponse, Role

logger = logging.getLogger(__name__)

# 摘要提示词：指导 LLM 提取关键信息
_DEFAULT_PROMPT = (
    "Summarize the following conversation so far in a concise paragraph. "
    "Preserve key facts, decisions, and any important context."
)


class ContextCompressor:
    """上下文压缩器，使用 LLM 摘要旧的对话消息以释放 Token 空间。"""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        threshold: float = 0.8,   # 触发压缩的 Token 使用率阈值
        keep_recent: int = 4,     # 保留最近 N 条消息不参与压缩
    ) -> None:
        self.provider = provider
        self.threshold = threshold
        self.keep_recent = keep_recent

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

        # 分割：旧消息（需要摘要）/ 最近消息（保留原文）
        old = conversation[: -self.keep_recent]
        recent = conversation[-self.keep_recent :]

        # 调用 LLM 生成旧消息摘要
        summary = await self._summarize(old)

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

    async def _summarize(self, messages: list[Message]) -> str:
        """调用 LLM 对旧消息生成摘要。"""
        prompt = "\n".join(f"{m.role.value}: {m.content}" for m in messages if m.content)
        resp: ProviderResponse = await self.provider.send(
            [Message(role=Role.USER, content=f"{_DEFAULT_PROMPT}\n\n{prompt}")]
        )
        return resp.content
