"""Builtin tools for delegating work to sub-agents."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from heagent.agent.sub import SubAgent, run_parallel
from heagent.engine.roles import RoleSpec, get_role, list_roles
from heagent.tools.decorator import tool
from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from heagent.context.compressor import ContextCompressor
    from heagent.engine import EngineContainer
    from heagent.engine.context import RunContext
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore
    from heagent.providers.base import BaseProvider
    from heagent.tools.registry import ToolRegistry
    from heagent.tools.safety import SafetyGuard


class SubTaskOutcome(BaseModel):
    """Structured outcome of one delegated sub-task (machine-parseable JSON).

    ``task_delegate`` returns one of these serialized; ``task_parallel`` returns
    ``{"status": ..., "outcomes": [...]}``. Pre-flight errors from either tool
    return ``{"status": "error", "message": ...}`` so every tool response is a
    JSON object carrying a ``status`` field.
    """

    status: Literal["ok", "failed"]
    role: str = ""
    task: str
    iterations: int = 0
    run_id: str = ""
    output: str


def _error_payload(message: str) -> str:
    """Serialize a pre-flight error as a structured JSON string."""
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


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
    run_context: RunContext | None = None
    roles: dict[str, RoleSpec] | None = None
    default_system: str | None = None


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
    run_context: RunContext | None = None,
    roles: dict[str, RoleSpec] | None = None,
    default_system: str | None = None,
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
            run_context=run_context,
            roles=roles,
            default_system=default_system,
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
    run_context: RunContext | None = None,
    roles: dict[str, RoleSpec] | None = None,
    default_system: str | None = None,
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
            run_context=run_context,
            roles=roles,
            default_system=default_system,
        )
    ):
        yield


def _runtime() -> SubagentToolRuntime | None:
    return _subagent_runtime.get()


def _resolve_role(runtime: SubagentToolRuntime, role: str) -> tuple[RoleSpec | None, str | None]:
    """Resolve a role name to a spec via the runtime map, then the global registry.

    Returns ``(spec, error)``; an empty ``role`` yields ``(None, None)``.
    """
    if not role:
        return None, None
    roles = runtime.roles or {}
    if role in roles:
        return roles[role], None
    try:
        return get_role(role), None
    except KeyError:
        available = sorted({*roles, *list_roles()})
        return None, f"Unknown role {role!r}. Available: {available}"


def _record_step(runtime: SubagentToolRuntime, *, outcome: SubTaskOutcome) -> None:
    """Append one delegation outcome to the supervisor run's metadata.

    Stored under ``completed_steps`` so it survives context window resets
    (metadata persists; tool-result messages may be summarized away).
    """
    if runtime.run_context is None:
        return
    steps = runtime.run_context.metadata.setdefault("completed_steps", [])
    steps.append(
        {
            "role": outcome.role,
            "task": outcome.task,
            "success": outcome.status == "ok",
            "iterations": outcome.iterations,
            "run_id": outcome.run_id,
            "output": outcome.output[:500],
        }
    )


def _make_subagent(runtime: SubagentToolRuntime, spec: RoleSpec | None, system: str | None) -> SubAgent:
    """Construct a SubAgent from the current runtime slot (shared factory for task_parallel)."""
    return SubAgent(
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
        role=spec,
        system=system,
    )


@tool
async def task_delegate(task: str, role: str = "", system: str = "") -> str:
    """Delegate one task to an isolated sub-agent.

    Pass ``role`` (e.g. planner/coder/tester) for a role-specialized agent, or
    ``system`` for a custom system prompt. With neither, a plain sub-agent runs.
    Returns a JSON object (``status`` ∈ ok/failed/error) so the supervisor can
    parse the outcome programmatically.
    """
    runtime = _runtime()
    if runtime is None or runtime.provider is None:
        return _error_payload("sub-agent tools not configured.")

    spec, err = _resolve_role(runtime, role)
    if err is not None:
        return _error_payload(err)
    agent = _make_subagent(runtime, spec, system or None)
    result = await agent.run(task)
    outcome = SubTaskOutcome(
        status="ok" if result.success else "failed",
        role=spec.name if spec else "",
        task=task,
        iterations=result.iterations,
        run_id=result.run_id,
        output=result.output,
    )
    _record_step(runtime, outcome=outcome)
    return outcome.model_dump_json()


@tool
async def task_parallel(tasks_json: str, role: str = "", system: str = "") -> str:
    """Run multiple sub-agent tasks concurrently (same role/system for all).

    Returns ``{"status": "ok"|"partial"|"error", "outcomes": [...]}`` where each
    entry is a :class:`SubTaskOutcome`; ``ok`` means every task succeeded,
    ``partial`` means at least one failed.
    """
    runtime = _runtime()
    if runtime is None or runtime.provider is None:
        return _error_payload("sub-agent tools not configured.")

    try:
        tasks = json.loads(tasks_json)
    except (json.JSONDecodeError, TypeError):
        return _error_payload("tasks_json must be a valid JSON array of strings.")

    if not isinstance(tasks, list) or not tasks:
        return _error_payload("tasks_json must be a non-empty JSON array.")
    if not all(isinstance(task, str) for task in tasks):
        return _error_payload("tasks_json must be an array of strings.")

    spec, err = _resolve_role(runtime, role)
    if err is not None:
        return _error_payload(err)
    # 为每个 task 创建独立的 SubAgent 实例（P1-1 修复：原 [agent] * len(tasks) 创建同一对象
    # 的多份引用，并发 task 竞态读写同一 SubAgent 内部状态会导致数据竞态）。
    agents = [_make_subagent(runtime, spec, system or None) for _ in tasks]
    results = await run_parallel(agents, tasks)

    role_name = spec.name if spec else ""
    outcomes = [
        SubTaskOutcome(
            status="ok" if result.success else "failed",
            role=role_name,
            task=task_text,
            iterations=result.iterations,
            run_id=result.run_id,
            output=result.output,
        )
        for task_text, result in zip(tasks, results, strict=True)
    ]
    for outcome in outcomes:
        _record_step(runtime, outcome=outcome)

    overall = "ok" if all(o.status == "ok" for o in outcomes) else "partial"
    return json.dumps({"status": overall, "outcomes": [o.model_dump() for o in outcomes]}, ensure_ascii=False)


@tool
async def task_status() -> str:
    """List delegation steps completed in this run (survives context resets)."""
    runtime = _runtime()
    if runtime is None or runtime.run_context is None:
        return "No run context available."
    steps = runtime.run_context.metadata.get("completed_steps", [])
    if not steps:
        return "尚无已完成的委派步骤。"
    lines: list[str] = []
    for index, step in enumerate(steps, 1):
        status = "OK" if step.get("success") else "FAILED"
        lines.append(f"[{index}] role={step.get('role', '?')} {status}: {step.get('task', '')}")
    return "\n".join(lines)
