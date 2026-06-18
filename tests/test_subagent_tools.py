"""Tests for sub-agent builtin tools — task_delegate / task_parallel。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

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


@pytest.fixture(autouse=True)
def _cleanup():
    """每个测试前后清理 ToolRegistry 和 subagent 模块状态。"""
    registry = ToolRegistry.get()
    registry._tools.clear()
    registry._handlers.clear()
    registry._disabled.clear()
    reset_subagent_tools()
    yield
    registry = ToolRegistry.get()
    registry._tools.clear()
    registry._handlers.clear()
    registry._disabled.clear()
    reset_subagent_tools()


class TestTaskDelegate:
    async def test_unconfigured_returns_error(self) -> None:
        result = await task_delegate("do something")
        assert "not configured" in result

    async def test_delegates_to_sub_agent(self) -> None:
        provider = _StubProvider("computed result")
        configure_subagent_tools(provider)
        result = await task_delegate("compute 2+2")
        assert "computed result" in result
        assert "Sub-agent completed" in result

    async def test_sub_agent_failure(self) -> None:
        """子 Agent 内部异常时返回失败信息。"""

        class _FailProvider:
            async def send(self, messages, *, tools=None):
                raise RuntimeError("API error")

            async def stream(self, messages, *, tools=None):
                yield ProviderResponse(content="", usage=TokenUsage(), model="fail", finish_reason="stop")

            def get_metadata(self):
                return ProviderMetadata(name="fail", model="fail")

        configure_subagent_tools(_FailProvider())
        result = await task_delegate("will fail")
        assert "Sub-agent failed" in result


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

    async def test_parallel_execution(self) -> None:
        provider = _StubProvider("done")
        configure_subagent_tools(provider)
        result = await task_parallel(json.dumps(["task 1", "task 2"]))
        assert "OK" in result
        assert "done" in result
        assert "[1]" in result
        assert "[2]" in result

    async def test_threads_context_components_into_subagent(self) -> None:
        """configure_subagent_tools 接收的 6 个上下文参数应转发到构造的 SubAgent。"""
        import heagent.tools.builtins.subagent as _sa_mod

        # 用最简单的真实对象作为 marker —— SubAgent 会原样存储
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

        # 捕获 SubAgent 构造时传入的 kwargs
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


class TestToolRegistration:
    def test_task_delegate_registered(self) -> None:
        """task_delegate 应通过 @tool 注册到 ToolRegistry。"""
        # @tool 在 import 时注册，但 autouse fixture 清理了 registry。
        # 重新导入触发注册验证。
        import importlib

        import heagent.tools.builtins.subagent as _sa
        importlib.reload(_sa)
        registry = ToolRegistry.get()
        schema = registry.get_schema("task_delegate")
        assert schema is not None
        assert "task_delegate" in schema.name

    def test_task_parallel_registered(self) -> None:
        """task_parallel 应通过 @tool 注册到 ToolRegistry。"""
        import importlib

        import heagent.tools.builtins.subagent as _sa
        importlib.reload(_sa)
        registry = ToolRegistry.get()
        schema = registry.get_schema("task_parallel")
        assert schema is not None
        assert "task_parallel" in schema.name
