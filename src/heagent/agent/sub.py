"""Sub-agent execution helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from heagent.agent.loop import AgentLoop
from heagent.engine import EngineContainer
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard

if TYPE_CHECKING:
    from heagent.context.compressor import ContextCompressor
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore
    from heagent.providers.base import BaseProvider


@dataclass
class SubAgentResult:
    """Result of one delegated sub-agent task."""

    task: str
    output: str
    success: bool
    iterations: int = 0


class SubAgent:
    """Isolated agent wrapper for delegated tasks."""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        registry: ToolRegistry | None = None,
        guard: SafetyGuard | None = None,
        max_iterations: int = 20,
        skills: SkillStore | None = None,
        facts: FactStore | None = None,
        profile: ProfileStore | None = None,
        compressor: ContextCompressor | None = None,
        context_dir: str | None = None,
        soul: SoulStore | None = None,
        engine: EngineContainer | None = None,
        parent_run_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry or ToolRegistry.get()
        self._guard = guard or SafetyGuard()
        self._max_iterations = max_iterations
        self._skills = skills
        self._facts = facts
        self._profile = profile
        self._compressor = compressor
        self._context_dir = context_dir
        self._soul = soul
        self._engine = engine or EngineContainer.default(workspace_root=context_dir)
        self._parent_run_id = parent_run_id

    async def run(self, task: str) -> SubAgentResult:
        """Run one delegated task in a fresh loop instance."""
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
            engine=self._engine,
            run_context=self._engine.create_run_context(
                parent_run_id=self._parent_run_id,
                metadata={"kind": "subagent"},
                workspace_root=self._context_dir,
            ),
        )
        try:
            output = await loop.run(task)
            return SubAgentResult(
                task=task,
                output=output,
                success=True,
                iterations=loop.last_iteration or 0,
            )
        except Exception as exc:
            return SubAgentResult(
                task=task,
                output=str(exc),
                success=False,
                iterations=loop.last_iteration or 0,
            )


async def run_parallel(agents: list[SubAgent], tasks: list[str]) -> list[SubAgentResult]:
    """Run multiple sub-agent tasks concurrently."""
    coroutines = [agent.run(task) for agent, task in zip(agents, tasks, strict=True)]
    return await asyncio.gather(*coroutines)
