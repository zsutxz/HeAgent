"""Tests for Agent core loop and middleware."""

from __future__ import annotations

import asyncio

import pytest

from heagent.agent.loop import AgentLoop, AgentState
from heagent.agent.middleware import Request, compose
from heagent.config import reset_settings
from heagent.exceptions import BudgetExceeded
from heagent.memory.skills import SkillStore
from heagent.providers.base import ProviderMetadata
from heagent.tools.registry import ToolRegistry
from heagent.types import (
    Message,
    ProviderResponse,
    Role,
    TokenUsage,
    ToolCall,
    ToolSchema,
)


class StubProvider:
    """In-memory provider that returns preconfigured responses."""

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return ProviderResponse(
            content="no more responses",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> object:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _usage() -> TokenUsage:
    return TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)


def _final(content: str) -> ProviderResponse:
    return ProviderResponse(content=content, usage=_usage(), model="stub", finish_reason="stop")


def _tc(call_id: str, name: str, args: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args or {})


def _tool_resp(calls: list[ToolCall], content: str = "") -> ProviderResponse:
    return ProviderResponse(content=content, tool_calls=calls, usage=_usage(), model="stub", finish_reason="tool_calls")


@pytest.fixture()
def fresh_registry() -> ToolRegistry:
    """Create a fresh non-singleton registry for each test."""
    return ToolRegistry()


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    reset_settings()
    yield
    reset_settings()


class TestMiddlewareCompose:
    def test_no_middleware(self) -> None:
        chain = compose([], lambda r: "ok")
        assert chain(Request(messages=[])) == "ok"

    def test_single_middleware(self) -> None:
        def mw(req: Request, next_fn: object) -> str:
            return f"before({next_fn(req)})"  # type: ignore[operator]

        chain = compose([mw], lambda r: "inner")
        assert chain(Request(messages=[])) == "before(inner)"

    def test_chain_order(self) -> None:
        order: list[str] = []

        def mw1(req: Request, next_fn: object) -> str:
            order.append("mw1-in")
            result = next_fn(req)  # type: ignore[operator]
            order.append("mw1-out")
            return result

        def mw2(req: Request, next_fn: object) -> str:
            order.append("mw2-in")
            result = next_fn(req)  # type: ignore[operator]
            order.append("mw2-out")
            return result

        compose([mw1, mw2], lambda r: "done")(Request(messages=[]))
        assert order == ["mw1-in", "mw2-in", "mw2-out", "mw1-out"]


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_immediate_answer(self) -> None:
        provider = StubProvider([_final("hello world")])
        loop = AgentLoop(provider, max_iterations=10)
        result = await loop.run("say hello")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_single_tool_call(self, fresh_registry: ToolRegistry) -> None:
        fresh_registry.register(
            ToolSchema(name="echo", description="echo", parameters={"type": "object", "properties": {}}),
            lambda text="default": text,
        )
        provider = StubProvider(
            [
                _tool_resp([_tc("1", "echo", {"text": "ping"})]),
                _final("pong"),
            ]
        )
        result = await AgentLoop(provider, registry=fresh_registry, max_iterations=10).run("test")
        assert result == "pong"

    @pytest.mark.asyncio
    async def test_unknown_tool(self, fresh_registry: ToolRegistry) -> None:
        provider = StubProvider(
            [
                _tool_resp([_tc("1", "nonexistent", {})]),
                _final("handled"),
            ]
        )
        result = await AgentLoop(provider, registry=fresh_registry, max_iterations=10).run("test")
        assert result == "handled"

    @pytest.mark.asyncio
    async def test_budget_exceeded(self, fresh_registry: ToolRegistry) -> None:
        infinite = _tool_resp([_tc("1", "fake", {})])
        provider = StubProvider([infinite] * 100)
        with pytest.raises(BudgetExceeded):
            await AgentLoop(provider, registry=fresh_registry, max_iterations=3).run("loop forever")

    @pytest.mark.asyncio
    async def test_safety_blocks_dangerous_command(self, fresh_registry: ToolRegistry) -> None:
        fresh_registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": "ok",
        )
        provider = StubProvider(
            [
                _tool_resp([_tc("1", "shell", {"command": "rm -rf /"})]),
                _final("blocked"),
            ]
        )
        result = await AgentLoop(provider, registry=fresh_registry, max_iterations=10).run("danger")
        assert result == "blocked"

    @pytest.mark.asyncio
    async def test_system_prompt(self) -> None:
        provider = StubProvider([_final("system ok")])
        loop = AgentLoop(provider, max_iterations=10)
        result = await loop.run("test", system="you are a helper")
        assert result == "system ok"

    @pytest.mark.asyncio
    async def test_async_tool_handler(self, fresh_registry: ToolRegistry) -> None:
        async def async_echo(text: str = "") -> str:
            return f"async:{text}"

        fresh_registry.register(
            ToolSchema(name="aecho", description="async echo", parameters={"type": "object", "properties": {}}),
            async_echo,
        )
        provider = StubProvider(
            [
                _tool_resp([_tc("1", "aecho", {"text": "hi"})]),
                _final("done"),
            ]
        )
        result = await AgentLoop(provider, registry=fresh_registry, max_iterations=10).run("test")
        assert result == "done"


