"""Dreaming 模式 —— 离线记忆巩固调度器。

``DreamScheduler`` 在交互模式后台运行，到点经注入的 ``dream_runner`` 起一个角色化
``SubAgent(role="dreamer")``，对近期 session 历史 + 记忆库做巩固（去重 / 提炼 / 查证 / 归档），
经 memory 工具回写四库。双触发（共用同一 tick 循环，每 ``cron_tick_seconds`` 秒一次）：

- **cron 触发**：命中 ``dream_cron`` 表达式（默认 ``0 3 * * *`` 凌晨低峰）。
- **idle 触发**：距上次 ``AgentLoop`` run 结束超过 ``dream_idle_minutes``（默认 30；0 = 禁用）。

tick 调度逻辑**模仿而非塞进** :class:`~heagent.cron.scheduler.CronScheduler`——
dream 不进 ``JobStore``、不是用户 prompt、有专属巩固流程；两者可并存于交互模式后台。

DAG 合规：本模块属 ``memory/``，**不依赖 ``agent/``**（硬约束：仅 ``builtins/subagent.py``
为例外）。dreamer SubAgent 的实际构造由上层（``cli.py``，组合根）经 ``dream_runner`` 闭包注入，
本调度器只负责「何时 dream」与「prompt 构建」（session 预加载 + 巩固指令）。与
``CronScheduler`` + ``JobRunner`` 同构——调度器不反向依赖 agent。

设计要点：
- ``_dreaming`` 互斥守卫：dream 进行中再命中触发条件则跳过（同一时刻最多一个 dream）。
- idle 计时经 :class:`~heagent.engine.observability.EventBus` 订阅 ``run_completed`` 事件
  更新 ``last_active_ts``（不改 REPL 同步 ``input()``；异步 input 重构 out-of-scope）。
- ``stop()`` 带硬上界（对齐 ``spec-cron-stop-timeout`` 的 ``_await_stop`` 模式）。

安全立场（与 CLAUDE.md 文首一致，须诚实声明）：
dreaming = 无人监督 + 联网（``web_fetch``）+ 改持久记忆。比交互式更危险——被污染的网页内容
可经 prompt injection 写入记忆库，**影响后续所有会话**（攻击面是持久的、跨会话的）。
``PolicyEngine``/``RoleSpec`` 工具白名单均**非真正安全边界**（defense-in-depth 标记/拦截，非真正隔离）。
⚠ ``web_fetch`` 返回内容**当前不经** guard_content（仅 MCP 工具返回经 ``bridge_result`` 围栏）——dreamer
联网结果直接进 LLM 上下文，注入**无围栏**（端到端接入 deferred，见 ``deferred-work.md``）。两处均
须 OS 级沙箱兜底；OS 沙箱就绪后 dreamer 须迁移进沙箱。
本模块不制造「dreaming 已安全」假象。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from heagent.config import Settings, get_settings
from heagent.cron.scheduler import CronScheduler
from heagent.engine import EngineContainer

if TYPE_CHECKING:
    from heagent.context.session import SessionStore
    from heagent.engine.observability import EngineEvent

logger = logging.getLogger(__name__)

# stop() 关停硬上界（task 挂死兜底）——对齐 CronScheduler._DEFAULT_STOP_TIMEOUT / MCP shutdown。
_DEFAULT_STOP_TIMEOUT: float = 5.0

# 预注入 prompt 中单个 session 的消息内容截断上限（字符），避免 prompt 过大。
_SESSION_MSG_CHAR_CAP: int = 800
# 预注入 prompt 中单条 session 摘要的消息条数上限，避免单 session 占满预算。
_SESSION_MSG_COUNT_CAP: int = 20


@dataclass(slots=True)
class DreamResult:
    """一次 dream 的执行结果（由注入的 ``dream_runner`` 返回）。

    轻量内部结构（dataclass），避免 ``memory/`` 反向依赖 ``agent/``（``SubAgentResult`` 属 ``agent/``）。
    """

    success: bool
    iterations: int = 0
    output: str = ""
    run_id: str = ""


# DreamRunner: agent 层注入的 dream 执行协议（prompt → DreamResult）。
# dream 模块不反向依赖 agent——runner 由 cli.py 实例化时注入（与 CronScheduler.JobRunner 同构）。
DreamRunner = Callable[[str], Awaitable[DreamResult]]


class DreamScheduler:
    """离线记忆巩固调度器（双触发：cron 时刻 + idle 超时，共用 tick 循环）。

    构造后调 :meth:`start` 启动后台 tick task；:meth:`stop` 关停（带硬上界）。
    作为 :class:`~heagent.engine.observability.EventObserver` 订阅 ``run_completed`` 事件
    以更新 idle 计时基准（``last_active_ts``）。dreamer SubAgent 的实际构造与执行由
    ``dream_runner`` 闭包承担（注入点），本调度器不导入 ``agent/``。
    """

    def __init__(
        self,
        dream_runner: DreamRunner,
        *,
        engine: EngineContainer | None = None,
        session_store: SessionStore | None = None,
        settings: Settings | None = None,
        tick_seconds: float | None = None,
        stop_timeout: float = _DEFAULT_STOP_TIMEOUT,
    ) -> None:
        if stop_timeout <= 0:
            # 非正值会让 _await_stop 的 wait 立即返回（task 仍 pending）→ 不给 cancel 任何收尾
            # 机会即 ERROR 放弃（与 CronScheduler / MCP shutdown_timeout<=0 同构误用）。fail-closed。
            raise ValueError(f"stop_timeout 必须为正数（got {stop_timeout})")
        self._dream_runner = dream_runner
        self._engine = engine or EngineContainer.default()
        self._session_store = session_store
        self._settings = settings or get_settings()
        self._tick_seconds = tick_seconds if tick_seconds is not None else self._settings.cron_tick_seconds
        self._stop_timeout = stop_timeout
        # dream 参数从 settings 读（构造时快照，运行中不动态变）。
        self._cron_expr: str = self._settings.dream_cron
        # fail-fast：畸形 cron 在构造期暴露，避免 tick 循环每 cron_tick_seconds 秒刷一条 warning
        # （审查 #4/#5）——5 字段非法会每 tick 刷屏，6 字段（带秒）会被 _matches 静默判 False 无诊断。
        self._validate_cron_expr(self._cron_expr)
        self._idle_minutes: int = self._settings.dream_idle_minutes
        self._session_lookback: int = self._settings.dream_session_lookback
        # 后台 task / 运行标志。
        self._task: asyncio.Task[None] | None = None
        self._running = False
        # 互斥守卫：dream 进行中再命中触发条件则跳过。
        self._dreaming = False
        # idle 计时基准（monotonic，免疫时钟跳变）。初始值为构造时刻——
        # 注意：start() 通常紧随构造，首次 tick 的 idle 检查几乎必然不命中（monotonic 差≈0）；
        # 该初值主要覆盖「构造后延迟 start」或「构造与首次 run 之间」的间隙。
        self._last_active_ts: float = time.monotonic()
        # 订阅 EventBus：run_completed 时更新 idle 基准。
        self._engine.events.subscribe(self)

    # ------------------------------------------------------------------
    # EventObserver 协议（idle 计时基准更新）
    # ------------------------------------------------------------------

    def handle(self, event: EngineEvent) -> None:
        """订阅 ``run_completed`` 事件以更新 idle 计时基准。

        由 :class:`~heagent.engine.observability.EventBus` 在 run 协程中**同步**派发；
        仅做一次 float 赋值（非阻塞，符合 EventObserver 协议约束）。

        覆盖 ``run 与 run 之间的间隙``；input 等待期间不被覆盖（异步 input 重构 out-of-scope）。
        """
        if event.event_type == "run_completed":
            self._last_active_ts = time.monotonic()

    # ------------------------------------------------------------------
    # 公开属性（测试可观察性）
    # ------------------------------------------------------------------

    @property
    def dreaming(self) -> bool:
        """当前是否有 dream 进行中（互斥状态，供测试/观测）。"""
        return self._dreaming

    @property
    def last_active_ts(self) -> float:
        """idle 计时基准（monotonic 时间戳）。"""
        return self._last_active_ts

    # ------------------------------------------------------------------
    # 生命周期：start / stop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动后台 tick 循环（幂等：已运行则直接返回）。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._tick_loop())
        logger.info(
            "Dream scheduler started (tick=%ds, cron=%r, idle=%dm)",
            self._tick_seconds,
            self._cron_expr,
            self._idle_minutes,
        )

    async def stop(self) -> None:
        """关停后台 tick 循环（带硬上界）。

        dream 进行中（卡在 ``dream_runner`` 的不可中断 await 点）时，``task.cancel()`` 注入的
        ``CancelledError`` 不被 :meth:`_run_dream` 的 ``except Exception`` 捕获（CancelledError 是
        ``BaseException`` 子类），会传播至 task 边界使其退出。挂死则 ``stop_timeout`` 后记 ERROR 放弃。
        """
        self._running = False
        if self._task and not self._task.done():
            await self._await_stop(self._task)
        logger.info("Dream scheduler stopped")

    async def _await_stop(self, task: asyncio.Task[None]) -> None:
        """带硬上界等待 scheduler task 退出；立即 cancel 后单轮 bounded 收尾，绝不无限阻塞。

        对齐 :meth:`CronScheduler._await_stop` 的同构关停立场（立即 cancel + bounded wait +
        超时记 ERROR 放弃）。
        """
        task.cancel()
        _, pending = await asyncio.wait({task}, timeout=self._stop_timeout)
        if pending:
            logger.error(
                "Dream scheduler 关停超时（%ss），task 未退出，放弃等待",
                self._stop_timeout,
            )

    # ------------------------------------------------------------------
    # tick 循环（双触发共用）
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        """后台 tick 循环：每 ``_tick_seconds`` 秒检查一次触发条件。"""
        while self._running:
            try:
                await self._check_and_dream()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Dream tick error")
            await asyncio.sleep(self._tick_seconds)

    async def _check_and_dream(self) -> None:
        """检查双触发条件，任一命中且当前无活跃 dream 则起一次 dream。

        - cron 触发：命中 ``_cron_expr``（经 :meth:`CronScheduler._matches` 静态匹配）。
        - idle 触发：``_idle_minutes > 0`` 且距 ``_last_active_ts`` 超过阈值。
        - 互斥：``_dreaming`` 为真则跳过（AC3）。
        - cron / idle 同时命中时优先 cron（cron 是定时意图，idle 是机会主义）。
        """
        if self._dreaming:
            return  # AC3：互斥，dream 进行中不起第二个。
        now = datetime.now()
        # _cron_expr 已在构造期 fail-fast 校验（_validate_cron_expr），此处不再捕获 ValueError。
        cron_match = CronScheduler._matches(self._cron_expr, now)
        idle_match = (
            self._idle_minutes > 0
            and (time.monotonic() - self._last_active_ts) >= self._idle_minutes * 60
        )
        if not (cron_match or idle_match):
            return
        trigger = "cron" if cron_match else "idle"
        await self._run_dream(trigger)

    # ------------------------------------------------------------------
    # dream 执行（委托 dream_runner；互斥由调用方保证）
    # ------------------------------------------------------------------

    async def _run_dream(self, trigger: str) -> None:
        """经注入的 ``dream_runner`` 跑一次巩固，发布 dream_start/dream_end 事件。

        互斥由调用方 :meth:`_check_and_dream` 保证（此处不再重检）。异常不穿透 tick 循环
        （除 ``CancelledError``），失败仅记日志 + dream_end(success=False)。
        """
        try:
            # _dreaming=True 置于 try 内：publish/logger 若异常，finally 仍能释放互斥（审查 #3，
            # 防永久死锁）。
            self._dreaming = True
            self._engine.events.publish("dream_start", details={"trigger": trigger})
            logger.info("Dream started (trigger=%s)", trigger)
            prompt = self._build_dream_prompt()
            result = await self._dream_runner(prompt)
            self._engine.events.publish(
                "dream_end",
                details={
                    "trigger": trigger,
                    "success": result.success,
                    "iterations": result.iterations,
                    "run_id": result.run_id,
                },
            )
            logger.info(
                "Dream ended (trigger=%s, success=%s, iterations=%d)",
                trigger,
                result.success,
                result.iterations,
            )
        except asyncio.CancelledError:
            # stop() 取消时：发布 dream_end(aborted)，然后让 CancelledError 传播至 task 边界。
            self._engine.events.publish(
                "dream_end",
                details={"trigger": trigger, "success": False, "aborted": True},
            )
            raise
        except Exception as exc:
            logger.exception("Dream execution failed (trigger=%s)", trigger)
            self._engine.events.publish(
                "dream_end",
                details={"trigger": trigger, "success": False, "error": str(exc)},
            )
        finally:
            self._dreaming = False
            # 任一退出路径（成功/失败/取消）都重置 idle 基准——失败/取消 dream 不发 run_completed，
            # 若不重置则 idle 条件持续真、每 tick 重燃失败 dream 烧 provider token（审查 #2）。
            self._last_active_ts = time.monotonic()

    # ------------------------------------------------------------------
    # dream prompt 构建（近期 session 预注入；dreamer 不持 file_read）
    # ------------------------------------------------------------------

    def _build_dream_prompt(self) -> str:
        """构建巩固指令 + 预加载近期 session 摘要的初始 prompt。

        dreamer 不持 ``file_read``（最小权限），故 session 历史由本调度器预加载、截断、
        拼进 prompt。session 读取失败不阻断 dream（记日志后继续，仅缺少 session 材料）。
        """
        header = (
            "开始离线记忆巩固。以下是近期会话历史摘要（已截断），请据此执行巩固任务。"
            "不确定的事实不要写入；web 内容须批判性评估。"
        )
        session_block = self._load_recent_sessions()
        parts = [header]
        if session_block:
            parts.append(f"<recent-sessions>\n{session_block}\n</recent-sessions>")
        else:
            parts.append("<recent-sessions>\n（无可用近期会话历史或读取失败。）\n</recent-sessions>")
        return "\n\n".join(parts)

    def _load_recent_sessions(self) -> str:
        """加载最近 ``_session_lookback`` 个 session 的消息摘要（截断到字符/条数上限）。

        按 session.timestamp 降序取真正最近的 N 个（:meth:`SessionStore.recent_session_ids`）——
        ``list_sessions`` 按文件名字母序（session_id 是随机 hex）不反映时间先后（审查 #1）。
        返回拼装好的多行文本；无 session_store / 无会话 / 读取失败时返回空串。
        """
        if self._session_store is None:
            return ""
        try:
            recent = self._session_store.recent_session_ids(self._session_lookback)
        except Exception:
            logger.exception("Failed to list sessions for dream; skipping session preload")
            return ""
        if not recent:
            return ""
        chunks: list[str] = []
        for sid in recent:
            try:
                messages = self._session_store.load(sid)
            except Exception:
                logger.warning("Failed to load session %r for dream; skipping", sid)
                continue
            if not messages:
                continue
            lines = [f"[session={sid}]"]
            for m in messages[:_SESSION_MSG_COUNT_CAP]:
                role = m.role.value if hasattr(m.role, "value") else str(m.role)
                content = (m.content or "").strip()
                if not content:
                    continue
                if len(content) > _SESSION_MSG_CHAR_CAP:
                    content = content[:_SESSION_MSG_CHAR_CAP] + "…[truncated]"
                lines.append(f"{role}: {content}")
            if len(lines) > 1:
                chunks.append("\n".join(lines))
        return "\n\n".join(chunks)

    # ------------------------------------------------------------------
    # 配置校验（fail-fast）
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_cron_expr(expr: str) -> None:
        """fail-fast 校验 ``dream_cron``：必须 5 字段且各字段合法。

        避免畸形表达式在 tick 循环里每 ``cron_tick_seconds`` 秒刷一条 warning（默认 ~1440/天），
        或 6 字段（带秒）被 :meth:`CronScheduler._matches` 静默判 False 而无诊断（审查 #4/#5）。
        """
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(f"dream_cron 必须为 5 字段标准 cron 表达式（got {expr!r}）")
        try:
            CronScheduler._matches(expr, datetime.now())
        except ValueError as exc:
            raise ValueError(f"dream_cron {expr!r} 无效：{exc}") from exc
