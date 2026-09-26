"""网页控制台的项目/会话/配置面（入口层实现，网络层只认注入的协议端口）。

**为什么单独成模块**（`heagent/cli/` 包内拆分，2026-09-26）：``HttpProjectConsole``（项目注册表
读写、会话投影、配置来源求解与写入闸门）与它的私有件合计约 450 行，与「HTTP 传输与生命周期」
（``cli/http.py``：listener、静态资源、安全响应头、SSE 与命令装配）只共享 ``logger`` /
``_safe_log`` / 协议模型。

**与 ``cli/http.py`` 的关系**：单向 ``http.py → http_console.py``（装配侧导入实现类）；本模块
**不**反向导入 ``cli/http.py``（否则与命令装配成环）。

**缝纪律**：本模块没有测试 patch 点（`HttpProjectConsole` / `HttpAgentHandler` 是**被导入实例化**
的类，patch 用的是它们的方法或注入的替身）；``_build_soul`` 的函数内导入指向
``heagent.cli.composition``（真源）。

分层：本模块属**入口层**，不被下层反向导入。
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import uuid
from collections.abc import Callable
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

import click

from heagent.cli.dialogs import DialogBusyError, DialogUnavailableError, DirectoryPicker
from heagent.config import GLOBAL_CONFIG_FILE, Settings
from heagent.config.catalog import LABELS, ConfigItem, ConfigReport, build_config_report
from heagent.config.write import ConfigChange, ConfigWriteRejection, ConfigWriteResult, apply_config_write
from heagent.context.session import SessionMetadata, SessionStore
from heagent.engine import EngineContainer
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore
from heagent.network.http_console_protocol import (
    MAX_SESSION_MESSAGES_IN_RESPONSE,
    ConfigGroupResponse,
    ConfigItemResponse,
    ConfigWriteRequest,
    ConfigWriteResponse,
    ConsoleOperationError,
    DirectoryPickResponse,
    EnvFileStatusResponse,
    ProjectConfigResponse,
    ProjectEntryResponse,
    ProjectListResponse,
    ProjectRegisterRequest,
    ProjectRenameRequest,
    ProjectRunRequest,
    ProjectRunResponse,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionEntryResponse,
    SessionListResponse,
    SessionRenameRequest,
    UnknownKeyResponse,
    is_valid_session_id,
)
from heagent.network.http_protocol import HttpErrorCode, HttpUsage, RunOutcome, RunStatus, SessionMessage
from heagent.network.http_server import (
    HttpRunConflictError,
    HttpRunService,
    RunEventPublisher,
)
from heagent.pub.exceptions import SessionConflictError, SessionNotFoundError, SessionUnreadableError
from heagent.pub.projects import ProjectEntry, ProjectRegistryError, default_project_registry
from heagent.pub.safe_logging import safe_log
from heagent.pub.types import Message, Role
from heagent.pub.workspace import WorkspacePaths

if TYPE_CHECKING:
    from heagent.agent.loop import AgentLoop
    from heagent.providers.base import BaseProvider
    from heagent.pub.types import TokenUsage

logger = logging.getLogger(__name__)


def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """记一条日志，**绝不让观测故障影响生命周期行为**（绑定**本模块** logger，故与 http.py 各留一份）。"""
    safe_log(logger, level, message, *args, exc_info=exc_info)


# 项目运行入口的工厂：给定项目路径派生结果与会话存储，返回该项目专属的运行入口。
# 网络层只看到不透明项目 id；项目根 → 运行时的解析全部留在入口层（脊柱 I1）。
ProjectHandlerFactory = Callable[[WorkspacePaths, SessionStore], "HttpAgentHandler"]


def _build_soul(soul_path: str | None) -> Any:
    """复用 ``cli._build_soul`` 的路径语义（global/project SOUL.md），不在此重复一份。"""
    from heagent.cli.composition import _build_soul as _cli_build_soul  # noqa: PLC0415 —— 见模块 docstring 的成环说明

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
    兄弟请求的档位串味（与 ``cli.tcp._resolve_model`` 同一立场）。
    """
    return loop.last_model or loop.provider.get_metadata().model


#: **网页展示策略**（Story 50-8 R5，非安全边界、也不改变任何有界口径）：这些工具的**成功**结果内容
#: 不进网页事件流——``file_read`` 会把整份文件正文灌进对话区，而网页只需要「读了哪个文件」。
#: 三条范围约束：
#:
#: - **只影响网页**：会话文件、``rollout.jsonl``、CLI、GUI 一律保留全文（审计与回放不受影响）；
#: - **失败结果不收敛**：错误消息是诊断必需，原样回传（``tool_error=True`` 时走原内容）；
#: - **作用对象照旧**：文件名/路径仍由 ``tool_call`` 事件的 ``tool_target`` 提供（网页结果行复用
#:   同一 ``tool_target``），这里只是不放**内容**。
_WEB_QUIET_TOOLS: frozenset[str] = frozenset({"file_read"})

