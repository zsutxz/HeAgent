"""Sub-Agent 委派工具 — 供 LLM 将任务委派给隔离的子 Agent。

通过 configure_subagent_tools(provider, registry, guard) 注入依赖。
未配置时所有工具返回错误提示，不会抛异常。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from heagent.agent.sub import SubAgent, run_parallel
from heagent.tools.decorator import tool

if TYPE_CHECKING:
    from heagent.providers.base import BaseProvider
    from heagent.tools.registry import ToolRegistry
    from heagent.tools.safety import SafetyGuard

_provider: BaseProvider | None = None
_registry: ToolRegistry | None = None
_guard: SafetyGuard | None = None


def configure_subagent_tools(
    provider: BaseProvider,
    *,
    registry: ToolRegistry | None = None,
    guard: SafetyGuard | None = None,
) -> None:
    """注入 Provider 和 Registry，激活 sub-agent 工具。"""
    global _provider, _registry, _guard
    _provider = provider
    _registry = registry
    _guard = guard


def reset_subagent_tools() -> None:
    """重置模块级依赖（测试清理用）。"""
    global _provider, _registry, _guard
    _provider = None
    _registry = None
    _guard = None


@tool
async def task_delegate(task: str) -> str:
    """将一个任务委派给隔离的子 Agent 执行。
    子 Agent 拥有独立的上下文和迭代预算，不会干扰主对话。
    适用于将复杂任务拆分、独立验证或并行处理。

    参数：
        task: 要委派给子 Agent 执行的任务描述
    """
    if _provider is None:
        return "Error: sub-agent tools not configured."

    agent = SubAgent(
        _provider,
        registry=_registry,
        guard=_guard,
    )
    result = await agent.run(task)
    if result.success:
        return f"Sub-agent completed (iterations: {result.iterations}):\n{result.output}"
    return f"Sub-agent failed: {result.output}"


@tool
async def task_parallel(tasks_json: str) -> str:
    """并行执行多个子任务。每个任务在独立的子 Agent 中运行。
    所有任务同时开始，全部完成后汇总结果。

    参数：
        tasks_json: JSON 数组格式的任务列表，如 '["任务1", "任务2"]'
    """
    if _provider is None:
        return "Error: sub-agent tools not configured."

    try:
        tasks = json.loads(tasks_json)
    except (json.JSONDecodeError, TypeError):
        return "Error: tasks_json must be a valid JSON array of strings."

    if not isinstance(tasks, list) or not tasks:
        return "Error: tasks_json must be a non-empty JSON array."

    agents = [
        SubAgent(_provider, registry=_registry, guard=_guard)
        for _ in tasks
    ]
    results = await run_parallel(agents, tasks)

    lines: list[str] = []
    for i, r in enumerate(results):
        status = "OK" if r.success else "FAILED"
        lines.append(f"[{i + 1}] {status}: {r.output}")
    return "\n".join(lines)
