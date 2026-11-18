"""重启后的运行事件回放（活动台账 A35）：把 rollout JSONL 读成 SSE 负载序列。

问题：网页入口的运行事件缓冲在**进程内**（``http_server.records`` 的 ring buffer）⇒ 进程重启后
``GET /api/runs/<id>/events`` 对旧 run 只能回 404，前端刷新即丢掉整段轨迹。会话历史本已落盘
（``SessionStore``，CLI 与网页共用），缺的只是**事件流**的读侧。

做法（刻意最小，不新做投影持久化架构）：``EVENTS_ROLLOUT_ENABLED=true`` 时引擎事件已逐行落
``<项目根>/.heagent/runs/<run_id>/rollout.jsonl``，这里复用既有的
:func:`heagent.events.sink.read_rollout` 读回，再映射成传输层既有的 ``RunEventPayload``。

**回放是粗粒度的，且刻意如实说明**：rollout 的 ``tool_call_completed`` 只记 ``content_length``，
不含工具输出原文 ⇒ 回放里工具结果统一标注「输出未记入 rollout」；流式文本增量同样没有落盘，
``assistant_message`` 以一条 ``done`` 交付完整答案。

分工：本模块在**入口层**（``cli/``）——它同时认识 ``events``（运行栈）与
``network`` 的负载模型，而 ``network/`` 自身不得导入运行栈（架构硬约束）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from heagent.events.protocol import ASSISTANT_MESSAGE_KIND
from heagent.events.sink import default_rollout_dir, read_rollout
from heagent.network.http_protocol import RunEventKind, RunEventPayload, clip_text

if TYPE_CHECKING:
    from pathlib import Path

    from heagent.events.protocol import RunEvent

logger = logging.getLogger(__name__)

#: run_id 只允许安全字符：它会拼进路径，必须挡住 ``..`` / 分隔符 / 绝对路径。
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

#: 回放中工具结果的固定说明（rollout 不记工具输出原文，如实标注而非留空）。
_UNRECORDED_OUTPUT = "(工具输出未记入 rollout：回放只保留调用、状态与最终答案)"

#: 视为「流已收敛」的终态类型；rollout 尾部缺终态时补一条 cancelled 说明（否则客户端等不到收尾）。
_TERMINAL_KINDS = frozenset({RunEventKind.DONE, RunEventKind.ERROR, RunEventKind.CANCELLED, RunEventKind.TIMED_OUT})

#: 一条回放最多交付的事件数（防止超大 rollout 撑爆单次响应；截断记 warning）。
_MAX_REPLAY_EVENTS = 2000

RunHistorySource = Callable[[str], "list[RunEventPayload] | None"]


def rollout_path(root: Path, run_id: str) -> Path | None:
    """``<root>/.heagent/runs/<run_id>/rollout.jsonl``；run_id 不安全或路径越界时返回 ``None``。"""
    if not _RUN_ID_PATTERN.match(run_id):
        return None
    base = default_rollout_dir(root)
    candidate = base / run_id / "rollout.jsonl"
    try:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(base.resolve()):
            return None
    except OSError:
        return None
    return resolved


def _to_payload(event: RunEvent) -> RunEventPayload | None:
    """把一条引擎事件映射成 SSE 负载；回放不表达的事件返回 ``None``（跳过）。"""
    # seq 由调用方统一重编号（rollout 里的 seq 是 sink 内序号，历史文件可能为 0/重复）。
    if event.kind == "tool_call_started":
        return RunEventPayload(
            kind=RunEventKind.TOOL_CALL, seq=1, tool_name=event.tool, tool_target=clip_text(event.target)
        )
    if event.kind == "tool_call_completed":
        return RunEventPayload(
            kind=RunEventKind.TOOL_RESULT,
            seq=1,
            tool_name=event.tool,
            tool_output=_UNRECORDED_OUTPUT,
            tool_error=False,
        )
    if event.kind in ("tool_call_failed", "tool_call_blocked"):
        reason = str(event.details.get("error") or event.details.get("reason") or event.kind)
        return RunEventPayload(
            kind=RunEventKind.TOOL_RESULT,
            seq=1,
            tool_name=event.tool,
            tool_output=clip_text(reason),
            tool_error=True,
        )
    if event.kind == ASSISTANT_MESSAGE_KIND:
        model = event.details.get("model")
        return RunEventPayload(
            kind=RunEventKind.DONE,
            seq=1,
            text=clip_text(str(event.details.get("content", ""))),
            model=str(model) if isinstance(model, str) and model else None,
        )
    if event.kind in ("run_failed", "cron_job_failed"):
        message = str(event.details.get("error") or "run failed")
        return RunEventPayload(kind=RunEventKind.ERROR, seq=1, message=clip_text(message))
    return None


def load_run_history(root: Path, run_id: str) -> list[RunEventPayload] | None:
    """读回一次运行的历史事件；文件不存在 / 读不出任何可回放事件时返回 ``None``。"""
    path = rollout_path(root, run_id)
    if path is None or not path.is_file():
        return None
    try:
        events = read_rollout(path)
    except OSError:
        logger.warning("run history replay: unable to read rollout %s", path, exc_info=True)
        return None
    payloads: list[RunEventPayload] = []
    for event in events:
        mapped = _to_payload(event)
        if mapped is None:
            continue
        payloads.append(mapped.model_copy(update={"seq": len(payloads) + 1}))
    if not payloads:
        return None
    if len(payloads) > _MAX_REPLAY_EVENTS:
        logger.warning("run history replay: %s has %d events, truncated to %d", path, len(payloads), _MAX_REPLAY_EVENTS)
        payloads = payloads[:_MAX_REPLAY_EVENTS]
    if payloads[-1].kind not in _TERMINAL_KINDS:
        # 崩溃/中断的 run 在 rollout 里没有终态行：补一条显式说明，别让客户端等一条永不结束的流。
        payloads.append(
            RunEventPayload(
                kind=RunEventKind.CANCELLED,
                seq=len(payloads) + 1,
                message="history replay: the rollout ends without a terminal event",
            )
        )
    return payloads


def run_history_source(root: Path) -> RunHistorySource:
    """把项目根绑定成注入用的回放来源（``build_http_app(history=...)`` 的形状）。"""

    def load(run_id: str) -> list[RunEventPayload] | None:
        return load_run_history(root, run_id)

    return load
