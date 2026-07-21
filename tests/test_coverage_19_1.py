"""Story 19-1: 覆盖率 90% 专项测试。

覆盖多个模块中 1-4 条未覆盖语句，优先低风险、高确定性。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path  # noqa: TC003
from unittest.mock import MagicMock, patch

import pytest

from heagent.agent.middleware import make_retry_middleware
from heagent.agent.system_prompt import build_system_prompt
from heagent.engine.container import EngineContainer
from heagent.engine.context import RunContext
from heagent.engine.observability import EventBus
from heagent.engine.store import RunStore
from heagent.memory.profile import ProfileStore
from heagent.providers.base import ProviderMetadata
from heagent.tools.builtins.file import file_read, file_write
from heagent.tools.builtins.subagent import (
    SubagentToolRuntime,
    _record_step,
    _resolve_role,
    configure_subagent_tools,
    reset_subagent_tools,
    task_parallel,
)
from heagent.tools.decorator import tool
from heagent.tools.mcp.config import _parse_server
from heagent.tools.path_safety import (
    WorkspacePathError,
    configure_workspace_root,
    reset_workspace_root,
    resolve_under_root,
    set_workspace_root,
    workspace_root,
)
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard
from heagent.types import ToolCall

# ── Stub provider for subagent tests ─────────────────────────────────

class StubProvider:
    """Minimal stub provider that satisfies the BaseProvider protocol."""

    async def send(self, messages, *, tools=None):
        pass

    async def stream(self, messages, *, tools=None):
        yield None
        return

    def get_metadata(self):
        return ProviderMetadata(name="stub", model="stub")


# ══════════════════════════════════════════════════════════════════════
# 1. registry.py:45 — ToolRegistry.reset()
# ══════════════════════════════════════════════════════════════════════


class TestRegistryReset:
    def test_reset_clears_singleton(self) -> None:
        """reset() 清空单例，下次 get() 返回新实例。"""
        a = ToolRegistry.get()
        ToolRegistry.reset()
        b = ToolRegistry.get()
        assert b is not None
        ToolRegistry._instance = a  # 恢复，不污染其他测试


# ══════════════════════════════════════════════════════════════════════
# 2. decorator.py:79 — @tool 参数有默认值
# ══════════════════════════════════════════════════════════════════════


class TestDecoratorDefaultParam:
    def test_default_param_stored_in_schema(self) -> None:
        """@tool 装饰器：有默认值的参数在 parameters.properties 中带 default。"""

        @tool
        def with_defaults(name: str, count: int = 42, verbose: bool = True) -> str:
            """Func with defaults."""
            return ""

        schema = ToolRegistry.get().get_schema("with_defaults")
        assert schema is not None
        props: dict[str, object] = schema.parameters.get("properties", {})  # type: ignore[assignment]
        assert props["count"]["default"] == 42
        assert props["verbose"]["default"] is True
        assert "count" not in schema.parameters["required"]
        ToolRegistry.get().unregister("with_defaults")


# ══════════════════════════════════════════════════════════════════════
# 3. safety.py:106 — shell 命令非字符串类型时 early return
# ══════════════════════════════════════════════════════════════════════


class TestSafetyNonStringCommand:
    def test_non_string_command_skipped(self) -> None:
        """shell 工具传入非 str 命令 → 跳过危险模式检查，不抛异常。"""
        guard = SafetyGuard()
        guard.check(ToolCall(id="tc", name="shell", arguments={"command": 123}))


# ══════════════════════════════════════════════════════════════════════
# 4. mapping.py:93 — call_result_to_text 未知内容块类型 (else branch)
# ══════════════════════════════════════════════════════════════════════


class TestMappingUnknownBlock:
    def test_unknown_block_type_placeholder(self) -> None:
        """call_result_to_text 遇到未知 block 类型 → [unknown: type_name] 占位。"""
        from mcp.types import CallToolResult

        from heagent.tools.mcp.mapping import call_result_to_text

        # 用 model_construct 绕过 Pydantic 验证，直接注入未知类型的 content item
        class UnknownItem:
            pass

        item = UnknownItem()
        r = CallToolResult.model_construct(content=[item], isError=False)
        text = call_result_to_text(r)
        assert "[unknown: UnknownItem]" in text


# ══════════════════════════════════════════════════════════════════════
# 5. mcp/config.py:72 — _parse_server 既无 command 也无 url
# ══════════════════════════════════════════════════════════════════════


class TestMCPConfigInvalidServer:
    def test_parse_server_no_command_no_url_raises(self) -> None:
        """_parse_server：无 command 且无 url → ToolError。"""
        from heagent.exceptions import ToolError

        with pytest.raises(ToolError, match="缺少 command"):
            _parse_server("broken", {"type": "stdio"})


# ══════════════════════════════════════════════════════════════════════
# 6. middleware.py:106 — make_retry_middleware 返回值
# ══════════════════════════════════════════════════════════════════════


class TestMakeRetryMiddleware:
    @pytest.mark.asyncio
    async def test_retry_middleware_callable_and_passes_through(self) -> None:
        """make_retry_middleware 返回可调用中间件，正常路径透传结果。"""
        mw = make_retry_middleware(max_attempts=1, base_delay=0.01)

        call_count = 0

        async def fake_next(req: object) -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await mw("req", fake_next)
        assert result == "ok"
        assert call_count == 1


# ══════════════════════════════════════════════════════════════════════
# 7. store.py:100 — checkpoint() 更新已存在的快照
# ══════════════════════════════════════════════════════════════════════


class TestStoreCheckpointUpdateExisting:
    @pytest.mark.asyncio
    async def test_checkpoint_updates_existing_snapshot(self, tmp_path: Path) -> None:
        """checkpoint() 对已存在快照走增量合并路径（load → 覆盖字段 → save）。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = RunContext()

        await store.start(ctx, prompt="first")
        await store.checkpoint(ctx, prompt="second", final_answer="done")

        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert snapshot.prompt == "second"
        assert snapshot.final_answer == "done"


