"""ASGI HTTP 传输层：静态资源、安全响应头与有界生命周期（Epic 49）。

**职责边界（AD-1）**：本模块只做 HTTP 协议与生命周期——路由、安全响应头、包内静态资源、
listener 的 start/close。它**不**构造 Agent：任何 Agent 能力都由入口层（``cli/http.py``）以
注入对象的方式交进来。因此本模块的导入面被刻意限制在：标准库、Pydantic、可选 ASGI 栈
（Starlette / Uvicorn，延迟导入）、``heagent.network.exposure``、``heagent.safe_logging`` 与
同层协议模型。``tests/test_architecture_contracts.py`` 对此有可执行断言。

**可选依赖（AD-11）**：Starlette / Uvicorn 由 ``pyproject.toml`` 的 ``http`` extra 直接声明，
且**只在需要时才导入**——普通 CLI 用法、库用法与 ``gui`` / ``tcp-server`` / ``init`` / ``replay``
子命令都不应因为「存在这个模块」而拉起 ASGI 栈，更不该因为缺依赖而失败。缺依赖时抛
:class:`HttpDependencyError`（带 ``pip install 'heagent[http]'`` 诊断），由入口层转成可读的
命令错误。

**生命周期契约（AD-5）**：``start()`` 只在「listener 已绑定**且** ``/api/health`` 真的可服务」
后返回；绑定失败或就绪探测失败都抛 :class:`HttpStartupError`，且绝不打印「正在监听」。
``serve_forever()`` 是阻塞式服务循环（由入口层放进自己的任务里，异常向该任务的持有者传播）。
``close()`` 按「停止接收 → 关闭 listener → 有界等待」收尾，幂等且**不会无界等待**：
Uvicorn 的连接排空受 ``timeout_graceful_shutdown`` 约束，本模块再加一层 ``wait_for`` 兜底。
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import math
import time
import uuid
from collections import OrderedDict, deque
from importlib import resources
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from heagent.network.exposure import exposure_warning, is_loopback_host
from heagent.network.http_console_protocol import (
    ConfigWriteRequest,
    ConsoleOperationError,
    ProjectRegisterRequest,
    ProjectRenameRequest,
    ProjectRunRequest,
    SessionCreateRequest,
    SessionRenameRequest,
    is_valid_session_id,
)
from heagent.network.http_protocol import (
    GENERIC_ERROR_MESSAGE,
    MAX_REQUEST_BYTES_FOR_MAX_PROMPT,
    SSE_HEARTBEAT_FRAME,
    SSE_HEARTBEAT_SECONDS,
    TERMINAL_RUN_STATUSES,
    HealthResponse,
    HttpErrorCode,
    RunEventKind,
    RunEventPayload,
    RunOutcome,
    RunRequest,
    RunStatus,
    RunStatusResponse,
    SessionMessage,
    SessionResponse,
    clip_text,
    error_envelope,
    sanitize_message,
)
from heagent.safe_logging import safe_log

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping

    from starlette.types import ASGIApp, Receive, Scope, Send

    from heagent.network.http_console_protocol import ConsoleHandler

    # 入口层交回的可调用对象：把 prompt 跑成 Agent 运行，并通过 publisher 推事件。
    #
    # ``network/`` 只认这个形状，不认 ``AgentLoop``——这是 AD-1（传输层不构造 Agent）与 AD-7
    # （治理链由既有 Agent 路径负责）的接缝；实现见入口层 ``cli.http.HttpAgentHandler``。
    RunExecutor = Callable[[str, "RunEventPublisher"], Awaitable[RunOutcome]]

logger = logging.getLogger(__name__)

# 静态资源所在包与**白名单**（路径 → 内容类型）。
#
# 用白名单而不是目录遍历：既挡掉 `../` 路径穿越，也保证「包内后来多出来的文件」不会因为
# 放在这里就被自动发布出去。新增页面资源必须同时改这张表（有测试钉住）。
_WEB_PACKAGE = "heagent.web"
_INDEX_ASSET = "index.html"
_WEB_ASSETS: dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}

# 安全响应头（AD-6 / NFR6、NFR7）：严格 CSP + 禁嗅探 + 禁 framing + 不泄露 referrer。
#
# `default-src 'none'` 把所有资源默认关掉，再逐项开同源：页面因此**不能**加载第三方脚本、
# 字体或图片，也不能内联 script/style（`script-src 'self'` 不含 'unsafe-inline'）——
# 这正是「页面不依赖第三方脚本」这条验收项的机械保证。
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (
        b"content-security-policy",
        b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        b"img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    ),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)

_HEALTH_PATH = "/api/health"
_RUNS_PATH = "/api/runs"
_RUN_DETAIL_PATH = "/api/runs/{run_id}"
_RUN_EVENTS_PATH = "/api/runs/{run_id}/events"
_SESSION_PATH = "/api/session"
_PROJECTS_PATH = "/api/projects"
_PROJECT_PATH = "/api/projects/{project_id}"
_PROJECT_SESSIONS_PATH = "/api/projects/{project_id}/sessions"
_PROJECT_SESSION_PATH = "/api/projects/{project_id}/sessions/{session_id}"
# 会话路径下**多出来的段**（``%2F`` 在路由前被解码 ⇒ ``../`` 之类会落成多段）：兜底回
# ``invalid_session_id``（AC7），而不是让「路由存不存在」的差异变成 404。
_PROJECT_SESSION_EXTRA_PATH = "/api/projects/{project_id}/sessions/{session_id}/{extra:path}"
_PROJECT_RUNS_PATH = "/api/projects/{project_id}/runs"
_PROJECT_CONFIG_PATH = "/api/projects/{project_id}/config"
# 非项目作用域的控制台端点（Story 50-8）：在**服务端所在机器**弹原生目录选择窗口。
_DIALOG_PICK_PATH = "/api/dialogs/pick-directory"

# 通配绑定地址：就绪探测改走回环（见 :func:`_probe_host`）。这里**只识别**，不在此绑定。
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "*"})  # noqa: S104 - 识别通配地址，非绑定
_IPV6_WILDCARDS = frozenset({"::", "[::]"})

# 就绪探测与关闭排空的预算（秒）。探测是进程内回环请求，正常在毫秒级返回。
_PROBE_TIMEOUT = 5.0
_SHUTDOWN_GRACE_MARGIN = 1.0

# Uvicorn 的 ``limit_concurrency`` 计的是**已建立的连接**，而 ``start()`` 的就绪探测自己也要占
# 一条（见 :meth:`HttpServer._probe_health`）。若把限额直接设为配置值，``HTTP_MAX_CONNECTIONS=1``
# 会让探测自己撞上限额（Uvicorn 直接回裸 503）→ 判为「未就绪」→ 入口永远起不来。预留一条。
_CONCURRENCY_PROBE_RESERVE = 1

# ``Last-Event-ID`` 的最大位数：够放 int64，且远小于 CPython 对 ``int()`` 的位数上限（3.11+ 起
# 超长数字串会直接 ValueError）。位数为界既是语义约束也是拒绝面约束。
_MAX_EVENT_ID_DIGITS = 19


class HttpDependencyError(RuntimeError):
    """缺少可选 HTTP 依赖（``heagent[http]``）。"""


class HttpStartupError(RuntimeError):
    """HTTP 服务未能绑定或未通过就绪探测。"""


class HttpRunConflictError(RuntimeError):
    """已有在途运行（或服务正在关闭），拒绝新运行（AD-3 的单运行约束）。"""


class HttpServerConfig(BaseModel):
    """单个 HTTP 服务实例的有界配置（默认值与 ``HTTP_*`` 设置、``docs/frame.md`` 4.17 一致）。

    ``port=0`` 允许（操作系统分配随机端口），仅用于程序化/测试用法——CLI 与设置层限定 1..65535。
    所有超时都禁 ``inf``/``nan``：``Inf`` 会让「有界关闭」静默变成无界等待。
    """

    model_config = ConfigDict(frozen=True)

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8766, ge=0, le=65535)
    max_connections: int = Field(default=16, ge=1)
    # **每个项目各自**的在途运行上限（Story 50-3 的 D9）：全局上限 = 项目数 × 该值，因此「A 项目在跑」
    # 不挡 B 项目；``POST /api/runs``（无项目归属）自己算一档，语义与 Epic 49 逐字相同。
    max_inflight_runs: int = Field(default=1, ge=1)
    max_request_bytes: int = Field(default=MAX_REQUEST_BYTES_FOR_MAX_PROMPT, ge=1)
    event_buffer_size: int = Field(default=512, ge=1)
    run_history_size: int = Field(default=64, ge=1)
    # 单次运行的**总时长**硬上限（秒）：0 = 不限制（默认）。它只该是运维显式设的兜底闸门——
    # 「跑得久」不等于「卡死」，把墙钟上限当默认会在长任务（多轮工具 / 子代理 / goal 工作流）上
    # 误杀，而卡死判定是 idle_timeout 的职责。
    request_timeout: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    # 单次运行的**静默**上限（秒）：既没有新事件、也没有在途工具时才开始计时，到点按 ``timed_out``
    # 终结（0 = 关闭静默判定）。在途工具（``tool_call`` 已发、``tool_result`` 未到）算「有进展」：
    # 一次长的 shell / 子代理调用期间没有事件，但它显然没有卡死。
    idle_timeout: float = Field(default=300.0, ge=0, allow_inf_nan=False)
    shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)


def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
    """记一条日志，**绝不让观测故障影响协议行为**（与 ``network/tcp_server.py`` 同一立场）。

    ``logger`` 被替换 / handler 抛异常 / logging 配置损坏时，请求仍必须拿到正常响应：
    观测故障只该降级成「少一条日志」。
    """
    safe_log(logger, level, message, *args, exc_info=exc_info)


def _require_module(name: str) -> Any:
    """延迟导入可选依赖模块；缺失时给出可诊断的安装提示。

    ``network/`` 是传输层，不能假定 HTTP 栈一定装好（基础安装只含 MCP 等必需依赖）。
    只有「真的要提供 HTTP 服务」的路径才走到这里，因此把导入失败收敛成一条安装指引
    而不是 ImportError 栈。
    """
    try:
        return importlib.import_module(name)
    except ImportError as exc:  # pragma: no cover - 依赖齐全时不会触发（CI 装 http extra）
        raise HttpDependencyError(
            f"the HTTP entry point requires optional dependencies (missing {name!r}); "
            "install them with: pip install 'heagent[http]'"
        ) from exc


def read_web_asset(name: str) -> bytes:
    """读取包内静态资源；``name`` 必须已在白名单内（否则 ``KeyError``）。

    ``importlib.resources.files("heagent.web")`` 是**唯一**的资源查找方式（AD-11）：它对
    ``wheel`` 安装与源码运行都成立，也不依赖 ``__file__`` 或开发机绝对路径。
    """
    if name not in _WEB_ASSETS:
        raise KeyError(name)
    return resources.files(_WEB_PACKAGE).joinpath(name).read_bytes()


# ── 运行服务（Story 49-3） ──


def _client_error_message(exc: BaseException) -> str:
    """把运行异常收敛成**有界、脱敏、非空**的客户端文案。

    用 duck-typing 取 ``HeAgentError.message``（项目自产的面向用户文本）；拿不到就用固定兜底
    文案——协议边界**绝不**回吐异常类型名、traceback 或路径。传输层因此不需要 import
    ``heagent.exceptions``（AD-1）。
    """
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return sanitize_message(message)
    return GENERIC_ERROR_MESSAGE


class _RunRecord:
    """单次运行的记录：状态、有界事件缓冲、订阅者、终态结果（AD-3/AD-4 的唯一状态源）。

    写者只有两个：运行任务（经 :class:`RunEventPublisher` 追加事件）与终态转换（
    :meth:`claim_terminal` + :meth:`close_subscribers`）。读者是 SSE 订阅者与会话快照。
    本对象**不**持有 ``AgentLoop``，也不碰 Provider——那些属于入口层注入的 executor。
    """

    def __init__(
        self,
        run_id: str,
        prompt: str,
        *,
        buffer_size: int,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.prompt = prompt
        # 不透明的归属 id（入口层在建立运行时注入）：供「项目 / 会话是否有在途运行」与「会话最近
        # 一次运行状态」查询使用。传输层不解释它们的语义，只做字符串比对（AD-1 的接缝）。
        self.project_id = project_id
        self.session_id = session_id
        self.status = RunStatus.RUNNING
        self.outcome: RunOutcome | None = None
        self.error_message: str | None = None
        self.created_at = time.perf_counter()
        # 最近一次「有进展」的时刻与在途工具数：:meth:`append` 是唯一写者，看门狗只读。
        # 「在途工具」（tool_call 已发、tool_result 未到）同样算进展——一次长的 shell / 子代理调用
        # 期间没有事件，但运行并没有卡死；漏配对时最坏也只是回到「纯事件判定」。
        self.last_activity_at = self.created_at
        self.tools_in_flight = 0
        # 看门狗终结本次运行的原因（"idle" / "hard" / None）：终态归因与文案据此区分
        # 「卡死」与「超过运维设的总时长上限」。
        self.deadline_reason: str | None = None
        # 有界 ring buffer：越过窗口的重连（49-4）据此判定 resync_required。
        self.events: deque[RunEventPayload] = deque(maxlen=buffer_size)
        self.subscribers: set[asyncio.Queue[RunEventPayload | None]] = set()
        # 订阅者队列与事件窗口**同界**：消费端（SSE 响应写 socket）被背压卡住时不能无限堆积，
        # 到界即结束该订阅者的流（见 :meth:`_drop_lagging_subscriber`）。
        self.subscriber_queue_size = buffer_size
        self._next_seq = 1

    def elapsed_ms(self) -> int:
        """自创建起的整数毫秒（终态日志用；不含任何内容字段）。"""
        return int((time.perf_counter() - self.created_at) * 1000)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    @property
    def oldest_seq(self) -> int | None:
        """缓冲里最老事件的序号（空缓冲 → ``None``）——``resync`` 判定的下界。"""
        return self.events[0].seq if self.events else None

    def append(self, kind: RunEventKind, **fields: Any) -> RunEventPayload:
        """追加一条事件：分配单调 ``seq``、入缓冲、广播给当前订阅者（同步，无 ``await``）。

        全程只在事件循环线程里执行，故顺带维护看门狗读的「有进展」信号（:attr:`last_activity_at`
        与 :attr:`tools_in_flight`）无需加锁：事件本身就是进展的证据。
        """
        self.last_activity_at = time.perf_counter()
        if kind is RunEventKind.TOOL_CALL:
            self.tools_in_flight += 1
        elif kind is RunEventKind.TOOL_RESULT:
            self.tools_in_flight = max(0, self.tools_in_flight - 1)
        payload = RunEventPayload(kind=kind, seq=self._next_seq, **fields)
        self._next_seq += 1
        self.events.append(payload)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                self._drop_lagging_subscriber(queue)
        return payload

    def _drop_lagging_subscriber(self, queue: asyncio.Queue[RunEventPayload | None]) -> None:
        """订阅者跟不上（有界队列已满）：**结束它的流**，而不是无限堆积或静默丢事件。

        队列与事件窗口同界，因此「队列满」等价于「该订阅者落后整整一个窗口」——它无论如何都要走
        重新同步路径，此时丢掉队列里的旧事件并不可惜：客户端会带 ``Last-Event-ID`` 重连，服务端
        按 ring buffer 补齐；若游标已越出窗口，``needs_resync`` 回 409，客户端拉 ``/api/session``
        快照收敛（AD-4 的既有恢复路径）。哨兵 ``None`` 让生成器**立即**结束该流（客户端据此重连），
        而不是干等心跳超时。规则：宁可让客户端重连，也不静默跳过事件。
        """
        self.subscribers.discard(queue)
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(None)

    def claim_terminal(self, status: RunStatus) -> bool:
        """抢占终态转换：**第一个调用者获胜**（AD-10），后续调用是 no-op 并返回 ``False``。

        只置状态、不写事件——获胜者随后自己 append 唯一的终态事件，再 :meth:`close_subscribers`，
        保证「终态事件先于流结束标记」的顺序。
        """
        if self.is_terminal:
            return False
        self.status = status
        return True

    def close_subscribers(self) -> None:
        """终态事件写完后通知所有订阅者「流到此结束」（``None`` 是哨兵，不占事件 ID）。"""
        for queue in list(self.subscribers):
            queue.put_nowait(None)


class RunEventPublisher:
    """入口层的事件出口：只暴露「发什么」，``seq`` 分配、截断与广播都在服务层。

    截断在这里做（而不是让入口层自己裁）：事件大小必须有界，而入口层只管把
    ``StreamEvent`` 映射过来。
    """

    def __init__(self, record: _RunRecord) -> None:
        self._record = record

    def text(self, text: str) -> None:
        """回答文本增量。"""
        self._record.append(RunEventKind.TEXT, text=clip_text(text))

    def tool_call(self, name: str, target: str) -> None:
        """工具开始执行（``target`` 是单行作用对象摘要，由 ``tools.call_summary`` 产出）。"""
        self._record.append(RunEventKind.TOOL_CALL, tool_name=name, tool_target=clip_text(target))

    def tool_result(self, name: str, output: str, *, is_error: bool) -> None:
        """工具执行完成；``is_error`` 让展示层把失败归因到具体调用。"""
        self._record.append(
            RunEventKind.TOOL_RESULT,
            tool_name=name,
            tool_output=clip_text(output),
            tool_error=is_error,
        )


class HttpRunService:
    """进程内单用户会话 + 运行记录的唯一所有者（AD-3）。

    三条不变量：

    - **单运行**：``max_inflight_runs``（MVP 默认 1）用**非等待式**名额限制——满即
      ``run_conflict``，绝不排队；名额在 ``finally`` 里归还（成功 / 失败 / 取消 / 超时都归还）。
      **名额按项目各自生效**（Story 50-3 的 D9）：作用域 = 项目（``project_id is None`` 是「无项目归属」
      的 49 端点那一档），因此「A 项目在跑」不挡 B 项目，同一项目内的第二个 run 仍被拒。
    - **每 run 独立 ``AgentLoop``**：由注入的 executor 负责；服务层不持有 loop，也不共享任何
      每运行可变状态（模型与用量只从该运行的结果复制，不读共享 provider 的最近状态）。
    - **会话投影只有一条路径**：:meth:`_project` 只在 ``COMPLETED`` 时追加 prompt + 最终回答；
      失败 / 取消 / 超时**绝不**把部分文本投影进历史。
    """

    def __init__(
        self,
        config: HttpServerConfig,
        executor: RunExecutor,
        *,
        session_id: str | None = None,
    ) -> None:
        self.config = config
        self.session_id = session_id or uuid.uuid4().hex
        self._executor = executor
        self._runs: OrderedDict[str, _RunRecord] = OrderedDict()
        # run_id → 运行任务：取消与关停都要按 id 找到它（``set`` 无法表达「取消哪一个」）。
        self._run_tasks: dict[str, asyncio.Task[None]] = {}
        self._active: set[str] = set()
        self._messages: list[SessionMessage] = []
        self._current_run_id: str | None = None
        self._closing = False

    # ---- 查询 ----

    @property
    def active_runs(self) -> int:
        """当前占用在途名额的运行数（诊断与测试用）。"""
        return len(self._active)

    def run(self, run_id: str) -> _RunRecord | None:
        """按 id 取运行记录；已被淘汰或从未存在时返回 ``None``（调用方回 ``unknown_run``）。"""
        return self._runs.get(run_id)

    def session_snapshot(self) -> SessionResponse:
        """``GET /api/session`` 的投影：会话 id、当前（或最近）运行状态、已完成的对话历史。"""
        current = self._runs.get(self._current_run_id) if self._current_run_id is not None else None
        return SessionResponse(
            session_id=self.session_id,
            run_id=current.run_id if current is not None else None,
            status=current.status if current is not None else None,
            messages=list(self._messages),
        )

    # ---- 生命周期 ----

    def reopen(self) -> None:
        """重新武装运行入口（``close()`` 的反操作）：清除「正在关闭」标记。

        只有 :meth:`HttpServer.start` 在启动成功后调用。若不复位，``close()`` → ``start()`` 重启
        同一实例会得到一个「健康检查 200、每次提交都 409 shutting_down」的假可用状态。
        """
        self._closing = False

    async def start_run(
        self,
        prompt: str,
        *,
        executor: RunExecutor | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> _RunRecord:
        """创建并启动一次运行；名额已满或正在关闭 → :class:`HttpRunConflictError`（不排队）。

        ``executor`` 缺省为服务级 executor（``POST /api/runs`` 的路径）；项目内运行（Story 50-3）
        传入**按项目 / 会话绑定**的 executor，同时带上不透明的 ``project_id`` / ``session_id`` 供
        在途查询使用（名额仍按**本 service** 计，即每项目各一份 —— 见脊柱 §6 的 D9 口径）。
        """
        if self._closing:
            raise HttpRunConflictError("server is shutting down")
        if self._inflight_in_scope(project_id) >= self.config.max_inflight_runs:
            raise HttpRunConflictError("another run is already in flight")
        record = _RunRecord(
            uuid.uuid4().hex,
            prompt,
            buffer_size=self.config.event_buffer_size,
            project_id=project_id,
            session_id=session_id,
        )
        self._store(record)
        self._active.add(record.run_id)
        if project_id is None:
            # 只有「无项目归属」的运行（Epic 49 的 ``POST /api/runs``）驱动 ``/api/session`` 投影，
            # 项目内运行不改变它——49 端点的语义因此逐字不变（R3/I13）。
            self._current_run_id = record.run_id
        _safe_log(logging.INFO, "http event=run_started run_id=%s", record.run_id)
        task: asyncio.Task[None] = asyncio.create_task(
            self._execute(record, executor or self._executor), name=f"heagent-http-run-{record.run_id}"
        )
        self._run_tasks[record.run_id] = task

        def _on_done(finished: asyncio.Task[None]) -> None:
            self._finalize(finished, record.run_id)

        task.add_done_callback(_on_done)
        return record

    def _inflight_in_scope(self, project_id: str | None) -> int:
        """该作用域内的在途运行数（作用域 = 项目；``None`` 是 49 端点的「无项目归属」档）。

        D9：名额按项目各自生效、跨项目不共享（全局上限 = 项目数 × ``max_inflight_runs``）。在途集合
        与运行记录同源，**不额外建索引**——判定与「属于谁」永远是同一个事实。
        """
        count = 0
        for run_id in self._active:
            record = self._runs.get(run_id)
            if record is not None and record.project_id == project_id:
                count += 1
        return count

    def has_inflight_run(self, *, project_id: str | None = None, session_id: str | None = None) -> bool:
        """是否有在途运行同时满足给出的（项目 / 会话）条件：50-2 的 ``project_busy`` 与 50-3 的
        ``session_busy`` 共用。

        判据是**逐项 AND**（给几项就必须全中）：只给项目 = 「该项目有在跑」（项目移除闸门）；两项都给 =
        「这个会话正在被写」（会话删除闸门）。若两项之间取 OR，同一项目里**别的**会话在跑就会把删除
        请求误判成 ``session_busy``（评审发现，2026-09-24 修）。在途集合（``_active``）与运行记录同源，
        因此查询就是单点事实——不需要控制台另建索引（评审 R2 要求的「console 级单点」在此天然成立）。
        """
        for run_id in self._active:
            record = self._runs.get(run_id)
            if record is None:
                continue
            if project_id is not None and record.project_id != project_id:
                continue
            if session_id is not None and record.session_id != session_id:
                continue
            return True
        return False

    def session_run_state(
        self, session_id: str, *, project_id: str | None = None
    ) -> tuple[str | None, RunStatus | None]:
        """该会话**最近一次**运行的 ``(run_id, status)``；没有则 ``(None, None)``。

        ``project_id`` 给定时同时要求归属匹配：会话文件按项目分目录存放，跨项目的同名 id 记录不该被
        当作「这个会话的运行」（Story 50-3 的 per-project 口径）。「run → 会话」的索引就在运行记录里
        （``OrderedDict`` 按建立顺序），因此上限与回收天然跟随 ``run_history_size``（NFR-11 的有界
        要求 / 评审 R4），不需要第二份会泄漏的映射表。
        """
        for run_id in reversed(self._runs):
            record = self._runs[run_id]
            if record.session_id != session_id:
                continue
            if project_id is not None and record.project_id != project_id:
                continue
            return record.run_id, record.status
        return None, None

    def _finalize(self, task: asyncio.Task[None], run_id: str) -> None:
        """运行任务的**兜底收尾**：注销任务、归还在途名额、并补写「未启动即被取消」的终态。

        ``asyncio`` 里 ``create_task`` 之后立刻 ``cancel()``（同一个事件循环 tick 内）会让协程体
        **完全不执行**——``_execute`` 的 ``except CancelledError`` 与 ``finally`` 都不会跑，于是
        记录会永远停在 ``running``、名额也永远不归还（实测：DELETE 立即返回 200 但状态是 running，
        后续订阅等不到终态事件而挂住）。这里把「终态 + 名额」放进 done callback，任何结束路径
        （正常、异常、取消、未启动即取消）都覆盖；正常路径下 ``claim_terminal`` 是 no-op。
        """
        self._run_tasks.pop(run_id, None)
        self._active.discard(run_id)
        record = self._runs.get(run_id)
        if record is None:
            return
        if record.claim_terminal(RunStatus.CANCELLED):
            record.append(RunEventKind.CANCELLED, message="run cancelled")
            record.close_subscribers()
        # 统一终态观测（AD-9）：只有不透明 run id、状态与耗时——**不含** prompt、回答或工具输出。
        _safe_log(
            logging.INFO if record.status is RunStatus.COMPLETED else logging.WARNING,
            "http event=run_finished run_id=%s status=%s elapsed_ms=%d",
            run_id,
            record.status.value,
            record.elapsed_ms(),
        )

    async def cancel_run(self, run_id: str) -> _RunRecord | None:
        """协作式取消**指定**运行并等待它进入终态（有界）；未知 run 返回 ``None``。

        - 只取消该 run 的任务：不触碰其它运行，也不关服务（49-4 的 Always 项）；
        - 幂等：任务已结束（或已是终态）时直接返回记录——终态由 ``claim_terminal`` 保证唯一；
        - 等待有界（``shutdown_timeout``）：忽略取消的运行不会把 ``DELETE`` 挂住，此时如实返回
          ``running``，由运行超时或关停兜底（AD-10「第一个终态获胜」不变）。
        """
        record = self._runs.get(run_id)
        if record is None:
            return None
        task = self._run_tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            _done, pending = await asyncio.wait({task}, timeout=self.config.shutdown_timeout)
            if pending:
                _safe_log(logging.WARNING, "http event=cancel_timeout run_id=%s", run_id)
        return record

    def needs_resync(self, record: _RunRecord, last_event_id: int | None) -> bool:
        """客户端的游标是否已落在事件窗口之外（AD-4 的 ``resync_required`` 判据）。

        语义（严格大于）：客户端说「我收到 N」时，只要 N+1 之后的事件都还在缓冲里就能无缝续读，
        即 ``N >= oldest_seq - 1``；更小的 N 意味着中间事件已被 ring buffer 淘汰，**必须**重新
        同步而不是发一条看似连续的流。没有游标（或 0）等价于「从头读」：若窗口已淘汰开头
        （``oldest_seq > 1``），同样要求重新同步。
        """
        cursor = 0 if last_event_id is None else max(0, last_event_id)
        oldest = record.oldest_seq
        if oldest is None:
            return False
        return cursor < oldest - 1

    def subscriber_count(self, record: _RunRecord) -> int:
        """该运行当前的 SSE 订阅者数（限额判定与测试用）。"""
        return len(record.subscribers)

    async def close(self) -> None:
        """停止接收新运行、使在途运行进入终态、等待运行任务退出（有界，AD-5 的关闭序列）。

        取消运行任务 ⇒ ``_execute`` 的 ``CancelledError`` 分支把记录置为 ``CANCELLED`` 并发出
        终态事件（关停赢得的运行一律记 ``cancelled``）。超时后仍会返回：``asyncio`` 无法强杀
        忽略取消的任务，残留由容器退出兜底。
        """
        self._closing = True
        tasks = tuple(self._run_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=self.config.shutdown_timeout)
            if pending:
                _safe_log(logging.WARNING, "http event=run_shutdown_timeout pending=%d", len(pending))
        self._run_tasks.clear()

    # ---- 运行执行 ----

    def _deadline_tick(self) -> float | None:
        """看门狗的巡检间隔；两个时限都没开时返回 ``None``（不启动看门狗）。

        取最小时限的 1/4（夹在 10ms..5s）：到点后最多晚一个 tick 发现，又不会为长时限空转占 CPU。
        ``inf``/``nan`` 已被 :class:`HttpServerConfig` 拒掉，故此处不必再防。
        """
        limits = [value for value in (self.config.request_timeout, self.config.idle_timeout) if value > 0]
        if not limits:
            return None
        return min(5.0, max(0.01, min(limits) / 4))

    def _deadline_message(self, record: _RunRecord) -> str:
        """时限终态的客户端文案：**区分**「卡死」与「超过运维显式设的总时长上限」。"""
        if record.deadline_reason == "idle":
            return f"run stalled: no activity for {self.config.idle_timeout:g}s"
        return f"run exceeded the configured time limit ({self.config.request_timeout:g}s)"

    async def _watch_deadlines(self, record: _RunRecord, task: asyncio.Task[Any], tick: float) -> None:
        """时限看门狗：判据成立就 ``task.cancel()``，并把**原因**写进记录（终态归因用）。

        两条判据（各自 > 0 才生效）：

        - ``request_timeout``：总时长硬上限——运维显式设的兜底闸门，默认 0（不限制）；
        - ``idle_timeout``：静默上限——**既没有新事件、也没有在途工具**才开始计时。

        为什么不用墙钟 ``asyncio.timeout``：Agent 运行「跑得久」是常态（多轮工具 / 子代理 / goal
        工作流），墙钟当默认会误杀正常长任务；真正该杀的是**卡死**（provider 挂住、吞掉取消）。
        取消仍统一走 ``_execute`` 的 ``CancelledError`` 分支（终态唯一），由 ``deadline_reason``
        区分「看门狗杀的」与「关停 / DELETE 杀的」。
        """
        while True:
            await asyncio.sleep(tick)
            if record.is_terminal:
                return
            now = time.perf_counter()
            hard = self.config.request_timeout
            if hard > 0 and now - record.created_at >= hard:
                record.deadline_reason = "hard"
                break
            idle = self.config.idle_timeout
            if idle > 0 and record.tools_in_flight == 0 and now - record.last_activity_at >= idle:
                record.deadline_reason = "idle"
                break
        if record.is_terminal:
            # 收尾竞态：判据成立的同时运行自己终结了——终态第一个赢，这里不碰它。
            return
        task.cancel()

    async def _execute(self, record: _RunRecord, executor: RunExecutor) -> None:
        """跑一次运行并把结果写进记录（唯一写终态的地方，AD-10）。

        时限（``HTTP_IDLE_TIMEOUT`` 静默 / ``HTTP_REQUEST_TIMEOUT`` 总时长，二者都可关）与取消都经
        这里的终态转换收口：**第一个**拿到终态的转换获胜，只发一条终态事件，并且在 ``finally`` 里
        归还唯一的在途名额。

        时限由 :meth:`_watch_deadlines` 以「取消运行任务」实现：``cancel()`` 只能**请求**取消，吞掉
        ``CancelledError`` 的 executor（长工具 / 子代理可能如此）会让它正常返回，此时时限并未真正
        生效——终态仍按实际结果走，但必须留下 ``event=timeout_ignored``。运行内部（provider / 网络）
        自己抛的 ``TimeoutError`` 只是普通异常 ⇒ 按 **failed** 归因，不会谎报「超过配置时限」。
        """
        task = asyncio.current_task()
        tick = self._deadline_tick()
        watchdog: asyncio.Task[None] | None = None
        if task is not None and tick is not None:
            watchdog = asyncio.create_task(
                self._watch_deadlines(record, task, tick),
                name=f"heagent-http-deadline-{record.run_id}",
            )
        try:
            outcome = await executor(record.prompt, RunEventPublisher(record))
        except asyncio.CancelledError:
            if record.deadline_reason is not None and not self._closing:
                # 看门狗杀的：终态按时限走，并**吞掉**这次取消——与旧实现（``asyncio.timeout`` 把
                # CancelledError 转成 TimeoutError）同义：任务正常结束，不是 cancelled。
                if record.claim_terminal(RunStatus.TIMED_OUT):
                    record.append(RunEventKind.TIMED_OUT, message=self._deadline_message(record))
                    record.close_subscribers()
                return
            if record.claim_terminal(RunStatus.CANCELLED):
                record.append(RunEventKind.CANCELLED, message="run cancelled")
                record.close_subscribers()
            raise
        except Exception as exc:
            # 运行是后台任务，异常不会走 Starlette / Uvicorn 的 traceback 通道：诊断细节只进服务端
            # 日志（客户端拿脱敏文案），否则真实缺陷的栈会被彻底丢掉。
            _safe_log(logging.ERROR, "http event=run_failed run_id=%s", record.run_id, exc_info=True)
            if record.claim_terminal(RunStatus.FAILED):
                record.error_message = _client_error_message(exc)
                record.append(RunEventKind.ERROR, message=record.error_message)
                record.close_subscribers()
        else:
            if record.deadline_reason is not None and not self._closing:
                # 时限已到但 executor 吞掉取消正常返回：终态按实际结果，但「时限没生效」必须可见。
                _safe_log(
                    logging.WARNING,
                    "http event=timeout_ignored run_id=%s reason=%s elapsed_ms=%d",
                    record.run_id,
                    record.deadline_reason,
                    record.elapsed_ms(),
                )
            if record.claim_terminal(RunStatus.COMPLETED):
                record.outcome = outcome
                record.append(
                    RunEventKind.DONE,
                    text=clip_text(outcome.answer),
                    model=outcome.model,
                    usage=outcome.usage,
                )
                record.close_subscribers()
                self._project(record)
        finally:
            if watchdog is not None:
                watchdog.cancel()
            self._active.discard(record.run_id)

    def _store(self, record: _RunRecord) -> None:
        """记住运行记录；超出 ``run_history_size`` 时淘汰**最旧的终态记录**。

        只淘汰终态记录（``run_history_size`` 的语义是「已终结 run 的保留条数」）：在途运行必须
        始终可按 id 找到——否则 ``DELETE`` 与 SSE 订阅会回 ``unknown_run``，而它仍占着在途名额、
        ``_finalize`` 也因查不到记录而连一行终态日志都不写，等于从系统里凭空消失。全部记录都在途
        时宁可暂时超出上限（在途数本身受 ``max_inflight_runs`` 约束），也不淘汰活记录。
        """
        self._runs[record.run_id] = record
        while len(self._runs) > self.config.run_history_size:
            victim = next((run_id for run_id, rec in self._runs.items() if rec.is_terminal), None)
            if victim is None:
                return
            del self._runs[victim]

    def _project(self, record: _RunRecord) -> None:
        """终态 → 会话的唯一 reducer：只投影成功完成运行的 prompt 与最终回答（AD-3）。

        只对**无项目归属**的运行生效（``POST /api/runs``）：项目内运行的历史以**会话文件**为唯一
        权威（Story 50-3），两套口径因此不会在同一页面上互相矛盾。
        """
        if record.project_id is not None:
            return
        if record.status is not RunStatus.COMPLETED or record.outcome is None:
            return
        self._messages.append(SessionMessage(role="user", text=record.prompt))
        self._messages.append(SessionMessage(role="assistant", text=record.outcome.answer))
        limit = 2 * self.config.run_history_size
        if len(self._messages) > limit:
            del self._messages[: len(self._messages) - limit]

    async def stream_events(
        self,
        record: _RunRecord,
        last_event_id: int | None = None,
        *,
        heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
    ) -> AsyncIterator[RunEventPayload | None]:
        """SSE 的事件源：先重放缓冲，再跟随实时事件；终态事件之后流立即结束（AD-4）。

        - ``last_event_id``（``Last-Event-ID``）只重放**严格大于**它的序号（缺口的判定由调用方
          在建立流之前用 :meth:`needs_resync` 做完，这里只管「不重复」）；
        - ``yield None`` 表示**心跳**（注释帧，不占事件 ID、不推进游标）；
        - 订阅者只读：断线只移除本队列，**绝不**取消运行——取消只能通过 ``DELETE``。
        """
        queue: asyncio.Queue[RunEventPayload | None] = asyncio.Queue(maxsize=record.subscriber_queue_size)
        record.subscribers.add(queue)
        try:
            # 注册订阅者与快照之间没有 ``await`` ⇒ 在单线程事件循环里是原子的：不会有事件
            # 「既在快照里、又被投进队列」而重复发送。
            snapshot = tuple(record.events)
            is_terminal = record.is_terminal
            for payload in snapshot:
                if last_event_id is None or payload.seq > last_event_id:
                    yield payload
            if is_terminal:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                except TimeoutError:
                    # 空闲期的保活帧：客户端（及中间层）据此判定连接仍然活着。超时取消的是
                    # ``queue.get()`` 本身，不会丢掉已在队列里的事件。
                    yield None
                    continue
                if item is None:
                    return
                if last_event_id is not None and item.seq <= last_event_id:
                    continue
                yield item
        finally:
            record.subscribers.discard(queue)


# ── 同源防线与请求观测（Story 49-5） ──

# 我们不信任任何代理头：反向代理部署不在 MVP 支持范围（AD-6），出现这些头即拒绝请求——
# 否则 `X-Forwarded-Host` 就能把「跨站请求」伪装成本机同源请求（DNS rebinding 的常见变体）。
_UNTRUSTED_FORWARD_HEADERS = frozenset(
    {b"forwarded", b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"x-real-ip"}
)

# 回环绑定时接受的等价本机写法：三者指向同一个 listener（浏览器地址栏习惯不同），拒绝其中
# 任何一个都会让「本机自用」这个主用例失效。**非回环绑定只用配置的那个名字**（不额外放宽）。
_LOOPBACK_HOST_ALIASES = ("127.0.0.1", "localhost", "[::1]")


def _canonical_authority(value: str) -> str | None:
    """规范化 ``Host`` 的 authority：小写、省略 http 默认端口 80。

    返回 ``None`` 表示格式不可信（含路径/查询、非数字端口、越界端口、空值）——调用方按拒绝处理。
    IPv6 字面量写成 ``[::1]:8766``（方括号是 authority 的一部分）。
    """
    text = value.strip().lower()
    if not text or "/" in text or "?" in text:
        return None
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            return None
        host = text[: end + 1]
        rest = text[end + 1 :]
        port = rest[1:] if rest.startswith(":") else ""
    elif ":" in text:
        host, _, port = text.rpartition(":")
    else:
        host, port = text, ""
    if port and (not port.isdigit() or int(port) > 65535):
        return None
    effective = int(port) if port else 80
    return host if effective == 80 else f"{host}:{effective}"


def _allowed_hosts(config: HttpServerConfig) -> frozenset[str]:
    """允许的 host 名集合：配置 host + （**仅当它是回环时**）等价本机写法。

    这是「请求必须打在本 listener 上」的判据，用于挡住 Host 伪装（例如把 ``evil.example`` 解析到
    127.0.0.1 的 DNS rebinding）。**不是认证**：能连上端口的本机进程可以随便伪造 Host。
    """
    host = config.host.strip().lower()
    names = {host}
    # 通配绑定（``0.0.0.0`` / ``::`` / ``*``）没有单一主机名：就绪探测与浏览器都是从回环地址
    # 打进这个 listener 的（见 :func:`_probe_host`），因此把等价本机写法一并接受——否则探测会
    # 撞上自己的 Host 校验（403），``HTTP_HOST=0.0.0.0`` 永远起不来。
    # 这不削弱反 DNS-rebinding：伪造的域名（``evil.example``）仍在拒绝之列；通配绑定的其它网卡
    # 地址也仍按「不匹配 listener 名」拒绝（非回环联网不受支持，见 CLI help 与 exposure 告警）。
    if is_loopback_host(host) or host in _WILDCARD_HOSTS or host in _IPV6_WILDCARDS:
        names.update(_LOOPBACK_HOST_ALIASES)
    return frozenset(names)


def _allowed_ports(config: HttpServerConfig) -> frozenset[int] | None:
    """允许的端口集合；``None`` 表示「任意端口」。

    ``port=0``（操作系统分配随机端口，只用于程序化/测试）时构建 app 还不知道实际端口，故不限制
    端口；CLI 与 ``HTTP_PORT`` 都限定 1..65535，生产路径永远有确定的端口。
    """
    return None if config.port == 0 else frozenset({config.port})


def _split_authority(authority: str) -> tuple[str, int]:
    """把规范化后的 authority 拆成 ``(host, port)``；无端口视为 http 默认端口 80。"""
    if authority.startswith("["):
        end = authority.find("]")
        host = authority[: end + 1]
        rest = authority[end + 1 :]
        return host, int(rest[1:]) if rest.startswith(":") else 80
    host, sep, port = authority.rpartition(":")
    if not sep:
        return authority, 80
    return host, int(port)


def _request_origin_violation(
    scope: MutableMapping[str, Any],
    *,
    hosts: frozenset[str],
    ports: frozenset[int] | None,
) -> str | None:
    """请求是否违反同源防线；返回违规原因（供日志），``None`` 表示通过。

    规则（AD-6）：

    1. 出现任何 forwarded-* 头 ⇒ 拒绝（见 :data:`_UNTRUSTED_FORWARD_HEADERS`）；
    2. ``Host`` 必须恰好一个、且规范化后的 host/port 都在允许集合内；
    3. 若带 ``Origin``：不得为 ``null``/空，且必须等于 ``http://`` 加该 authority（同源）。
       **缺少 Origin** 只表示「非浏览器客户端」（curl / 脚本），Host 已校验故放行。
    """
    headers = scope.get("headers") or []
    if any(name.lower() in _UNTRUSTED_FORWARD_HEADERS for name, _value in headers):
        return "untrusted forwarded header"
    host_headers = [value.decode("latin-1") for name, value in headers if name.lower() == b"host"]
    if len(host_headers) != 1:
        return "missing or duplicated Host header"
    authority = _canonical_authority(host_headers[0])
    if authority is None:
        return "malformed Host header"
    host, port = _split_authority(authority)
    if host not in hosts:
        return "host not allowed"
    if ports is not None and port not in ports:
        return "port not allowed"
    for name, value in headers:
        if name.lower() != b"origin":
            continue
        origin = value.decode("latin-1").strip().lower()
        if not origin or origin == "null":
            return "null Origin"
        if origin != f"http://{authority}":
            return "origin mismatch"
    return None


async def _send_json(
    send: Send, status_code: int, payload: dict[str, Any], *, extra: tuple[tuple[bytes, bytes], ...] = ()
) -> None:
    """在**没有 Starlette 响应对象**的中间件层发一个 JSON 响应（保持错误信封一致）。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        *extra,
    ]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class _OriginGuardMiddleware:
    """同源防线（AD-6）：校验 Host，并在带 Origin 时要求它与 listener 同源。

    **defense-in-depth，不是认证**：能连上回环端口的本机进程可以伪造请求头直接调 API；
    这里的价值是挡住浏览器发起的跨站请求（CSRF）与 Host 伪装（DNS rebinding），并把
    forwarded-* 头这类「代理欺骗」明确拒掉。
    """

    def __init__(self, app: ASGIApp, *, hosts: frozenset[str], ports: frozenset[int] | None) -> None:
        self.app = app
        self.hosts = hosts
        self.ports = ports

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        violation = _request_origin_violation(scope, hosts=self.hosts, ports=self.ports)
        if violation is None:
            await self.app(scope, receive, send)
            return
        # 违规原因只进服务端日志；客户端拿固定的脱敏文案（不透露允许的 host 集合）。
        _safe_log(
            logging.WARNING,
            "http event=origin_rejected method=%s path=%s reason=%s",
            scope.get("method"),
            scope.get("path"),
            violation,
        )
        await _send_json(
            send,
            403,
            error_envelope(HttpErrorCode.ORIGIN_FORBIDDEN, "request origin rejected").model_dump(mode="json"),
        )


