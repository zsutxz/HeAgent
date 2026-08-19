"""Tests for runtime approval loop (Epic 29)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from heagent.agent.loop import AgentLoop
from heagent.engine import (
    ApprovalDecision,
    ApprovalRequest,
    ConsoleApprovalHandler,
    DenyAllApprovalHandler,
    EngineContainer,
    PolicyEngine,
)
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


def _tool_response(tool_name: str, args: dict[str, object], call_id: str = "tc1") -> ProviderResponse:
    return ProviderResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name=tool_name, arguments=args)],
        usage=_usage(),
        model="stub",
        finish_reason="tool_calls",
    )


def _final(text: str) -> ProviderResponse:
    return ProviderResponse(content=text, usage=_usage(), model="stub", finish_reason="stop")


class RecordingHandler:
    """审批处理器：返回固定决策并记录每次请求。"""

    def __init__(self, decision: ApprovalDecision = ApprovalDecision.APPROVE) -> None:
        self.decision = decision
        self.requests: list[ApprovalRequest] = []

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return self.decision


class ExplodingHandler:
    """审批处理器：总是抛异常，验证 fail-safe。"""

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        raise RuntimeError("approval backend down")


@pytest.fixture()
def workspace_dir() -> Path:
    base = Path.cwd() / ".test-workdirs"
    path = base / f"approval-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _shell_registry() -> tuple[ToolRegistry, list[str]]:
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(
        ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
        lambda command="": calls.append(command) or "shell-ok",
    )
    return registry, calls


def _make_engine(workspace_dir: Path, approval_tools: list[str]) -> EngineContainer:
    engine = EngineContainer.default(workspace_root=str(workspace_dir))
    engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
    engine.policy = PolicyEngine(workspace_root=str(workspace_dir), approval_tools=approval_tools)
    return engine


class TestApprovalPrimitives:
    def test_approval_request_serializes(self) -> None:
        request = ApprovalRequest(
            tool_name="shell",
            reason="requires approval",
            call=ToolCall(id="tc1", name="shell", arguments={"command": "dir"}),
        )
        dumped = request.model_dump()
        assert dumped["tool_name"] == "shell"
        assert dumped["call"]["name"] == "shell"

    @pytest.mark.asyncio
    async def test_deny_all_handler_denies(self) -> None:
        handler = DenyAllApprovalHandler()
        decision = await handler.request(
            ApprovalRequest(tool_name="shell", reason="x", call=ToolCall(id="1", name="shell", arguments={}))
        )
        assert decision is ApprovalDecision.DENY

    @pytest.mark.asyncio
    async def test_console_handler_approve_deny(self) -> None:
        approve = ConsoleApprovalHandler(prompt_fn=lambda msg: "y")
        deny = ConsoleApprovalHandler(prompt_fn=lambda msg: "n")
        req = ApprovalRequest(tool_name="shell", reason="x", call=ToolCall(id="1", name="shell", arguments={}))
        assert (await approve.request(req)) is ApprovalDecision.APPROVE
        assert (await deny.request(req)) is ApprovalDecision.DENY


class TestApprovalIntegration:
    @pytest.mark.asyncio
    async def test_approve_executes_tool(self, workspace_dir: Path) -> None:
        registry, calls = _shell_registry()
        engine = _make_engine(workspace_dir, approval_tools=["shell"])
        handler = RecordingHandler(ApprovalDecision.APPROVE)
        engine.approval_handler = handler
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == ["dir"]  # handler 实际执行了
        assert len(handler.requests) == 1  # 询问了一次
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is False

    @pytest.mark.asyncio
    async def test_deny_blocks_tool(self, workspace_dir: Path) -> None:
        registry, calls = _shell_registry()
        engine = _make_engine(workspace_dir, approval_tools=["shell"])
        engine.approval_handler = RecordingHandler(ApprovalDecision.DENY)
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == []  # handler 未执行
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True
        assert "requires approval" in snapshot.results[0].content

    @pytest.mark.asyncio
    async def test_handler_failure_fails_safe(self, workspace_dir: Path) -> None:
        registry, calls = _shell_registry()
        engine = _make_engine(workspace_dir, approval_tools=["shell"])
        engine.approval_handler = ExplodingHandler()
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == []  # fail-safe 拒绝，未执行
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True

    @pytest.mark.asyncio
    async def test_approval_granted_is_cached_per_run(self, workspace_dir: Path) -> None:
        registry, calls = _shell_registry()
        engine = _make_engine(workspace_dir, approval_tools=["shell"])
        handler = RecordingHandler(ApprovalDecision.APPROVE)
        engine.approval_handler = handler
        provider = StubProvider(
            [
                _tool_response("shell", {"command": "one"}, call_id="tc1"),
                _tool_response("shell", {"command": "two"}, call_id="tc2"),
                _final("done"),
            ]
        )
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell twice")

        assert result == "done"
        assert calls == ["one", "two"]  # 两次都执行了
        assert len(handler.requests) == 1  # 但只询问了一次（授权缓存）

    @pytest.mark.asyncio
    async def test_no_handler_keeps_legacy_blocking(self, workspace_dir: Path) -> None:
        # 零回归：未配置 handler 时 APPROVAL_REQUIRED 等同阻断（与 29 前行为一致）。
        registry, calls = _shell_registry()
        engine = _make_engine(workspace_dir, approval_tools=["shell"])
        assert engine.approval_handler is None
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == []
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True
        assert "requires approval" in snapshot.results[0].content
