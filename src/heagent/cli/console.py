"""Command-line entrypoint for HeAgent."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

import heagent.tools.builtins  # noqa: F401
from heagent.cli.display import (
    _print_banner,
)
from heagent.config import Settings, get_settings
from heagent.events.sink import read_rollout, render_event
from heagent.exceptions import HeAgentError
from heagent.providers.router import active_model
from heagent.providers.switchable import SwitchableProvider
from heagent.roles import load_agent_roles
from heagent.safe_logging import install_logging_fault_guard
from heagent.tools.mcp import MCPClientManager, load_mcp_config
from heagent.wiring import _build_provider

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure logging for CLI mode (stderr console + file).

    同时安装进程级日志故障守卫（:func:`~heagent.safe_logging.install_logging_fault_guard`）：
    handler 写失败只降级成「少一条日志」，不得让成功的 run 因日志设施故障而失败。
    """
    install_logging_fault_guard()
    _settings = get_settings()
    _console_level = getattr(logging, _settings.log_level.upper(), logging.INFO)
    _file_level = getattr(logging, (_settings.log_file_level or _settings.log_level).upper(), _console_level)
    _log_dir = Path(_settings.log_dir)
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _log_dir / f"heagent-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

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


def _prune_runtime_artifacts(settings: Settings) -> None:
    """启动时回收运行时产物（日志 / 会话 / 编辑快照）：best-effort，绝不阻断启动。

    具体实现在 ``heagent.housekeeping``（单独成模块便于直接测试）；这里只做「失败不上抛」。
    """
    try:
        from heagent.housekeeping import prune_runtime_artifacts_sync

        prune_runtime_artifacts_sync(settings)
    except Exception:
        logger.warning("runtime artifact cleanup failed; continuing", exc_info=True)


async def _prompt_startup_provider(provider: SwitchableProvider) -> None:
    """Prompt the user to select a provider at startup (interactive mode).

    ACTIVE_PROVIDER in .env determines the default (press Enter to accept).
    """
    if not sys.stdin.isatty():
        return

    info = provider.info()
    names = list(info.keys())

    if len(names) <= 1:
        return

    default_idx = names.index(provider.active) + 1

    click.echo("Multiple providers available. Choose one:", err=True)
    for i, name in enumerate(names, 1):
        meta = info[name]
        # 智能路由条目（RoutingProvider）：只显示默认模型（如 deepseek-flash），而非池内全部模型列表。
        display_model = active_model(provider.providers[name]) or meta.model
        marker = "<- default" if i == default_idx else ""
        click.echo(f"  [{i}] {name}  ({display_model})  {marker}", err=True)

    while True:
        try:
            raw = click.prompt("Select (number)", type=str, default=str(default_idx))
            choice = int(raw)
            if 1 <= choice <= len(names):
                await provider.switch(names[choice - 1])
                display_model = active_model(provider.current) or provider.get_metadata().model
                click.echo(f"  -> Using {provider.active} ({display_model})", err=True)
                return
            click.echo(f"  Please enter 1-{len(names)}", err=True)
        except (ValueError, click.Abort):
            raise SystemExit(0) from None


def _mcp_lifecycle(settings: Settings) -> AbstractAsyncContextManager[Any]:
    """Return the MCP lifecycle context manager based on current settings."""
    if not settings.mcp_enabled:
        logger.info("MCP disabled via settings")
        return contextlib.nullcontext()
    config = load_mcp_config(settings.mcp_config_path)
    if config.is_empty:
        return contextlib.nullcontext()
    return MCPClientManager(config)


