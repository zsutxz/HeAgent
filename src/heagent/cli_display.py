"""Terminal rendering helpers shared by CLI and GUI integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import click

from heagent import __version__
from heagent.config import get_settings
from heagent.context.tokens import estimate_cost
from heagent.providers.router import active_model

if TYPE_CHECKING:
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
    model = active_model(loop.provider) or meta.model
    settings = get_settings()
    parts = [model, f"{_format_tokens_k(loop.last_context_tokens)}/{_format_tokens_k(settings.max_context_tokens)} tok"]
    if loop.window_reset is not None:
        parts.append(f"reset@{int(loop.window_reset.config.threshold * 100)}%")
    elif loop.compressor is not None:
        parts.append(f"cmp@{int(loop.compressor.threshold * 100)}%")
    if loop.cumulative_tokens > 0:
        parts.append(f"累计: {_format_tokens_k(loop.cumulative_tokens)} tok")
    return f"[{' | '.join(parts)}]"


def _announce_start(name: str, purpose: str) -> None:
    """Print a start banner when a phase/skill/agent begins."""
    click.echo(f"▶ 启动 [{name}] — {purpose}", err=True)


def _announce_end(name: str, loop: AgentLoop, *, iterations: int | None = None, ok: bool = True) -> None:
    """Print a completion summary plus the token/status line after an agent finishes."""
    mark = "✔" if ok else "✘"
    suffix = f"（{iterations} 轮）" if iterations else ""
    click.echo(f"{mark} [{name}] {'完成' if ok else '失败'}{suffix}", err=True)
    click.echo(_format_status(loop), err=True)
