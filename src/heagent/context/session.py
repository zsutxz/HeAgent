"""会话持久化 — 将对话历史保存/恢复为 JSON 文件。

存储路径：.heagent/sessions/{session_id}.json
每个文件包含：session_id、时间戳、version、消息列表的序列化数据（以及可选的 title）。

接入路径：``cli.py`` 交互模式创建 → ``AgentLoop`` 持有；``run()`` 入口按 ``session_id``
调 ``load`` 恢复历史，结束时调 ``save`` 落盘（loop.py 流式/非流式双入口均已实现）。

**控制台（Epic 50 / Story 50-3）新增的三件事——全部是增量，CLI 语义逐字节不变**：

- :meth:`SessionStore.save` 支持可选 ``expected_version``：磁盘版本不符即抛
  :class:`~heagent.exceptions.SessionConflictError`，网页据此回 ``session_conflict`` 而不是静默
  覆盖（CLI 不传该参数 ⇒ 与改造前行为一致，脊柱 I11/I13）；
- :meth:`SessionStore.load_metadata` / :meth:`SessionStore.list_metadata` 供网页列会话——
  **元数据解析留在本模块**，网络层不得自己解析会话 JSON（脊柱「Never」项）；
- ``title`` 是会话文件的可选**顶层**字段：由 :meth:`SessionStore.rename` 拥有、由
  :meth:`SessionStore.save` **保留**（``save`` 只拥有对话内容）。标题绝不写进 ``messages``，
  CLI 的读取路径因此不受影响。
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from heagent.exceptions import SessionConflictError, SessionNotFoundError, SessionUnreadableError
from heagent.persist import atomic_update_text, prune_entries_by_mtime
from heagent.types import Message, Role

logger = logging.getLogger(__name__)

# session_id 允许的字符集：字母数字 + 连字符/下划线，防止路径遍历（如 ../etc/passwd）。
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
# 合理长度上限：UUID hex 最大 32 字符，加上前缀/后缀留有余额，超过视为异常拒绝。
_MAX_SESSION_ID_LEN = 128

# 会话标题上限（字符）：标题进控制台列表、详情与页面，必须有界。
MAX_SESSION_TITLE_CHARS = 120
# 派生标题上限：它是摘要而非用户设定的标题，刻意比可设标题更短。
MAX_DERIVED_TITLE_CHARS = 60
# 一次列表返回的会话数上限（NFR-11 有界）；会话数本身无上限（每次交互都新建一个 id）。
MAX_SESSION_LIST_LIMIT = 200
# 列表元数据读取的文件大小上限：超过则不数 ``message_count``（D6 的退化口径：详情才给）。
MAX_SESSION_METADATA_BYTES = 1_048_576
# 无可用内容时的会话标题；列表与详情共用同一常量，避免后端与 UI 各写一份文案。
UNNAMED_SESSION_TITLE = "未命名会话"
# 不可解析的会话文件在列表里的标题——它**不会**被丢掉（否则等于静默消失），而是显式标注。
UNREADABLE_SESSION_TITLE = "不可读会话"


def _complete_tool_transactions(messages: list[Message]) -> list[Message]:
    """Return the longest prefix containing only complete tool-call transactions.

    Chat Completions requires every assistant ``tool_calls`` message to be followed
    immediately by one TOOL message for each call. A cancelled run can otherwise be
    persisted after the assistant message but before its tool results, which poisons
    every later request that restores that session.
    """
    complete: list[Message] = []
    pending_ids: set[str] = set()
    transaction_start = 0

    for message in messages:
        if pending_ids:
            if message.role is not Role.TOOL or message.tool_call_id not in pending_ids:
                logger.warning("Discarding incomplete tool-call transaction from session history")
                return complete[:transaction_start]
            pending_ids.remove(message.tool_call_id)
            complete.append(message)
            continue

        if message.role is Role.TOOL:
            logger.warning("Discarding session history from orphaned tool result")
            return complete

        complete.append(message)
        if message.role is Role.ASSISTANT and message.tool_calls:
            call_ids = [call.id for call in message.tool_calls]
            if not all(call_ids) or len(set(call_ids)) != len(call_ids):
                logger.warning("Discarding session history from malformed tool-call transaction")
                return complete[:-1]
            pending_ids = set(call_ids)
            transaction_start = len(complete) - 1

    if pending_ids:
        logger.warning("Discarding incomplete tool-call transaction at end of session history")
        return complete[:transaction_start]
    return complete


def _validate_session_id(session_id: str) -> None:
    """校验 session_id 仅含安全字符，拒绝路径遍历 payload。"""
    if not session_id or len(session_id) > _MAX_SESSION_ID_LEN or not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")


def validate_title(title: str) -> str:
    """规范化并校验会话标题（折叠空白 + 长度上限），非法时抛 ``ValueError``。

    折叠内部空白既是「标题必须单行」的语义要求，也顺手挡掉「标题里塞换行伪造列表项」这类展示层
    注入；长度上限保证标题不会把控制台响应撑大。
    """
    normalized = " ".join(title.split())
    if not normalized or len(normalized) > MAX_SESSION_TITLE_CHARS:
        raise ValueError(f"Session title must be 1..{MAX_SESSION_TITLE_CHARS} characters")
    return normalized


def derive_title(messages: list[Message]) -> str:
    """从对话内容派生标题：首条**非空**用户消息（折叠空白 + 截断），否则固定回退文案。

    纯函数、可单测。只读消息内容，不触碰文件系统——网页列会话时对没有 ``title`` 的会话用它兜底。
    """
    for message in messages:
        if message.role is not Role.USER:
            continue
        collapsed = " ".join(message.content.split())
        if not collapsed:
            continue
        if len(collapsed) > MAX_DERIVED_TITLE_CHARS:
            return collapsed[: MAX_DERIVED_TITLE_CHARS - 1] + "…"
        return collapsed
    return UNNAMED_SESSION_TITLE


class SessionMetadata(BaseModel):
    """会话文件的轻量元数据（不构造 ``Message``，避免列表时校验整份历史）。

    ``message_count`` 为 ``None`` 表示「本次未统计」（文件超过
    :data:`MAX_SESSION_METADATA_BYTES`，按 D6 退化为详情才给），**不是** 0。
    ``unreadable=True`` 表示文件存在但无法解析：详情接口会对它回 ``session_unreadable``。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    title: str
    message_count: int | None = None
    version: int = 0
    timestamp: float = 0.0
    updated_at: str | None = None
    unreadable: bool = False


