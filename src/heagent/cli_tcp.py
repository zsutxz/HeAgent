"""``heagent tcp-server`` 子命令与 Agent 请求适配（入口层组合根）。

Epic 48 Story 48-3。本模块属**入口层**（与 ``cli`` / ``cli_init`` / ``cli_goal`` / ``wiring`` 同级）：
把现有 Provider / Engine / AgentLoop 装配成 :data:`~heagent.network.tcp_server.TcpRequestHandler`，
再交给 ``network`` 层的 :class:`~heagent.network.tcp_server.TcpServer`。边界：

- ``network/`` 不反向依赖本模块（``tests/test_architecture_contracts.py`` 有可执行断言）；
- 本模块不复制 Provider 构造分支——一律经 ``heagent.wiring._build_provider`` 与
  ``heagent.cli._build_loop``（**函数内延迟导入**：``cli`` 在模块尾部 import 本模块注册命令，
  模块级互相导入会成环）；
- 请求体只读取 ``id`` / ``prompt``：system / provider / model / 工具策略 / 沙箱 / 迭代预算
  全部取自**服务端**配置（见 story 48-3 的 Never 列表）。

**每请求一个 ``AgentLoop``（并发决策，有源码依据）**：``AgentLoop`` 实例持有跨 run 的可变展示态
（``last_usage`` / ``last_iteration`` / ``cumulative_tokens`` / ``active_tool`` / ``tool_activity`` /
``last_run_context`` / 暂停 ``Event``）。若共享一个实例并发服务多个请求，A 请求的 ``last_usage``
会被 B 请求覆盖——A 的响应就会带上 B 的 usage/model。故这里**共享 provider / engine / 记忆存储**
（构造便宜、以只读为主），**每请求新建 loop**。连接与在途并发上限属 Story 48-4。

**不装交互式审批处理器**：``cli._prepare_engine`` 在 TTY 下会装 ``ConsoleApprovalHandler``，
它读取**服务进程的 stdin**——网络入口无人应答，一旦挂起就把请求卡死。故这里直接从
``EngineContainer.default`` 构造容器（``approval_handler`` 留 ``None``）：需要审批的工具调用维持
既有 fail-safe 语义（等同阻断），而不是把服务变成交互终端。
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import TYPE_CHECKING, Any

import click

from heagent.config import get_settings
from heagent.engine import EngineContainer
from heagent.exceptions import HeAgentError
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.network.protocol import TcpErrorCode, TcpUsage, error_response, success_response
from heagent.network.tcp_server import TcpServer, TcpServerConfig
from heagent.roles import load_agent_roles
from heagent.wiring import _build_provider

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.config import Settings
    from heagent.memory.soul import SoulStore
    from heagent.network.protocol import TcpRequest, TcpResponse
    from heagent.providers.base import BaseProvider
    from heagent.types import TokenUsage

logger = logging.getLogger(__name__)

# 客户端可见的兜底错误文案：不含异常类型名 / traceback / 路径（协议边界信息最小化）。
_GENERIC_AGENT_ERROR = "agent request failed"
# 单条错误文案上限：``HeAgentError.message`` 是项目自产的面向用户文本（非 traceback），
# 但仍做长度截断，避免超长 Provider 正文原样回吐给客户端。
_MAX_ERROR_MESSAGE_CHARS = 500


def _client_error_message(message: str) -> str:
    """把内部错误文案收敛为单行、有界、非空的客户端文案。"""
    collapsed = " ".join(message.split())
    if not collapsed:
        return _GENERIC_AGENT_ERROR
    if len(collapsed) > _MAX_ERROR_MESSAGE_CHARS:
        return collapsed[:_MAX_ERROR_MESSAGE_CHARS] + "…"
    return collapsed


def _to_tcp_usage(usage: TokenUsage | None) -> TcpUsage | None:
    """把 loop 采集到的用量映射为协议用量；未采集到时不发明数字。"""
    if usage is None:
        return None
    return TcpUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _resolve_model(loop: AgentLoop) -> str | None:
    """本次请求实际使用的模型名。

    只读**本请求 loop** 的运行记录（``last_model``，由 provider 响应回填）；共享 provider 的
    路由状态（``active_model`` → ``RoutingProvider.last_decision``）是实例级「最近一次决策」，
    并发请求下会把兄弟请求的档位串味进本响应——见 ``tests/test_tcp_agent_integration.py``
    的 ``test_concurrent_routed_requests_report_their_own_model``。元数据兜底只用于 provider
    完全没报模型的罕见情形（``RoutingProvider`` 在此返回池内模型汇总串）。
    """
    return loop.last_model or loop.provider.get_metadata().model


def _build_soul(soul_path: str | None) -> SoulStore | None:
    """复用 ``cli._build_soul`` 的路径语义（global/project SOUL.md），不在此重复一份。"""
    from heagent.cli import _build_soul as _cli_build_soul  # noqa: PLC0415 —— 见模块 docstring 的成环说明

    return _cli_build_soul(soul_path)


class TcpAgentHandler:
    """``TcpRequest`` → 一次 ``AgentLoop.run`` 的适配器（网络层只认这个可调用对象）。

    服务级共享：``provider`` / ``engine`` / 四个记忆存储（构造便宜、以只读为主）。
    请求级独占：每次调用 ``new_loop()`` 新建的 ``AgentLoop``（可变展示态不跨请求）。
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
        # 网络入口不装审批处理器（见模块 docstring）：需要审批的调用按既有 fail-safe 语义阻断。
        self.engine = engine or EngineContainer.default(workspace_root=os.getcwd(), sandbox_backend=sandbox_backend)
        self.skills = SkillStore()
        self.facts = FactStore()
        self.profile = ProfileStore()
        self.soul = _build_soul(soul_path)

    def new_loop(self) -> AgentLoop:
        """按服务级共享组件构造一个请求级 ``AgentLoop``。

        ``session=None``：TCP 请求是**无状态单请求单响应**，不复用会话文件（也就不创建 cron 调度器）。
        """
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

    async def __call__(self, request: TcpRequest) -> TcpResponse:
        """执行一次 Agent 运行并映射为协议响应；``CancelledError`` 原样传播（不是业务失败）。"""
        loop = self.new_loop()
        try:
            result = await loop.run(request.prompt, system=self.system)
        except asyncio.CancelledError:
            # 服务关闭 / 请求超时的取消：保持取消语义，绝不包装成 agent_error（48-2/48-4 依赖）。
            raise
        except HeAgentError as exc:
            # 已知框架异常（含 BudgetExceeded / ProviderError）：由协议层给出稳定 agent_error，
            # message 是项目自产的面向用户文本（不含 traceback / 异常类名）。
            logger.warning("TCP agent run failed (request_id=%s): %s", request.id, exc.message)
            return error_response(request.id, TcpErrorCode.AGENT_ERROR, _client_error_message(exc.message))
        except Exception:
            # 未知异常：只记服务端日志，客户端拿固定文案（不泄漏类型名 / 路径 / traceback）。
            logger.exception("TCP agent run failed (request_id=%s)", request.id)
            return error_response(request.id, TcpErrorCode.AGENT_ERROR, _GENERIC_AGENT_ERROR)
        return success_response(
            request.id,
            result,
            model=_resolve_model(loop),
            usage=_to_tcp_usage(loop.last_usage),
        )


