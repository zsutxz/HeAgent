"""Tests for Plan Mode / read-only mode (Epic 33)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from heagent.agent.loop import AgentLoop
from heagent.cli.console import _apply_plan_mode
from heagent.engine import EngineContainer
from heagent.providers.base import ProviderMetadata
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall


class StubProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:
        if self._idx < len(self._responses):
            response = self._responses[self._idx]
            self._idx += 1
            return response
        return ProviderResponse(
            content="done",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools=None):
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _usage() -> TokenUsage:
    return TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5)


def _tool_response(tool_name: str, args: dict[str, object]) -> ProviderResponse:
    return ProviderResponse(
        content="",
        tool_calls=[ToolCall(id="tc1", name=tool_name, arguments=args)],
        usage=_usage(),
        model="stub",
        finish_reason="tool_calls",
    )


def _final(text: str) -> ProviderResponse:
    return ProviderResponse(content=text, usage=_usage(), model="stub", finish_reason="stop")


@pytest.fixture()
def workspace_dir() -> Path:
    base = Path.cwd() / ".test-workdirs"
    path = base / f"planmode-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class TestReadonlyAnnotations:
    def test_readonly_tools_marked(self) -> None:
        """内置只读工具应有 readOnlyHint=True；写工具不应有。"""
        registry = ToolRegistry.get()
        for name in (
            "file_read",
            "file_search",
            "content_search",
            "skill_list",
            "skill_curate",
            "cron_list",
            "task_status",
        ):
            schema = registry.get_schema(name)
            assert schema is not None, name
            assert schema.annotations is not None and schema.annotations.readOnlyHint, name

        for name in ("shell", "file_write", "fact_add", "profile_update", "cron_add", "cron_remove"):
            schema = registry.get_schema(name)
            assert schema is not None, name
            assert schema.annotations is None or not schema.annotations.readOnlyHint, name


class TestApplyPlanMode:
    def test_off_returns_none_and_keeps_policy(self) -> None:
        engine = EngineContainer()
        assert engine.policy.allowed_tools is None
        hint = _apply_plan_mode(engine, plan_mode=False)
        assert hint is None
        assert engine.policy.allowed_tools is None

    def test_on_filters_to_readonly_and_returns_hint(self) -> None:
        engine = EngineContainer()
        hint = _apply_plan_mode(engine, plan_mode=True)
        assert hint is not None
        assert "PLAN MODE" in hint
        allowed = engine.policy.allowed_tools
        assert allowed is not None
        # 只读工具保留
        assert "file_read" in allowed
        assert "git_status" in allowed
        assert "web_fetch" in allowed
        # 写工具排除
        assert "shell" not in allowed
        assert "file_write" not in allowed
        assert "skill_create" not in allowed
        # MCP 工具（name 含 __）一律排除（readOnlyHint 不可信）
        assert not any("__" in tool for tool in allowed)


class TestPlanModeIntegration:
    @pytest.mark.asyncio
    async def test_plan_mode_blocks_write_tool(self, workspace_dir: Path) -> None:
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        _apply_plan_mode(engine, plan_mode=True)
        provider = StubProvider([_tool_response("shell", {"command": "echo hi"}), _final("done")])
        loop = AgentLoop(provider, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("plan")

        assert result == "done"
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True
        assert "allowlist" in snapshot.results[0].content
