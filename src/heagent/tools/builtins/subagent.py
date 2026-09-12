"""Builtin tools for delegating work to sub-agents.

工具层只持有「怎么委派」的可注入异步回调（:data:`DelegateOne` /
:data:`DelegateMany`）与 run 作用域数据（``run_context`` / ``roles``），
**不认识**具体的子 Agent 实现——真实编排由 ``agent`` 层提供
（``agent.delegation.build_subagent_delegates``），经 ``AgentLoop`` 在每次 run
的作用域内绑定。这样 ``tools`` 不再反向依赖 ``agent``（架构硬约束：新增工具
禁止从 ``agent/`` 导入）。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from heagent.engine.roles import RoleSpec, get_role, list_roles
from heagent.tools.decorator import tool
from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from heagent.engine.context import RunContext


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


# 委派回调协议：由 agent 层实现并注入（工具层不构造 SubAgent，也不导入 agent 层）。
# delegate_one(task, role_spec, system) -> 单任务结构化结果
DelegateOne = Callable[[str, RoleSpec | None, str | None], Awaitable[SubTaskOutcome]]
# delegate_many(tasks, role_spec, system) -> 与 tasks 等长且保序的结果列表
DelegateMany = Callable[[list[str], RoleSpec | None, str | None], Awaitable[list[SubTaskOutcome]]]


def _error_payload(message: str) -> str:
    """Serialize a pre-flight error as a structured JSON string."""
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


@dataclass(slots=True)
class SubagentToolRuntime:
    """Runtime dependencies for sub-agent delegation tools.

    只保存注入进来的委派回调、本次 run 的作用域数据与递归深度预算；
    ``delegate_one`` / ``delegate_many`` 为 None 表示未绑定运行时（工具返回
    ``status=error``，不构造任何子 Agent）。``depth`` 是当前 loop 所处的委派
    深度，``max_depth`` 来自 ``Settings.subagent_max_depth``——``depth >=
    max_depth`` 时委派工具直接返回结构化错误，防止 LLM 自我委派无限递归。
    """

    delegate_one: DelegateOne | None = None
    delegate_many: DelegateMany | None = None
    run_context: RunContext | None = None
    roles: dict[str, RoleSpec] | None = None
    depth: int = 0
    max_depth: int = 3


_subagent_runtime = RuntimeSlot[SubagentToolRuntime]("heagent_subagent_tools")


def configure_subagent_tools(
    delegate_one: DelegateOne | None = None,
    delegate_many: DelegateMany | None = None,
    *,
    run_context: RunContext | None = None,
    roles: dict[str, RoleSpec] | None = None,
    depth: int = 0,
    max_depth: int = 3,
) -> None:
    """Set fallback delegation callbacks for sub-agent tools."""
    _subagent_runtime.configure(
        SubagentToolRuntime(
            delegate_one=delegate_one,
            delegate_many=delegate_many,
            run_context=run_context,
            roles=roles,
            depth=depth,
            max_depth=max_depth,
        )
    )


def reset_subagent_tools() -> None:
    """Clear fallback sub-agent tool dependencies."""
    _subagent_runtime.reset()


@contextmanager
def bind_subagent_tools(
    delegate_one: DelegateOne | None = None,
    delegate_many: DelegateMany | None = None,
    *,
    run_context: RunContext | None = None,
    roles: dict[str, RoleSpec] | None = None,
    depth: int = 0,
    max_depth: int = 3,
) -> Iterator[None]:
    """Bind sub-agent delegation callbacks for the current run context."""
    with _subagent_runtime.bind(
        SubagentToolRuntime(
            delegate_one=delegate_one,
            delegate_many=delegate_many,
            run_context=run_context,
            roles=roles,
            depth=depth,
            max_depth=max_depth,
        )
    ):
        yield


def _runtime() -> SubagentToolRuntime | None:
    return _subagent_runtime.get()


_DELEGATION_FALLBACK = (
    " If a context-free reviewer is still required (e.g. bmad-build review layers), write every child "
    "prompt verbatim to `_bmad-output/implementation-artifacts/` and HALT, so a human can run each one "
    "in a separate session."
)


def _depth_limit_error(runtime: SubagentToolRuntime) -> str | None:
    """Return an error message when the delegation depth budget is exhausted.

    ``depth`` is the current loop's nesting level (root=0, each SubAgent level
    +1); ``max_depth`` is the configured ceiling. Reaching the ceiling makes
    both delegation tools fail fast with a structured error instead of spawning
    another sub-agent, which bounds self-delegation recursion.
    """
    if runtime.depth < runtime.max_depth:
        return None
    return (
        f"sub-agent delegation depth limit reached (depth={runtime.depth}, "
        f"max_depth={runtime.max_depth}); finish the task in the current agent "
        "instead of delegating further." + _DELEGATION_FALLBACK
    )


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


@tool
async def task_delegate(task: str, role: str = "", system: str = "") -> str:
    """Delegate one task to an isolated sub-agent.

    Pass ``role`` (e.g. planner/coder/tester) for a role-specialized agent, or
    ``system`` for a custom system prompt. With neither, a plain sub-agent runs.
    Returns a JSON object (``status`` ∈ ok/failed/error) so the supervisor can
    parse the outcome programmatically.
    """
    runtime = _runtime()
    if runtime is None or runtime.delegate_one is None:
        return _error_payload("sub-agent tools not configured." + _DELEGATION_FALLBACK)

    depth_error = _depth_limit_error(runtime)
    if depth_error is not None:
        return _error_payload(depth_error)

    spec, err = _resolve_role(runtime, role)
    if err is not None:
        return _error_payload(err)

    outcome = await runtime.delegate_one(task, spec, system or None)
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
    if runtime is None or runtime.delegate_many is None:
        return _error_payload("sub-agent tools not configured." + _DELEGATION_FALLBACK)

    depth_error = _depth_limit_error(runtime)
    if depth_error is not None:
        return _error_payload(depth_error)

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

    outcomes = await runtime.delegate_many(tasks, spec, system or None)
    if len(outcomes) != len(tasks):
        # 回调契约要求与 tasks 等长保序；长度不符时显性失败，避免错位记账。
        return _error_payload("delegation callback returned a mismatched outcome count.")

    for outcome in outcomes:
        _record_step(runtime, outcome=outcome)

    overall = "ok" if all(o.status == "ok" for o in outcomes) else "partial"
    return json.dumps({"status": overall, "outcomes": [o.model_dump() for o in outcomes]}, ensure_ascii=False)


@tool(read_only=True)
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