def _coerce_version(value: object) -> int:
    """把磁盘上的 ``version`` 收敛成非负整数（缺失/畸形一律按 0）。"""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _coerce_timestamp(value: object) -> float:
    """把磁盘上的 ``timestamp`` 收敛成有限非负数（缺失/畸形一律按 0.0，排序时沉底）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return 0.0
    return number


def _iso_timestamp(timestamp: float) -> str | None:
    """把 epoch 秒转成 ISO8601（UTC）；无可用时间时返回 ``None``（不发明时间）。"""
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _read_header(raw: str) -> tuple[int, str | None]:
    """读磁盘会话头（``version`` / ``title``）；损坏或缺失按「无版本、无标题」处理。

    ``save`` / ``rename`` 的读改写闭包用它：**损坏的文件不阻断写入**（既有语义是 version 归 0 后
    继续写），否则一个坏文件会让该会话永远无法通过 CLI 保存。
    """
    try:
        current = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0, None
    if not isinstance(current, dict):
        return 0, None
    title = current.get("title")
    return _coerce_version(current.get("version")), title if isinstance(title, str) else None


def _session_payload(
    session_id: str,
    version: int,
    timestamp: float,
    messages: list[Message],
    title: str | None,
) -> dict[str, object]:
    """组装落盘 JSON。**无 title 时键序与改造前完全一致**（CLI 侧逐字节不变，见 story 负向验证）。"""
    payload: dict[str, object] = {"session_id": session_id, "version": version, "timestamp": timestamp}
    if title is not None:
        payload["title"] = title
    payload["messages"] = [m.model_dump() for m in _complete_tool_transactions(messages)]
    return payload


def _metadata_from_data(
    session_id: str,
    data: dict[str, object],
    *,
    count_messages: bool = True,
) -> SessionMetadata:
    """从已解析的会话文档构造元数据；``title`` 缺失时退回派生值。"""
    messages = data.get("messages")
    message_list = messages if isinstance(messages, list) else []
    raw_title = data.get("title")
    timestamp = _coerce_timestamp(data.get("timestamp"))
    if isinstance(raw_title, str) and " ".join(raw_title.split()):
        title = " ".join(raw_title.split())[:MAX_SESSION_TITLE_CHARS]
    else:
        # 消息项不合法（缺字段 / 旧 schema / 类型不符）与「JSON 坏了」同属「不可解析」：必须抛
        # :class:`SessionUnreadableError` 而不是让 pydantic 的 ``ValidationError`` 逃出去——否则
        # 一条畸形消息会让**整页会话列表** 500（与 :meth:`list_metadata` 的 fail-soft 承诺矛盾），
        # 详情接口也会退化成不透明 500 而不是稳定的 ``session_unreadable``。
        try:
            well_formed = [Message(**item) for item in message_list if isinstance(item, dict)]
        except ValidationError as exc:
            raise SessionUnreadableError(f"session {session_id!r} has invalid message entries") from exc
        title = derive_title(well_formed)
    return SessionMetadata(
        session_id=session_id,
        title=title,
        message_count=len(message_list) if count_messages else None,
        version=_coerce_version(data.get("version")),
        timestamp=timestamp,
        updated_at=_iso_timestamp(timestamp),
    )


def _metadata_from_raw(session_id: str, raw: str, *, count_messages: bool = True) -> SessionMetadata:
    """解析一份会话文件的内容为元数据；不可解析时抛 :class:`SessionUnreadableError`。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SessionUnreadableError(f"session {session_id!r} is not valid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise SessionUnreadableError(f"session {session_id!r} has an unexpected structure")
    return _metadata_from_data(session_id, data, count_messages=count_messages)


def _unreadable_metadata(session_id: str, mtime: float) -> SessionMetadata:
    """损坏会话在列表里的占位元数据：显式标注而非从列表消失。"""
    return SessionMetadata(
        session_id=session_id,
        title=UNREADABLE_SESSION_TITLE,
        message_count=None,
        version=0,
        timestamp=mtime,
        updated_at=_iso_timestamp(mtime),
        unreadable=True,
    )


class SessionStore:
    """会话存储管理器，支持对话历史的持久化和恢复。

    使用 :func:`atomic_write_text` 实现原子写，避免崩溃留下截断 JSON。
    version 字段递增，防止并发写覆盖。
    """

    def __init__(self, base_dir: str = ".heagent/sessions") -> None:
        self._base = Path(base_dir)

    async def prune(self, retention_days: int, *, min_interval_seconds: int = 0) -> int:
        """按 mtime 回收过期会话文件，返回删除数（``retention_days <= 0`` 禁用）。

        会话此前**没有任何回收方**（实测 84 天积累 409 文件 / 83 MiB，最老 101 天）：老会话
        几乎不会被 ``--continue`` 再用，但文件会随每次交互单调增长。判定只看文件 mtime
        （会话每次保存都会刷新 mtime，故「在用的会话」不会被误删），不解析 JSON。
        单条删除失败不中断整批；``min_interval_seconds > 0`` 时走跨进程节流（见
        ``engine.persist.stamp_is_recent``）。序列实现在 ``prune_entries_by_mtime``
        （与 logs / edit-snapshots 共用，仅后缀不同）。
        """
        return await prune_entries_by_mtime(
            self._base, retention_days=retention_days, suffix=".json", min_interval_seconds=min_interval_seconds
        )

    def path_for(self, session_id: str) -> Path:
        """会话文件路径（校验 id 后给出；调用方可据此探测存在性，不写盘）。"""
        _validate_session_id(session_id)
        return self._base / f"{session_id}.json"

    def save(self, session_id: str, messages: list[Message], *, expected_version: int | None = None) -> str:
        """保存对话历史到 JSON 文件（原子写 + version 递增）。

        返回保存的文件路径。``expected_version`` 是**增量**语义：``None``（缺省）= 既有的
        last-write-wins（CLI 与运行落盘用这条）；给了数字则要求磁盘 ``version`` 相等，否则抛
        :class:`SessionConflictError` 且**不写文件**（网页的显式冲突检测）。

        磁盘上已有的 ``title`` 会被原样保留（由 :meth:`rename` 拥有）——否则「重命名后再对话，
        标题被抹掉」。
        """
        _validate_session_id(session_id)
        path = self._base / f"{session_id}.json"
        written_at = time.time()

        def update(raw: str) -> tuple[str, None]:
            version, title = _read_header(raw)
            if expected_version is not None and version != expected_version:
                raise SessionConflictError(
                    f"session {session_id!r} changed on disk (expected version {expected_version}, found {version})"
                )
            payload = _session_payload(session_id, version + 1, written_at, messages, title)
            return json.dumps(payload, ensure_ascii=False, indent=2), None

        atomic_update_text(path, update)
        return str(path)

    def create(self, session_id: str, *, title: str | None = None) -> SessionMetadata:
        """新建一个**空**会话文件（可选标题）并返回其元数据。

        已存在（非空文件）时抛 :class:`SessionConflictError`——新建绝不能覆盖既有对话。空文件
        （0 字节）视为「不存在」，与 :func:`atomic_update_text` 的「缺失即空串」语义一致。
        """
        _validate_session_id(session_id)
        normalized = validate_title(title) if title is not None else None
        path = self._base / f"{session_id}.json"
        created_at = time.time()

        def update(raw: str) -> tuple[str, None]:
            if raw.strip():
                raise SessionConflictError(f"session {session_id!r} already exists")
            payload = _session_payload(session_id, 1, created_at, [], normalized)
            return json.dumps(payload, ensure_ascii=False, indent=2), None

        atomic_update_text(path, update)
        return SessionMetadata(
            session_id=session_id,
            title=normalized or UNNAMED_SESSION_TITLE,
            message_count=0,
            version=1,
            timestamp=created_at,
            updated_at=_iso_timestamp(created_at),
        )

    def load(self, session_id: str) -> list[Message]:
        """从 JSON 文件恢复对话历史。

        文件不存在时返回空列表。version 用于日志记录，不做合并冲突处理。

        **损坏文件仍返回空列表**（既有 CLI 语义，不改）；需要区分「损坏」与「空」的调用方走
        :meth:`load_metadata`（它抛 :class:`SessionUnreadableError`）。
        """
        _validate_session_id(session_id)
        path = self._base / f"{session_id}.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        messages = [Message(**m) for m in data.get("messages", [])]
        return _complete_tool_transactions(messages)

    def load_metadata(self, session_id: str) -> SessionMetadata | None:
        """读单个会话的元数据；文件不存在返回 ``None``，不可解析抛 :class:`SessionUnreadableError`。"""
        _validate_session_id(session_id)
        path = self._base / f"{session_id}.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise SessionUnreadableError(f"session {session_id!r} cannot be read") from exc
        return _metadata_from_raw(session_id, raw)

    def list_metadata(self, *, limit: int = MAX_SESSION_LIST_LIMIT) -> list[SessionMetadata]:
        """列出会话元数据，按落盘 ``timestamp`` 降序，最多 ``limit`` 条。

        两条有界/容错口径：

        - **损坏文件不丢**：以 ``unreadable=True``（标题「不可读会话」、按文件 mtime 排序）出现在
          列表里，详情接口对它回 ``session_unreadable``；单条解析失败不拖垮整个列表（fail-soft）。
        - **大会话不数消息**：文件超过 :data:`MAX_SESSION_METADATA_BYTES` 时
          ``message_count=None``（D6：详情才给），避免列表逐文件解析数 MB JSON。
        """
        if not self._base.exists() or limit <= 0:
            return []
        entries: list[SessionMetadata] = []
        for path in self._base.glob("*.json"):
            try:
                info = path.stat()
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                entries.append(_unreadable_metadata(path.stem, mtime))
                continue
            try:
                entries.append(
                    _metadata_from_raw(
                        path.stem,
                        raw,
                        count_messages=info.st_size <= MAX_SESSION_METADATA_BYTES,
                    )
                )
            except SessionUnreadableError:
                logger.warning("Session file %s is unreadable; listing it as unreadable", path.name)
                entries.append(_unreadable_metadata(path.stem, info.st_mtime))
        entries.sort(key=lambda item: (item.timestamp, item.session_id), reverse=True)
        return entries[:limit]

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

    def rename(self, session_id: str, title: str, *, expected_version: int | None = None) -> SessionMetadata:
        """就地改写会话标题（**不动 ``messages``**），返回新元数据。

        - 会话不存在 → :class:`SessionNotFoundError`；不可解析 → :class:`SessionUnreadableError`；
        - ``expected_version`` 给定时与磁盘版本比对，不符 → :class:`SessionConflictError`（不写文件）；
        - 写入会**递增 version**（标题变更也是一次写入，客户端据此知道自己持有的版本已过期）；
        - ``messages`` 与文件里的未知键原样保留（只增/改 ``title``、``version`` 两个键）。
        """
        _validate_session_id(session_id)
        normalized = validate_title(title)
        path = self._base / f"{session_id}.json"
        result: SessionMetadata | None = None

        def update(raw: str) -> tuple[str, None]:
            nonlocal result
            if not raw.strip():
                raise SessionNotFoundError(f"no session {session_id!r}")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SessionUnreadableError(f"session {session_id!r} is not valid JSON") from exc
            if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
                raise SessionUnreadableError(f"session {session_id!r} has an unexpected structure")
            version = _coerce_version(data.get("version"))
            if expected_version is not None and version != expected_version:
                raise SessionConflictError(
                    f"session {session_id!r} changed on disk (expected version {expected_version}, found {version})"
                )
            updated = {**data, "title": normalized, "version": version + 1}
            result = _metadata_from_data(session_id, updated)
            return json.dumps(updated, ensure_ascii=False, indent=2), None

        atomic_update_text(path, update)
        if result is None:
            raise RuntimeError("session rename completed without a result")
        return result

    def delete(self, session_id: str) -> bool:
        """删除指定会话文件。返回是否成功删除。"""
        _validate_session_id(session_id)
        path = self._base / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False


__all__ = [
    "MAX_DERIVED_TITLE_CHARS",
    "MAX_SESSION_LIST_LIMIT",
    "MAX_SESSION_METADATA_BYTES",
    "MAX_SESSION_TITLE_CHARS",
    "UNNAMED_SESSION_TITLE",
    "UNREADABLE_SESSION_TITLE",
    "SessionMetadata",
    "SessionStore",
    "derive_title",
    "validate_title",
]