class _AccessLogMiddleware:
    """请求级观测（AD-9）：每条请求一条日志 + 响应头 ``x-request-id``。

    只记 **方法 / 路径 / 状态码 / 耗时 / 不透明 request id**；**绝不**记请求体、请求头、
    提示词、回答或工具输出——内容字段一律排除，而不是靠脱敏去打补丁。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        status = 0

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 0))
                raw = list(message.get("headers") or [])
                raw.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": raw}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            _safe_log(
                logging.INFO if status < 400 else logging.WARNING,
                "http event=request request_id=%s method=%s path=%s status=%s elapsed_ms=%d",
                request_id,
                scope.get("method"),
                scope.get("path"),
                status,
                int((time.perf_counter() - started) * 1000),
            )


class _SecurityHeadersMiddleware:
    """给每个 HTTP 响应补安全头的纯 ASGI 包装（不吃框架内部 API，便于单独测试）。

    已存在的同名响应头**不覆盖**（框架或路由给了更具体取值时以它们为准，避免中间件把
    有意设置的头改回去）。
    """

    def __init__(self, app: ASGIApp, headers: tuple[tuple[bytes, bytes], ...]) -> None:
        self.app = app
        self.headers = headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                raw = list(message.get("headers") or [])
                present = {key.lower() for key, _ in raw}
                raw.extend((key, value) for key, value in self.headers if key.lower() not in present)
                message = {**message, "headers": raw}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _json_error(responses: Any, code: HttpErrorCode, message: str, *, status_code: int) -> Any:
    """统一的 JSON 错误响应（有界、脱敏、结构稳定，AD-8）。"""
    return responses.JSONResponse(
        error_envelope(code, message).model_dump(mode="json"),
        status_code=status_code,
    )


class HttpRequestTooLargeError(RuntimeError):
    """请求体超过 ``max_request_bytes``（**未读完**即拒绝）。"""


async def _read_body(request: Any, *, limit: int) -> bytes:
    """按块读取请求体；超限立即中断。

    **不能**用 Starlette 的 ``request.body()``：它会把整个 body 读进内存再交给我们——对不可信
    客户端这等于把「有界」交给对方决定。
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HttpRequestTooLargeError(f"request body exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_model(
    request: Any,
    *,
    model: Any,
    config: HttpServerConfig,
    responses: Any,
    blank_code: HttpErrorCode | None = None,
) -> tuple[Any, Any | None]:
    """读请求体并校验为 ``model``：返回 ``(parsed, error_response)``（恰有一个非 ``None``）。

    把「有界读 + Pydantic 校验 + 统一错误信封」收在一处：``POST /api/runs`` 与三条控制台写路由
    因此共用同一套 413/400 语义（取值与 49-3 一致，不因重构而漂移）。

    ``parsed`` 的类型是 ``Any`` 而不是 ``| None``：契约是「要么拿到了模型、要么调用方已经被
    ``if error is not None: return error`` 短路掉」。让类型带上 ``| None`` 只会逼 9 处调用点重复同一句
    收窄断言，换不来任何真实保证（错误路径返回的 ``None`` 永远到不了使用点）。
    """
    try:
        raw = await _read_body(request, limit=config.max_request_bytes)
    except HttpRequestTooLargeError:
        return None, _json_error(
            responses,
            HttpErrorCode.REQUEST_TOO_LARGE,
            "request body exceeds the configured limit",
            status_code=413,
        )
    try:
        return model.model_validate_json(raw), None
    except ValidationError as exc:
        code = HttpErrorCode.INVALID_REQUEST
        if blank_code is not None and any("blank" in str(error.get("msg", "")) for error in exc.errors()):
            code = blank_code
        return None, _json_error(responses, code, "request body is invalid", status_code=400)


