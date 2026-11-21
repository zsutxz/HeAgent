"""HeAgent 异常层次与统一错误码。

层次（:class:`HeAgentError` 为根，中间一层是**分类**，具体异常挂在分类下）::

    HeAgentError
    ├── ProviderError                  提供方调用
    │   ├── ProviderAuthError
    │   ├── ProviderRateLimitError
    │   ├── ProviderTimeoutError
    │   └── ProviderResponseFormatError
    ├── ToolError                      工具执行
    │   ├── ToolArgumentError
    │   ├── ToolExecutionError
    │   ├── UnknownToolError
    │   ├── SafetyViolation
    │   └── McpSdkMissingError
    ├── EngineError                    运行时治理（policy / ledger / workflow / 存储写冲突）
    │   ├── PolicyViolation
    │   ├── LedgerError
    │   ├── PolicyExecutionError
    │   ├── WorkflowExecutionError
    │   └── FactCompactConflictError
    ├── AgentError                     循环与委派
    │   ├── BudgetExceeded
    │   │   └── IterationLimitError
    │   ├── SubAgentError
    │   └── AgentResumeError
    ├── SessionError                   会话文件存取
    │   ├── SessionConflictError
    │   ├── SessionNotFoundError
    │   └── SessionUnreadableError
    └── ConfigurationError             配置面错配（键值不合法 / 名字不在池里）
        └── InputValidationError

分类层的用途是「一整类可 catch」：``except ToolError`` 覆盖全部工具异常，``except
HeAgentError`` 覆盖全部框架异常。

**错误码**：每个类带 ``code: ClassVar[str]``（形态 ``E_<分类>_<具体>``），实例经
``exc.code`` 读到同一个值。码一经发布不改名、不复用（只增）；非框架异常由
:func:`error_code_of` 统一兜底为 ``E_UNKNOWN`` 而不抛。:func:`error_catalog` 给出
「码 → 类名 / 描述 / 建议」的程序化清单，``docs/errors.md`` 的码表由测试与本清单
**逐条**比对（不手抄第二份）。

**兼容约定**：

- ``HeAgentException`` 是 :class:`HeAgentError` 的别名（旧称），不是第二个基类。
- 部分新异常与旧内置异常多继承（如 ``LedgerError(EngineError, ValueError)``）：让既有
  ``except ValueError`` / ``except RuntimeError`` 调用点不必改动就继续捕获到它们。
  分类祖先仍然只有一个——多出来的那个是内置异常，不是分类。

本模块属 ``pub/`` 层：只依赖标准库与 pydantic。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from heagent.pub.validation import ValidationIssue

__all__ = [
    "AgentError",
    "AgentResumeError",
    "BudgetExceeded",
    "ConfigurationError",
    "EngineError",
    "ERROR_FAMILIES",
    "FactCompactConflictError",
    "HeAgentError",
    "HeAgentException",
    "InputValidationError",
    "IterationLimitError",
    "LedgerError",
    "McpSdkMissingError",
    "PolicyExecutionError",
    "PolicyViolation",
    "ProviderAuthError",
    "ProviderError",
    "ProviderRateLimitError",
    "ProviderResponseFormatError",
    "ProviderTimeoutError",
    "SafetyViolation",
    "SessionConflictError",
    "SessionError",
    "SessionNotFoundError",
    "SessionUnreadableError",
    "SubAgentError",
    "ToolArgumentError",
    "ToolError",
    "ToolExecutionError",
    "UnknownToolError",
    "WorkflowExecutionError",
    "error_catalog",
    "error_code_of",
]

#: 未知异常的兜底码（不进 ``error_catalog()``：它不对应任何类）。
UNKNOWN_ERROR_CODE = "E_UNKNOWN"


class HeAgentError(Exception):
    """框架异常的根类。"""

    code: ClassVar[str] = "E_HEAGENT"
    description: ClassVar[str] = "框架内部错误的通用形态，未归入任何分类时才会直接出现"
    suggestion: ClassVar[str] = "按具体子类处理；只有它本身说明该错误尚未归类"

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(message)


# ── Provider 分类 ────────────────────────────────────────────────


class ProviderError(HeAgentError):
    """Provider 调用失败（分类层；也用于「重试耗尽 / 全部 provider 失败」这类具体错误）。"""

    code: ClassVar[str] = "E_PROVIDER"
    description: ClassVar[str] = "Provider 调用失败，已用尽重试与回退"
    suggestion: ClassVar[str] = (
        "看日志 provider_call_completed 的 details.model 与上游状态码；认证问题核对该条目的 *_API_KEY"
    )

    def __init__(self, message: str = "", *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderAuthError(ProviderError):
    """Provider 认证失败（401 / 403）。"""

    code: ClassVar[str] = "E_PROVIDER_AUTH"
    description: ClassVar[str] = "Provider 认证失败（401 / 403）"
    suggestion: ClassVar[str] = "核对 .env 里该条目的 *_API_KEY；池内换档刻意不覆盖认证失败（属配置问题）"


class ProviderRateLimitError(ProviderError):
    """Provider 限流（429 / rate 关键词）。"""

    code: ClassVar[str] = "E_PROVIDER_RATE_LIMIT"
    description: ClassVar[str] = "Provider 限流（429 或响应体命中 rate 关键词）"
    suggestion: ClassVar[str] = "等限流窗口重置；回退链会自动换 provider / 密钥，也可 /provider 手工切"


class ProviderTimeoutError(ProviderError):
    """Provider 超时（408 / 504 或超时类消息）。"""

    code: ClassVar[str] = "E_PROVIDER_TIMEOUT"
    description: ClassVar[str] = "Provider 调用超时（408 / 504 或消息命中超时关键词）"
    suggestion: ClassVar[str] = "重试该调用；持续超时查网络与中转站健康度，必要时 /provider 换一家"


class ProviderResponseFormatError(ProviderError):
    """Provider 返回体不符合预期形状（缺 choices 等）。"""

    code: ClassVar[str] = "E_PROVIDER_RESPONSE_FORMAT"
    description: ClassVar[str] = "Provider 返回体形状不符合预期（如 choices 为空）"
    suggestion: ClassVar[str] = "确认上游是否兼容中转站（响应契约漂移）；换官方端点或换 provider"


# ── Tool 分类 ────────────────────────────────────────────────────


class ToolError(HeAgentError):
    """工具执行失败（分类层）。"""

    code: ClassVar[str] = "E_TOOL"
    description: ClassVar[str] = "工具执行失败（分类层，具体原因看子类）"
    suggestion: ClassVar[str] = "读工具返回正文（is_error=true）；路径类错误见 docs/faq.md 故障排查"


class ToolArgumentError(ToolError, ValueError):
    """工具参数不合法（缺必填 / 形状不对）。

    与 ``ValueError`` 多继承：参数校验失败此前抛 ``ValueError``，保留内置基类让既有
    ``except ValueError`` 调用点与测试无需改动。
    """

    code: ClassVar[str] = "E_TOOL_ARGUMENT"
    description: ClassVar[str] = "工具参数不合法（缺必填参数或参数形状不对）"
    suggestion: ClassVar[str] = "按工具 Schema 补参数；文件类工具的路径须过 path_safety（工作区相对路径）"


class ToolExecutionError(ToolError):
    """工具已开始执行但失败（超时 / 连接断开等）。"""

    code: ClassVar[str] = "E_TOOL_EXECUTION"
    description: ClassVar[str] = "工具开始执行后失败（调用超时、server 断连等）"
    suggestion: ClassVar[str] = "读工具返回正文；MCP 工具查 server 连接状态与 call_timeout 配置"


class UnknownToolError(ToolError):
    """调用了未注册或未启用的工具名。"""

    code: ClassVar[str] = "E_TOOL_UNKNOWN"
    description: ClassVar[str] = "调用了未注册或未启用的工具名"
    suggestion: ClassVar[str] = "核对工具名；确认该工具已注册且未被 ALLOWED_TOOLS / BLOCKED_TOOLS 过滤"


class SafetyViolation(ToolError):
    """SafetyGuard 拦下了这次工具调用（未执行）。"""

    code: ClassVar[str] = "E_TOOL_SAFETY_VIOLATION"
    description: ClassVar[str] = "SafetyGuard 在 handler 之前拦下调用（危险命令 / 受保护路径）"
    suggestion: ClassVar[str] = (
        "该调用未执行；看事件 tool_call_blocked 的 details.reason 与 SAFETY_BLOCKED_TOOLS 是否误伤"
    )


class McpSdkMissingError(ToolError):
    """MCP 桥接的可选依赖（``mcp`` SDK）未安装。

    继承 ``ToolError``：MCP 工具面缺依赖属于工具能力不可用，``except ToolError`` 与既有入口层
    的 ``except HeAgentError`` 都能把它渲染成一行可执行提示，而不是裸 traceback。
    """

    code: ClassVar[str] = "E_TOOL_MCP_SDK_MISSING"
    description: ClassVar[str] = "MCP 桥接的可选依赖 mcp SDK 未安装（可选能力，不影响其余功能）"
    suggestion: ClassVar[str] = '装可选依赖：pip install "heagent[mcp]"；不要 MCP 时保持 MCP_ENABLED=false'


# ── Engine 分类 ──────────────────────────────────────────────────


class EngineError(HeAgentError):
    """运行时治理层错误（分类层：policy / ledger / workflow）。"""

    code: ClassVar[str] = "E_ENGINE"
    description: ClassVar[str] = "运行时治理层错误（分类层）"
    suggestion: ClassVar[str] = "按子类处理；治理层的拒绝一律「未执行」，先看事件流里的 details"


class PolicyViolation(EngineError):
    """PolicyEngine 在执行前拒绝了这次工具调用（未执行）。"""

    code: ClassVar[str] = "E_ENGINE_POLICY_VIOLATION"
    description: ClassVar[str] = "PolicyEngine 在 handler 之前拒绝调用（档位 / 白黑名单 / 审批未过）"
    suggestion: ClassVar[str] = (
        "该调用未执行；看 tool_call_blocked 的 details.mode；SANDBOX_MODE=read-only 会拦所有写与 shell"
    )


class LedgerError(EngineError, ValueError):
    """执行台账（幂等记录）读写失败。

    与 ``ValueError`` 多继承：台账的「记录不存在 / 不可读 / 状态不符」在引入本类之前是
    ``ValueError``，保留内置异常基类让既有 ``except ValueError`` 调用点无须改动。
    """

    code: ClassVar[str] = "E_ENGINE_LEDGER"
    description: ClassVar[str] = "执行台账（幂等记录）读写失败或记录状态不符"
    suggestion: ClassVar[str] = "查 .heagent 下的台账记录文件；台账只是幂等缓存，任务可安全重跑"


class PolicyExecutionError(EngineError, RuntimeError):
    """策略裁决已通过，但执行环境不成立（沙箱会话目录缺失）。

    与 ``RuntimeError`` 多继承：该判定此前抛 ``RuntimeError``，保留内置异常基类让既有
    ``except RuntimeError`` 调用点无须改动。
    """

    code: ClassVar[str] = "E_ENGINE_POLICY_EXECUTION"
    description: ClassVar[str] = "策略裁决通过但执行环境不成立（沙箱会话目录缺失等）"
    suggestion: ClassVar[str] = "检查 run metadata 的 sandbox_workspace；或关闭沙箱会话目录让路径恢复存在"


class WorkflowExecutionError(EngineError, ValueError):
    """工作流步骤选择 / 状态推进不合法。

    与 ``ValueError`` 多继承：该系列判定此前抛 ``ValueError``，保留内置异常基类让既有
    ``except ValueError`` 调用点无须改动。
    """

    code: ClassVar[str] = "E_ENGINE_WORKFLOW"
    description: ClassVar[str] = "工作流步骤选择或状态推进不合法"
    suggestion: ClassVar[str] = "核对 workflow 的 steps 声明与 active_step；恢复一律走 checkpoint，不猜、不静默跳过"


class FactCompactConflictError(EngineError):
    """记忆事实库在读与写之间被并发修改（compare-after-write 冲突）。

    判定语义是「整批放弃、留底不动」：宁可在下次重跑，也不覆盖别人刚写入的事实。
    """

    code: ClassVar[str] = "E_ENGINE_STORE_CONFLICT"
    description: ClassVar[str] = "存储在读与写之间被并发修改（fact_compact 的 MEMORY.md 冲突），整批放弃"
    suggestion: ClassVar[str] = "重跑 fact_compact（被移出的条目已留底）；同写 MEMORY.md 的进程需串行化"


# ── Agent 分类 ───────────────────────────────────────────────────


class AgentError(HeAgentError):
    """Agent 循环与委派错误（分类层）。"""

    code: ClassVar[str] = "E_AGENT"
    description: ClassVar[str] = "Agent 循环与子 Agent 委派错误（分类层）"
    suggestion: ClassVar[str] = "按子类处理；预算 / 上限类错误改配置或拆小任务"


class BudgetExceeded(AgentError):
    """迭代或 token 预算用尽。"""

    code: ClassVar[str] = "E_AGENT_BUDGET_EXCEEDED"
    description: ClassVar[str] = "迭代或 token 预算用尽"
    suggestion: ClassVar[str] = "调大 MAX_ITERATIONS / SUBAGENT_MAX_ITERATIONS，或把任务拆小"


class IterationLimitError(BudgetExceeded):
    """迭代硬上限用尽（本轮未给出最终回答）。"""

    code: ClassVar[str] = "E_AGENT_ITERATION_LIMIT"
    description: ClassVar[str] = "迭代硬上限用尽（本轮未给出最终回答）"
    suggestion: ClassVar[str] = "调大 MAX_ITERATIONS；或把任务拆成多轮 / 委派子 Agent"


class SubAgentError(AgentError, ValueError):
    """子 Agent 委派的请求本身不成立（如任务与 agent 数量不匹配）。

    与 ``ValueError`` 多继承：长度不匹配此前由 ``zip(strict=True)`` 抛 ``ValueError``，
    保留内置异常基类让既有 ``except ValueError`` 调用点无须改动。
    """

    code: ClassVar[str] = "E_AGENT_SUBAGENT"
    description: ClassVar[str] = "子 Agent 委派请求不成立（任务与 agent 数量不匹配等）"
    suggestion: ClassVar[str] = "核对委派调用参数；单任务走 subagent，多任务走并行委派且两列等长"


class AgentResumeError(AgentError, ValueError):
    """续跑时找不到该 run 的快照。

    与 ``ValueError`` 多继承：此前抛 ``ValueError``，保留内置异常基类让既有调用点无须改动。
    """

    code: ClassVar[str] = "E_AGENT_RESUME"
    description: ClassVar[str] = "续跑时找不到该 run 的快照"
    suggestion: ClassVar[str] = "用 run 列表里的真实 run_id；快照已被清理时只能重跑"


# ── Session 分类 ─────────────────────────────────────────────────


class SessionError(HeAgentError):
    """会话文件存取错误（分类层）。"""

    code: ClassVar[str] = "E_SESSION"
    description: ClassVar[str] = "会话文件存取错误（分类层）"
    suggestion: ClassVar[str] = "按子类处理；会话文件在 .heagent/sessions/ 下"


class SessionConflictError(SessionError):
    """会话文件在读取后被改动（乐观锁冲突）。

    只在调用方显式传 ``expected_version`` 时抛出（``SessionStore.save`` / ``rename``）；不传则维持
    既有的 last-write-wins 语义，CLI 行为因此逐字节不变（Epic 50 / Story 50-3，脊柱 I11）。
    """

    code: ClassVar[str] = "E_SESSION_CONFLICT"
    description: ClassVar[str] = "会话文件在读取后被改动（显式传 expected_version 时的乐观锁冲突）"
    suggestion: ClassVar[str] = "重新读取会话再提交；不传 expected_version 即 last-write-wins"


class SessionNotFoundError(SessionError):
    """该会话 id 没有对应的会话文件。"""

    code: ClassVar[str] = "E_SESSION_NOT_FOUND"
    description: ClassVar[str] = "该会话 id 没有对应的会话文件"
    suggestion: ClassVar[str] = "用会话列表 / 服务端返回的真实 id，不要自己拼路径"


class SessionUnreadableError(SessionError):
    """会话文件存在但无法解析。

    与「空会话」严格区分：``SessionStore.load`` 为兼容 CLI 仍对损坏文件返回空列表，而元数据读
    （``load_metadata`` / ``list_metadata`` / ``rename``）抛出本异常，由控制台映射为
    ``session_unreadable`` —— 否则网页会把损坏的会话当空会话继续写并覆盖掉原内容。
    """

    code: ClassVar[str] = "E_SESSION_UNREADABLE"
    description: ClassVar[str] = "会话文件存在但无法解析"
    suggestion: ClassVar[str] = "备份后删除 .heagent/sessions/ 下的该文件"


# ── 配置分类 ─────────────────────────────────────────────────────


class ConfigurationError(HeAgentError, ValueError):
    """配置面错配：键值不合法，或引用了池里不存在的名字。

    与 ``ValueError`` 多继承：配置校验失败此前抛 ``ValueError``，保留内置异常基类让既有
    ``except ValueError`` 调用点无须改动。
    """

    code: ClassVar[str] = "E_CONFIGURATION"
    description: ClassVar[str] = "配置面错配（键值不合法，或引用了池里不存在的名字）"
    suggestion: ClassVar[str] = "按 .env.example 对应键给合法值；heagent doctor 会逐项列出问题键"


class InputValidationError(ConfigurationError):
    """统一输入校验失败：``str()`` 逐字段列出问题，CLI / HTTP 可直接展示。

    当前唯一接入面是配置写入的字段守卫（``config/write.py::guard_reason``）——即「用户输入的
    键值不合法」；归在 ``ConfigurationError`` 下使 ``except ConfigurationError`` 能一次接住
    「值不合法」的两种表达（单条原因 vs 多字段清单）。
    """

    code: ClassVar[str] = "E_CONFIGURATION_INVALID_INPUT"
    description: ClassVar[str] = "输入校验失败（逐字段列出问题；当前接入面是配置写入守卫）"
    suggestion: ClassVar[str] = "按提示改对应字段；键名与取值域见 .env.example，全局体检跑 heagent doctor"

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)
        super().__init__("invalid input: " + "; ".join(f"{issue.field}: {issue.message}" for issue in self.issues))

    @property
    def fields(self) -> tuple[str, ...]:
        """涉及的字段名（按 issue 顺序去重）——调用方可用它高亮对应的输入项。"""
        return tuple(dict.fromkeys(issue.field for issue in self.issues))


#: ``HeAgentException`` 是旧称别名，不是第二个基类。
HeAgentException = HeAgentError


# ── 错误码清单 ───────────────────────────────────────────────────


class ErrorCatalogEntry(BaseModel):
    """``error_catalog()`` 的一条：码 + 对应类 + 描述 + 建议。"""

    code: str
    class_name: str
    description: str
    suggestion: str


#: ``error_catalog()`` 的顺序真源：根 → 各分类（分类排在它的具体异常之前）。
_CATALOG_CLASSES: tuple[type[HeAgentError], ...] = (
    HeAgentError,
    ProviderError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderResponseFormatError,
    ToolError,
    ToolArgumentError,
    ToolExecutionError,
    UnknownToolError,
    SafetyViolation,
    McpSdkMissingError,
    EngineError,
    PolicyViolation,
    LedgerError,
    PolicyExecutionError,
    WorkflowExecutionError,
    FactCompactConflictError,
    AgentError,
    BudgetExceeded,
    IterationLimitError,
    SubAgentError,
    AgentResumeError,
    SessionError,
    SessionConflictError,
    SessionNotFoundError,
    SessionUnreadableError,
    ConfigurationError,
    InputValidationError,
)


def error_catalog() -> list[ErrorCatalogEntry]:
    """返回全部框架异常的「码 → 类名 / 描述 / 建议」清单（顺序 = 层次顺序）。"""
    return [
        ErrorCatalogEntry(
            code=cls.code,
            class_name=cls.__name__,
            description=cls.description,
            suggestion=cls.suggestion,
        )
        for cls in _CATALOG_CLASSES
    ]


def error_code_of(exc: BaseException) -> str:
    """返回异常的稳定错误码；非框架异常一律 :data:`UNKNOWN_ERROR_CODE`（不抛）。"""
    if isinstance(exc, HeAgentError):
        return exc.code
    return UNKNOWN_ERROR_CODE


#: 入口兜底的显式异常族清单 = ``HeAgentError`` 的**全部直接子类**。
#:
#: 入口层刻意不写 ``except HeAgentError``：新增一个直接子类却忘了在此登记时，
#: ``tests/test_exception_families.py`` 会红——新错误类型必须被显式接纳（进而可以被赋予
#: 各自的出口行为），而不是被静默渲染成一行 ``[error]``。
ERROR_FAMILIES: tuple[type[HeAgentError], ...] = (
    ProviderError,
    ToolError,
    EngineError,
    AgentError,
    SessionError,
    ConfigurationError,
)
