"""Tests for sub-agent and parallel orchestration."""

from __future__ import annotations

import asyncio

import pytest

from heagent.agent.sub import SubAgent, run_parallel
from heagent.memory.facts import FactStore
from heagent.memory.skills import SkillStore
from heagent.memory.soul import SoulStore
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage


class StubProvider:
    def __init__(self, answer: str = "done") -> None:
        self._answer = answer

    async def send(self, messages: list[Message], **kw: object) -> ProviderResponse:
        return ProviderResponse(
            content=self._answer,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], **kw: object) -> object:
        yield await self.send(messages)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.mark.asyncio
class TestSubAgent:
    async def test_run_success(self) -> None:
        r = await SubAgent(StubProvider("result A"), max_iterations=5).run("task A")
        assert r.success
        assert r.output == "result A"

    async def test_run_failure(self) -> None:
        class Fail(StubProvider):
            async def send(self, messages: list[Message], **kw: object) -> ProviderResponse:
                raise RuntimeError("API down")
        r = await SubAgent(Fail(), max_iterations=2).run("fail")
        assert not r.success
        assert "API down" in r.output

    async def test_run_reports_iteration_count(self) -> None:
        """成功完成时 iterations 应反映实际迭代次数，而非恒为默认 0。"""
        r = await SubAgent(StubProvider("result"), max_iterations=5).run("task")
        assert r.success
        # StubProvider 一轮即产出文本答案 → 迭代计数为 1
        assert r.iterations == 1

    async def test_separate_context(self) -> None:
        r1, r2 = await asyncio.gather(
            SubAgent(StubProvider("a1"), max_iterations=3).run("t1"),
            SubAgent(StubProvider("a2"), max_iterations=3).run("t2"),
        )
        assert r1.output == "a1"
        assert r2.output == "a2"


@pytest.mark.asyncio
class TestSubAgentContextInjection:
    """子 Agent 应继承父级 soul/facts/skills 等上下文组件，但保持消息历史隔离。"""

    async def test_stores_context_components(self) -> None:
        """构造时传入的组件应存储在 SubAgent 上，便于转发到子 AgentLoop。"""
        soul = SoulStore(global_path="/nonexistent/global.md", project_path="/nonempty/does-not-exist.md")
        facts = FactStore(path="/nonexistent/facts.md")
        agent = SubAgent(
            StubProvider(),
            soul=soul,
            facts=facts,
            skills=None,
            profile=None,
            compressor=None,
            context_dir=None,
        )
        assert agent._soul is soul
        assert agent._facts is facts
        assert agent._skills is None
        assert agent._profile is None
        assert agent._compressor is None
        assert agent._context_dir is None

    async def test_child_loop_inherits_soul_and_facts(self, tmp_path) -> None:
        """run() 内部构造的子 AgentLoop 应使用注入的 soul/facts，系统提示词含其内容。"""

        # 构造真实带内容的 SoulStore（项目级文件存在）
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("I am a helpful fish.", encoding="utf-8")
        soul = SoulStore(
            global_path="/nonexistent/global.md",
            project_path=str(soul_path),
        )

        # 构造带内容的 FactStore
        facts_path = tmp_path / "MEMORY.md"
        facts_path.write_text("- water is wet\n", encoding="utf-8")
        facts = FactStore(path=str(facts_path))

        # 捕获子 AgentLoop 构造时传入的组件：patch AgentLoop 构造器
        captured: dict[str, object] = {}
        from heagent.agent import loop as loop_module

        real_init = loop_module.AgentLoop.__init__

        def spy_init(self_loop, provider, **kwargs):
            captured["soul"] = kwargs.get("soul")
            captured["facts"] = kwargs.get("facts")
            captured["skills"] = kwargs.get("skills")
            captured["profile"] = kwargs.get("profile")
            captured["compressor"] = kwargs.get("compressor")
            captured["context_dir"] = kwargs.get("context_dir")
            return real_init(self_loop, provider, **kwargs)

        loop_module.AgentLoop.__init__ = spy_init
        try:
            agent = SubAgent(
                StubProvider("ok"),
                soul=soul,
                facts=facts,
            )
            result = await agent.run("anything")
        finally:
            loop_module.AgentLoop.__init__ = real_init

        assert result.success
        # 断言转发到子 AgentLoop
        assert captured["soul"] is soul
        assert captured["facts"] is facts
        # 子 loop 用其 _build_system 验证内容确实被注入
        # （直接验证 AgentLoop 自身行为已由 loop 测试覆盖；此处只验证转发）

    async def test_backward_compat_bare_constructor(self) -> None:
        """裸 SubAgent(provider) 不传任何上下文组件，行为与现状一致。"""
        agent = SubAgent(StubProvider("legacy"))
        # 六个组件应全为 None
        for attr in ("_soul", "_facts", "_skills", "_profile", "_compressor", "_context_dir"):
            assert getattr(agent, attr) is None
        result = await agent.run("anything")
        assert result.success
        assert result.output == "legacy"


@pytest.mark.asyncio
class TestParallel:
    async def test_parallel_all_succeed(self) -> None:
        agents = [SubAgent(StubProvider(f"r{i}"), max_iterations=5) for i in range(3)]
        results = await run_parallel(agents, [f"t{i}" for i in range(3)])
        assert len(results) == 3
        assert all(r.success for r in results)

    async def test_parallel_one_fails(self) -> None:
        class Fail(StubProvider):
            async def send(self, messages: list[Message], **kw: object) -> ProviderResponse:
                raise ValueError("boom")
        results = await run_parallel(
            [SubAgent(StubProvider("ok"), max_iterations=5),
             SubAgent(Fail(), max_iterations=5)],
            ["good", "bad"],
        )
        assert results[0].success
        assert not results[1].success

    async def test_empty(self) -> None:
        assert await run_parallel([], []) == []

    async def test_parallel_shared_skillstore_no_lost_usage_update(self, tmp_path) -> None:
        """回归：多个并行 SubAgent 共享同一 SkillStore 时，record_usage 不丢失更新。

        deferred-work 曾记录此为写竞态（2026-06-18），但经核实不成立：SkillStore.record_usage
        是无 await 的同步原子段（parse→+1→save→write_text），单线程 asyncio 下两个协程的调用
        必然串行执行（A 完整写完后才轮到 B），不存在丢失更新或交错写入。此测试锁定该不变量——
        若未来 SkillStore 方法 async 化引入真正的 await 交错，usage_count 将不再等于并发数，
        测试变红以提醒重新评估并发安全。
        """
        store = SkillStore(str(tmp_path / "skills"))
        store.save(
            "grepsearch", "search files with grep", "grep search files",
            ["run grep"], tags=["search"],
        )
        n = 8
        agents = [SubAgent(StubProvider(f"r{i}"), max_iterations=5, skills=store) for i in range(n)]
        await run_parallel(agents, ["use grep to search files"] * n)
        parsed = store.parse("grepsearch")
        assert parsed is not None
        assert parsed.usage_count == n
