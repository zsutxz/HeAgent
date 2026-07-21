"""工具执行策略裁决（policy）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。工具执行链固定为
``PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler``（项目硬约束）。
``PolicyEngine`` 在**任何实际执行之前**对一次 :class:`~heagent.types.ToolCall` 做裁决，
产出 :class:`PolicyVerdict`，交由 :class:`~heagent.engine.executor.ToolExecutor` 分发。

裁决维度（按 :meth:`PolicyEngine.evaluate_tool_call` 内的先后顺序，前者优先短路）：

1. **白名单**（``allowed_tools``）—— 设了白名单且工具不在其中 → ``BLOCKED``；
2. **黑名单**（``blocked_tools``）—— 命中 → ``BLOCKED``；
3. **MCP 门控**（``block_mcp_tools``）—— 命中 MCP 工具 → ``BLOCKED``；
4. **工作区路径围栏**（:meth:`_validate_paths`）—— file/git 工具路径越界 → ``BLOCKED``；
5. **审批**（``approval_tools``）—— 需审批且当前 run 未授权 → ``APPROVAL_REQUIRED``；
   对 MCP 工具，如果传入了 ``schema``（含 ``annotations``），则：
   - ``destructiveHint`` → 需要审批（FR-A3）；
   - ``readOnlyHint`` → 不需审批（FR-A4，除非被显式策略覆盖：``approval_tools`` / ``approval_mcp_tools`` 优先）；
   - annotations 存在但两 hint 均为 ``False`` → fail-safe 需要审批（FR-A5）；
   - 缺 ``annotations``（``None``）→ fail-safe 需要审批（FR-A5）；
   - ``schema=None``（内置工具）→ 跳过注解裁决，走既有路径（FR-A2 AD-2，零回归）；
6. **沙箱**（``sandbox_tools``）—— 需沙箱 → ``SANDBOX_REQUIRED``（无论是否已授权，mode 均
   为 ``SANDBOX_REQUIRED``，仅 reason 因授权状态不同）；
7. 其余 → ``DIRECT``。

与 :class:`~heagent.tools.safety.SafetyGuard` 的关系：二者职责分离、**串行**——policy 先做
准入 / 围栏 / 审批 / 沙箱裁决，executor 内部再过 guard（shell 命令模式黑名单）。
policy **不是安全边界**（围栏可被绕过），须 OS 级沙箱兜底（见 CLAUDE.md 安全声明）。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from heagent.tools.path_safety import WorkspacePathError, resolve_under_root

if TYPE_CHECKING:
    from heagent.engine.context import RunContext
    from heagent.types import ToolCall, ToolSchema


class ToolExecutionMode(StrEnum):
    """policy 对单次工具调用决定的执行模式。

    ``StrEnum`` 便于序列化到事件 details（见 executor 的 emit）。
    """

    DIRECT = "direct"  # 直接执行
    APPROVAL_REQUIRED = "approval_required"  # 需审批授权（V1 executor 中等同阻断）
    SANDBOX_REQUIRED = "sandbox_required"  # 需在沙箱内执行
    BLOCKED = "blocked"  # 硬阻断


class PolicyVerdict(BaseModel):
    """一次工具调用经 policy 裁决的结果。

    ``mode`` 决定 executor 的分发路径；``reason`` 为人类可读说明；``sandbox_profile``
    在沙箱模式下指出使用哪个沙箱配置（executor 透传给后端）。
    """

    mode: ToolExecutionMode = ToolExecutionMode.DIRECT
    reason: str = ""
    sandbox_profile: str | None = None

    @property
    def allowed(self) -> bool:
        """是否未被硬阻断（mode 非 BLOCKED）。"""
        return self.mode is not ToolExecutionMode.BLOCKED

    @property
    def requires_approval(self) -> bool:
        """是否需要审批授权。"""
        return self.mode is ToolExecutionMode.APPROVAL_REQUIRED

    @property
    def requires_sandbox(self) -> bool:
        """是否需要在沙箱内执行。"""
        return self.mode is ToolExecutionMode.SANDBOX_REQUIRED


class PolicyEngine:
    """工具准入与工作区作用域的中央策略层。

    对象本身无状态（仅持有构造时注入的策略配置）：所有运行态授权信息都从传入的
    :class:`RunContext.metadata` 读取，因此同一 engine 可被多个 run / 子 Agent 安全复用。
    """

    # 受路径围栏约束的工具 → 其参数中表示路径的字段名。
    # P1-15 修复：补全 git_status/git_diff/git_log/git_blame，使 git 路径越界在 policy 层
    # 也被预检拦截，与 file 工具保持一致的「policy + handler」两层纵深防御。
    _PATH_FIELDS: dict[str, tuple[str, ...]] = {
        "file_read": ("path",),
        "file_write": ("path",),
        "file_search": ("directory",),
        "content_search": ("directory",),
        "git_status": ("path",),
        "git_diff": ("path",),
        "git_log": ("path",),
        "git_blame": ("file_path",),
    }

    def __init__(
        self,
        *,
        workspace_root: str | None = None,
        blocked_tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        approval_tools: list[str] | None = None,
        sandbox_tools: list[str] | None = None,
        sandbox_profiles: dict[str, str] | None = None,
        block_mcp_tools: bool = False,
        approval_mcp_tools: bool = False,
        sandbox_mcp_tools: bool = False,
    ) -> None:
        # 工作区根（绝对路径）；为 None 时 _validate_paths 不做围栏。
        self.workspace_root = workspace_root
        # 黑名单：命中的工具直接 BLOCKED。
        self.blocked_tools = set(blocked_tools or [])
        # 白名单：None 表示不启用（全部放行至后续检查）；非 None 时仅放行其中工具。
        self.allowed_tools = None if allowed_tools is None else set(allowed_tools)
        # 需审批的工具集。
        self.approval_tools = set(approval_tools or [])
        # 需沙箱的工具集。
        self.sandbox_tools = set(sandbox_tools or [])
        # 工具 → 沙箱配置名映射；命中 sandbox_tools 但未列于此则用 "default"。
        self.sandbox_profiles = dict(sandbox_profiles or {})
        # MCP 工具的三类门控开关（按需阻断 / 审批 / 沙箱）。
        self.block_mcp_tools = block_mcp_tools
        self.approval_mcp_tools = approval_mcp_tools
        self.sandbox_mcp_tools = sandbox_mcp_tools

    def evaluate_tool_call(
        self,
        call: ToolCall,
        *,
        context: RunContext | None = None,
        schema: ToolSchema | None = None,
    ) -> PolicyVerdict:
        """在任何运行时执行之前裁决一次工具调用。

        按模块 docstring 列出的 7 步顺序短路返回：先准入（白 / 黑 / MCP 门控），
        再工作区路径围栏，最后判审批与沙箱。``context`` 提供运行态授权信息；
        ``schema`` （含 ``annotations``）供注解感知裁决（MCP V2 写操作治理）。
        """
        # 1) 白名单：设了白名单且工具不在其中 → 阻断。
        if self.allowed_tools is not None and call.name not in self.allowed_tools:
            return PolicyVerdict(
                mode=ToolExecutionMode.BLOCKED,
                reason=f"Tool '{call.name}' is not in the policy allowlist.",
            )

        # 2) 黑名单：命中 → 阻断。
        if call.name in self.blocked_tools:
            return PolicyVerdict(
                mode=ToolExecutionMode.BLOCKED,
                reason=f"Tool '{call.name}' is blocked by policy.",
            )

        # 3) MCP 门控：开启 block_mcp_tools 且调用的是 MCP 工具 → 阻断。
        if self.block_mcp_tools and self._is_mcp_tool(call):
            return PolicyVerdict(
                mode=ToolExecutionMode.BLOCKED,
                reason=f"MCP tool '{call.name}' is blocked by policy.",
            )

        # 4) 工作区路径围栏：file/git 工具的路径参数越界 → 阻断。
        path_error = self._validate_paths(call, context=context)
        if path_error:
            return PolicyVerdict(mode=ToolExecutionMode.BLOCKED, reason=path_error)

        # 计算沙箱配置（该工具需沙箱则非 None）。
        sandbox_profile = self._sandbox_profile(call)

        # 5) 审批：显式策略优先，注解感知 MCP 工具缺省行为（FR-A3/A4/A5）。
        if self._requires_approval(call, schema=schema) and not self._approval_granted(call, context=context):
            return PolicyVerdict(
                mode=ToolExecutionMode.APPROVAL_REQUIRED,
                reason=self._approval_reason(call, schema=schema),
                sandbox_profile=sandbox_profile,
            )

        # 6) 沙箱：需沙箱但当前 run 未授权 → 要求沙箱授权（reason 提示需 grant）。
        if sandbox_profile is not None and not self._sandbox_granted(call, context=context):
            return PolicyVerdict(
                mode=ToolExecutionMode.SANDBOX_REQUIRED,
                reason=f"Tool '{call.name}' requires sandbox '{sandbox_profile}' by policy.",
                sandbox_profile=sandbox_profile,
            )
        # 6') 需沙箱且已授权：mode 仍为 SANDBOX_REQUIRED（指示 executor 走沙箱路径），reason 留空。
        if sandbox_profile is not None:
            return PolicyVerdict(
                mode=ToolExecutionMode.SANDBOX_REQUIRED,
                sandbox_profile=sandbox_profile,
            )

        # 7) 其余：直接执行。
        return PolicyVerdict(mode=ToolExecutionMode.DIRECT, sandbox_profile=sandbox_profile)

    def _validate_paths(self, call: ToolCall, *, context: RunContext | None) -> str:
        """对受约束的 file/git 工具做工作区路径围栏校验。

        返回非空字符串即越界原因（调用方据此 BLOCKED）；空串表示通过 / 不适用。
        围栏基线 = context.workspace_root（优先）或 self.workspace_root；二者皆空则放行。

        围栏算法委托 :func:`heagent.tools.path_safety.resolve_under_root`——与 handler 守卫
        (:func:`~heagent.tools.path_safety.resolve_workspace_path`) 共用同一实现，属有意的
        两层纵深防御（policy 预检 + handler 守卫），不再是两份可漂移的副本。root 来源策略
        （context/self，皆空放行）是本层与 handler 的唯一有意差异。
        """
        fields = self._PATH_FIELDS.get(call.name)
        if not fields:
            return ""

        root = self._workspace_root(context)
        if root is None:
            return ""

        for field in fields:
            value = call.arguments.get(field)
            if not isinstance(value, str):
                continue
            try:
                resolve_under_root(value, root)
            except WorkspacePathError:
                return f"Tool '{call.name}' attempted to access a path outside workspace: {value}"
        return ""

    def _workspace_root(self, context: RunContext | None) -> Path | None:
        """解析工作区根：context 优先，其次 self；解析为绝对路径。无根则返回 None。"""
        root = context.workspace_root if context is not None else self.workspace_root
        if not root:
            return None
        return Path(root).resolve()

    def _requires_approval(self, call: ToolCall, *, schema: ToolSchema | None = None) -> bool:
        """该工具是否需审批：显式策略（``approval_tools`` / ``approval_mcp_tools``）优先；
        对 MCP 工具，若传入了 ``schema``，则按 annotations 确定缺省审批行为（FR-A3/A4/A5）。

        优先级（前者短路）：
        1. 显式策略命中（``approval_tools`` 含该工具，或开启 ``approval_mcp_tools`` 且为 MCP 工具）；
        2. MCP 工具 + ``schema.annotations.destructiveHint`` → 需审批（FR-A3）；
        3. MCP 工具 + ``schema.annotations.readOnlyHint`` → 放行（免审批，FR-A4）；
        4. MCP 工具 + annotations 存在但两 hint 均为 False → fail-safe 需审批（FR-A5）；
        5. MCP 工具 + ``schema.annotations is None`` → fail-safe 需审批（FR-A5）；
        6. ``schema`` 为 ``None``（V1 内置工具 / 未知工具）→ 跳过注解裁决，走既有路径（零回归）。
        """
        # 1) 显式策略始终优先。
        if call.name in self.approval_tools:
            return True
        if self.approval_mcp_tools and self._is_mcp_tool(call):
            return True

        # 2) MCP 工具 + schema → 注解感知裁决。
        if self._is_mcp_tool(call) and schema is not None:
            ann = schema.annotations
            # 2a) destructiveHint → 需审批（FR-A3）。
            if ann is not None and ann.destructiveHint:
                return True
            # 2b) readOnlyHint → 免审批（FR-A4）。
            if ann is not None and ann.readOnlyHint:
                return False
            # 2c) annotations 存在但两个 hint 均为 False → fail-safe 需审批（FR-A5）。
            if ann is not None:
                return True
            # 2d) 缺 annotations（None）→ fail-safe 需审批（FR-A5）。
            if ann is None:
                return True

        # 3) schema 为 None（V1 内置工具）或非 MCP 工具 → 既有路径。
        return False

    def _approval_reason(self, call: ToolCall, *, schema: ToolSchema | None = None) -> str:
        """生成审批原因的友好说明，反映是 annotations 还是显式策略触发。"""
        # 显式策略
        if call.name in self.approval_tools:
            return f"Tool '{call.name}' requires approval by policy (in approval_tools)."
        if self.approval_mcp_tools and self._is_mcp_tool(call):
            return f"MCP tool '{call.name}' requires approval by policy (approval_mcp_tools=True)."

        # MCP 注解触发
        if self._is_mcp_tool(call) and schema is not None:
            ann = schema.annotations
            if ann is not None and ann.destructiveHint:
                return f"MCP tool '{call.name}' requires approval (destructiveHint)."
            if ann is not None:
                return f"MCP tool '{call.name}' requires approval (annotations present, neither hint set; fail-safe)."
            if ann is None:
                return f"MCP tool '{call.name}' requires approval (no annotations; fail-safe)."

        return f"Tool '{call.name}' requires approval by policy."

    def _sandbox_profile(self, call: ToolCall) -> str | None:
        """返回该工具应使用的沙箱配置名；无需沙箱则返回 None。

        MCP 工具在开启 sandbox_mcp_tools 时走 ``__mcp__`` 配置（缺省 "mcp"）。
        """
        if call.name in self.sandbox_tools:
            return self.sandbox_profiles.get(call.name, "default")
        if self.sandbox_mcp_tools and self._is_mcp_tool(call):
            return self.sandbox_profiles.get(call.name, self.sandbox_profiles.get("__mcp__", "mcp"))
        return None

    def _approval_granted(self, call: ToolCall, *, context: RunContext | None) -> bool:
        """当前 run 是否已授予该工具审批（读 metadata.approved_tools）。

        ``"*"`` 表示通配全部；MCP 工具可由 ``"__mcp__"`` 整体授权。
        """
        approved_tools = self._context_name_set(context, "approved_tools")
        if "*" in approved_tools or call.name in approved_tools:
            return True
        return self._is_mcp_tool(call) and "__mcp__" in approved_tools

    def _sandbox_granted(self, call: ToolCall, *, context: RunContext | None) -> bool:
        """当前 run 是否已授予该工具的沙箱执行权（委托 :meth:`context_grants_sandbox`）。"""
        sandbox_profile = self._sandbox_profile(call)
        return self.context_grants_sandbox(
            call,
            context=context,
            sandbox_profile=sandbox_profile,
        )

    @staticmethod
    def _context_name_set(context: RunContext | None, key: str) -> set[str]:
        """从 context.metadata[key] 取字符串集合（兼容单值 str / 列表）。无 context 返回空集。"""
        if context is None:
            return set()
        raw = context.metadata.get(key, [])
        if isinstance(raw, str):
            return {raw}
        if isinstance(raw, list):
            return {value for value in raw if isinstance(value, str)}
        return set()

    @staticmethod
    def _is_mcp_tool(call: ToolCall) -> bool:
        """按命名约定判断是否 MCP 工具：MCP 工具名为 ``<server>__<tool>``（含双下划线）。"""
        return "__" in call.name

    @classmethod
    def context_grants_sandbox(
        cls,
        call: ToolCall,
        *,
        context: RunContext | None,
        sandbox_profile: str | None,
    ) -> bool:
        """当前 run 是否授予该调用的沙箱执行权（供 ToolExecutor 复核）。

        授权来源（任一命中即授权）：
        - ``metadata.sandbox_active`` 为真（整 run 沙箱已激活）；
        - ``metadata.sandboxed_tools`` 含该工具 / ``"*"`` /（MCP 工具）``"__mcp__"``；
        - ``metadata.sandbox_profiles`` 含该调用所需 profile 或 ``"*"``。
        """
        if context is None:
            return False

        metadata = context.metadata
        if bool(metadata.get("sandbox_active", False)):
            return True

        sandboxed_tools = cls._context_name_set(context, "sandboxed_tools")
        if "*" in sandboxed_tools or call.name in sandboxed_tools:
            return True
        if cls._is_mcp_tool(call) and "__mcp__" in sandboxed_tools:
            return True

        if sandbox_profile is None:
            return False

        sandbox_profiles = cls._context_name_set(context, "sandbox_profiles")
        return sandbox_profile in sandbox_profiles or "*" in sandbox_profiles
