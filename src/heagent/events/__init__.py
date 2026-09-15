"""事件传输层：机器可读 JSONL 协议、rollout 落盘与回放。

对外的稳定契约见 :mod:`heagent.events.protocol`（``RunEvent`` / ``SCHEMA_VERSION``），
接收器与回放见 :mod:`heagent.events.sink`。本包在运行时**不依赖** ``engine/``
（引擎类型仅在 TYPE_CHECKING 下引入），CLI 与 GUI 均可独立订阅。
"""

from __future__ import annotations

from heagent.events.protocol import (
    ASSISTANT_MESSAGE_KIND,
    KNOWN_KINDS,
    SCHEMA_VERSION,
    RunEvent,
    from_engine_event,
    make_event,
)
from heagent.events.sink import JsonlSink, default_rollout_dir, read_rollout, render_event

__all__ = [
    "ASSISTANT_MESSAGE_KIND",
    "KNOWN_KINDS",
    "SCHEMA_VERSION",
    "JsonlSink",
    "RunEvent",
    "default_rollout_dir",
    "from_engine_event",
    "make_event",
    "read_rollout",
    "render_event",
]
