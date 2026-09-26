"""Tests for session persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from heagent.context.session import (
    MAX_DERIVED_TITLE_CHARS,
    MAX_SESSION_METADATA_BYTES,
    MAX_SESSION_TITLE_CHARS,
    UNNAMED_SESSION_TITLE,
    UNREADABLE_SESSION_TITLE,
    SessionStore,
    derive_title,
    validate_title,
)
from heagent.exceptions import SessionConflictError, SessionNotFoundError, SessionUnreadableError
from heagent.types import Message, Role, ToolCall


def _msgs(*contents: str) -> list[Message]:
    roles = [Role.USER, Role.ASSISTANT, Role.SYSTEM, Role.TOOL]
    return [Message(role=roles[i % len(roles)], content=c) for i, c in enumerate(contents)]


class TestSessionStore:
    def test_save_and_load(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        msgs = _msgs("hello", "world")
        store.save("s1", msgs)

        loaded = store.load("s1")
        assert len(loaded) == 2
        assert loaded[0].content == "hello"
        assert loaded[1].content == "world"

    def test_load_nonexistent(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        assert store.load("ghost") == []

    def test_json_format(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        msgs = [Message(role=Role.USER, content="test")]
        path = store.save("fmt", msgs)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "session_id" in data
        assert "timestamp" in data
        assert data["session_id"] == "fmt"
        assert data["version"] == 1
        assert len(data["messages"]) == 1

    def test_roundtrip_with_tool_calls(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="c1", name="shell", arguments={"command": "ls"})],
            ),
            Message(role=Role.TOOL, content="file list", tool_call_id="c1", name="shell"),
        ]
        store.save("tools", msgs)
        loaded = store.load("tools")
        assert len(loaded) == 2
        assert loaded[0].tool_calls is not None
        assert loaded[0].tool_calls[0].name == "shell"

    def test_save_discards_incomplete_tool_call_transaction(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        messages = [
            Message(role=Role.USER, content="inspect the directory"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="c1", name="shell", arguments={"command": "ls"})],
            ),
        ]

        store.save("interrupted", messages)

        assert [message.role for message in store.load("interrupted")] == [Role.USER]

    def test_load_discards_corrupt_tool_call_suffix(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        path = tmp_path / "sessions" / "corrupt.json"  # type: ignore[operator]
        path.parent.mkdir()
        path.write_text(
            json.dumps(
                {
                    "session_id": "corrupt",
                    "messages": [
                        Message(role=Role.USER, content="first").model_dump(),
                        Message(
                            role=Role.ASSISTANT,
                            content="",
                            tool_calls=[ToolCall(id="c1", name="shell", arguments={"command": "ls"})],
                        ).model_dump(),
                        Message(role=Role.USER, content="must not reach the API").model_dump(),
                    ],
                }
            ),
            encoding="utf-8",
        )

        loaded = store.load("corrupt")

        assert [message.content for message in loaded] == ["first"]

    def test_list_sessions(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        store.save("b", _msgs("b"))
        store.save("a", _msgs("a"))
        assert store.list_sessions() == ["a", "b"]

    def test_delete(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        store.save("del", _msgs("x"))
        assert store.delete("del") is True
        assert store.load("del") == []
        assert store.delete("del") is False

    def test_overwrite(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        store.save("ow", _msgs("v1"))
        store.save("ow", _msgs("v2"))
        loaded = store.load("ow")
        assert len(loaded) == 1
        assert loaded[0].content == "v2"
        data = json.loads((tmp_path / "sessions" / "ow.json").read_text(encoding="utf-8"))  # type: ignore[operator]
        assert data["version"] == 2


# ──────────────────────────────────────────────────────────────────────────────
# Story 50-3：会话持久化 API 的存储层
#   T1 冲突检测 · T2 元数据 · T3 标题派生 · T4 重命名保真 · T5 损坏文件 · AC8 CLI 兼容
# ──────────────────────────────────────────────────────────────────────────────
def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(base_dir=str(tmp_path / "sessions"))


def _payload(tmp_path: Path, session_id: str) -> dict:
    return json.loads((tmp_path / "sessions" / f"{session_id}.json").read_text(encoding="utf-8"))


def _rewrite_timestamp(tmp_path: Path, session_id: str, timestamp: float) -> None:
    """就地改写磁盘 ``timestamp``：排序断言不依赖真实时钟粒度（两次 save 可能同微秒）。"""
    path = tmp_path / "sessions" / f"{session_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["timestamp"] = timestamp
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class TestCliCompatibleWrites:
    """CLI 不传 ``expected_version`` ⇒ last-write-wins 与落盘形状均与改造前一致（I13 / AC8）。"""

    def test_payload_keys_keep_legacy_order(self, tmp_path: Path) -> None:
        _store(tmp_path).save("fmt", [Message(role=Role.USER, content="hi")])
        assert list(_payload(tmp_path, "fmt")) == ["session_id", "version", "timestamp", "messages"]

    def test_save_without_expected_version_still_overwrites(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save("ow", [Message(role=Role.USER, content="v1")])
        store.save("ow", [Message(role=Role.USER, content="v2")])
        data = _payload(tmp_path, "ow")
        assert data["version"] == 2
        assert [message["content"] for message in data["messages"]] == ["v2"]
        assert "title" not in data


class TestConflictDetection:
    def test_mismatch_raises_and_leaves_file_untouched(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save("s", [Message(role=Role.USER, content="first")])
        before = (tmp_path / "sessions" / "s.json").read_text(encoding="utf-8")
        with pytest.raises(SessionConflictError):
            store.save("s", [Message(role=Role.USER, content="clobber")], expected_version=99)
        assert (tmp_path / "sessions" / "s.json").read_text(encoding="utf-8") == before

    def test_matching_version_writes_and_advances(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save("s", [Message(role=Role.USER, content="first")])
        store.save("s", [Message(role=Role.USER, content="second")], expected_version=1)
        assert _payload(tmp_path, "s")["version"] == 2

    def test_missing_file_is_version_zero(self, tmp_path: Path) -> None:
        _store(tmp_path).save("fresh", [], expected_version=0)
        assert _payload(tmp_path, "fresh")["version"] == 1

    def test_conflict_still_surfaces_after_a_rename(self, tmp_path: Path) -> None:
        """重命名也递增 version ⇒ 客户端持有的旧版本号必须被判为冲突（AC4 的同源语义）。"""
        store = _store(tmp_path)
        store.save("s", [Message(role=Role.USER, content="x")])
        store.rename("s", "title")
        with pytest.raises(SessionConflictError):
            store.save("s", [Message(role=Role.USER, content="y")], expected_version=1)


class TestMetadataRead:
    def test_load_metadata_missing_returns_none(self, tmp_path: Path) -> None:
        assert _store(tmp_path).load_metadata("ghost") is None

    def test_load_metadata_reports_header_and_count(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save("s", _msgs("hello", "world"))
        meta = store.load_metadata("s")
        assert meta is not None
        assert (meta.session_id, meta.message_count, meta.version, meta.unreadable) == ("s", 2, 1, False)
        assert meta.title == "hello"  # 无 title 字段 ⇒ 派生自首条非空 user 消息
        assert meta.updated_at is not None

    def test_load_metadata_raises_on_corrupt_file(self, tmp_path: Path) -> None:
        path = tmp_path / "sessions" / "bad.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SessionUnreadableError):
            _store(tmp_path).load_metadata("bad")

    def test_load_metadata_rejects_unexpected_structure(self, tmp_path: Path) -> None:
        path = tmp_path / "sessions" / "shape.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"session_id": "shape"}), encoding="utf-8")
        with pytest.raises(SessionUnreadableError):
            _store(tmp_path).load_metadata("shape")

    def test_load_returns_empty_for_corrupt_file_but_metadata_does_not(self, tmp_path: Path) -> None:
        """既有 CLI 语义（损坏 = 空列表）与新的显式状态必须**同时**成立（AC9 / D1）。"""
        path = tmp_path / "sessions" / "bad.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        store = _store(tmp_path)
        assert store.load("bad") == []
        with pytest.raises(SessionUnreadableError):
            store.load_metadata("bad")

    def test_list_metadata_sorts_by_timestamp_descending(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save("older", [Message(role=Role.USER, content="a")])
        store.save("newer", [Message(role=Role.USER, content="b")])
        _rewrite_timestamp(tmp_path, "older", 100.0)
        _rewrite_timestamp(tmp_path, "newer", 200.0)
        assert [item.session_id for item in store.list_metadata()] == ["newer", "older"]

    def test_list_metadata_limit_and_empty_directory(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert store.list_metadata() == []
        for name in ("a", "b", "c"):
            store.save(name, [Message(role=Role.USER, content=name)])
        assert len(store.list_metadata(limit=2)) == 2
        assert store.list_metadata(limit=0) == []

    def test_list_metadata_treats_invalid_message_entry_as_unreadable(self, tmp_path: Path) -> None:
        """畸形消息条目 = 不可解析：该会话标 unreadable，**不得**让整页列表抛异常。

        评审发现（镜头一 H1）：``_metadata_from_data`` 直接 ``Message(**item)``，pydantic 的
        ``ValidationError`` 会穿透 ``list_metadata`` 的 ``except SessionUnreadableError``——一条
        ``{"role": "user"}``（缺 ``content``）就能让 ``GET /api/projects/{id}/sessions`` 对**全部**
        会话回 500，与类 docstring 的 fail-soft 承诺矛盾。
        """
        store = _store(tmp_path)
        store.save("good", [Message(role=Role.USER, content="ok")])
        (tmp_path / "sessions" / "broken.json").write_text(
            json.dumps({"version": 1, "timestamp": 1.0, "messages": [{"role": "user"}]}), encoding="utf-8"
        )
        listed = {item.session_id: item for item in store.list_metadata()}
        assert set(listed) == {"good", "broken"}
        assert listed["good"].unreadable is False
        assert listed["broken"].unreadable is True
        assert listed["broken"].title == UNREADABLE_SESSION_TITLE

    def test_load_metadata_raises_unreadable_for_invalid_message_entry(self, tmp_path: Path) -> None:
        """同一份文件走详情路径 → 稳定 ``session_unreadable``（而不是不透明 500）。"""
        path = tmp_path / "sessions" / "broken.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "messages": [{"role": "user", "content": 42}]}), encoding="utf-8")
        with pytest.raises(SessionUnreadableError):
            _store(tmp_path).load_metadata("broken")

    def test_list_metadata_keeps_unreadable_file_visible(self, tmp_path: Path) -> None:
        """损坏文件**不得**从列表消失（否则等于静默丢数据，AC9）。"""
        store = _store(tmp_path)
        store.save("good", [Message(role=Role.USER, content="ok")])
        (tmp_path / "sessions" / "broken.json").write_text("{oops", encoding="utf-8")
        listed = {item.session_id: item for item in store.list_metadata()}
        assert set(listed) == {"good", "broken"}
        assert listed["broken"].unreadable is True
        assert listed["broken"].title == UNREADABLE_SESSION_TITLE
        assert listed["broken"].message_count is None

    def test_list_metadata_skips_message_count_for_oversized_session(self, tmp_path: Path) -> None:
        """D6：超过字节预算的会话在**列表**里不数消息（详情仍给）。"""
        store = _store(tmp_path)
        big = [Message(role=Role.USER, content="x" * 4096) for _ in range(MAX_SESSION_METADATA_BYTES // 4096 + 32)]
        store.save("big", big)
        assert (tmp_path / "sessions" / "big.json").stat().st_size > MAX_SESSION_METADATA_BYTES
        detail = store.load_metadata("big")
        assert detail is not None and detail.message_count == len(big)
        assert [item.message_count for item in store.list_metadata()] == [None]


class TestTitleDerivation:
    def test_derive_title_uses_first_non_empty_user_message(self) -> None:
        messages = [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="   "),
            Message(role=Role.USER, content="  fix\n the   bug  "),
            Message(role=Role.USER, content="later"),
        ]
        assert derive_title(messages) == "fix the bug"

    def test_derive_title_truncates_and_falls_back(self) -> None:
        derived = derive_title([Message(role=Role.USER, content="y" * 500)])
        assert derived.endswith("…")
        assert len(derived) == MAX_DERIVED_TITLE_CHARS
        assert derive_title([Message(role=Role.ASSISTANT, content="hi")]) == UNNAMED_SESSION_TITLE
        assert derive_title([]) == UNNAMED_SESSION_TITLE

    def test_validate_title_collapses_and_rejects_out_of_bounds(self) -> None:
        assert validate_title("  two\nlines  ") == "two lines"
        assert len(validate_title("z" * MAX_SESSION_TITLE_CHARS)) == MAX_SESSION_TITLE_CHARS
        with pytest.raises(ValueError):
            validate_title("   ")
        with pytest.raises(ValueError):
            validate_title("z" * (MAX_SESSION_TITLE_CHARS + 1))


class TestTitleFidelity:
    def test_save_preserves_title_written_by_rename(self, tmp_path: Path) -> None:
        """AC8 的正向：重命名后继续对话，``save`` 不得抹掉标题。"""
        store = _store(tmp_path)
        store.save("s", [Message(role=Role.USER, content="hello")])
        store.rename("s", "My title")
        store.save(
            "s",
            [Message(role=Role.USER, content="hello"), Message(role=Role.ASSISTANT, content="world")],
        )
        data = _payload(tmp_path, "s")
        assert data["title"] == "My title"
        assert [message["content"] for message in data["messages"]] == ["hello", "world"]

    def test_rename_keeps_messages_and_unknown_keys(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save("s", [Message(role=Role.USER, content="keep me")])
        raw = _payload(tmp_path, "s")
        raw["future_field"] = {"nested": True}
        (tmp_path / "sessions" / "s.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = store.rename("s", "  renamed  ")

        data = _payload(tmp_path, "s")
        assert meta.title == "renamed"
        assert (data["title"], data["version"]) == ("renamed", 2)
        assert data["future_field"] == {"nested": True}
        assert [message["content"] for message in data["messages"]] == ["keep me"]

    def test_title_never_leaks_into_messages(self, tmp_path: Path) -> None:
        """AC8 的反向：CLI 的读取路径（``load``）不受标题影响。"""
        store = _store(tmp_path)
        store.save("s", [Message(role=Role.USER, content="hello")])
        store.rename("s", "session title")
        assert [message.content for message in store.load("s")] == ["hello"]

    def test_rename_missing_session_raises_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(SessionNotFoundError):
            _store(tmp_path).rename("ghost", "title")

    def test_rename_corrupt_session_raises_unreadable(self, tmp_path: Path) -> None:
        path = tmp_path / "sessions" / "bad.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SessionUnreadableError):
            _store(tmp_path).rename("bad", "title")

    def test_rename_honours_expected_version(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save("s", [Message(role=Role.USER, content="x")])
        with pytest.raises(SessionConflictError):
            store.rename("s", "title", expected_version=7)
        assert "title" not in _payload(tmp_path, "s")
        assert store.rename("s", "title", expected_version=1).title == "title"


class TestSessionCreate:
    def test_create_writes_empty_session_with_title(self, tmp_path: Path) -> None:
        meta = _store(tmp_path).create("new", title="  Fresh  ")
        data = _payload(tmp_path, "new")
        assert (meta.title, meta.message_count, meta.version) == ("Fresh", 0, 1)
        assert (data["messages"], data["title"], data["version"]) == ([], "Fresh", 1)

    def test_create_without_title_leaves_the_field_absent(self, tmp_path: Path) -> None:
        meta = _store(tmp_path).create("new")
        assert meta.title == UNNAMED_SESSION_TITLE
        assert "title" not in _payload(tmp_path, "new")

    def test_create_refuses_to_overwrite_existing_session(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save("dup", [Message(role=Role.USER, content="keep")])
        with pytest.raises(SessionConflictError):
            store.create("dup")
        assert [message.content for message in store.load("dup")] == ["keep"]

    def test_create_treats_empty_file_as_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "sessions" / "blank.json"
        path.parent.mkdir(parents=True)
        path.write_text("", encoding="utf-8")
        assert _store(tmp_path).create("blank").version == 1


class TestSessionIdGuards:
    def test_path_for_validates_without_touching_disk(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        with pytest.raises(ValueError):
            store.path_for("../escape")
        target = store.path_for("ok-1")
        assert target.name == "ok-1.json"
        assert not target.exists()

    @pytest.mark.parametrize("session_id", ["../escape", "a/b", "a\\b", "", "x" * 129, "ab.cd", "abc\n"])
    def test_invalid_ids_are_rejected_before_any_write(self, tmp_path: Path, session_id: str) -> None:
        store = _store(tmp_path)
        for call in (
            lambda: store.load_metadata(session_id),
            lambda: store.rename(session_id, "title"),
            lambda: store.create(session_id),
            lambda: store.save(session_id, []),
        ):
            with pytest.raises(ValueError):
                call()
        assert not (tmp_path / "sessions").exists()