def build_server_config(
    settings: Settings,
    *,
    host: str | None = None,
    port: int | None = None,
    max_connections: int | None = None,
    max_inflight: int | None = None,
    max_request_bytes: int | None = None,
    idle_timeout: float | None = None,
    request_timeout: float | None = None,
    shutdown_timeout: float | None = None,
) -> TcpServerConfig:
    """把 CLI 覆盖（``None`` = 未覆盖）合并到 ``Settings`` 的 TCP 配置。

    两个不变量：

    - **不写回 Settings**：覆盖只作用于本次服务实例，设置单例保持 env / 文件默认值。
    - **范围规则唯一**：CLI 侧先用 ``click`` 的 range 类型拦一道，最终仍由
      :class:`TcpServerConfig`（Pydantic）统一校验——避免 CLI 与 env 两套规则漂移
      （端口 1..65535、计数 >=1、超时 >0 在两侧同义）。
    """
    return TcpServerConfig(
        host=settings.tcp_host if host is None else host,
        port=settings.tcp_port if port is None else port,
        max_connections=settings.tcp_max_connections if max_connections is None else max_connections,
        max_inflight_requests=settings.tcp_max_inflight_requests if max_inflight is None else max_inflight,
        max_request_bytes=settings.tcp_max_request_bytes if max_request_bytes is None else max_request_bytes,
        idle_timeout=settings.tcp_idle_timeout if idle_timeout is None else idle_timeout,
        request_timeout=settings.tcp_request_timeout if request_timeout is None else request_timeout,
        shutdown_timeout=settings.tcp_shutdown_timeout if shutdown_timeout is None else shutdown_timeout,
    )