# 控制台稳定错误码 → HTTP 状态码（未列出的码按 400 处理；未知码由下面的函数降级为 500）。
_CONSOLE_ERROR_STATUS: dict[HttpErrorCode, int] = {
    HttpErrorCode.INVALID_REQUEST: 400,
    HttpErrorCode.INVALID_PROJECT_PATH: 400,
    HttpErrorCode.INVALID_SESSION_ID: 400,
    HttpErrorCode.CONFIRM_REQUIRED: 400,
    HttpErrorCode.UNKNOWN_PROJECT: 404,
    HttpErrorCode.UNKNOWN_SESSION: 404,
    HttpErrorCode.PROJECT_UNAVAILABLE: 409,
    HttpErrorCode.PROJECT_NOT_REMOVABLE: 409,
    HttpErrorCode.PROJECT_BUSY: 409,
    HttpErrorCode.PROJECT_LIMIT_REACHED: 409,
    HttpErrorCode.SESSION_CONFLICT: 409,
    HttpErrorCode.SESSION_BUSY: 409,
    HttpErrorCode.SESSION_UNREADABLE: 409,
    HttpErrorCode.RUN_CONFLICT: 409,
    HttpErrorCode.LOOPBACK_REQUIRED: 403,
    # 原生目录选择（Story 50-8）：后端不可用 → 503（不是客户端错误）；已有一次在途 → 409。
    HttpErrorCode.DIALOG_UNAVAILABLE: 503,
    HttpErrorCode.DIALOG_BUSY: 409,
    # 配置写入通道（Story 50-5）：闸门关 / 键只读 → 403；值非法 → 400；指纹冲突 → 409；写失败 → 500。
    HttpErrorCode.WRITE_DISABLED: 403,
    HttpErrorCode.FIELD_NOT_WRITABLE: 400,
    HttpErrorCode.INVALID_VALUE: 400,
    HttpErrorCode.CONFIG_CONFLICT: 409,
    HttpErrorCode.CONFIG_WRITE_FAILED: 500,
    # 服务端状态类失败（如注册表内容无法解析 ⇒ 拒绝改写）：显式 500，别落到默认 400。
    HttpErrorCode.SERVER_ERROR: 500,
}


