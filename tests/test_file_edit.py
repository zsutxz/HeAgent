"""Tests for the surgical edit primitive (``file_edit``) and edit receipts.

覆盖三组契约：

1. **编辑语义** —— 唯一命中要求、``replace_all``、失败时磁盘零改动；
2. **保真** —— CRLF / BOM / 未触及字节逐字节不变（本仓 2026-09-08 行尾治理的事故面）；
3. **回执与快照** —— ``+N -M`` diff、落盘前快照 + manifest 台账、快照失败不阻断编辑。
"""

from __future__ import annotations

import codecs
import json
from typing import TYPE_CHECKING

import pytest

import heagent.tools.edits as edits_mod
from heagent.engine.policy import PolicyEngine
from heagent.tools.builtins.file import file_edit, file_read, file_write
from heagent.tools.edits import MANIFEST_NAME, bind_edit_snapshot_run, snapshot_root
from heagent.tools.path_safety import reset_workspace_root, set_workspace_root
from heagent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

CRLF = b"\r\n"


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path) -> Generator[None, None, None]:
    set_workspace_root(tmp_path.resolve())
    yield
    reset_workspace_root()


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _snapshot_from_receipt(receipt: str, workspace: Path) -> Path:
    """从回执的 ``snapshot: <相对 workspace 的路径>`` 行解析快照绝对路径。"""
    line = next(line for line in receipt.splitlines() if line.startswith("snapshot: "))
    return (workspace / line.removeprefix("snapshot: ")).resolve()


def _last_manifest_record() -> dict[str, object]:
    """读回 manifest 最后一行（一次编辑一条记录）。"""
    text = (snapshot_root() / MANIFEST_NAME).read_text(encoding="utf-8")
    return json.loads(text.strip().splitlines()[-1])


class TestRegistration:
    def test_file_edit_registered(self) -> None:
        assert "file_edit" in ToolRegistry.get().list_names()

    def test_policy_fences_file_edit_paths(self) -> None:
        """file_edit 必须进 policy 路径预检表——否则「编辑」会是不受围栏约束的写入旁路。"""
        assert PolicyEngine._PATH_FIELDS["file_edit"] == ("path",)


class TestSnapshotScoping:
    async def test_bound_run_scopes_snapshot_directory(self, tmp_path: Path) -> None:
        """绑定 run 后快照必须落在该 run 的子目录——loop._runtime_scope 接线依赖此契约。"""
        _write_bytes(tmp_path / "f.txt", b"before\n")
        with bind_edit_snapshot_run("run-abc"):
            result = await file_edit("f.txt", "before", "after")
        snapshot = _snapshot_from_receipt(result, tmp_path)
        expected_dir = tmp_path / ".heagent" / "tmp" / "edit-snapshots" / "run-abc"
        assert snapshot.parent == expected_dir.resolve()

    async def test_unbound_snapshot_uses_workspace_directory(self, tmp_path: Path) -> None:
        """未绑定 run（直接调工具/子进程）退化为工作区级目录，不因缺 run 上下文而放弃留痕。"""
        _write_bytes(tmp_path / "f.txt", b"before\n")
        result = await file_edit("f.txt", "before", "after")
        snapshot = _snapshot_from_receipt(result, tmp_path)
        assert snapshot.parent == (tmp_path / ".heagent" / "tmp" / "edit-snapshots").resolve()


