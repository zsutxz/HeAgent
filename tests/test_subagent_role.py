"""Tests for role-specialized SubAgent — execution-level tool allowlist (D1).

Covers: a SubAgent whose role restricts tools blocks out-of-role tool calls at
the PolicyEngine (handler never runs, returns an error ToolResult), and that
``task_delegate(role=...)`` resolves the role name into a RoleSpec.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import heagent.tools.builtins.subagent as _sa_mod
from heagent.agent.sub import SubAgent
from heagent.engine import EngineContainer, PolicyEngine
from heagent.providers.base import ProviderMetadata
from heagent.tools.builtins.subagent import (
    configure_subagent_tools,
    reset_subagent_tools,
    task_delegate,
)
from heagent.tools.decorator import tool
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _ToolCallProvider:
    """Round 1: emit a ``secret_tool`` call. Round 2: finish with text.

    Records every message list it sees so the test can inspect tool results.
    """

    def __init__(self) -> None:
        self._round = 0
        self.seen: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:
        self.seen.append([m.model_copy() for m in messages])
        self._round += 1
        if self._round == 1:
            return ProviderResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="secret_tool", arguments={})],
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model="stub",
                finish_reason="tool_calls",
            )
        return ProviderResponse(
            content="done",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools=None) -> AsyncIterator[ProviderResponse]:
        yield ProviderResponse(
            content="done",
            usage=TokenUsage(),
            model="stub",
            finish_reason="stop",
        )

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture(autouse=True)
def _clean_registry():
    reg = ToolRegistry.get()
    reg._tools.clear()
    reg._handlers.clear()
    reg._disabled.clear()
    reset_subagent_tools()
    yield
    reg = ToolRegistry.get()
    reg._tools.clear()
    reg._handlers.clear()
    reg._disabled.clear()
    reset_subagent_tools()


async def test_allowed_tools_blocks_out_of_role_call() -> None:
    """Out-of-allowlist tool call is blocked by PolicyEngine; handler never runs."""
    invocations: list[str] = []

    @tool
    def secret_tool() -> str:
        """A tool outside the allowed set."""
        invocations.append("ran")
        return "should not run"

    provider = _ToolCallProvider()
    agent = SubAgent(
        provider,
        registry=ToolRegistry.get(),
        allowed_tools=["file_read"],  # secret_tool not allowed
        max_iterations=5,
    )
    await agent.run("call the secret tool")

    # handler never executed (policy blocks before dispatch)
    assert invocations == []
    # round 2 saw the blocked tool result mentioning the tool name
    assert len(provider.seen) >= 2
    tool_msgs = [m for m in provider.seen[1] if m.role is Role.TOOL]
    assert tool_msgs, "expected a TOOL message carrying the blocked result"
    assert any("secret_tool" in (m.content or "") for m in tool_msgs)


async def test_task_delegate_resolves_role_to_spec() -> None:
    """task_delegate(role='coder') threads the coder RoleSpec into SubAgent."""
    class _Stub:
        async def send(self, messages, *, tools=None):
            return ProviderResponse(
                content="ok",
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model="stub",
                finish_reason="stop",
            )

        async def stream(self, messages, *, tools=None):
            yield ProviderResponse(content="ok", usage=TokenUsage(), model="stub", finish_reason="stop")

        def get_metadata(self):
            return ProviderMetadata(name="stub", model="stub")

    configure_subagent_tools(_Stub())

    captured: dict[str, object] = {}
    original_init = _sa_mod.SubAgent.__init__

    def spy(self_sa, provider_arg, **kwargs):
        captured["role"] = kwargs.get("role")
        captured["system"] = kwargs.get("system")
        return original_init(self_sa, provider_arg, **kwargs)

    _sa_mod.SubAgent.__init__ = spy
    try:
        await task_delegate("write a function", role="coder")
    finally:
        _sa_mod.SubAgent.__init__ = original_init

    role = captured["role"]
    assert role is not None
    assert role.name == "coder"
    assert "file_write" in role.allowed_tools
    # task_delegate passes role and lets SubAgent derive system from it
    # (system="" → None); SubAgent.__init__ resolves role.system internally.
    assert captured["system"] is None


async def test_task_delegate_unknown_role_reports_error() -> None:
    class _Stub:
        async def send(self, messages, *, tools=None):
            return ProviderResponse(
                content="ok",
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model="stub",
                finish_reason="stop",
            )

        async def stream(self, messages, *, tools=None):
            yield ProviderResponse(content="ok", usage=TokenUsage(), model="stub", finish_reason="stop")

        def get_metadata(self):
            return ProviderMetadata(name="stub", model="stub")

    configure_subagent_tools(_Stub())
    result = await task_delegate("x", role="no_such_role")
    assert "Unknown role" in result


def test_subagent_role_policy_inherits_parent_governance() -> None:
    parent_engine = EngineContainer(
        policy=PolicyEngine(
            workspace_root="/workspace",
            allowed_tools=["file_read", "file_write", "shell"],
            approval_tools=["shell"],
            sandbox_tools=["file_write"],
            sandbox_profiles={"file_write": "workspace-write"},
            block_mcp_tools=True,
            approval_mcp_tools=True,
            sandbox_mcp_tools=True,
        )
    )
    agent = SubAgent(
        _ToolCallProvider(),
        engine=parent_engine,
        allowed_tools=["file_read", "file_write"],
        blocked_tools=["content_search"],
    )

    child_engine = agent._build_engine()
    child_policy = child_engine.policy

    assert child_policy.allowed_tools == {"file_read", "file_write"}
    assert child_policy.blocked_tools == {"content_search"}
    assert child_policy.approval_tools == {"shell"}
    assert child_policy.sandbox_tools == {"file_write"}
    assert child_policy.sandbox_profiles == {"file_write": "workspace-write"}
    assert child_policy.block_mcp_tools is True
    assert child_policy.approval_mcp_tools is True
    assert child_policy.sandbox_mcp_tools is True
