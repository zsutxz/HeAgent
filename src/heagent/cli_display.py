"""Terminal rendering helpers shared by CLI and GUI integrations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import click

from heagent import __version__
from heagent.config import get_settings
from heagent.context.tokens import estimate_cost
from heagent.providers.router import active_model, annotate_route

if TYPE_CHECKING:
    from pathlib import Path

    from heagent.agent.loop import AgentLoop
    from heagent.types import TokenUsage


def _print_banner() -> None:
    click.echo(f"HeAgent v{__version__} — A self-improving AI Agent core framework", err=True)


def _print_usage(usage: TokenUsage | None, *, model: str | None = None) -> None:
    if usage is None or usage.total_tokens == 0:
        return
    line = f"  [tokens: {usage.prompt_tokens} in + {usage.completion_tokens} out = {usage.total_tokens} total]"
    if model:
        cost = estimate_cost(usage, model, get_settings().model_pricing_map)
        if cost is not None:
            line += f" [cost: ${cost:.4f}]"
    click.echo(line, err=True)


@dataclass
class _LineState:
    at_line_start: bool = True

    def write(self, text: str) -> None:
        if text:
            self.at_line_start = text.endswith("\n")


def _echo_status(message: str, line_state: _LineState) -> None:
    prefix = "" if line_state.at_line_start else "\n"
    click.echo(f"{prefix}{message}", err=True)
    line_state.at_line_start = True


def _print_stream_event(event: Any, line_state: _LineState) -> None:
    if event.type == "text":
        click.echo(event.text, nl=False)
        line_state.write(event.text)
    elif event.type == "tool_call":
        text = f"\n[calling {event.tool_name}...]"
        click.echo(text, nl=False)
        line_state.write(text)
    elif event.type == "tool_result":
        click.echo(" [done]", nl=False)
        line_state.write(" [done]")


def _format_tokens_k(n: int) -> str:
    if n < 1000:
        return str(n)
    if n >= 1_000_000:
        m = n / 1_000_000
        return f"{int(m)}M" if m == int(m) else f"{m:.1f}M"
    k = n / 1000
    return f"{int(k)}K" if k == int(k) else f"{k:.1f}K"


def _format_status(loop: AgentLoop) -> str:
    meta = loop.provider.get_metadata()
    model = annotate_route(loop.provider, active_model(loop.provider) or meta.model)
    settings = get_settings()
    parts = [model, f"{_format_tokens_k(loop.last_context_tokens)}/{_format_tokens_k(settings.max_context_tokens)} tok"]
    if loop.window_reset is not None:
        parts.append(f"reset@{int(loop.window_reset.config.threshold * 100)}%")
    elif loop.compressor is not None:
        parts.append(f"cmp@{int(loop.compressor.threshold * 100)}%")
    if loop.cumulative_tokens > 0:
        parts.append(f"累计: {_format_tokens_k(loop.cumulative_tokens)} tok")
    return f"[{' | '.join(parts)}]"


_DEFERRED_LEDGER = "implementation-artifacts/deferred-work.md"
_DEFERRED_LEGACY = "deferred-work.md"


def _deferred_ledgers(root: Path) -> list[Path]:
    """Return every deferred-work ledger under ``root``, canonical path first.

    bmad-build *writes* these ledgers but nothing read them back, so deferrals piled up
    unseen (three different locations by 2026-09-12).  This resolver is the missing reader:
    the canonical ``implementation-artifacts`` path, the legacy root ledger, then the
    goal-local Epic ledgers.
    """
    candidates = [root / "_bmad-output" / _DEFERRED_LEDGER, root / "_bmad-output" / _DEFERRED_LEGACY]
    candidates.extend(sorted((root / "_he-output" / "goals").glob("*/step-*/**/deferred-work.md")))
    return [path for path in candidates if path.is_file()]


def _deferred_entries(text: str) -> list[str]:
    """Return one ``source_spec — summary`` line per entry in a ledger."""
    entries: list[str] = []
    for block in re.split(r"^- source_spec:", text, flags=re.MULTILINE)[1:]:
        lines = block.splitlines()
        raw = lines[0].strip() if lines else ""
        # Entries may carry prose after the code span; keep the path only.
        spec = raw.split("`")[1] if raw.startswith("`") and "`" in raw[1:] else raw.strip("`")
        summary = next(
            (line.strip()[len("summary:") :].strip() for line in lines[1:] if line.strip().startswith("summary:")),
            "",
        )
        entries.append(f"{spec} — {summary}" if summary else spec)
    return entries


def show_deferred_work(root: Path, *, tail: int = 10) -> None:
    """Print every deferred-work ledger with its entry count and latest entries."""
    ledgers = _deferred_ledgers(root)
    if not ledgers:
        click.echo(f"[deferred] no ledger found (expected _bmad-output/{_DEFERRED_LEDGER})", err=True)
        return
    for path in ledgers:
        entries = _deferred_entries(path.read_text(encoding="utf-8"))
        shown = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
        click.echo(f"[deferred] {shown}: {len(entries)} entries", err=True)
        for entry in entries[-tail:]:
            click.echo(f"  - {entry}", err=True)


def _announce(message: str) -> None:
    """Write one progress banner to stderr unless the operator silenced announcements.

    Nested agents share the terminal with the interactive input line, so banners can be
    submitted as a prompt by accident; ``ANNOUNCE_PROGRESS=false`` silences them.
    """
    if get_settings().announce_progress:
        click.echo(message, err=True)


def _announce_start(name: str, purpose: str, *, run_id: str = "") -> None:
    """Print a start banner when a phase/skill/agent begins.

    ``run_id`` is folded into the label so parallel children of the same step stay
    distinguishable on screen and line up with the run ids in the log file.
    """
    label = f"{name}#{run_id[:8]}" if run_id else name
    _announce(f"▶ 启动 [{label}] — {purpose}")


def _announce_end(name: str, loop: AgentLoop, *, iterations: int | None = None, ok: bool = True) -> None:
    """Print a completion summary plus the token/status line after an agent finishes."""
    mark = "✔" if ok else "✘"
    suffix = f"（{iterations} 轮）" if iterations else ""
    _announce(f"{mark} [{name}] {'完成' if ok else '失败'}{suffix}")
    _announce(_format_status(loop))
