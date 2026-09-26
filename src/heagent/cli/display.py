"""Terminal rendering helpers shared by CLI and GUI integrations."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import click

from heagent.config import get_settings
from heagent.context.tokens import estimate_cost
from heagent.providers.router import active_model, annotate_route
from heagent.tools.call_summary import activity_label

if TYPE_CHECKING:
    from pathlib import Path

    from heagent.agent.loop import AgentLoop
    from heagent.types import StreamEvent, TokenUsage


def _current_version() -> str:
    """源码版本号（``heagent.__version__``，与 ``pyproject.toml`` 同步）。

    刻意**延迟**到调用时导入根包：本模块处于根包 ``__init__`` 链的可能下游，
    模块级 import 根包会形成回环；函数内导入时根包必已初始化完成。
    不再读 ``importlib.metadata``——安装元数据会滞后于源码（editable 安装
    未刷新时横幅会报出旧版本），源码才是唯一事实源。
    """
    from heagent import __version__

    return __version__


def _print_banner() -> None:
    click.echo(f"HeAgent v{_current_version()} — A self-improving AI Agent core framework", err=True)


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


def _icon(icon: str, fallback: str, *, encoding: str | None = None) -> str:
    """返回当前 stderr 能输出的图标；编码不支持时降级为 ``fallback``（P7）。

    GBK（cp936）控制台或重定向下 ``🔧`` ``▶`` ``✔`` ``✘`` 均无法编码，``click.echo``
    会抛 ``UnicodeEncodeError`` 打断交互（本机中文 Windows 实测：四者在 cp936 下全部
    失败，``→`` 可编码）。降级只影响图标，正文照常；``encoding`` 参数供测试注入。
    """
    enc = encoding or getattr(sys.stderr, "encoding", None) or "utf-8"
    try:
        icon.encode(enc)
    except (LookupError, UnicodeEncodeError):
        return fallback
    return icon


def _line_prefix(line_state: _LineState) -> str:
    """行首前缀：流式文本停在半行时先换行，避免提示与正文粘连。"""
    return "" if line_state.at_line_start else "\n"


def _echo_status(message: str, line_state: _LineState) -> None:
    prefix = _line_prefix(line_state)
    click.echo(f"{prefix}{message}", err=True)
    line_state.at_line_start = True


def _emit(text: str, line_state: _LineState) -> None:
    """流式输出（不自动换行）：写 stdout 的同时推进行首状态，避免两处失步。"""
    click.echo(text, nl=False)
    line_state.write(text)


def _print_stream_event(event: StreamEvent, line_state: _LineState) -> None:
    if event.type == "text":
        _emit(event.text, line_state)
    elif event.type == "tool_call":
        # 自成一行：紧跟其后的可能是模型继续输出的文本，行尾不留悬挂内容。
        # 标签拼接走 activity_label，与状态行 / GUI / 活动台账同一口径。
        label = activity_label(event.tool_name, event.tool_target)
        _emit(f"{_line_prefix(line_state)}[calling {label}]\n", line_state)
    elif event.type == "tool_result" and event.tool_error:
        # 成功不逐条回显：批次是并发执行的，N 个结果会在同一刻到达，逐条 [done]
        # 只会挤成一串无主语的标记；失败必须归因到具体调用，故单独提示。
        subject = f" {event.tool_name}" if event.tool_name else ""
        _emit(f"{_line_prefix(line_state)}[failed{subject}]\n", line_state)


def format_tokens_k(n: int) -> str:
    """把 token 数渲染成 ``K``/``M`` 后缀短形式（CLI 状态行与 GUI 状态栏的唯一实现）。

    2026-09-15：CLI ``_format_status`` 与 GUI ``ChatScreen`` 曾各持一份逐字相同的副本，
    此处合并为唯一实现点。边界行为刻意保持不变：``999_999`` 仍渲染为 ``1000.0K``
    （K 分支不去进位到 M）。
    """
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
    parts = [model, f"{format_tokens_k(loop.last_context_tokens)}/{format_tokens_k(settings.max_context_tokens)} tok"]
    if loop.window_reset is not None:
        parts.append(f"reset@{int(loop.window_reset.config.threshold * 100)}%")
    elif loop.compressor is not None:
        parts.append(f"cmp@{int(loop.compressor.threshold * 100)}%")
    if loop.cumulative_tokens > 0:
        parts.append(f"累计: {format_tokens_k(loop.cumulative_tokens)} tok")
    # 在途工具：暂停/恢复或子 Agent 收尾时，一眼看出「卡在哪个工具」。
    if loop.active_tool:
        parts.append(f"{_icon('🔧', '[tool]')} {loop.active_tool}")
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


def show_tool_activity(loop: AgentLoop, *, limit: int = 20) -> None:
    """打印本次 run 的工具活动回顾：试过读哪些文件、跑哪些命令、委派谁。

    数据取自 loop 自己的 run 级台账（``loop.tool_activity``）而非 EventBus 环缓冲
    ——后者只留 200 条事件，长 run 会丢掉早期调用，而这份回顾恰恰是「事后要看的记录」。
    ⚠ 台账记的是**调用尝试**（执行前登记）：被 policy/hook 阻止、命中 ledger 缓存的
    调用同样留痕，所以头部措辞是「调用尝试」而不是「执行成功」。
    相同目标去重（同一文件读三次只列一次），超出 ``limit`` 折叠为一行计数；
    无调用时不输出（与 ``_print_usage`` 零用量静默一致）。
    """
    activity = list(loop.tool_activity)
    if not activity:
        return
    unique = list(dict.fromkeys(activity))
    header = f"[tools] {len(activity)} 次调用尝试"
    if len(unique) != len(activity):
        header += f"，{len(unique)} 个不同目标"
    click.echo(f"{header}：", err=True)
    for label in unique[:limit]:
        click.echo(f"  {label}", err=True)
    if len(unique) > limit:
        click.echo(f"  … 另有 {len(unique) - limit} 个目标", err=True)


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
    _announce(f"{_icon('▶ ', '> ')}启动 [{label}] — {purpose}")


def _announce_end(name: str, loop: AgentLoop, *, iterations: int | None = None, ok: bool = True) -> None:
    """Print a completion summary plus the token/status line after an agent finishes."""
    mark = _icon("✔ ", "") if ok else _icon("✘ ", "")
    suffix = f"（{iterations} 轮）" if iterations else ""
    _announce(f"{mark}[{name}] {'完成' if ok else '失败'}{suffix}")
    _announce(_format_status(loop))


class _CliSubAgentAnnouncer:
    """终端入口的 :class:`~heagent.agent.sub.SubAgentAnnouncer` 实现（stderr 横幅）。

    复用既有 ``_announce_start`` / ``_announce_end``——子 Agent 横幅行为与
    注入前逐字一致（含 ``ANNOUNCE_PROGRESS=false`` 静默开关）。
    """

    def started(self, name: str, purpose: str, *, run_id: str = "") -> None:
        _announce_start(name, purpose, run_id=run_id)

    def finished(self, name: str, loop: AgentLoop, *, iterations: int = 0, ok: bool = True) -> None:
        _announce_end(name, loop, iterations=iterations, ok=ok)


SUBAGENT_ANNOUNCER = _CliSubAgentAnnouncer()
"""进程级单例：CLI / GUI 入口构造 ``SubAgent`` / ``AgentLoop`` 时注入，保持既有横幅行为。"""
