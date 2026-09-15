"""CLI entry for ``heagent gui`` subcommand.

Thin wrapper that builds the Provider/AgentLoop and hands off to the Textual app.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import click

logger = logging.getLogger(__name__)


def _is_missing_textual(error: ImportError) -> bool:
    return error.name == "textual" or (error.name or "").startswith("textual.")


@click.command("gui")
@click.option("--model", default=None, help="Model name (default: per-provider setting)")
@click.option(
    "--sandbox",
    type=click.Choice(["passthrough", "firejail"]),
    default=None,
    help="Sandbox backend for shell execution",
)
@click.option(
    "--sandbox-session-workspace/--no-sandbox-session-workspace",
    "sandbox_session_workspace",
    default=None,
    help="Per-run sandbox session dir for shell (default: SANDBOX_SESSION_WORKSPACE env)",
)
@click.option(
    "--sandbox-session-keep/--no-sandbox-session-keep",
    "sandbox_session_keep",
    default=None,
    help="Keep the per-run sandbox session dir after the run (default: SANDBOX_SESSION_KEEP env)",
)
def gui_cmd(
    model: str | None,
    sandbox: str | None,
    sandbox_session_workspace: bool | None,
    sandbox_session_keep: bool | None,
) -> None:
    """Launch the HeAgent terminal UI."""
    try:
        from heagent.gui import gui_main  # noqa: PLC0415
    except ImportError as exc:
        if not _is_missing_textual(exc):
            raise
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

    # 启动时回收运行时产物（日志 / 会话 / 编辑快照）：与 CLI 同一实现，best-effort。
    try:
        from heagent.housekeeping import prune_runtime_artifacts_sync

        prune_runtime_artifacts_sync(_settings)
    except Exception:
        logger.warning("runtime artifact cleanup failed; continuing", exc_info=True)

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
        # gui_main 是同步入口（内部自行运行 Textual 事件循环）；
        # 不能包 asyncio.run()——gui_main 返回 None，asyncio.run(None) 会抛 TypeError。
        gui_main(
            model=model,
            sandbox=sandbox,
            sandbox_session_workspace=sandbox_session_workspace,
            sandbox_session_keep=sandbox_session_keep,
        )
    except ImportError as exc:
        if not _is_missing_textual(exc):
            raise
        click.echo(
            "GUI 依赖未安装。请运行: pip install heagent[gui]",
            err=True,
        )
        raise SystemExit(1) from None
