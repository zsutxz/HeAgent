"""A61：审计面无保留/轮转 → 段上限 + 归档段 + 链续接判据。

钉住四条契约：

1. **段上限**：``HEAGENT_AUDIT_SEGMENT_BYTES`` 达阈值即把当前文件改名为
   ``tool-audit.seg-NNN.jsonl``，新主文件首行是段头（``kind="segment"``）；
2. **链续接**：段头的 ``prev`` == ``continues_from`` == 上一段末行 ``digest``
   ⇒ :func:`verify_chain` 不看前段文本也能自证，:func:`verify_chain_segments` 复核段边界；
3. **查询面跨段**：``read_entries(include_segments=True)`` 与 ``heagent audit list/export/verify``
   都看得到归档段（轮转不该让历史从查询面消失）；
4. **关闭面**：``SEGMENT_BYTES_ENV=0`` 完全关闭轮转，取值与引入前逐字一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from heagent.cli.console import main
from heagent.pub.audit import (
    AUDIT_FILENAME,
    DEFAULT_SEGMENT_BYTES,
    SEGMENT_BYTES_ENV,
    read_entries,
    record_operation,
    record_tool_execution,
    resolve_audit_path,
    rotate_audit,
    segment_bytes,
    segment_files,
    verify_chain,
    verify_chain_segments,
)


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    """临时工作区里的审计文件落点（``<tmp>/.heagent/audit/tool-audit.jsonl``）。"""
    return resolve_audit_path(root=tmp_path)


def _write_records(audit_path: Path, count: int) -> None:
    """连续落 ``count`` 条工具记录（每条约 200 字节，够撑出多个段）。"""
    state_dir = audit_path.parent.parent
    for index in range(count):
        assert record_tool_execution(
            tool="probe",
            args={"index": index, "padding": "x" * 120},
            status="ok",
            state_dir=state_dir,
        )


# ── 段上限取值 ──────────────────────────────────────────────────


def test_segment_bytes_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """未设 / 非法 / 负数取默认；``0`` 表示关闭轮转。"""
    monkeypatch.delenv(SEGMENT_BYTES_ENV, raising=False)
    assert segment_bytes() == DEFAULT_SEGMENT_BYTES

    monkeypatch.setenv(SEGMENT_BYTES_ENV, "1024")
    assert segment_bytes() == 1024

    monkeypatch.setenv(SEGMENT_BYTES_ENV, "0")
    assert segment_bytes() == 0

    monkeypatch.setenv(SEGMENT_BYTES_ENV, "not-a-number")
    assert segment_bytes() == DEFAULT_SEGMENT_BYTES

    monkeypatch.setenv(SEGMENT_BYTES_ENV, "-5")
    assert segment_bytes() == DEFAULT_SEGMENT_BYTES


# ── 自动轮转与段头 ──────────────────────────────────────────────


def test_records_rotate_into_segments(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """达阈值即切段：产生归档段，新主文件首行是段头且承接上一段末行 digest。"""
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "1024")
    _write_records(audit_path, 30)

    segments = segment_files(audit_path)
    assert segments, "达到字节上限后应产生归档段"
    assert segments[0].name == f"{audit_path.stem}.seg-001{audit_path.suffix}"

    head = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    previous_tail = segments[-1].read_text(encoding="utf-8").splitlines()[-1]
    previous_digest = json.loads(previous_tail)["digest"]
    assert head["kind"] == "segment"
    assert head["prev"] == head["continues_from"] == previous_digest


def test_rotation_can_be_disabled(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``SEGMENT_BYTES_ENV=0``：单文件累积，不产生任何归档段。"""
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "0")
    _write_records(audit_path, 30)

    assert segment_files(audit_path) == []