# ══════════════════════════════════════════════════════════════════════
# 8. path_safety.py:41 — resolve_under_root 路径逃逸
# ══════════════════════════════════════════════════════════════════════


class TestPathSafetyEscape:
    def test_resolve_under_root_raises_on_escape(self, tmp_path: Path) -> None:
        """resolve_under_root 检测到路径逃逸时抛 WorkspacePathError。"""
        root = tmp_path / "ws"
        root.mkdir()
        with pytest.raises(WorkspacePathError, match="escapes"):
            resolve_under_root("../../etc/passwd", root)


# ══════════════════════════════════════════════════════════════════════
# 9. path_safety.py:67 — configure_workspace_root
# ══════════════════════════════════════════════════════════════════════


class TestConfigureWorkspaceRoot:
    def test_configure_then_resolve(self, tmp_path: Path) -> None:
        """configure_workspace_root 设置后 workspace_root() 返回该路径。"""
        try:
            configure_workspace_root(tmp_path.resolve())
            assert workspace_root() == tmp_path.resolve()
        finally:
            # 必须用 None 清除 RuntimeSlot，否则其优先级高于 _workspace_override，
            # 会污染其他测试的 set_workspace_root(tmp_path) 路径。
            configure_workspace_root(None)


# ══════════════════════════════════════════════════════════════════════
# 10. subagent.py:173 — _resolve_role 从 runtime map 命中
# ══════════════════════════════════════════════════════════════════════


