"""Tests for P2 supervisor orchestration — supervisor RoleSpec + completed_steps.

Covers: the ``supervisor`` role restricts the agent to delegation tools;
``task_delegate`` records each outcome into the supervisor run's
``metadata['completed_steps']`` (which survives window resets); ``task_status``
reads that ledger back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from heagent.engine.context import RunContext
from heagent.engine.roles import get_role
from heagent.providers.base import ProviderMetadata
from heagent.tools.builtins.subagent import (
    configure_subagent_tools,
    reset_subagent_tools,
    task_delegate,
    task_status,
)
from heagent.types import ProviderResponse, TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _StubProvider:
    """One-shot provider that immediately finishes with text (no tool calls)."""

    async def send(self, messages, *, tools=None) -> ProviderResponse:  # noqa: ANN001
        return ProviderResponse(
            content="ok",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages, *, tools=None) -> AsyncIterator[ProviderResponse]:  # noqa: ANN001
        yield ProviderResponse(content="ok", usage=TokenUsage(), model="stub", finish_reason="stop")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture(autouse=True)
def _reset():
    reset_subagent_tools()
    yield
    reset_subagent_tools()


def test_supervisor_role_spec() -> None:
    spec = get_role("supervisor")
    assert spec.name == "supervisor"
    # supervisor may only delegate — no direct file/shell tools
    assert spec.allowed_tools == ["task_delegate", "task_parallel", "task_status"]
    assert "file_write" not in spec.allowed_tools
    assert "shell" not in spec.allowed_tools
    assert spec.max_iterations == 30


async def test_task_delegate_records_completed_step() -> None:
    run_context = RunContext()
    configure_subagent_tools(_StubProvider(), run_context=run_context)

    out = await task_delegate("write an add function", role="coder")
    assert "completed" in out.lower()

    steps = run_context.metadata["completed_steps"]
    assert len(steps) == 1
    step = steps[0]
    assert step["role"] == "coder"
    assert step["task"] == "write an add function"
    assert step["success"] is True


async def test_task_status_reads_recorded_steps() -> None:
    run_context = RunContext()
    configure_subagent_tools(_StubProvider(), run_context=run_context)
    await task_delegate("write an add function", role="coder")

    status = await task_status()
    assert "coder" in status
    assert "write an add function" in status


async def test_task_status_empty_when_no_delegations() -> None:
    run_context = RunContext()
    configure_subagent_tools(_StubProvider(), run_context=run_context)

    status = await task_status()
    assert "尚无" in status


async def test_task_status_without_run_context() -> None:
    # nothing configured → no runtime → graceful message
    status = await task_status()
    assert "No run context" in status
