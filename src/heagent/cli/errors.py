"""CLI 错误的统一出口：描述 + 可用选项 + 文档链接。

为什么单独成模块：错误文案的**形状**要在所有失败分支一致，而各分支散在 ``console`` / ``http`` /
``wiring`` 里。把形状收在一处，新增分支只需给选项与锚点。

分层：入口层模块，只依赖 ``click``；不被下层导入，也不导入任何 heagent 运行栈符号（避免把
provider/engine 拖进入口层的轻量路径）。

约定：**原消息文本逐字保留**在首行——它既是用户熟悉的文本，也是既有测试断言的判据；本模块只在其后
追加 ``Try:`` 与 ``Docs:`` 两段。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

import click

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 错误索引文档（仓库相对路径）。锚点按 GitHub 的 slug 规则拼，与 `docs/errors.md` 的标题一一对应。
ERRORS_DOC = "docs/errors.md"

#: 「CLI 与启动期错误」那一节的锚点。集中成常量，测试才能一次性校验它没随文档标题漂移。
ANCHOR_CLI_ERRORS = "三cli-与启动期错误"


def with_hints(message: str, *, options: Sequence[str], anchor: str = "") -> str:
    """把一段错误消息渲染成「描述 + 可用选项 + 文档链接」。

    Args:
        message: 原始错误消息（原样放在块首，可含 ``[]`` 前缀形态或换行）。
        options: 可执行动作，每条一句话，**至少一条**——空列表会产出只有标题没有条目的畸形块。
        anchor: ``docs/errors.md`` 的标题锚点（不带 ``#``）；为空时只链到文档首页。

    Returns:
        多行字符串：``message`` + 缩进的 ``Try:`` 列表 + ``Docs:`` 行。

    Raises:
        ValueError: ``options`` 为空——宁可在构造期炸掉，也不要把畸形块写给用户。
    """
    if not options:
        raise ValueError("with_hints requires at least one option")
    lines = [message, "  Try:"]
    lines.extend(f"    - {option}" for option in options)
    link = f"{ERRORS_DOC}#{anchor}" if anchor else ERRORS_DOC
    lines.append(f"  Docs: {link}")
    return "\n".join(lines)


def exit_with_hints(message: str, *, options: Sequence[str], anchor: str = "") -> NoReturn:
    """以 ``click.ClickException`` 退出（stderr + 退出码 1），带选项与文档链接。"""
    raise click.ClickException(with_hints(message, options=options, anchor=anchor))


def report_with_hints(message: str, *, options: Sequence[str], anchor: str = "") -> None:
    """把同形状的错误写到 stderr，但**不**退出（用于要自行决定退出码的分支）。"""
    click.echo(with_hints(message, options=options, anchor=anchor), err=True)


__all__ = [
    "ANCHOR_CLI_ERRORS",
    "ERRORS_DOC",
    "exit_with_hints",
    "report_with_hints",
    "with_hints",
]
