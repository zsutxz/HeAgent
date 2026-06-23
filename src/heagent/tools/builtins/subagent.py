"""Builtin tools for delegating work to sub-agents."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from heagent.agent.sub import SubAgent, run_parallel
from heagent.engine import EngineContainer
from heagent.tools.decorator import tool
from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from heagent.context.compressor import ContextCompressor
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore
    from heagent.providers.base import BaseProvider
    from heagent.tools.registry import ToolRegistry
    from heagent.tools.safety import SafetyGuard


@dataclass(slots=True)
class SubagentToolRuntime:
    """Runtime dependencies for sub-agent delegation tools."""

    provider: BaseProvider | None
    registry: ToolRegistry | None
    guard: SafetyGuard | None
    skills: SkillStore | None
    facts: FactStore | None
    profile: ProfileStore | None
    compressor: ContextCompressor | None
    context_dir: str | None
    soul: SoulStore | None
    engine: EngineContainer | None
    parent_run_id: str | None


_subagent_runtime = RuntimeSlot[SubagentToolRuntime]("heagent_subagent_tools")


def configure_subagent_tools(
    provider: BaseProvider | None,
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
) -> None:
    """Set fallback runtime dependencies for sub-agent tools."""
    _subagent_runtime.configure(
        SubagentToolRuntime(
            provider=provider,
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
        )
    )


def reset_subagent_tools() -> None:
    """Clear fallback sub-agent tool dependencies."""
    _subagent_runtime.reset()


@contextmanager
def bind_subagent_tools(
    provider: BaseProvider | None,
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
) -> Iterator[None]:
    """Bind sub-agent tool dependencies for the current run context."""
    with _subagent_runtime.bind(
        SubagentToolRuntime(
            provider=provider,
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
        )
    ):
        yield


def _runtime() -> SubagentToolRuntime | None:
    return _subagent_runtime.get()


@tool
async def task_delegate(task: str) -> str:
    """Delegate one task to an isolated sub-agent."""
    runtime = _runtime()
    if runtime is None or runtime.provider is None:
        return "Error: sub-agent tools not configured."

    agent = SubAgent(
        runtime.provider,
        registry=runtime.registry,
        guard=runtime.guard,
        skills=runtime.skills,
        facts=runtime.facts,
        profile=runtime.profile,
        compressor=runtime.compressor,
        context_dir=runtime.context_dir,
        soul=runtime.soul,
        engine=runtime.engine,
        parent_run_id=runtime.parent_run_id,
    )
    result = await agent.run(task)
    if result.success:
        return f"Sub-agent completed (iterations: {result.iterations}):\n{result.output}"
    return f"Sub-agent failed: {result.output}"


@tool
async def task_parallel(tasks_json: str) -> str:
    """Run multiple sub-agent tasks concurrently."""
    runtime = _runtime()
    if runtime is None or runtime.provider is None:
        return "Error: sub-agent tools not configured."

    try:
        tasks = json.loads(tasks_json)
    except (json.JSONDecodeError, TypeError):
        return "Error: tasks_json must be a valid JSON array of strings."

    if not isinstance(tasks, list) or not tasks:
        return "Error: tasks_json must be a non-empty JSON array."
    if not all(isinstance(task, str) for task in tasks):
        return "Error: tasks_json must be an array of strings."

    agent = SubAgent(
        runtime.provider,
        registry=runtime.registry,
        guard=runtime.guard,
        skills=runtime.skills,
        facts=runtime.facts,
        profile=runtime.profile,
        compressor=runtime.compressor,
        context_dir=runtime.context_dir,
        soul=runtime.soul,
        engine=runtime.engine,
        parent_run_id=runtime.parent_run_id,
    )
    results = await run_parallel([agent] * len(tasks), tasks)

    lines: list[str] = []
    for index, result in enumerate(results, 1):
        status = "OK" if result.success else "FAILED"
        lines.append(f"[{index}] {status}: {result.output}")
    return "\n".join(lines)
