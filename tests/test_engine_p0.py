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
from heagent.tools.builtins.file import file_write
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
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
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
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
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
    @pytest.mark.asyncio
    async def test_acquire_and_complete(self, workspace_dir: Path) -> None:
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.ledger = engine.ledger.__class__(base_dir=str(workspace_dir / "ledger"))

        claim = await engine.ledger.acquire("cron:test:2026-06-23T10:00", scope="cron")
        assert claim.acquired is True

        duplicate = await engine.ledger.acquire("cron:test:2026-06-23T10:00", scope="cron")
        assert duplicate.acquired is False

        await engine.ledger.complete("cron:test:2026-06-23T10:00")
        record = await engine.ledger.get("cron:test:2026-06-23T10:00")
        assert record is not None
        assert record.status == "completed"

    @pytest.mark.asyncio
    async def test_corrupt_ledger_record_returns_none(self, workspace_dir: Path) -> None:
        """C：损坏的 ledger JSON 不抛 JSONDecodeError，容错返回 None。"""
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.ledger = engine.ledger.__class__(base_dir=str(workspace_dir / "ledger"))
        bad_path = engine.ledger._path("cron:test:bad")
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("{not valid json", encoding="utf-8")
        assert await engine.ledger.get("cron:test:bad") is None

    @pytest.mark.asyncio
    async def test_corrupt_run_snapshot_loads_none(self, workspace_dir: Path) -> None:
        """C：损坏的 run 快照 JSON 容错返回 None（不破坏 resume 链路）。"""
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        bad_path = engine.run_store._path("bad-run")
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("<<broken", encoding="utf-8")
        assert await engine.run_store.load("bad-run") is None

    def test_ledger_io_methods_are_coroutines(self) -> None:
        """D：ledger/store 的 I/O 方法是协程（防回归为同步）。"""
        import asyncio

        from heagent.engine.ledger import ExecutionLedger
        from heagent.engine.store import RunStore

        for method in (
            ExecutionLedger.acquire,
            ExecutionLedger.complete,
            ExecutionLedger.fail,
            ExecutionLedger.get,
            ExecutionLedger._save,
        ):
            assert asyncio.iscoroutinefunction(method), f"{method.__name__} should be async"
        for method in (
            RunStore.save,
            RunStore.load,
            RunStore.start,
            RunStore.checkpoint,
            RunStore.build_run_tree,
        ):
            assert asyncio.iscoroutinefunction(method), f"{method.__name__} should be async"

    def test_atomic_write_leaves_target_intact_on_crash(self, workspace_dir: Path, monkeypatch) -> None:
        """C：os.replace 前崩溃 → 目标保持旧内容，不留半截文件。"""
        from heagent.engine.persist import atomic_write_text

        def _boom(*args: object, **kwargs: object) -> None:
            raise OSError("simulated crash before replace")

        target = workspace_dir / "runs" / "r1.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"old": true}', encoding="utf-8")

        monkeypatch.setattr("heagent.engine.persist.os.replace", _boom)
        with pytest.raises(OSError, match="simulated crash"):
            atomic_write_text(target, '{"new": true}')
        assert target.read_text(encoding="utf-8") == '{"old": true}'


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

    @pytest.mark.asyncio
    async def test_workspace_binding_tracks_run_context_root(self, workspace_dir: Path) -> None:
        nested = workspace_dir / "nested-root"
        nested.mkdir()

        async def write_inside_bound_workspace() -> str:
            engine = EngineContainer.default(workspace_root=str(workspace_dir))
            loop = AgentLoop(StubProvider([_final("ok")]), engine=engine, context_dir=str(workspace_dir))
            run_context = engine.create_run_context(workspace_root=str(nested))
            with loop._runtime_scope(run_context):
                return await file_write("note.txt", "hello")

        result = await write_inside_bound_workspace()

        assert "OK" in result
        assert (nested / "note.txt").read_text(encoding="utf-8") == "hello"
        assert not (workspace_dir / "note.txt").exists()


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
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
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
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
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
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
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

    @pytest.mark.asyncio
    async def test_sandboxed_tool_grant_matches_policy_engine(self) -> None:
        granted_context = RunContext(
            workspace_root=str(Path.cwd()),
            metadata={"sandboxed_tools": ["shell"]},
        )
        verdict = PolicyEngine(
            sandbox_tools=["shell"],
            sandbox_profiles={"shell": "workspace-shell"},
        ).evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            context=granted_context,
        )

        result = await ToolExecutor().execute(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            verdict=verdict,
            guard=type("Guard", (), {"check": lambda self, call: None})(),
            handler=lambda call: asyncio.sleep(0, result="sandboxed-by-name"),
            run_context=granted_context,
        )

        assert result.is_error is False
        assert result.content == "sandboxed-by-name"

    @pytest.mark.asyncio
    async def test_sandbox_runner_injected_into_handler(self) -> None:
        """SANDBOX_REQUIRED + sandbox_runner → executor bind 后 handler 经 get_command_runner 取到该后端。"""
        from heagent.tools.sandbox import get_command_runner

        class _RecordingRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                return f"recorded:{command}"

        async def shell_like_handler(call):
            runner = get_command_runner()
            return await runner.run(call.arguments["command"], timeout=10)

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
        assert verdict.requires_sandbox

        executor = ToolExecutor(sandbox_runner=_RecordingRunner())
        result = await executor.execute(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            verdict=verdict,
            guard=type("Guard", (), {"check": lambda self, call: None})(),
            handler=shell_like_handler,
            run_context=granted_context,
        )

        assert result.is_error is False
        assert result.content == "recorded:dir"

    @pytest.mark.asyncio
    async def test_direct_path_not_polluted_by_runner(self) -> None:
        """DIRECT 路径不 bind → handler 取默认 Passthrough，即使 executor 配了 sandbox_runner。"""
        from heagent.tools.sandbox import PassthroughRunner, get_command_runner

        class _NeverRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                raise AssertionError("DIRECT 路径不应取到 sandbox runner")

        async def shell_like_handler(call):
            runner = get_command_runner()
            assert isinstance(runner, PassthroughRunner)
            return "direct-ok"

        direct_verdict = PolicyEngine().evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
        )
        assert direct_verdict.mode is ToolExecutionMode.DIRECT

        executor = ToolExecutor(sandbox_runner=_NeverRunner())
        result = await executor.execute(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            verdict=direct_verdict,
            guard=type("Guard", (), {"check": lambda self, call: None})(),
            handler=shell_like_handler,
            run_context=None,
        )

        assert result.is_error is False
        assert result.content == "direct-ok"

    def test_container_post_init_injects_runner_to_executor(self) -> None:
        """EngineContainer.__post_init__ 把 command_runner 注入 executor.sandbox_runner。"""
        from heagent.tools.sandbox import FirejailBackend

        backend = FirejailBackend()
        container = EngineContainer(command_runner=backend)
        assert container.executor.sandbox_runner is backend

    def test_container_default_runner_is_none(self) -> None:
        """默认装配 command_runner=None → executor.sandbox_runner=None（透传，向后兼容）。"""
        container = EngineContainer()
        assert container.executor.sandbox_runner is None

    def test_container_preserves_executor_supplied_runner(self) -> None:
        """container.command_runner=None 时不覆写 executor 自带 runner（防 clobber 回归）。"""
        from heagent.tools.sandbox import FirejailBackend

        backend = FirejailBackend()
        executor = ToolExecutor(sandbox_runner=backend)
        container = EngineContainer(executor=executor, command_runner=None)
        assert container.executor.sandbox_runner is backend

    def test_subagent_inherits_runner_via_replace(self) -> None:
        """SubAgent 经 replace(engine, policy=...) 只换 policy，executor 引用不变 → 继承父 runner。"""
        from dataclasses import replace

        from heagent.tools.sandbox import FirejailBackend

        backend = FirejailBackend()
        container = EngineContainer(command_runner=backend)
        child = replace(container, policy=PolicyEngine())
        assert child.executor is container.executor
        assert child.executor.sandbox_runner is backend
