"""Stream 策略——流式主循环体（Phase 2 自 loop.py 拆出）。

``AgentLoop.run_stream``（façade）委托至 :func:`stream_run`：每轮 LLM 调用走
``provider.stream`` 逐 chunk 消费，文本片段实时下推为 ``StreamEvent``；工具调用
与最终完成同样以事件产出，支持 steering/follow-up 双层循环。

末尾的 ``noqa: C901`` 是**实测必要**：抽出 ``_inject_*`` / ``_append_*`` / ``finish_run``
后仍为 17 > 15，剩余复杂度全部来自流式分块消费与三处事件 ``yield``——再拆就得让
消费块回传终值（holder 参数或内部事件），那是绕路而非简化。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from heagent.agent.run_lifecycle import (
    _ResumeState,
    checkpoint,
    finish_run,
    init_or_resume,
    on_run_failed,
    persist_and_cache,
)
from heagent.tools.call_summary import summarize_tool_call
from heagent.types import ProviderResponse, StreamEvent, TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.agent.loop import AgentLoop
    from heagent.types import ToolCall

logger = logging.getLogger(__name__)


async def stream_run(  # noqa: C901
    loop: AgentLoop,
    prompt: str,
    *,
    system: str | None = None,
    session_id: str | None = None,
    _resume: _ResumeState | None = None,
) -> AsyncIterator[StreamEvent]:
    """``AgentLoop.run_stream`` 的循环体（行为与拆分前逐行等价）。"""
    init = await init_or_resume(loop, prompt, system, session_id, _resume, stream=True)
    state = init.state
    run_context = init.run_context
    system_content = init.system_content
    accumulated = init.accumulated

    response: ProviderResponse | None = None
    try:
        with loop._runtime_scope(run_context):
            # ---- 外层循环：follow-up 接续 ----
            while True:
                # ---- 内层循环：steering + 工具执行 ----
                while True:
                    # 暂停检查点（协作式）：pause() 后挂在此处，unpause() 继续。
                    await loop._wait_if_paused(run_context)

                    # steering 注入的消息作为用户指令进入下一轮上下文
                    await loop._inject_steering(state)

                    loop._begin_iteration(state, run_context)

                    tools = loop._get_tools()
                    full_content = ""
                    tool_calls: list[ToolCall] = []
                    chunk_usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
                    model = ""
                    finish_reason = ""
                    reasoning_content = ""

                    async for chunk in loop.provider.stream(state.messages, tools=tools or None):
                        if chunk.content:
                            full_content += chunk.content
                            yield StreamEvent(type="text", text=chunk.content)
                        if chunk.tool_calls:
                            tool_calls.extend(chunk.tool_calls)
                        if chunk.usage and chunk.usage.total_tokens > 0:
                            # P1-2 修复：跨 chunk 的 usage 用累加而非覆盖
                            # （非 OpenAI 提供者可能分多个 chunk 分发 usage）
                            chunk_usage = loop._add_usage(chunk_usage, chunk.usage)
                        if chunk.model:
                            model = chunk.model
                        if chunk.finish_reason:
                            finish_reason = chunk.finish_reason
                        if chunk.reasoning_content:
                            reasoning_content += chunk.reasoning_content

                    # 部分 Provider（DeepSeek 等）流式 API 不支持 usage-bearing chunk，
                    # chunk_usage 始终为零 → 用量显示、压缩、窗口重置全部失效。
                    # 此时用本地 token 估算兜底（与 _call_provider / _maybe_window_reset 一致）。
                    if chunk_usage.total_tokens == 0:
                        from heagent.context.tokens import count_tokens, estimate_completion_tokens

                        estimated_prompt = count_tokens(state.messages)
                        estimated_completion = estimate_completion_tokens(full_content, tool_calls)
                        chunk_usage = TokenUsage(
                            prompt_tokens=estimated_prompt,
                            completion_tokens=estimated_completion,
                            total_tokens=estimated_prompt + estimated_completion,
                        )

                    accumulated = loop._add_usage(accumulated, chunk_usage)
                    response = ProviderResponse(
                        content=full_content,
                        tool_calls=tool_calls,
                        usage=chunk_usage,
                        model=model,
                        finish_reason=finish_reason or "stop",
                        reasoning_content=reasoning_content or None,
                    )

                    await loop._maybe_compress(state, run_context, response.usage)
                    loop._append_assistant_message(state, response)

                    # P1-1 修复：流式 delta 累积未能捕获 tool_calls、
                    # 但 finish_reason 指示 tool_calls 时，回退到非流式调用。
                    # 此前不完整消息已追加入 messages，LLM 回退调用看到残缺历史
                    # 并在覆盖后仍不一致；现先 pop 残缺消息、回退成功后再 append。
                    if not response.tool_calls and finish_reason == "tool_calls":
                        state.messages.pop()  # 移除残缺的流式 assistant 消息
                        response = await loop._call_provider(state, run_context=run_context)
                        loop._append_assistant_message(state, response)
                        accumulated = loop._add_usage(accumulated, response.usage)

                    await checkpoint(loop, run_context, prompt=init.prompt, system=system_content, state=state)

                    if not response.tool_calls:
                        break  # 退出内层，进入 follow-up 检查

                    # 先逐个公告「调用什么、作用在哪个对象上」，再执行：
                    # 工具可能耗时数十秒（shell / 联网 / 子 Agent），展示层需要在
                    # 它真正跑起来之前就看到目标；结果事件在执行后补发。
                    for tool_call in response.tool_calls:
                        yield StreamEvent(
                            type="tool_call",
                            tool_name=tool_call.name,
                            tool_target=summarize_tool_call(tool_call.name, tool_call.arguments),
                        )
                    tool_results = await loop._execute_tools(response.tool_calls, state, run_context=run_context)
                    for tool_call, tool_result in zip(response.tool_calls, tool_results, strict=True):
                        # 批次内并发执行，结果按调用顺序返回——带上工具名与成败标志，
                        # 展示层才能把「失败」归因到具体调用（成功不必逐条提示）。
                        yield StreamEvent(
                            type="tool_result",
                            tool_name=tool_call.name,
                            tool_result_content=tool_result.content,
                            tool_error=tool_result.is_error,
                        )
                        loop._append_tool_result(state, tool_result)
                    await checkpoint(loop, run_context, prompt=init.prompt, system=system_content, state=state)
                    await loop._maybe_window_reset(
                        state, run_context, init.prompt, system_content, usage=response.usage
                    )

                # ---- follow-up 检查 ----
                if not await loop._inject_follow_up(state):
                    break  # 无 follow-up，外层退出
                # 有 follow-up → 继续外层循环

            # 真正完成：外层退出后统一收尾
            final_answer = response.content if response is not None else ""
            await finish_run(loop, run_context, init, state, accumulated, final_answer=final_answer)
            yield StreamEvent(type="done", final_answer=final_answer)
    except Exception as exc:
        await on_run_failed(
            loop,
            run_context,
            init.prompt,
            system_content,
            state,
            exc,
            duration_ms=max(int((time.perf_counter() - init.started_perf) * 1000), 0),
        )
        raise
    finally:
        await persist_and_cache(loop, session_id, state, accumulated, run_context)
