"""子 Agent 执行工具 —— 把一个委派子任务放进隔离的 loop 中跑。

主 Agent（``AgentLoop``）通过工具（``subagent`` 工具族）把子任务委派给
``SubAgent``。每个 ``SubAgent`` 拥有独立的循环实例、独立的运行上下文
（``RunContext``，挂在父 run 之下），并可按角色（``RoleSpec``）收敛可用工具集
与最大迭代数，从而在受限沙箱里完成「检索/分析/草拟」这类辅助任务，再把结果
交回主循环。本模块提供：

  - :class:`SubAgent`      —— 单个委派任务的隔离执行器；
  - :class:`SubAgentResult`—— 一次委派任务的返回结构；
  - :func:`run_parallel`   —— 并发执行多个子任务。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from heagent.agent.loop import AgentLoop
from heagent.config import get_settings
from heagent.engine import EngineContainer
from heagent.engine.policy import PolicyEngine
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard

if TYPE_CHECKING:
    from heagent.context.compressor import ContextCompressor
    from heagent.context.window_reset import WindowResetConfig
    from heagent.engine.roles import RoleSpec
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore
    from heagent.memory.soul import SoulStore
    from heagent.providers.base import BaseProvider


@dataclass
class SubAgentResult:
    """一次委派子任务的返回结果（dataclass：轻量内部结构，无需序列化/校验）。"""

    task: str  # 委派给子 Agent 的原始任务描述
    output: str  # 子 Agent 的产出（成功时为最终回答，失败时为异常文本）
    success: bool  # 子任务是否成功完成
    iterations: int = 0  # 子 loop 实际跑的迭代轮数
    run_id: str = ""  # 子任务的运行 ID（挂在父 run 之下，便于追踪/恢复）


class SubAgent:
    """委派子任务的隔离执行器。

    复用父 Agent 的 provider / 工具注册表 / 记忆存储等组件，但每次 ``run()``
    都会创建一个**全新的** ``AgentLoop`` 实例与**独立的** ``RunContext``，
    因此子任务的状态、消息历史与运行记录互不污染。

    可选的 ``role``（``RoleSpec``）会一次性收敛本次委派的「系统提示词 / 可用
    工具 / 迭代上限」；显式传入的 ``system`` / ``allowed_tools`` /
    ``blocked_tools`` / ``max_iterations`` 若非 None，则**覆盖** role 的对应字段。
    """

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
        window_reset: WindowResetConfig | None = None,
    ) -> None:
        # 组件依赖：缺省时回退到全局默认（与 AgentLoop 的兜底策略一致）。
        self._provider = provider
        self._registry = registry or ToolRegistry.get()
        self._guard = guard or SafetyGuard(blocked_tools=get_settings().safety_blocked_tools)
        self._skills = skills
        self._facts = facts
        self._profile = profile
        self._compressor = compressor
        self._context_dir = context_dir
        self._soul = soul
        self._engine = engine or EngineContainer.default(workspace_root=context_dir)
        self._parent_run_id = parent_run_id
        self._role = role
        self._window_reset = window_reset

        # 以下四项遵循「显式参数 > role 默认 > 内置默认」的优先级解析。
        # 1) 系统提示词：显式 system 优先，否则取 role.system。
        self._system = system or (role.system if role is not None else None)
        # 2) 允许工具白名单：显式参数优先；否则继承 role.allowed_tools（为空则 None=不限制）。
        self._allowed_tools = (
            allowed_tools
            if allowed_tools is not None
            else (list(role.allowed_tools) if role is not None and role.allowed_tools else None)
        )
        # 3) 禁用工具黑名单：同上。
        self._blocked_tools = (
            blocked_tools
            if blocked_tools is not None
            else (list(role.blocked_tools) if role is not None and role.blocked_tools else None)
        )
        # 4) 最大迭代数：显式参数 > role.max_iterations > 内置默认 20（子任务通常更短）。
        self._max_iterations = (
            max_iterations if max_iterations is not None else (role.max_iterations if role is not None else 20)
        )

    def _build_engine(self) -> EngineContainer:
        """构造本次子任务的 engine：在角色限定工具时，替换出一个角色专属策略。

        若本委派未限定工具（allowed/blocked 均为 None），直接复用父 engine。
        否则克隆父 ``PolicyEngine``，只改写工具白/黑名单——其余运行时服务
        （run_store / ledger / events）原样继承，使子任务的运行记录、事件流
        仍挂在同一治理体系下。

        白名单取「父允许 ∩ 角色允许」的交集（只能更严，不能放宽）；
        黑名单取「父禁止 ∪ 角色禁止」的并集（叠加禁用）。
        """
        if self._allowed_tools is None and self._blocked_tools is None:
            return self._engine
        parent_policy = self._engine.policy
        # —— 白名单：父级有白名单时取交集，否则直接用角色的；都没有则 None（不限制）。
        inherited_allowed = None
        if parent_policy.allowed_tools is not None:
            inherited_allowed = set(parent_policy.allowed_tools)
        if self._allowed_tools is not None:
            role_allowed = set(self._allowed_tools)
            inherited_allowed = role_allowed if inherited_allowed is None else inherited_allowed & role_allowed
        # —— 黑名单：在父级黑名单基础上叠加角色黑名单。
        inherited_blocked = set(parent_policy.blocked_tools)
        if self._blocked_tools:
            inherited_blocked.update(self._blocked_tools)
        role_policy = PolicyEngine(
            workspace_root=parent_policy.workspace_root,
            allowed_tools=sorted(inherited_allowed) if inherited_allowed is not None else None,
            blocked_tools=sorted(inherited_blocked),
            approval_tools=sorted(parent_policy.approval_tools),
            sandbox_tools=sorted(parent_policy.sandbox_tools),
            sandbox_profiles=dict(parent_policy.sandbox_profiles),
            block_mcp_tools=parent_policy.block_mcp_tools,
            approval_mcp_tools=parent_policy.approval_mcp_tools,
            sandbox_mcp_tools=parent_policy.sandbox_mcp_tools,
        )
        # dataclasses.replace：以 role_policy 覆写 policy 字段，其余字段保持不变。
        return replace(self._engine, policy=role_policy)

    async def run(self, task: str) -> SubAgentResult:
        """在一个全新的 loop 实例中跑完一次委派子任务，返回结构化结果。

        流程：
          1. 用 ``_build_engine`` 得到（可能收敛过工具集的）engine；
          2. 建一个挂在父 run 之下的独立 ``RunContext``（metadata 标记 kind/role）；
          3. 构造全新 ``AgentLoop``——若传入 ``window_reset`` 则启用跨窗口续跑
             （长任务场景），否则走就地压缩（默认）；
          4. 调 ``loop.run`` 执行，成功/失败都包装成 ``SubAgentResult`` 返回
             （失败不抛出，而是 success=False、output=异常文本，便于父循环处理）。
        """
        engine = self._build_engine()
        metadata: dict[str, object] = {"kind": "subagent"}
        if self._role is not None:
            metadata["role"] = self._role.name
        # 上下文管理：window_reset 优先（长任务跨窗口续跑）；否则走 in-place 压缩（默认）。
        compressor = None
        window_reset = self._window_reset
        if window_reset is None:
            compressor = self._compressor
            if compressor is None:
                from heagent.context.compressor import ContextCompressor
                compressor = ContextCompressor(self._provider)
        loop = AgentLoop(
            self._provider,
            registry=self._registry,
            guard=self._guard,
            max_iterations=self._max_iterations,
            skills=self._skills,
            facts=self._facts,
            profile=self._profile,
            compressor=compressor,
            window_reset=window_reset,
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
                run_id=loop.last_run_context.run_id if loop.last_run_context else "",
            )
        except Exception as exc:
            # 捕获所有异常：子任务失败不中断父循环，而是以失败结果回传。
            return SubAgentResult(
                task=task,
                output=str(exc),
                success=False,
                iterations=loop.last_iteration or 0,
                run_id=loop.last_run_context.run_id if loop.last_run_context else "",
            )


async def run_parallel(agents: list[SubAgent], tasks: list[str]) -> list[SubAgentResult]:
    """并发执行多个子任务。

    ``agents`` 与 ``tasks`` 按位置一一对应（``zip(..., strict=True)`` 保证
    长度一致，否则报错）；用 ``asyncio.gather`` 同时调度，等待全部完成后
    按原顺序返回各自的结果。
    """
    coroutines = [agent.run(task) for agent, task in zip(agents, tasks, strict=True)]
    return await asyncio.gather(*coroutines)
