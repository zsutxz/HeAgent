"""Runtime configuration must be stable after construction."""

import pytest
from pydantic import ValidationError

from heagent.config import Settings, get_settings, reset_settings, resolve_runtime_config
from heagent.engine.container import EngineContainer
from heagent.engine.policy import PolicyEngine, ToolExecutionMode
from heagent.types import ToolCall


@pytest.fixture(autouse=True)
def clean_settings():
    reset_settings()
    yield
    reset_settings()


def test_snapshot_detaches_collections_and_credentials():
    settings = Settings(
        _env_file=None,
        openai_api_key="private-key",
        safety_blocked_tools=["shell"],
        routing_pools='{"openai":{"tiers":{"fast":"first"}}}',
    )
    config = resolve_runtime_config(settings)
    settings.safety_blocked_tools = ["file_write"]
    settings.routing_pools = ""
    pool = config.routing_pool_map
    pool["openai"].tiers["fast"] = "changed"
    assert config.safety_blocked_tools == ("shell",)
    assert config.routing_pool_map["openai"].tiers["fast"] == "first"
    with pytest.raises(ValidationError):
        config.max_iterations = 1
    assert "private-key" not in repr(config)
    assert "private-key" not in config.model_dump_json()
    assert resolve_runtime_config(config, plan_mode=True).openai_api_key == "private-key"


def test_explicit_false_wins_and_records_origin():
    config = resolve_runtime_config(
        Settings(_env_file=None, sandbox_session_workspace=True), sandbox_session_workspace=False
    )
    assert config.sandbox_session_workspace is False
    assert config.source_for("sandbox_session_workspace") == "override"


def test_container_pins_settings_and_records_actual_backend(monkeypatch):
    monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "false")
    engine = EngineContainer.default(settings=Settings(_env_file=None, sandbox_backend="passthrough"))
    monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
    reset_settings()
    assert engine._session_workspace_enabled() is False
    first = engine.create_run_context()
    second = engine.create_run_context()
    assert first.run_id != second.run_id
    assert first.metadata is not second.metadata
    assert first.metadata["sandbox_decision"]["filesystem_isolation"] is False


def test_unavailable_explicit_backend_reports_passthrough(monkeypatch):
    monkeypatch.setattr("heagent.tools.sandbox.WinJobBackend.available", False)
    engine = EngineContainer.default(settings=Settings(_env_file=None, sandbox_backend="winjob"))
    assert engine.sandbox_decision.requested_backend == "winjob"
    assert engine.sandbox_decision.effective_backend == "passthrough"
    assert not engine.sandbox_decision.network_isolation


def test_policy_preserves_priority_and_exposes_source():
    verdict = PolicyEngine(blocked_tools=["shell"], approval_tools=["shell"]).evaluate_tool_call(
        ToolCall(id="call", name="shell", arguments={})
    )
    assert verdict.mode == ToolExecutionMode.BLOCKED
    assert verdict.source == "blocked_tools"


# ---------------------------------------------------------------------------
# Phase 1 剩余任务：业务执行期只读快照（loop/sub/提示词/技能工具）+ 入口共用解析
# ---------------------------------------------------------------------------


class _CaptureCompressor:
    """捕获 max_tokens 的假 compressor：返回原列表（不替换），只用于观察快照值。"""

    def __init__(self) -> None:
        self.max_tokens = None

    async def compress(self, messages, *, token_count, max_tokens):
        self.max_tokens = max_tokens
        return messages


async def test_loop_pins_snapshot_for_business_execution():
    """运行中的压缩路径读构造期快照；运行开始后再改全局 Settings 不影响已创建的 loop。"""
    from types import SimpleNamespace

    from heagent.agent.loop import AgentLoop, AgentState

    snapshot = resolve_runtime_config(Settings(_env_file=None, max_context_tokens=123))
    compressor = _CaptureCompressor()
    loop = AgentLoop(object(), compressor=compressor, max_iterations=1, runtime_config=snapshot)
    assert loop._runtime is snapshot

    get_settings().max_context_tokens = 9999  # 模拟运行中全局配置漂移
    state = AgentState(messages=[])
    await loop._maybe_compress(state, None, SimpleNamespace(total_tokens=10_000))
    assert compressor.max_tokens == 123


async def test_subagent_inherits_snapshot_over_late_global_change():
    from heagent.agent.sub import SubAgent

    get_settings().subagent_max_iterations = 3  # 全局低值（构造后才继承，不得生效）
    snapshot = resolve_runtime_config(Settings(_env_file=None, subagent_max_iterations=7))
    agent = SubAgent(object(), runtime_config=snapshot)
    assert agent._runtime is snapshot
    assert agent._max_iterations == 7


def test_build_system_prompt_honors_snapshot(tmp_path):
    from heagent.agent.system_prompt import build_system_prompt

    (tmp_path / "AGENTS.md").write_text("proj context body", encoding="utf-8")
    kwargs: dict = {
        "soul": None,
        "context_dir": str(tmp_path),
        "skills": None,
        "facts": None,
        "profile": None,
    }
    enabled = resolve_runtime_config(Settings(_env_file=None, context_files_enabled=True))
    disabled = resolve_runtime_config(Settings(_env_file=None, context_files_enabled=False))
    assert "<project-context>" in build_system_prompt(None, "p", **kwargs, settings=enabled)
    # 快照关、全局开（默认）→ 仍不注入：运行路径不得回读全局。
    assert build_system_prompt(None, "p", **kwargs, settings=disabled) is None


def test_skill_tools_read_bound_snapshot_values():
    from heagent.tools.builtins.skills import (
        _curator_stale_default,
        _manual_load_budget,
        bind_skill_tools,
    )

    assert _manual_load_budget() == get_settings().skill_max_manual_load_tokens
    with bind_skill_tools(None, manual_load_budget=10, curator_stale_days=5):
        assert _manual_load_budget() == 10
        assert _curator_stale_default() == 5
    # 无 run 绑定（独立脚本/测试）才回退全局。
    assert _manual_load_budget() == get_settings().skill_max_manual_load_tokens


def test_build_loop_shares_engine_resolved_config():
    """CLI/GUI/cron 组装共用同一解析结果：loop 的快照就是 engine 装配用的那份。"""
    from heagent.cli import _build_loop

    loop, scheduler = _build_loop(
        Settings(_env_file=None, cron_enabled=False), object(), max_iterations=5, soul_path=None
    )
    assert scheduler is None
    assert loop._runtime is loop.engine.runtime_config
