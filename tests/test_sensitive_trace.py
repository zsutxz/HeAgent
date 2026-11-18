"""Story 67.3：敏感操作留痕（会话删除 / 技能删除 / 配置写入 + 哈希链校验）。

钉住四条契约：

1. 三类敏感操作各落一条 ``operation`` 记录，``before`` / ``after`` **只有摘要**；
2. 文件里搜不到明文敏感值（会话正文、技能正文、配置值都不落盘）；
3. 篡改任一行 → ``heagent audit verify`` 报出**首个**断链行号（退出码 1）；
4. 链与读取面复用 67.2 的同一份存储格式（单文件单链，不另建第二套）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from heagent.cli.console import main
from heagent.context.session import SessionStore
from heagent.network.http_console_protocol import ConfigWriteChangeRequest, ConfigWriteRequest
from heagent.pub.audit import read_entries, record_operation, resolve_audit_path, verify_chain
from heagent.pub.types import Message, Role
from heagent.skills.skill_store import SkillStore


def _ops(state_dir: Path) -> list[dict]:
    entries = read_entries(resolve_audit_path(state_dir=state_dir))
    return [entry for entry in entries if entry.get("kind") == "operation"]


# ── 三类敏感操作 ──────────────────────────────────────────────


def test_session_delete_is_traced_without_storing_content(tmp_path: Path) -> None:
    state_dir = tmp_path / ".heagent"
    store = SessionStore(base_dir=str(state_dir / "sessions"))
    secret = "my-secret-token-abcdef"
    store.save("sess-1", [Message(role=Role.USER, content=f"here is {secret}")])

    assert store.delete("sess-1") is True

    entries = _ops(state_dir)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["operation"] == "session.delete"
    assert entry["target"] == "sess-1"
    assert entry["before"]["sha256"].startswith("sha256:")
    assert entry["before"]["bytes"] > 0
    assert entry["after"] is None
    raw = resolve_audit_path(state_dir=state_dir).read_text(encoding="utf-8")
    assert secret not in raw


def test_skill_delete_is_traced_without_storing_content(tmp_path: Path) -> None:
    state_dir = tmp_path / ".heagent"
    store = SkillStore(base_dir=str(state_dir / "skills"))
    store.save("demo-skill", "a demo", "demo pattern", ["step one"])

    assert store.delete("demo-skill") is True

    entries = _ops(state_dir)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["operation"] == "skill.delete"
    assert entry["target"] == "demo-skill"
    assert entry["before"]["files"] >= 1
    assert entry["before"]["sha256"].startswith("sha256:")
    assert "demo pattern" not in resolve_audit_path(state_dir=state_dir).read_text(encoding="utf-8")


async def test_config_write_is_traced_with_fingerprints_only(tmp_path: Path) -> None:
    pytest.importorskip("starlette")

    from heagent.cli.http_console import HttpProjectConsole

    env_file = tmp_path / ".env"
    env_file.write_bytes(b"MAX_ITERATIONS=25\n")
    before_fingerprint = hashlib.sha256(env_file.read_bytes()).hexdigest()
    console = HttpProjectConsole(tmp_path, write_enabled=True, global_setting_file=None)

    request = ConfigWriteRequest(
        changes=[ConfigWriteChangeRequest(key="MAX_ITERATIONS", value="42")],
        fingerprint=before_fingerprint,
    )
    response = await console.update_project_config("default", request)

    assert response.fingerprint != before_fingerprint
    entries = _ops(tmp_path / ".heagent")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["operation"] == "config.write"
    assert entry["target"] == "project:default"
    assert entry["before"]["fingerprint"] == before_fingerprint
    assert entry["after"]["fingerprint"] == response.fingerprint
    assert entry["after"]["keys"] == ["MAX_ITERATIONS"]
    raw = resolve_audit_path(state_dir=tmp_path / ".heagent").read_text(encoding="utf-8")
    assert "MAX_ITERATIONS=42" not in raw  # 值不落审计面


# ── 哈希链 ────────────────────────────────────────────────────


def _three_records(state_dir: Path) -> Path:
    for index in range(3):
        assert (
            record_operation(
                operation="session.delete",
                target=f"sess-{index}",
                before={"sha256": "sha256:" + "a" * 64, "bytes": index},
                state_dir=state_dir,
            )
            is True
        )
    return resolve_audit_path(state_dir=state_dir)


def test_chain_is_intact_after_appends(tmp_path: Path) -> None:
    path = _three_records(tmp_path / ".heagent")

    verdict = verify_chain(path)

    assert verdict.ok is True
    assert verdict.lines == 3
    assert verdict.first_broken_line is None


def test_tampered_content_reports_the_tampered_line(tmp_path: Path) -> None:
    path = _three_records(tmp_path / ".heagent")
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["target"] = "sess-HACKED"
    lines[1] = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verdict = verify_chain(path)

    assert verdict.ok is False
    assert verdict.first_broken_line == 2
    assert "digest" in verdict.reason


def test_removed_line_reports_the_following_line(tmp_path: Path) -> None:
    path = _three_records(tmp_path / ".heagent")
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")

    verdict = verify_chain(path)

    assert verdict.first_broken_line == 2
    assert "prev" in verdict.reason


def test_verify_cli_exits_nonzero_on_broken_chain(tmp_path: Path) -> None:
    path = _three_records(tmp_path / ".heagent")
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[2])
    record["before"] = {"sha256": "sha256:" + "b" * 64, "bytes": 0}
    lines[2] = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["audit", "verify", "--path", str(path)])

    assert result.exit_code == 1
    assert "chain broken at line 3" in result.output


def test_verify_cli_is_clean_on_a_fresh_chain(tmp_path: Path) -> None:
    path = _three_records(tmp_path / ".heagent")

    result = CliRunner().invoke(main, ["audit", "verify", "--path", str(path)])

    assert result.exit_code == 0, result.output
    assert "chain intact: 3 record(s)" in result.output


def test_verify_of_missing_file_is_an_empty_chain(tmp_path: Path) -> None:
    verdict = verify_chain(tmp_path / "nope.jsonl")
    assert verdict.ok is True
    assert verdict.lines == 0
