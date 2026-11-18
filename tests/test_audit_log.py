"""Story 67.2：工具执行审计日志（``pub/audit.py`` + ``ToolExecutor`` 接入 + ``heagent audit``）。

钉住四条契约：

1. **一次执行一行**：``ToolExecutor.execute`` 是工具真被执行的唯一出口，DIRECT / SANDBOX / 阻断
   三路都留痕，字段齐（ts / operator / tool / args / status / duration_ms / error_kind）；
2. **脱敏**：参数里的凭证形态落盘只剩掩码（复用 ``pub/safe_logging``），文件里搜不到原值；
3. **fail-soft**：审计写入抛异常时工具结果不变，只留一条 WARNING；
4. **查询面**：``heagent audit list|export`` 的过滤与逐行 ``json.loads`` 可解析。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from click.testing import CliRunner

from heagent.cli.console import main
from heagent.engine.context import RunContext
from heagent.engine.executor import ToolExecutor
from heagent.engine.policy import PolicyEngine, PolicyVerdict, ToolExecutionMode
from heagent.pub.audit import (
    AUDIT_FILENAME,
    OPERATOR_ENV,
    read_entries,
    record_tool_execution,
    resolve_audit_path,
    verify_chain,
)
from heagent.pub.types import ToolCall

if TYPE_CHECKING:
    import pytest


class _AllowAllGuard:
    """``SafetyGuard.check`` 的放行替身（本文件只关心审计，不测 guard 语义）。"""

    def check(self, call: ToolCall) -> None:
        return None


def _context(root: Path) -> RunContext:
    return RunContext(workspace_root=str(root), session_id="sess-audit")


def _audit_file(root: Path) -> Path:
    return resolve_audit_path(root=root)


def _handler(output: str):
    async def handler(call: ToolCall) -> object:
        await asyncio.sleep(0)
        return output

    return handler


async def _execute(root: Path, call: ToolCall, *, handler=None, verdict: PolicyVerdict | None = None) -> object:
    return await ToolExecutor().execute(
        call=call,
        verdict=verdict or PolicyEngine().evaluate_tool_call(call),
        guard=_AllowAllGuard(),
        handler=handler or _handler("done"),
        run_context=_context(root),
    )


# ── 1. 一次执行一行 ────────────────────────────────────────────


async def test_tool_execution_writes_one_line_with_all_fields(tmp_path: Path) -> None:
    context = _context(tmp_path)
    call = ToolCall(id="1", name="shell", arguments={"command": "echo hi"})
    result = await ToolExecutor().execute(
        call=call,
        verdict=PolicyEngine().evaluate_tool_call(call),
        guard=_AllowAllGuard(),
        handler=_handler("hi"),
        run_context=context,
    )

    assert result.is_error is False
    path = _audit_file(tmp_path)
    entries = read_entries(path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "tool"
    assert entry["tool"] == "shell"
    assert entry["status"] == "ok"
    assert entry["args"] == {"command": "echo hi"}
    assert isinstance(entry["duration_ms"], int)
    assert entry["error_kind"] is None
    assert entry["operator"].endswith(f"run:{context.run_id}")
    assert entry["ts"].endswith("+00:00")  # 带时区的 UTC
    assert verify_chain(path).ok


async def test_handler_exception_is_recorded_as_error(tmp_path: Path) -> None:
    call = ToolCall(id="2", name="shell", arguments={"command": "boom"})

    async def boom(call: ToolCall) -> object:
        raise RuntimeError("kaboom")

    result = await _execute(tmp_path, call, handler=boom)

    assert result.is_error is True  # type: ignore[union-attr]
    entry = read_entries(_audit_file(tmp_path))[0]
    assert entry["status"] == "error"
    assert entry["error_kind"] == "tool_error"
    assert "kaboom" not in json.dumps(entry["args"])


async def test_policy_blocked_call_is_recorded_as_blocked(tmp_path: Path) -> None:
    call = ToolCall(id="3", name="shell", arguments={"command": "rm -rf /"})
    verdict = PolicyVerdict(mode=ToolExecutionMode.BLOCKED, reason="denied by policy", sandbox_profile="")
    called = False

    async def handler(call: ToolCall) -> object:
        nonlocal called
        called = True
        return "should not run"

    result = await _execute(tmp_path, call, handler=handler, verdict=verdict)

    assert called is False
    assert result.is_error is True  # type: ignore[union-attr]
    entry = read_entries(_audit_file(tmp_path))[0]
    assert entry["status"] == "blocked"
    assert entry["error_kind"] == "policy_blocked"


async def test_execution_without_run_context_is_not_audited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无 run 上下文 = 无操作者与落点归属 ⇒ 不落盘（否则测试/库调用会给 cwd 灌审计）。"""
    monkeypatch.chdir(tmp_path)
    call = ToolCall(id="4", name="shell", arguments={"command": "echo hi"})
    await ToolExecutor().execute(
        call=call,
        verdict=PolicyEngine().evaluate_tool_call(call),
        guard=_AllowAllGuard(),
        handler=_handler("hi"),
        run_context=None,
    )
    assert not (tmp_path / ".heagent" / "audit").exists()


