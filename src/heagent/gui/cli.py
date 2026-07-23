"""CLI entry for ``heagent gui`` subcommand.

Thin wrapper that builds the Provider/AgentLoop and hands off to the Textual app.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

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

    # ── 日志配置（stderr + 文件双写，与 CLI 模式 `_setup_logging` 同构）──
    from heagent.config import get_settings

    _settings = get_settings()
    _console_level = getattr(logging, _settings.log_level.upper(), logging.INFO)
    _file_level = getattr(logging, (_settings.log_file_level or _settings.log_level).upper(), _console_level)

    _log_dir = Path(_settings.log_dir)
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _log_dir / f"heagent-gui-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    _console_handler = logging.StreamHandler(sys.stderr)
    _console_handler.setLevel(_console_level)
    _file_handler = logging.FileHandler(str(_log_file), encoding="utf-8")
    _file_handler.setLevel(_file_level)

    logging.basicConfig(
        level=min(_console_level, _file_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[_console_handler, _file_handler],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger.info("GUI session started — log file: %s", _log_file)

    # 沙箱提醒
    if sandbox == "firejail":
        import shutil as _shutil

        if _shutil.which(_settings.sandbox_firejail_path) is None:
            click.echo(
                f" WARNING: firejail not found ({_settings.sandbox_firejail_path}). "
                f"Shell commands will run WITHOUT sandbox isolation.",
                err=True,
            )
        else:
            click.echo(f" firejail sandbox ENABLED ({_settings.sandbox_firejail_path})", err=True)

    try:
        asyncio.run(gui_main(model=model, sandbox=sandbox))
    except ImportError:
        click.echo(
            "GUI 依赖未安装。请运行: pip install heagent[gui]",
            err=True,
        )
        raise SystemExit(1) from None