class TestResolveRole:
    def test_resolve_role_from_runtime_map(self) -> None:
        """_resolve_role 在 runtime.roles 中命中时返回该 RoleSpec。"""
        from heagent.engine.roles import RoleSpec

        runtime = SubagentToolRuntime(
            provider=None,
            registry=None,
            guard=None,
            skills=None,
            facts=None,
            profile=None,
            compressor=None,
            context_dir=None,
            soul=None,
            engine=None,
            parent_run_id=None,
        )
        spec = RoleSpec(name="custom", system="custom system")
        runtime.roles = {"custom": spec}
        result, err = _resolve_role(runtime, "custom")
        assert result is spec
        assert err is None

    def test_resolve_role_unknown(self) -> None:
        """_resolve_role 未知 role → 返回错误，列出可用角色。"""
        runtime = SubagentToolRuntime(
            provider=None,
            registry=None,
            guard=None,
            skills=None,
            facts=None,
            profile=None,
            compressor=None,
            context_dir=None,
            soul=None,
            engine=None,
            parent_run_id=None,
        )
        result, err = _resolve_role(runtime, "ghost_role")
        assert result is None
        assert err is not None
        assert "Unknown role" in err
        assert "Available" in err


# ══════════════════════════════════════════════════════════════════════
# 11. subagent.py:275 — task_parallel 未知 role 返回错误
# ══════════════════════════════════════════════════════════════════════


class TestTaskParallelUnknownRole:
    @pytest.mark.asyncio
    async def test_task_parallel_unknown_role_error(self) -> None:
        """task_parallel 传入未知 role → 返回错误 payload。"""
        configure_subagent_tools(provider=StubProvider())
        try:
            result = await task_parallel(
                tasks_json=json.dumps(["task 1", "task 2"]),
                role="this_role_does_not_exist",
            )
            assert isinstance(result, str)
            parsed = json.loads(result)
            assert parsed["status"] == "error"
            assert "Unknown role" in parsed["message"]
        finally:
            reset_subagent_tools()


# ══════════════════════════════════════════════════════════════════════
# 12. observability.py:94, 105-106, 131 — EventBus subscribe/emit/recent
# ══════════════════════════════════════════════════════════════════════


class FakeObserver:
    """简单观察者：记录事件用于断言。"""

    def __init__(self) -> None:
        self.events: list = []

    def handle(self, event) -> None:  # type: ignore[no-untyped-def]
        self.events.append(event)


class TestEventBus:
    def test_subscribe_and_emit(self) -> None:
        """EventBus.subscribe → emit → 观察者收到事件（line 94, 105-106）。"""
        bus = EventBus()
        obs = FakeObserver()
        bus.subscribe(obs)

        _event = bus.publish("test.event", run_id="r1", iteration=1)
        assert len(obs.events) == 1
        assert obs.events[0].event_type == "test.event"

    def test_recent_events_returns_buffer(self) -> None:
        """EventBus.recent_events 返回缓冲事件列表（line 131）。"""
        bus = EventBus(retain=3)
        bus.publish("e1")
        bus.publish("e2")
        recent = bus.recent_events
        assert len(recent) == 2
        assert [e.event_type for e in recent] == ["e1", "e2"]

    def test_emit_observer_exception_not_propagated(self, caplog) -> None:
        """emit 中观察者抛异常：记录日志，不影响其他观察者（line 105-106）。"""
        bus = EventBus()
        good = FakeObserver()

        bad = MagicMock()
        bad.handle.side_effect = RuntimeError("observer crash")

        bus.subscribe(bad)
        bus.subscribe(good)

        with caplog.at_level(logging.ERROR):
            bus.publish("test.crash")

        assert len(good.events) == 1
        assert any("Event observer failed" in r.message for r in caplog.records)


# ══════════════════════════════════════════════════════════════════════
# 13. container.py:91-96 — WinJobBackend 回退路径
# ══════════════════════════════════════════════════════════════════════


