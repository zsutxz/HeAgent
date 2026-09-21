"""消息端口——steering / follow-up 注入与协作式暂停（Phase 2 自 loop.py 拆出）。

把原本散在 ``AgentLoop`` 上的两类「外部消息进入循环」通道收拢为独立端口：
steering/follow-up 回调的 poll+inject（参考 Pi 双层循环设计），以及
``pause``/``unpause``/``wait_if_paused`` 协作式暂停。端口仅依赖注入在 loop 上的
回调与 ``_pause_event``，可用最小替身独立测试。

依赖方向：运行期不导入 ``heagent.agent.loop``（仅 TYPE_CHECKING）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from heagent.agent.loop import AgentLoop
    from heagent.agent.run_lifecycle import AgentState
    from heagent.engine import RunContext
    from heagent.types import Message

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# steering / follow-up 消息队列（参考 Pi 双层循环设计）
# ----------------------------------------------------------------------


async def _poll(callback: Callable[[], Awaitable[list[Message]]] | None, label: str) -> list[Message]:
    """轮询一个可选回调：未配置返回空表，回调抛错只记 warning。

    消息注入（steering / follow-up）**不得阻断主循环**，故异常在此静默；两处调用点仅
    「回调 + 日志标签」不同，原先各持一份逐字副本。
    """
    if callback is None:
        return []
    try:
        return await callback()
    except Exception:
        logger.warning("%s failed", label, exc_info=True)
        return []


async def poll_steering(loop: AgentLoop) -> list[Message]:
    """Poll steering 回调，返回待注入的消息（失败静默，不阻断主循环）。"""
    return await _poll(loop.steering_callback, "steering_callback")


async def poll_follow_up(loop: AgentLoop) -> list[Message]:
    """Poll follow-up 回调，返回待注入的消息（失败静默，不阻断主循环）。"""
    return await _poll(loop.follow_up_callback, "follow_up_callback")


async def inject_steering(loop: AgentLoop, state: AgentState) -> None:
    """把 steering 消息追加进上下文（每轮 LLM 调用前的边界）。

    ``run``/``run_stream`` 共用——两条循环此前各持一份「轮询 → 逐条追加」的逐字副本。
    """
    for msg in await poll_steering(loop):
        state.messages.append(msg)


async def inject_follow_up(loop: AgentLoop, state: AgentState) -> bool:
    """把 follow-up 消息追加进上下文；返回**是否还有下一轮**（外层循环判据）。

    返回 ``False`` 表示无 follow-up → 外层退出。``run``/``run_stream`` 共用。
    """
    follow_up = await poll_follow_up(loop)
    if not follow_up:
        return False
    for msg in follow_up:
        state.messages.append(msg)
    return True


# ----------------------------------------------------------------------
# 暂停 / 恢复（协作式：在下一轮 LLM 调用前的边界生效）
# ----------------------------------------------------------------------


def pause(loop: AgentLoop) -> None:
    """请求暂停循环：当前进行中的 LLM 调用会跑完，随后在下一轮边界挂起。

    协作式暂停——不打断进行中的 provider 调用、不取消任务；``unpause()`` 后从
    挂起点原地继续（消息、迭代计数、run 上下文均保留）。幂等，可多次调用。
    须在同一事件循环内调用（跨线程请用 ``loop.call_soon_threadsafe`` 包装）。
    """
    loop._pause_event.clear()
    logger.info("AgentLoop pause requested")


def unpause(loop: AgentLoop) -> None:
    """恢复被 ``pause()`` 挂起的循环。幂等，可多次调用。"""
    loop._pause_event.set()
    logger.info("AgentLoop unpaused")


def is_paused(loop: AgentLoop) -> bool:
    """当前是否处于暂停请求态（循环可能尚未到达挂起点）。"""
    return not loop._pause_event.is_set()


async def wait_if_paused(loop: AgentLoop, run_context: RunContext) -> None:
    """暂停检查点：处于暂停态则挂起，直到 ``unpause()``。

    由 ``run`` / ``run_stream`` 内层循环在每轮边界调用；挂起前后各发一条
    ``run_paused`` / ``run_resumed`` 事件供观测。
    """
    if loop._pause_event.is_set():
        return
    loop._emit("run_paused", run_context=run_context)
    try:
        await loop._pause_event.wait()
    finally:
        loop._emit("run_resumed", run_context=run_context)
