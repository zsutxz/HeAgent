"""机器可读运行事件协议（JSONL）——对外的**稳定子集**，对齐 Codex 的 ``--json`` 事件流。

设计立场：

* **不复制埋点**：事件源仍是进程内的 :class:`~heagent.engine.observability.EngineEvent`
  总线（``engine/observability.py``），本模块只做「映射 + 序列化」，不重复插桩。
* **开集 kind**：``kind`` 直接沿用引擎事件名（``run_started`` / ``tool_call_completed`` …），
  引擎新增事件无需改协议即可被消费；:data:`KNOWN_KINDS` 只用于文档与黄金测试，**不**作过滤依据。
* **稳定性**：字段集由 :data:`SCHEMA_VERSION` 锚定；改字段须 bump 版本并更新黄金测试。
* **不可信内容**：``target`` / ``details`` 携带工具原始输入输出（含 MCP / 远端返回内容），
  与工具返回**同等不可信**——消费方不得因「结构化」而提升信任（与 CLAUDE.md 安全立场一致）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from heagent.engine.observability import EngineEvent

SCHEMA_VERSION = "1"

# 当前引擎事件全集（文档 + 黄金测试依据）。消费方须按「开集」处理未知 kind。
KNOWN_KINDS: frozenset[str] = frozenset(
    {
        # run 生命周期
        "run_started",
        "run_paused",
        "run_resumed",
        "run_completed",
        "run_failed",
        # 迭代 / provider
        "iteration_started",
        "provider_call_started",
        "provider_call_completed",
        # 上下文
        "context_compressed",
        "window_reset",
        # 工具执行（含被 SafetyGuard 拦截）
        "tool_call_started",
        "tool_call_completed",
        "tool_call_failed",
        "tool_call_blocked",
    }
)

# 传输层补充的事件（**唯一**非引擎来源）：CLI 在 run 结束后交回最终答案。
ASSISTANT_MESSAGE_KIND = "assistant_message"


def _now_iso() -> str:
    """本地时间 ISO-8601（秒精度）。

    刻意与 ``engine.context.iso_now`` 同格式但**独立实现**：``events/`` 在运行时
    不依赖 ``engine/``（引擎类型仅在 TYPE_CHECKING 下引入），保持传输层可独立复用。
    """
    return datetime.now().isoformat(timespec="seconds")


class RunEvent(BaseModel):
    """一条 JSONL 运行事件（对外契约）。

    字段含义与 :class:`~heagent.engine.observability.EngineEvent` 同义（刻意同形，避免
    多一层嵌套 payload）：``tool`` 对应 ``tool_name``，``kind`` 对应 ``event_type``。
    """

    schema_version: str = SCHEMA_VERSION
    # 同一 sink 内严格递增，从 1 开始（消费方可据此判定丢行 / 乱序）。
    seq: int = 0
    ts: str = ""
    run_id: str = ""
    iteration: int = 0
    kind: str
    tool: str = ""
    target: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    def to_jsonl(self) -> str:
        """序列化为**单行** JSON（不含换行；正文里的换行由 JSON 自动转义）。

        ``fallback=str`` + ``default=str`` 双重兜底：details 里出现不可序列化对象时降级为
        字符串（pydantic 的 ``model_dump(mode="json")`` 对未知类型会直接抛
        ``PydanticSerializationError``，仅靠 ``json.dumps(default=...)`` 兜不住）——
        观测层的问题绝不打断 run。
        """
        return json.dumps(self.model_dump(mode="json", fallback=str), ensure_ascii=False, default=str)


def make_event(
    kind: str,
    *,
    seq: int,
    run_id: str = "",
    iteration: int = 0,
    tool: str = "",
    target: str = "",
    details: dict[str, Any] | None = None,
    ts: str | None = None,
) -> RunEvent:
    """构造一条事件（``seq`` 由调用方负责单调递增）。"""
    return RunEvent(
        seq=seq,
        ts=ts or _now_iso(),
        run_id=run_id,
        iteration=iteration,
        kind=kind,
        tool=tool,
        target=target,
        details=dict(details or {}),
    )


def from_engine_event(event: EngineEvent, *, seq: int) -> RunEvent:
    """把总线上的 :class:`EngineEvent` 映射为对外 :class:`RunEvent`（无信息丢失）。"""
    return make_event(
        event.event_type,
        seq=seq,
        run_id=event.run_id,
        iteration=event.iteration,
        tool=event.tool_name,
        target=event.target,
        details=event.details,
        ts=event.timestamp or None,
    )
