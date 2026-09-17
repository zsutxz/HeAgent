"""Tests for agent-layer delegation callbacks — tools ↔ agent 依赖倒置。

Covers: ``build_subagent_delegates`` 把 ``SubAgentResult`` 映射为工具层
``SubTaskOutcome``、并行时每个 task 独立 SubAgent 且保序、组件与 parent run id
透传；以及 ``AgentLoop`` 在 run 作用域内绑定回调后，真实循环能调用
``task_delegate`` 完成端到端委派（工具层不认识 SubAgent）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from heagent.agent.delegation import build_subagent_delegates
from heagent.agent.loop import AgentLoop, _delegation_details
from heagent.agent.sub import SubAgent
from heagent.config import get_settings, reset_settings
from heagent.engine import EngineContainer
from heagent.roles import get_role
from heagent.memory.facts import FactStore
from heagent.memory.soul import SoulStore
from heagent.providers.base import ProviderMetadata
from heagent.tools.builtins.subagent import reset_subagent_tools, task_delegate
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture(autouse=True)
def _reset_subagent_runtime() -> object:
    """每个测试前后复位委派回调槽与 Settings 单例，避免测试间串扰。"""
    reset_subagent_tools()
    reset_settings()
    yield
    reset_subagent_tools()
    reset_settings()


class _StubProvider:
    """Returns a fixed answer, so a delegated sub-agent finishes in one round."""

    def __init__(self, answer: str = "child answer") -> None:
        self._answer = answer

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:  # noqa: ANN001, ARG002
        return ProviderResponse(
            content=self._answer,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools=None) -> AsyncIterator[ProviderResponse]:  # noqa: ANN001, ARG002
        yield ProviderResponse(
            content=self._answer,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _spy_subagent_init(monkeypatch, captured: list[dict]) -> None:  # noqa: ANN001
    """Record every SubAgent construction kwargs while keeping real behavior."""
    original = SubAgent.__init__

    def spy(self, provider, **kwargs):  # noqa: ANN001, ANN202
        captured.append(kwargs)
        original(self, provider, **kwargs)

    monkeypatch.setattr(SubAgent, "__init__", spy)


async def test_delegate_one_maps_result_to_outcome() -> None:
    delegate_one, _ = build_subagent_delegates(_StubProvider("computed"))
    outcome = await delegate_one("do it", None, None)

    assert outcome.status == "ok"
    assert outcome.task == "do it"
    assert outcome.output == "computed"
    assert outcome.iterations >= 1
    assert outcome.run_id
    assert outcome.role == ""


async def test_delegate_one_carries_role_name() -> None:
    delegate_one, _ = build_subagent_delegates(_StubProvider())
    outcome = await delegate_one("write a function", get_role("coder"), None)
    assert outcome.role == "coder"


async def test_delegate_one_reports_failure() -> None:
    class _FailProvider(_StubProvider):
        async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:  # noqa: ANN001, ARG002
            raise RuntimeError("provider exploded")

    delegate_one, _ = build_subagent_delegates(_FailProvider())
    outcome = await delegate_one("boom", None, None)

    assert outcome.status == "failed"
    assert "provider exploded" in outcome.output


async def test_delegate_many_keeps_order_with_one_agent_per_task(monkeypatch) -> None:
    captured: list[dict] = []
    _spy_subagent_init(monkeypatch, captured)

    _, delegate_many = build_subagent_delegates(_StubProvider())
    outcomes = await delegate_many(["a", "b", "c"], None, None)

    assert [o.task for o in outcomes] == ["a", "b", "c"]
    assert all(o.status == "ok" for o in outcomes)
    # P1-1：每个 task 独立实例（同一实例被并发 run 会竞态读写内部状态）。
    assert len(captured) == 3


async def test_delegates_thread_components_and_parent_run_id(monkeypatch) -> None:
    captured: list[dict] = []
    _spy_subagent_init(monkeypatch, captured)

    soul = SoulStore(global_path="/nonexistent/global.md", project_path="/nonexistent/project.md")
    facts = FactStore(path="/nonexistent/facts.md")
    delegate_one, _ = build_subagent_delegates(
        _StubProvider(),
        soul=soul,
        facts=facts,
        parent_run_id="parent-1",
    )
    await delegate_one("any task", None, "be terse")

    assert captured[0]["soul"] is soul
    assert captured[0]["facts"] is facts
    assert captured[0]["parent_run_id"] == "parent-1"
    assert captured[0]["system"] == "be terse"
    assert captured[0]["skills"] is None
    assert captured[0]["profile"] is None
    assert captured[0]["compressor"] is None
    assert captured[0]["context_dir"] is None


class _DelegatingProvider:
    """Round 1: main loop asks for ``task_delegate``. Later rounds: plain text.

    主 loop 与子 loop 共用同一 provider 实例，因此按调用序号区分：
    #1 主 loop 发起委派 → #2 子 loop 收尾（无工具调用）→ #3 主 loop 收尾。
    """

    def __init__(self) -> None:
        self.round = 0
        self.seen: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:  # noqa: ANN001, ARG002
        self.round += 1
        self.seen.append([m.model_copy() for m in messages])
        if self.round == 1:
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCall(id="call_1", name="task_delegate", arguments={"task": "child work", "role": "coder"})
                ],
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model="stub",
                finish_reason="tool_calls",
            )
        return ProviderResponse(
            content="parent done",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools=None) -> AsyncIterator[ProviderResponse]:  # noqa: ANN001, ARG002
        yield ProviderResponse(content="parent done", usage=TokenUsage(), model="stub", finish_reason="stop")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


async def test_agent_loop_run_binds_delegates_end_to_end(tmp_path) -> None:  # noqa: ANN001
    """AC3：AgentLoop 起一次 run 后，模型调用 task_delegate 即完成真实委派。"""
    provider = _DelegatingProvider()
    loop = AgentLoop(provider, context_dir=str(tmp_path), max_iterations=5)
    output = await loop.run("delegate something")

    assert output == "parent done"
    assert loop.last_run_context is not None
    steps = loop.last_run_context.metadata["completed_steps"]
    assert len(steps) == 1
    assert steps[0]["task"] == "child work"
    assert steps[0]["role"] == "coder"
    assert steps[0]["success"] is True
    assert steps[0]["run_id"]


async def test_delegates_thread_depth_to_subagent(monkeypatch) -> None:  # noqa: ANN001
    """父 loop 深度 depth → 子 Agent 记录 depth+1。"""
    captured: list[dict] = []
    _spy_subagent_init(monkeypatch, captured)

    delegate_one, _ = build_subagent_delegates(_StubProvider(), depth=2)
    await delegate_one("x", None, None)

    assert captured[0]["delegation_depth"] == 3


async def test_subagent_child_loop_inherits_depth(monkeypatch) -> None:
    """SubAgent 的深度透传到它创建的子 AgentLoop（闸门输入）。"""
    depths: list[int | None] = []
    original = AgentLoop.__init__

    def spy(self, provider, **kwargs):  # noqa: ANN001, ANN202
        depths.append(kwargs.get("delegation_depth"))
        original(self, provider, **kwargs)

    monkeypatch.setattr(AgentLoop, "__init__", spy)
    delegate_one, _ = build_subagent_delegates(_StubProvider(), depth=2)
    await delegate_one("x", None, None)

    assert depths == [3]


async def test_agent_loop_depth_limit_blocks_delegation(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """max_depth=0 时根 loop 的委派被拒：子 Agent 不构造，父循环正常收尾。"""
    monkeypatch.setattr(get_settings(), "subagent_max_depth", 0)
    provider = _DelegatingProvider()
    loop = AgentLoop(provider, context_dir=str(tmp_path), max_iterations=5)
    output = await loop.run("delegate something")

    assert output == "parent done"
    # 只有主 loop 的两轮调用（#1 发起委派被拒，#2 收尾）——子 loop 未启动。
    assert provider.round == 2
    assert loop.last_run_context is not None
    assert loop.last_run_context.metadata.get("completed_steps", []) == []


class _NestedDelegatingProvider:
    """轮次 #1/#2 请求 task_delegate，#3/#4 以文本收尾。

    主 loop 与子 loop 共用同一实例：#1 主 loop 发起一级委派 → 子 loop（depth=1）
    #2 尝试二级委派（max_depth=1 时被闸门拒绝）→ #3 子 loop 收尾 → #4 主 loop 收尾。
    """

    def __init__(self) -> None:
        self.round = 0

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:  # noqa: ANN001, ARG002
        self.round += 1
        if self.round <= 2:
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"call_{self.round}",
                        name="task_delegate",
                        arguments={"task": f"level-{self.round}"},
                    )
                ],
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model="stub",
                finish_reason="tool_calls",
            )
        return ProviderResponse(
            content=f"done-{self.round}",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools=None) -> AsyncIterator[ProviderResponse]:  # noqa: ANN001, ARG002
        yield ProviderResponse(content="done", usage=TokenUsage(), model="stub", finish_reason="stop")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


async def test_nested_delegation_stops_at_depth_limit(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """max_depth=1：一级委派放行，子 loop 的二级委派被闸门拒绝并自行收尾。"""
    monkeypatch.setattr(get_settings(), "subagent_max_depth", 1)
    provider = _NestedDelegatingProvider()
    loop = AgentLoop(provider, context_dir=str(tmp_path), max_iterations=6)
    output = await loop.run("delegate chain")

    assert output == "done-4"
    # #1 主 loop 委派 → #2 子 loop 二级委派被拒 → #3 子 loop 收尾 → #4 主 loop 收尾。
    assert provider.round == 4
    assert loop.last_run_context is not None
    steps = loop.last_run_context.metadata["completed_steps"]
    assert len(steps) == 1
    assert steps[0]["task"] == "level-1"
    assert steps[0]["output"] == "done-3"


async def test_agent_loop_binding_is_scoped_to_run(tmp_path) -> None:  # noqa: ANN001
    """run 结束后回调解绑：工具返回未配置错误，而不是复用上一次 run 的回调。"""
    loop = AgentLoop(_StubProvider(), context_dir=str(tmp_path), max_iterations=2)
    await loop.run("hello")

    payload = json.loads(await task_delegate("stale"))
    assert payload["status"] == "error"
    assert "not configured" in payload["message"]


def test_delegation_details_keep_only_identity_keys() -> None:
    """Only the delegation identity travels into the log; unrelated metadata stays out."""
    engine = EngineContainer()
    run_context = engine.create_run_context(
        metadata={"kind": "subagent", "role": "bmad-build", "workflow_step": "step-07-implement-story.md", "memo": ""}
    )
    assert _delegation_details(run_context) == {
        "kind": "subagent",
        "role": "bmad-build",
        "workflow_step": "step-07-implement-story.md",
    }


@pytest.mark.asyncio
async def test_run_started_event_carries_the_delegation_identity(tmp_path) -> None:  # noqa: ANN001
    """``run_started`` must name the delegated run, since banners never reach the log file."""
    engine = EngineContainer(workspace_root=str(tmp_path))
    run_context = engine.create_run_context(
        metadata={"kind": "subagent", "role": "bmad-build", "workflow_step": "step-07-implement-story.md"}
    )
    loop = AgentLoop(
        _StubProvider(),
        engine=engine,
        context_dir=str(tmp_path),
        max_iterations=2,
        run_context=run_context,
    )
    await loop.run("do it")
    started = [event for event in engine.events.recent_events if event.event_type == "run_started"]
    assert started
    assert started[-1].details["kind"] == "subagent"
    assert started[-1].details["role"] == "bmad-build"
    assert started[-1].details["workflow_step"] == "step-07-implement-story.md"
