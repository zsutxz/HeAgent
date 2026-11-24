"""Resume 策略——从 run_store 快照重建续跑状态（Phase 2 自 loop.py 拆出）。

``AgentLoop.resume`` / ``resume_stream``（façade 公共入口）经 :func:`build_resume_state`
取得 ``(snapshot, _ResumeState | None)``：已完成的 run 返回 ``(snapshot, None)`` 由
façade 直接短路返回缓存答案；未完成则重建「原 prompt + 进度摘要」窗口注入
``run()`` / ``run_stream()`` 续跑。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.agent.run_lifecycle import AgentState, _ResumeState
from heagent.context.window_reset import WindowReset
from heagent.engine import RunStatus
from heagent.pub.exceptions import AgentResumeError

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.engine.store import RunSnapshot

logger = logging.getLogger(__name__)


async def build_resume_state(loop: AgentLoop, run_id: str) -> tuple[RunSnapshot, _ResumeState | None]:
    """从快照重建恢复状态；已完成的 run 返回 ``(snapshot, None)``。"""
    snapshot = await loop.engine.run_store.load(run_id)
    if snapshot is None:
        raise AgentResumeError(f"No run snapshot found for run_id={run_id!r}")
    if snapshot.context.status == RunStatus.COMPLETED:
        return snapshot, None

    # FAILED 快照仍可恢复：瞬时失败正是 ``resume()`` 存在的理由。
    # ``RunContext.mark_terminal`` 禁止同一 context 二次写终态（fail-loud reducer），
    # 所以这里把 context 重新置为 RUNNING——resume 的语义是「在同一个 run_id 上再起一次尝试」，
    # 而已完成的那次尝试在 checkpoint 链里保留自己的记录。没有这一步，恢复后的首次终态写入
    # 会抛 RuntimeError，随后被 ``on_run_failed`` 掩盖成「第二次写 FAILED」。
    if snapshot.context.status == RunStatus.FAILED:
        snapshot.context.touch(status=RunStatus.RUNNING)

    progress = snapshot.context.metadata.get("progress_summary")
    if progress:
        messages = WindowReset.build_resume_messages(original_prompt=snapshot.prompt, summary=progress)
    else:
        messages = [m.model_copy(deep=True) for m in snapshot.messages]

    state = AgentState(
        messages=messages,
        max_iterations=loop.max_iterations,
        iteration=snapshot.context.iteration,
    )
    return snapshot, _ResumeState(
        state=state,
        run_context=snapshot.context,
        prompt=snapshot.prompt,
        system=snapshot.system,
    )
