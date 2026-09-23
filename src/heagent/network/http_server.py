"""ASGI HTTP 传输层：静态资源、安全响应头与有界生命周期（Epic 49）。

**职责边界（AD-1）**：本模块只做 HTTP 协议与生命周期——路由、安全响应头、包内静态资源、
listener 的 start/close。它**不**构造 Agent：任何 Agent 能力都由入口层（``cli_http.py``）以
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
from heagent.network.http_protocol import (
    GENERIC_ERROR_MESSAGE,
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

    # 入口层交回的可调用对象：把 prompt 跑成 Agent 运行，并通过 publisher 推事件。
    #
    # ``network/`` 只认这个形状，不认 ``AgentLoop``——这是 AD-1（传输层不构造 Agent）与 AD-7
    # （治理链由既有 Agent 路径负责）的接缝；实现见入口层 ``cli_http.HttpAgentHandler``。
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
    max_inflight_runs: int = Field(default=1, ge=1)
    max_request_bytes: int = Field(default=65_536, ge=1)
    event_buffer_size: int = Field(default=512, ge=1)
    run_history_size: int = Field(default=64, ge=1)
    request_timeout: float = Field(default=300.0, gt=0, allow_inf_nan=False)
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

    def __init__(self, run_id: str, prompt: str, *, buffer_size: int) -> None:
        self.run_id = run_id
        self.prompt = prompt
        self.status = RunStatus.RUNNING
        self.outcome: RunOutcome | None = None
        self.error_message: str | None = None
        self.created_at = time.perf_counter()
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
        """追加一条事件：分配单调 ``seq``、入缓冲、广播给当前订阅者（同步，无 ``await``）。"""
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

    async def start_run(self, prompt: str) -> _RunRecord:
        """创建并启动一次运行；名额已满或正在关闭 → :class:`HttpRunConflictError`（不排队）。"""
        if self._closing:
            raise HttpRunConflictError("server is shutting down")
        if len(self._active) >= self.config.max_inflight_runs:
            raise HttpRunConflictError("another run is already in flight")
        record = _RunRecord(uuid.uuid4().hex, prompt, buffer_size=self.config.event_buffer_size)
        self._store(record)
        self._active.add(record.run_id)
        self._current_run_id = record.run_id
        _safe_log(logging.INFO, "http event=run_started run_id=%s", record.run_id)
        task: asyncio.Task[None] = asyncio.create_task(self._execute(record), name=f"heagent-http-run-{record.run_id}")
        self._run_tasks[record.run_id] = task

        def _on_done(finished: asyncio.Task[None]) -> None:
            self._finalize(finished, record.run_id)

        task.add_done_callback(_on_done)
        return record

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

    async def _execute(self, record: _RunRecord) -> None:
        """跑一次运行并把结果写进记录（唯一写终态的地方，AD-10）。

        超时（``HTTP_REQUEST_TIMEOUT``）与取消都经这里的终态转换收口：**第一个**拿到终态的转换
        获胜，只发一条终态事件，并且在 ``finally`` 里归还唯一的在途名额。

        ``asyncio.timeout`` 只能**请求**取消：吞掉 ``CancelledError`` 的 executor（长工具 / 子代理
        可能如此）会让块正常返回，此时时限并未真正生效——终态仍按实际结果走，但必须留下观测痕迹。
        ``deadline.expired()`` 因此承担两件事：区分「本模块的时限到了」与「上游自己抛的
        ``TimeoutError``」，以及在超时被忽略时留下 ``event=timeout_ignored``。
        """
        deadline = asyncio.timeout(self.config.request_timeout)
        try:
            async with deadline:
                outcome = await self._executor(record.prompt, RunEventPublisher(record))
        except asyncio.CancelledError:
            if record.claim_terminal(RunStatus.CANCELLED):
                record.append(RunEventKind.CANCELLED, message="run cancelled")
                record.close_subscribers()
            raise
        except TimeoutError as exc:
            if deadline.expired():
                if record.claim_terminal(RunStatus.TIMED_OUT):
                    record.append(RunEventKind.TIMED_OUT, message="run exceeded the configured time limit")
                    record.close_subscribers()
            else:
                # 运行内部（provider / 网络 / MCP ping）自己抛的 TimeoutError 不是本模块的时限：
                # 归因保持原样，否则运维会按「超过配置时限」去排查一个 100ms 就失败的运行。
                _safe_log(logging.ERROR, "http event=run_failed run_id=%s", record.run_id, exc_info=True)
                if record.claim_terminal(RunStatus.FAILED):
                    record.error_message = _client_error_message(exc)
                    record.append(RunEventKind.ERROR, message=record.error_message)
                    record.close_subscribers()
        except Exception as exc:
            # 运行是后台任务，异常不会走 Starlette / Uvicorn 的 traceback 通道：诊断细节只进服务端
            # 日志（客户端拿脱敏文案），否则真实缺陷的栈会被彻底丢掉。
            _safe_log(logging.ERROR, "http event=run_failed run_id=%s", record.run_id, exc_info=True)
            if record.claim_terminal(RunStatus.FAILED):
                record.error_message = _client_error_message(exc)
                record.append(RunEventKind.ERROR, message=record.error_message)
                record.close_subscribers()
        else:
            if deadline.expired():
                # 时限已过但 executor 吞掉取消正常返回：终态按实际结果，但「时限没生效」必须可见。
                _safe_log(
                    logging.WARNING,
                    "http event=timeout_ignored run_id=%s elapsed_ms=%d",
                    record.run_id,
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
        """终态 → 会话的唯一 reducer：只投影成功完成运行的 prompt 与最终回答（AD-3）。"""
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
        try:
            raw = await _read_body(request, limit=config.max_request_bytes)
        except HttpRequestTooLargeError:
            return _json_error(
                responses,
                HttpErrorCode.REQUEST_TOO_LARGE,
                "request body exceeds the configured limit",
                status_code=413,
            )
        try:
            parsed = RunRequest.model_validate_json(raw)
        except ValidationError as exc:
            messages = [str(error.get("msg", "")) for error in exc.errors()]
            code = (
                HttpErrorCode.EMPTY_PROMPT
                if any("blank" in message for message in messages)
                else HttpErrorCode.INVALID_REQUEST
            )
            return _json_error(responses, code, "request body is invalid", status_code=400)
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


def build_http_app(config: HttpServerConfig, *, version: str, run_service: HttpRunService | None = None) -> ASGIApp:
    """构造网页入口的 ASGI 应用（健康检查 + 运行 API/SSE + 包内静态页 + 安全头）。

    ``version`` 由入口层注入（来自 ``heagent.__version__``）：传输层因此不需要知道版本从哪来，
    也不需要在导入期触碰包元数据。``run_service`` 是**注入的运行服务**（AD-1 的接缝）——为 ``None``
    时不注册 ``/api/runs*`` 与 ``/api/session``（那些路径回 404），Story 49-1 的用法因此保持不变。
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

    def __init__(self, config: HttpServerConfig, *, version: str, run_service: HttpRunService | None = None) -> None:
        self.config = config
        self.version = version
        self.run_service = run_service
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
            self._app = build_http_app(self.config, version=self.version, run_service=self.run_service)
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
