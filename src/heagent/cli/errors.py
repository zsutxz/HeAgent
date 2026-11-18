"""CLI 错误的统一出口：描述 + 可用选项 + 文档链接 + 可直接执行的命令建议。

为什么单独成模块：错误文案的**形状**要在所有失败分支一致，而各分支散在 ``console`` / ``http`` /
``wiring`` 里。把形状收在一处，新增分支只需给选项与锚点。

分层：入口层模块，只依赖 ``click`` 与同层的 ``cli.suggestions``；不被下层导入，也不导入任何
heagent 运行栈符号（避免把 provider/engine 拖进入口层的轻量路径）。

约定：
- **原消息文本逐字保留**在首行——它既是用户熟悉的文本，也是既有测试断言的判据；本模块只在其后
  追加 ``Try:`` 与 ``Docs:`` 两段，再按需追加 ``Try these commands:`` 建议段。
- 三段块（``message`` / ``Try:`` / ``Docs:``）是**既有契约**：不传 ``commands`` 时输出逐字不变。
  建议段只在 ``commands`` 非空时出现，且恒在 ``Docs:`` 之后。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

import click

from heagent.cli.suggestions import MIN_SUGGESTIONS, CommandSuggestion, suggest_commands

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 错误索引文档（仓库相对路径）。锚点按 GitHub 的 slug 规则拼，与 `docs/errors.md` 的标题一一对应。
ERRORS_DOC = "docs/errors.md"

#: 「CLI 与启动期错误」那一节的锚点。集中成常量，测试才能一次性校验它没随文档标题漂移。
ANCHOR_CLI_ERRORS = "三cli-与启动期错误"

#: 建议段的抬头（两空格缩进，与 ``Try:`` / ``Docs:`` 同一视觉层级）。
SUGGESTIONS_HEADER = "  Try these commands:"

#: 调试模式下的 traceback 段抬头（默认不出现；出现即说明 ``DEBUG_MODE=true``）。
TRACEBACK_HEADER = "  Traceback (DEBUG_MODE=true):"


def _debug_traceback() -> str:
    """``DEBUG_MODE=true`` 且当前确有异常在飞时，返回完整 traceback 文本；否则返回空串。

    刻意**惰性**导入 ``heagent.config``：本模块的其余部分只依赖 click 与同层建议表，
    保持「入口层轻量路径」不被 pydantic-settings 拖累。``get_settings()`` 有进程级缓存，
    调试模式下多调几次也不构成开销。
    """
    import sys
    import traceback

    from heagent.config import get_settings

    if not get_settings().debug_mode or sys.exc_info()[0] is None:
        return ""
    return traceback.format_exc()


def _append_traceback(lines: list[str]) -> list[str]:
    """把调试模式 traceback 段追加到错误块末尾（无异常或无调试模式时原样返回）。"""
    trace = _debug_traceback()
    if not trace:
        return lines
    lines.append(TRACEBACK_HEADER)
    lines.extend(f"    {line}" for line in trace.rstrip().splitlines())
    return lines


def _render_commands(commands: Sequence[CommandSuggestion]) -> list[str]:
    """渲染建议段的行。

    Raises:
        ValueError: ``commands`` 少于 :data:`MIN_SUGGESTIONS` —— 票面要求 ≥2 条，少给比不给更糟
            （用户会以为「只有这一条可做」）。
    """
    if len(commands) < MIN_SUGGESTIONS:
        raise ValueError(f"suggestions require at least {MIN_SUGGESTIONS} commands")
    lines = [SUGGESTIONS_HEADER]
    lines.extend(f"    - {item.command}  # {item.when}" for item in commands)
    return lines


def with_hints(
    message: str,
    *,
    options: Sequence[str],
    anchor: str = "",
    commands: Sequence[CommandSuggestion] | None = None,
) -> str:
    """把一段错误消息渲染成「描述 + 可用选项 + 文档链接（+ 命令建议）」。

    Args:
        message: 原始错误消息（原样放在块首，可含 ``[]`` 前缀形态或换行）。
        options: 可执行动作，每条一句话，**至少一条**——空列表会产出只有标题没有条目的畸形块。
        anchor: ``docs/errors.md`` 的标题锚点（不带 ``#``）；为空时只链到文档首页。
        commands: 命令建议；``None``（默认）时输出与三段块完全一致，不追加任何段落。

    Returns:
        多行字符串：``message`` + 缩进的 ``Try:`` 列表 + ``Docs:`` 行，``commands`` 非空时再接
        ``Try these commands:`` 列表。

    Raises:
        ValueError: ``options`` 为空，或 ``commands`` 少于两条。
    """
    if not options:
        raise ValueError("with_hints requires at least one option")
    lines = [message, "  Try:"]
    lines.extend(f"    - {option}" for option in options)
    link = f"{ERRORS_DOC}#{anchor}" if anchor else ERRORS_DOC
    lines.append(f"  Docs: {link}")
    if commands is not None:
        lines.extend(_render_commands(commands))
    # traceback 恒在最后：错误块的既有三段（+ 建议段）形状与顺序不变，追加只发生在调试模式。
    return "\n".join(_append_traceback(lines))


def with_command_hints(
    message: str,
    *,
    options: Sequence[str],
    anchor: str = "",
    scenario: str | None = None,
) -> str:
    """同 :func:`with_hints`，但按 ``message``（或显式 ``scenario``）自动追加命令建议。

    Args:
        message: 原始错误消息；原样置于块首，同时作为场景推断的输入。
        options: 可执行动作（至少一条）。
        anchor: ``docs/errors.md`` 的标题锚点。
        scenario: 显式场景 key；为空时按 ``message`` 的关键词推断，推断不出走兜底建议。

    Returns:
        多行字符串，形状同 :func:`with_hints` 且必含 ``Try these commands:`` 段。

    Raises:
        KeyError: ``scenario`` 不是已声明的场景 key。
        ValueError: ``options`` 为空。
    """
    return with_hints(
        message,
        options=options,
        anchor=anchor,
        commands=suggest_commands(message, scenario=scenario),
    )


def exit_with_hints(
    message: str,
    *,
    options: Sequence[str],
    anchor: str = "",
    commands: Sequence[CommandSuggestion] | None = None,
) -> NoReturn:
    """以 ``click.ClickException`` 退出（stderr + 退出码 1），带选项与文档链接。"""
    raise click.ClickException(with_hints(message, options=options, anchor=anchor, commands=commands))


def exit_with_command_hints(
    message: str,
    *,
    options: Sequence[str],
    anchor: str = "",
    scenario: str | None = None,
) -> NoReturn:
    """以 ``click.ClickException`` 退出，并带上自动推断的命令建议。"""
    raise click.ClickException(with_command_hints(message, options=options, anchor=anchor, scenario=scenario))


def report_with_hints(
    message: str,
    *,
    options: Sequence[str],
    anchor: str = "",
    commands: Sequence[CommandSuggestion] | None = None,
) -> None:
    """把同形状的错误写到 stderr，但**不**退出（用于要自行决定退出码的分支）。"""
    click.echo(with_hints(message, options=options, anchor=anchor, commands=commands), err=True)


def report_with_command_hints(
    message: str,
    *,
    options: Sequence[str],
    anchor: str = "",
    scenario: str | None = None,
) -> None:
    """把带命令建议的错误写到 stderr，但**不**退出。"""
    click.echo(with_command_hints(message, options=options, anchor=anchor, scenario=scenario), err=True)


__all__ = [
    "ANCHOR_CLI_ERRORS",
    "ERRORS_DOC",
    "SUGGESTIONS_HEADER",
    "TRACEBACK_HEADER",
    "exit_with_command_hints",
    "exit_with_hints",
    "report_with_command_hints",
    "report_with_hints",
    "with_command_hints",
    "with_hints",
]