class TestContainerWinJobFallback:
    def test_winjob_unavailable_falls_back(self, caplog) -> None:
        """EngineContainer.default(sandbox_backend='winjob') 在不可用时回退。"""
        with (
            patch("heagent.tools.sandbox.WinJobBackend.available", return_value=False),
            caplog.at_level(logging.WARNING),
        ):
            container = EngineContainer.default(sandbox_backend="winjob")

        assert container is not None
        assert any("falling back to Passthrough" in r.message for r in caplog.records)


# ══════════════════════════════════════════════════════════════════════
# 14. file.py:73-74, 87-88 — file_read/file_write WorkspacePathError
# ══════════════════════════════════════════════════════════════════════


class TestFileWorkspaceError:
    @pytest.mark.asyncio
    async def test_file_read_workspace_error(self, tmp_path: Path) -> None:
        """file_read 路径逃逸时返回 error 字符串而非抛异常。"""
        try:
            set_workspace_root(tmp_path.resolve())
            result = await file_read("../outside.txt")
            assert "Error:" in result
        finally:
            reset_workspace_root()
            configure_workspace_root(None)

    @pytest.mark.asyncio
    async def test_file_write_workspace_error(self, tmp_path: Path) -> None:
        """file_write 路径逃逸时返回 error 字符串而非抛异常。"""
        try:
            set_workspace_root(tmp_path.resolve())
            result = await file_write("../outside.txt", "bad content")
            assert "Error:" in result
        finally:
            reset_workspace_root()
            configure_workspace_root(None)


# ══════════════════════════════════════════════════════════════════════
# 15. system_prompt.py:65-66 — context_files 启用且命中
# ══════════════════════════════════════════════════════════════════════


class TestBuildSystemContextFiles:
    def test_context_files_enabled_with_content(self, tmp_path: Path) -> None:
        """context_files_enabled=True 且存在上下文文件时注入 <project-context>。"""
        (tmp_path / "CLAUDE.md").write_text("# Test Context\nhello", encoding="utf-8")

        from heagent.config import get_settings

        settings = get_settings()
        old_enabled = settings.context_files_enabled
        try:
            settings.context_files_enabled = True
            result = build_system_prompt(
                user_system=None,
                prompt="hello",
                soul=None,
                context_dir=str(tmp_path),
                skills=None,
                facts=None,
                profile=None,
            )
            assert result is not None
            assert "<project-context>" in result
            assert "Test Context" in result
        finally:
            settings.context_files_enabled = old_enabled


# ══════════════════════════════════════════════════════════════════════
# 16. system_prompt.py:124-127 — profile 非空文本
# ══════════════════════════════════════════════════════════════════════


class TestBuildSystemProfile:
    def test_profile_with_content_injected(self, tmp_path: Path) -> None:
        """profile.load() 返回非空文本时注入 <profile> 块。"""
        profile_path = tmp_path / "USER.md"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text("用户偏好：中文回复", encoding="utf-8")
        profile = ProfileStore(path=str(profile_path))

        result = build_system_prompt(
            user_system=None,
            prompt="hello",
            soul=None,
            context_dir=None,
            skills=None,
            facts=None,
            profile=profile,
        )
        assert result is not None
        assert "<profile>" in result
        assert "中文回复" in result


# ══════════════════════════════════════════════════════════════════════
# 17. subagent.py — _record_step 在无 run_context 时 return
# ══════════════════════════════════════════════════════════════════════


class TestRecordStepNoRuntime:
    def test_record_step_no_run_context_noop(self) -> None:
        """_record_step 在 runtime.run_context 为 None 时直接返回，不抛异常。"""
        from heagent.tools.builtins.subagent import SubTaskOutcome as Sto

        runtime = SubagentToolRuntime(
            provider=None,
            registry=None,
            guard=None,
            skills=None,
            facts=None,
            profile=None,
            compressor=None,
            context_dir=None,
            soul=None,
            engine=None,
            parent_run_id=None,
        )
        runtime.run_context = None
        outcome = Sto(status="ok", role="tester", task="test", iterations=1, output="done")
        _record_step(runtime, outcome=outcome)
