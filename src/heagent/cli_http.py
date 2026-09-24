"""``heagent http-server`` 子命令与 HTTP 服务装配（入口层组合根，Epic 49）。

本模块属**入口层**（与 ``cli`` / ``cli_init`` / ``cli_goal`` / ``cli_tcp`` / ``wiring`` 同级）：
它读设置、构造可选 HTTP 栈下的 :class:`~heagent.network.http_server.HttpServer`、注册 Click
命令；``network/`` 侧不反向依赖本模块（``tests/test_architecture_contracts.py`` 有可执行断言）。

Story 49-1 的职责只有「把服务拉起来、打得开网页、失败要显式」：

- 默认绑 ``127.0.0.1:8766``，并把**实际**监听地址打到 stderr；
- 非回环绑定复用 :mod:`heagent.network.exposure` 的判定与文案，启动前先告警；
- 缺 ``heagent[http]`` 可选依赖、端口被占用、健康探测失败都在命令层转成可读错误
  （``ClickException``），既不吐 traceback，也绝不打印「已监听」。

**默认 CLI 自启动（Story 49-2）、运行 API 与 SSE（49-3）、取消与限额（49-4）**都建立在本模块的
装配方式上；为了让那些 Story 不必重写这段编排，这里已经确定了两条边界：HTTP 服务与 CLI 共用
同一个 asyncio 生命周期（本模块只提供 ``_serve_http`` 这一种「跑到底」的形态），以及 CLI 覆盖
只作用于本次实例（``build_server_config`` 不写回 ``Settings`` 单例，与 TCP 入口一致）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

import click

from heagent.config import get_settings
from heagent.engine import EngineContainer
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.network.exposure import exposure_warning
from heagent.network.http_console_protocol import (
    ConsoleOperationError,
    ProjectEntryResponse,
    ProjectListResponse,
    ProjectRegisterRequest,
    ProjectRenameRequest,
)
from heagent.network.http_protocol import HttpUsage, RunOutcome
from heagent.network.http_server import (
    HttpDependencyError,
    HttpRunService,
    HttpServer,
    HttpServerConfig,
    HttpStartupError,
    RunEventPublisher,
)
from heagent.projects import ProjectRegistryError, default_project_registry
from heagent.safe_logging import safe_log
from heagent.wiring import _build_provider
from heagent.workspace import WorkspacePaths

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.config import Settings
    from heagent.providers.base import BaseProvider
    from heagent.types import TokenUsage

logger = logging.getLogger(__name__)


def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """记一条日志，**绝不让观测故障影响生命周期行为**（与 TCP / HTTP 传输层同一立场）。"""
    safe_log(logger, level, message, *args, exc_info=exc_info)


def _build_soul(soul_path: str | None) -> Any:
    """复用 ``cli._build_soul`` 的路径语义（global/project SOUL.md），不在此重复一份。"""
    from heagent.cli import _build_soul as _cli_build_soul  # noqa: PLC0415 —— 见模块 docstring 的成环说明

    return _cli_build_soul(soul_path)


def _to_http_usage(usage: TokenUsage | None) -> HttpUsage | None:
    """把 loop 采集到的用量映射为协议用量；未采集到时不发明数字。"""
    if usage is None:
        return None
    return HttpUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _resolve_model(loop: AgentLoop) -> str | None:
    """本次运行实际使用的模型名。

    只读**本次运行 loop** 的记录（``last_model``，由 provider 响应回填）：共享 provider 的路由状态
    （``active_model`` → ``RoutingProvider.last_decision``）是实例级「最近一次决策」，并发下会把
    兄弟请求的档位串味（与 ``cli_tcp._resolve_model`` 同一立场）。
    """
    return loop.last_model or loop.provider.get_metadata().model


def _current_version() -> str:
    """当前包版本（健康检查对外报告用）。

    在**函数内**导入根包：模块级导入根包会与 ``cli`` 的命令注册形成回环风险，而这里只在真正
    启动 HTTP 服务时才需要版本号（与 ``cli_display._current_version`` 同一手法）。
    """
    from heagent import __version__

    return __version__


def _reject_non_finite(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    """拒绝 ``NaN`` / ``Inf`` 超时值（``click.FloatRange`` 本身会放行它们）。

    不拦的后果与 TCP 入口一致：``Inf`` 让「有界关闭」静默变成无界等待，``NaN`` 绕过范围比较后
    直到 Pydantic 才以 traceback 炸掉（与其它非法值的 usage error 语义不一致）。
    """
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("must be a finite number", ctx=ctx, param=param)
    return value


def build_server_config(
    settings: Settings,
    *,
    host: str | None = None,
    port: int | None = None,
    max_connections: int | None = None,
    max_inflight_runs: int | None = None,
    max_request_bytes: int | None = None,
    event_buffer_size: int | None = None,
    run_history_size: int | None = None,
    request_timeout: float | None = None,
    shutdown_timeout: float | None = None,
) -> HttpServerConfig:
    """把 CLI 覆盖（``None`` = 未覆盖）合并到 ``Settings`` 的 HTTP 配置。

    两个不变量（与 ``cli_tcp.build_server_config`` 同义）：

    - **不写回 Settings**：覆盖只作用于本次服务实例，设置单例保持 env / 文件默认值；
    - **范围规则唯一**：CLI 侧先用 ``click`` 的 range 类型拦一道，最终仍由
      :class:`HttpServerConfig`（Pydantic）统一校验，避免 CLI 与 env 两套规则漂移。
    """
    return HttpServerConfig(
        host=settings.http_host if host is None else host,
        port=settings.http_port if port is None else port,
        max_connections=settings.http_max_connections if max_connections is None else max_connections,
        max_inflight_runs=settings.http_max_inflight_runs if max_inflight_runs is None else max_inflight_runs,
        max_request_bytes=settings.http_max_request_bytes if max_request_bytes is None else max_request_bytes,
        event_buffer_size=settings.http_event_buffer_size if event_buffer_size is None else event_buffer_size,
        run_history_size=settings.http_run_history_size if run_history_size is None else run_history_size,
        request_timeout=settings.http_request_timeout if request_timeout is None else request_timeout,
        shutdown_timeout=settings.http_shutdown_timeout if shutdown_timeout is None else shutdown_timeout,
    )


async def _serve_http(server: HttpServer) -> None:
    """启动服务并运行到取消 / 关闭；启动消息只走 stderr。

    ``start()`` 在 try 之外：它失败时要么 listener 没建起来、要么内部已回滚，不需要再 close；
    一旦进入服务循环，任何退出路径都必须走 ``close()``，否则 Ctrl+C 会留下悬挂的 listener。
    """
    await server.start()
    click.echo(
        f"[http] listening on http://{server.address}  (open this URL in a browser; no authentication)",
        err=True,
    )
    try:
        await server.serve_forever()
    finally:
        await server.close()


class HttpAgentHandler:
    """``prompt`` → 一次 ``AgentLoop.run_stream`` 的适配器（网络层只认这个可调用对象）。

    与 :class:`~heagent.cli_tcp.TcpAgentHandler` 同构——服务级共享 ``provider`` / ``engine`` /
    四个记忆存储（构造便宜、以只读为主），**每次运行新建 ``AgentLoop``**（loop 持有跨 run 可变展示态：
    ``last_usage`` / ``last_model`` / ``active_tool`` / 暂停 Event，共享单实例并发会互相覆盖）。

    **独立引擎，不装审批处理器**：HTTP handler 自建 ``EngineContainer``（``approval_handler=None``），
    因此需要审批的工具调用维持既有 fail-safe 阻断语义，而**不会**去读 CLI / 服务进程的 stdin——
    网络入口无人应答，装了只会把请求挂死（与 ``cli_tcp`` 同一决策）。代价是网页侧与 CLI 终端各有一份
    引擎与事件总线（记忆存储同样各自一份），互不干扰。

    **不连接 MCP**：``.mcp.json`` 声明的 server 属不可信代码 / 端点，网络入口自动连接等于把触达面
    暴露给任何能连上端口的人；需要 MCP 请在可控的交互式会话里显式启用。
    """

    def __init__(
        self,
        provider: BaseProvider,
        settings: Settings,
        *,
        engine: EngineContainer | None = None,
        system: str | None = None,
        max_iterations: int | None = None,
        sandbox_backend: str | None = None,
        soul_path: str | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.system = system
        self.max_iterations = max_iterations
        self.sandbox_backend = sandbox_backend
        # 网络入口不装审批处理器（见类 docstring）；engine 可注入（测试）但默认自建。
        paths = WorkspacePaths.from_root((engine.workspace_root if engine else None) or os.getcwd())
        self.engine = engine or EngineContainer.default(
            workspace_root=str(paths.root), sandbox_backend=sandbox_backend, settings=settings
        )
        self.skills = SkillStore(str(paths.skills))
        self.facts = FactStore(str(paths.memory_file))
        self.profile = ProfileStore(str(paths.profile_file))
        self.soul = _build_soul(soul_path)

    def new_loop(self) -> AgentLoop:
        """按服务级共享组件构造一个请求级 ``AgentLoop``（``session=None``：网页运行无会话文件）。"""
        from heagent.cli import _build_loop  # noqa: PLC0415 —— 见模块 docstring 的成环说明

        loop, _scheduler = _build_loop(
            self.settings,
            self.provider,
            self.max_iterations or self.settings.max_iterations,
            None,
            engine=self.engine,
            sandbox_backend=self.sandbox_backend,
            skills=self.skills,
            facts=self.facts,
            profile=self.profile,
            soul=self.soul,
        )
        return loop

    async def __call__(self, prompt: str, publisher: RunEventPublisher) -> RunOutcome:
        """跑一次流式运行并把 ``StreamEvent`` 映射为协议事件。

        ``CancelledError`` 原样传播（是取消，不是业务失败）；其它异常也原样抛出——由服务层统一
        收敛成脱敏的终态事件（``_client_error_message``）。答案与用量只从**这次运行**取。
        """
        loop = self.new_loop()
        answer = ""
        async for event in loop.run_stream(prompt, system=self.system):
            if event.type == "text":
                publisher.text(event.text)
            elif event.type == "tool_call":
                publisher.tool_call(event.tool_name, event.tool_target)
            elif event.type == "tool_result":
                publisher.tool_result(event.tool_name, event.tool_result_content, is_error=event.tool_error)
            elif event.type == "done":
                answer = event.final_answer
        return RunOutcome(
            answer=answer,
            model=_resolve_model(loop),
            usage=_to_http_usage(loop.last_usage),
        )


class HttpProjectConsole:
    """Entry-layer adapter that exposes the workspace project registry to HTTP."""

    def __init__(self, workspace: Path, *, projects_file: str | None = None) -> None:
        self.registry = default_project_registry(workspace, projects_file)
        self._busy: set[str] = set()

    async def list_projects(self) -> ProjectListResponse:
        return ProjectListResponse(
            projects=[ProjectEntryResponse(**entry.model_dump()) for entry in self.registry.list()]
        )

    async def register_project(self, request: ProjectRegisterRequest) -> ProjectEntryResponse:
        try:
            entry = self.registry.register(request.path, request.name)
        except ProjectRegistryError as exc:
            raise ConsoleOperationError(exc.code, str(exc)) from exc
        return ProjectEntryResponse(**entry.model_dump())

    async def rename_project(self, project_id: str, request: ProjectRenameRequest) -> ProjectEntryResponse:
        try:
            entry = self.registry.rename(project_id, request.name)
        except ProjectRegistryError as exc:
            raise ConsoleOperationError(exc.code, str(exc)) from exc
        return ProjectEntryResponse(**entry.model_dump())

    async def project_has_inflight_run(self, project_id: str) -> bool:
        return project_id in self._busy

    async def remove_project(self, project_id: str) -> None:
        try:
            self.registry.remove(project_id)
        except ProjectRegistryError as exc:
            raise ConsoleOperationError(exc.code, str(exc)) from exc


class EmbeddedHttpService:
    """默认 CLI **内嵌** HTTP 服务的生命周期（同进程、同一 asyncio 生命周期）。

    与 :func:`_serve_http`（显式 `http-server` 命令「跑到底」的形态）的区别：内嵌服务是**伴随**
    CLI 的——交互模式与 REPL 共存、单次模式与那次 run 并存，CLI 生命周期结束时一起收尾。

    - ``start()``：绑定 + 就绪门禁（失败直接抛，调用方**必须**让命令失败，不得进入「看起来正常
      但没有网页入口」的半启动状态）+ 后台 serve 任务 + stderr 公告；
    - ``close()``：幂等、全程有界（关闭 listener → 等 serve 循环退出，超时则取消）；
    - ``failure``：serve 循环**意外**结束时的异常。交互模式每轮检查它——HTTP 挂掉而 CLI 还在
      正常聊天，等于「页面打不开但看着一切正常」，正是 AD-5 要消除的假可用状态。
    """

    def __init__(self, server: HttpServer) -> None:
        self._server = server
        self._task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None
        self._closed = False

    @property
    def address(self) -> str:
        """实际监听地址（stderr 公告与诊断用）。"""
        return self._server.address

    @property
    def failure(self) -> BaseException | None:
        """serve 循环意外结束时的异常；仍在服务或已被正常关闭时为 ``None``。"""
        return self._failure

    async def start(self) -> None:
        """启动服务并进入后台服务循环；绑定 / 就绪失败时抛错且不留下任务。"""
        await self._server.start()
        self._task = asyncio.create_task(self._server.serve_forever(), name="heagent-http-serve")
        self._task.add_done_callback(self._on_serve_done)
        click.echo(
            f"[http] web UI: http://{self.address}  (local only; no authentication)",
            err=True,
        )

    def _on_serve_done(self, task: asyncio.Task[None]) -> None:
        """serve 循环收尾回调：只有**意外**结束才记 ERROR 并暴露给所有者。"""
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        if self._closed:
            # 关闭期间 serve 循环因 listener 已关闭而报错属正常收尾，不该污染 `failure`。
            _safe_log(logging.WARNING, "HTTP serve loop ended during shutdown: %s", error)
            return
        self._failure = error
        _safe_log(logging.ERROR, "HTTP serve loop stopped unexpectedly: %s", error)

    async def close(self) -> None:
        """停止服务并回收 serve 任务（幂等、有界）。"""
        if self._closed:
            return
        self._closed = True
        await self._server.close()
        task, self._task = self._task, None
        if task is None or task is asyncio.current_task():
            return
        budget = self._server.config.shutdown_timeout + 1.0
        try:
            await asyncio.wait_for(task, timeout=budget)
        except TimeoutError:
            _safe_log(logging.WARNING, "HTTP serve loop did not stop within %.1fs; cancelling", budget)
            task.cancel()
            with contextlib.suppress(Exception):
                await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 已在 done callback 记过 ERROR：此处既不重抛（会掩盖退出原因），也不静默（已记录）。
            _safe_log(logging.WARNING, "HTTP serve loop ended while closing: %s", exc)

    async def __aenter__(self) -> EmbeddedHttpService:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()


def build_http_service(settings: Settings, *, executor: Any | None = None) -> EmbeddedHttpService:
    """按 ``Settings`` 构造默认 CLI 的内嵌 HTTP 服务。

    默认 CLI **不提供** HTTP 相关 CLI 选项（brief：不做含糊的参数透传），因此这里不带覆盖参数——
    绑定地址与限额全部来自 ``HTTP_*`` 设置；需要覆盖时用显式 `heagent http-server`。

    ``executor`` 是运行入口（入口层的 :class:`HttpAgentHandler`）：为 ``None`` 时服务只提供健康检查与
    静态页（Story 49-1 的形态），``/api/runs*`` 与 ``/api/session`` 不注册。
    """
    config = build_server_config(settings)
    run_service = HttpRunService(config, executor) if executor is not None else None
    workspace = WorkspacePaths.from_root(getattr(settings, "workspace_root", None) or os.getcwd())
    console = HttpProjectConsole(workspace.root)
    return EmbeddedHttpService(HttpServer(config, version=_current_version(), run_service=run_service, console=console))


def embedded_http_error_message(exc: BaseException) -> str | None:
    """把内嵌 HTTP 的启动失败转成一行命令级文案；其它异常返回 ``None``（由调用方原样传播）。

    绑定失败与「缺可选依赖」都必须让默认 CLI **显式失败**（story 49-2 AC）：静默降级成「没有网页
    入口但聊天照常」是明确禁止的行为。
    """
    if isinstance(exc, HttpStartupError):
        return f"HTTP server failed to start: {exc}"
    if isinstance(exc, HttpDependencyError):
        return str(exc)
    return None


@click.command("http-server")
@click.option(
    "--host",
    default=None,
    help="Bind address (default: HTTP_HOST / 127.0.0.1). This entry is experimental and unsupported on non-loopback networks.",
)
@click.option(
    "--port",
    type=click.IntRange(min=1, max=65535),
    default=None,
    help="Bind port (default: HTTP_PORT / 8766)",
)
@click.option(
    "--max-connections",
    type=click.IntRange(min=1),
    default=None,
    help="Max simultaneous client connections (default: HTTP_MAX_CONNECTIONS / 16)",
)
@click.option(
    "--max-inflight-runs",
    type=click.IntRange(min=1),
    default=None,
    help="Max concurrent agent runs; extra submissions get run_conflict (default: HTTP_MAX_INFLIGHT_RUNS / 1)",
)
@click.option(
    "--max-request-bytes",
    type=click.IntRange(min=1),
    default=None,
    help="Max size of one JSON request body in bytes (default: HTTP_MAX_REQUEST_BYTES / 65536)",
)
@click.option(
    "--event-buffer-size",
    type=click.IntRange(min=1),
    default=None,
    help="Max buffered SSE events per run (default: HTTP_EVENT_BUFFER_SIZE / 512)",
)
@click.option(
    "--run-history-size",
    type=click.IntRange(min=1),
    default=None,
    help="Max finished run records kept for SSE replay (default: HTTP_RUN_HISTORY_SIZE / 64)",
)
@click.option(
    "--request-timeout",
    type=click.FloatRange(min=0, min_open=True),
    callback=_reject_non_finite,
    default=None,
    help="Seconds allowed per agent run (default: HTTP_REQUEST_TIMEOUT / 300)",
)
@click.option(
    "--shutdown-timeout",
    type=click.FloatRange(min=0, min_open=True),
    callback=_reject_non_finite,
    default=None,
    help="Seconds to drain in-flight work on shutdown (default: HTTP_SHUTDOWN_TIMEOUT / 5)",
)
@click.option("--model", default=None, help="Model name (default: per-provider setting)")
@click.option("--system", default=None, help="System prompt applied to every run")
@click.option("--max-iterations", type=int, default=None, help="Max agent loop iterations per run")
@click.option("--soul", default=None, help="Path to custom SOUL.md personality file")
@click.option(
    "--sandbox",
    type=click.Choice(["auto", "passthrough", "firejail", "winjob"]),
    default=None,
    help="Sandbox backend for shell execution (default: auto = probe firejail)",
)
def http_server_cmd(
    host: str | None,
    port: int | None,
    max_connections: int | None,
    max_inflight_runs: int | None,
    max_request_bytes: int | None,
    event_buffer_size: int | None,
    run_history_size: int | None,
    request_timeout: float | None,
    shutdown_timeout: float | None,
    model: str | None,
    system: str | None,
    max_iterations: int | None,
    soul: str | None,
    sandbox: str | None,
) -> None:
    """Serve the built-in HeAgent web UI over HTTP (experimental; no authentication)."""
    # 函数内导入：``cli`` 在模块尾部 import 本模块注册命令，模块级互相导入会成环。
    from heagent.cli import _prune_runtime_artifacts, _setup_logging  # noqa: PLC0415
    from heagent.roles import load_agent_roles  # noqa: PLC0415

    _setup_logging()
    settings = get_settings()
    _prune_runtime_artifacts(settings)
    # 角色是 system prompt 的组成部分（技能匹配 / 子 Agent 委派都读它），与其它入口一致地加载。
    load_agent_roles()
    provider = _build_provider(settings, model)
    config = build_server_config(
        settings,
        host=host,
        port=port,
        max_connections=max_connections,
        max_inflight_runs=max_inflight_runs,
        max_request_bytes=max_request_bytes,
        event_buffer_size=event_buffer_size,
        run_history_size=run_history_size,
        request_timeout=request_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    handler = HttpAgentHandler(
        provider,
        settings,
        system=system,
        max_iterations=max_iterations,
        sandbox_backend=sandbox,
        soul_path=soul,
    )
    workspace = WorkspacePaths.from_root(os.getcwd())
    console = HttpProjectConsole(workspace.root)
    server = HttpServer(
        config,
        version=_current_version(),
        run_service=HttpRunService(config, handler),
        console=console,
    )
    # 非回环绑定：启动前先向 stderr 打印一次明确告警（无认证 / 无 TLS / 非生产安全边界）。
    # 判定与文案来自 ``network.exposure``——与 ``HttpServer.start()`` 的 ``event=exposed`` 同源。
    warning = exposure_warning(config.host)
    if warning is not None:
        click.echo(f"[http] WARNING: {warning}", err=True)
    try:
        asyncio.run(_serve_http(server))
    except KeyboardInterrupt:
        # Ctrl+C：asyncio.run 先取消主任务、跑完 ``_serve_http`` 的 finally（有界 close），再把
        # KeyboardInterrupt 抛回来。用户主动停止不是错误——安静退出，不打印 traceback。
        click.echo("[http] stopped", err=True)
    except HttpStartupError as exc:
        # 绑定失败 / 就绪探测失败：只给一行可诊断文案，不打印任何「已监听」，也不吐 traceback。
        raise click.ClickException(f"HTTP server failed to start: {exc}") from None
    except HttpDependencyError as exc:
        raise click.ClickException(str(exc)) from None


__all__ = [
    "EmbeddedHttpService",
    "HttpAgentHandler",
    "build_http_service",
    "build_server_config",
    "embedded_http_error_message",
    "http_server_cmd",
]
