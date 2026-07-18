"""上下文窗口重置器 —— token 用量达阈值时清窗重建，配合 resume 跨多段窗口续跑。

与 ``ContextCompressor`` **互斥**（D3）：compressor 在原位摘要、保留最近 N 条原文；
本模块更激进，把整段对话压成一条摘要 + 原始 task + 续跑提示，清窗后由
``AgentLoop.resume()`` 用**同一 run_id** 跨多段 context window 续跑。摘要提示词与
compressor 保持一致，确保摘要风格统一。

设计要点：
  - ``should_trigger``：``token_count / max_tokens >= threshold``（默认 60%）。
  - ``reset``：摘要对话 → 写 ``run_context.metadata['progress_summary']`` 与
    ``['segment']``（metadata 跨清窗存活）→ 返回清爽的续跑消息窗口。
  - 不重置 iteration / accumulated（防绕预算；二者由 ``AgentLoop`` 持有）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from heagent.types import Message, ProviderResponse, Role

if TYPE_CHECKING:
    from heagent.engine.context import RunContext
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# 摘要提示词（与 ContextCompressor 保持一致，统一摘要风格）
DEFAULT_SUMMARY_PROMPT = (
    "Summarize the following conversation so far in a concise paragraph. "
    "Preserve key facts, decisions, and any important context."
)

# 续跑提示：注入清窗后的新窗口，引导模型基于摘要继续、不重复已完成步骤
RESUME_HINT = (
    "The previous context window was summarized and reset. "
    "Continue the task using the progress summary above; "
    "do not repeat steps that the summary description already describes as completed."
)

# 摘要输入字符硬上限（~8000 tokens，保守适配任意 LLM 上下文窗口）。
# 从末尾截断（最新消息更重要），超出部分不送入摘要请求。
_MAX_SUMMARY_CHARS = 32000


class WindowResetConfig(BaseModel):
    """窗口重置配置。"""

    threshold: float = Field(default=0.6, ge=0.0, le=1.0)  # 触发重置的 token 使用率阈值
    summary_prompt: str = DEFAULT_SUMMARY_PROMPT


class WindowReset:
    """token 阈值触发的上下文窗口重置器。"""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        config: WindowResetConfig | None = None,
    ) -> None:
        self.provider = provider
        self.config = config or WindowResetConfig()

    def should_trigger(self, *, token_count: int, max_tokens: int) -> bool:
        """token 使用率达阈值即触发；max_tokens 非正时永不触发。"""
        if max_tokens <= 0:
            return False
        return token_count / max_tokens >= self.config.threshold

    async def reset(
        self,
        *,
        run_context: RunContext,
        original_prompt: str,
        messages: list[Message],
    ) -> list[Message]:
        """摘要当前对话 → 更新 metadata → 返回清窗后的续跑消息列表。

        ``metadata['progress_summary']`` 与 ``['segment']`` 跨清窗存活，
        ``AgentLoop.resume()`` 据此重建续跑窗口。system 消息（人设/技能等）
        不参与摘要，由 ``AgentLoop`` 在下一轮重新注入。
        """
        conversation = [m for m in messages if m.role != Role.SYSTEM]
        summary = await self._summarize(conversation)
        run_context.metadata["progress_summary"] = summary
        run_context.metadata["segment"] = int(run_context.metadata.get("segment", 0)) + 1
        return self.build_resume_messages(original_prompt=original_prompt, summary=summary)

    @staticmethod
    def build_resume_messages(*, original_prompt: str, summary: str) -> list[Message]:
        """构造清窗后的续跑消息窗口（reset 与 resume 共用同一结构）。"""
        return [
            Message(role=Role.SYSTEM, content=f"[Progress summary]\n{summary}"),
            Message(role=Role.USER, content=original_prompt),
            Message(role=Role.SYSTEM, content=RESUME_HINT),
        ]

    async def _summarize(self, messages: list[Message]) -> str:
        """调用 provider 生成摘要（复用 compressor 的提示词风格）。

        从末尾截断保护：当对话极长时，仅保留最近的 ~32k 字符送入摘要请求，
        避免摘要请求自身超出 LLM 上下文窗口（与 ``ContextCompressor._summarize``
        的截断保护对齐）。
        """
        # 从末尾累积消息行，使最近的对话内容优先保留
        lines: list[str] = []
        total_chars = 0
        for m in reversed(messages):
            if not m.content:
                continue
            line = f"{m.role.value}: {m.content}"
            if total_chars + len(line) > _MAX_SUMMARY_CHARS:
                logger.debug(
                    "WindowReset summary input truncated at ~%d chars (limit=%d)",
                    total_chars,
                    _MAX_SUMMARY_CHARS,
                )
                break
            lines.insert(0, line)
            total_chars += len(line)

        if not lines:
            return "(conversation content omitted - too large to summarize for window reset)"

        prompt = "\n".join(lines)
        try:
            resp: ProviderResponse = await self.provider.send(
                [Message(role=Role.USER, content=f"{self.config.summary_prompt}\n\n{prompt}")]
            )
        except Exception:
            # 摘要失败时不抛异常、不中断主循环：返回占位符，
            # 下次迭代若 token 仍超阈值会再次尝试重置。
            logger.exception("WindowReset summary generation failed; returning placeholder")
            return "(summary unavailable - window reset attempted but LLM call failed)"

        return resp.content
