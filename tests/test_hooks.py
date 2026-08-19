"""Tests for user-configurable hooks (Epic 32)."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from heagent.agent.loop import AgentLoop
from heagent.engine import EngineContainer, HookConfig, HookManager
from heagent.providers.base import ProviderMetadata
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall, ToolSchema


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
    path = base / f"hooks-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class TestHookLoad:
    def test_load_parses(self, tmp_path) -> None:
        p = tmp_path / "hooks.json"
        p.write_text(
            json.dumps({"hooks": [{"event": "PreToolUse", "command": "echo hi", "matcher": "shell", "block": True}]}),
            encoding="utf-8",
        )
        mgr = HookManager.load(str(p))
        assert len(mgr._hooks) == 1
        assert mgr._hooks[0].matcher == "shell"
        assert mgr._hooks[0].block is True

    def test_load_nonexistent(self, tmp_path) -> None:
        assert HookManager.load(str(tmp_path / "nope.json"))._hooks == []

    def test_load_invalid_json(self, tmp_path) -> None:
        p = tmp_path / "hooks.json"
        p.write_text("not json", encoding="utf-8")
        assert HookManager.load(str(p))._hooks == []

    def test_load_skips_invalid_entry(self, tmp_path) -> None:
        p = tmp_path / "hooks.json"
        p.write_text(
            json.dumps(
                {
                    "hooks": [
                        {"event": "PreToolUse"},  # 缺 command，应跳过
                        {"event": "PreToolUse", "command": "echo hi"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert len(HookManager.load(str(p))._hooks) == 1


class TestPreToolHook:
    @pytest.mark.asyncio
    async def test_block_on_nonzero(self) -> None:
        hooks = [HookConfig(event="PreToolUse", command="exit 1", matcher="shell", block=True)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is True

    @pytest.mark.asyncio
    async def test_allow_on_zero(self) -> None:
        hooks = [HookConfig(event="PreToolUse", command="exit 0", matcher="shell", block=True)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_non_block_hook_never_blocks(self) -> None:
        hooks = [HookConfig(event="PreToolUse", command="exit 1", matcher="shell", block=False)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_matcher_filters(self) -> None:
        hooks = [HookConfig(event="PreToolUse", command="exit 1", matcher="shell", block=True)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="file_read", arguments={}))
        assert result.blocked is False


class TestHookIntegration:
    @pytest.mark.asyncio
    async def test_pre_tool_hook_blocks_in_loop(self, workspace_dir: Path) -> None:
        registry = ToolRegistry()
        calls: list[str] = []
        registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": calls.append(command) or "ran",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.hooks = HookManager([HookConfig(event="PreToolUse", command="exit 1", matcher="shell", block=True)])
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == []  # 被 hook 阻断，handler 未执行
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True
        assert "blocked by hook" in snapshot.results[0].content

    @pytest.mark.asyncio
    async def test_non_block_hook_does_not_block(self, workspace_dir: Path) -> None:
        registry = ToolRegistry()
        calls: list[str] = []
        registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": calls.append(command) or "ran",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.hooks = HookManager([HookConfig(event="PreToolUse", command="exit 0", matcher="shell", block=True)])
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == ["dir"]  # hook 放行，handler 正常执行