def _console_error_response(responses: Any, exc: BaseException, *, event: str) -> Any:
    """注入的控制台失败时的统一响应。

    ``ConsoleOperationError`` 携带**稳定码**，映射为固定状态码；其它异常一律 500 + 固定文案，
    诊断细节只进服务端日志（AD-8/AD-9）。码不在闭集内（入口层写错）时降级为 500 并留下 ERROR，
    绝不把未知码原样回给客户端。
    """
    if isinstance(exc, ConsoleOperationError):
        try:
            code = HttpErrorCode(exc.code)
        except ValueError:
            _safe_log(logging.ERROR, "http event=%s unknown_console_code=%s", event, exc.code)
            return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=500)
        return _json_error(responses, code, str(exc), status_code=_CONSOLE_ERROR_STATUS.get(code, 400))
    _safe_log(logging.ERROR, "http event=%s handler_failed", event, exc_info=True)
    return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=500)


def format_sse(payload: RunEventPayload) -> bytes:
    """把一条事件编码为 SSE 帧（``id`` / ``event`` / ``data``，以空行结束）。

    ``data`` 是单行 JSON（``json`` 转义会吃掉换行），因此整帧不会出现「意外的多行 data」。
    """
    data = payload.model_dump_json(exclude_none=True, ensure_ascii=False)
    return f"id: {payload.seq}\nevent: {payload.kind.value}\ndata: {data}\n\n".encode()


