"""Tests for P0 engine runtime services."""

from __future__ import annotations

import asyncio
import logging
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
from heagent.tools.sandbox import SandboxTier
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, TokenUsage, ToolAnnotations, ToolCall, ToolSchema


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

    def test_policy_block_logs_warning(self, workspace_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
        """BLOCKED 裁决落 warning（拦截轨迹可观测，事后可审计）。"""
        policy = PolicyEngine(workspace_root=str(workspace_dir), blocked_tools=["shell"])
        with caplog.at_level(logging.WARNING, logger="heagent.engine.policy"):
            verdict = policy.evaluate_tool_call(
                ToolCall(id="1", name="shell", arguments={"command": "dir"}),
                context=RunContext(workspace_root=str(workspace_dir)),
            )
        assert verdict.allowed is False
        assert any("PolicyEngine blocked 'shell'" in rec.getMessage() for rec in caplog.records)

    def test_policy_approval_logs_info(self, workspace_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
        """APPROVAL_REQUIRED 落 info（需人工介入，区别于硬阻断）。"""
        policy = PolicyEngine(workspace_root=str(workspace_dir), approval_tools=["shell"])
        with caplog.at_level(logging.INFO, logger="heagent.engine.policy"):
            verdict = policy.evaluate_tool_call(
                ToolCall(id="1", name="shell", arguments={"command": "dir"}),
                context=RunContext(workspace_root=str(workspace_dir)),
            )
        assert verdict.requires_approval is True
        assert any("requires approval for 'shell'" in rec.getMessage() for rec in caplog.records)

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
        from heagent.persist import atomic_write_text

        def _boom(*args: object, **kwargs: object) -> None:
            raise OSError("simulated crash before replace")

        target = workspace_dir / "runs" / "r1.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"old": true}', encoding="utf-8")

        monkeypatch.setattr("heagent.persist.os.replace", _boom)
        with pytest.raises(OSError, match="simulated crash"):
            atomic_write_text(target, '{"new": true}')
        assert target.read_text(encoding="utf-8") == '{"old": true}'


class TestPruneLedgerOnce:
    @pytest.mark.asyncio
    async def test_prune_once_dedup(self, workspace_dir: Path) -> None:
        """prune_ledger_once 首次清理、第二次短路返回 0（去重）。"""
        from datetime import UTC, datetime, timedelta

        from heagent.engine.ledger import ExecutionRecord, ExecutionStatus

        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.ledger = engine.ledger.__class__(base_dir=str(workspace_dir / "ledger"))
        engine.ledger_retention_days = 7
        old = (datetime.now(tz=UTC) - timedelta(days=30)).isoformat()
        await engine.ledger._save(ExecutionRecord(key="old:done", status=ExecutionStatus.COMPLETED, finished_at=old))
        assert await engine.prune_ledger_once() == 1
        # 第二次短路（_pruned=True）
        assert await engine.prune_ledger_once() == 0

    @pytest.mark.asyncio
    async def test_prune_once_zero_retention_noop(self, workspace_dir: Path) -> None:
        """ledger_retention_days=0 时 prune_ledger_once 直接返回 0（禁用）。"""
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.ledger = engine.ledger.__class__(base_dir=str(workspace_dir / "ledger"))
        engine.ledger_retention_days = 0
        assert await engine.prune_ledger_once() == 0


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

        call_count = 0

        async def run_job(prompt: str, ctx: RunContext) -> None:
            nonlocal call_count
            call_count += 1

        scheduler = CronScheduler(store, engine=engine, job_runner=run_job)
        due = datetime(2026, 6, 23, 10, 15, 0)

        await scheduler._execute_job(job, now=due)
        await scheduler._execute_job(job, now=due)

        assert call_count == 1


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
            async def execute_in_sandbox(self, *, call, profile, handler, run_context=None):
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


class TestPolicyAnnotationGate:
    """MCP V2 写操作治理: annotations → PolicyVerdict 确定性裁决(FR-A3/A4/A5/A6,AD-3).

    所有测试不触达任何 LLM provider(纯函数,确定性可单测,FR-A6).
    """

    _MCP_CALL = ToolCall(id="m1", name="github__list_issues", arguments={})
    _BUILTIN_CALL = ToolCall(id="b1", name="shell", arguments={"command": "dir"})

    def test_destructive_hint_requires_approval(self) -> None:
        """FR-A3: destructiveHint=true → APPROVAL_REQUIRED(未授权时)."""
        policy = PolicyEngine()
        schema = ToolSchema(
            name="github__delete_repo",
            description="Delete repo",
            parameters={},
            annotations=ToolAnnotations(destructiveHint=True),
        )
        verdict = policy.evaluate_tool_call(self._MCP_CALL, schema=schema)
        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert "destructiveHint" in verdict.reason

    def test_destructive_hint_after_approval_grants(self) -> None:
        policy = PolicyEngine()
        schema = ToolSchema(
            name="github__delete_repo",
            description="Delete repo",
            parameters={},
            annotations=ToolAnnotations(destructiveHint=True),
        )
        ctx = RunContext(
            workspace_root=str(Path.cwd()),
            metadata={"approved_tools": ["github__delete_repo"]},
        )
        verdict = policy.evaluate_tool_call(
            ToolCall(id="m2", name="github__delete_repo", arguments={}),
            context=ctx,
            schema=schema,
        )
        assert verdict.mode is not ToolExecutionMode.APPROVAL_REQUIRED

    def test_readonly_hint_passes_without_approval(self) -> None:
        policy = PolicyEngine()
        schema = ToolSchema(
            name="github__list_issues",
            description="List issues",
            parameters={},
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        verdict = policy.evaluate_tool_call(self._MCP_CALL, schema=schema)
        assert verdict.mode is not ToolExecutionMode.APPROVAL_REQUIRED

    def test_explicit_approval_overrides_readonly_hint(self) -> None:
        policy = PolicyEngine(approval_mcp_tools=True)
        schema = ToolSchema(
            name="github__list_issues",
            description="List issues",
            parameters={},
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        verdict = policy.evaluate_tool_call(self._MCP_CALL, schema=schema)
        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert "approval_mcp_tools=True" in verdict.reason

    def test_no_annotations_failsafe_requires_approval(self) -> None:
        policy = PolicyEngine()
        schema = ToolSchema(
            name="github__list_issues",
            description="List issues",
            parameters={},
            annotations=None,
        )
        verdict = policy.evaluate_tool_call(self._MCP_CALL, schema=schema)
        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert "fail-safe" in verdict.reason

    def test_builtin_tool_schema_none_skips_annotation_gate(self) -> None:
        policy = PolicyEngine()
        verdict = policy.evaluate_tool_call(self._BUILTIN_CALL, schema=None)
        assert verdict.mode is ToolExecutionMode.DIRECT

    def test_builtin_tool_with_approval_tools_still_works(self) -> None:
        policy = PolicyEngine(approval_tools=["shell"])
        ctx = RunContext(workspace_root=str(Path.cwd()))
        verdict = policy.evaluate_tool_call(self._BUILTIN_CALL, schema=None, context=ctx)
        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert "approval_tools" in verdict.reason

    def test_idempotent_hint_does_not_affect_verdict(self) -> None:
        policy = PolicyEngine()
        schema = ToolSchema(
            name="github__list_issues",
            description="List issues",
            parameters={},
            annotations=ToolAnnotations(idempotentHint=True),
        )
        # annotations 存在(非None)但 destructiveHint/readOnlyHint 均为 False → fail-safe 需审批
        # idempotentHint 不影响裁决（policy 不读取该字段）
        verdict = policy.evaluate_tool_call(self._MCP_CALL, schema=schema)
        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED

    def test_wildcard_approval_grants_mcp_tool(self) -> None:
        policy = PolicyEngine()
        schema = ToolSchema(
            name="github__delete_repo",
            description="Delete repo",
            parameters={},
            annotations=ToolAnnotations(destructiveHint=True),
        )
        ctx = RunContext(
            workspace_root=str(Path.cwd()),
            metadata={"approved_tools": ["*"]},
        )
        verdict = policy.evaluate_tool_call(
            ToolCall(id="m3", name="github__delete_repo", arguments={}),
            context=ctx,
            schema=schema,
        )
        assert verdict.mode is not ToolExecutionMode.APPROVAL_REQUIRED

    def test_mcp_wildcard_approval_grants_mcp_tool(self) -> None:
        policy = PolicyEngine()
        schema = ToolSchema(
            name="github__delete_repo",
            description="Delete repo",
            parameters={},
            annotations=ToolAnnotations(destructiveHint=True),
        )
        ctx = RunContext(
            workspace_root=str(Path.cwd()),
            metadata={"approved_tools": ["__mcp__"]},
        )
        verdict = policy.evaluate_tool_call(
            ToolCall(id="m4", name="github__delete_repo", arguments={}),
            context=ctx,
            schema=schema,
        )
        assert verdict.mode is not ToolExecutionMode.APPROVAL_REQUIRED

    def test_non_mcp_tool_with_schema_does_not_failsafe(self) -> None:
        policy = PolicyEngine()
        schema = ToolSchema(
            name="file_read",
            description="Read file",
            parameters={},
            annotations=None,
        )
        verdict = policy.evaluate_tool_call(
            ToolCall(id="b2", name="file_read", arguments={"path": "/tmp/x"}),
            schema=schema,
        )
        assert verdict.mode is ToolExecutionMode.DIRECT


class TestSandboxSessionWorkspace:
    """FR-1: create_run_context 沙箱会话目录两态 + execute_in_sandbox bind 生效。"""

    @pytest.fixture(autouse=True)
    def _reset_settings_around(self):
        """每测试前后重置 Settings 单例，防 SANDBOX_SESSION_WORKSPACE 泄漏到后续测试。"""
        from heagent.config import reset_settings

        reset_settings()
        yield
        reset_settings()

    def test_switch_off_no_metadata_no_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """开关关（默认）：无 metadata 键、不建目录——与现状一致。"""
        monkeypatch.delenv("SANDBOX_SESSION_WORKSPACE", raising=False)
        monkeypatch.chdir(tmp_path)
        engine = EngineContainer(workspace_root=str(tmp_path))
        ctx = engine.create_run_context()
        assert "sandbox_workspace" not in ctx.metadata
        assert not (tmp_path / ".heagent" / "sandboxes").exists()

    def test_switch_on_writes_metadata_and_creates_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """开关开：metadata["sandbox_workspace"] = <cwd>/.heagent/sandboxes/<run_id>/ 且目录存在。"""
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        monkeypatch.chdir(tmp_path)
        engine = EngineContainer(workspace_root=str(tmp_path))
        ctx = engine.create_run_context()
        expected = tmp_path / ".heagent" / "sandboxes" / ctx.run_id
        assert ctx.metadata["sandbox_workspace"] == str(expected)
        assert expected.is_dir()

    def test_switch_on_mkdir_failure_raises_with_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """开关开但目录不可创建 → create_run_context 抛异常（含目标路径），不静默降级（NFR-1）。"""
        import re

        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".heagent").write_text("placeholder file, not a dir")  # 占位文件 → 子路径 mkdir 失败
        engine = EngineContainer(workspace_root=str(tmp_path))
        with pytest.raises(RuntimeError) as excinfo:
            engine.create_run_context()
        # 消息含目标路径（.heagent/sandboxes/<run_id>），且链了原始 OSError
        assert ".heagent" in str(excinfo.value)
        assert "sandboxes" in str(excinfo.value)
        assert excinfo.value.__cause__ is not None
        assert isinstance(excinfo.value.__cause__, OSError)
        assert re.search(r"sandboxes[/\\][0-9a-f]{32}", str(excinfo.value))

    def test_dir_anchors_to_workspace_root_not_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """修订1 主断言：进程 cwd=A、container workspace_root=B → 目录落 B 下、绝不落 A 下。

        真实 caller（loop/sub/cron）传的 root 可 ≠ cwd；分叉时目录若锚 cwd 会逃出
        file 工具围栏（shell 写入产物 file 工具不可读，split-brain）。
        """
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        cwd_a = tmp_path / "cwd-a"
        root_b = tmp_path / "root-b"
        cwd_a.mkdir()
        root_b.mkdir()
        monkeypatch.chdir(cwd_a)
        engine = EngineContainer(workspace_root=str(root_b))
        ctx = engine.create_run_context()
        expected = root_b / ".heagent" / "sandboxes" / ctx.run_id
        assert ctx.metadata["sandbox_workspace"] == str(expected)
        assert expected.is_dir()
        # 绝不落在进程 cwd 下（A 无任何沙箱目录痕迹）
        assert not (cwd_a / ".heagent").exists()

    def test_explicit_param_root_wins_in_fork(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """回退链最高优先级：参数 root=C 覆盖 container root=B 与 cwd=A，目录落 C。"""
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        cwd_a = tmp_path / "cwd-a"
        root_b = tmp_path / "root-b"
        root_c = tmp_path / "root-c"
        cwd_a.mkdir()
        root_b.mkdir()
        root_c.mkdir()
        monkeypatch.chdir(cwd_a)
        engine = EngineContainer(workspace_root=str(root_b))
        ctx = engine.create_run_context(workspace_root=str(root_c))
        expected = root_c / ".heagent" / "sandboxes" / ctx.run_id
        assert ctx.metadata["sandbox_workspace"] == str(expected)
        assert expected.is_dir()
        assert not (root_b / ".heagent").exists()

    def test_preseeded_key_cleared_when_switch_off(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """修订1：caller metadata 预含 sandbox_workspace + 开关关 → 键被清除，不 bind。"""
        monkeypatch.delenv("SANDBOX_SESSION_WORKSPACE", raising=False)
        monkeypatch.chdir(tmp_path)
        engine = EngineContainer(workspace_root=str(tmp_path))
        ctx = engine.create_run_context(metadata={"sandbox_workspace": "/stale/path"})
        assert "sandbox_workspace" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_execute_in_sandbox_binds_workspace_from_metadata(self, tmp_path: Path) -> None:
        """metadata 含 sandbox_workspace → handler 内 get_sandbox_workspace() 取到该目录。"""
        from heagent.tools.sandbox import get_sandbox_workspace

        class _RecordingRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                return "recorded"

        captured: list[Path | None] = []

        async def handler(call):
            captured.append(get_sandbox_workspace())
            return "ok"

        session = tmp_path / "session-dir"
        session.mkdir()
        ctx = RunContext(workspace_root=str(tmp_path), metadata={"sandbox_workspace": str(session)})
        executor = ToolExecutor(sandbox_runner=_RecordingRunner())
        await executor.execute_in_sandbox(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            profile=None,
            handler=handler,
            run_context=ctx,
        )
        assert captured == [session]

    @pytest.mark.asyncio
    async def test_execute_in_sandbox_without_metadata_no_bind(self, tmp_path: Path) -> None:
        """metadata 无键 / run_context=None → 不 bind，handler 内取 None（现状一致）。"""
        from heagent.tools.sandbox import get_sandbox_workspace

        class _RecordingRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                return "recorded"

        captured: list[Path | None] = []

        async def handler(call):
            captured.append(get_sandbox_workspace())
            return "ok"

        executor = ToolExecutor(sandbox_runner=_RecordingRunner())
        await executor.execute_in_sandbox(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            profile=None,
            handler=handler,
            run_context=RunContext(workspace_root=str(tmp_path)),
        )
        await executor.execute_in_sandbox(
            call=ToolCall(id="2", name="shell", arguments={"command": "dir"}),
            profile=None,
            handler=handler,
            run_context=None,
        )
        assert captured == [None, None]

    @pytest.mark.asyncio
    async def test_non_str_metadata_value_no_bind(self, tmp_path: Path) -> None:
        """修订1：sandbox_workspace 非 str（int）/ 空串 → 不 bind（None），不抛异常。"""
        from heagent.tools.sandbox import get_sandbox_workspace

        class _RecordingRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                return "recorded"

        captured: list[Path | None] = []

        async def handler(call):
            captured.append(get_sandbox_workspace())
            return "ok"

        executor = ToolExecutor(sandbox_runner=_RecordingRunner())
        await executor.execute_in_sandbox(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            profile=None,
            handler=handler,
            run_context=RunContext(workspace_root=str(tmp_path), metadata={"sandbox_workspace": 123}),
        )
        await executor.execute_in_sandbox(
            call=ToolCall(id="2", name="shell", arguments={"command": "dir"}),
            profile=None,
            handler=handler,
            run_context=RunContext(workspace_root=str(tmp_path), metadata={"sandbox_workspace": ""}),
        )
        assert captured == [None, None]

    @pytest.mark.asyncio
    async def test_missing_session_dir_raises_before_bind(self, tmp_path: Path) -> None:
        """修订1：metadata 指向不存在的目录 → bind 前抛 RuntimeError("sandbox workspace missing: <path>")。"""

        class _RecordingRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                return "recorded"

        async def handler(call):
            raise AssertionError("目录缺失应在 handler 前（bind 前）显性失败")

        missing = tmp_path / "never-created"
        ctx = RunContext(workspace_root=str(tmp_path), metadata={"sandbox_workspace": str(missing)})
        executor = ToolExecutor(sandbox_runner=_RecordingRunner())
        with pytest.raises(RuntimeError, match="sandbox workspace missing") as excinfo:
            await executor.execute_in_sandbox(
                call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
                profile=None,
                handler=handler,
                run_context=ctx,
            )
        assert str(missing) in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_no_runner_with_workspace_logs_ignored_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """修订1：sandbox_runner=None + metadata 含会话目录 → 明确 warning（sandbox_workspace ignored）。"""
        import logging

        session = tmp_path / "session-dir"
        session.mkdir()
        ctx = RunContext(workspace_root=str(tmp_path), metadata={"sandbox_workspace": str(session)})
        with caplog.at_level(logging.WARNING, logger="heagent.engine.executor"):
            result = await ToolExecutor().execute_in_sandbox(
                call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
                profile=None,
                handler=lambda call: asyncio.sleep(0, result="passthrough"),
                run_context=ctx,
            )
        assert result == "passthrough"
        assert any("sandbox_workspace ignored" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_old_signature_subclass_override_compat(self, tmp_path: Path) -> None:
        """修订1：库消费者旧签名 execute_in_sandbox(*, call, profile, handler) 经 execute() 不 TypeError。"""

        class OldSignatureExecutor(ToolExecutor):
            async def execute_in_sandbox(self, *, call, profile, handler):
                return f"legacy:{call.name}"

        session = tmp_path / "session-dir"
        session.mkdir()
        granted_context = RunContext(
            workspace_root=str(tmp_path),
            metadata={"sandbox_profiles": ["workspace-shell"], "sandbox_workspace": str(session)},
        )
        verdict = PolicyEngine(
            sandbox_tools=["shell"],
            sandbox_profiles={"shell": "workspace-shell"},
        ).evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            context=granted_context,
        )
        assert verdict.requires_sandbox

        executor = OldSignatureExecutor()
        result = await executor.execute(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            verdict=verdict,
            guard=type("Guard", (), {"check": lambda self, call: None})(),
            handler=lambda call: asyncio.sleep(0, result="unused"),
            run_context=granted_context,
        )
        assert result.is_error is False
        assert result.content == "legacy:shell"

    @pytest.mark.asyncio
    async def test_execute_threads_run_context_into_sandbox(self, tmp_path: Path) -> None:
        """SANDBOX_REQUIRED 完整链路：run_context 经 execute() 流至 execute_in_sandbox 并 bind。"""
        from heagent.tools.sandbox import get_sandbox_workspace

        class _RecordingRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                return "recorded"

        captured: list[Path | None] = []

        async def shell_like_handler(call):
            captured.append(get_sandbox_workspace())
            return "sandboxed"

        session = tmp_path / "session-x"
        session.mkdir()
        granted_context = RunContext(
            workspace_root=str(tmp_path),
            metadata={"sandbox_profiles": ["workspace-shell"], "sandbox_workspace": str(session)},
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
        assert captured == [session]


class TestSandboxSessionSwitchPrecedence:
    """E40-D4: 沙箱会话两开关三态（CLI 显式值 > Settings/env），含 default() 透传。"""

    @pytest.fixture(autouse=True)
    def _reset_settings_around(self):
        """每测试前后重置 Settings 单例，防 SANDBOX_SESSION_* 泄漏到后续测试。"""
        from heagent.config import reset_settings

        reset_settings()
        yield
        reset_settings()

    def test_container_true_overrides_env_false(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """显式 True（CLI ``--sandbox-session-workspace``）压过 env 的 false。"""
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "false")
        monkeypatch.chdir(tmp_path)
        engine = EngineContainer(workspace_root=str(tmp_path), sandbox_session_workspace=True)
        ctx = engine.create_run_context()
        assert ctx.metadata["sandbox_workspace"] == str(tmp_path / ".heagent" / "sandboxes" / ctx.run_id)

    def test_container_false_overrides_env_true(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """显式 False（CLI ``--no-sandbox-session-workspace``）压过 env 的 true。

        这是三态（而非「只能开」）的意义：env 开了也能在单次运行里关掉。
        """
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        monkeypatch.chdir(tmp_path)
        engine = EngineContainer(workspace_root=str(tmp_path), sandbox_session_workspace=False)
        ctx = engine.create_run_context()
        assert "sandbox_workspace" not in ctx.metadata
        assert not (tmp_path / ".heagent" / "sandboxes").exists()

    def test_container_none_follows_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """选项缺席（None）跟随 env——不传标志时行为与改动前逐字节一致。"""
        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        monkeypatch.chdir(tmp_path)
        engine = EngineContainer(workspace_root=str(tmp_path))
        ctx = engine.create_run_context()
        assert ctx.metadata["sandbox_workspace"] == str(tmp_path / ".heagent" / "sandboxes" / ctx.run_id)

    def test_keep_switch_precedence(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """teardown 保留开关同样三态：显式值压过 env，None 跟随 env。"""
        monkeypatch.setenv("SANDBOX_SESSION_KEEP", "false")
        keeping = EngineContainer(workspace_root=str(tmp_path), sandbox_session_keep=True)
        assert keeping._session_keep_enabled() is True

        monkeypatch.setenv("SANDBOX_SESSION_KEEP", "true")
        dropping = EngineContainer(workspace_root=str(tmp_path), sandbox_session_keep=False)
        assert dropping._session_keep_enabled() is False
        assert EngineContainer(workspace_root=str(tmp_path))._session_keep_enabled() is True

    def test_default_forwards_session_flags(self, tmp_path: Path) -> None:
        """``default()`` 把两个会话开关透传到容器（CLI/GUI 的唯一装配路径）。"""
        engine = EngineContainer.default(
            workspace_root=str(tmp_path),
            sandbox_backend="passthrough",
            sandbox_session_workspace=True,
            sandbox_session_keep=False,
        )
        assert engine.sandbox_session_workspace is True
        assert engine.sandbox_session_keep is False


class TestSandboxBackendTier:
    """FR-2: executor 查询后端强度档位 + emit 事件传递 sandbox_tier。"""

    def test_runner_tier_none_is_passthrough(self) -> None:
        executor = ToolExecutor()  # sandbox_runner=None（透传快速路径）
        assert executor._runner_tier() is SandboxTier.PASSTHROUGH

    def test_runner_tier_reflects_injected_backend(self) -> None:
        class _TierRunner:
            tier = SandboxTier.FIREJAIL

            async def run(self, command: str, *, timeout: int) -> str:
                return "ok"

        executor = ToolExecutor(sandbox_runner=_TierRunner())
        assert executor._runner_tier() is SandboxTier.FIREJAIL

    @pytest.mark.asyncio
    async def test_emit_details_include_sandbox_tier(self, tmp_path: Path) -> None:
        """SANDBOX_REQUIRED 链路 emit 事件 details 含当前后端档位字符串。"""

        class _RecordingRunner:
            tier = SandboxTier.JOB

            async def run(self, command: str, *, timeout: int) -> str:
                return "recorded"

        events: list[tuple[str, dict]] = []

        def emit(name, **kwargs):
            events.append((name, kwargs.get("details") or {}))

        session = tmp_path / "sess"
        session.mkdir()
        granted = RunContext(
            workspace_root=str(tmp_path),
            metadata={"sandbox_profiles": ["ws"], "sandbox_workspace": str(session)},
        )
        verdict = PolicyEngine(sandbox_tools=["shell"], sandbox_profiles={"shell": "ws"}).evaluate_tool_call(
            ToolCall(id="1", name="shell", arguments={"command": "dir"}), context=granted
        )
        assert verdict.requires_sandbox

        async def shell_like_handler(call):
            return "sandboxed"

        executor = ToolExecutor(sandbox_runner=_RecordingRunner())
        result = await executor.execute(
            call=ToolCall(id="1", name="shell", arguments={"command": "dir"}),
            verdict=verdict,
            guard=type("Guard", (), {"check": lambda self, call: None})(),
            handler=shell_like_handler,
            run_context=granted,
            emit=emit,
        )
        assert result.is_error is False

        started = [d for n, d in events if n == "tool_call_started"]
        assert started, "expected tool_call_started event"
        assert started[0]["sandbox_tier"] == "job"
        completed = [d for n, d in events if n == "tool_call_completed"]
        assert completed and completed[0]["sandbox_tier"] == "job"


class TestSandboxSessionBinding:
    """FR-4: execute_in_sandbox 绑定 SandboxSession（handler 可取到）。"""

    @pytest.mark.asyncio
    async def test_execute_in_sandbox_binds_session(self, tmp_path: Path) -> None:
        from heagent.tools.sandbox import get_sandbox_session, pop_session

        class _RecordingRunner:
            tier = SandboxTier.FIREJAIL

            async def run(self, command, *, timeout):
                return "recorded"

        captured: list[object] = []

        async def handler(call):
            captured.append(get_sandbox_session())
            return "ok"

        session_dir = tmp_path / "session-dir"
        session_dir.mkdir()
        ctx = RunContext(workspace_root=str(tmp_path), metadata={"sandbox_workspace": str(session_dir)})
        executor = ToolExecutor(sandbox_runner=_RecordingRunner())
        await executor.execute_in_sandbox(
            call=ToolCall(id="1", name="shell", arguments={"command": "pwd"}),
            profile=None,
            handler=handler,
            run_context=ctx,
        )
        pop_session(ctx.run_id)  # 清理模块级会话缓存

        assert len(captured) == 1
        assert captured[0] is not None
        assert captured[0].cwd == session_dir
