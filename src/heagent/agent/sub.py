"""子 Agent — 隔离的 Agent 实例，用于任务委派和并行执行。

SubAgent 拥有独立的 AgentLoop + 对话上下文，
可安全地并行运行多个子任务而不互相干扰。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from heagent.agent.loop import AgentLoop
from heagent.providers.base import BaseProvider
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard
from heagent.types import Message, Role


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
    """

    def __init__(
        self,
        provider: BaseProvider,
        *,
        registry: ToolRegistry | None = None,
        guard: SafetyGuard | None = None,
        max_iterations: int = 20,  # 子 Agent 默认迭代上限更低
    ) -> None:
        self._provider = provider
        self._registry = registry or ToolRegistry.get()
        self._guard = guard or SafetyGuard()
        self._max_iterations = max_iterations

    async def run(self, task: str) -> SubAgentResult:
        """执行单个子任务。

        为每次运行创建全新的 AgentLoop（确保上下文隔离），
        捕获所有异常并转换为 SubAgentResult。
        """
        loop = AgentLoop(
            self._provider,
            registry=self._registry,
            guard=self._guard,
            max_iterations=self._max_iterations,
        )
        try:
            output = await loop.run(task)
            return SubAgentResult(task=task, output=output, success=True)
        except Exception as e:
            # 异常不向外抛出，包装为失败结果
            return SubAgentResult(task=task, output=str(e), success=False)


async def run_parallel(agents: list[SubAgent], tasks: list[str]) -> list[SubAgentResult]:
    """并行运行多个子 Agent。

    通过 asyncio.gather 实现真正的并发执行，
    所有子任务同时开始，全部完成后返回结果列表。
    agents[i] 执行 tasks[i]，两者长度必须一致。
    """
    coros = [a.run(t) for a, t in zip(agents, tasks)]
    return list(await asyncio.gather(*coros, return_exceptions=False))