async def _sse_stream(
    service: HttpRunService,
    record: _RunRecord,
    last_event_id: int | None = None,
    *,
    heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
) -> AsyncIterator[bytes]:
    """SSE 响应体：只读订阅运行事件；``None`` 转成心跳注释帧；断线即回收订阅者（生成器 finally）。"""
    async for payload in service.stream_events(record, last_event_id, heartbeat_seconds=heartbeat_seconds):
        yield SSE_HEARTBEAT_FRAME if payload is None else format_sse(payload)


def _parse_last_event_id(request: Any) -> int | None:
    """解析 ``Last-Event-ID`` 请求头（SSE 规范里是字符串）。

    非数字 / 负数 / 空值一律当作「没有游标」（不报错）：游标只是客户端自述的进度，格式可疑时
    按「从头读」处理并由 ``needs_resync`` 决定是否需要重新同步，**不**把畸形头变成 400——
    否则一个坏游标会让客户端再也订阅不上。

    判据必须是「ASCII 十进制 + 位数有界」，不能只用 ``str.isdigit()``：它对 Unicode 数字
    （``'²'`` 这类 latin-1 单字节就能塞进请求头的字符）为真，而 ``int()`` 会抛 ``ValueError``
    → 客户端可控的 500；超长数字串还会撞 CPython 3.11+ 的 ``int()`` 位数上限，同样 500。
    """
    raw = getattr(request, "headers", None)
    if raw is None:
        return None
    value = raw.get("last-event-id")
    if value is None:
        return None
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or len(text) > _MAX_EVENT_ID_DIGITS:
        return None
    return int(text)