#: 内置工具的**可预期失败约定**：失败以返回值 ``Error: ...`` 表达（不是异常）⇒ 执行器的 ``is_error``
#: 仍为 ``False``（见 ``tools/builtins/*`` 与 ``engine/executor.py`` 的异常约定）。网页收敛必须让这些
#: 消息照旧可见，否则「文件不存在 / 路径越界」这类诊断会从页面上消失——那是展示层的**退化**，不是精简。
_FAILURE_PREFIX = "Error:"


def _looks_like_a_failure(content: str) -> bool:
    """内容是「工具自己报的失败」吗（**展示层判据，非安全边界**）。"""
    return content.lstrip().startswith(_FAILURE_PREFIX)


def _web_tool_output(event: Any) -> str:
    """按 :data:`_WEB_QUIET_TOOLS` 决定进网页的工具结果内容（见该常量的范围说明）。"""
    content = str(event.tool_result_content)
    if event.tool_name in _WEB_QUIET_TOOLS and not event.tool_error and not _looks_like_a_failure(content):
        return ""
    return content


class HttpAgentHandler:
    """``prompt`` → 一次 ``AgentLoop.run_stream`` 的适配器（网络层只认这个可调用对象）。

    与 :class:`~heagent.cli.tcp.TcpAgentHandler` 同构——服务级共享 ``provider`` / ``engine`` /
    四个记忆存储（构造便宜、以只读为主），**每次运行新建 ``AgentLoop``**（loop 持有跨 run 可变展示态：
    ``last_usage`` / ``last_model`` / ``active_tool`` / 暂停 Event，共享单实例并发会互相覆盖）。

    **独立引擎，不装审批处理器**：HTTP handler 自建 ``EngineContainer``（``approval_handler=None``），
    因此需要审批的工具调用维持既有 fail-safe 阻断语义，而**不会**去读 CLI / 服务进程的 stdin——
    网络入口无人应答，装了只会把请求挂死（与 ``cli/tcp`` 同一决策）。代价是网页侧与 CLI 终端各有一份
    引擎与事件总线（记忆存储同样各自一份），互不干扰。

    **不连接 MCP**：``.mcp.json`` 声明的 server 属不可信代码 / 端点，网络入口自动连接等于把触达面
    暴露给任何能连上端口的人；需要 MCP 请在可控的交互式会话里显式启用。

    **单项目运行时（Story 50-3）**：自本 story 起本对象是**一个项目**的运行入口——工作区根由形参
    显式给出（缺省回落到注入引擎 / 进程 cwd，Epic 49 语义不变），并持有该项目的 ``SessionStore``
    与 ``WorkspacePaths``；控制台为别的项目派生同款实例（:meth:`for_workspace`），跨项目零共享
    可变状态。因此「一个 ``HttpAgentHandler`` = 一个项目根」是新的不变量，不要再把它当作全局单例。
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
        workspace_root: str | Path | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.system = system
        self.max_iterations = max_iterations
        self.sandbox_backend = sandbox_backend
        self._soul_path = soul_path
        # 工作区根的三级取值：显式形参 → 注入引擎（测试）→ 进程 cwd（Epic 49 的既有兜底）。
        # 网络入口不装审批处理器（见类 docstring）；engine 可注入（测试）但默认自建。
        paths = WorkspacePaths.from_root(workspace_root or (engine.workspace_root if engine else None) or os.getcwd())
        self.paths = paths
        self.engine = engine or EngineContainer.default(
            workspace_root=str(paths.root), sandbox_backend=sandbox_backend, settings=settings
        )
        # 运行时**传入**会话存储（Story 50-3）：为 ``None`` 时本运行时没有会话，行为与 Epic 49 一致；
        # 控制台侧传入时，会话文件落在该项目的 ``paths.sessions``。
        self.session_store = session_store
        self.skills = SkillStore(str(paths.skills))
        self.facts = FactStore(str(paths.memory_file))
        self.profile = ProfileStore(str(paths.profile_file))
        self.soul = _build_soul(soul_path)

    def for_workspace(self, paths: WorkspacePaths, session_store: SessionStore) -> HttpAgentHandler:
        """派生一个绑定到**另一个项目根**的同款运行时（控制台的 per-project 工厂，Story 50-3）。

        - **共享** ``provider`` / ``system``：它们是连接参数（provider 上的路由状态是「最近一次决策」，
          不写入项目）。
        - **按项目解析** ``settings``（脊柱 §7）：显式 ``_env_file=[全局, <项目根>/.env]``——项目
          ``.env`` 才是「该项目的配置」，绝不能让运行端继续读**服务器 cwd** 的 ``.env``（那会让
          50-4 的配置面板报出与运行期不符的来源与取值）。解析失败时回退服务级 settings 并留
          WARNING（坏掉的 ``项目 .env`` 不该让控制台整个不可用，面板会独立标注 ``project_env_invalid``）。
        - **重建** engine 与四个记忆存储：围栏基址、run/ledger 落点、技能与记忆全都指向该项目根，
          跨项目因此零共享可变状态（脊柱 §6）。
        - ``soul`` 沿用同一构造口径（``soul_path=None`` ⇒ 默认两级 SOUL.md）：项目级 SOUL.md 的解析
          语义与 Epic 49 完全一致，本 story 不改变它。
        """
        return HttpAgentHandler(
            self.provider,
            _project_settings(paths.root, fallback=self.settings),
            system=self.system,
            max_iterations=self.max_iterations,
            sandbox_backend=self.sandbox_backend,
            soul_path=self._soul_path,
            workspace_root=str(paths.root),
            session_store=session_store,
        )

    def new_loop(self) -> AgentLoop:
        """按服务级共享组件构造一个请求级 ``AgentLoop``。

        Story 50-3：``session=self.session_store`` 让运行把对话写进该项目的
        ``.heagent/sessions/{session_id}.json``（此前是 ``session=None``，这正是网页不落盘的根因）；
        ``session`` 为 ``None`` 时行为与 Epic 49 逐字相同。

        ``enable_cron=False`` 是**显式**拒绝，不是副作用：``_build_loop`` 的调度器分支含
        ``session is not None`` 条件，传入会话后「HTTP 侧没有后台调度」再也不能靠 ``session=None``
        偶然成立（评审 F2）。返回值里若真出现调度器，本方法**显式失败**——把带无人监督执行面的
        运行时装进 HTTP 进程是 49-5 明令禁止的形态，绝不静默忽略。
        """
        from heagent.cli.composition import _build_loop  # noqa: PLC0415 —— patch 缝落在此模块（见其 docstring）

        loop, scheduler = _build_loop(
            self.settings,
            self.provider,
            self.max_iterations or self.settings.max_iterations,
            None,
            session=self.session_store,
            engine=self.engine,
            sandbox_backend=self.sandbox_backend,
            skills=self.skills,
            facts=self.facts,
            profile=self.profile,
            soul=self.soul,
            enable_cron=False,
        )
        if scheduler is not None:
            raise RuntimeError("HTTP runtime must not own a CronScheduler")
        return loop

    async def __call__(
        self,
        prompt: str,
        publisher: RunEventPublisher,
        *,
        session_id: str | None = None,
    ) -> RunOutcome:
        """跑一次流式运行并把 ``StreamEvent`` 映射为协议事件。

        ``session_id`` 由控制台按项目 / 会话绑定后传入（缺省 ``None`` = 不落会话，Epic 49 行为）。

        ``CancelledError`` 原样传播（是取消，不是业务失败）；其它异常也原样抛出——由服务层统一
        收敛成脱敏的终态事件（``_client_error_message``）。答案与用量只从**这次运行**取。
        """
        loop = self.new_loop()
        answer = ""
        async for event in loop.run_stream(prompt, system=self.system, session_id=session_id):
            if event.type == "text":
                publisher.text(event.text)
            elif event.type == "tool_call":
                publisher.tool_call(event.tool_name, event.tool_target)
            elif event.type == "tool_result":
                publisher.tool_result(event.tool_name, _web_tool_output(event), is_error=event.tool_error)
            elif event.type == "done":
                answer = event.final_answer
        return RunOutcome(
            answer=answer,
            model=_resolve_model(loop),
            usage=_to_http_usage(loop.last_usage),
        )


def _project_settings(root: Path, *, fallback: Settings) -> Settings:
    """按**项目工作区**解析 ``Settings``（脊柱 §7：必须显式传 ``_env_file``）。

    相对 ``.env`` 会按**进程 cwd** 解析（``Settings.model_config`` 的 ``env_file`` 就是
    ``[全局, ".env"]``），多项目下「项目的配置」会静默退化成服务器 cwd 的配置——这正是配置面板与
    运行期口径分叉的根因。解析失败（值非法 / 编码不可解析）时回退服务级 settings 并留 WARNING：
    坏掉的项目 ``.env`` 只该影响它自己（面板会标注 ``project_env_invalid``），不该让控制台不可用。
    """
    try:
        # ``_env_file`` 是 pydantic-settings 的运行时参数（mypy 按字段合成的签名看不到它）。
        return Settings(_env_file=[str(GLOBAL_CONFIG_FILE), str(root / ".env")])  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001 - 降级而非带崩：项目配置坏了不该让控制台整体失败
        _safe_log(logging.WARNING, "Project %s .env is unusable; using server settings: %s", root, exc)
        return fallback


def _config_item_response(item: ConfigItem) -> ConfigItemResponse:
    """域模型（``config_catalog``）→ 协议模型（网络层）的单条映射（叶子模型按字段名镜像）。"""
    return ConfigItemResponse.model_validate(item.model_dump(mode="json"))


def _config_response(project_id: str, report: ConfigReport, *, write_enabled: bool) -> ProjectConfigResponse:
    """域模型（``config_catalog``）→ 协议模型（网络层）。

    两类模型各自归属一层（``config_catalog`` 是顶层模块，不得 import 网络层），因此这里按字段名
    做一次**显式**映射；叶子模型用 ``model_validate(model_dump(mode="json"))`` 镜像，两侧字段一旦
    漂移就会立刻失败（``extra="forbid"``），并由契约测试钉住。

    ``write_enabled`` 由调用方（持有写闸门的入口层）**显式**传入，**没有默认值**：闸门状态一旦漏传，
    面板就会把「可写」谎报成「只读」（或反之），故让它在构造期就失败，而不是给一个可能撒谎的兜底值。
    """
    return ProjectConfigResponse(
        project_id=project_id,
        field_count=report.field_count,
        write_enabled=write_enabled,
        groups=tuple(
            ConfigGroupResponse(
                id=group.id,
                label=group.label,
                items=tuple(_config_item_response(item) for item in group.items),
            )
            for group in report.groups
        ),
        env_file=EnvFileStatusResponse.model_validate(report.env_file.model_dump(mode="json")),
        unknown_keys=tuple(
            UnknownKeyResponse.model_validate(item.model_dump(mode="json")) for item in report.unknown_keys
        ),
        labels=dict(report.labels),
        notes=report.notes,
    )


def _guarded_session_id(session_id: str) -> str:
    """入口层的**第二道**会话 id 校验（网络层已挡一次）：非法即稳定错误，且不触碰文件系统。

    两道各自 fail-closed：传输层拥有「不认识的 id 不进路由」的保证，入口层拥有「即便被直接调用
    （测试 / 未来的其它传输）也不越界」的保证。
    """
    if not is_valid_session_id(session_id):
        raise ConsoleOperationError(HttpErrorCode.INVALID_SESSION_ID, "session id is invalid")
    return session_id


def _project_messages(messages: list[Message]) -> tuple[list[SessionMessage], bool]:
    """把会话文件的消息投影成可展示历史（与 ``/api/session`` 同构：只有 user / assistant 文本）。

    工具调用、工具结果与系统提示不进展示面——它们仍完整保存在会话文件里（文件是唯一权威）。
    超过响应上限时只回**最后** N 条并把 ``truncated`` 置真（显式标注，绝不静默截断）。
    """
    projected: list[SessionMessage] = []
    for message in messages:
        if message.role is Role.USER:
            projected.append(SessionMessage(role="user", text=message.content))
        elif message.role is Role.ASSISTANT and message.content.strip():
            projected.append(SessionMessage(role="assistant", text=message.content))
    truncated = len(projected) > MAX_SESSION_MESSAGES_IN_RESPONSE
    return projected[-MAX_SESSION_MESSAGES_IN_RESPONSE:], truncated


def _session_entry(meta: SessionMetadata) -> SessionEntryResponse:
    return SessionEntryResponse(
        session_id=meta.session_id,
        title=meta.title,
        message_count=meta.message_count,
        version=meta.version,
        updated_at=meta.updated_at,
        unreadable=meta.unreadable,
    )


class _ProjectRuntime:
    """一个项目的运行时切片：路径派生 + 会话存储 + （可选）运行入口。

    按 ``project_id`` 缓存。**条目数天然有界**——项目注册表本身有条目上限（``MAX_PROJECTS`` = 32）
    加上隐式 default，已移除项目的条目也只是留一个扁平小对象，不需要额外淘汰规则（NFR-11）。

    ``executor`` 为 ``None`` 表示本服务没有该项目的运行入口（默认 CLI 在 ``executor=None`` 时连
    ``HttpRunService`` 都不建）：**会话 API 仍然可用**（只读文件），只有项目内运行回
    ``project_unavailable``。
    """

    __slots__ = ("executor", "paths", "root", "sessions")

    def __init__(
        self,
        *,
        root: Path,
        paths: WorkspacePaths,
        sessions: SessionStore,
        executor: HttpAgentHandler | None,
    ) -> None:
        self.root = root
        self.paths = paths
        self.sessions = sessions
        self.executor = executor


class HttpProjectConsole:
    """Entry-layer adapter that exposes the workspace project registry to HTTP.

    Story 50-3 起它同时是**会话面与项目内运行**的入口层实现：项目 id → 该项目运行时（路径派生 /
    ``SessionStore`` / 运行入口）的解析全部在这里单点完成，网络层只看到不透明 id 与 Pydantic 模型
    （脊柱 I1）。会话 JSON 的解析一律留在 ``SessionStore``（脊柱「Never」项）。

    Story 50-5 起它还是**配置写入**的入口层实现：10 步流水线的同步内核在
    :func:`heagent.config.write.apply_config_write`（顶层模块），这里负责三件事——提供项目 ``.env``
    的绝对路径（脊柱 I2）、持有**服务启动时**解析的写闸门（D4：开关只能由启动配置决定，网页任何
    请求都改不到它自己）、以及写成功后的**生效语义**（I10：让该项目的运行时缓存失效，下一次 run
    重新解析；在途 run 持有的旧快照不受影响）。
    """

    def __init__(
        self,
        workspace: Path,
        *,
        projects_file: str | None = None,
        runs: HttpRunService | None = None,
        handler_factory: ProjectHandlerFactory | None = None,
        write_enabled: bool = False,
        global_env_file: str | Path | None = GLOBAL_CONFIG_FILE,
        dialog_backend: str = "auto",
    ) -> None:
        self.registry = default_project_registry(workspace, projects_file)
        self.workspace = workspace
        # 运行服务是**注入**的（AD-1 接缝）：在途判定与「会话最近一次运行状态」都取自它，
        # 控制台因此不持有第二份会过期的索引（评审 R2/R4）。
        self._runs = runs
        self._handler_factory = handler_factory
        self._runtimes: dict[str, _ProjectRuntime] = {}
        # 写闸门与「全局 .env 层」路径是**服务级**事实（按启动配置解析一次），不是项目级：写入通道
        # 的每一层判定都必须与面板 / 运行期同源，否则会出现「面板说可写、写下去不生效」。
        self.write_enabled = write_enabled
        self.global_env_file = Path(global_env_file).expanduser() if global_env_file is not None else None
        # 原生目录选择（Story 50-8）：后端口径来自**启动配置**（`--dialog-backend`），单在途由入口层持有。
        # 它会拉起宿主进程（弹窗），因此只服务「登记项目」这条链路；返回值不是权限——拿到路径后仍要过
        # ``registry.register`` 的存在性 / 目录性 / 规范化 / 去重 / 上限全套校验。
        self._picker = DirectoryPicker(dialog_backend)
        # 每个项目的**配置代**：写成功后自增（UI 与测试用它观测「下一次运行生效」，I10）。
        self._config_generations: dict[str, int] = {}
        if write_enabled:
            # D4：开关一旦打开就必须**在启动时**说清楚代价（stderr + 日志），不能只写在文档里。
            _safe_log(
                logging.WARNING,
                "Config write channel enabled (HTTP_CONSOLE_WRITE_ENABLED): anyone who can reach this "
                "port can modify the project .env. This entry has no authentication and is not a "
                "security boundary.",
            )
            click.echo(
                "[http] WARNING: config write channel is ENABLED — anyone who can reach this port can "
                "modify the project .env (no authentication, not a security boundary)",
                err=True,
            )

    # ── 项目（Story 50-2） ──

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
        """该项目是否有在途运行（50-2 的 ``project_busy`` 闸门）。

        事实单点取自注入的运行服务：``run → project`` 的归属在建立运行时写进运行记录，故无需
        控制台再维护一份索引（评审 R2）。
        """
        return self._runs is not None and self._runs.has_inflight_run(project_id=project_id)

    async def remove_project(self, project_id: str) -> None:
        try:
            self.registry.remove(project_id)
        except ProjectRegistryError as exc:
            raise ConsoleOperationError(exc.code, str(exc)) from exc
        self._runtimes.pop(project_id, None)

    # ── 会话与项目内运行（Story 50-3） ──

    async def list_sessions(self, project_id: str) -> SessionListResponse:
        """该项目的会话列表（时间降序）。损坏文件也列出（``unreadable=true``），不静默消失。"""
        runtime = self._runtime_for(project_id)
        return SessionListResponse(sessions=[_session_entry(item) for item in runtime.sessions.list_metadata()])

    async def create_session(self, project_id: str, request: SessionCreateRequest) -> SessionEntryResponse:
        """新建空会话。断言「绝不复用已有 id」（uuid4），也就不会覆盖既有对话。"""
        runtime = self._runtime_for(project_id)
        session_id = uuid.uuid4().hex
        try:
            meta = runtime.sessions.create(session_id, title=request.title)
        except ValueError as exc:  # 标题边界（协议层已挡一次）——入口层 fail-closed，不落半成品
            raise ConsoleOperationError(HttpErrorCode.INVALID_REQUEST, "session title is invalid") from exc
        except SessionConflictError as exc:
            # 评审发现·镜头一⑩：``SessionConflictError`` 不是 ``ValueError``，漏捕会退化成不透明 500。
            raise ConsoleOperationError(HttpErrorCode.SESSION_CONFLICT, str(exc)) from exc
        return _session_entry(meta)

    async def get_session(self, project_id: str, session_id: str) -> SessionDetailResponse:
        """读单个会话：**会话文件是唯一权威**的对话历史，``run_id``/``status`` 如实报告最近一次运行。

        失败 / 取消的运行也已写进文件（``persist_and_cache`` 在 ``finally`` 里保存），因此状态字段
        与可见消息自洽：界面按「已完成 / 失败」标注，不会出现「历史里有、状态说没有」的矛盾
        （T9b / AC10）。
        """
        runtime = self._runtime_for(project_id)
        sid = _guarded_session_id(session_id)
        store = runtime.sessions
        try:
            meta = store.load_metadata(sid)
        except SessionUnreadableError as exc:
            raise ConsoleOperationError(HttpErrorCode.SESSION_UNREADABLE, "session file cannot be parsed") from exc
        if meta is None:
            raise ConsoleOperationError(HttpErrorCode.UNKNOWN_SESSION, f"no session {sid!r}")
        messages, truncated = _project_messages(store.load(sid))
        run_id, status = self._run_state(project_id, sid)
        return SessionDetailResponse(
            session_id=sid,
            title=meta.title,
            version=meta.version,
            messages=messages,
            messages_truncated=truncated,
            run_id=run_id,
            status=status,
        )

    async def rename_session(
        self, project_id: str, session_id: str, request: SessionRenameRequest
    ) -> SessionEntryResponse:
        """就地改标题（不动 ``messages``）；``fingerprint`` 不符即 ``session_conflict``（不写文件）。"""
        runtime = self._runtime_for(project_id)
        sid = _guarded_session_id(session_id)
        try:
            meta = runtime.sessions.rename(sid, request.title, expected_version=request.fingerprint)
        except SessionNotFoundError as exc:
            raise ConsoleOperationError(HttpErrorCode.UNKNOWN_SESSION, f"no session {sid!r}") from exc
        except SessionUnreadableError as exc:
            raise ConsoleOperationError(HttpErrorCode.SESSION_UNREADABLE, "session file cannot be parsed") from exc
        except SessionConflictError as exc:
            raise ConsoleOperationError(HttpErrorCode.SESSION_CONFLICT, str(exc)) from exc
        return _session_entry(meta)

    async def delete_session(self, project_id: str, session_id: str) -> None:
        """删除会话文件。在途运行写入期间拒绝（``session_busy``），否则运行收尾会把它写回来。"""
        runtime = self._runtime_for(project_id)
        sid = _guarded_session_id(session_id)
        if self._runs is not None and self._runs.has_inflight_run(project_id=project_id, session_id=sid):
            raise ConsoleOperationError(HttpErrorCode.SESSION_BUSY, "session is in use by an in-flight run")
        if not runtime.sessions.delete(sid):
            raise ConsoleOperationError(HttpErrorCode.UNKNOWN_SESSION, f"no session {sid!r}")

    async def start_project_run(self, project_id: str, request: ProjectRunRequest) -> ProjectRunResponse:
        """在项目内创建一次运行；``run_id`` 复用既有 SSE / 取消端点（``/api/runs/{run_id}/…``）。"""
        runtime = self._runtime_for(project_id)
        if self._runs is None or runtime.executor is None:
            raise ConsoleOperationError(
                HttpErrorCode.PROJECT_UNAVAILABLE, "this server has no run entry for the project"
            )
        session_id = self._resolve_session(runtime, request.session_id)
        executor = functools.partial(runtime.executor, session_id=session_id)
        try:
            record = await self._runs.start_run(
                request.prompt,
                executor=executor,
                project_id=project_id,
                session_id=session_id,
            )
        except HttpRunConflictError as exc:
            raise ConsoleOperationError(HttpErrorCode.RUN_CONFLICT, str(exc)) from exc
        self._touch(project_id)
        return ProjectRunResponse(run_id=record.run_id, session_id=session_id, status=record.status)

    # ── 配置可见性（Story 50-4） ──

    async def get_project_config(self, project_id: str) -> ProjectConfigResponse:
        """该项目的**有效**配置：值 + 来源 + 可写性 + 只读原因 + 诊断（只读；凭证仅掩码）。

        求解完全交给 :func:`heagent.config.catalog.build_config_report`（单一求解器，NFR-3）；
        这里只做两件事：解析项目运行时（拿 ``<项目根>/.env`` 的绝对路径，脊柱 I2）与把域模型
        映射成网络层协议模型。
        """
        runtime = self._runtime_for(project_id)
        return _config_response(
            project_id,
            build_config_report(runtime.paths.env_file, global_env_file=self.global_env_file),
            write_enabled=self.write_enabled,
        )

    # ── 配置写入（Story 50-5） ──

    async def update_project_config(self, project_id: str, request: ConfigWriteRequest) -> ConfigWriteResponse:
        """执行配置写入流水线：闸门 → 项目 → 10 步（顶层模块）→ 生效语义（I10）。

        三处顺序/归属有意如此：

        - **闸门先于项目解析**：开关关着时连「该项目是否存在」都不回答（不把项目登记表变成未授权
          的信息探测面）；
        - **回环来源判定在传输层**（流水线第 2 步）——非回环请求根本到不了这里，因此也不会有任何
          副作用（AC10）；
        - **同步内核经 ``asyncio.to_thread`` 卸载**：锁与文件 I/O 都是阻塞的，事件循环里不能直跑。
        """
        if not self.write_enabled:
            raise ConsoleOperationError(
                HttpErrorCode.WRITE_DISABLED,
                "config writing is disabled; enable HTTP_CONSOLE_WRITE_ENABLED when starting the service",
            )
        runtime = self._runtime_for(project_id)
        try:
            result = await asyncio.to_thread(
                apply_config_write,
                [ConfigChange(key=change.key, value=change.value) for change in request.changes],
                env_file=runtime.paths.env_file,
                backups_dir=runtime.paths.config_backups,
                audit_dir=runtime.paths.console_dir,
                write_enabled=True,
                expected_fingerprint=request.fingerprint,
                global_env_file=self.global_env_file,
            )
        except ConfigWriteRejection as exc:
            raise ConsoleOperationError(exc.code, str(exc)) from exc
        self._invalidate_runtime(project_id)
        return self._write_response(project_id, runtime, result)

    def _write_response(
        self, project_id: str, runtime: _ProjectRuntime, result: ConfigWriteResult
    ) -> ConfigWriteResponse:
        """写后条目：与面板**同源求解**（复用 50-4 的求解器，绝不自己拼装来源 / 可写性）。"""
        report = build_config_report(runtime.paths.env_file, global_env_file=self.global_env_file)
        items = {item.key: item for item in report.items}
        return ConfigWriteResponse(
            project_id=project_id,
            fingerprint=result.fingerprint,
            backup=result.backup,
            audit_recorded=result.audit_recorded,
            changes=tuple(_config_item_response(items[key]) for key in result.keys if key in items),
            notes=() if result.audit_recorded else ("audit_not_recorded",),
            labels=dict(LABELS),
        )

    def config_generation(self, project_id: str) -> int:
        """该项目的**配置代**（0 = 尚未经网页改过；每次成功写入 +1）。

        生效语义的观测点（I10）：写成功后运行时缓存被丢弃，下一次 run 用重新解析的快照；在途 run
        继续用它自己构造期的快照。
        """
        return self._config_generations.get(project_id, 0)

    def _invalidate_runtime(self, project_id: str) -> None:
        """把该项目标记为「配置代已过期」：丢缓存 → 下一次 ``_runtime_for`` 重新解析设置与引擎。

        **只丢缓存**，不触碰在途运行：run 持有自己的 ``AgentLoop``（构造期已从旧设置解析出
        ``ResolvedRuntimeConfig`` 快照），因此「当前 run 用旧值 / 下一次用新值」天然成立。
        """
        self._config_generations[project_id] = self._config_generations.get(project_id, 0) + 1
        self._runtimes.pop(project_id, None)

    # ── 原生目录选择（Story 50-8） ──

    async def pick_directory(self) -> DirectoryPickResponse:
        """在**服务端所在机器**弹一次原生目录选择窗口（登记项目的便捷入口）。

        三条语义（都**不是**安全边界）：

        - 返回值只是「用户输入的一种」：UI 拿到后仍走 ``POST /api/projects`` ⇒ 此处不校验路径、
          不碰注册表、不写任何文件（校验链只有一条，不新增第二条）；
        - 「取消 / 超时 / 后端脏值」统一为 ``cancelled=True``（UI 只需两条分支）；
        - 后端不可用（容器 / 缺 tkinter / ``--dialog-backend none``）与「已有一次在途」分别转成稳定码
          ``dialog_unavailable`` / ``dialog_busy``——不静默失败、也不排队（原生窗口不能叠着开）。
        """
        try:
            path = await self._picker.pick()
        except DialogBusyError as exc:
            raise ConsoleOperationError(HttpErrorCode.DIALOG_BUSY, "a directory dialog is already open") from exc
        except DialogUnavailableError as exc:
            raise ConsoleOperationError(HttpErrorCode.DIALOG_UNAVAILABLE, str(exc)) from exc
        return DirectoryPickResponse(path=path, cancelled=path is None, backend=self._picker.backend)

    # ── 内部 ──

    def _project_entry(self, project_id: str) -> ProjectEntry:
        for entry in self.registry.list():
            if entry.id == project_id:
                return entry
        raise ConsoleOperationError(HttpErrorCode.UNKNOWN_PROJECT, f"no project {project_id!r}")

    def _runtime_for(self, project_id: str) -> _ProjectRuntime:
        """解析（并缓存）项目运行时；未登记 → ``unknown_project``，目录失效 → ``project_unavailable``。"""
        entry = self._project_entry(project_id)
        if not entry.available:
            raise ConsoleOperationError(HttpErrorCode.PROJECT_UNAVAILABLE, f"project {project_id!r} is unavailable")
        runtime = self._runtimes.get(project_id)
        if runtime is None:
            root = Path(entry.path)
            paths = WorkspacePaths.from_root(root)
            sessions = SessionStore(str(paths.sessions))
            executor = self._handler_factory(paths, sessions) if self._handler_factory is not None else None
            runtime = _ProjectRuntime(root=root, paths=paths, sessions=sessions, executor=executor)
            self._runtimes[project_id] = runtime
        return runtime

    def _resolve_session(self, runtime: _ProjectRuntime, requested: str | None) -> str:
        """决定本次运行绑定哪个会话：显式 id 必须存在；缺省取**最近的可用**会话，无则新建。

        缺省不是「再开一个新会话」而是「继续最近的会话」（与 CLI ``--continue`` 同口径），否则刷新
        页面后每次提交都会另起一份历史。候选取自元数据列表并按 ``unreadable`` 过滤——损坏文件被
        ``recent_session_ids`` 沉底却**不会**被剔除，直接采用会把它当空会话覆盖掉（AC9）。
        """
        if requested is not None:
            sid = _guarded_session_id(requested)
            try:
                meta = runtime.sessions.load_metadata(sid)
            except SessionUnreadableError as exc:
                raise ConsoleOperationError(HttpErrorCode.SESSION_UNREADABLE, "session file cannot be parsed") from exc
            if meta is None:
                raise ConsoleOperationError(HttpErrorCode.UNKNOWN_SESSION, f"no session {sid!r}")
            return sid
        for item in runtime.sessions.list_metadata():
            if not item.unreadable:
                return item.session_id
        session_id = uuid.uuid4().hex
        runtime.sessions.create(session_id)
        return session_id

    def _run_state(self, project_id: str, session_id: str) -> tuple[str | None, RunStatus | None]:
        if self._runs is None:
            return None, None
        return self._runs.session_run_state(session_id, project_id=project_id)

    def _touch(self, project_id: str) -> None:
        """尽力更新「最近打开」时间；失败绝不影响本次请求（注册表可能刚好被外部改动）。"""
        try:
            self.registry.touch(project_id)
        except (ProjectRegistryError, OSError) as exc:
            _safe_log(logging.WARNING, "Unable to touch project %s: %s", project_id, exc)
