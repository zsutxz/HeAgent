"""Tests for Agent core loop and middleware."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

import pytest

from heagent.agent.loop import AgentLoop, AgentState
from heagent.agent.middleware import Request, compose
from heagent.config import reset_settings
from heagent.context.session import SessionStore
from heagent.exceptions import BudgetExceeded
from heagent.memory.facts import FactStore
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
        self.calls: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls.append([message.model_copy(deep=True) for message in messages])
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
    async def test_session_restore_keeps_system_first(self, tmp_path) -> None:
        """回归：恢复会话历史后 SYSTEM 提示词必须仍是消息列表第一条。

        严格模板（如 Ollama）要求 SYSTEM 只能出现在开头，
        历史上曾把恢复的消息拼到 SYSTEM 之前，导致报错
        「System message must be at the beginning」。
        """
        store = SessionStore(base_dir=str(tmp_path))
        store.save(
            "sess1",
            [
                Message(role=Role.SYSTEM, content="old system"),
                Message(role=Role.USER, content="q1"),
                Message(role=Role.ASSISTANT, content="a1"),
            ],
        )
        provider = StubProvider([_final("done")])
        loop = AgentLoop(provider, session=store, max_iterations=10)
        result = await loop.run("q2", system="new system", session_id="sess1")
        assert result == "done"
        sent = provider.calls[0]
        roles = [m.role for m in sent]
        # 第一条必须是 SYSTEM，且其后不得再出现 SYSTEM（旧 SYSTEM 已剔除）。
        assert roles[0] == Role.SYSTEM
        assert Role.SYSTEM not in roles[1:]
        assert sent[0].content == "new system"
        # 恢复的历史消息与新的 USER 提示词都在，新 USER 在最末。
        contents = [m.content for m in sent]
        assert "q1" in contents
        assert "a1" in contents
        assert contents[-1] == "q2"

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
    async def test_tool_followup_preserves_reasoning_content(self, fresh_registry: ToolRegistry) -> None:
        fresh_registry.register(
            ToolSchema(name="echo", description="echo", parameters={"type": "object", "properties": {}}),
            lambda text="default": text,
        )
        tool_response = _tool_resp([_tc("1", "echo", {"text": "ping"})])
        tool_response.reasoning_content = "I should call echo."
        provider = StubProvider([tool_response, _final("pong")])

        result = await AgentLoop(provider, registry=fresh_registry, max_iterations=10).run("test")

        assert result == "pong"
        assistant = next(message for message in provider.calls[1] if message.role == Role.ASSISTANT)
        assert assistant.reasoning_content == "I should call echo."

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
    async def test_run_survives_undecodable_memory_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """MEMORY.md 非 UTF-8 ⇒ 记忆注入跳过（fail-soft），但 run 必须照常完成（Z-D12）。"""
        path = tmp_path / "MEMORY.md"
        raw = "- 中文记忆条目\n".encode("gbk")
        path.write_bytes(raw)

        with caplog.at_level(logging.WARNING, logger="heagent.memory.facts"):
            result = await AgentLoop(
                StubProvider([_final("ok")]),
                facts=FactStore(path=str(path)),
                max_iterations=3,
            ).run("hi")

        assert result == "ok"
        assert "not valid UTF-8" in caplog.text
        assert path.read_bytes() == raw, "fail-soft 不得改写文件本体"

    @pytest.mark.asyncio
    async def test_last_model_records_the_serving_model(self) -> None:
        """``last_model`` 是「本次运行实际用了哪个模型」的唯一记录点（run 与 run_stream 都经漏斗）。"""
        provider = StubProvider([_final("ok")])
        loop = AgentLoop(provider, max_iterations=3)

        assert loop.last_model is None
        await loop.run("hi")
        assert loop.last_model == "stub"

        streaming = AgentLoop(StubProvider([_final("ok")]), max_iterations=3)
        async for _event in streaming.run_stream("hi"):
            pass
        assert streaming.last_model == "stub"

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

    @pytest.mark.asyncio
    async def test_pause_resume_before_first_iteration(self) -> None:
        """pause() 后循环在首轮边界挂起（不发 LLM 调用），unpause() 后继续完成。"""
        provider = StubProvider([_final("hello")])
        loop = AgentLoop(provider, max_iterations=10)

        loop.pause()
        assert loop.is_paused is True

        run_task = asyncio.create_task(loop.run("hi"))
        await asyncio.sleep(0.1)
        assert not run_task.done()  # 已挂起，尚未完成
        assert provider.calls == []  # 未发起任何 LLM 调用

        loop.unpause()
        assert loop.is_paused is False
        result = await asyncio.wait_for(run_task, timeout=2)
        assert result == "hello"
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_run_stream_pause_resume(self) -> None:
        """流式入口同样在边界挂起，unpause 后产出事件。"""
        provider = StubProvider([_final("stream hello")])
        loop = AgentLoop(provider, max_iterations=10)

        loop.pause()
        events: list[object] = []

        async def consume() -> None:
            async for ev in loop.run_stream("hi"):
                events.append(ev)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.1)
        assert not task.done()
        assert events == []  # 挂起期间无任何事件产出

        loop.unpause()
        await asyncio.wait_for(task, timeout=2)
        assert any(getattr(e, "type", None) == "done" for e in events)

    @pytest.mark.asyncio
    async def test_run_stream_estimates_completion_when_usage_absent(self) -> None:
        """流式 Provider 不返回 usage 时，completion 用本地估算而非 0。"""
        resp = ProviderResponse(
            content="stream hello world",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="stub",
            finish_reason="stop",
        )
        loop = AgentLoop(StubProvider([resp]), max_iterations=10)
        async for _ in loop.run_stream("hi"):
            pass
        assert loop.last_usage is not None
        assert loop.last_usage.completion_tokens > 0
        assert loop.last_usage.total_tokens >= loop.last_usage.prompt_tokens

    @pytest.mark.asyncio
    async def test_pause_state_reset_after_cancelled_run(self) -> None:
        """暂停后被取消的 run 不残留暂停态：下一次 run 应立即运行（P1 回归）。"""
        provider = StubProvider([_final("first")])
        loop = AgentLoop(provider, max_iterations=10)

        # 第一次 run：暂停 → 挂起 → 取消（模拟 CLI「暂停 + 双击 Esc 打断」）
        loop.pause()
        run_task = asyncio.create_task(loop.run("hi"))
        await asyncio.sleep(0.1)
        assert not run_task.done()  # 已挂起
        assert provider.calls == []  # 挂起期间未发起任何 LLM 调用
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task

        # 复位后：下一次 run 应立即运行，不再挂起
        assert loop.is_paused is False
        result = await asyncio.wait_for(loop.run("hi again"), timeout=2)
        assert result == "first"  # 第一次 run 未消费响应，第二次拿到第一个
        assert len(provider.calls) == 1  # 第二次 run 正常调用一次

    def test_pause_resume_idempotent(self) -> None:
        """pause()/unpause() 幂等，is_paused 反映请求态。"""
        loop = AgentLoop(StubProvider([_final("ok")]), max_iterations=10)
        assert loop.is_paused is False
        loop.pause()
        loop.pause()
        assert loop.is_paused is True
        loop.unpause()
        loop.unpause()
        assert loop.is_paused is False

    @pytest.mark.asyncio
    async def test_failed_run_still_persists_the_history(self, tmp_path: Path) -> None:
        """失败运行也要把已发生的对话写进会话文件（50-3 AC10 的**真实链路**证据）。

        评审发现·镜头三①：原先唯一相关的用例用替身 handler「先 ``save`` 再 ``raise``」，被验证的
        前提被写死在替身里（循环论证）⇒ 把 ``persist_and_cache`` 从 ``finally`` 挪进成功分支也
        不会有任何测试变红。本用例走真实 ``AgentLoop`` + 真实 ``SessionStore``。
        """
        store = SessionStore(base_dir=str(tmp_path / "sessions"))
        loop = AgentLoop(_ExplodingProvider(), session=store, max_iterations=3)

        with pytest.raises(RuntimeError, match="provider exploded"):
            await loop.run("hello", session_id="s1")

        assert [message.content for message in store.load("s1") if message.role is Role.USER] == ["hello"]


class _ExplodingProvider:
    """始终失败的 provider（模拟网络/鉴权失败，钉住失败路径的落盘契约）。"""

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> object:  # noqa: ARG002
        raise RuntimeError("provider exploded")

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None):  # noqa: ANN201, ARG002
        raise RuntimeError("provider exploded")
        yield  # pragma: no cover - 使本方法成为 async generator（异常在首个 __anext__ 抛出）

    def get_metadata(self) -> object:  # pragma: no cover - 失败路径不会读元数据
        return None


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
    async def test_auto_invoke_token_budget_skips_long_skill_and_does_not_count_it(self, tmp_path, monkeypatch) -> None:
        captured: list[Message] = []

        class CaptureProvider:
            async def send(self, messages, *, tools=None):
                captured.extend(messages)
                return _final("done")

            async def stream(self, messages, *, tools=None):
                yield await self.send(messages, tools=tools)

            def get_metadata(self):
                return ProviderMetadata(name="capture", model="capture")

        monkeypatch.setenv("SKILL_MAX_AUTO_INVOKE_TOKENS", "80")
        reset_settings()
        skills = SkillStore(base_dir=str(tmp_path / "skills"))
        skills.save("long", "Long", "deploy", ["x" * 400])
        skills.save("short", "Short", "deploy", ["ok"])
        loop = AgentLoop(CaptureProvider(), max_iterations=10, skills=skills)
        await loop.run("deploy")

        system = next(message.content for message in captured if message.role == Role.SYSTEM)
        assert "# short" in system
        assert "# long" not in system
        assert skills.parse("long").usage_count == 0  # type: ignore[union-attr]
        assert skills.parse("short").usage_count == 1  # type: ignore[union-attr]
        reset_settings()

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


class TestToolActivity:
    """run 作用域的工具展示态：在途摘要（状态栏）+ 活动台账（跑完回显）。"""

    @pytest.mark.asyncio
    async def test_active_tool_visible_in_flight_and_cleared_after(self, fresh_registry: ToolRegistry) -> None:
        seen: list[str] = []
        holder: list[AgentLoop] = []

        async def probe_tool(path: str = "") -> str:
            seen.append(holder[0].active_tool)
            return "ok"

        _register(fresh_registry, "probe", probe_tool)
        provider = StubProvider([_tool_resp([_tc("1", "probe", {"path": "docs/frame.md"})]), _final("done")])
        loop = AgentLoop(provider, registry=fresh_registry, max_iterations=10)
        holder.append(loop)

        result = await loop.run("probe it")

        assert result == "done"
        # 工具执行期间状态栏读得到；批次一结束即清空。
        assert seen == ["probe → docs/frame.md"]
        assert loop.active_tool == ""
        assert loop.tool_activity == ["probe → docs/frame.md"]

    @pytest.mark.asyncio
    async def test_batch_summary_counts_the_extra_calls(self, fresh_registry: ToolRegistry) -> None:
        """一批多调用只占一个状态段：首个工具 + (+N)，但台账逐条留痕。"""
        seen: list[str] = []
        holder: list[AgentLoop] = []

        async def probe_tool(path: str = "") -> str:
            if not seen:
                seen.append(holder[0].active_tool)
            return "ok"

        _register(fresh_registry, "probe", probe_tool)
        provider = StubProvider(
            [
                _tool_resp([_tc("1", "probe", {"path": "a.md"}), _tc("2", "probe", {"path": "b.md"})]),
                _final("done"),
            ]
        )
        loop = AgentLoop(provider, registry=fresh_registry, max_iterations=10)
        holder.append(loop)

        await loop.run("probe twice")

        assert seen == ["probe → a.md (+1)"]
        assert loop.tool_activity == ["probe → a.md", "probe → b.md"]

    @pytest.mark.asyncio
    async def test_activity_ledger_resets_between_runs(self, fresh_registry: ToolRegistry) -> None:
        """交互模式复用同一 loop：活动台账按 run 重置，不跨轮累积。"""

        async def probe_tool(path: str = "") -> str:
            return "ok"

        _register(fresh_registry, "probe", probe_tool)
        provider = StubProvider(
            [
                _tool_resp([_tc("1", "probe", {"path": "a.md"})]),
                _final("first"),
                _tool_resp([_tc("2", "probe", {"path": "b.md"})]),
                _final("second"),
            ]
        )
        loop = AgentLoop(provider, registry=fresh_registry, max_iterations=10)

        await loop.run("one")
        assert loop.tool_activity == ["probe → a.md"]

        await loop.run("two")
        assert loop.tool_activity == ["probe → b.md"]

    @pytest.mark.asyncio
    async def test_resume_path_also_resets_display_state(self, fresh_registry: ToolRegistry) -> None:
        """恢复也是新的一次 run：在途工具与活动台账都要清空。

        回归：重置原先只在 ``_init_new_run`` 里，而 ``_init_or_resume`` 在恢复分支
        提前 return，resume 后状态栏 / 台账会残留上一段 run 的值。
        """
        from heagent.agent.loop import _ResumeState

        loop = AgentLoop(StubProvider([_final("done")]), registry=fresh_registry, max_iterations=10)
        loop.active_tool = "file_read → stale.md"
        loop.tool_activity = ["file_read → stale.md"]

        init = await loop._init_or_resume(
            "resume me",
            None,
            None,
            _ResumeState(
                state=AgentState(),
                run_context=loop._ensure_run_context(session_id=None),
                prompt="resume me",
                system=None,
            ),
            stream=False,
        )

        assert init.prompt == "resume me"
        assert loop.active_tool == ""
        assert loop.tool_activity == []

    @pytest.mark.asyncio
    async def test_active_tool_cleared_when_run_is_cancelled(self, fresh_registry: ToolRegistry) -> None:
        """取消（双击 Esc / 中断）也必须清空在途工具，否则状态栏留着陈旧值。"""
        started = asyncio.Event()

        async def hang_tool() -> str:
            started.set()
            await asyncio.sleep(30)
            return "never"

        _register(fresh_registry, "hang", hang_tool)
        provider = StubProvider([_tool_resp([_tc("1", "hang")]), _final("unreachable")])
        loop = AgentLoop(provider, registry=fresh_registry, max_iterations=5)

        task = asyncio.create_task(loop.run("hang"))
        await asyncio.wait_for(started.wait(), timeout=5)
        assert loop.active_tool == "hang"

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert loop.active_tool == ""


def _register(registry: ToolRegistry, name: str, handler: object) -> None:
    """注册一个只有一个字符串参数的工具（活动标签走 call_summary 的兜底取名）。"""
    registry.register(
        ToolSchema(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
        handler,
    )


class TestSandboxWorkspaceVisibility:
    """E40-D2: 本 run 的 sandbox 会话目录对模型可见（system prompt 唯一通道）且与 shell 同源。"""

    def test_prompt_block_present_when_workspace_effective(self, tmp_path) -> None:
        """生效时注入 ``<shell-workspace>`` 块并含该绝对路径。"""
        from heagent.agent.system_prompt import build_system_prompt

        session = tmp_path / "sess"
        system = build_system_prompt(
            None,
            "",
            soul=None,
            context_dir=None,
            skills=None,
            facts=None,
            profile=None,
            sandbox_workspace=str(session),
        )

        assert system is not None
        assert "<shell-workspace>" in system
        assert str(session) in system

    def test_prompt_block_absent_without_workspace(self) -> None:
        """未生效（None/空串）时不注入——宁可不提示，也不报一个与真实 cwd 不符的路径。"""
        from heagent.agent.system_prompt import build_system_prompt

        for value in (None, ""):
            system = build_system_prompt(
                None,
                "",
                soul=None,
                context_dir=None,
                skills=None,
                facts=None,
                profile=None,
                sandbox_workspace=value,
            )
            assert system is None or "<shell-workspace>" not in system

    @pytest.mark.asyncio
    async def test_prompt_reports_the_same_dir_shell_receives(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """端到端：SYSTEM 里报的路径 == executor 实际 bind 给 shell 的 cwd（同一来源，不分叉）。"""
        from heagent.agent.loop import AgentLoop
        from heagent.engine import EngineContainer
        from heagent.tools.builtins.shell import shell
        from heagent.tools.sandbox import get_sandbox_workspace

        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        monkeypatch.chdir(tmp_path)

        seen: list[Path | None] = []

        class _RecordingRunner:
            async def run(self, command: str, *, timeout: int) -> str:
                seen.append(get_sandbox_workspace())
                return "recorded"

        engine = EngineContainer(workspace_root=str(tmp_path), command_runner=_RecordingRunner())
        # 模拟 EngineContainer.default() 在真实后端在位时的自动授权（shell 走沙箱路径）
        engine.policy.sandbox_tools.add("shell")

        registry = ToolRegistry()
        registry.register(
            ToolSchema(
                name="shell",
                description="run shell",
                parameters={"type": "object", "properties": {"command": {"type": "string"}}},
            ),
            shell,
        )
        provider = StubProvider([_tool_resp([_tc("1", "shell", {"command": "pwd"})]), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, max_iterations=5)

        assert await loop.run("where am i") == "done"

        assert seen and seen[0] is not None, "shell 未收到沙箱会话目录（授权/bind 链断了）"
        system = next(m.content for m in provider.calls[0] if m.role == Role.SYSTEM)
        assert str(seen[0]) in system, "模型看到的路径与 shell 实际 cwd 不一致"
        assert "<shell-workspace>" in system

    @pytest.mark.asyncio
    async def test_no_prompt_block_when_backend_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """开关开但**无真实后端**（passthrough）：目录不生效 → 不向模型报路径。"""
        from heagent.agent.loop import AgentLoop
        from heagent.engine import EngineContainer

        monkeypatch.setenv("SANDBOX_SESSION_WORKSPACE", "true")
        monkeypatch.chdir(tmp_path)

        engine = EngineContainer(workspace_root=str(tmp_path))  # command_runner=None
        provider = StubProvider([_final("done")])
        loop = AgentLoop(provider, engine=engine, max_iterations=5)
        await loop.run("hi")

        # 无 soul/context/skills/facts/profile 时 system_content 为 None（无 SYSTEM 消息），
        # 故断言「任何 SYSTEM 消息都不含该块」，而非假定一定有一条。
        systems = [m.content for m in provider.calls[0] if m.role == Role.SYSTEM]
        assert all("<shell-workspace>" not in (content or "") for content in systems)
