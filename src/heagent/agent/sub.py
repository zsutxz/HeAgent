"""Sub-agent execution helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from heagent.agent.loop import AgentLoop
from heagent.engine import EngineContainer
from heagent.engine.policy import PolicyEngine
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard

if TYPE_CHECKING:
    from heagent.context.compressor import ContextCompressor
    from heagent.engine.roles import RoleSpec
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
        max_iterations: int | None = None,
        skills: SkillStore | None = None,
        facts: FactStore | None = None,
        profile: ProfileStore | None = None,
        compressor: ContextCompressor | None = None,
        context_dir: str | None = None,
        soul: SoulStore | None = None,
        engine: EngineContainer | None = None,
        parent_run_id: str | None = None,
        role: RoleSpec | None = None,
        system: str | None = None,
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry or ToolRegistry.get()
        self._guard = guard or SafetyGuard()
        self._skills = skills
        self._facts = facts
        self._profile = profile
        self._compressor = compressor
        self._context_dir = context_dir
        self._soul = soul
        self._engine = engine or EngineContainer.default(workspace_root=context_dir)
        self._parent_run_id = parent_run_id
        self._role = role
        self._system = system or (role.system if role is not None else None)
        self._allowed_tools = allowed_tools if allowed_tools is not None else (
            list(role.allowed_tools) if role is not None and role.allowed_tools else None
        )
        self._blocked_tools = blocked_tools if blocked_tools is not None else (
            list(role.blocked_tools) if role is not None and role.blocked_tools else None
        )
        self._max_iterations = (
            max_iterations
            if max_iterations is not None
            else (role.max_iterations if role is not None else 20)
        )

    def _build_engine(self) -> EngineContainer:
        """Return the engine for this run, swapping in a role-specific policy.

        When a role restricts tools (allowed_tools / blocked_tools), build a
        per-role PolicyEngine and replace the parent engine's policy — all other
        runtime services (run_store / ledger / events) are inherited unchanged.
        """
        if self._allowed_tools is None and self._blocked_tools is None:
            return self._engine
        role_policy = PolicyEngine(
            workspace_root=self._engine.policy.workspace_root,
            allowed_tools=list(self._allowed_tools) if self._allowed_tools else None,
            blocked_tools=list(self._blocked_tools) if self._blocked_tools else None,
        )
        return replace(self._engine, policy=role_policy)

    async def run(self, task: str) -> SubAgentResult:
        """Run one delegated task in a fresh loop instance."""
        engine = self._build_engine()
        metadata: dict[str, object] = {"kind": "subagent"}
        if self._role is not None:
            metadata["role"] = self._role.name
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
            engine=engine,
            run_context=engine.create_run_context(
                parent_run_id=self._parent_run_id,
                metadata=metadata,
                workspace_root=self._context_dir,
            ),
        )
        try:
            output = await loop.run(task, system=self._system)
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
