"""Run 生命周期策略——初始化、主循环体、终结与持久化（Phase 2 自 loop.py 拆出）。

本模块承载 ``run()`` 的完整生命周期：状态数据类（``AgentState``/``_RunInit``/
``_ResumeState``）、初始化分叉（恢复 vs 全新）、非流式主循环体、成功/失败终结与
``run_store`` 检查点。``AgentLoop``（façade）保留同名方法委托至此；策略独立可测
（构造最小 loop 替身即可驱动）。

依赖方向：本模块**运行期不得导入** ``heagent.agent.loop``（loop façade 运行期导入
本模块，反向运行期导入即成环）；``AgentLoop`` 仅作 TYPE_CHECKING 类型引用。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from heagent.engine import RunContext, RunStatus
from heagent.engine.hooks import SESSION_END, SESSION_START
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolResult

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """单次循环执行的可变内部状态（dataclass：轻量、可变、无需序列化）。"""

    messages: list[Message] = field(default_factory=list)  # 当前对话消息列表（SYSTEM/USER/ASSISTANT/TOOL）
    iteration: int = 0  # 当前已执行的迭代轮数（每轮 +1）
    max_iterations: int = 50  # 迭代硬上限，超过即抛 BudgetExceeded
    results: list[ToolResult] = field(default_factory=list)  # 本轮累计的工具执行结果


@dataclass
class _ResumeState:
    """``resume()`` 注入 ``run()`` 的预构建状态（私有，恢复专用）。

    ``resume()`` 从持久化快照重建出一份「上下文 + 进度」，绕过 ``run()`` 正常的
    会话/系统提示词初始化分支，直接带着旧 run_id 继续跑。
    """

    state: AgentState  # 重建后的循环状态（含历史消息与迭代计数）
    run_context: RunContext  # 沿用的原运行上下文（保留原 run_id）
    prompt: str  # 原 prompt（恢复时仍需作为系统提示词注入的依据）
    system: str | None  # 原系统提示词


@dataclass(slots=True)
class _RunInit:
    """``run()`` / ``run_stream()`` 共享的初始化产物。

    与 ``_ResumeState`` 互为双生：``init_or_resume`` 输出统一结构，
    循环体据此进入主循环，不再重复分支逻辑。
    """

    state: AgentState
    run_context: RunContext
    system_content: str | None
    accumulated: TokenUsage
    prompt: str  # 原始 prompt（恢复时可能已替换为 _resume.prompt）


_DELEGATION_DETAIL_KEYS = ("kind", "role", "workflow_step", "workflow_story", "goal_id", "goal_kind")


def _delegation_details(run_context: RunContext) -> dict[str, Any]:
    """Return a delegated run's identity for the ``run_started`` log line.

    Progress banners (``cli_display._announce_*``) are stderr-only, so the log file could
    not answer "which agent/step ran when" after the fact.  These keys make a delegated run
    reconstructible from ``logs/heagent-*.log``; a root run carries no such metadata and
    therefore logs exactly as before.
    """
    metadata = run_context.metadata or {}
    return {key: metadata[key] for key in _DELEGATION_DETAIL_KEYS if metadata.get(key) not in (None, "")}


# ----------------------------------------------------------------------
# 初始化（run / run_stream 共享）
# ----------------------------------------------------------------------


async def init_or_resume(
    loop: AgentLoop,
    prompt: str,
    system: str | None,
    session_id: str | None,
    _resume: _ResumeState | None,
    *,
    stream: bool,
) -> _RunInit:
    """统一初始化：恢复模式（_resume → 跳过）或全新运行。

    返回 ``_RunInit`` 供 ``run()`` / ``run_stream()`` 直接消费，
    循环体不再重复分支逻辑。
    """
    # 展示态按 run 重置（恢复也是新的一次 run）：交互模式复用同一 loop 跑多轮，
    # 不清会跨轮串味。放在本函数顶部而非 init_new_run——后者在恢复分支被提前
    # 跳过，会导致 resume 后的状态栏/台账残留上一段 run 的值。
    loop.active_tool = ""
    loop.tool_activity = []
    if _resume is not None:
        resume_details: dict[str, Any] = {"resume": True, "stream": stream}
        resume_details.update(_delegation_details(_resume.run_context))
        loop._emit("run_started", run_context=_resume.run_context, details=resume_details)
        return _RunInit(
            state=_resume.state,
            run_context=_resume.run_context,
            system_content=_resume.system,
            accumulated=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            prompt=_resume.prompt,
        )
    fresh = await init_new_run(loop, prompt, system, session_id, stream=stream)
    return _RunInit(
        state=fresh[0],
        run_context=fresh[1],
        system_content=fresh[2],
        accumulated=fresh[3],
        prompt=prompt,
    )


async def init_new_run(
    loop: AgentLoop,
    prompt: str,
    system: str | None,
    session_id: str | None,
    *,
    stream: bool,
) -> tuple[AgentState, RunContext, str | None, TokenUsage]:
    """全新运行的初始化（``run``/``run_stream`` 的「分支①-B」共用）。

    建空白状态与运行上下文 → 恢复会话历史（剔除旧 SYSTEM）→ 拼系统提示词 →
    落 SYSTEM+USER 首条消息 → 写初始运行快照 → 发 run_started 事件。
    返回 ``(state, run_context, system_content, accumulated)``。

    ``stream`` 仅决定 run_started 事件 details 的载荷（流式带 ``stream`` 标记，
    非流式带 ``session_id``），与两个入口重构前的行为逐字段一致。
    """
    await loop.engine.prune_ledger_once()  # 全新 run 启动清理一次；resume 不触发（那次 run 启动已清过）
    await loop.engine.prune_runs_once()  # 同上去重：run 快照/锁/产物目录按 run_retention_days 回收
    state = AgentState(max_iterations=loop.max_iterations)
    accumulated = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    run_context = loop._ensure_run_context(session_id=session_id)

    # 拼装系统提示词（注入 soul/context/skills/facts/profile），先落 SYSTEM——
    # 严格模板（如 Ollama）要求 SYSTEM 必须是消息数组的第一条。E40-D2：本 run 的
    # shell 沙箱工作目录（真正生效时）也在此告知模型。
    system_content = await asyncio.to_thread(
        loop._build_system,
        system,
        prompt=prompt,
        sandbox_workspace=loop._bound_sandbox_workspace(run_context),
    )
    if system_content:
        state.messages.append(Message(role=Role.SYSTEM, content=system_content))

    # 若指定会话，恢复历史消息（剔除旧 SYSTEM，避免与新系统提示词重复），
    # 置于 SYSTEM 之后、新 USER 提示词之前。
    if loop.session and session_id:
        prior = await asyncio.to_thread(loop.session.load, session_id)
        if prior:
            state.messages.extend(m for m in prior if m.role != Role.SYSTEM)
            logger.debug("Restored %d messages from session '%s'", len(prior), session_id)

    state.messages.append(Message(role=Role.USER, content=prompt))

    await start_run_record(loop, run_context, prompt=prompt, system=system_content)
    details: dict[str, Any] = {"stream": True} if stream else {"session_id": session_id or ""}
    details.update(_delegation_details(run_context))
    # 展示态已由 init_or_resume 统一重置（新 run 与恢复路径共用）。
    loop._emit("run_started", run_context=run_context, details=details)
    if loop.engine.hooks is not None:
        await loop.engine.hooks.run_session(SESSION_START, run_context)
    return state, run_context, system_content, accumulated


# ----------------------------------------------------------------------
# 非流式主循环体
# ----------------------------------------------------------------------


async def execute_run(
    loop: AgentLoop,
    prompt: str,
    *,
    system: str | None = None,
    session_id: str | None = None,
    _resume: _ResumeState | None = None,
) -> str:
    """``AgentLoop.run`` 的循环体（行为与拆分前逐行等价）。

    流程分两段：① ``init_or_resume`` → ② 双层主循环（外层 follow-up + 内层
    steering/tool 执行）。``raise`` 留在 except 末尾（显性失败），``finally`` 统一持久化。
    """
    init = await init_or_resume(loop, prompt, system, session_id, _resume, stream=False)
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
                    response = await loop._call_provider(state, run_context=run_context)
                    if response.usage:
                        accumulated = loop._add_usage(accumulated, response.usage)

                    await loop._maybe_compress(state, run_context, response.usage)
                    loop._append_assistant_message(state, response)
                    await checkpoint(loop, run_context, prompt=init.prompt, system=system_content, state=state)

                    if not response.tool_calls:
                        break  # 退出内层，进入 follow-up 检查

                    tool_results = await loop._execute_tools(response.tool_calls, state, run_context=run_context)
                    for tool_result in tool_results:
                        loop._append_tool_result(state, tool_result)
                    await checkpoint(loop, run_context, prompt=init.prompt, system=system_content, state=state)
                    await loop._maybe_window_reset(
                        state, run_context, init.prompt, system_content, usage=response.usage
                    )

                # ---- follow-up 检查 ----
                if not await loop._inject_follow_up(state):
                    break  # 无 follow-up，外层退出
                # 有 follow-up → 继续外层循环，启动新一轮 LLM 调用

            final_answer = response.content if response is not None else ""
            await finish_run(loop, run_context, init, state, accumulated, final_answer=final_answer)
            return final_answer
    except Exception as exc:
        await on_run_failed(loop, run_context, init.prompt, system_content, state, exc)
        raise
    finally:
        await persist_and_cache(loop, session_id, state, accumulated, run_context)


# ----------------------------------------------------------------------
# 终结（run / run_stream 共享）
# ----------------------------------------------------------------------


async def finish_run(
    loop: AgentLoop,
    run_context: RunContext,
    init: _RunInit,
    state: AgentState,
    accumulated: TokenUsage,
    *,
    final_answer: str,
) -> None:
    """正常完成的统一收尾（``run``/``run_stream`` 共用）。

    置 COMPLETED → 落最终检查点 → 发 ``run_completed`` 事件 → 更新 ``last_*`` 缓存。
    两条循环此前各持一份逐字副本（连 ``answer_length`` 都有两种等价写法，此处统一）；
    调用方随后的动作仍各自保留：``run`` 返回答案、``run_stream`` yield ``done`` 事件。
    """
    run_context.mark_terminal(RunStatus.COMPLETED, iteration=state.iteration)
    await checkpoint(
        loop,
        run_context,
        prompt=init.prompt,
        system=init.system_content,
        state=state,
        final_answer=final_answer,
    )
    loop._emit("run_completed", run_context=run_context, details={"answer_length": len(final_answer)})
    loop.last_usage = accumulated
    loop.cumulative_tokens += accumulated.total_tokens
    loop.last_iteration = state.iteration


async def persist_and_cache(
    loop: AgentLoop,
    session_id: str | None,
    state: AgentState,
    accumulated: TokenUsage,
    run_context: RunContext,
) -> None:
    """持久化会话 + 缓存事后产物（finally 块共用）。

    无论成功/失败均调用：落盘会话消息、缓存 ``last_*`` 属性。
    """
    # 复位暂停态：无论完成/失败/取消（finally 块），均解除协作式暂停，
    # 防止「暂停后被打断」的暂停态泄漏到下一次 run（P1 修复）。
    loop._pause_event.set()
    if loop.session and session_id:
        await asyncio.to_thread(loop.session.save, session_id, state.messages)
        logger.debug("Saved %d messages to session '%s'", len(state.messages), session_id)
    loop.last_usage = accumulated
    loop.last_iteration = state.iteration
    loop.last_run_context = run_context
    # 当前上下文占用：以「下一轮将发送的消息」估算 token 数（区别于 last_usage 的累计值）。
    from heagent.context.tokens import count_tokens

    loop.last_context_tokens = count_tokens(state.messages)
    if loop.engine.hooks is not None:
        await loop.engine.hooks.run_session(SESSION_END, run_context)
    await loop.engine.close_run(run_context)


async def on_run_failed(
    loop: AgentLoop,
    run_context: RunContext,
    prompt: str,
    system_content: str | None,
    state: AgentState,
    exc: Exception,
) -> None:
    """异常收尾：置 FAILED、记错误快照、发布 run_failed 事件（不含 re-raise）。

    ``run``/``run_stream`` 的 except 块共用；``raise`` 留在各自 except 末尾
    （显性失败，异常原样向上抛）。
    """
    run_context.mark_terminal(RunStatus.FAILED, iteration=state.iteration)
    await checkpoint(
        loop,
        run_context,
        prompt=prompt,
        system=system_content,
        state=state,
        error=str(exc),
    )
    loop._emit(
        "run_failed",
        run_context=run_context,
        details={"error": str(exc)},
    )


# ----------------------------------------------------------------------
# run_store 持久化（best-effort：失败仅记日志，不阻断主循环）
# ----------------------------------------------------------------------


async def start_run_record(loop: AgentLoop, run_context: RunContext, *, prompt: str, system: str | None) -> None:
    """写入初始运行快照（best-effort：失败仅记日志，不阻断主循环）。"""
    try:
        await loop.engine.run_store.start(run_context, prompt=prompt, system=system)
    except Exception:
        logger.exception("Failed to start run record for '%s'", run_context.run_id)


async def checkpoint(
    loop: AgentLoop,
    run_context: RunContext,
    *,
    prompt: str,
    system: str | None,
    state: AgentState,
    final_answer: str | None = None,
    error: str | None = None,
) -> None:
    """持久化运行进度（best-effort：失败仅记日志，不阻断主循环）。

    在关键节点（每轮助手回复后、工具执行后、最终完成/失败时）落盘当前消息与
    结果，供 ``resume()`` 续跑或事后审计使用。
    """
    try:
        await loop.engine.run_store.checkpoint(
            run_context,
            prompt=prompt,
            system=system,
            messages=state.messages,
            results=state.results,
            final_answer=final_answer,
            error=error,
        )
    except Exception:
        logger.exception("Failed to checkpoint run '%s'", run_context.run_id)
