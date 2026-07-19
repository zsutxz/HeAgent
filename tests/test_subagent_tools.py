"""Tests for sub-agent builtin tools — task_delegate / task_parallel。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from heagent.providers.base import ProviderMetadata
from heagent.tools.builtins.subagent import (
    configure_subagent_tools,
    reset_subagent_tools,
    task_delegate,
    task_parallel,
)
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, TokenUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _StubProvider:
    """返回固定回答的模拟 Provider，用于子 Agent 测试。"""

    def __init__(self, response: str = "stub answer") -> None:
        self._response = response

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:
        return ProviderResponse(
            content=self._response,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools=None) -> AsyncIterator[ProviderResponse]:
        yield ProviderResponse(
            content=self._response,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture()
def _reset_subagent():
    """Teardown only: 测试后复位 subagent 模块状态，防止 provider 泄漏到后续测试。"""
    yield
    reset_subagent_tools()


@pytest.mark.usefixtures("_reset_subagent")
class TestTaskDelegate:
    async def test_unconfigured_returns_error(self) -> None:
        result = await task_delegate("do something")
        assert "not configured" in result

    async def test_delegates_to_sub_agent(self) -> None:
        provider = _StubProvider("computed result")
        configure_subagent_tools(provider)
        result = await task_delegate("compute 2+2")
        payload = json.loads(result)
        assert payload["status"] == "ok"
        assert payload["output"] == "computed result"
        assert payload["iterations"] >= 1
        assert payload["run_id"]

    async def test_sub_agent_failure(self) -> None:
        """子 Agent 内部异常时返回结构化失败结果。"""

        class _FailProvider:
            async def send(self, messages, *, tools=None):
                raise RuntimeError("API error")

            async def stream(self, messages, *, tools=None):
                yield ProviderResponse(content="", usage=TokenUsage(), model="fail", finish_reason="stop")

            def get_metadata(self):
                return ProviderMetadata(name="fail", model="fail")

        configure_subagent_tools(_FailProvider())
        payload = json.loads(await task_delegate("will fail"))
        assert payload["status"] == "failed"
        assert "API error" in payload["output"]


@pytest.mark.usefixtures("_reset_subagent")
class TestTaskParallel:
    async def test_unconfigured_returns_error(self) -> None:
        result = await task_parallel('["task1"]')
        assert "not configured" in result

    async def test_invalid_json(self) -> None:
        configure_subagent_tools(_StubProvider())
        result = await task_parallel("not json")
        assert "valid JSON array" in result

    async def test_empty_array(self) -> None:
        configure_subagent_tools(_StubProvider())
        result = await task_parallel("[]")
        assert "non-empty" in result

    async def test_not_array(self) -> None:
        configure_subagent_tools(_StubProvider())
        result = await task_parallel('"hello"')
        assert "non-empty" in result

    async def test_not_all_strings(self) -> None:
        """元素含非字符串时应拒绝，避免把 int 等传入 SubAgent。"""
        configure_subagent_tools(_StubProvider())
        result = await task_parallel(json.dumps(["ok", 123]))
        assert "array of strings" in result

    async def test_parallel_execution(self) -> None:
        provider = _StubProvider("done")
        configure_subagent_tools(provider)
        result = await task_parallel(json.dumps(["task 1", "task 2"]))
        payload = json.loads(result)
        assert payload["status"] == "ok"
        outcomes = payload["outcomes"]
        assert len(outcomes) == 2
        assert all(o["status"] == "ok" and o["output"] == "done" for o in outcomes)

    async def test_threads_context_components_into_subagent(self) -> None:
        """configure_subagent_tools 接收的 6 个上下文参数应转发到构造的 SubAgent。"""
        import heagent.tools.builtins.subagent as _sa_mod
        from heagent.memory.facts import FactStore
        from heagent.memory.soul import SoulStore

        soul = SoulStore(
            global_path="/nonexistent/global.md",
            project_path="/nonexistent/project.md",
        )
        facts = FactStore(path="/nonexistent/facts.md")

        provider = _StubProvider("ok")
        configure_subagent_tools(
            provider,
            soul=soul,
            facts=facts,
        )

        captured: dict[str, object] = {}
        original_subagent_init = _sa_mod.SubAgent.__init__

        def spy_init(self_sa, provider_arg, **kwargs):
            for key in ("soul", "facts", "skills", "profile", "compressor", "context_dir"):
                captured[key] = kwargs.get(key)
            return original_subagent_init(self_sa, provider_arg, **kwargs)

        _sa_mod.SubAgent.__init__ = spy_init
        try:
            await task_delegate("any task")
        finally:
            _sa_mod.SubAgent.__init__ = original_subagent_init

        assert captured["soul"] is soul
        assert captured["facts"] is facts
        assert captured["skills"] is None
        assert captured["profile"] is None
        assert captured["compressor"] is None
        assert captured["context_dir"] is None


@pytest.mark.usefixtures("_reset_subagent")
class TestStructuredResults:
    """P5-3：委派工具一律返回带 ``status`` 字段的 JSON。"""

    async def test_preflight_errors_are_structured(self) -> None:
        """未配置 / 非法 JSON 等预检错误也返回 status=error 的 JSON。"""
        unconfigured = json.loads(await task_delegate("x"))
        assert unconfigured["status"] == "error"
        assert "not configured" in unconfigured["message"]

        configure_subagent_tools(_StubProvider())
        bad = json.loads(await task_parallel("not json"))
        assert bad["status"] == "error"
        assert "valid JSON array" in bad["message"]

    async def test_delegate_carries_role(self) -> None:
        configure_subagent_tools(_StubProvider("ok"))
        payload = json.loads(await task_delegate("plan it", role="planner"))
        assert payload["status"] == "ok"
        assert payload["role"] == "planner"

    async def test_parallel_partial_when_one_fails(self) -> None:
        """部分失败时 status=partial，且 outcomes 逐条标 failed。"""

        class _FlakyProvider:
            _n = 0

            async def send(self, messages, *, tools=None):
                _FlakyProvider._n += 1
                if _FlakyProvider._n == 1:
                    raise RuntimeError("boom")
                return ProviderResponse(
                    content="ok",
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                    model="stub",
                    finish_reason="stop",
                )

            async def stream(self, messages, *, tools=None):
                yield ProviderResponse(content="ok", usage=TokenUsage(), model="stub", finish_reason="stop")

            def get_metadata(self):
                return ProviderMetadata(name="stub", model="stub")

        configure_subagent_tools(_FlakyProvider())
        payload = json.loads(await task_parallel(json.dumps(["a", "b"])))
        assert payload["status"] == "partial"
        statuses = {o["status"] for o in payload["outcomes"]}
        assert statuses == {"ok", "failed"}


class TestToolRegistration:
    def test_task_delegate_registered(self) -> None:
        """task_delegate 已注册且 schema 形态绑定本工具（task/role/system 参数）。"""

        registry = ToolRegistry.get()
        schema = registry.get_schema("task_delegate")
        assert schema is not None
        assert schema.name == "task_delegate"
        props = schema.parameters["properties"]
        assert "task" in props
        assert {"role", "system"} <= set(props)

    def test_task_parallel_registered(self) -> None:
        """task_parallel 已注册且 schema 形态绑定本工具（tasks_json 参数）。"""
        registry = ToolRegistry.get()
        schema = registry.get_schema("task_parallel")
        assert schema is not None
        assert schema.name == "task_parallel"
        props = schema.parameters["properties"]
        assert "tasks_json" in props
