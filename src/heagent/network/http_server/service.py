"""进程内运行服务：运行生命周期、名额、看门狗与 SSE 事件源（Story 62.1 自 ``network/http_server.py`` 拆出）。

:class:`HttpRunService` 是 AD-3 的唯一所有者——单运行名额（按项目各自生效）、每 run 独立
executor、会话投影只有一条路径；时限看门狗与取消归因也收在这里。

``__all__`` 显式列出包内公开名：包级再导出（``__init__.py``）与 exception 快照
（``scripts/contract_snapshot.py``）都以「定义模块的 ``__all__``」为收录依据。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from heagent.network.event_stream_hub import WsRegistry
from heagent.network.http_protocol import (
    GENERIC_ERROR_MESSAGE,
    SSE_HEARTBEAT_SECONDS,
    HttpErrorCode,
    HttpRunConflictError,
    RunEventKind,
    RunStatus,
    SessionMessage,
    SessionResponse,
    clip_text,
    cursor_out_of_window,
    replay_then_follow,
    sanitize_message,
)
from heagent.pub.safe_logging import safe_log

from .records import RunEventPublisher, _RunRecord

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from heagent.network.http_protocol import RunEventPayload, RunOutcome

    from .config import HttpServerConfig

    # 入口层交回的可调用对象：把 prompt 跑成 Agent 运行，并通过 publisher 推事件。
    #
    # ``network/`` 只认这个形状，不认 ``AgentLoop``——传输层不构造 Agent，治理链由既有
    # Agent 路径负责；实现见入口层 ``cli.http.HttpAgentHandler``。
    RunExecutor = Callable[[str, "RunEventPublisher"], Awaitable[RunOutcome]]

logger = logging.getLogger("heagent.network.http_server")

__all__ = ["HttpRunService"]


def _client_error_message(exc: BaseException) -> str:
    """把运行异常收敛成**有界、脱敏、非空**的客户端文案。

    用 duck-typing 取 ``HeAgentError.message``（项目自产的面向用户文本）；拿不到就用固定兜底
    文案——协议边界**绝不**回吐异常类型名、traceback 或路径。传输层因此不需要 import
    ``heagent.pub.exceptions``（AD-1）。
    """
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return sanitize_message(message)
    return GENERIC_ERROR_MESSAGE


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
        # 连接登记与有界关停委托 WsRegistry（与只读流同一实现，A54⑤）；
        # 关停预算在本服务的方法面上仍取 shutdown_timeout（调用方无参调用，既有签名不变）。
        self._ws_registry = WsRegistry(log_prefix="http", stream_label="run_id")

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
        if self.config.max_total_inflight and len(self._active) >= self.config.max_total_inflight:
            # 服务级总额：**跨**项目共享。``_active`` 装着所有项目的在途运行，与运行记录同源，
            # 因此判定不需要另建索引，也不会与 ``_inflight_in_scope`` 的事实分叉。
            raise HttpRunConflictError(
                "server is at its total in-flight limit",
                code=HttpErrorCode.TOTAL_INFLIGHT_LIMIT,
            )
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
            # 只有「无项目归属」的运行（``POST /api/runs``）驱动 ``/api/session`` 投影，
            # 项目内运行不改变它——该端点的语义因此逐字不变（R3/I13）。
            self._current_run_id = record.run_id
        safe_log(logger, logging.INFO, "http event=run_started run_id=%s", record.run_id)
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
        # 统一终态观测：只有不透明 run id、状态与耗时——**不含** prompt、回答或工具输出。
        safe_log(
            logger,
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
            # 标记「这是用户发的取消」，供 ``_execute`` 与看门狗归因区分。
            record.user_cancel_requested = True
            task.cancel()
            _done, pending = await asyncio.wait({task}, timeout=self.config.shutdown_timeout)
            if pending:
                safe_log(logger, logging.WARNING, "http event=cancel_timeout run_id=%s", run_id)
        return record

    def needs_resync(self, record: _RunRecord, last_event_id: int | None) -> bool:
        """客户端的游标是否已落在事件窗口之外（AD-4 的 ``resync_required`` 判据；算术单源
        ``http_protocol.cursor_out_of_window``，与只读流 / WS 共用）。"""
        return cursor_out_of_window(last_event_id, record.oldest_seq)

    def subscriber_count(self, record: _RunRecord) -> int:
        """该运行当前的 SSE 订阅者数（限额判定与测试用）。"""
        return len(record.subscribers)

    def ws_connection_count(self, record: _RunRecord) -> int:
        """该运行当前的 WS 连接数；不计入 SSE subscriber_count。"""
        return len(record.ws_subscribers)

    def register_ws(self, connection_id: str, run_id: str, websocket: Any) -> None:
        """登记已通过独立限额的 WS 连接，供有界关停关闭（委托 :class:`WsRegistry`）。"""
        self._ws_registry.register_ws(connection_id, run_id, websocket)

    def unregister_ws(self, connection_id: str) -> None:
        """移除断线或已关闭的 WS 连接登记。"""
        self._ws_registry.unregister_ws(connection_id)

    async def close_websockets(self) -> None:
        """通知所有已登记连接服务关闭，并在 shutdown_timeout 内完成收尾。"""
        await self._ws_registry.close_websockets(timeout=self.config.shutdown_timeout)

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
                safe_log(logger, logging.WARNING, "http event=run_shutdown_timeout pending=%d", len(pending))
        self._run_tasks.clear()

    # ---- 运行执行 ----

    def _deadline_tick(self) -> float | None:
        """看门狗的巡检间隔；三个时限全关时返回 ``None``（不启动看门狗）。

        取最小时限的 1/4（夹在 10ms..5s）：到点后最多晚一个 tick 发现，又不会为长时限空转占 CPU。
        ``inf``/``nan`` 已被 :class:`HttpServerConfig` 拒掉，故此处不必再防。
        """
        limits = [
            value
            for value in (
                self.config.request_timeout,
                self.config.idle_timeout,
                self.config.tool_inflight_timeout,
            )
            if value > 0
        ]
        if not limits:
            return None
        return min(5.0, max(0.01, min(limits) / 4))

    def _deadline_message(self, record: _RunRecord) -> str:
        """时限终态的客户端文案：**区分**「静默卡死」「工具卡死」与「超过运维显式设的总时长上限」。"""
        if record.deadline_reason == "idle":
            return f"run stalled: no activity for {self.config.idle_timeout:g}s"
        if record.deadline_reason == "tool":
            return f"run stalled: a tool has been in flight for over {self.config.tool_inflight_timeout:g}s"
        return f"run exceeded the configured time limit ({self.config.request_timeout:g}s)"

    async def _watch_deadlines(self, record: _RunRecord, task: asyncio.Task[Any], tick: float) -> None:
        """时限看门狗：判据成立就 ``task.cancel()``，并把**原因**写进记录（终态归因用）。

        三条判据（各自 > 0 才生效）：

        - ``request_timeout``：总时长硬上限——运维显式设的兜底闸门，默认 0（不限制）；
        - ``idle_timeout``：静默上限——**既没有新事件、也没有在途工具**才开始计时；
        - ``tool_inflight_timeout``：单个在途工具的最长在途时间（默认 1 小时）——
          永不返回的工具不再无界占住名额（A9②）。

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
            # 在途工具也要有**上限**：只数「有没有在途工具」会让永不返回的工具把在途名额无界
            # 占住。阈值**独立**于 idle_timeout——长 shell / 子代理期间同样没有
            # 事件，用静默阈值判工具卡死会误杀正常长调用（既有用例
            # ``test_in_flight_tool_stretches_the_idle_window`` 钉的正是这一点）。
            tool_limit = self.config.tool_inflight_timeout
            if (
                tool_limit > 0
                and record.tools_in_flight > 0
                and record.tools_in_flight_since is not None
                and now - record.tools_in_flight_since >= tool_limit
            ):
                record.deadline_reason = "tool"
                break
        if record.is_terminal:
            # 收尾竞态：判据成立的同时运行自己终结了——终态第一个赢，这里不碰它。
            return
        task.cancel()

    async def _execute(self, record: _RunRecord, executor: RunExecutor) -> None:
        """跑一次运行并把结果写进记录（唯一写终态的地方，AD-10）。

        时限（``HTTP_IDLE_TIMEOUT`` 静默 / ``HTTP_TOOL_INFLIGHT_TIMEOUT`` 单个在途工具 / ``HTTP_REQUEST_TIMEOUT`` 总时长，三者都可关）与取消都经
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
            # 用户显式 DELETE 优先于看门狗归因：看门狗的第一次取消可能已被 executor
            # 吞掉（``deadline_reason`` 仍在且未被消费），此时单看它会把这次 DELETE 记成
            # ``timed_out`` 并吞掉取消——归因必须看「谁发的取消」。
            if record.user_cancel_requested and not self._closing:
                if record.claim_terminal(RunStatus.CANCELLED):
                    record.append(RunEventKind.CANCELLED, message="run cancelled")
                    record.close_subscribers()
                raise
            reason = record.consume_deadline_reason()
            if reason is not None and not self._closing:
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
            safe_log(logger, logging.ERROR, "http event=run_failed run_id=%s", record.run_id, exc_info=True)
            if record.claim_terminal(RunStatus.FAILED):
                record.error_message = _client_error_message(exc)
                record.append(RunEventKind.ERROR, message=record.error_message)
                record.close_subscribers()
        else:
            reason = record.consume_deadline_reason()
            if reason is not None and not self._closing:
                # 时限已到但 executor 吞掉取消正常返回：终态按实际结果，但「时限没生效」必须可见。
                safe_log(
                    logger,
                    logging.WARNING,
                    "http event=timeout_ignored run_id=%s reason=%s elapsed_ms=%d",
                    record.run_id,
                    reason,
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
        queue: asyncio.Queue[RunEventPayload | None] | None = None,
        heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
    ) -> AsyncIterator[RunEventPayload | None]:
        """SSE 的事件源：先重放缓冲，再跟随实时事件；终态事件之后流立即结束（AD-4）。

        - ``last_event_id``（``Last-Event-ID``）只重放**严格大于**它的序号（缺口的判定由调用方
          在建立流之前用 :meth:`needs_resync` 做完，这里只管「不重复」——重放/去重/终态语义
          单源 ``http_protocol.replay_then_follow``，与 WS run 订阅共用）；
        - ``yield None`` 表示**心跳**（注释帧，不占事件 ID、不推进游标）；
        - 订阅者只读：断线只移除本队列，**绝不**取消运行——取消只能通过 ``DELETE``；
        - ``queue`` 由调用方传入时表示**已经登记过**（限额检查与登记必须同一步完成，
          见 :meth:`_RunRecord.try_add_subscriber`，活动台账 A9③）。
        """
        if queue is None:
            queue = asyncio.Queue(maxsize=record.subscriber_queue_size)
            record.subscribers.add(queue)
        try:
            # 生产路径在端点里先 try_add_subscriber、生成器首迭代才取快照，两者之间存在真实
            # await 窗口；快照与终态必须在同一同步段内读出（无 await），终态事件先于流结束
            # （AD-4）。重放与水位去重见 ``replay_then_follow``。
            snapshot = tuple(record.events)
            is_terminal = record.is_terminal
            async for payload in replay_then_follow(
                snapshot,
                cursor=last_event_id,
                is_terminal=is_terminal,
                queue=queue,
                heartbeat_seconds=heartbeat_seconds,
            ):
                yield payload
        finally:
            record.subscribers.discard(queue)
