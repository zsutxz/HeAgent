"""斜杠命令的 ``/help`` 渲染（列表版 + 详情版 + 未知命令建议）。

为什么单独成模块：这三段的形状（+ 三个段落标签）要**逐字一致**，而 ``cli/interactive.py``
已逼近单文件 1000 行上限（Epic 62 Outcome）。把「纯展示」搬出来，注册与派发留在 ``interactive``。

分层：入口层（``heagent/cli/`` 包内）。只依赖 ``click`` 与 ``cli.slash`` 的注册表模型——
不认识 provider / agent / engine，因此可在任何 CLI/GUI 路径里复用。

调用方（``heagent.cli.interactive``）以**同名导入**取用本模块的函数，测试的
``from heagent.cli.interactive import _render_command_help`` 这条缝保持有效。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from heagent.cli.slash import SlashCommandInfo, SlashRegistry

__all__ = [
    "_help_argument_lines",
    "_render_command_help",
    "_render_help_list",
    "_render_unknown_command",
]

#: ``/help <command>`` 详情版的三个固定段落标签（与列表版共用同一数据源）。
HELP_USAGE_LABEL = "语法:"
HELP_ARGUMENTS_LABEL = "参数:"
HELP_EXAMPLES_LABEL = "示例:"


def _render_help_list(registry: SlashRegistry) -> None:
    """``/help`` 列表版：按命令名排序，名字列对齐 + 一句话描述。"""
    names = registry.names()
    width = max((len(name) for name in names), default=0)
    click.echo("Available slash commands:", err=True)
    for name in names:
        click.echo(f"  /{name.ljust(width)}  {registry.describe(name)}", err=True)
    click.echo("[help] Run /help <command> for syntax, arguments and examples.", err=True)


def _help_argument_lines(info: SlashCommandInfo) -> list[str]:
    """参数段内容：显式声明优先，缺元数据时给显式兜底（不渲染空块）。

    兜底文案必须与「语法」段的自洽：语法在没有 ``usage`` 时只渲染 ``/<name>``（不写 ``[参数]``），
    否则会出现「语法说有可选参数 / 参数说无参数」的自相矛盾。
    """
    if info.arguments.strip():
        return info.arguments.strip().splitlines()
    if info.custom:
        return [f"自定义命令，无参数说明（正文见 .heagent/commands/{info.name}.md；$ARGUMENTS 替换为本次参数）。"]
    return ["未提供参数说明。"]


def _render_command_help(registry: SlashRegistry, name: str) -> None:
    """``/help <command>`` 详情版：描述 + 语法 + 参数 + 示例，四段格式统一。"""
    info = registry.info(name)
    if info is None:
        _render_unknown_command(registry, name)
        return
    click.echo(f"/{info.name}  {info.description or '（无描述）'}", err=True)
    click.echo(HELP_USAGE_LABEL, err=True)
    for line in (info.usage.strip() or f"/{info.name}").splitlines():
        click.echo(f"  {line}", err=True)
    click.echo(HELP_ARGUMENTS_LABEL, err=True)
    for line in _help_argument_lines(info):
        click.echo(f"  {line}", err=True)
    click.echo(HELP_EXAMPLES_LABEL, err=True)
    for line in info.examples or [f"/{info.name}"]:
        click.echo(f"  {line}", err=True)


def _render_unknown_command(registry: SlashRegistry, name: str) -> None:
    """未知命令：错误 + 最接近的命令建议 + 列表入口提示。"""
    click.echo(f"[help] Unknown slash command: /{name}", err=True)
    suggestions = registry.suggest(name)
    if suggestions:
        click.echo("[help] Did you mean: " + ", ".join(f"/{item}" for item in suggestions), err=True)
    click.echo("[help] Run /help to list all commands.", err=True)
