"""上下文运行时策略——迭代控制、消息追加与压缩/窗口重置（Phase 2 自 loop.py 拆出）。

承载内层循环每轮的上下文侧步骤：迭代计数与硬上限（``begin_iteration``）、
assistant/tool 消息追加、token 用量叠加、就地压缩（``maybe_compress``）与窗口重置
（``maybe_window_reset``）。``AgentLoop`` 保留同名方法委托至此。

依赖方向：运行期只依赖 ``run_lifecycle``（checkpoint）与 ``heagent.pub.types``/``engine``
类型，不导入 ``heagent.agent.loop``（仅 TYPE_CHECKING）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.agent.run_lifecycle import AgentState, checkpoint
from heagent.pub.exceptions import BudgetExceeded
from heagent.pub.types import Message, ProviderResponse, Role, TokenUsage, ToolResult

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.engine import RunContext

logger = logging.getLogger(__name__)


def begin_iteration(loop: AgentLoop, state: AgentState, run_context: RunContext) -> None:
    """推进迭代计数、发布 iteration_started 事件，并强制迭代硬上限。

    每轮循环入口调用：iteration+1 → touch 上下文 → 发事件 → 超过 max_iterations
    即抛 ``BudgetExceeded``（显性失败，防止失控循环）。``run``/``run_stream`` 共用。
    """
    state.iteration += 1
    run_context.touch(iteration=state.iteration)
    loop._emit("iteration_started", run_context=run_context)
    if state.iteration > state.max_iterations:
        raise BudgetExceeded(f"Exceeded {state.max_iterations} iterations without final answer")


def append_assistant_message(loop: AgentLoop, state: AgentState, response: ProviderResponse) -> None:
    """把助手回复追加进上下文（``run``/``run_stream`` 共用的循环步骤）。

    含流式回退路径在内，本模块原有三处各写一份逐字段相同的 ``Message(role=ASSISTANT, ...)``。

    同时回填 ``loop.last_model``：两条运行路径（非流式 / 流式）都经此处落消息，故这里
    是「本次运行实际用了哪个模型」的**唯一**记录点——共享 provider 的路由状态会被并发
    运行覆盖，消费方不能依赖它（见 ``AgentLoop.last_model`` 的说明）。
    """
    if response.model:
        loop.last_model = response.model
    state.messages.append(
        Message(
            role=Role.ASSISTANT,
            content=response.content,
            tool_calls=response.tool_calls or None,
            reasoning_content=response.reasoning_content,
        )
    )


def append_tool_result(loop: AgentLoop, state: AgentState, result: ToolResult) -> None:
    """把单条工具结果追加进上下文（``run``/``run_stream`` 共用）。

    逐条而非整批：流式路径需在每个结果事件 ``yield`` **之后**才落消息，
    以保持「事件先于消息」的先后与重构前一致。
    """
    state.messages.append(Message(role=Role.TOOL, content=result.content, tool_call_id=result.tool_call_id))


def add_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
    """把两份 token 用量计数逐字段相加，返回新的 ``TokenUsage``（不可变叠加）。"""
    return TokenUsage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
    )


async def maybe_compress(
    loop: AgentLoop,
    state: AgentState,
    run_context: RunContext,
    usage: TokenUsage | None,
) -> None:
    """就地压缩上下文（compressor 启用时）。

    compressor 仅在返回新列表时才替换（用 ``is`` 判同避免无谓替换），
    同时发布 context_compressed 事件。``usage`` 为空则跳过。
    """
    if not loop.compressor or not usage:
        return
    compressed = await loop.compressor.compress(
        state.messages,
        token_count=usage.total_tokens,
        max_tokens=loop._runtime.max_context_tokens,
    )
    if compressed is not state.messages:
        before = len(state.messages)
        state.messages = compressed
        logger.info("Context compressed: %d -> %d messages", before, len(state.messages))
        loop._emit(
            "context_compressed",
            run_context=run_context,
            details={"before": before, "after": len(state.messages)},
        )


async def maybe_window_reset(
    loop: AgentLoop,
    state: AgentState,
    run_context: RunContext,
    prompt: str,
    system_content: str | None,
    *,
    usage: TokenUsage | None = None,
) -> None:
    """窗口重置（window_reset 启用时）。

    达到 token 阈值时把长对话折叠成「原始 prompt + 进度摘要」的新窗口
    （segment 计数 +1），换段继续，避免上下文溢出。

    P1-3 修复：取 LLM 上报的 ``usage.total_tokens``（调用**前**的输入 token 数）
    与 ``count_tokens(state.messages)``（调用**后**、含工具结果的 token 估算）
    的**最大值**作为触发判断依据——纠正此前仅用 usage（滞后一轮）的偏差。
    """
    if not loop.window_reset:
        return
    from heagent.context.tokens import count_tokens

    # P1-3: usage reflects pre-call input tokens; count_tokens reflects current msg list
    # (including just-appended tool results); take max to avoid one-round lag.
    llm_tokens = usage.total_tokens if usage else 0
    current_tokens = max(llm_tokens, count_tokens(state.messages))
    if not loop.window_reset.should_trigger(
        token_count=current_tokens,
        max_tokens=loop._runtime.max_context_tokens,
    ):
        return
    before = len(state.messages)
    state.messages = await loop.window_reset.reset(
        run_context=run_context,
        original_prompt=prompt,
        messages=state.messages,
    )
    logger.info(
        "Window reset: %d -> %d messages (segment=%s)",
        before,
        len(state.messages),
        run_context.metadata.get("segment"),
    )
    loop._emit(
        "window_reset",
        run_context=run_context,
        details={"before": before, "after": len(state.messages)},
    )
    await checkpoint(loop, run_context, prompt=prompt, system=system_content, state=state)
