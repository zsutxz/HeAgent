"""子 Agent — 隔离的 Agent 实例，用于任务委派和并行执行。

SubAgent 拥有独立的 AgentLoop + 对话上下文，
可安全地并行运行多个子任务而不互相干扰。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from heagent.agent.loop import AgentLoop
from heagent.providers.base import BaseProvider
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard

if TYPE_CHECKING:
    from heagent.context.compressor import ContextCompressor
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore


@dataclass
class SubAgentResult:
    """子 Agent 任务执行结果。

    task: 原始任务描述
    output: 执行输出（成功时为最终答案，失败时为错误信息）
    success: 是否成功完成
    iterations: 实际迭代次数
    """

    task: str
    output: str
    success: bool
    iterations: int = 0


class SubAgent:
    """隔离的 Agent 实例。

    与主 AgentLoop 共享 Provider 和 Registry，但拥有独立的对话上下文和迭代预算。
    适用于将复杂任务拆分为多个可并行的子任务。

    父级的 soul/skills/facts/profile/compressor/context_dir 可选注入——
    这些组件参与子 AgentLoop 系统提示词组装，保证子 Agent 与父级人格/
    记忆/技能一致。注意：非纯只读——组装时 SkillStore 会触发 record_usage
    写入，并行子 Agent 共享同一 store 存在写竞态（已知限制，见 deferred-work）。
    session/middlewares/cron_store 不继承：session 会污染父级持久化，cron 不在诉求内。
    """

    def __init__(
        self,
        provider: BaseProvider,
        *,
        registry: ToolRegistry | None = None,
        guard: SafetyGuard | None = None,
        max_iterations: int = 20,  # 子 Agent 默认迭代上限更低
        skills: SkillStore | None = None,
        facts: FactStore | None = None,
        profile: ProfileStore | None = None,
        compressor: ContextCompressor | None = None,
        context_dir: str | None = None,
        soul: SoulStore | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry or ToolRegistry.get()
        self._guard = guard or SafetyGuard()
        self._max_iterations = max_iterations
        # 父级上下文组件（只读注入，转发到子 AgentLoop）
        self._skills = skills
        self._facts = facts
        self._profile = profile
        self._compressor = compressor
        self._context_dir = context_dir
        self._soul = soul

    async def run(self, task: str) -> SubAgentResult:
        """执行单个子任务。

        为每次运行创建全新的 AgentLoop（确保上下文隔离——messages 空起步），
        转发父级上下文组件用于系统提示词注入。
        捕获所有异常并转换为 SubAgentResult。
        """
        loop = AgentLoop(
            self._provider,
            registry=self._registry,
            guard=self._guard,
            max_iterations=self._max_iterations,
            skills=self._skills,
            facts=self._facts,
            profile=self._profile,
            compressor=self._compressor,
            context_dir=self._context_dir,
            soul=self._soul,
        )
        try:
            output = await loop.run(task)
            return SubAgentResult(
                task=task, output=output, success=True,
                iterations=loop.last_iteration or 0,
            )
        except Exception as e:
            # 异常不向外抛出，包装为失败结果
            return SubAgentResult(
                task=task, output=str(e), success=False,
                iterations=loop.last_iteration or 0,
            )


async def run_parallel(agents: list[SubAgent], tasks: list[str]) -> list[SubAgentResult]:
    """并行运行多个子 Agent。

    通过 asyncio.gather 实现真正的并发执行，
    所有子任务同时开始，全部完成后返回结果列表。
    agents[i] 执行 tasks[i]，两者长度必须一致。
    """
    coros = [a.run(t) for a, t in zip(agents, tasks, strict=True)]
    return list(await asyncio.gather(*coros, return_exceptions=False))