class TestEditSemantics:
    async def test_replaces_unique_snippet_and_keeps_rest(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "mod.py", b"def a():\n    return 1\n\n\ndef b():\n    return 2\n")
        result = await file_edit("mod.py", "    return 1", "    return 42")
        assert result.startswith("OK: edited mod.py")
        assert target.read_bytes() == b"def a():\n    return 42\n\n\ndef b():\n    return 2\n"

    async def test_receipt_contains_diff(self, tmp_path: Path) -> None:
        _write_bytes(tmp_path / "mod.py", b"alpha\nbeta\ngamma\n")
        result = await file_edit("mod.py", "beta", "BETA")
        assert "+1 -1" in result
        assert "-beta" in result
        assert "+BETA" in result

    async def test_missing_snippet_changes_nothing(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "mod.py", b"alpha\n")
        result = await file_edit("mod.py", "nonexistent", "x")
        assert result.startswith("Error: old_string not found")
        assert target.read_bytes() == b"alpha\n"

    async def test_ambiguous_snippet_is_refused(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "mod.py", b"same\nother\nsame\n")
        result = await file_edit("mod.py", "same", "changed")
        assert "matches 2 locations" in result
        assert "replace_all=true" in result
        assert target.read_bytes() == b"same\nother\nsame\n"

    async def test_replace_all_replaces_every_occurrence(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "mod.py", b"same\nother\nsame\n")
        result = await file_edit("mod.py", "same", "changed", replace_all=True)
        assert result.startswith("OK: edited mod.py (2 replacements)")
        assert target.read_bytes() == b"changed\nother\nchanged\n"

    async def test_identical_strings_rejected(self, tmp_path: Path) -> None:
        _write_bytes(tmp_path / "mod.py", b"alpha\n")
        result = await file_edit("mod.py", "alpha", "alpha")
        assert result.startswith("Error: file_edit is a no-op")

    async def test_empty_old_string_rejected(self, tmp_path: Path) -> None:
        _write_bytes(tmp_path / "mod.py", b"alpha\n")
        result = await file_edit("mod.py", "", "x")
        assert result.startswith("Error: old_string must not be empty")

    async def test_missing_file_reports_not_found(self, tmp_path: Path) -> None:
        result = await file_edit("nope.py", "a", "b")
        assert result == "Error: file not found: nope.py"

    async def test_directory_target_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        result = await file_edit("pkg", "a", "b")
        assert result.startswith("Error: path is a directory")

    async def test_path_escape_rejected(self, tmp_path: Path) -> None:
        result = await file_edit("../outside.py", "a", "b")
        assert result.startswith("Error: Path escapes current workspace")

    async def test_non_utf8_file_rejected(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "blob.bin", b"\xff\xfe\x00\x01binary")
        result = await file_edit("blob.bin", "a", "b")
        assert "not valid UTF-8" in result
        assert target.read_bytes() == b"\xff\xfe\x00\x01binary"

    async def test_file_write_can_overwrite_non_utf8(self, tmp_path: Path) -> None:
        """file_write 是覆写语义：旧内容不可解码不影响写入，只是回执退化为计数。"""
        target = _write_bytes(tmp_path / "blob.bin", b"\xff\xfe")
        result = await file_write("blob.bin", "text")
        assert result.startswith("OK: wrote blob.bin")
        assert "diff unavailable" in result
        assert target.read_bytes() == b"text"


class TestFidelity:
    async def test_crlf_line_endings_preserved(self, tmp_path: Path) -> None:
        body = "".join(f"line {i}\r\n" for i in range(50)).encode()
        target = _write_bytes(tmp_path / "crlf.txt", body)
        result = await file_edit("crlf.txt", "line 25", "line 25 changed")
        assert result.startswith("OK: edited crlf.txt")
        raw = target.read_bytes()
        assert raw.count(CRLF) == 50
        assert raw.replace(CRLF, b"").count(b"\n") == 0  # 未产生孤立 LF
        assert b"line 25 changed" + CRLF in raw
        assert b"line 24" + CRLF in raw and b"line 26" + CRLF in raw

    async def test_lf_line_endings_preserved(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "lf.txt", b"alpha\nbeta\ngamma\n")
        await file_edit("lf.txt", "beta", "BETA")
        assert target.read_bytes() == b"alpha\nBETA\ngamma\n"

    async def test_bom_preserved(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "bom.txt", codecs.BOM_UTF8 + b"alpha\r\nbeta\r\n")
        result = await file_edit("bom.txt", "beta", "beta2")
        assert result.startswith("OK: edited bom.txt")
        assert target.read_bytes() == codecs.BOM_UTF8 + b"alpha\r\nbeta2\r\n"

    async def test_crlf_in_old_string_is_tolerated(self, tmp_path: Path) -> None:
        """模型若把含 CRLF 的整段粘进来，归一化后仍应命中——否则是纯粹的可用性陷阱。"""
        target = _write_bytes(tmp_path / "crlf.txt", b"alpha\r\nbeta\r\n")
        result = await file_edit("crlf.txt", "alpha\r\nbeta", "alpha\nBETA")
        assert result.startswith("OK: edited crlf.txt")
        assert target.read_bytes() == b"alpha\r\nBETA\r\n"

    async def test_read_form_matches_edit_form(self, tmp_path: Path) -> None:
        """file_read 必须与 file_edit 的匹配形态一致（去 BOM + LF），否则模型无法照抄片段。"""
        target = _write_bytes(tmp_path / "bom.txt", codecs.BOM_UTF8 + b"alpha\r\nbeta\r\n")
        text = await file_read("bom.txt")
        assert text == "alpha\nbeta\n"
        assert "\ufeff" not in text
        result = await file_edit("bom.txt", text.splitlines()[1], "beta2")
        assert result.startswith("OK: edited bom.txt")
        assert target.read_bytes() == codecs.BOM_UTF8 + b"alpha\r\nbeta2\r\n"

    async def test_untouched_bytes_are_byte_identical(self, tmp_path: Path) -> None:
        """大文件只改一处：除目标片段外其余字节必须逐字节一致（含尾随换行）。"""
        body = b"".join(f"row-{i:03d}\n".encode() for i in range(300))
        target = _write_bytes(tmp_path / "big.txt", body)
        await file_edit("big.txt", "row-150", "ROW-150")
        assert target.read_bytes() == body.replace(b"row-150\n", b"ROW-150\n")


