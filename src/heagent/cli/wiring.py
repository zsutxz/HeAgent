"""入口层装配点 —— provider 呈现薄壳 + ``ensure_runtime_config`` / ``build_cron_job_runner``。

provider 装配**规则真身**已于 2026-11-07（批次 9 卡 B）迁至 ``heagent.providers.composition``
（providers 层，致命配置错误抛 ``ProviderConfigError``）；本模块保留 ``_build_provider``
绑定名作**呈现薄壳**：catch 后 ``click.echo(err=True)`` + ``SystemExit(1)``——搬规则不搬
呈现，``console`` / ``http`` / ``gui`` 的绑定名与测试 patch 字符串零变化。

剩余职责两件：``ensure_runtime_config``（构造期配置快照收窄，Phase 1）与
``build_cron_job_runner``（原 cli/gui 两处 ``_run_job`` 的逐字合并，Phase 2 C3）——
入口层各 loop 构造点真正共用、且漂移风险高的两段。

分层：本模块是**入口层**（与 ``cli`` / ``gui`` 同级），依赖 ``providers`` / ``config``，
不被任何下层模块导入——不构成反向依赖。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import click

from heagent.agent.loop import AgentLoop
from heagent.providers.composition import ProviderConfigError
from heagent.providers.composition import _build_provider as _composition_build_provider

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from heagent.agent.middleware import MiddlewareFn
    from heagent.agent.sub import SubAgentAnnouncer
    from heagent.config import ResolvedRuntimeConfig, Settings
    from heagent.context.compressor import ContextCompressor
    from heagent.context.window_reset import WindowResetConfig
    from heagent.cron.jobs import JobStore
    from heagent.engine import EngineContainer, RunContext
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.soul import SoulStore
    from heagent.network.http_protocol import CronResultStatus
    from heagent.providers.base import BaseProvider
    from heagent.skills import SkillStore

    # cron job runner：(prompt, run_context) → None（共享缝的返回类型）
    CronJobRunner = Callable[[str, RunContext], Awaitable[None]]

    # cron 结果通知器：(job_id, status, text) → None。入口层构造（网络中枢 + 终端回显），
    # wiring 只负责调用 —— runner 因此不认识任何网络类型，`network/` 也不必反向依赖运行栈。
    CronNotifier = Callable[[str, "CronResultStatus", str], None]

logger = logging.getLogger(__name__)


def _first_line(exc: BaseException) -> str:
    """异常的首个非空行（失败通知只带一行，绝不把 traceback 塞进通知流/终端）。"""
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _build_provider(settings: Settings, model: str | None) -> BaseProvider:
    """provider 装配呈现薄壳（批次 9 卡 B）：规则真身在 ``heagent.providers.composition``。

    把规则侧 ``ProviderConfigError`` 转成终端呈现——``click.echo(err=True)`` +
    ``SystemExit(1)``，消息字节与退出码不变。
    """
    try:
        return _composition_build_provider(settings, model)
    except ProviderConfigError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from None


# ----------------------------------------------------------------------
# loop 装配共享缝：入口层各 loop 构造点真正共用、且漂移风险高的
# 两段——engine 配置快照读回收窄与 cron job runner——收敛到此处。
# 主 loop 本体仍由各入口显式构造：两入口在每个旋钮上都有真实产品差异
# （session/上下文策略/soul/retry 中间件/context_dir），全量参数化会产出
# 17 参 + 4 布尔旗的巨函，比两个显式构造点更难读。
# ----------------------------------------------------------------------


def ensure_runtime_config(engine: EngineContainer) -> ResolvedRuntimeConfig:
    """读取 engine 的构造期配置快照并收窄类型（Phase 1：``engine.runtime_config`` 是权威）。

    ``EngineContainer`` 构造完成即已完成解析；``None`` 只会出现在构造完成前的中间态，
    此处显性失败（不静默兜底）。
    """
    resolved = engine.runtime_config
    if resolved is None:  # pragma: no cover —— 构造完成即已解析，此分支仅为类型收窄显性兜底
        raise RuntimeError("EngineContainer.runtime_config 未解析：构造后不应为 None")
    return resolved


def build_cron_job_runner(
    provider: BaseProvider,
    engine: EngineContainer,
    runtime_config: ResolvedRuntimeConfig,
    cron_store: JobStore,
    *,
    skills: SkillStore | None,
    facts: FactStore | None,
    profile: ProfileStore | None,
    soul: SoulStore | None = None,
    max_iterations: int | None = None,
    retry_mw: MiddlewareFn,
    compressor: ContextCompressor | None = None,
    window_reset: WindowResetConfig | None = None,
    context_dir: str | None = None,
    subagent_announcer: SubAgentAnnouncer | None = None,
    cron_notifier: CronNotifier | None = None,
) -> CronJobRunner:
    """构造 cron 任务的 job runner（原 cli/gui 两处 ``_run_job`` 的逐字合并，Phase 2 C3）。

    runner 语义：goal 自动推进 job（``_goal_auto_goal_id`` 命中）走 ``_goal_cron_advance``
    续推 workflow；其余 prompt 构造**一次性 loop**（与入口主 loop 共享 provider/engine/
    stores，事件经同一 EventBus 汇聚），使用传入的 ``run_context``，不与交互中的主 loop
    抢占上下文。

    ``heagent.cli.goal`` 经函数体内惰性导入：wiring 与 cli/goal 同属入口层，但 cli/goal
    装载侧会经 wiring 建 provider，模块级互导即成环。

    ``cron_notifier``（Epic 58 D5）是入口层注入的**结果投递回调**：一次执行产出**一条**通知
    （成功带最终答案、失败带异常首行）。回调抛异常一律 warning 后丢弃——后台任务的成功与否
    不该被「通知送不出去」改写。
    """

    def _notify(run_context: RunContext, status: CronResultStatus, text: str) -> None:
        """把一次执行的终局交给通知器；**任何**异常都不得影响 cron 执行结果。"""
        if cron_notifier is None:
            return
        job_id = str(run_context.metadata.get("job_id", "") or "")
        try:
            cron_notifier(job_id, status, text)
        except Exception:
            logger.warning("cron notifier failed; notification dropped (job=%s)", job_id, exc_info=True)

    async def _run_job(prompt: str, run_context: RunContext) -> None:
        from heagent.cli.goal import _goal_auto_goal_id, _goal_cron_advance
        from heagent.network.http_protocol import CronResultStatus  # noqa: PLC0415 —— 见上方惰性导入说明

        goal_id = _goal_auto_goal_id(prompt)
        if goal_id is not None:
            # goal 自动推进不是「给用户的回答」——不发通知（零投递、零回显）。
            await _goal_cron_advance(provider, engine, cron_store, goal_id)
            return
        loop = AgentLoop(
            provider,
            max_iterations=max_iterations,
            middlewares=[retry_mw],
            skills=skills,
            facts=facts,
            profile=profile,
            compressor=compressor,
            window_reset=window_reset,
            context_dir=context_dir,
            soul=soul,
            cron_store=cron_store,
            engine=engine,
            runtime_config=runtime_config,
            run_context=run_context,
            subagent_announcer=subagent_announcer,
        )
        try:
            answer = await loop.run(prompt)
        except Exception as exc:
            # 失败也要送达（客户端/终端需要知道「跑了但没结果」），但异常**继续上抛**：
            # scheduler 仍要 ledger.fail + 更新 last_run（只有 goal 推进分支不发通知）。
            _notify(run_context, CronResultStatus.FAILED, _first_line(exc))
            raise
        _notify(run_context, CronResultStatus.COMPLETED, answer)

    return _run_job
