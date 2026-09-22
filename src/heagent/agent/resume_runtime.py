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

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.engine.store import RunSnapshot

logger = logging.getLogger(__name__)


async def build_resume_state(loop: AgentLoop, run_id: str) -> tuple[RunSnapshot, _ResumeState | None]:
    """从快照重建恢复状态；已完成的 run 返回 ``(snapshot, None)``。"""
    snapshot = await loop.engine.run_store.load(run_id)
    if snapshot is None:
        raise ValueError(f"No run snapshot found for run_id={run_id!r}")
    if snapshot.context.status == RunStatus.COMPLETED:
        return snapshot, None

    # A FAILED snapshot stays resumable: transient failures are the whole point of
    # ``resume()``. ``RunContext.mark_terminal`` forbids a second terminal write on
    # the same context (fail-loud reducer, Phase 2 C2), so re-arm the context to
    # RUNNING here — resume means "start another attempt on this run_id", and the
    # finished attempt keeps its record in the checkpoint chain. Without this the
    # first terminal write of the resumed attempt raises RuntimeError, which
    # ``on_run_failed`` then masks by trying to write FAILED a second time.
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
