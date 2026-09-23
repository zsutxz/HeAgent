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
import logging
import math
import time
import uuid
from collections import OrderedDict, deque
from importlib import resources
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from heagent.network.exposure import exposure_warning
from heagent.network.http_protocol import (
    GENERIC_ERROR_MESSAGE,
    TERMINAL_RUN_STATUSES,
    HealthResponse,
    HttpErrorCode,
    RunCreatedResponse,
    RunEventKind,
    RunEventPayload,
    RunOutcome,
    RunRequest,
    RunStatus,
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
_RUN_EVENTS_PATH = "/api/runs/{run_id}/events"
_SESSION_PATH = "/api/session"

# 通配绑定地址：就绪探测改走回环（见 :func:`_probe_host`）。这里**只识别**，不在此绑定。
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "*"})  # noqa: S104 - 识别通配地址，非绑定
_IPV6_WILDCARDS = frozenset({"::", "[::]"})

# 就绪探测与关闭排空的预算（秒）。探测是进程内回环请求，正常在毫秒级返回。
_PROBE_TIMEOUT = 5.0
_SHUTDOWN_GRACE_MARGIN = 1.0


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
        # 有界 ring buffer：越过窗口的重连（49-4）据此判定 resync_required。
        self.events: deque[RunEventPayload] = deque(maxlen=buffer_size)
        self.subscribers: set[asyncio.Queue[RunEventPayload | None]] = set()
        self._next_seq = 1

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    def append(self, kind: RunEventKind, **fields: Any) -> RunEventPayload:
        """追加一条事件：分配单调 ``seq``、入缓冲、广播给当前订阅者（同步，无 ``await``）。"""
        payload = RunEventPayload(kind=kind, seq=self._next_seq, **fields)
        self._next_seq += 1
        self.events.append(payload)
        for queue in list(self.subscribers):
            queue.put_nowait(payload)
        return payload

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
        self._tasks: set[asyncio.Task[None]] = set()
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
        task: asyncio.Task[None] = asyncio.create_task(self._execute(record), name=f"heagent-http-run-{record.run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return record

    async def close(self) -> None:
        """停止接收新运行、使在途运行进入终态、等待运行任务退出（有界，AD-5 的关闭序列）。

        取消运行任务 ⇒ ``_execute`` 的 ``CancelledError`` 分支把记录置为 ``CANCELLED`` 并发出
        终态事件（关停赢得的运行一律记 ``cancelled``）。超时后仍会返回：``asyncio`` 无法强杀
        忽略取消的任务，残留由容器退出兜底。
        """
        self._closing = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=self.config.shutdown_timeout)
            if pending:
                _safe_log(logging.WARNING, "http event=run_shutdown_timeout pending=%d", len(pending))
        self._tasks.clear()

    # ---- 运行执行 ----

    async def _execute(self, record: _RunRecord) -> None:
        """跑一次运行并把结果写进记录（唯一写终态的地方，AD-10）。"""
        try:
            outcome = await self._executor(record.prompt, RunEventPublisher(record))
        except asyncio.CancelledError:
            if record.claim_terminal(RunStatus.CANCELLED):
                record.append(RunEventKind.CANCELLED, message="run cancelled")
                record.close_subscribers()
            raise
        except Exception as exc:
            if record.claim_terminal(RunStatus.FAILED):
                record.error_message = _client_error_message(exc)
                record.append(RunEventKind.ERROR, message=record.error_message)
                record.close_subscribers()
            _safe_log(logging.WARNING, "http event=run_failed run_id=%s", record.run_id)
        else:
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
        """记住运行记录；超出 ``run_history_size`` 时淘汰最旧的（之后按其 id 订阅得 ``unknown_run``）。"""
        self._runs[record.run_id] = record
        while len(self._runs) > self.config.run_history_size:
            self._runs.popitem(last=False)

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
    ) -> AsyncIterator[RunEventPayload]:
        """SSE 的事件源：先重放缓冲，再跟随实时事件；终态事件之后流立即结束（AD-4）。

        - ``last_event_id``（``Last-Event-ID``）只重放**严格大于**它的序号；
        - 订阅者只读：断线只移除本队列，**绝不**取消运行；
        - 复位扫描（resync 判定）在 49-4 接入调用方——那里才有「游标早于窗口」的语义。
        """
        queue: asyncio.Queue[RunEventPayload | None] = asyncio.Queue()
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
                item = await queue.get()
                if item is None:
                    return
                if last_event_id is not None and item.seq <= last_event_id:
                    continue
                yield item
        finally:
            record.subscribers.discard(queue)


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


async def _sse_stream(service: HttpRunService, record: _RunRecord) -> AsyncIterator[bytes]:
    """SSE 响应体：只读订阅运行事件；订阅者清理由生成器的 ``finally`` 保证（断线即回收）。"""
    async for payload in service.stream_events(record):
        yield format_sse(payload)


def _build_run_endpoints(
    responses: Any,
    config: HttpServerConfig,
    service: HttpRunService,
) -> tuple[Any, Any, Any]:
    """构造运行 API 的三个端点（``POST /api/runs`` / 事件流 / 会话快照）。

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
            RunCreatedResponse(run_id=record.run_id, status=record.status).model_dump(mode="json"),
            status_code=201,
        )

    async def run_events(request: Any) -> Any:
        """``GET /api/runs/{run_id}/events``：SSE 订阅（只读；断线不取消运行）。"""
        run_id = str(request.path_params.get("run_id", ""))
        record = service.run(run_id)
        if record is None:
            return _json_error(responses, HttpErrorCode.UNKNOWN_RUN, "no such run", status_code=404)
        return responses.StreamingResponse(
            _sse_stream(service, record),
            media_type="text/event-stream",
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )

    async def session(request: Any) -> Any:  # noqa: ARG001
        """``GET /api/session``：进程内单用户会话的可展示快照（刷新后恢复用）。"""
        return responses.JSONResponse(service.session_snapshot().model_dump(mode="json"))

    return create_run, run_events, session


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
        create_run, run_events, session_endpoint = _build_run_endpoints(responses, config, run_service)
        routes.extend(
            [
                routing.Route(_RUNS_PATH, endpoint=create_run, methods=["POST"]),
                routing.Route(_RUN_EVENTS_PATH, endpoint=run_events, methods=["GET"]),
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
    return _SecurityHeadersMiddleware(app, _SECURITY_HEADERS)


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
        self._closing = False

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
        self._closing = False
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
                limit_concurrency=self.config.max_connections,
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
        """
        if self._closing:
            return
        self._closing = True
        service = self.run_service
        if service is not None:
            await service.close()
        server, self._server = self._server, None
        if server is None:
            return
        server.should_exit = True
        await self._stop_listener(server)

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
            request = (f"GET {_HEALTH_PATH} HTTP/1.1\r\nhost: {host}:{port}\r\nconnection: close\r\n\r\n").encode()
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