def _reject_non_finite(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    """拒绝 ``NaN`` / ``Inf`` 超时值（``click.FloatRange`` 本身会放行它们）。

    不拦的后果：``Inf`` 让「超时」静默变成无限制（关闭等待因此无界），``NaN`` 会绕过范围比较、
    直到 Pydantic 校验才以 traceback 形式炸掉——与其它非法值（usage error + exit 2）不一致。
    """
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("must be a finite number", ctx=ctx, param=param)
    return value


def _listen_address(server: TcpServer) -> str:
    """实际监听地址：只有 ``TcpServerConfig(port=0)``（程序化/测试用法）时读 socket 才有意义。"""
    sockets: tuple[Any, ...] = server.sockets
    if not sockets:
        return f"{server.config.host}:{server.config.port}"
    sockname = sockets[0].getsockname()
    return f"{sockname[0]}:{sockname[1]}"


async def _serve_tcp(server: TcpServer) -> None:
    """启动 server 并运行到取消 / 关闭。

    启动消息只走 stderr / 日志（TCP 通道只承载协议响应）；退出路径必须关闭监听与在途连接，
    否则 Ctrl+C / 服务取消会留下悬挂的 writer 与 request task（48-2 的 ``close()`` 语义）。
    """
    await server.start()
    click.echo(f"[tcp] listening on {_listen_address(server)} (UTF-8 JSON Lines; one request per connection)", err=True)
    try:
        await server.serve_forever()
    finally:
        await server.close()


@click.command("tcp-server")
@click.option(
    "--host",
    default=None,
    help="Bind address (default: TCP_HOST / 127.0.0.1). This experimental entry is unsupported on non-loopback networks.",
)
@click.option(
    "--port",
    type=click.IntRange(min=1, max=65535),
    default=None,
    help="Bind port (default: TCP_PORT / 8765)",
)
@click.option(
    "--max-connections",
    type=click.IntRange(min=1),
    default=None,
    help="Max simultaneous client connections (default: TCP_MAX_CONNECTIONS / 32)",
)
@click.option(
    "--max-inflight",
    type=click.IntRange(min=1),
    default=None,
    help="Max concurrent agent runs; extra requests get rate_limited (default: TCP_MAX_INFLIGHT_REQUESTS / 4)",
)
@click.option(
    "--max-request-bytes",
    type=click.IntRange(min=1),
    default=None,
    help="Max size of one request line in bytes (default: TCP_MAX_REQUEST_BYTES / 1048576)",
)
@click.option(
    "--idle-timeout",
    type=click.FloatRange(min=0, min_open=True),
    callback=_reject_non_finite,
    default=None,
    help="Seconds to wait for a complete request line (default: TCP_IDLE_TIMEOUT / 60)",
)
@click.option(
    "--request-timeout",
    type=click.FloatRange(min=0, min_open=True),
    callback=_reject_non_finite,
    default=None,
    help="Seconds allowed per agent run (default: TCP_REQUEST_TIMEOUT / 300)",
)
@click.option(
    "--shutdown-timeout",
    type=click.FloatRange(min=0, min_open=True),
    callback=_reject_non_finite,
    default=None,
    help="Seconds to drain in-flight work on shutdown (default: TCP_SHUTDOWN_TIMEOUT / 5)",
)
@click.option("--model", default=None, help="Model name (default: per-provider setting)")
@click.option("--system", default=None, help="System prompt applied to every request")
@click.option("--max-iterations", type=int, default=None, help="Max agent loop iterations per request")
@click.option("--soul", default=None, help="Path to custom SOUL.md personality file")
@click.option(
    "--sandbox",
    type=click.Choice(["auto", "passthrough", "firejail", "winjob"]),
    default=None,
    help="Sandbox backend for shell execution (default: auto = probe firejail)",
)
def tcp_server_cmd(
    host: str | None,
    port: int | None,
    max_connections: int | None,
    max_inflight: int | None,
    max_request_bytes: int | None,
    idle_timeout: float | None,
    request_timeout: float | None,
    shutdown_timeout: float | None,
    model: str | None,
    system: str | None,
    max_iterations: int | None,
    soul: str | None,
    sandbox: str | None,
) -> None:
    """Serve HeAgent over TCP with UTF-8 JSON Lines (experimental; no authentication)."""
    from heagent.cli import _prune_runtime_artifacts, _setup_logging  # noqa: PLC0415

    _setup_logging()
    settings = get_settings()
    _prune_runtime_artifacts(settings)
    load_agent_roles()
    provider = _build_provider(settings, model)
    handler = TcpAgentHandler(
        provider,
        settings,
        system=system,
        max_iterations=max_iterations,
        sandbox_backend=sandbox,
        soul_path=soul,
    )
    config = build_server_config(
        settings,
        host=host,
        port=port,
        max_connections=max_connections,
        max_inflight=max_inflight,
        max_request_bytes=max_request_bytes,
        idle_timeout=idle_timeout,
        request_timeout=request_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    server = TcpServer(config, handler)
    try:
        # 绑定失败（端口占用 / 地址不可用）显式失败：只给一行可诊断文案，不打印任何「已监听」，
        # 也不吐 traceback（story 48-2 的启动语义 + CLI 的 UX 约定）。
        asyncio.run(_serve_tcp(server))
    except OSError as exc:
        raise click.ClickException(f"TCP server failed to start: {exc}") from None


__all__ = ["TcpAgentHandler", "build_server_config", "tcp_server_cmd"]