class TestReceiptsAndSnapshots:
    async def test_file_write_receipt_has_diff(self, tmp_path: Path) -> None:
        _write_bytes(tmp_path / "f.txt", b"a\nb\nc\n")
        result = await file_write("f.txt", "a\nB\nc\n")
        assert result.startswith("OK: wrote f.txt")
        assert "+1 -1" in result
        assert "-b" in result and "+B" in result

    async def test_file_write_new_file_receipt(self, tmp_path: Path) -> None:
        result = await file_write("fresh.txt", "one\ntwo\n")
        assert result.startswith("OK: wrote fresh.txt")
        assert "new file, 2 lines" in result

    async def test_file_write_does_not_translate_line_endings(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "f.txt", b"old\n")
        await file_write("f.txt", "a\nb\n")
        assert target.read_bytes() == b"a\nb\n"

    async def test_edit_snapshot_keeps_previous_content(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "f.txt", b"before\n")
        result = await file_edit("f.txt", "before", "after")
        assert _snapshot_from_receipt(result, tmp_path).read_bytes() == b"before\n"
        assert target.read_bytes() == b"after\n"

    async def test_write_snapshot_keeps_previous_content(self, tmp_path: Path) -> None:
        _write_bytes(tmp_path / "f.txt", b"before\n")
        result = await file_write("f.txt", "after\n")
        assert _snapshot_from_receipt(result, tmp_path).read_bytes() == b"before\n"

    async def test_snapshot_manifest_records_edit(self, tmp_path: Path) -> None:
        target = _write_bytes(tmp_path / "f.txt", b"before\n")
        await file_edit("f.txt", "before", "after")
        record = _last_manifest_record()
        assert record["op"] == "edit"
        assert record["path"] == str(target)
        assert record["bytes"] == len(b"before\n")

    async def test_new_file_has_no_snapshot(self, tmp_path: Path) -> None:
        result = await file_write("fresh.txt", "x\n")
        assert "snapshot: " not in result

    async def test_oversized_file_skips_snapshot(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(edits_mod, "MAX_SNAPSHOT_BYTES", 8)
        _write_bytes(tmp_path / "f.txt", b"way more than eight bytes\n")
        result = await file_edit("f.txt", "way", "WAY")
        assert result.startswith("OK: edited f.txt")
        assert "snapshot: " not in result

    async def test_snapshot_failure_does_not_block_edit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """快照是 best-effort：I/O 失败也必须让编辑落地，只是回执里没有 snapshot 行。"""

        def _boom() -> Path:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(edits_mod, "snapshot_root", _boom)
        target = _write_bytes(tmp_path / "f.txt", b"before\n")
        result = await file_edit("f.txt", "before", "after")
        assert result.startswith("OK: edited f.txt")
        assert "snapshot: " not in result
        assert target.read_bytes() == b"after\n"

    async def test_long_diff_is_bounded(self, tmp_path: Path) -> None:
        old = "".join(f"line {i}\n" for i in range(200))
        _write_bytes(tmp_path / "big.txt", old.encode())
        new = "".join(f"LINE {i}\n" for i in range(200))  # 每行都变 → 远超 diff 行数上限
        result = await file_write("big.txt", new)
        assert "more diff lines" in result
        assert len(result) < 2000
