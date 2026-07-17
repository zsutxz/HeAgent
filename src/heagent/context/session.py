"""会话持久化 — 将对话历史保存/恢复为 JSON 文件。

存储路径：.heagent/sessions/{session_id}.json
每个文件包含：session_id、时间戳、version、消息列表的序列化数据。

接入路径：``cli.py`` 交互模式创建 → ``AgentLoop`` 持有；``run()`` 入口按 ``session_id``
调 ``load`` 恢复历史，结束时调 ``save`` 落盘（loop.py 流式/非流式双入口均已实现）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from heagent.engine.persist import atomic_write_text
from heagent.types import Message


class SessionStore:
    """会话存储管理器，支持对话历史的持久化和恢复。

    使用 :func:`atomic_write_text` 实现原子写，避免崩溃留下截断 JSON。
    version 字段递增，防止并发写覆盖。
    """

    def __init__(self, base_dir: str = ".heagent/sessions") -> None:
        self._base = Path(base_dir)

    def save(self, session_id: str, messages: list[Message]) -> str:
        """保存对话历史到 JSON 文件（原子写 + version 递增）。

        返回保存的文件路径。
        """
        path = self._base / f"{session_id}.json"

        # 读取现有 version，在此基础上递增
        existing_version = 0
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                existing_version = data.get("version", 0) or 0
            except (json.JSONDecodeError, OSError):
                pass  # 文件损坏则从头开始

        data = {
            "session_id": session_id,
            "version": existing_version + 1,
            "timestamp": time.time(),
            "messages": [m.model_dump() for m in messages],
        }
        text = json.dumps(data, ensure_ascii=False, indent=2)
        atomic_write_text(path, text)
        return str(path)

    def load(self, session_id: str) -> list[Message]:
        """从 JSON 文件恢复对话历史。

        文件不存在时返回空列表。version 用于日志记录，不做合并冲突处理。
        """
        path = self._base / f"{session_id}.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [Message(**m) for m in data.get("messages", [])]

    def list_sessions(self) -> list[str]:
        """返回所有已保存的会话 ID（按名称排序）。"""
        if not self._base.exists():
            return []
        return sorted(p.stem for p in self._base.glob("*.json"))

    def delete(self, session_id: str) -> bool:
        """删除指定会话文件。返回是否成功删除。"""
        path = self._base / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
