"""上下文压缩器 — 当 Token 用量接近上限时，通过 LLM 摘要旧消息。

压缩策略：
  1. 将消息分为三组：系统消息 / 旧消息 / 最近 N 条消息
  2. 调用 LLM 对旧消息生成摘要
  3. 返回：[系统消息, 摘要消息, 最近消息]

触发条件：token_count / max_tokens >= threshold（默认 80%）

已接入 AgentLoop：每轮响应后按 token 使用率检查，超阈值时摘要旧消息释放空间。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from heagent.context.sidecall import send_accounted
from heagent.context.tokens import estimate_text_tokens
from heagent.pub.types import Message, ProviderResponse, Role

if TYPE_CHECKING:
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# 摘要提示词：要求**结构化**四段，而不是「一段话」。
#
# 旧版只要求 "concise paragraph…preserve key facts"——实测会把「改过哪些文件、还剩什么
# 没做」这类**可重放状态**揉成模糊叙述，压缩后模型接着干时容易重做已完成的改动或丢掉
# 未完成的步骤。四段制把可重放状态显式化，并要求标识符/路径/命令/报错**逐字保留**。
# 公开名：window_reset 复用同一份结构化提示词，避免两套上下文策略各写一份摘要指令而
# 漂移（历史上「与 compressor 保持一致」只靠注释维系，改一处另一处不会跟着变）。
STRUCTURED_SUMMARY_PROMPT = (
    "Summarize the conversation so far for your own future use. Reply with exactly these "
    "four sections, in this order, and nothing else:\n"
    "## Goal\nThe user's current objective, in one or two sentences.\n"
    "## Changed files\nEvery file created, edited or deleted so far, one line each: path — "
    "what changed (function/section level). Write 'none' if nothing was changed.\n"
    "## Todo\nWhat still remains to be done, in the order it should be done. "
    "Write 'none' if the work is complete.\n"
    "## Constraints and failures\n"
    "Decisions that must keep holding, plus commands/tests already run with their outcome "
    "and every error already encountered and how it was resolved.\n"
    "Keep identifiers, file paths, commands and error messages verbatim; do not invent "
    "details that are not in the conversation."
)

# 摘要请求本身的安全缓冲区：预留足够的 token 空间给摘要提示词 + 回复
# （提示词约 30 tokens，回复预留 512 tokens，简单旧消息不会用完）
_SUMMARY_SAFETY_MARGIN = 1024  # tokens，为摘要提示词 + LLM 回复保底

# 进度回调签名：(percent, message)。压缩器不认识任何注册表/传输层，只调用这个可调用对象；
# 由上层（入口层）绑定到具体实现，因此 context 层不反向依赖 engine / network。
ProgressReporter = Callable[[int, str], None]

# 环境式进度钩子：生产者在**自己的一次压缩调用**外层用 :func:`compression_progress` 绑定上报器，
# 压缩器在该上下文内取得它。用环境变量而非 ``compress`` 形参，是为保持该方法的既有签名契约
# （它被多处替换实现与测试替身调用，加形参会让这些实现静默失配）；钩子缺席时压缩行为完全不变。
_PROGRESS: ContextVar[ProgressReporter | None] = ContextVar("heagent_compressor_progress", default=None)

# 上报区间：压缩内部把 0–100 分给三段——切分 10、摘要 20–90、组装完成 100。
_PERCENT_SPLIT = 10
_PERCENT_SUMMARY_START = 20
_PERCENT_SUMMARY_END = 90
_PERCENT_DONE = 100


@contextmanager
def compression_progress(reporter: ProgressReporter | None) -> Iterator[None]:
    """把 ``reporter`` 绑定为**当前上下文**内压缩调用的进度上报器（可嵌套，退出即还原）。

    只影响本上下文（``ContextVar`` 随任务复制），不污染并发中的其它压缩调用。
    """
    token = _PROGRESS.set(reporter)
    try:
        yield
    finally:
        _PROGRESS.reset(token)


def _report(progress: ProgressReporter | None, percent: int, message: str) -> None:
    """调用进度回调；回调自身出错只记日志，**绝不**影响压缩结果。"""
    if progress is None:
        return
    try:
        progress(percent, message)
    except Exception:
        logger.debug("Progress reporter failed at percent=%d", percent, exc_info=True)


def render_message_for_summary(message: Message, *, tool_result_content: bool) -> list[str]:
    """把单条消息渲染成摘要请求用的文本片段（角色前缀 + tool_call + tool_result）。

    **摘要输入的唯一序列化点**：``ContextCompressor._summarize`` 与
    ``WindowReset._summarize`` 曾各持一份逐字副本（2026-09-15 合并，此前仅靠注释
    「与 … 保持一致」手工同步）。两者压缩的是同一份对话的两条路径，模型看到的格式不该因
    走哪条路径而变。

    组装顺序有讲究（P1-1 修复）：先 ``content``（含角色前缀）、再逐条 ``tool_call``，避免
    content 与 tool_calls 内嵌 content 重复；``tool_result`` 插到头部作为该消息的标识。

    ``tool_result_content`` 决定 TOOL 消息的正文挂在哪一行（这是两处调用点唯一的有意差异）；
    正文始终**只写一次**：
      - ``False``（compressor）—— 正文挂角色行 ``tool: <content>``，标识行只写
        ``tool_result(<id>):``。其返回值同时充当 token 估算输入，须与
        :func:`heagent.context.tokens.count_tokens` 对 TOOL 消息的口径对齐。
      - ``True``（window reset）—— 正文并入标识行 ``tool_result(<id>): <content>``，不再另写
        角色行。

    2026-09-15 修复：``True`` 分支此前「标识行带正文 + 角色行再带一次」，工具正文被重复计入
    摘要输入（既浪费 token，也让模型读到重复内容）。

    返回空列表表示该消息无可用内容，调用方应跳过它（不写入摘要）。
    """
    parts: list[str] = []
    tool_result_marker = message.role == Role.TOOL and bool(message.tool_call_id)
    # 工具结果的正文只写一次：并入标识行（True）或留在角色行（False），二者不并用。
    if message.content and not (tool_result_marker and tool_result_content):
        parts.append(f"{message.role.value}: {message.content}")
    if message.tool_calls:
        for call in message.tool_calls:
            parts.append(f"tool_call: {call.name}({json.dumps(call.arguments, ensure_ascii=False)})")
    if tool_result_marker:
        suffix = f" {message.content or ''}" if tool_result_content else ""
        parts.insert(0, f"tool_result({message.tool_call_id}):{suffix}")
    return parts


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

        # 进度只在**真正开始压缩**时上报：未超阈值 / 消息太少等提前返回路径一次都不报
        # （那不算「进行中的任务」，调用方的 scope 会按正常路径自己收尾）。
        progress = _PROGRESS.get()
        _report(progress, _PERCENT_SPLIT, "splitting messages")

        # 调用 LLM 生成旧消息摘要（带截断保护，防超出上下文窗口）
        summary = await self._summarize(old, max_tokens=max_tokens, progress=progress)

        # 组装压缩后的消息列表
        compressed = [
            *system_msgs,
            Message(role=Role.USER, content=f"[Conversation summary]\n{summary}"),
            *recent,
        ]
        logger.info(
            "Compressed %d messages into summary (threshold=%.0f%%)",
            len(old),
            self.threshold * 100,
        )
        _report(progress, _PERCENT_DONE, "compression finished")
        return compressed

    async def _summarize(
        self,
        messages: list[Message],
        max_tokens: int = 0,
        *,
        progress: ProgressReporter | None = None,
    ) -> str:
        """调用 LLM 对旧消息生成摘要，带截断保护。

        如果旧消息的估算 token 数超过安全阈值（``effective_limit - SAFETY_MARGIN``），
        会从末尾截断保留最重要的部分，避免摘要请求本身超出上下文窗口。
        ``effective_limit`` 取 ``min(max_tokens, self.max_summary_tokens)``（P1-4 修复：
        激活 max_summary_tokens 死字段，防止摘要输入膨胀至 ~127K token 导致质量劣化）。

        当 ``effective_limit <= SAFETY_MARGIN`` 导致安全空间不足以承载摘要请求本身时，
        不调 LLM 直接返回占位符——避免浪费一次注定失败的 API 调用。

        参数：
            messages: 需要摘要的旧消息列表
            max_tokens: 原始上下文窗口上限；为 0 时不截断（纯兼容）
            progress: 可选进度回调，按「已处理的输入条目数 / 总数」在 20–90 之间线性上报
        返回：
            摘要文本
        """
        _report(progress, _PERCENT_SUMMARY_START, f"summarizing {len(messages)} messages")

        # effective_limit：min(window_limit, summary_input_limit)，收紧摘要输入上限
        effective_limit = min(max_tokens, self.max_summary_tokens) if max_tokens > 0 else self.max_summary_tokens
        safety_limit = effective_limit - _SUMMARY_SAFETY_MARGIN

        # 安全空间不足以承载摘要请求本身 → 不调 LLM，直接返回占位符。
        # 调用方（compress）下次迭代若 token 仍超阈值会再次进入此地。
        if effective_limit > 0 and safety_limit <= 0:
            logger.warning(
                "Context window too small for summarization (effective_limit=%d, safety_margin=%d)",
                effective_limit,
                _SUMMARY_SAFETY_MARGIN,
            )
            _report(progress, _PERCENT_SUMMARY_END, "summarization skipped: context window too small")
            return "(conversation content omitted - context window too small to summarize by LLM)"

        prompt_parts: list[str] = []
        estimated = 0
        per_message_overhead = 3  # 每条消息角色标签开销
        should_truncate = effective_limit > 0 and safety_limit > 0

        # 从末尾向前取消息（最新消息最重要），直到接近安全阈值（或不截断时全部取出）
        total = len(messages)
        for index, m in enumerate(reversed(messages), start=1):
            # 组装走共用序列化（与 WindowReset 同一实现）；tool_result 只留标识符，
            # 因其返回值同时用于 token 估算，须与 tokens.count_tokens 的 TOOL 口径对齐。
            parts = render_message_for_summary(m, tool_result_content=False)
            if not parts:
                continue
            text = "\n".join(parts)

            msg_tokens = per_message_overhead + estimate_text_tokens(text)
            # 每条 tool_call 附加 JSON 结构开销（大括号、引号、逗号、函数调用包裹等）
            if m.tool_calls:
                msg_tokens += len(m.tool_calls) * 30
            if should_truncate and estimated + msg_tokens > safety_limit:
                # 超过安全阈值——此条及更早的消息被截断
                logger.debug(
                    "Summary input truncated at ~%d tokens (effective=%d, safety=%d)",
                    estimated,
                    effective_limit,
                    safety_limit,
                )
                break
            estimated += msg_tokens
            prompt_parts.insert(0, text)  # 因为是从后向前遍历，插到头部恢复原序
            # 分段循环即进度来源：百分比只随「已确定的输入条目数」前进，单调不减。
            _report(
                progress,
                _PERCENT_SUMMARY_START + (_PERCENT_SUMMARY_END - _PERCENT_SUMMARY_START) * index // total,
                f"summarizing {index}/{total} messages",
            )

        # 如果一条消息都没保留，则强制包含最近一条（避免无意义的占位符）
        if not prompt_parts and messages:
            m = messages[-1]  # 至少保留最近消息
            text = f"{m.role.value}: {m.content}" if m.content else "(empty)"
            prompt_parts.append(text)

        # 极少数情况：输入完全为空（不应发生）
        if not prompt_parts:
            _report(progress, _PERCENT_SUMMARY_END, "summarization input is empty")
            return "(conversation content omitted - too large to summarize)"

        prompt = "\n".join(prompt_parts)
        try:
            # 残余非流式调用：大上下文经代理中转（如 Cloudflare）有读超时风险，
            # 失败已被下方 except 吞为占位符，不致崩；如需根治可切 provider.stream。
            resp: ProviderResponse = await send_accounted(
                self.provider,
                [Message(role=Role.USER, content=f"{STRUCTURED_SUMMARY_PROMPT}\n\n{prompt}")],
                caller="compressor",
            )
        except Exception:
            # 摘要失败时不抛异常、不中断主循环：返回简短占位符，
            # 下次迭代若 token 仍超阈值会再次尝试压缩。
            logger.exception("Summary generation failed; returning placeholder")
            _report(progress, _PERCENT_SUMMARY_END, "summarization failed")
            return "(summary unavailable - conversation history preserved in recent messages)"

        _report(progress, _PERCENT_SUMMARY_END, "summary ready")
        return resp.content