class TestParallelExecution:
    @pytest.mark.asyncio
    async def test_multiple_tools_parallel(self, fresh_registry: ToolRegistry) -> None:
        call_order: list[str] = []

        async def slow_tool(name: str = "") -> str:
            call_order.append(f"{name}-start")
            await asyncio.sleep(0.05)
            call_order.append(f"{name}-end")
            return f"result-{name}"

        fresh_registry.register(
            ToolSchema(name="slow", description="slow", parameters={"type": "object", "properties": {}}),
            slow_tool,
        )
        provider = StubProvider(
            [
                _tool_resp(
                    [
                        _tc("1", "slow", {"name": "a"}),
                        _tc("2", "slow", {"name": "b"}),
                    ]
                ),
                _final("all done"),
            ]
        )
        result = await AgentLoop(provider, registry=fresh_registry, max_iterations=10).run("parallel")
        assert result == "all done"
        assert call_order[0].endswith("-start")
        assert call_order[1].endswith("-start")

    @pytest.mark.asyncio
    async def test_one_failure_does_not_block_others(self, fresh_registry: ToolRegistry) -> None:
        async def good_tool() -> str:
            return "ok"

        async def bad_tool() -> str:
            raise ValueError("boom")

        fresh_registry.register(
            ToolSchema(name="good", description="good", parameters={"type": "object", "properties": {}}),
            good_tool,
        )
        fresh_registry.register(
            ToolSchema(name="bad", description="bad", parameters={"type": "object", "properties": {}}),
            bad_tool,
        )
        provider = StubProvider(
            [
                _tool_resp(
                    [
                        _tc("1", "good", {}),
                        _tc("2", "bad", {}),
                    ]
                ),
                _final("recovered"),
            ]
        )
        result = await AgentLoop(provider, registry=fresh_registry, max_iterations=10).run("mixed")
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_safety_violation_parallel(self, fresh_registry: ToolRegistry) -> None:
        fresh_registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": "ok",
        )
        fresh_registry.register(
            ToolSchema(name="safe", description="safe", parameters={"type": "object", "properties": {}}),
            lambda: "safe-result",
        )
        provider = StubProvider(
            [
                _tool_resp(
                    [
                        _tc("1", "shell", {"command": "rm -rf /"}),
                        _tc("2", "safe", {}),
                    ]
                ),
                _final("done"),
            ]
        )
        result = await AgentLoop(provider, registry=fresh_registry, max_iterations=10).run("mixed safety")
        assert result == "done"


class TestAgentState:
    def test_defaults(self) -> None:
        s = AgentState()
        assert s.iteration == 0
        assert s.max_iterations == 50
        assert s.messages == []
        assert s.results == []