# ── 2. 脱敏 ────────────────────────────────────────────────────


async def test_credentials_in_arguments_never_reach_the_file(tmp_path: Path) -> None:
    secret = "sk-live-PLAINTEXT-abcdef123456"
    call = ToolCall(id="5", name="shell", arguments={"command": f"curl --api-key {secret} http://x"})

    await _execute(tmp_path, call)

    raw = _audit_file(tmp_path).read_text(encoding="utf-8")
    assert secret not in raw
    assert "***" in raw
    entry = read_entries(_audit_file(tmp_path))[0]
    assert "***" in entry["args"]["command"]


def test_operator_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPERATOR_ENV, "svc:deploy-bot")
    assert record_tool_execution(tool="shell", root=tmp_path) is True
    assert read_entries(_audit_file(tmp_path))[0]["operator"] == "svc:deploy-bot"


# ── 3. fail-soft ──────────────────────────────────────────────


async def test_audit_write_failure_does_not_change_the_tool_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _explode(path: Path, line: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("heagent.pub.audit._append_line", _explode)
    call = ToolCall(id="6", name="shell", arguments={"command": "echo hi"})

    with caplog.at_level(logging.WARNING, logger="heagent.pub.audit"):
        result = await _execute(tmp_path, call)

    assert result.is_error is False
    assert result.content == "done"  # type: ignore[union-attr]
    assert not _audit_file(tmp_path).exists()
    assert any("audit record dropped" in record.getMessage() for record in caplog.records)


def test_record_tool_execution_reports_false_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(path: Path, line: str) -> None:
        raise OSError("nope")

    monkeypatch.setattr("heagent.pub.audit._append_line", _explode)
    assert record_tool_execution(tool="shell", root=tmp_path) is False


# ── 4. 查询面 / 导出 ──────────────────────────────────────────


def test_audit_path_defaults_under_the_state_root(tmp_path: Path) -> None:
    path = resolve_audit_path(root=tmp_path)
    assert path == tmp_path / ".heagent" / "audit" / AUDIT_FILENAME


def test_export_emits_parsable_json_lines_filtered_by_tool(tmp_path: Path) -> None:
    for tool in ("shell", "file_read", "shell"):
        assert record_tool_execution(tool=tool, args={"command": "ls"}, root=tmp_path) is True
    path = _audit_file(tmp_path)

    result = CliRunner().invoke(main, ["audit", "export", "--path", str(path), "--tool", "shell"])

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert {entry["tool"] for entry in parsed} == {"shell"}
    assert all(entry["prev"] is not None for entry in parsed)


def test_export_filters_by_since(tmp_path: Path) -> None:
    assert record_tool_execution(tool="shell", root=tmp_path) is True
    path = _audit_file(tmp_path)

    future = CliRunner().invoke(main, ["audit", "export", "--path", str(path), "--since", "2999-01-01T00:00:00Z"])
    past = CliRunner().invoke(main, ["audit", "export", "--path", str(path), "--since", "2000-01-01T00:00:00Z"])

    assert future.exit_code == 0
    assert "no records" in future.output
    assert past.exit_code == 0
    assert len([line for line in past.output.splitlines() if line.strip()]) == 1


def test_bad_since_is_a_usage_error(tmp_path: Path) -> None:
    path = _audit_file(tmp_path)
    result = CliRunner().invoke(main, ["audit", "list", "--path", str(path), "--since", "yesterday"])
    assert result.exit_code == 2


def test_list_renders_human_readable_lines(tmp_path: Path) -> None:
    recorded = record_tool_execution(tool="shell", args={"command": "ls"}, status="ok", duration_ms=7, root=tmp_path)
    assert recorded is True
    path = _audit_file(tmp_path)

    result = CliRunner().invoke(main, ["audit", "list", "--path", str(path)])

    assert result.exit_code == 0, result.output
    assert "tool" in result.output
    assert "shell" in result.output
    assert "7ms" in result.output
