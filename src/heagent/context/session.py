"""会话持久化 — 将对话历史保存/恢复为 JSON 文件。

存储路径：.heagent/sessions/{session_id}.json
每个文件包含：session_id、时间戳、version、消息列表的序列化数据。

接入路径：``cli.py`` 交互模式创建 → ``AgentLoop`` 持有；``run()`` 入口按 ``session_id``
调 ``load`` 恢复历史，结束时调 ``save`` 落盘（loop.py 流式/非流式双入口均已实现）。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from heagent.engine.persist import atomic_update_text
from heagent.types import Message

# session_id 允许的字符集：字母数字 + 连字符/下划线，防止路径遍历（如 ../etc/passwd）。
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
# 合理长度上限：UUID hex 最大 32 字符，加上前缀/后缀留有余额，超过视为异常拒绝。
_MAX_SESSION_ID_LEN = 128


def _validate_session_id(session_id: str) -> None:
    """校验 session_id 仅含安全字符，拒绝路径遍历 payload。"""
    if not session_id or len(session_id) > _MAX_SESSION_ID_LEN or not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")


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
        _validate_session_id(session_id)
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

        def update(raw: str) -> tuple[str, None]:
            try:
                current = json.loads(raw) if raw else {}
                version = current.get("version", 0) if isinstance(current, dict) else 0
            except json.JSONDecodeError:
                version = 0
            data["version"] = (version or 0) + 1
            return json.dumps(data, ensure_ascii=False, indent=2), None

        atomic_update_text(path, update)
        return str(path)

    def load(self, session_id: str) -> list[Message]:
        """从 JSON 文件恢复对话历史。

        文件不存在时返回空列表。version 用于日志记录，不做合并冲突处理。
        """
        _validate_session_id(session_id)
        path = self._base / f"{session_id}.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [Message(**m) for m in data.get("messages", [])]

    def list_sessions(self) -> list[str]:
        """返回所有已保存的会话 ID（按文件名字母序）。"""
        if not self._base.exists():
            return []
        return sorted(p.stem for p in self._base.glob("*.json"))

    def recent_session_ids(self, limit: int) -> list[str]:
        """返回最近 ``limit`` 个会话 ID（按 session 落盘 ``timestamp`` 降序）。

        :meth:`list_sessions` 按文件名字母序、不反映时间先后（session_id 是随机 hex）；
        DreamScheduler 需按真实时间取近期 session 做巩固，故按 ``timestamp`` 降序。
        损坏 / 缺 timestamp 的条目按 0.0 排序（沉底，不剔除）。
        """
        if not self._base.exists() or limit <= 0:
            return []
        entries: list[tuple[float, str]] = []
        for p in self._base.glob("*.json"):
            ts = 0.0
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                ts = float(data.get("timestamp") or 0.0)
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                pass  # 损坏文件按 ts=0.0 排序
            entries.append((ts, p.stem))
        entries.sort(key=lambda e: e[0], reverse=True)
        return [sid for _, sid in entries[:limit]]

    def delete(self, session_id: str) -> bool:
        """删除指定会话文件。返回是否成功删除。"""
        _validate_session_id(session_id)
        path = self._base / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
