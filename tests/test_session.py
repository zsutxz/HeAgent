"""Tests for session persistence."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from heagent.context.session import (
    _read_head,
    WINDOWS_RESERVED_DEVICE_NAMES,
    validate_session_id,
    MAX_DERIVED_TITLE_CHARS,
    MAX_SESSION_METADATA_BYTES,
    MAX_SESSION_TITLE_CHARS,
    UNNAMED_SESSION_TITLE,
    UNREADABLE_SESSION_TITLE,
    SessionStore,
    derive_title,
    validate_title,
)
from heagent.pub.exceptions import SessionConflictError, SessionNotFoundError, SessionUnreadableError
from heagent.pub.types import Message, Role, ToolCall


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


class TestReservedDeviceNames:
    """Windows 保留设备名必须被拒（2026-09-27 闭合台账同名条目）。

    判据是**拒绝**而不是「能不能写」：Windows 上 `NUL.json` 解析为空设备，`exists()` 恒真、
    读取得空串、写入被丢弃——所以只有拒绝才能在两个平台上给出同一结论。
    """

    @pytest.mark.parametrize("name", ["NUL", "nul", "Nul", "CON", "PRN", "AUX", "COM1", "lpt9"])
    def test_path_for_rejects_reserved_device_names(self, tmp_path: object, name: str) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        with pytest.raises(ValueError, match="reserved device name"):
            store.path_for(name)

    def test_save_refuses_instead_of_writing_to_the_null_device(self, tmp_path: object) -> None:
        """回归原缺陷：放行 `NUL` 时 `save` 在 Windows 上写向空设备——不报错、不落盘、也列不出来。"""
        base = tmp_path / "sessions"  # type: ignore[operator]
        store = SessionStore(base_dir=str(base))
        with pytest.raises(ValueError, match="reserved device name"):
            store.save("NUL", _msgs("secret"))
        assert not base.exists() or not list(base.iterdir())

    @pytest.mark.parametrize("name", ["abc123", "NUL2", "CONS", "com0", "lpt", "x" * 128])
    def test_lookalikes_are_still_accepted(self, tmp_path: object, name: str) -> None:
        """只有**精确**的保留名是设备：`NUL2` / `CONS` / `com0` 都是普通文件，不得误伤。"""
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        assert store.path_for(name).name == f"{name}.json"

    def test_reserved_set_is_the_windows_one(self) -> None:
        """22 项：4 个经典名 + COM1-9 + LPT1-9（大小写不敏感由 `.upper()` 比较承担）。"""
        assert len(WINDOWS_RESERVED_DEVICE_NAMES) == 22
        assert {"CON", "PRN", "AUX", "NUL"} <= WINDOWS_RESERVED_DEVICE_NAMES
        assert all(name == name.upper() for name in WINDOWS_RESERVED_DEVICE_NAMES)


class TestValidateSessionIdShape:
    """公开校验器与存储路径解析必须同源（CLI `--resume` 直接用前者 fail-fast）。"""

    def test_validator_matches_path_for(self, tmp_path: object) -> None:
        store = SessionStore(base_dir=str(tmp_path / "sessions"))  # type: ignore[operator]
        for candidate in ["ok-1", "NUL", "nul", "../escape", "x" * 129, "", "a b"]:
            try:
                store.path_for(candidate)
                accepted = True
            except ValueError:
                accepted = False
            if accepted:
                validate_session_id(candidate)
            else:
                with pytest.raises(ValueError):
                    validate_session_id(candidate)


class TestConcurrentWriteObservability:
    """会话并发写入可观测性测试（台账条目：同一会话文件的两个写者会整份覆盖对方的历史）。"""

    def test_version_jump_warning_when_last_known_version_provided(self, tmp_path: Path, caplog) -> None:
        """当提供 last_known_version 且磁盘版本跳过多个版本时，发出 WARNING 日志。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")

        store = _store(tmp_path)
        # 写者 A：初始保存，version=1
        store.save("s1", _msgs("a"))
        # 写者 B：中间保存两次，version=2, 3
        store.save("s1", _msgs("b1", "b2"))
        store.save("s1", _msgs("b1", "b2", "b3"))
        # 写者 A：以为自己的 version=1 之后应该是 2，但磁盘已经是 3 了（跳过了 version=2）
        store.save("s1", _msgs("a", "a2"), last_known_version=1)

        assert "version jumped from 1 to 3" in caplog.text
        assert "Another writer may have modified this session concurrently" in caplog.text

    def test_no_warning_when_version_increments_normally(self, tmp_path: Path, caplog) -> None:
        """正常递增时不发出告警。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")

        store = _store(tmp_path)
        store.save("s1", _msgs("a"))
        # 从 version=1 到 version=2 是正常递增，不算跳跃
        store.save("s1", _msgs("a", "b"), last_known_version=1)

        assert "version jumped" not in caplog.text

    def test_no_warning_when_last_known_version_not_provided(self, tmp_path: Path, caplog) -> None:
        """不提供 last_known_version 时不检测（保持既有 last-write-wins 行为）。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")

        store = _store(tmp_path)
        store.save("s1", _msgs("a"))
        store.save("s1", _msgs("b1", "b2"))
        store.save("s1", _msgs("c"))

        assert "version jumped" not in caplog.text

    def test_warning_includes_session_id_and_versions(self, tmp_path: Path, caplog) -> None:
        """告警消息包含会话 ID 和具体版本号，便于诊断。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")

        store = _store(tmp_path)
        store.save("my-session", _msgs("a"))
        store.save("my-session", _msgs("b"))
        store.save("my-session", _msgs("c"))
        # 从 version=1 直接到 version=3，跳过了 version=2
        store.save("my-session", _msgs("d"), last_known_version=1)

        assert "'my-session'" in caplog.text
        assert "from 1 to 3" in caplog.text


def _users(*texts: str) -> list[Message]:
    """只有 USER 轮次的消息序列（``_msgs`` 会循环出 SYSTEM/TOOL，会干扰并发合并的比对语义）。"""
    return [Message(role=Role.USER, content=text) for text in texts]


class TestConcurrentWriteMerge:
    """台账条目「同一会话文件的两个写者会整份覆盖对方的历史」的**修复**判据。

    场景：CLI 与网页入口共享同一 ``.heagent/sessions``，两边各自 ``load → … → save``，后写者用
    整份消息列表替换掉对方的整轮对话（静默数据丢失）。``save(base=...)`` 给定时改为**保守合并**
    ——只在「三方的非 SYSTEM 投影构成同一前缀」时把两段接起来；任何无法安全判定的形态都退回
    last-write-wins（最坏情况与改造前逐字一致）并记 WARNING。
    """

    def test_another_writers_tail_is_merged_not_overwritten(self, tmp_path: Path, caplog) -> None:
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")
        store = _store(tmp_path)
        store.save("s1", _users("base"))
        base = store.load("s1")  # 两个写者各自 load 到的同一份基线

        store.save("s1", base + _users("A1", "A2"), base=base)  # 写者 A（CLI）
        store.save("s1", base + _users("B1"), base=base)  # 写者 B（网页运行，同一基线）

        assert [m.content for m in store.load("s1")] == ["base", "A1", "A2", "B1"]
        assert "another writer appended 2 message(s)" in caplog.text

    def test_merge_keeps_our_system_header_only(self, tmp_path: Path) -> None:
        """合并后的列表只保留**本次** writer 的 SYSTEM（SYSTEM 由每次 run 重建，load 时会被剔除）。"""
        store = _store(tmp_path)
        store.save("s1", [Message(role=Role.SYSTEM, content="old system"), Message(role=Role.USER, content="base")])
        base = store.load("s1")

        store.save("s1", base + _users("A1"), base=base)
        store.save(
            "s1",
            [Message(role=Role.SYSTEM, content="new system"), *base, *_users("B1")],
            base=base,
        )

        loaded = store.load("s1")
        assert loaded[0].role is Role.SYSTEM and loaded[0].content == "new system"
        assert [m.role for m in loaded[1:]] == [Role.USER, Role.USER, Role.USER]
        assert [m.content for m in loaded] == ["new system", "base", "A1", "B1"]

    def test_a_rewritten_shared_prefix_falls_back_instead_of_guessing(self, tmp_path: Path, caplog) -> None:
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")
        store = _store(tmp_path)
        store.save("s1", _users("base", "second"))
        base = store.load("s1")

        # 关键：改写后的历史**比基线更长** —— 否则「磁盘比基线短」会由另一条分支兜住，
        # 这条判据就测不出「共享前缀必须一致」这个护栏本身。
        store.save("s1", _users("rewritten-a", "rewritten-b", "rewritten-c"))
        store.save("s1", base + _users("B1"), base=base)

        assert [m.content for m in store.load("s1")] == ["base", "second", "B1"]  # 回退到 last-write-wins
        assert "last-write-wins" in caplog.text
        assert "kept both conversations" not in caplog.text

    def test_a_truncated_file_falls_back(self, tmp_path: Path, caplog) -> None:
        """磁盘比基线**短**（对方删了历史）：同样无法判定，回退而不是拼出个四不像。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")
        store = _store(tmp_path)
        store.save("s1", _users("a", "b", "c"))
        base = store.load("s1")

        store.save("s1", _users("a"))
        store.save("s1", base + _users("B1"), base=base)

        assert [m.content for m in store.load("s1")] == ["a", "b", "c", "B1"]
        assert "last-write-wins" in caplog.text

    def test_an_unreadable_file_never_blocks_the_save(self, tmp_path: Path, caplog) -> None:
        """损坏文件不得让保存失败（与 ``_read_header`` 的既有立场一致）：判别不出 ⇒ 原样写入。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")
        store = _store(tmp_path)
        store.save("s1", _users("base"))
        base = store.load("s1")
        (tmp_path / "s1.json").write_bytes(b"{not json")

        store.save("s1", base + _users("B1"), base=base)

        assert [m.content for m in store.load("s1")] == ["base", "B1"]

    def test_an_unchanged_file_takes_the_plain_path(self, tmp_path: Path, caplog) -> None:
        """基线与磁盘一致（最常见）：零额外行为、零告警。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")
        store = _store(tmp_path)
        store.save("s1", _users("base"))
        base = store.load("s1")

        path = store.save("s1", base + _users("B1"), base=base)

        assert [m.content for m in store.load("s1")] == ["base", "B1"]
        assert "kept both conversations" not in caplog.text and "last-write-wins" not in caplog.text
        assert path.endswith("s1.json")

    def test_a_base_that_is_not_a_prefix_of_ours_falls_back(self, tmp_path: Path, caplog) -> None:
        """调用方给的 base 与要写的内容对不上（陈旧/错配）：不得据此合并，回退并告警。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")
        store = _store(tmp_path)
        store.save("s1", _users("x", "y"))

        # base 声明「磁盘上本来是 [z]」，但它既不是磁盘内容、也不是我们要写的内容的前缀
        store.save("s1", _users("ours"), base=_users("z"))

        assert [m.content for m in store.load("s1")] == ["ours"]
        assert "last-write-wins" in caplog.text

    def test_an_identical_tail_is_not_appended_twice(self, tmp_path: Path) -> None:
        """两个写者产出**同一条尾巴**（重复写）时不追加第二份。"""
        store = _store(tmp_path)
        store.save("s1", _users("base"))
        base = store.load("s1")

        store.save("s1", base + _users("same"), base=base)
        store.save("s1", base + _users("same"), base=base)

        assert [m.content for m in store.load("s1")] == ["base", "same"]

    def test_expected_version_still_wins_over_merging(self, tmp_path: Path) -> None:
        """显式的 ``expected_version`` 冲突检测优先：给了它就必须抛，不得被合并悄悄放行。"""
        store = _store(tmp_path)
        store.save("s1", _users("base"))
        base = store.load("s1")
        store.save("s1", base + _users("A1"), base=base)

        with pytest.raises(SessionConflictError):
            store.save("s1", base + _users("B1"), expected_version=1, base=base)

    def test_without_base_the_legacy_behaviour_is_unchanged(self, tmp_path: Path, caplog) -> None:
        """不传 ``base`` = 既有 last-write-wins（CLI 单写者与库调用方的现状逐字不变）。"""
        import logging

        caplog.set_level(logging.WARNING, logger="heagent.context.session")
        store = _store(tmp_path)
        store.save("s1", _users("base"))
        base = store.load("s1")

        store.save("s1", base + _users("A1"))
        store.save("s1", base + _users("B1"))

        assert [m.content for m in store.load("s1")] == ["base", "B1"]
        assert "kept both conversations" not in caplog.text


class TestOversizedSessionListing:
    """超过 `MAX_SESSION_METADATA_BYTES` 的会话必须**有界**读取（台账「控制台阻塞 I/O」条目）。

    原实现：列表对每个文件 `read_text` 整份（200 × MB 级）；`count_messages=False` 只省了计数、
    没省读。现改为只读头部——落盘键序保证元数据都排在 `messages` 之前。
    """

    def _write_big(self, base: Path, *, title: str = "Big one", fill: int = 300) -> Path:
        base.mkdir(parents=True, exist_ok=True)
        path = base / "big.json"
        payload = {
            "session_id": "big",
            "version": 3,
            "timestamp": 1700000000.5,
            "title": title,
            "messages": [{"role": "user", "content": "x" * 4096} for _ in range(fill)],
        }
        path.write_bytes(json.dumps(payload).encode("utf-8"))
        assert path.stat().st_size > MAX_SESSION_METADATA_BYTES
        return path

    def test_head_read_never_exceeds_the_cap(self, tmp_path: object) -> None:
        path = self._write_big(tmp_path / "sessions")  # type: ignore[operator]
        head = _read_head(path, 1024)
        assert len(head.encode("utf-8")) <= 1024
        assert '"title"' in head

    def test_listing_of_a_big_session_does_not_read_it_in_full(self, tmp_path: object, monkeypatch) -> None:  # noqa: ANN001
        base = tmp_path / "sessions"  # type: ignore[operator]
        path = self._write_big(base)
        store = SessionStore(base_dir=str(base))
        original = Path.read_text

        def guarded(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            if self == path:
                raise AssertionError("oversized session was read in full")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", guarded)
        listed = store.list_metadata()

        assert [item.session_id for item in listed] == ["big"]
        meta = listed[0]
        assert meta.title == "Big one"  # 头部字段照旧可用
        assert meta.message_count is None  # D6：大会话详情才给
        assert meta.version == 3
        assert meta.timestamp == 1700000000.5

    def test_cap_boundary_inside_a_multibyte_character_is_tolerated(self, tmp_path: object) -> None:
        """cap 落在多字节字符中间时只裁掉不完整尾序列，不得把文件判成「不可读」。"""
        path = tmp_path / "cjk.txt"  # type: ignore[operator]
        path.write_bytes(("中" * 10).encode("utf-8"))  # 每字符 3 字节
        assert _read_head(path, 4) == "中"
        assert _read_head(path, 5) == "中"
        assert _read_head(path, 6) == "中中"

    def test_broken_encoding_still_lists_as_unreadable(self, tmp_path: object) -> None:
        """严格解码语义不变：真坏编码的大文件仍旧是「不可读会话」，不被静默降级成未命名。"""
        base = tmp_path / "sessions"  # type: ignore[operator]
        base.mkdir(parents=True, exist_ok=True)
        path = base / "bad.json"
        path.write_bytes(b"\xff\xfe" + b"x" * (MAX_SESSION_METADATA_BYTES + 10))
        listed = SessionStore(base_dir=str(base)).list_metadata()
        assert [item.session_id for item in listed] == ["bad"]
        assert listed[0].unreadable is True


class TestSessionPruneReapsOrphanLocks:
    """会话 prune 顺带回收**孤儿**锁（在用会话的锁两条门槛都不满足，绝不误删）。"""

    async def test_prune_reaps_aged_orphan_lock_and_keeps_live_ones(self, tmp_path) -> None:
        base = tmp_path / "sessions"
        base.mkdir(parents=True, exist_ok=True)
        store = SessionStore(base_dir=str(base))
        store.save("live", _msgs("hi"))
        live_lock = base / "live.json.lock"
        assert live_lock.exists(), "会话写入应产生同名锁（persist 的既有形态）"

        orphan = base / "gone.json.lock"
        orphan.write_bytes(b"\n")
        stale = time.time() - 40 * 86400  # 超过 30 天保留期
        os.utime(orphan, (stale, stale))

        removed = await store.prune(retention_days=30)

        assert removed == 0, "live 会话未过期，不应被回收"
        assert not orphan.exists(), "超龄孤儿锁应随 prune 回收"
        assert live_lock.exists(), "在用会话的锁不得被回收"
        assert (base / "live.json").exists()


class TestHeadMetadataScope:
    """`_metadata_from_head` 的作用域与真实性（2026-09-27 复审发现）。"""

    def test_message_payload_cannot_forge_the_listed_title(self, tmp_path: object) -> None:
        """消息里的 `"title"` 是**数据**：头部提取必须限定在 `messages` 之前。

        工具参数是**未转义**的 JSON 键，故消息体里的 `"title": …` 会与元数据字段同形；不限定作用域
        时列表标题会被它顶掉（正文里的转义引号 `\"title\"` 反而安全，故这条走 arguments 而非 content）。
        """
        base = tmp_path / "sessions"  # type: ignore[operator]
        base.mkdir(parents=True, exist_ok=True)
        path = base / "forged.json"
        payload = {
            "session_id": "forged",
            "version": 1,
            "timestamp": 1700000000.0,
            "messages": [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "c1", "name": "demo", "arguments": {"title": "FORGED-FROM-ARGS", "blob": "x" * 4096}}
                    ],
                },
                *[{"role": "user", "content": "x" * 4096} for _ in range(300)],
            ],
        }
        path.write_bytes(json.dumps(payload).encode("utf-8"))
        assert path.stat().st_size > MAX_SESSION_METADATA_BYTES

        meta = SessionStore(base_dir=str(base)).list_metadata()[0]

        assert meta.title == UNNAMED_SESSION_TITLE, meta.title


def test_count_sessions_counts_files_without_parsing(tmp_path: Path) -> None:
    """A18：真实规模只能数文件——列表接口有硬上限，列表长度不等于总数。"""
    store = SessionStore(base_dir=str(tmp_path / "sessions"))
    assert store.count_sessions() == 0
    store.save("s0", _msgs("a"))
    store.save("s1", _msgs("b"))
    assert store.count_sessions() == 2
    # `.lock`（以及任何非 `.json` 文件）不计入
    (tmp_path / "sessions" / "s0.json.lock").write_text("", encoding="utf-8")
    assert store.count_sessions() == 2
