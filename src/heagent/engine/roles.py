"""角色化子 Agent 的命名角色规格（roles）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12，对应 P1 / P2）。

一个 :class:`RoleSpec` 把「系统提示词」与「执行级工具策略」（``allowed_tools`` /
``blocked_tools``）打包在一起。运行时 :class:`~heagent.agent.sub.SubAgent` 依据规格构建
**角色专属**的 :class:`~heagent.engine.policy.PolicyEngine`，使越权工具调用被
``ToolExecutor`` 在执行级拦截（设计决策 D1：执行级 allowlist，而非 schema 级屏蔽——工具
仍对模型可见，但调用会被 policy 阻断并回执错误结果，模型可据此纠正）。

内置四种角色（planner / coder / tester / supervisor），在模块导入时注册到进程级
``_REGISTRY``；亦可经 :func:`register_role` 扩展自定义角色。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RoleSpec(BaseModel):
    """角色化 agent 的声明式规格。

    字段与 :class:`~heagent.engine.policy.PolicyEngine` 构造参数对齐，故一份规格可直接
    映射为「每 agent 一份」的 policy（``allowed_tools`` 作为白名单）。
    """

    name: str
    # 角色系统提示词（注入为该子 Agent 的 system message）。
    system: str
    # 允许的工具白名单；越权调用被 policy BLOCKED（D1：执行级拦截）。
    allowed_tools: list[str] = Field(default_factory=list)
    # 显式黑名单（额外阻断）。
    blocked_tools: list[str] = Field(default_factory=list)
    # 该角色子 Agent 的最大迭代轮次。
    max_iterations: int = 20
    # 沙箱配置名（可选）；为 None 表示不强制沙箱。
    sandbox_profile: str | None = None
    # 附加元数据（如角色描述、标签）。
    metadata: dict[str, str] = Field(default_factory=dict)


# 进程级角色注册表：name → RoleSpec。模块导入时填入内置角色。
_REGISTRY: dict[str, RoleSpec] = {}


def register_role(spec: RoleSpec) -> None:
    """注册或替换一个命名角色规格（进程级全局）。"""
    _REGISTRY[spec.name] = spec


def get_role(name: str) -> RoleSpec:
    """按名字查找已注册的角色规格；未知则抛 ``KeyError``（消息列出全部已注册角色）。"""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"Unknown role {name!r}. Registered roles: {sorted(_REGISTRY)}") from None


def list_roles() -> list[str]:
    """返回全部已注册角色的名字（排序）。"""
    return sorted(_REGISTRY)


# --- 内置角色系统提示词（中文；仅声明各角色职责与可用工具，运行时不改）---

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
    """构造四种内置角色（planner / coder / tester / supervisor）及其工具白名单与迭代上限。"""
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


# 模块导入时注册内置角色（一次性，进程级生效）。
for _spec in _builtin_roles():
    register_role(_spec)