class TestSkillInjection:
    """技能内容注入系统提示词的测试。"""

    @pytest.mark.asyncio
    async def test_no_skills_no_system(self) -> None:
        """无 skills 无 system → 无 SYSTEM 消息（向后兼容）。"""
        provider = StubProvider([_final("ok")])
        loop = AgentLoop(provider, max_iterations=10)
        result = await loop.run("test")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_skills_injected_into_system(self, tmp_path) -> None:
        """匹配的技能内容出现在 <skills> 标签中。"""
        captured: list[Message] = []

        class CaptureProvider:
            async def send(self, messages, *, tools=None):
                captured.extend(messages)
                return _final("done")

            async def stream(self, messages, *, tools=None):
                yield await self.send(messages, tools=tools)

            def get_metadata(self):
                return ProviderMetadata(name="capture", model="capture")

        skills = SkillStore(base_dir=str(tmp_path / "skills"))
        skills.save("test_skill", "A test skill", "testing pattern", ["step1", "step2"])

        loop = AgentLoop(CaptureProvider(), max_iterations=10, skills=skills)
        await loop.run("testing")  # prompt 包含 pattern 关键词 "testing"

        system_msgs = [m for m in captured if m.role == Role.SYSTEM]
        assert len(system_msgs) == 1
        assert "<skills>" in system_msgs[0].content
        assert "</skills>" in system_msgs[0].content
        assert "test_skill" in system_msgs[0].content

    @pytest.mark.asyncio
    async def test_skills_and_system_combined(self, tmp_path) -> None:
        """用户 system + 匹配的 skills 共存在同一条 SYSTEM 消息中。"""
        captured: list[Message] = []

        class CaptureProvider:
            async def send(self, messages, *, tools=None):
                captured.extend(messages)
                return _final("done")

            async def stream(self, messages, *, tools=None):
                yield await self.send(messages, tools=tools)

            def get_metadata(self):
                return ProviderMetadata(name="capture", model="capture")

        skills = SkillStore(base_dir=str(tmp_path / "skills"))
        skills.save("skill_a", "desc", "pattern matching test", ["step"])

        loop = AgentLoop(CaptureProvider(), max_iterations=10, skills=skills)
        await loop.run("pattern test", system="You are helpful.")

        system_msgs = [m for m in captured if m.role == Role.SYSTEM]
        assert len(system_msgs) == 1
        assert system_msgs[0].content.startswith("You are helpful.")
        assert "<skills>" in system_msgs[0].content

    @pytest.mark.asyncio
    async def test_empty_skills_no_injection(self, tmp_path) -> None:
        """空 SkillStore → 不注入 <skills> 标签。"""
        captured: list[Message] = []

        class CaptureProvider:
            async def send(self, messages, *, tools=None):
                captured.extend(messages)
                return _final("done")

            async def stream(self, messages, *, tools=None):
                yield await self.send(messages, tools=tools)

            def get_metadata(self):
                return ProviderMetadata(name="capture", model="capture")

        skills = SkillStore(base_dir=str(tmp_path / "skills"))  # 空，无技能文件

        loop = AgentLoop(CaptureProvider(), max_iterations=10, skills=skills)
        await loop.run("test", system="base prompt")

        system_msgs = [m for m in captured if m.role == Role.SYSTEM]
        assert len(system_msgs) == 1
        assert "<skills>" not in system_msgs[0].content
        assert system_msgs[0].content == "base prompt"

    @pytest.mark.asyncio
    async def test_skills_only_no_user_system(self, tmp_path) -> None:
        """只有 skills 没有 user system → skills 成为系统消息。"""
        captured: list[Message] = []

        class CaptureProvider:
            async def send(self, messages, *, tools=None):
                captured.extend(messages)
                return _final("done")

            async def stream(self, messages, *, tools=None):
                yield await self.send(messages, tools=tools)

            def get_metadata(self):
                return ProviderMetadata(name="capture", model="capture")

        skills = SkillStore(base_dir=str(tmp_path / "skills"))
        skills.save("only_skill", "desc", "only pat", ["s1"])

        loop = AgentLoop(CaptureProvider(), max_iterations=10, skills=skills)
        await loop.run("only")  # prompt 匹配 pattern 关键词

        system_msgs = [m for m in captured if m.role == Role.SYSTEM]
        assert len(system_msgs) == 1
        assert "<skills>" in system_msgs[0].content

    @pytest.mark.asyncio
    async def test_auto_invoke_no_match(self, tmp_path) -> None:
        """有技能但 prompt 不匹配 → 注入"无匹配"提示。"""
        captured: list[Message] = []

        class CaptureProvider:
            async def send(self, messages, *, tools=None):
                captured.extend(messages)
                return _final("done")

            async def stream(self, messages, *, tools=None):
                yield await self.send(messages, tools=tools)

            def get_metadata(self):
                return ProviderMetadata(name="capture", model="capture")

        skills = SkillStore(base_dir=str(tmp_path / "skills"))
        skills.save("deploy_skill", "Deploy app", "deploy production release", ["push", "deploy"])

        loop = AgentLoop(CaptureProvider(), max_iterations=10, skills=skills)
        await loop.run("what is the weather today")

        system_msgs = [m for m in captured if m.role == Role.SYSTEM]
        assert len(system_msgs) == 1
        assert "No skills matched" in system_msgs[0].content
        assert "deploy_skill" not in system_msgs[0].content

    @pytest.mark.asyncio
    async def test_auto_invoke_max_limit(self, tmp_path) -> None:
        """多个匹配技能只注入 skill_max_auto_invoke 个。"""
        captured: list[Message] = []

        class CaptureProvider:
            async def send(self, messages, *, tools=None):
                captured.extend(messages)
                return _final("done")

            async def stream(self, messages, *, tools=None):
                yield await self.send(messages, tools=tools)

            def get_metadata(self):
                return ProviderMetadata(name="capture", model="capture")

        skills = SkillStore(base_dir=str(tmp_path / "skills"))
        # 5 个技能共享关键词 "deploy"
        for i in range(5):
            skills.save(f"skill_{i}", f"Skill {i}", "deploy step", [f"step_{i}"])

        loop = AgentLoop(CaptureProvider(), max_iterations=10, skills=skills)
        await loop.run("deploy")

        system_msgs = [m for m in captured if m.role == Role.SYSTEM]
        assert len(system_msgs) == 1
        content = system_msgs[0].content
        # 默认 skill_max_auto_invoke=3，不应出现全部 5 个
        for i in range(3):
            assert f"skill_{i}" in content
        assert "skill_3" not in content
        assert "skill_4" not in content