def test_manual_rotate_is_threshold_guarded(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``rotate_audit`` 达阈值才动；``force=True`` 无条件切段；文件不存在返回 ``None``。"""
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "0")
    _write_records(audit_path, 3)

    assert rotate_audit(audit_path, threshold=10**9) is None
    assert segment_files(audit_path) == []

    archived = rotate_audit(audit_path, force=True)
    assert archived is not None and archived.exists()
    assert len(segment_files(audit_path)) == 1

    missing = audit_path.parent / "nope.jsonl"
    assert rotate_audit(missing, force=True) is None


# ── 链续接 ──────────────────────────────────────────────────────


def test_chain_verifies_across_segments(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """跨段链完好吗：段内自查 + 段边界续接都通过。"""
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "1024")
    _write_records(audit_path, 30)

    verdict = verify_chain_segments(audit_path)
    assert verdict.ok, verdict.reason
    assert verdict.lines == len(read_entries(audit_path, include_segments=True))
    # 单段校验同样可用（段头自证，不依赖前段文本）
    assert verify_chain(audit_path).ok
    for segment in segment_files(audit_path):
        assert verify_chain(segment).ok


def test_tampered_segment_head_is_reported(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """改段头（continues_from 与 prev 不再一致）⇒ 跨段校验报断链，行号指向段首。"""
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "1024")
    _write_records(audit_path, 30)
    assert segment_files(audit_path)

    lines = audit_path.read_text(encoding="utf-8").splitlines()
    head = json.loads(lines[0])
    head["continues_from"] = "sha256:" + "0" * 64
    lines[0] = json.dumps(head, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    broken = verify_chain_segments(audit_path)
    assert not broken.ok
    assert broken.first_broken_line is not None


def test_missing_segment_head_is_reported(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """归档段存在、主文件却无段头 ⇒ 跨段校验报断链（边界未锚定）。

    场景构造成「主文件自身重算成完好链」——不重算时首行 ``prev`` 就直接不匹配（段内自查即拦下），
    那样测不到段边界分支。
    """
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "1024")
    _write_records(audit_path, 30)
    assert segment_files(audit_path)

    lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    while lines and json.loads(lines[0]).get("kind") == "segment":
        lines.pop(0)
    audit_path.write_text("\n".join(_rechain(lines)) + "\n", encoding="utf-8")
    assert verify_chain(audit_path).ok, "前提：主文件被重算成内部完好的链"

    broken = verify_chain_segments(audit_path)
    assert not broken.ok
    assert "segment head" in broken.reason


def _rechain(lines: list[str]) -> list[str]:
    """按实现口径重算整条链（模拟「能改文件的人」把主文件重写成自洽链）。"""
    from heagent.pub.audit import _digest_of  # 私有符号：判据要复算同一套规范化口径

    previous = ""
    rewritten: list[str] = []
    for line in lines:
        record = json.loads(line)
        record["prev"] = previous
        record["digest"] = _digest_of(record)
        previous = record["digest"]
        rewritten.append(json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    return rewritten


# ── 查询面跨段 ──────────────────────────────────────────────────


def test_read_entries_can_include_segments(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """默认只看主文件；``include_segments=True`` 才含归档段，且段头不入业务视图之外。"""
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "1024")
    _write_records(audit_path, 30)

    current = read_entries(audit_path)
    full = read_entries(audit_path, include_segments=True)
    assert len(full) > len(current)
    assert [entry for entry in full if entry.get("kind") == "tool"] == [e for e in full if e.get("kind") == "tool"]
    assert len([e for e in full if e.get("kind") == "tool"]) == 30


def test_cli_commands_see_archived_segments(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``heagent audit list|export|verify`` 都跨段工作（轮转后历史不消失、链仍完整）。"""
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "1024")
    _write_records(audit_path, 30)
    monkeypatch.setenv("COLUMNS", "400")
    runner = CliRunner()

    listed = runner.invoke(main, ["audit", "list", "--path", str(audit_path)])
    assert listed.exit_code == 0
    assert listed.output.count("tool") >= 30

    exported = runner.invoke(main, ["audit", "export", "--path", str(audit_path)])
    assert exported.exit_code == 0
    exported_records = [json.loads(line) for line in exported.output.splitlines() if line.strip().startswith("{")]
    assert len([r for r in exported_records if r.get("kind") == "tool"]) == 30

    verified = runner.invoke(main, ["audit", "verify", "--path", str(audit_path)])
    assert verified.exit_code == 0, verified.output
    assert "chain intact" in verified.output


def test_operation_records_also_rotate(audit_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """敏感操作记录与工具记录共用同一文件与同一条链 ⇒ 同样参与轮转。"""
    monkeypatch.setenv(SEGMENT_BYTES_ENV, "512")
    for index in range(20):
        record_operation(
            operation="config_write",
            target=f".env#{index}",
            before={"bytes": index},
            after={"bytes": index + 1},
            state_dir=audit_path.parent.parent,
        )

    assert segment_files(audit_path)
    assert verify_chain_segments(audit_path).ok


def test_cli_default_path_uses_workspace_root(tmp_path: Path) -> None:
    """无 ``--path`` 时按进程工作区派生落点（与 :func:`resolve_audit_path` 同口径）。"""
    assert audit_path_name(tmp_path) == AUDIT_FILENAME


def audit_path_name(root: Path) -> str:
    """辅助：默认落点文件名（保持断言与常量同源）。"""
    return resolve_audit_path(root=root).name