def _run_with_embedded_http(awaitable_factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """跑默认 CLI 的 asyncio 生命周期（单次 / 交互），把内嵌 HTTP 的启动失败转成命令错误。

    用**工厂**而不是现成 coroutine：``asyncio.run`` 自建事件循环，awaitable 必须在它内部创建，
    否则会以「attached to a different loop」这类 `RuntimeError` 的形式炸出来。
    """
    from heagent.cli.http import embedded_http_error_message  # noqa: PLC0415

    try:
        asyncio.run(awaitable_factory())
    except Exception as exc:
        message = embedded_http_error_message(exc)
        if message is None:
            raise
        # 绑定冲突 / 缺可选依赖：一行可诊断文案 + 非零退出（exit 1），不吐 traceback。
        raise click.ClickException(message) from None


# =============================================================================
# Core CLI implementation (shared by run subcommand and default path)
# =============================================================================


def _run_cli_impl(
    prompt: str | None,
    model: str | None,
    system: str | None,
    max_iterations: int | None,
    soul: str | None,
    sandbox: str | None,
    continue_session: bool = False,
    resume_session: str | None = None,
    plan_mode: bool = False,
    json_output: bool = False,
    sandbox_session_workspace: bool | None = None,
    sandbox_session_keep: bool | None = None,
) -> None:
    """Core CLI routine — logging, provider, MCP, dispatch to single/chat."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _setup_logging()
    _print_banner()

    settings = get_settings()
    # 启动时回收运行时产物（日志 / 会话 / 编辑快照）：best-effort，失败只记日志不阻断启动。
    _prune_runtime_artifacts(settings)
    resolved_iterations = max_iterations or settings.max_iterations
    resolved_plan = plan_mode or settings.plan_mode
    provider = _build_provider(settings, model)

    # 函数内导入（**函数内**才能让缝生效）：`_run_single` / `_run_chat` 住在 cli/interactive.py，
    # 与其调用方同模块的缝纪律要求「调用期按模块属性查找」——模块级导入会在本模块绑定一份副本，
    # 测试 patch `heagent.cli.interactive._run_single` 就打不中。
    from heagent.cli.interactive import _run_chat, _run_single  # noqa: PLC0415

    # 加载配置文件驱动的自定义角色（Epic 34）：.heagent/agents/*.md + ~/.heagent/agents/*.md
    load_agent_roles()

    # --- Sandbox warning ---
    sandbox_resolved = sandbox or settings.sandbox_backend
    if sandbox_resolved == "firejail":
        import shutil as _shutil

        if _shutil.which(settings.sandbox_firejail_path) is None:
            click.echo(
                f" WARNING: firejail not found ({settings.sandbox_firejail_path}). "
                f"Shell commands will run WITHOUT sandbox isolation. "
                f"Install firejail: sudo apt install firejail",
                err=True,
            )
        else:
            click.echo(f" firejail sandbox ENABLED ({settings.sandbox_firejail_path})", err=True)

    # --- Interactive provider selection at startup ---
    if isinstance(provider, SwitchableProvider):
        asyncio.run(_prompt_startup_provider(provider))

    try:
        mcp_ctx = _mcp_lifecycle(settings)
    except HeAgentError as exc:
        click.echo(f"[mcp config error] {exc.message}", err=True)
        raise SystemExit(1) from None

    if prompt:
        _run_with_embedded_http(
            lambda: _run_single(
                prompt,
                provider,
                system,
                resolved_iterations,
                soul_path=soul,
                mcp_ctx=mcp_ctx,
                sandbox_backend=sandbox,
                plan_mode=resolved_plan,
                json_output=json_output,
                sandbox_session_workspace=sandbox_session_workspace,
                sandbox_session_keep=sandbox_session_keep,
            )
        )
    else:
        _run_with_embedded_http(
            lambda: _run_chat(
                provider,
                system,
                resolved_iterations,
                soul_path=soul,
                mcp_ctx=mcp_ctx,
                sandbox_backend=sandbox,
                continue_session=continue_session,
                resume_session=resume_session,
                plan_mode=resolved_plan,
                sandbox_session_workspace=sandbox_session_workspace,
                sandbox_session_keep=sandbox_session_keep,
            )
        )


# =============================================================================
# Click command group (with DefaultGroup for backward-compatible "heagent msg")
# =============================================================================

_RUN_OPTIONS = [
    click.argument("prompt", required=False),
    click.option("--model", default=None, help="Model name (default: per-provider setting)"),
    click.option("--system", default=None, help="System prompt"),
    click.option("--max-iterations", type=int, default=None, help="Max agent loop iterations"),
    click.option("--soul", default=None, help="Path to custom SOUL.md personality file"),
    click.option(
        "--sandbox",
        type=click.Choice(["auto", "passthrough", "firejail", "winjob"]),
        default=None,
        help="Sandbox backend for shell execution (default: auto = probe firejail)",
    ),
    click.option(
        "--sandbox-session-workspace/--no-sandbox-session-workspace",
        "sandbox_session_workspace",
        default=None,
        help="Per-run sandbox session dir for shell (default: SANDBOX_SESSION_WORKSPACE env)",
    ),
    click.option(
        "--sandbox-session-keep/--no-sandbox-session-keep",
        "sandbox_session_keep",
        default=None,
        help="Keep the per-run sandbox session dir after the run (default: SANDBOX_SESSION_KEEP env)",
    ),
    click.option(
        "--continue",
        "continue_session",
        is_flag=True,
        default=False,
        help="Continue the most recent session (interactive mode)",
    ),
    click.option(
        "--resume",
        "resume_session",
        default=None,
        help="Resume a specific session by id (interactive mode)",
    ),
    click.option(
        "--plan",
        "plan_mode",
        is_flag=True,
        default=False,
        help="Plan mode: read-only (no write tools / shell)",
    ),
    click.option(
        "--json",
        "json_output",
        is_flag=True,
        default=False,
        help="Single-shot: emit a JSONL event stream on stdout (human output stays on stderr)",
    ),
]


def _apply_options(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: apply shared CLI options to a Click command."""
    for opt in reversed(_RUN_OPTIONS):
        fn = opt(fn)
    return fn


class DefaultGroup(click.Group):
    """A Click Group that falls back to the ``default_command`` when an unknown
    command name is provided (instead of raising ``NoSuchCommand``).

    This allows ``heagent "hello"`` to be treated as ``heagent run "hello"``
    while explicit subcommands (``gui``, ``run``) take priority.
    """

    _default_command: str | None = None

    def set_default_command(self, name: str) -> None:
        self._default_command = name

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        """已注册子命令优先；其余一律回退到默认命令 run 解析。

        ``heagent "prompt"`` 与 ``heagent --model X "prompt"`` 都依赖该回退——
        未知选项随后仍由 run 自身的解析器报错，不会静默吞掉。
        """
        if args and args[0] in self.commands:
            return super().resolve_command(ctx, args)
        default = self._default_command
        if default is not None and default in self.commands:
            return default, self.commands[default], args
        return super().resolve_command(ctx, args)


@click.command(cls=DefaultGroup, invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """HeAgent — A self-improving AI Agent core framework.

    Run without arguments for interactive chat mode, or provide a prompt
    for single-shot execution.

    \b
    Examples:
      heagent                        # interactive chat
      heagent "analyze this file"    # single-shot
      heagent run "prompt"           # explicit run subcommand
      heagent init                   # create global config in ~/.heagent
      heagent gui                    # launch terminal UI
    """
    if ctx.invoked_subcommand is None:
        # No subcommand -> interactive mode
        ctx.invoke(run, prompt=None)


@main.command("run")
@_apply_options
def run(
    prompt: str | None,
    model: str | None,
    system: str | None,
    max_iterations: int | None,
    soul: str | None,
    sandbox: str | None,
    continue_session: bool,
    resume_session: str | None,
    plan_mode: bool,
    json_output: bool = False,
    sandbox_session_workspace: bool | None = None,
    sandbox_session_keep: bool | None = None,
) -> None:
    """Run HeAgent in single-shot or interactive mode."""
    _run_cli_impl(
        prompt,
        model,
        system,
        max_iterations,
        soul,
        sandbox,
        continue_session,
        resume_session,
        plan_mode,
        json_output=json_output,
        sandbox_session_workspace=sandbox_session_workspace,
        sandbox_session_keep=sandbox_session_keep,
    )


@main.command("replay")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit raw JSONL instead of rendered lines")
def replay_cmd(path: Path, as_json: bool) -> None:
    """Replay a rollout / JSONL event file (from ``--json`` or ``EVENTS_ROLLOUT_ENABLED``)."""
    events = read_rollout(path)
    if not events:
        click.echo(f"[replay] no events in {path}", err=True)
        return
    for event in events:
        click.echo(event.to_jsonl() if as_json else render_event(event))


# Init 子命令在 cli/init.py（wiring.py 先例：模板文案与命令定义随配置项变，与交互编排变化原因不同）。
# 尾部导入而非模块顶部：`main` 命令组要先定义，子模块才能挂命令（模块级互导会成环）。
from heagent.cli.init import init_cmd  # noqa: E402

main.add_command(init_cmd)

# Set run as the default command (heagent "hello" -> run "hello")
main.set_default_command("run")

# Register the lightweight GUI command wrapper; Textual itself remains lazy.
from heagent.gui.cli import gui_cmd  # noqa: E402

main.add_command(gui_cmd)

# TCP Server 子命令（Epic 48 Story 48-3）同样随命令定义拆分到入口层模块：命令只在显式调用时
# 才装配 Provider / Engine（普通 CLI 不监听任何端口），此处仅注册，保持 heagent.cli 命名空间可用。
from heagent.cli.tcp import tcp_server_cmd  # noqa: E402

main.add_command(tcp_server_cmd)

# HTTP 网页入口子命令（Epic 49 Story 49-1）：与 tcp-server 同理——只有显式调用该命令才导入
# 可选 HTTP 栈（`heagent[http]`）并绑定端口；普通 CLI 用法、gui、init、replay 都不监听 HTTP，
# 也都不因缺 starlette/uvicorn 而失败。49-2 起默认 CLI 会**在同一进程内**另起 HTTP 服务，
# 而显式 http-server 永远只起这一份（不派生子实例）。
from heagent.cli.http import http_server_cmd  # noqa: E402

main.add_command(http_server_cmd)
