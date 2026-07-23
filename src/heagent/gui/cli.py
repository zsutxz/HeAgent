"""CLI entry for ``heagent gui`` subcommand.

Thin wrapper that builds the Provider/AgentLoop and hands off to the Textual app.
"""

from __future__ import annotations

import asyncio
import logging
import os

import click

logger = logging.getLogger(__name__)


@click.command("gui")
@click.option("--model", default=None, help="Model name (default: per-provider setting)")
@click.option(
    "--sandbox",
    type=click.Choice(["passthrough", "firejail"]),
    default=None,
    help="Sandbox backend for shell execution",
)
def gui_cmd(model: str | None, sandbox: str | None) -> None:
    """Launch the HeAgent terminal UI."""
    try:
        from heagent.gui import gui_main  # noqa: PLC0415
    except ImportError:
        click.echo(
            "GUI 依赖未安装。请运行: pip install heagent[gui]",
            err=True,
        )
        raise SystemExit(1) from None

    # 基本的日志配置（完整配置在 cli.py 的 run 命令中；GUI 走 Textual 自己的日志）
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # 沙箱提醒
    if sandbox == "firejail":
        from heagent.config import get_settings

        settings = get_settings()
        import shutil as _shutil

        if _shutil.which(settings.sandbox_firejail_path) is None:
            click.echo(
                f" WARNING: firejail not found ({settings.sandbox_firejail_path}). "
                f"Shell commands will run WITHOUT sandbox isolation.",
                err=True,
            )
        else:
            click.echo(f" firejail sandbox ENABLED ({settings.sandbox_firejail_path})", err=True)

    try:
        asyncio.run(gui_main(model=model, sandbox=sandbox))
    except ImportError:
        click.echo(
            "GUI 依赖未安装。请运行: pip install heagent[gui]",
            err=True,
        )
        raise SystemExit(1) from None
