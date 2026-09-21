"""Runtime configuration must be stable after construction."""

import pytest
from pydantic import ValidationError

from heagent.config import Settings, reset_settings, resolve_runtime_config
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
    monkeypatch.setattr("heagent.tools.sandbox.WinJobBackend.available", lambda: False)
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
