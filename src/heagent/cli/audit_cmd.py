"""``heagent audit``：审计日志的查询 / 导出 / 链校验（只读，不启运行时）。

子命令：

- ``list``：一行一条的人类可读视图（时间 / 类别 / 工具或操作名 / 状态 / 耗时 / 操作者）；
- ``export``：逐行 JSON（每条都是 ``json.loads`` 可解析的对象，含 ``prev`` / ``digest`` 链字段，
  便于外部取证工具接手）；
- ``verify``：校验哈希链，报**首个**断链行号。

过滤面两个：``--since <ISO>``（无时区按本地时理解，与 :func:`heagent.pub.audit.parse_since` 同口径）与
``--tool <NAME>``（同时匹配工具名与敏感操作名）。``--path`` 缺省取当前工作区
``<root>/.heagent/audit/tool-audit.jsonl``。

退出码（与 ``heagent cron`` 同一约定）：

- ``0``：查询成功；``verify`` 且链完整（含「还没有任何记录」）；
- ``1``：``verify`` 发现断链（行号见输出）；
- ``2``：参数或文件不可用（``--since`` 解析失败 / 审计文件读不了）。

分层：入口层（``heagent/cli/``），只依赖 click + 标准库 + ``heagent.pub.audit``；不导入
``agent`` / ``engine``——查审计不需要运行栈。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from heagent.pub.audit import (
    filter_entries,
    parse_since,
    read_entries,
    resolve_audit_path,
    verify_chain_segments,
)

#: 退出码（见模块 docstring）。
EXIT_OK = 0
EXIT_CHAIN_BROKEN = 1
EXIT_UNUSABLE = 2

#: ``list`` 里 ``args`` / ``before`` 摘要的展示宽度。
DETAIL_WIDTH = 100


def _audit_path(path: Path | None) -> Path:
    """``--path`` 优先，否则按当前工作区派生的默认落点。"""
    return path if path is not None else resolve_audit_path()


def _load(path: Path, *, since: str | None, tool: str | None) -> list[dict[str, Any]]:
    """读回 + 过滤（``--since`` 解析失败按「参数不可用」退出 2，而不是静默不过滤）。"""
    window = None
    if since is not None:
        try:
            window = parse_since(since)
        except ValueError as exc:
            # click 的用法错误退出码同为 2；消息里点名原文，免得住把「相对时间」当 ISO 传。
            raise click.BadParameter(f"--since must be an ISO-8601 timestamp: {since!r} ({exc})") from exc
    return filter_entries(read_entries(path, include_segments=True), since=window, name=tool)


def _clip(text: str, width: int = DETAIL_WIDTH) -> str:
    return text if len(text) <= width else f"{text[:width]}…"


def _render(entry: dict[str, Any]) -> str:
    """一行人类可读视图；两类记录字段不同，故按 ``kind`` 分支（未知 kind 原样给 JSON）。"""
    ts = str(entry.get("ts", "?"))
    kind = entry.get("kind")
    if kind == "tool":
        duration = entry.get("duration_ms")
        parts = [
            ts,
            "tool",
            str(entry.get("tool", "?")),
            str(entry.get("status", "?")),
            f"{duration}ms" if isinstance(duration, int) else "-",
        ]
        if entry.get("error_kind"):
            parts.append(f"error_kind={entry['error_kind']}")
        parts.append(f"operator={entry.get('operator', '?')}")
        args = entry.get("args") or {}
        if args:
            parts.append(f"args={_clip(json.dumps(args, ensure_ascii=False, sort_keys=True))}")
        return "  ".join(parts)
    if kind == "operation":
        parts = [
            ts,
            "operation",
            str(entry.get("operation", "?")),
            f"target={entry.get('target', '?')}",
            f"operator={entry.get('operator', '?')}",
        ]
        for label in ("before", "after"):
            summary = entry.get(label)
            if summary:
                parts.append(f"{label}={_clip(json.dumps(summary, ensure_ascii=False, sort_keys=True))}")
        return "  ".join(parts)
    return _clip(json.dumps(entry, ensure_ascii=False, sort_keys=True))


@click.group("audit")
def audit_cmd() -> None:
    """Inspect the audit log (tool executions + sensitive operations; read-only)."""


@audit_cmd.command("list")
@click.option("--path", type=click.Path(dir_okay=False, path_type=Path), default=None, help="audit JSONL file")
@click.option("--since", default=None, help="only records at/after this ISO-8601 timestamp")
@click.option("--tool", "tool", default=None, help="only records for this tool or sensitive operation")
def audit_list_cmd(path: Path | None, since: str | None, tool: str | None) -> None:
    """Print one line per audit record."""
    target = _audit_path(path)
    entries = _load(target, since=since, tool=tool)
    if not entries:
        click.echo(f"[audit] no records in {target}")
        return
    for entry in entries:
        click.echo(_render(entry))


@audit_cmd.command("export")
@click.option("--path", type=click.Path(dir_okay=False, path_type=Path), default=None, help="audit JSONL file")
@click.option("--since", default=None, help="only records at/after this ISO-8601 timestamp")
@click.option("--tool", "tool", default=None, help="only records for this tool or sensitive operation")
def audit_export_cmd(path: Path | None, since: str | None, tool: str | None) -> None:
    """Emit matching audit records as JSON lines (one object per line)."""
    target = _audit_path(path)
    entries = _load(target, since=since, tool=tool)
    if not entries:
        click.echo(f"[audit] no records in {target}", err=True)
        return
    for entry in entries:
        click.echo(json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


@audit_cmd.command("verify")
@click.option("--path", type=click.Path(dir_okay=False, path_type=Path), default=None, help="audit JSONL file")
def audit_verify_cmd(path: Path | None) -> None:
    """Verify the hash chain across archived segments; report the first broken line (exit 1 when broken)."""
    target = _audit_path(path)
    verdict = verify_chain_segments(target)
    if verdict.ok:
        click.echo(f"[audit] chain intact: {verdict.lines} record(s) verified in {target}")
        return
    click.echo(f"[audit] chain broken at line {verdict.first_broken_line}: {verdict.reason} ({target})")
    raise SystemExit(EXIT_CHAIN_BROKEN)


__all__ = ["EXIT_CHAIN_BROKEN", "EXIT_OK", "EXIT_UNUSABLE", "audit_cmd"]
