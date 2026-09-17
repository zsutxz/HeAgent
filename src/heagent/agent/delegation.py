"""子 Agent 委派的编排实现 —— 为 tools 层注入可调用的委派回调。

``tools/builtins/subagent.py`` 只定义「委派请求 / 结果序列化 / 运行时槽」，
不认识 :class:`~heagent.agent.sub.SubAgent`；「怎么造子 Agent、怎么并发跑」由
本模块实现，经 :meth:`heagent.agent.loop.AgentLoop._runtime_scope` 在每次 run
的作用域内绑定。依赖方向因此固定为 ``agent → tools``，工具层不再反向依赖编排层。

回调协议见 :data:`~heagent.tools.builtins.subagent.DelegateOne` /
:data:`~heagent.tools.builtins.subagent.DelegateMany`：工具层传入「任务 + 已解析的
角色 + system 覆盖」，本模块返回工具层定义的 :class:`SubTaskOutcome`。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heagent.agent.sub import SubAgent, SubAgentAnnouncer, SubAgentResult, run_parallel
from heagent.tools.builtins.subagent import DelegateMany, DelegateOne, SubTaskOutcome

if TYPE_CHECKING:
    from heagent.context.compressor import ContextCompressor
    from heagent.engine import EngineContainer
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore
    from heagent.providers.base import BaseProvider
    from heagent.roles import RoleSpec
    from heagent.tools.registry import ToolRegistry
    from heagent.tools.safety import SafetyGuard


def build_subagent_delegates(
    provider: BaseProvider,
    *,
    registry: ToolRegistry | None = None,
    guard: SafetyGuard | None = None,
    skills: SkillStore | None = None,
    facts: FactStore | None = None,
    profile: ProfileStore | None = None,
    compressor: ContextCompressor | None = None,
    context_dir: str | None = None,
    soul: SoulStore | None = None,
    engine: EngineContainer | None = None,
    parent_run_id: str | None = None,
    depth: int = 0,
    announcer: SubAgentAnnouncer | None = None,
) -> tuple[DelegateOne, DelegateMany]:
    """构造本次 run 的单任务 / 并行委派回调（闭包捕获父 Agent 的组件依赖）。

    参数与 :class:`~heagent.agent.sub.SubAgent` 的构造参数一一对应：回调被调用时
    才构造子 Agent，因此每次委派都拿到全新实例；``parent_run_id`` 让子 run 挂在
    当前父 run 之下（可追踪 / 可恢复）；``depth`` 是父 loop 的委派深度，子 Agent
    以 ``depth + 1`` 记录自身深度（配合工具层的递归深度闸门）。
    """

    def _make(spec: RoleSpec | None, system: str | None) -> SubAgent:
        """按（角色, system 覆盖）构造一个子 Agent 实例。"""
        return SubAgent(
            provider,
            registry=registry,
            guard=guard,
            skills=skills,
            facts=facts,
            profile=profile,
            compressor=compressor,
            context_dir=context_dir,
            soul=soul,
            engine=engine,
            parent_run_id=parent_run_id,
            role=spec,
            system=system,
            delegation_depth=depth + 1,
            announcer=announcer,
        )

    def _to_outcome(result: SubAgentResult, spec: RoleSpec | None) -> SubTaskOutcome:
        """把 agent 层的 ``SubAgentResult`` 映射为工具层的可序列化结果。"""
        return SubTaskOutcome(
            status="ok" if result.success else "failed",
            role=spec.name if spec is not None else "",
            task=result.task,
            iterations=result.iterations,
            run_id=result.run_id,
            output=result.output,
        )

    async def delegate_one(task: str, spec: RoleSpec | None, system: str | None) -> SubTaskOutcome:
        return _to_outcome(await _make(spec, system).run(task), spec)

    async def delegate_many(tasks: list[str], spec: RoleSpec | None, system: str | None) -> list[SubTaskOutcome]:
        # 为每个 task 创建独立 SubAgent 实例（P1-1 修复：复用同一实例时并发 task 会
        # 竞态读写其内部状态）；run_parallel 保证结果与 tasks 等长且保序。
        agents = [_make(spec, system) for _ in tasks]
        results = await run_parallel(agents, tasks)
        return [_to_outcome(result, spec) for result in results]

    return delegate_one, delegate_many
