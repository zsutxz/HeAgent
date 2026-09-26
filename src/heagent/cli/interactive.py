"""单次 / 交互模式执行：REPL 循环、斜杠命令族、内嵌 HTTP 服务的挂载点。

**为什么单独成模块**（`heagent/cli/` 包内拆分，2026-09-26）：这两条执行路径（``_run_single`` /
``_run_chat``）与它们在交互期的挂件（暂停/恢复、流式消费、斜杠命令注册表、会话 id 解析）合计约
500 行，与 Click 命令层的**注册与参数解析**是两件事。

**缝纪律**：``_run_prompt`` / ``_run_single`` 被测试 patch，**调用方必须在本模块**（``_run_chat`` /
``_build_slash_registry`` 在此）；Click 命令层要用 ``_run_single`` 时走**函数内导入**（见 console.py）。

**不反向依赖 console.py**：本模块只依赖 composition（装配）与 ``cli/http.py``（内嵌服务，函数内导入），
否则与 console 的命令注册形成模块级环。

分层：本模块属**入口层**，不被下层反向导入。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

import heagent.tools.builtins  # noqa: F401
from heagent.cli.composition import (
    _build_dream_scheduler,
    _build_event_sink,
    _build_loop,
    _build_soul,
    _extract_routing,
    _prepare_engine,
)
from heagent.cli.display import (
    _echo_status,
    _format_status,
    _LineState,
    _print_stream_event,
    _print_usage,
    show_deferred_work,
    show_tool_activity,
)
from heagent.cli.goal import _goal_runner
from heagent.config import GLOBAL_CONFIG_DIR, Settings, get_settings
from heagent.context.session import SessionStore
from heagent.exceptions import BudgetExceeded, HeAgentError
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.providers.router import active_model, display_reason
from heagent.providers.switchable import SwitchableProvider
from heagent.slash import SlashRegistry, load_custom_commands
from heagent.terminal import KeyInterruptMonitor
from heagent.tools.mcp import MCPClientManager
from heagent.workspace import WorkspacePaths

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AbstractAsyncContextManager

    from heagent.agent.loop import AgentLoop
    from heagent.cron.jobs import JobStore
    from heagent.providers.base import BaseProvider


def _report_mcp_discovery_failures(mcp_manager: object) -> None:
    """MCP 发现阶段失败的结构化呈报（单 server 隔离后仍可见，不隐藏发现错误）。

    manager 无失败时零输出；非 MCPClientManager（nullcontext 场景）不处理。
    """
    if not isinstance(mcp_manager, MCPClientManager):
        return
    for failure in mcp_manager.discovery_failures:
        click.echo(f"[mcp] server '{failure.server}' 连接/发现失败，已隔离：{failure.reason}", err=True)


@contextlib.asynccontextmanager
async def _embedded_http_service(settings: Settings, provider: BaseProvider) -> AsyncIterator[Any]:
    """默认 CLI 的内嵌 HTTP 服务（Epic 49 Story 49-2/49-3）。

    交互模式与 REPL 共存、单次模式与那次 run 并存；两种模式都在**同一个 asyncio 生命周期**内启动
    与收尾（AD-5：``cli/http`` 是唯一生命周期所有者）。`heagent gui` / `tcp-server` / `http-server` /
    `init` / `replay` 都不经过本函数，因此**不会**派生第二个 HTTP 实例。

    运行入口是入口层的 ``HttpAgentHandler``（每运行新建独立 ``AgentLoop``、自建 engine 不装审批、
    不连 MCP）；它只共享 ``provider`` 与 CLI 进程，不共享 CLI 终端的引擎与会话。

    启动失败（端口被占 / 缺 ``heagent[http]``）直接抛出——由 :func:`_run_with_embedded_http` 转成
    命令级错误并退出，绝不进入「聊天看着正常、网页入口其实没起来」的半启动状态。

    ``build_http_service`` / ``HttpAgentHandler`` 在**函数内**导入：``cli/http`` 在模块尾部 import 本
    模块注册命令，模块级互相导入会成环。测试缝因此落在 ``heagent.cli.http.build_http_service``
    （**不要**在本模块顶部绑定该名字，否则缝会漂到 cli 上、既有 patch 目标失效）。
    """
    from heagent.cli.http import build_http_service  # noqa: PLC0415
    from heagent.cli.http_console import HttpAgentHandler  # noqa: PLC0415

    handler = HttpAgentHandler(provider, settings)
    async with build_http_service(settings, executor=handler) as service:
        yield service


async def _run_single(
    prompt: str,
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
    soul_path: str | None = None,
    mcp_ctx: AbstractAsyncContextManager[Any] | None = None,
    sandbox_backend: str | None = None,
    plan_mode: bool = False,
    json_output: bool = False,
    sandbox_session_workspace: bool | None = None,
    sandbox_session_keep: bool | None = None,
) -> None:
    """Run a single prompt and print the result.

    ``json_output=True``（``--json``）时 **stdout 只出 JSONL 事件流**：最终答案作为
    ``assistant_message`` 事件交回，横幅 / 用量 / 活动回顾等人类可读信息本就走 stderr，
    故管道消费方拿到的是干净的事件流。
    """
    settings = get_settings()
    engine, system = _prepare_engine(
        sandbox_backend=sandbox_backend,
        sandbox_session_workspace=sandbox_session_workspace,
        sandbox_session_keep=sandbox_session_keep,
        plan_mode=plan_mode,
        system=system,
        tty_approval=True,
    )

    sink = _build_event_sink(settings, json_output=json_output)
    if sink is not None:
        engine.events.subscribe(sink)

    async with _embedded_http_service(settings, provider), mcp_ctx or contextlib.nullcontext() as mcp_manager:
        _report_mcp_discovery_failures(mcp_manager)
        loop, _ = _build_loop(
            settings, provider, max_iterations, soul_path, engine=engine, sandbox_backend=sandbox_backend
        )
        try:
            result = await loop.run(prompt, system=system)
            if sink is not None and json_output:
                sink.assistant_message(result)
            else:
                click.echo(result)
            _print_usage(loop.last_usage, model=loop.provider.get_metadata().model)
        except BudgetExceeded as exc:
            click.echo(f"[budget exceeded] {exc.message}", err=True)
        except HeAgentError as exc:
            click.echo(f"[error] {exc.message}", err=True)
        finally:
            # 活动回顾放 finally：出错/超预算时「它到底动了什么」往往才是最需要看的。
            show_tool_activity(loop)


def _setup_readline() -> None:
    """配置 readline 历史（Epic 35 体验优化）；readline 不可用（如 Windows）时静默跳过。"""
    try:
        import readline  # noqa: PLC0415
    except ImportError:
        return
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    histfile = GLOBAL_CONFIG_DIR / "history"
    with contextlib.suppress(OSError, FileNotFoundError):
        # unused-ignore：Windows 的 readline 存根缺这些属性（ignore 被使用），Linux 的
        # 有（ignore 未被使用）——列上 unused-ignore 让两个平台都不报 strict 的未用告警。
        readline.read_history_file(str(histfile))  # type: ignore[attr-defined, unused-ignore]
    readline.set_history_length(1000)  # type: ignore[attr-defined, unused-ignore]
    import atexit  # noqa: PLC0415

    atexit.register(readline.write_history_file, str(histfile))  # type: ignore[attr-defined, unused-ignore]


def _resolve_session_id(
    session: SessionStore,
    *,
    continue_session: bool = False,
    resume_session: str | None = None,
) -> str:
    """决定本次交互会话的 session_id（Epic 30）。

    - ``resume_session`` 指定时复用该 id；
    - ``continue_session`` 时复用最近一次会话 id（无历史则回退新 id 并提示）；
    - 否则新建随机 id。
    """
    if resume_session:
        return resume_session
    if continue_session:
        recent = session.recent_session_ids(1)
        if recent:
            click.echo(f"[session] Continuing most recent session: {recent[0]}", err=True)
            return recent[0]
        click.echo("[session] No prior session found; starting a new one.", err=True)
    return uuid.uuid4().hex[:8]


async def _run_chat(
    provider: BaseProvider,
    system: str | None,
    max_iterations: int,
    soul_path: str | None = None,
    mcp_ctx: AbstractAsyncContextManager[Any] | None = None,
    sandbox_backend: str | None = None,
    continue_session: bool = False,
    resume_session: str | None = None,
    plan_mode: bool = False,
    sandbox_session_workspace: bool | None = None,
    sandbox_session_keep: bool | None = None,
) -> None:
    """Run interactive chat mode."""
    _setup_readline()
    settings = get_settings()
    engine, system = _prepare_engine(
        sandbox_backend=sandbox_backend,
        sandbox_session_workspace=sandbox_session_workspace,
        sandbox_session_keep=sandbox_session_keep,
        plan_mode=plan_mode,
        system=system,
    )

    async with _embedded_http_service(settings, provider) as http, mcp_ctx or contextlib.nullcontext() as mcp_manager:
        _report_mcp_discovery_failures(mcp_manager)
        paths = WorkspacePaths.from_root(os.getcwd())
        session = SessionStore(str(paths.sessions))
        # 会话复用（Epic 30）：--resume 指定 / --continue 最近 / 否则新建。
        session_id = _resolve_session_id(session, continue_session=continue_session, resume_session=resume_session)
        # 预构建记忆存储，与 DreamScheduler 共享同一份实例（dream 回写即主 loop 可见）。
        skills = SkillStore(str(paths.skills))
        facts = FactStore(str(paths.memory_file))
        profile = ProfileStore(str(paths.profile_file))
        soul = _build_soul(soul_path)
        loop, scheduler = _build_loop(
            settings,
            provider,
            max_iterations,
            soul_path,
            session=session,
            engine=engine,
            sandbox_backend=sandbox_backend,
            skills=skills,
            facts=facts,
            profile=profile,
            soul=soul,
        )
        dream_scheduler = _build_dream_scheduler(settings, provider, engine, session, skills, facts, profile, soul)
        registry = _build_slash_registry(provider, mcp_manager, session, session_id, loop, system, loop.cron_store)
        click.echo(
            f"HeAgent interactive mode (session: {session_id}). Type your message (Esc to pause, Enter to resume, double Esc to interrupt, Ctrl+C to exit)."
        )

        try:
            if scheduler:
                await scheduler.start()
            if dream_scheduler:
                await dream_scheduler.start()
            while True:
                # 网页入口挂掉后 CLI 继续正常聊天 = 「页面打不开但看着一切正常」的假可用
                # 状态（AD-5）。每轮检查一次：把 serve 循环的意外结束如实报出并退出交互。
                if http.failure is not None:
                    click.echo(f"[http] service stopped unexpectedly: {http.failure}", err=True)
                    break
                try:
                    status = _format_status(loop)
                    user_input = await asyncio.to_thread(input, f"{status}\n> ")
                except (KeyboardInterrupt, EOFError):
                    click.echo("\nBye!")
                    break

                if not user_input.strip():
                    continue

                if user_input.startswith("/"):
                    handled = await _dispatch_slash_interactive(user_input, registry)
                    if handled:
                        continue

                await _run_prompt(loop, user_input, system, session_id)
        finally:
            if dream_scheduler:
                await dream_scheduler.stop()
            if scheduler:
                await scheduler.stop()


# =============================================================================
# Slash command routing (CLI interactive mode)
# =============================================================================


def _pause_loop(loop: AgentLoop, line_state: _LineState) -> None:
    """暂停当前 run（幂等，已暂停则无操作）。"""
    if not loop.is_paused:
        loop.pause()
        _echo_status("[paused] Run paused (Enter to resume).", line_state)
        # 补一行状态：暂停常发生在长工具中途，把在途工具显示出来才知道卡在哪。
        _echo_status(_format_status(loop), line_state)


def _resume_loop(loop: AgentLoop, line_state: _LineState) -> None:
    """恢复被暂停的 run（幂等，未暂停则无操作）。"""
    if loop.is_paused:
        loop.unpause()
        _echo_status("[paused] Run resumed.", line_state)
        _echo_status(_format_status(loop), line_state)


async def _run_prompt(loop: AgentLoop, prompt: str, system: str | None, session_id: str) -> None:
    """把一条用户消息提交给 loop 流式执行并打印结果（自定义斜杠命令复用）。

    运行期间后台监听按键：
      - 单击 Esc 暂停当前 run（暂停不取消，恢复后从挂起点继续）；
      - Enter 恢复被暂停的 run；
      - 双击 Esc 取消当前 run、回到交互输入状态（程序不退出）。
    """
    monitor = KeyInterruptMonitor()
    monitor.start(asyncio.get_running_loop())
    line_state = _LineState()
    run_task = asyncio.create_task(_consume_stream(loop, prompt, system, session_id, line_state))
    interrupt_wait: asyncio.Task[bool] | None = None
    pause_wait: asyncio.Task[bool] | None = None
    resume_wait: asyncio.Task[bool] | None = None
    try:
        if monitor.active:
            interrupt_wait = asyncio.create_task(monitor.interrupted.wait())
            while not run_task.done():
                pause_wait = asyncio.create_task(monitor.pause_toggle.wait())
                resume_wait = asyncio.create_task(monitor.resume.wait())
                done, _ = await asyncio.wait(
                    {run_task, interrupt_wait, pause_wait, resume_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if run_task.done():
                    break
                if interrupt_wait in done:
                    run_task.cancel()
                    break
                if pause_wait in done:
                    _pause_loop(loop, line_state)
                    monitor.pause_toggle.clear()
                if resume_wait in done:
                    _resume_loop(loop, line_state)
                    monitor.resume.clear()
                for task in (pause_wait, resume_wait):
                    task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            _echo_status("[interrupted] Run interrupted by double Esc.", line_state)
    finally:
        monitor.stop()

        async def _cancel(task: asyncio.Task[bool] | None) -> None:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        await _cancel(interrupt_wait)
        await _cancel(pause_wait)
        await _cancel(resume_wait)


async def _consume_stream(
    loop: AgentLoop, prompt: str, system: str | None, session_id: str, line_state: _LineState
) -> None:
    """消费 ``loop.run_stream`` 并打印；业务异常在此收口（CancelledError 透传）。"""
    try:
        async for event in loop.run_stream(prompt, system=system, session_id=session_id):
            _print_stream_event(event, line_state)
        if not line_state.at_line_start:
            click.echo("")
            line_state.at_line_start = True
        _print_usage(loop.last_usage, model=loop.provider.get_metadata().model)
    except BudgetExceeded as exc:
        click.echo(f"[budget exceeded] {exc.message}", err=True)
    except HeAgentError as exc:
        click.echo(f"[error] {exc.message}", err=True)


def _build_slash_registry(
    provider: BaseProvider,
    mcp_manager: Any,
    session: SessionStore | None,
    session_id: str,
    loop: AgentLoop,
    system: str | None,
    cron_store: JobStore | None = None,
) -> SlashRegistry:
    """构造斜杠命令注册表：内置命令 + 用户自定义命令（Epic 31）。"""
    registry = SlashRegistry()

    async def _model(args: str) -> None:
        await _handle_model_cmd(["/model", *args.split()], provider)

    async def _route(args: str) -> None:
        await _handle_route_cmd(provider, args)

    async def _mcp_prompt(args: str) -> None:
        await _handle_mcp_prompt(f"/mcp-prompt {args}".strip(), mcp_manager)

    async def _clear(args: str) -> None:
        if session is not None:
            session.delete(session_id)
        click.echo("[clear] Session history cleared. Next message starts fresh.", err=True)

    async def _help(args: str) -> None:
        click.echo("Available slash commands:", err=True)
        for name in registry.names():
            click.echo(f"  /{name}  {registry.describe(name)}", err=True)

    registry.register("model", "切换 LLM 模型", _model)
    registry.register("route", "智能路由状态 / 强制模型 (<name>|auto)", _route)
    registry.register("mcp-prompt", "调度 MCP prompt", _mcp_prompt)

    async def _deferred(args: str) -> None:
        show_deferred_work(Path.cwd())

    registry.register("deferred", "列出 deferred-work 台账（遗留项登记）", _deferred)
    registry.register("clear", "清空当前会话上下文", _clear)
    registry.register("help", "列出所有斜杠命令", _help)

    async def _goal(args: str) -> None:
        await _goal_runner(provider, loop.engine, args, cron_store=cron_store)

    registry.register("goal", "目标驱动开发（new/next/run/status/pause/resume/auto/reset）", _goal)

    for command in load_custom_commands():
        prompt = command.prompt

        async def _custom(args: str, prompt: str = prompt) -> None:
            await _run_prompt(loop, prompt, system, session_id)

        registry.register(command.name, command.description, _custom)

    return registry


async def _handle_slash(user_input: str, registry: SlashRegistry) -> bool:
    """Route slash commands via registry; returns True if handled, False to pass through."""
    parts = user_input.split()
    cmd = parts[0].lower() if parts else ""
    if not cmd.startswith("/"):
        return False
    name = cmd[1:]
    args = " ".join(parts[1:])
    return await registry.dispatch(name, args)


async def _dispatch_slash_interactive(user_input: str, registry: SlashRegistry) -> bool:
    """Dispatch one interactive slash command while preserving cancellation semantics."""
    try:
        return await _handle_slash(user_input, registry)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        click.echo("[interrupted] Slash command interrupted; state is preserved.", err=True)
        return True
    except Exception as exc:
        click.echo(f"[error] Slash command failed: {exc}", err=True)
        return True


async def _handle_model_cmd(parts: list[str], provider: BaseProvider) -> None:
    """Handle /model slash command for runtime LLM switching."""
    if not isinstance(provider, SwitchableProvider):
        click.echo("[model] Only one provider configured; switching not available.", err=True)
        return

    if len(parts) == 1:
        info = provider.info()
        click.echo("Available models:", err=True)
        for name, meta in info.items():
            marker = "->" if meta.active else " "
            display_model = active_model(provider.providers[name]) or meta.model
            click.echo(f"  [{marker}] {name}  ({display_model})", err=True)
        return

    name = parts[1]
    try:
        await provider.switch(name)
        display_model = active_model(provider.current) or provider.get_metadata().model
        click.echo(f"[model] Switched to {name} ({display_model})", err=True)
    except ValueError as exc:
        click.echo(f"[model] {exc}", err=True)


async def _handle_route_cmd(provider: BaseProvider, args: str = "") -> None:
    """Handle /route slash command: show/force smart-routing model.

    ``/route``           显示路由池 + 最近决策 + 当前强制状态；
    ``/route <name>``    强制固定使用池内某个模型（后续调用跳过启发式路由）；
    ``/route auto``      清除强制，恢复自动路由。
    """
    routing, hint = _extract_routing(provider)
    if routing is None:
        if hint:
            click.echo(f"[route] {hint}", err=True)
        else:
            click.echo("[route] Smart routing not enabled (configure ROUTING_POOLS).", err=True)
        return

    arg = (args or "").strip().lower()
    if arg == "auto":
        routing.set_force(None)
        click.echo("[route] Forced model cleared; back to auto routing.", err=True)
        return
    if arg:
        if arg in routing.names:
            try:
                routing.set_force(arg)
            except ValueError as exc:
                click.echo(f"[route] {exc}", err=True)
                return
            click.echo(f"[route] Forced model -> {arg} ({routing.current_model})", err=True)
            return
        click.echo(f"[route] Unknown argument {arg!r} (use: {' | '.join(routing.names)} | auto).", err=True)
        return

    click.echo("Smart routing pool:", err=True)
    click.echo(f"  models: {routing.get_metadata().model}", err=True)
    if routing.force is not None:
        click.echo(f"  forced: {routing.force} ({routing.current_model})", err=True)
    if routing.last_decision is not None:
        # 与状态行同一展示策略：兜底理由（default_fast）不展示——它不解释任何东西，
        # 还容易被误读成模型名。原始 reason 仍可查（日志 / active_route_reason）。
        line = f"  last decision: {routing.last_decision.provider}"
        reason = display_reason(routing.last_decision.reason)
        if reason:
            line += f" ({reason})"
        click.echo(line, err=True)
    else:
        click.echo("  last decision: (none yet)", err=True)


def _format_prompt_args(args: list[dict[str, Any]]) -> str:
    """Format MCP Prompt arguments list for display."""
    if not args:
        return "(no args)"
    return " ".join(f"{a['name']}=..." if a.get("required") else f"{a['name']}?" for a in args)


async def _handle_mcp_prompt(user_input: str, mcp_manager: Any) -> None:
    """Handle /mcp-prompt slash command in chat mode."""
    if mcp_manager is None or not hasattr(mcp_manager, "list_prompts"):
        click.echo("[mcp] No MCP server connected.", err=True)
        return

    parts = user_input.split()

    if len(parts) == 1:
        result = await mcp_manager.list_prompts()
        data = json.loads(result)
        if not data:
            click.echo("[mcp-prompt] No prompts available.")
            return
        for p in data:
            server = p["server"]
            name = p["name"]
            desc = p.get("description", "")
            arg_str = _format_prompt_args(p.get("arguments", []))
            click.echo(f"  [{server}] {name}: {desc} ({arg_str})")
        return

    if len(parts) == 2:
        server = parts[1]
        result = await mcp_manager.list_prompts(server)
        data = json.loads(result)
        if not data:
            click.echo(f"[mcp-prompt] No prompts on server '{server}'.")
            return
        for p in data:
            name = p["name"]
            desc = p.get("description", "")
            arg_str = _format_prompt_args(p.get("arguments", []))
            click.echo(f"  {name}: {desc} ({arg_str})")
        return

    server = parts[1]
    prompt_name = parts[2]
    arguments: dict[str, str] = {}
    for arg in parts[3:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            arguments[k] = v
    try:
        text = await mcp_manager.get_prompt(server, prompt_name, arguments or None)
        guarded = _guard_mcp_content(text)
        click.echo(guarded)
    except Exception as exc:
        click.echo(f"[mcp-prompt error] {exc}", err=True)


def _guard_mcp_content(text: str) -> str:
    """Apply heuristic injection guard to MCP prompt output (non-bridge path, CLI only)."""
    from heagent.tools.mcp.mapping import guard_content  # noqa: PLC0415

    return guard_content(text)
