"""会话持久化 — 将对话历史保存/恢复为 JSON 文件。

存储路径：.heagent/sessions/{session_id}.json
每个文件包含：session_id、时间戳、消息列表的序列化数据。

当前状态：已实现但未接入 AgentLoop。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from heagent.types import Message, Role


class SessionStore:
    """会话存储管理器，支持对话历史的持久化和恢复。"""

    def __init__(self, base_dir: str = ".heagent/sessions") -> None:
        self._base = Path(base_dir)

    def save(self, session_id: str, messages: list[Message]) -> str:
        """保存对话历史到 JSON 文件。

        返回保存的文件路径。
        """
        self._base.mkdir(parents=True, exist_ok=True)
        path = self._base / f"{session_id}.json"
        data = {
            "session_id": session_id,
            "timestamp": time.time(),
            "messages": [m.model_dump() for m in messages],  # Pydantic 模型序列化
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def load(self, session_id: str) -> list[Message]:
        """从 JSON 文件恢复对话历史。

        文件不存在时返回空列表。
        """
        path = self._base / f"{session_id}.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
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