def _build_run_endpoints(
    responses: Any,
    config: HttpServerConfig,
    service: HttpRunService,
) -> tuple[Any, Any, Any, Any]:
    """构造运行 API 的四个端点（创建 / 事件流 / 取消 / 会话快照）。

    以**具体类型**的 ``service`` 为参数（而不是让端点闭包捕获 ``Optional`` 再在体内断言）：
    「路由只在注入 service 时注册」这条前提写在签名里比写在断言里可靠，也让
    :func:`build_http_app` 的复杂度只反映路由装配本身（C901 的判据）。
    """

    async def create_run(request: Any) -> Any:
        """``POST /api/runs``：有界非空 prompt → 创建一次运行（单运行约束，不排队）。"""
        parsed, error = await _read_model(
            request,
            model=RunRequest,
            config=config,
            responses=responses,
            blank_code=HttpErrorCode.EMPTY_PROMPT,
        )
        if error is not None:
            return error
        try:
            record = await service.start_run(parsed.prompt)
        except HttpRunConflictError as exc:
            return _json_error(responses, HttpErrorCode.RUN_CONFLICT, str(exc), status_code=409)
        return responses.JSONResponse(
            RunStatusResponse(run_id=record.run_id, status=record.status).model_dump(mode="json"),
            status_code=201,
        )

    async def run_events(request: Any) -> Any:
        """``GET /api/runs/{run_id}/events``：SSE 订阅（只读；断线不取消运行）。"""
        run_id = str(request.path_params.get("run_id", ""))
        record = service.run(run_id)
        if record is None:
            return _json_error(responses, HttpErrorCode.UNKNOWN_RUN, "no such run", status_code=404)
        cursor = _parse_last_event_id(request)
        if service.needs_resync(record, cursor):
            # 游标早于缓冲窗口：**不**发一条「看起来连续」的流，明确要求重新同步（AD-4）。
            # 客户端应改拉 `/api/session` 快照，而不是把缺口当作没发生。
            return _json_error(
                responses,
                HttpErrorCode.RESYNC_REQUIRED,
                "event cursor is older than the buffered window; reload the session snapshot",
                status_code=409,
            )
        if service.subscriber_count(record) >= config.max_connections:
            return _json_error(
                responses,
                HttpErrorCode.RATE_LIMITED,
                "too many event subscribers for this run",
                status_code=429,
            )
        return responses.StreamingResponse(
            _sse_stream(service, record, cursor),
            media_type="text/event-stream",
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )

    async def cancel_run(request: Any) -> Any:
        """``DELETE /api/runs/{run_id}``：协作式取消指定运行（幂等；不触碰其它运行）。"""
        run_id = str(request.path_params.get("run_id", ""))
        record = await service.cancel_run(run_id)
        if record is None:
            return _json_error(responses, HttpErrorCode.UNKNOWN_RUN, "no such run", status_code=404)
        return responses.JSONResponse(
            RunStatusResponse(run_id=record.run_id, status=record.status).model_dump(mode="json")
        )

    async def session(request: Any) -> Any:  # noqa: ARG001
        """``GET /api/session``：进程内单用户会话的可展示快照（刷新后恢复用）。"""
        return responses.JSONResponse(service.session_snapshot().model_dump(mode="json"))

    return create_run, run_events, cancel_run, session


def _project_source(request: Any) -> str:
    """路径里的项目 id（不透明字符串；缺失/未知由注入的 console 判为 ``unknown_project``）。"""
    return str(request.path_params.get("project_id", ""))


