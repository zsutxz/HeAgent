"""Tool execution policy evaluation."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from heagent.engine.context import RunContext
    from heagent.types import ToolCall


class ToolExecutionMode(StrEnum):
    """Execution mode decided by policy for one tool call."""

    DIRECT = "direct"
    APPROVAL_REQUIRED = "approval_required"
    SANDBOX_REQUIRED = "sandbox_required"
    BLOCKED = "blocked"


class PolicyVerdict(BaseModel):
    """Result of evaluating a tool call against engine policy."""

    mode: ToolExecutionMode = ToolExecutionMode.DIRECT
    reason: str = ""
    sandbox_profile: str | None = None

    @property
    def allowed(self) -> bool:
        """Return whether the call is not hard-blocked."""
        return self.mode is not ToolExecutionMode.BLOCKED

    @property
    def requires_approval(self) -> bool:
        """Return whether the tool needs an approval grant."""
        return self.mode is ToolExecutionMode.APPROVAL_REQUIRED

    @property
    def requires_sandbox(self) -> bool:
        """Return whether the tool needs a sandbox grant."""
        return self.mode is ToolExecutionMode.SANDBOX_REQUIRED


class PolicyEngine:
    """Central policy layer for tool admission and workspace scoping."""

    _PATH_FIELDS: dict[str, tuple[str, ...]] = {
        "file_read": ("path",),
        "file_write": ("path",),
        "file_search": ("directory",),
        "content_search": ("directory",),
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
        self.workspace_root = workspace_root
        self.blocked_tools = set(blocked_tools or [])
        self.allowed_tools = set(allowed_tools or [])
        self.approval_tools = set(approval_tools or [])
        self.sandbox_tools = set(sandbox_tools or [])
        self.sandbox_profiles = dict(sandbox_profiles or {})
        self.block_mcp_tools = block_mcp_tools
        self.approval_mcp_tools = approval_mcp_tools
        self.sandbox_mcp_tools = sandbox_mcp_tools

    def evaluate_tool_call(
        self,
        call: ToolCall,
        *,
        context: RunContext | None = None,
    ) -> PolicyVerdict:
        """Evaluate a tool call before any runtime execution happens."""
        if self.allowed_tools and call.name not in self.allowed_tools:
            return PolicyVerdict(
                mode=ToolExecutionMode.BLOCKED,
                reason=f"Tool '{call.name}' is not in the policy allowlist.",
            )

        if call.name in self.blocked_tools:
            return PolicyVerdict(
                mode=ToolExecutionMode.BLOCKED,
                reason=f"Tool '{call.name}' is blocked by policy.",
            )

        if self.block_mcp_tools and self._is_mcp_tool(call):
            return PolicyVerdict(
                mode=ToolExecutionMode.BLOCKED,
                reason=f"MCP tool '{call.name}' is blocked by policy.",
            )

        path_error = self._validate_paths(call, context=context)
        if path_error:
            return PolicyVerdict(mode=ToolExecutionMode.BLOCKED, reason=path_error)

        sandbox_profile = self._sandbox_profile(call)
        if self._requires_approval(call) and not self._approval_granted(call, context=context):
            return PolicyVerdict(
                mode=ToolExecutionMode.APPROVAL_REQUIRED,
                reason=f"Tool '{call.name}' requires approval by policy.",
                sandbox_profile=sandbox_profile,
            )

        if sandbox_profile is not None and not self._sandbox_granted(call, context=context):
            return PolicyVerdict(
                mode=ToolExecutionMode.SANDBOX_REQUIRED,
                reason=f"Tool '{call.name}' requires sandbox '{sandbox_profile}' by policy.",
                sandbox_profile=sandbox_profile,
            )
        if sandbox_profile is not None:
            return PolicyVerdict(
                mode=ToolExecutionMode.SANDBOX_REQUIRED,
                sandbox_profile=sandbox_profile,
            )

        return PolicyVerdict(mode=ToolExecutionMode.DIRECT, sandbox_profile=sandbox_profile)

    def _validate_paths(self, call: ToolCall, *, context: RunContext | None) -> str:
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
            candidate = Path(value)
            resolved = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=False)
            if not resolved.is_relative_to(root):
                return f"Tool '{call.name}' attempted to access a path outside workspace: {value}"
        return ""

    def _workspace_root(self, context: RunContext | None) -> Path | None:
        root = context.workspace_root if context is not None else self.workspace_root
        if not root:
            return None
        return Path(root).resolve()

    def _requires_approval(self, call: ToolCall) -> bool:
        return call.name in self.approval_tools or (self.approval_mcp_tools and self._is_mcp_tool(call))

    def _sandbox_profile(self, call: ToolCall) -> str | None:
        if call.name in self.sandbox_tools:
            return self.sandbox_profiles.get(call.name, "default")
        if self.sandbox_mcp_tools and self._is_mcp_tool(call):
            return self.sandbox_profiles.get(call.name, self.sandbox_profiles.get("__mcp__", "mcp"))
        return None

    def _approval_granted(self, call: ToolCall, *, context: RunContext | None) -> bool:
        approved_tools = self._context_name_set(context, "approved_tools")
        if "*" in approved_tools or call.name in approved_tools:
            return True
        if self._is_mcp_tool(call) and "__mcp__" in approved_tools:
            return True
        return False

    def _sandbox_granted(self, call: ToolCall, *, context: RunContext | None) -> bool:
        if context is None:
            return False
        metadata = context.metadata
        if bool(metadata.get("sandbox_active", False)):
            return True
        sandboxed_tools = self._context_name_set(context, "sandboxed_tools")
        if "*" in sandboxed_tools or call.name in sandboxed_tools:
            return True
        if self._is_mcp_tool(call) and "__mcp__" in sandboxed_tools:
            return True
        sandbox_profile = self._sandbox_profile(call)
        if sandbox_profile is None:
            return False
        sandbox_profiles = self._context_name_set(context, "sandbox_profiles")
        return sandbox_profile in sandbox_profiles or "*" in sandbox_profiles

    @staticmethod
    def _context_name_set(context: RunContext | None, key: str) -> set[str]:
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
        return "__" in call.name
