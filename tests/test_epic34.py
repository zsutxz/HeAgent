"""Tests for cost estimation + config-driven roles (Epic 34)."""

from __future__ import annotations

import pytest

from heagent.config import Settings, reset_settings
from heagent.context.tokens import estimate_cost
from heagent.engine.roles import _parse_role_md, get_role, load_agent_roles
from heagent.types import TokenUsage


class TestEstimateCost:
    def test_computes_input_plus_output(self) -> None:
        usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000)
        pricing = {"deepseek-chat": {"input": 0.27, "output": 1.1}}
        cost = estimate_cost(usage, "deepseek-chat", pricing)
        # 1M * 0.27 + 0.5M * 1.1 = 0.27 + 0.55 = 0.82
        assert cost == pytest.approx(0.82)

    def test_unknown_model_returns_none(self) -> None:
        usage = TokenUsage(prompt_tokens=100, completion_tokens=100, total_tokens=200)
        assert estimate_cost(usage, "unknown", {}) is None

    def test_zero_price_returns_zero(self) -> None:
        usage = TokenUsage(prompt_tokens=1_000, completion_tokens=1_000, total_tokens=2_000)
        pricing = {"m": {"input": 0.0, "output": 0.0}}
        assert estimate_cost(usage, "m", pricing) == 0.0


class TestModelPricingMap:
    def test_parses_json(self) -> None:
        s = Settings(model_pricing='{"deepseek-chat": {"input": 0.27, "output": 1.1}}')
        assert s.model_pricing_map["deepseek-chat"]["input"] == 0.27
        assert s.model_pricing_map["deepseek-chat"]["output"] == 1.1

    def test_invalid_json_returns_empty(self) -> None:
        s = Settings(model_pricing="not-json")
        assert s.model_pricing_map == {}

    def test_empty_returns_empty(self) -> None:
        s = Settings(model_pricing="")
        assert s.model_pricing_map == {}


class TestAgentRoles:
    def test_parse_role_md(self, tmp_path) -> None:
        p = tmp_path / "security.md"
        p.write_text(
            "---\nname: security-reviewer\ndescription: 安全审查\ntools: file_read, content_search\n"
            "max_iterations: 15\n---\n你是安全审查角色",
            encoding="utf-8",
        )
        spec = _parse_role_md(p)
        assert spec is not None
        assert spec.name == "security-reviewer"
        assert spec.allowed_tools == ["file_read", "content_search"]
        assert spec.max_iterations == 15
        assert spec.system == "你是安全审查角色"
        assert spec.metadata["description"] == "安全审查"

    def test_parse_role_falls_back_to_filename(self, tmp_path) -> None:
        p = tmp_path / "foo.md"
        p.write_text("正文", encoding="utf-8")
        spec = _parse_role_md(p)
        assert spec is not None
        assert spec.name == "foo"

    def test_parse_role_skips_empty_body(self, tmp_path) -> None:
        p = tmp_path / "empty.md"
        p.write_text("---\nname: empty\n---\n   \n", encoding="utf-8")
        assert _parse_role_md(p) is None

    def test_load_agent_roles_registers(self, tmp_path) -> None:
        (tmp_path / "security.md").write_text("---\nname: security-reviewer\n---\n安全审查", encoding="utf-8")
        loaded = load_agent_roles([str(tmp_path)])
        assert len(loaded) == 1
        assert get_role("security-reviewer").system == "安全审查"

    def test_load_agent_roles_later_dir_overrides(self, tmp_path) -> None:
        d1 = tmp_path / "global"
        d2 = tmp_path / "project"
        d1.mkdir()
        d2.mkdir()
        (d1 / "x.md").write_text("---\nname: x\n---\nglobal", encoding="utf-8")
        (d2 / "x.md").write_text("---\nname: x\n---\nproject", encoding="utf-8")
        load_agent_roles([str(d1), str(d2)])
        assert get_role("x").system == "project"

    def test_load_agent_roles_nonexistent_dir(self, tmp_path) -> None:
        assert load_agent_roles([str(tmp_path / "nope")]) == []


class TestPrintUsageCost:
    def test_print_usage_shows_cost(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_PRICING", '{"deepseek-chat": {"input": 0.27, "output": 1.1}}')
        reset_settings()
        from heagent.cli import _print_usage

        usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)
        _print_usage(usage, model="deepseek-chat")
        err = capsys.readouterr().err
        assert "cost: $" in err
        reset_settings()
