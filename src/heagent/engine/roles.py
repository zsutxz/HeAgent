"""Named role specs for role-specialized sub-agents.

A ``RoleSpec`` bundles a system prompt with an execution-level tool policy
(``allowed_tools`` / ``blocked_tools``). At run time the :class:`SubAgent` builds a
role-specific :class:`~heagent.engine.policy.PolicyEngine` from the spec so
out-of-role tool calls are blocked by the engine's ``ToolExecutor`` (design
decision D1: execution-level allowlist, not schema-level masking).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RoleSpec(BaseModel):
    """Declarative spec for a role-specialized agent.

    Fields align with :class:`~heagent.engine.policy.PolicyEngine` constructor
    kwargs so a spec can be mapped onto a per-agent policy.
    """

    name: str
    system: str
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    max_iterations: int = 20
    sandbox_profile: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


_REGISTRY: dict[str, RoleSpec] = {}


def register_role(spec: RoleSpec) -> None:
    """Register or replace a named role spec (process-global)."""
    _REGISTRY[spec.name] = spec


def get_role(name: str) -> RoleSpec:
    """Look up a registered role spec by name; raise ``KeyError`` if unknown."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown role {name!r}. Registered roles: {sorted(_REGISTRY)}"
        ) from None


def list_roles() -> list[str]:
    """Return the names of all registered roles, sorted."""
    return sorted(_REGISTRY)


_PLANNER_SYSTEM = """\
你是【计划角色 Planner】。职责：分析任务、拆解为可执行步骤、规划实现路径。只读不写、不执行副作用操作。

可用工具（仅这些，调用其他工具会被拦截）：
- file_read：阅读现有文件
- file_search：按文件名查找
- content_search：按内容查找

输出一份清晰的分步计划（步骤 + 每步负责的角色 + 验收标准）。"""

_CODER_SYSTEM = """\
你是【编程角色 Coder】。职责：按计划实现代码，保持简洁、匹配既有风格。写完即止，不自测（交 Tester）。

可用工具（仅这些）：
- file_read / file_write：读写文件
- file_search / content_search：查找
- shell：执行构建 / 格式化命令

遵循项目代码规范（PEP8、Pydantic、异步、120 行宽）。"""

_TESTER_SYSTEM = """\
你是【测试角色 Tester】。职责：为已实现的代码写测试并运行，报告通过 / 失败与根因。

可用工具（仅这些）：
- file_read：读被测代码
- content_search：定位
- shell：运行 pytest

测试验证意图（捕捉逻辑失效），不仅跑通流程。"""

_SUPERVISOR_SYSTEM = """\
你是【调度角色 Supervisor】。职责：把任务拆解为子任务，委派给专业角色执行，汇总结果。不直接写代码 / 跑测试。

可用工具（仅这些）：
- task_delegate：把单个子任务委派给一个角色（planner / coder / tester）
- task_parallel：并发委派多个同类型子任务
- task_status：查看本 run 已完成的委派步骤（上下文被清理后仍可查）

编排规则：
1. 先想清楚要哪些角色、各做什么，再委派（一次别塞太多）。
2. 典型链路：planner 拆步骤 → coder 实现 → tester 验证。
3. 每步委派返回后，依结果决定下一步：通过则继续，失败则让对应角色修复。
4. 全部完成后，汇总成最终答案交给用户。"""


def _builtin_roles() -> list[RoleSpec]:
    return [
        RoleSpec(
            name="planner",
            system=_PLANNER_SYSTEM,
            allowed_tools=["file_read", "file_search", "content_search"],
            max_iterations=15,
        ),
        RoleSpec(
            name="coder",
            system=_CODER_SYSTEM,
            allowed_tools=["file_read", "file_write", "file_search", "content_search", "shell"],
            max_iterations=25,
        ),
        RoleSpec(
            name="tester",
            system=_TESTER_SYSTEM,
            allowed_tools=["file_read", "content_search", "shell"],
            max_iterations=20,
        ),
        RoleSpec(
            name="supervisor",
            system=_SUPERVISOR_SYSTEM,
            allowed_tools=["task_delegate", "task_parallel", "task_status"],
            max_iterations=30,
        ),
    ]


for _spec in _builtin_roles():
    register_role(_spec)
