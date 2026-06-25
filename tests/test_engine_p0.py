"""Tests for P0 engine runtime services."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from heagent.agent.loop import AgentLoop
from heagent.engine import EngineContainer, PolicyEngine, RunContext, RunStatus, ToolExecutionMode, ToolExecutor
from heagent.memory.facts import FactStore
from heagent.memory.skills import SkillStore
from heagent.providers.base import ProviderMetadata
from heagent.tools.builtins.memory import bind_memory_tools, fact_add
from heagent.tools.builtins.skills import bind_skill_tools, configure_skill_tools, reset_skill_tools, skill_create
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall, ToolSchema


class StubProvider:
    """In-memory provider for loop tests."""

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
    path = base / f"engine-p0-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class TestRunStoreIntegration:
    @pytest.mark.asyncio
    async def test_run_checkpoints_and_final_state(self, workspace_dir: Path) -> None:
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        provider = StubProvider([_final("ok")])
        loop = AgentLoop(provider, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("hello")

        assert result == "ok"
        assert loop.last_run_context is not None
        snapshot = engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.final_answer == "ok"
        assert snapshot.context.status == RunStatus.COMPLETED


class TestPolicyEngine:
    @pytest.mark.asyncio
    async def test_policy_blocks_tool_outside_workspace(self, workspace_dir: Path) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="file_read", description="read file", parameters={"type": "object", "properties": {}}),
            lambda path="": "blocked",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        provider = StubProvider([_tool_response("file_read", {"path": "../secret.txt"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("read outside workspace")

        assert result == "done"
        assert loop.last_run_context is not None
        snapshot = engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True
        assert "outside workspace" in snapshot.results[0].content

    def test_policy_allowlist(self, workspace_dir: Path) -> None:
        policy = PolicyEngine(workspace_root=str(workspace_dir), allowed_tools=["echo"])
        verdict = policy.evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            context=RunContext(workspace_root=str(workspace_dir)),
        )
        assert verdict.allowed is False
        assert "allowlist" in verdict.reason

    def test_policy_requires_approval_when_configured(self, workspace_dir: Path) -> None:
        policy = PolicyEngine(workspace_root=str(workspace_dir), approval_tools=["shell"])
        verdict = policy.evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            context=RunContext(workspace_root=str(workspace_dir)),
        )
        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.requires_approval is True

    def test_policy_requires_sandbox_when_configured(self, workspace_dir: Path) -> None:
        policy = PolicyEngine(
            workspace_root=str(workspace_dir),
            sandbox_tools=["shell"],
            sandbox_profiles={"shell": "workspace-shell"},
        )
        verdict = policy.evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            context=RunContext(workspace_root=str(workspace_dir)),
        )
        assert verdict.mode is ToolExecutionMode.SANDBOX_REQUIRED
        assert verdict.sandbox_profile == "workspace-shell"

    def test_policy_keeps_sandbox_mode_after_grants(self, workspace_dir: Path) -> None:
        policy = PolicyEngine(
            workspace_root=str(workspace_dir),
            sandbox_tools=["shell"],
            sandbox_profiles={"shell": "workspace-shell"},
        )
        context = RunContext(
            workspace_root=str(workspace_dir),
            metadata={"sandbox_profiles": ["workspace-shell"]},
        )
        verdict = policy.evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            context=context,
        )
        assert verdict.mode is ToolExecutionMode.SANDBOX_REQUIRED
        assert verdict.allowed is True

    def test_policy_supports_mcp_sandbox_and_approval(self, workspace_dir: Path) -> None:
        policy = PolicyEngine(
            workspace_root=str(workspace_dir),
            approval_mcp_tools=True,
            sandbox_mcp_tools=True,
            sandbox_profiles={"__mcp__": "mcp-net"},
        )
        context = RunContext(
            workspace_root=str(workspace_dir),
            metadata={"sandbox_profiles": ["mcp-net"]},
        )
        verdict = policy.evaluate_tool_call(
            ToolCall(id="1", name="github__list_issues", arguments={}),
            context=context,
        )
        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.sandbox_profile == "mcp-net"

    def test_policy_approval_takes_precedence_over_granted_sandbox(self, workspace_dir: Path) -> None:
        policy = PolicyEngine(
            workspace_root=str(workspace_dir),
            approval_tools=["shell"],
            sandbox_tools=["shell"],
            sandbox_profiles={"shell": "workspace-shell"},
        )
        context = RunContext(
            workspace_root=str(workspace_dir),
            metadata={"sandbox_profiles": ["workspace-shell"]},
        )
        verdict = policy.evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            context=context,
        )
        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED


class TestExecutionLedger:
    def test_acquire_and_complete(self, workspace_dir: Path) -> None:
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.ledger = engine.ledger.__class__(base_dir=str(workspace_dir / "ledger"))

        claim = engine.ledger.acquire("cron:test:2026-06-23T10:00", scope="cron")
        assert claim.acquired is True

        duplicate = engine.ledger.acquire("cron:test:2026-06-23T10:00", scope="cron")
        assert duplicate.acquired is False

        engine.ledger.complete("cron:test:2026-06-23T10:00")
        record = engine.ledger.get("cron:test:2026-06-23T10:00")
        assert record is not None
        assert record.status == "completed"


class TestCronDedup:
    @pytest.mark.asyncio
    async def test_cron_scheduler_uses_ledger_to_skip_duplicate_tick(self, workspace_dir: Path) -> None:
        from heagent.cron.jobs import JobStore
        from heagent.cron.scheduler import CronScheduler

        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.ledger = engine.ledger.__class__(base_dir=str(workspace_dir / "ledger"))
        store = JobStore(str(workspace_dir / "jobs.json"))
        job = store.create_job("say hi", "* * * * *")
        store.add(job)

        class CountingProvider(StubProvider):
            def __init__(self) -> None:
                super().__init__([_final("ok"), _final("ok")])
                self.calls = 0

            async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:
                self.calls += 1
                return await super().send(messages, tools=tools)

        provider = CountingProvider()
        scheduler = CronScheduler(store, provider, engine=engine, context_dir=str(workspace_dir))
        due = datetime(2026, 6, 23, 10, 15, 0)

        await scheduler._execute_job(job, now=due)
        await scheduler._execute_job(job, now=due)

        assert provider.calls == 1


class TestRuntimeBindings:
    @pytest.mark.asyncio
    async def test_memory_bindings_are_task_local(self, workspace_dir: Path) -> None:
        store_a = FactStore(path=str(workspace_dir / "facts-a.md"))
        store_b = FactStore(path=str(workspace_dir / "facts-b.md"))

        async def write_fact(store: FactStore, text: str) -> str:
            with bind_memory_tools(facts=store):
                return await fact_add(text)

        await asyncio.gather(
            write_fact(store_a, "alpha fact"),
            write_fact(store_b, "beta fact"),
        )

        assert store_a.load() == ["alpha fact"]
        assert store_b.load() == ["beta fact"]

    @pytest.mark.asyncio
    async def test_skill_binding_overrides_fallback_without_polluting_it(self, workspace_dir: Path) -> None:
        fallback_store = SkillStore(base_dir=str(workspace_dir / "skills-fallback"))
        override_store = SkillStore(base_dir=str(workspace_dir / "skills-override"))
        configure_skill_tools(fallback_store)
        try:
            with bind_skill_tools(override_store):
                result = await skill_create("override_skill", "desc", "pattern", "step")
                assert "created" in result

            result = await skill_create("fallback_skill", "desc", "pattern", "step")
            assert "created" in result
        finally:
            reset_skill_tools()

        assert override_store.load("override_skill") is not None
        assert override_store.load("fallback_skill") is None
        assert fallback_store.load("fallback_skill") is not None
        assert fallback_store.load("override_skill") is None


class TestPolicyIntegration:
    @pytest.mark.asyncio
    async def test_agent_loop_blocks_sandbox_required_tool(self, workspace_dir: Path) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": "should not run",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.policy = PolicyEngine(
            workspace_root=str(workspace_dir),
            sandbox_tools=["shell"],
            sandbox_profiles={"shell": "workspace-shell"},
        )
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        snapshot = engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True
        assert "requires sandbox" in snapshot.results[0].content

    @pytest.mark.asyncio
    async def test_agent_loop_blocks_approval_required_tool(self, workspace_dir: Path) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": "should not run",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.policy = PolicyEngine(
            workspace_root=str(workspace_dir),
            approval_tools=["shell"],
        )
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        snapshot = engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True
        assert "requires approval" in snapshot.results[0].content

    @pytest.mark.asyncio
    async def test_agent_loop_executes_sandbox_tool_after_grant(self, workspace_dir: Path) -> None:
        calls: list[str] = []
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": calls.append(command) or "sandbox-ok",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.policy = PolicyEngine(
            workspace_root=str(workspace_dir),
            sandbox_tools=["shell"],
            sandbox_profiles={"shell": "workspace-shell"},
        )
        context = engine.create_run_context(
            workspace_root=str(workspace_dir),
            metadata={"sandbox_profiles": ["workspace-shell"]},
        )
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(
            provider,
            registry=registry,
            engine=engine,
            context_dir=str(workspace_dir),
            run_context=context,
        )

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == ["dir"]
        snapshot = engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is False
        assert "sandbox-ok" in snapshot.results[0].content


class TestToolExecutor:
    @pytest.mark.asyncio
    async def test_custom_executor_can_override_sandbox_backend(self) -> None:
        class RecordingExecutor(ToolExecutor):
            async def execute_in_sandbox(self, *, call, profile, handler):
                return f"sandbox:{profile}:{call.name}"

        executor = RecordingExecutor()
        granted_context = RunContext(
            workspace_root=str(Path.cwd()),
            metadata={"sandbox_profiles": ["workspace-shell"]},
        )
        verdict = PolicyEngine(
            sandbox_tools=["shell"],
            sandbox_profiles={"shell": "workspace-shell"},
        ).evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            context=granted_context,
        )

        result = await executor.execute(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            verdict=verdict,
            guard=type("Guard", (), {"check": lambda self, call: None})(),
            handler=lambda call: asyncio.sleep(0, result="direct"),
            run_context=granted_context,
        )

        assert result.is_error is False
        assert result.content == "sandbox:workspace-shell:shell"