def _loopback_error(responses: Any, request: Any) -> Any | None:
    """**写类**操作要求本机回环来源；非回环 → 403 ``loopback_required``（脊柱 §9）。

    判定复用 ``network.exposure.is_loopback_host``（含 IPv4 映射形式 ``::ffff:127.0.0.1``）。
    这是 defense-in-depth 而**不是认证**：能连上回环端口的本机进程可以伪造请求头。

    适用面：项目登记 / 重命名 / 移除（Story 50-2）与**配置写入**（Story 50-5 流水线第 2 步——那一步
    留在传输层，因为网络层不认识 ``Settings``，见 ``heagent.config_write`` 的模块 docstring）。
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", "") if client is not None else ""
    if is_loopback_host(str(host)):
        return None
    return _json_error(
        responses,
        HttpErrorCode.LOOPBACK_REQUIRED,
        "this change requires a loopback client",
        status_code=403,
    )


def _confirm_required(responses: Any, request: Any, *, action: str) -> Any | None:
    """危险操作的服务端确认闸门（缺 ``?confirm=true`` → 400 ``confirm_required``）。

    确认放在**服务端**而不只靠 UI：项目移除与会话删除都走这里，缺一即拒（story 50-2 AC6 /
    50-3 AC6 同一口径）。
    """
    if request.query_params.get("confirm") == "true":
        return None
    return _json_error(
        responses,
        HttpErrorCode.CONFIRM_REQUIRED,
        f"{action} requires confirm=true",
        status_code=400,
    )


def _build_project_endpoints(  # noqa: C901 - 四个端点闭包共享同一套分支（与 50-2 原实现同口径）
    responses: Any, console: ConsoleHandler, config: HttpServerConfig
) -> tuple[Any, ...]:
    """项目注册表的四条路由（Story 50-2），全部围绕注入的入口层 handler 构造。"""

    async def list_projects(request: Any) -> Any:  # noqa: ARG001
        try:
            result = await console.list_projects()
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_list_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def register_project(request: Any) -> Any:
        denied = _loopback_error(responses, request)
        if denied is not None:
            return denied
        parsed, error = await _read_model(request, model=ProjectRegisterRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.register_project(parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_register_failed")
        return responses.JSONResponse(result.model_dump(mode="json"), status_code=201)

    async def rename_project(request: Any) -> Any:
        parsed, error = await _read_model(request, model=ProjectRenameRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.rename_project(_project_source(request), parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_rename_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def remove_project(request: Any) -> Any:
        project_id = _project_source(request)
        denied = _confirm_required(responses, request, action="project removal")
        if denied is not None:
            return denied
        if project_id != "default":
            denied = _loopback_error(responses, request)
            if denied is not None:
                return denied
        try:
            if project_id != "default" and await console.project_has_inflight_run(project_id):
                return _json_error(
                    responses,
                    HttpErrorCode.PROJECT_BUSY,
                    "project has a run in progress",
                    status_code=409,
                )
            await console.remove_project(project_id)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_remove_failed")
        return responses.Response(status_code=204)

    return list_projects, register_project, rename_project, remove_project


def _build_session_endpoints(  # noqa: C901 - 六个端点闭包共享同一套分支（与 50-2 同口径）
    responses: Any, console: ConsoleHandler, config: HttpServerConfig
) -> tuple[Any, ...]:
    """会话 API 与项目内运行入口（Story 50-3）：五条会话路由 + 一条运行入口。

    网络层在这里只做三件事：**校验会话 id 形态**（非法即回 ``invalid_session_id``，不触碰文件
    系统）、把不透明 id 交给注入的 console、把稳定码映射为状态码。会话 JSON 的解析、标题派生、
    在途判定与项目路径解析一律在入口层（脊柱 I1 的「网络层不认识项目」）。
    """

    def session_source(request: Any) -> tuple[str, Any | None]:
        """路径里的会话 id（已过形态校验；错误路径回 ``("", error)``，调用方必须先短路 error）。

        形态校验放在**网络层**（非法即 ``invalid_session_id``，且**不触碰文件系统**）；入口层还有第二道
        同样的守卫（``cli.http._guarded_session_id``），两点各自 fail-closed。
        """
        session_id = str(request.path_params.get("session_id", ""))
        if not is_valid_session_id(session_id):
            return "", _json_error(
                responses,
                HttpErrorCode.INVALID_SESSION_ID,
                "session id is invalid",
                status_code=400,
            )
        return session_id, None

    async def list_sessions(request: Any) -> Any:
        try:
            result = await console.list_sessions(_project_source(request))
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_list_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def create_session(request: Any) -> Any:
        parsed, error = await _read_model(request, model=SessionCreateRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.create_session(_project_source(request), parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_create_failed")
        return responses.JSONResponse(result.model_dump(mode="json"), status_code=201)

    async def get_session(request: Any) -> Any:
        session_id, error = session_source(request)
        if error is not None:
            return error
        try:
            result = await console.get_session(_project_source(request), session_id)
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_read_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def rename_session(request: Any) -> Any:
        session_id, error = session_source(request)
        if error is not None:
            return error
        parsed, error = await _read_model(request, model=SessionRenameRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.rename_session(_project_source(request), session_id, parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_rename_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def delete_session(request: Any) -> Any:
        """删除会话：危险操作，确认由**服务端**把关（与会话 / 项目删除同一口径）。"""
        session_id, error = session_source(request)
        if error is not None:
            return error
        denied = _confirm_required(responses, request, action="session removal")
        if denied is not None:
            return denied
        try:
            await console.delete_session(_project_source(request), session_id)
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_delete_failed")
        return responses.Response(status_code=204)

    async def create_project_run(request: Any) -> Any:
        """``POST /api/projects/{id}/runs``：项目内运行，``run_id`` 复用既有 SSE/取消端点。"""
        parsed, error = await _read_model(
            request,
            model=ProjectRunRequest,
            config=config,
            responses=responses,
            blank_code=HttpErrorCode.EMPTY_PROMPT,
        )
        if error is not None:
            return error
        try:
            result = await console.start_project_run(_project_source(request), parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_run_failed")
        return responses.JSONResponse(result.model_dump(mode="json"), status_code=201)

    async def session_malformed(request: Any) -> Any:  # noqa: ARG001 - 端点的固定签名
        """会话路径下多出来的段 ⇒ 会话 id 必然非法（AC7：拒绝且不触碰 console / 文件系统）。

        必须存在这条兜底路由：``%2F`` 会在**路由之前**被解码成 ``/``，于是 ``sessions/..%2Fescape``
        落成 5 段路径——不兜底就回 404 ``not_found``，与 AC7 承诺的稳定码 ``invalid_session_id`` 不符
        （且把「路由存不存在」的差异暴露给客户端）。注册顺序在具体会话路由**之后**，因此绝不会遮蔽
        正常的单段 id。
        """
        return _json_error(responses, HttpErrorCode.INVALID_SESSION_ID, "session id is invalid", status_code=400)

    return (
        list_sessions,
        create_session,
        get_session,
        rename_session,
        delete_session,
        create_project_run,
        session_malformed,
    )


def _build_config_endpoint(responses: Any, console: ConsoleHandler, config: HttpServerConfig) -> tuple[Any, Any]:
    """配置面板的两条路由（``GET`` 只读 / ``PUT`` 写入；Story 50-4 + 50-5）。

    网络层只把不透明的项目 id 与协议模型交给注入的 console，并把稳定错误码映射为状态码；分组、
    来源求解、白名单、保真写、备份与审计一律留在入口层与顶层模块（脊柱 I1：网络层不认识配置）。

    ``PUT`` 另外要求本机回环来源（流水线第 2 步；非回环时**不触碰** console ⇒ 文件 / 备份 / 审计
    三者都不会变，AC10）。
    """

    async def get_project_config(request: Any) -> Any:
        try:
            result = await console.get_project_config(_project_source(request))
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_config_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def update_project_config(request: Any) -> Any:
        """``PUT /api/projects/{id}/config``：白名单内的项目级非凭证配置，fail-closed 写入。"""
        denied = _loopback_error(responses, request)
        if denied is not None:
            return denied
        parsed, error = await _read_model(request, model=ConfigWriteRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.update_project_config(_project_source(request), parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_config_write_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    return get_project_config, update_project_config


def _build_dialog_endpoint(responses: Any, console: ConsoleHandler) -> Any:
    """``POST /api/dialogs/pick-directory``：在**服务端所在机器**弹出原生目录选择窗口（Story 50-8）。

    三条边界（都不是安全边界）：

    - **回环来源**：非回环 → 403 ``loopback_required``（复用 :func:`_loopback_error`）。远程客户端不该让
      服务机弹窗——那是窗口注入 / 骚扰面，而且弹在别人机器上的窗口对调用者毫无用处；
    - **只回用户明确选中的那一个目录**：取消 / 超时 / 后端脏值一律 ``cancelled=true``，**不回传任何
      目录列表**（这里没有目录浏览能力）；
    - **单在途**由入口层持有（原生窗口不能叠着开），并发 → 409 ``dialog_busy``。

    用 ``POST`` 而不是 ``GET``：避免被 ``<img>`` / 链接意外触发（与写类端点同一姿态）。
    """

    async def pick_directory(request: Any) -> Any:
        denied = _loopback_error(responses, request)
        if denied is not None:
            return denied
        try:
            result = await console.pick_directory()
        except Exception as exc:
            return _console_error_response(responses, exc, event="dialog_pick_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    return pick_directory


def build_http_app(
    config: HttpServerConfig,
    *,
    version: str,
    run_service: HttpRunService | None = None,
    console: ConsoleHandler | None = None,
) -> ASGIApp:
    """构造网页入口的 ASGI 应用（健康检查 + 运行 API/SSE + 包内静态页 + 安全头）。

    ``version`` 由入口层注入（来自 ``heagent.__version__``）：传输层因此不需要知道版本从哪来，
    也不需要在导入期触碰包元数据。``run_service`` 是**注入的运行服务**（AD-1 的接缝）——为 ``None``
    时不注册 ``/api/runs*``、``/api/session`` 或 ``/api/projects*``（那些路径回 404），Story 49-1 的用法因此保持不变。
    错误响应一律走 :func:`_json_error`，异常细节只进服务端日志。
    """
    applications = _require_module("starlette.applications")
    responses = _require_module("starlette.responses")
    routing = _require_module("starlette.routing")
    starlette_exceptions = _require_module("starlette.exceptions")

    async def health(request: Any) -> Any:  # noqa: ARG001 - 端点的固定签名
        return responses.JSONResponse(
            HealthResponse(version=version).model_dump(mode="json"),
        )

    def asset_response(name: str) -> Any:
        """读包内资源并回响应；资源缺失（如 wheel 漏打）时回稳定 500，不吐 traceback。"""
        try:
            payload = read_web_asset(name)
        except (KeyError, OSError, ModuleNotFoundError):
            _safe_log(logging.ERROR, "http event=asset_unavailable asset=%s", name)
            return _json_error(
                responses,
                HttpErrorCode.SERVER_ERROR,
                "built-in page resource is unavailable",
                status_code=500,
            )
        return responses.Response(
            payload,
            media_type=_WEB_ASSETS[name],
            headers={"cache-control": "no-cache"},
        )

    async def index(request: Any) -> Any:  # noqa: ARG001 - 端点的固定签名
        return asset_response(_INDEX_ASSET)

    async def asset(request: Any) -> Any:
        name = str(request.path_params.get("asset", ""))
        if name not in _WEB_ASSETS:
            return _json_error(responses, HttpErrorCode.NOT_FOUND, "no such resource", status_code=404)
        return asset_response(name)

    async def http_exception(request: Any, exc: Any) -> Any:  # noqa: ARG001
        status = getattr(exc, "status_code", 500)
        if status == 405:
            return _json_error(
                responses,
                HttpErrorCode.METHOD_NOT_ALLOWED,
                "method not allowed for this endpoint",
                status_code=405,
            )
        if status == 404:
            return _json_error(responses, HttpErrorCode.NOT_FOUND, "no such endpoint", status_code=404)
        return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=int(status))

    async def server_error(request: Any, exc: Any) -> Any:  # noqa: ARG001
        # 详细 traceback 只进服务端 error 日志；客户端拿固定文案。
        _safe_log(logging.ERROR, "http event=request_error", exc_info=True)
        return _json_error(responses, HttpErrorCode.SERVER_ERROR, "internal server error", status_code=500)

    routes = [
        routing.Route(_HEALTH_PATH, endpoint=health, methods=["GET"]),
        routing.Route("/", endpoint=index, methods=["GET"]),
    ]
    if run_service is not None:
        create_run, run_events, cancel_run, session_endpoint = _build_run_endpoints(responses, config, run_service)
        routes.extend(
            [
                routing.Route(_RUNS_PATH, endpoint=create_run, methods=["POST"]),
                routing.Route(_RUN_EVENTS_PATH, endpoint=run_events, methods=["GET"]),
                routing.Route(_RUN_DETAIL_PATH, endpoint=cancel_run, methods=["DELETE"]),
                routing.Route(_SESSION_PATH, endpoint=session_endpoint, methods=["GET"]),
            ]
        )
    if console is not None:
        list_projects, register_project, rename_project, remove_project = _build_project_endpoints(
            responses, console, config
        )
        (
            list_sessions,
            create_session,
            get_session,
            rename_session,
            delete_session,
            create_project_run,
            session_malformed,
        ) = _build_session_endpoints(responses, console, config)
        project_config, project_config_write = _build_config_endpoint(responses, console, config)
        pick_directory = _build_dialog_endpoint(responses, console)
        routes.extend(
            [
                routing.Route(_PROJECTS_PATH, endpoint=list_projects, methods=["GET"]),
                routing.Route(_PROJECTS_PATH, endpoint=register_project, methods=["POST"]),
                routing.Route(_PROJECT_PATH, endpoint=rename_project, methods=["PATCH"]),
                routing.Route(_PROJECT_PATH, endpoint=remove_project, methods=["DELETE"]),
                routing.Route(_PROJECT_SESSIONS_PATH, endpoint=list_sessions, methods=["GET"]),
                routing.Route(_PROJECT_SESSIONS_PATH, endpoint=create_session, methods=["POST"]),
                routing.Route(_PROJECT_SESSION_PATH, endpoint=get_session, methods=["GET"]),
                routing.Route(_PROJECT_SESSION_PATH, endpoint=rename_session, methods=["PATCH"]),
                routing.Route(_PROJECT_SESSION_PATH, endpoint=delete_session, methods=["DELETE"]),
                # 兜底路由**必须在具体会话路由之后**注册：先匹配到具体的单段 id 语义。
                routing.Route(
                    _PROJECT_SESSION_EXTRA_PATH,
                    endpoint=session_malformed,
                    methods=["GET", "POST", "PATCH", "DELETE"],
                ),
                routing.Route(_PROJECT_RUNS_PATH, endpoint=create_project_run, methods=["POST"]),
                routing.Route(_PROJECT_CONFIG_PATH, endpoint=project_config, methods=["GET"]),
                # 写入通道（Story 50-5）：与 GET 同一路径、不同方法（Starlette 按 method 匹配）。
                routing.Route(_PROJECT_CONFIG_PATH, endpoint=project_config_write, methods=["PUT"]),
                # 原生目录选择（Story 50-8）：非项目作用域 + 回环门 + 单在途（入口层持有）。
                routing.Route(_DIALOG_PICK_PATH, endpoint=pick_directory, methods=["POST"]),
            ]
        )
    routes.append(routing.Route("/{asset}", endpoint=asset, methods=["GET"]))
    app = applications.Starlette(
        routes=routes,
        exception_handlers={
            starlette_exceptions.HTTPException: http_exception,
            Exception: server_error,
        },
    )
    # 包装顺序（由外到内）：安全头（保证连被拒的响应也带）→ 请求观测 → 同源防线 → 应用路由。
    guarded = _OriginGuardMiddleware(app, hosts=_allowed_hosts(config), ports=_allowed_ports(config))
    logged = _AccessLogMiddleware(guarded)
    return _SecurityHeadersMiddleware(logged, _SECURITY_HEADERS)


def _probe_host(host: str) -> str:
    """就绪探测用的连接地址：通配绑定（``0.0.0.0`` / ``::`` / 空串）改用回环地址。

    连 ``0.0.0.0`` 在多数平台上是未定义/失败行为，而「通配绑定是否真的能服务」完全可以经
    回环地址验证（通配包含回环）。
    """
    candidate = host.strip()
    if candidate in _IPV6_WILDCARDS:
        return "::1"
    if candidate in _WILDCARD_HOSTS:
        return "127.0.0.1"
    return candidate


class HttpServer:
    """一个 HTTP listener 的所有者：绑定、服务、有界关闭。

    与 :class:`~heagent.network.tcp_server.TcpServer` 保持同一 API 形状（``start`` /
    ``serve_forever`` / ``close``），入口层的装配代码因此可以逐行对照。
    """

    def __init__(
        self,
        config: HttpServerConfig,
        *,
        version: str,
        run_service: HttpRunService | None = None,
        console: ConsoleHandler | None = None,
    ) -> None:
        self.config = config
        self.version = version
        self.run_service = run_service
        self.console = console
        self._app: ASGIApp | None = None
        self._server: Any = None
        # 生命周期锁与「已关闭」标记：``close()`` 必须**等到**收尾真正完成才返回。只用一个布尔
        # 标记的话，并发/重复调用会拿到「已关闭」的假成功，而 listener 仍在接受并服务请求
        # （与 ``TcpServer._lifecycle_lock`` 同形）。
        self._lifecycle_lock = asyncio.Lock()
        self._closed = False

    @property
    def app(self) -> ASGIApp:
        """ASGI 应用（延迟构造一次；测试可用 ASGI transport 直接打，无需真实 listener）。"""
        if self._app is None:
            self._app = build_http_app(
                self.config, version=self.version, run_service=self.run_service, console=self.console
            )
        return self._app

    @property
    def port(self) -> int:
        """实际监听端口：``port=0``（随机端口）时只有绑定后才能读出来。"""
        for listener in getattr(self._server, "servers", None) or ():
            for sock in getattr(listener, "sockets", None) or ():
                with contextlib.suppress(OSError):
                    return int(sock.getsockname()[1])
        return self.config.port

    @property
    def address(self) -> str:
        """人类可读的监听地址（stderr 公告与诊断用）。"""
        return f"{self.config.host}:{self.port}"

    async def start(self) -> None:
        """绑定地址并确认 ``/api/health`` **真的可服务**，否则抛 :class:`HttpStartupError`。

        Uvicorn 在绑定失败时不是抛 ``OSError`` 而是 ``sys.exit(STARTUP_FAILURE)``（见其
        ``Server.startup`` 的 standard-case 分支），所以这里同时接住 ``SystemExit`` 与
        ``OSError``，并统一转成可诊断错误——**绝不能**让「端口被占用」变成进程静默退出或
        「看似在监听」的半启动状态。
        """
        if self._server is not None:
            return
        uvicorn = _require_module("uvicorn")
        self._closed = False
        server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=self.config.host,
                port=self.config.port,
                lifespan="on",
                # log_config=None：**不**调用 dictConfig —— Uvicorn 默认配置会重写整个 logging
                # 配置并禁用既有 logger，把 HeAgent 的日志通道一起关掉。
                log_config=None,
                # access 日志由本模块的结构化日志取代：Uvicorn 的 access 行会带上完整路径与
                # 查询串，而 AD-9 要求日志只含不透明的 request/run id、状态与耗时。
                access_log=False,
                server_header=False,
                # 绝不信任 forwarded-* 头（AD-6）：同源判定必须基于真实 listener 地址。
                proxy_headers=False,
                limit_concurrency=self.config.max_connections + _CONCURRENCY_PROBE_RESERVE,
                # 关闭时连接排空的硬上界（Uvicorn 默认 None = 无限等待）。
                timeout_graceful_shutdown=max(1, math.ceil(self.config.shutdown_timeout)),
            )
        )
        try:
            # uvicorn 的 ``Server.startup()`` 假定 ``lifespan`` 已由 ``Server._serve()`` 建好，而我们
            # 刻意绕过 ``serve()``（它会把绑定错误转成 ``sys.exit``，还会抢进程信号——信号归 CLI
            # 所有，见 AD-5），因此照它的顺序把这两步补齐。``Config.load()`` 对「传进来的 ASGI
            # 对象」只是打标记，不会重新 import。
            if not server.config.loaded:
                server.config.load()
            server.lifespan = server.config.lifespan_class(server.config)
            await server.startup()
        except SystemExit as exc:
            raise HttpStartupError(f"HTTP server could not bind {self.address}: address unavailable") from exc
        except OSError as exc:
            raise HttpStartupError(f"HTTP server could not bind {self.address}: {exc}") from exc
        self._server = server
        _safe_log(logging.INFO, "http event=started address=%s", self.address)
        warning = exposure_warning(self.config.host)
        if warning is not None:
            _safe_log(logging.WARNING, "http event=exposed host=%s %s", self.config.host, warning)
        if not await self._probe_health():
            # 绑定成功但应用不可服务 ⇒ 回滚，绝不对外宣称「已启动」。
            self._server = None
            await self._stop_listener(server)
            raise HttpStartupError(f"HTTP server started but {_HEALTH_PATH} is not servable")
        if self.run_service is not None:
            # 重新武装运行入口：``close()`` 会把「停止接收」标记置上且不可逆，于是
            # ``close()`` → ``start()`` 之后健康检查照常 200，而每次 ``POST /api/runs`` 都被
            # 409 ``run_conflict``（`server is shutting down`）拒绝——正是 AD-5 要消除的
            # 「看起来正常但不可用」。
            self.run_service.reopen()

    async def serve_forever(self) -> None:
        """阻塞式服务循环；Uvicorn 主循环退出（``should_exit``）或异常时返回/抛出。"""
        server = self._server
        if server is None:
            raise RuntimeError("HTTP server is not started")
        await server.main_loop()

    async def close(self) -> None:
        """停止接收新请求、终结在途运行、关闭 listener，全程有界；幂等。

        关闭顺序按 AD-5：**停止接收（service 拒绝新 run）→ 使在途运行进入终态并发出终态事件 →
        关闭订阅 → 关闭 listener → 有界等待**。Uvicorn 的 ``shutdown()`` 负责最后两步（关闭监听、
        请求既有连接收尾，受 ``timeout_graceful_shutdown`` 约束），本方法另加一层 ``wait_for`` 兜底，
        保证即使框架内部出现无界等待也不会把 CLI 退出卡死。

        幂等指「重复/并发调用都等到**同一次**收尾完成」：后到者持锁排队，不会在本方法仍在等待
        在途运行时提前返回一个「已关闭」的假成功。收尾中途被取消（如 Ctrl+C 二次打断）时不置
        ``_closed``，让下一次调用可以接着收尾。
        """
        async with self._lifecycle_lock:
            if self._closed:
                return
            service = self.run_service
            if service is not None:
                await service.close()
            server, self._server = self._server, None
            if server is None:
                self._closed = True
                return
            server.should_exit = True
            await self._stop_listener(server)
            self._closed = True

    async def _stop_listener(self, server: Any) -> None:
        budget = self.config.shutdown_timeout + _SHUTDOWN_GRACE_MARGIN
        try:
            await asyncio.wait_for(server.shutdown(), timeout=budget)
        except TimeoutError:
            _safe_log(logging.WARNING, "http event=shutdown_timeout phase=listener")
            server.force_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.shutdown(), timeout=budget)
        except asyncio.CancelledError:
            raise
        except Exception:
            _safe_log(logging.WARNING, "http event=shutdown_failed", exc_info=True)

    async def _probe_health(self) -> bool:
        """用**真实 TCP 连接**打通一次 ``/api/health``（AD-5 的就绪判据）。

        刻意用标准库而不是 HTTP 客户端：``network/`` 的依赖面里没有 httpx，而「listener 是否
        真的能服务」这件事用一次手写 `GET` 就能验证——返回 200 即通过，其余（连接失败、超时、
        5xx、畸形响应行）一律视为未就绪。
        """
        host = _probe_host(self.config.host)
        port = self.port
        started_at = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=_PROBE_TIMEOUT)
        except (OSError, TimeoutError) as exc:
            _safe_log(logging.WARNING, "http event=probe_failed phase=connect error=%r", exc)
            return False
        try:
            # IPv6 字面量的 authority 必须带方括号：``::1:8766`` 会被拆成 host ``::1`` +
            # port 8766（恰好侥幸通过），而 ``[::1]:8766`` 才是浏览器与校验两侧都认的写法。
            authority = f"[{host}]" if ":" in host else host
            request = (f"GET {_HEALTH_PATH} HTTP/1.1\r\nhost: {authority}:{port}\r\nconnection: close\r\n\r\n").encode()
            writer.write(request)
            await writer.drain()
            status_line = await asyncio.wait_for(reader.readline(), timeout=_PROBE_TIMEOUT)
        except (OSError, TimeoutError) as exc:
            _safe_log(logging.WARNING, "http event=probe_failed phase=request error=%r", exc)
            return False
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        ok = b" 200 " in status_line
        if not ok:
            _safe_log(logging.WARNING, "http event=probe_failed phase=status status=%r", status_line[:32])
        else:
            _safe_log(
                logging.DEBUG,
                "http event=probe_ok elapsed_ms=%d",
                int((time.perf_counter() - started_at) * 1000),
            )
        return ok


__all__ = [
    "HttpDependencyError",
    "HttpRequestTooLargeError",
    "HttpRunConflictError",
    "HttpRunService",
    "HttpServer",
    "HttpServerConfig",
    "HttpStartupError",
    "RunEventPublisher",
    "build_http_app",
    "format_sse",
    "read_web_asset",
]
