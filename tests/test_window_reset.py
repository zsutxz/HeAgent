"""Tests for P3 checkpoint-resume (WindowReset + AgentLoop.resume) and the P4
ExecutionLedger idempotency wired into ``_execute_one``.

Covers:
  - ``WindowReset.should_trigger`` threshold semantics.
  - ``WindowReset.reset`` rebuilds a 3-message window and bumps segment/progress
    metadata (survives window resets).
  - ``ContextCompressor`` and ``window_reset`` are mutually exclusive (D3).
  - ``AgentLoop.resume`` returns the cached answer for COMPLETED runs and
    rebuilds a fresh window from ``progress_summary`` for unfinished runs.
  - End-to-end: a high-usage tool round triggers a reset; a re-sent
    ``tool_call.id`` afterwards is short-circuited by the ledger (no duplicate
    side effect).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from heagent.agent.loop import AgentLoop
from heagent.context.compressor import ContextCompressor
from heagent.context.window_reset import WindowReset, WindowResetConfig
from heagent.engine.container import EngineContainer
from heagent.engine.context import RunContext, RunStatus
from heagent.engine.ledger import ExecutionLedger
from heagent.engine.store import RunStore
from heagent.providers.base import ProviderMetadata
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall, ToolSchema

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence


def _usage(total: int = 15) -> TokenUsage:
    return TokenUsage(prompt_tokens=total // 2, completion_tokens=total - total // 2, total_tokens=total)


def _final(content: str) -> ProviderResponse:
    return ProviderResponse(content=content, usage=_usage(), model="stub", finish_reason="stop")


class _StubProvider:
    """Scripted main-conversation provider that returns a canned summary.

    A summary request (a single user message whose content starts with the
    shared summary prompt) is answered from a side channel so it does not
    consume the main scripted response sequence.
    """

    def __init__(self, responses: Sequence[ProviderResponse], *, summary: str = "SUMMARY") -> None:
        self._responses = list(responses)
        self._idx = 0
        self._summary = summary

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        last = messages[-1] if messages else None
        if (
            last is not None
            and last.role == Role.USER
            and (last.content or "").startswith("Summarize the following conversation so far")
        ):
            return ProviderResponse(content=self._summary, usage=_usage(), model="stub", finish_reason="stop")
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return _final("ok")

    async def stream(
        self, messages: list[Message], *, tools: list[object] | None = None
    ) -> AsyncIterator[ProviderResponse]:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _engine(tmp_path, store: RunStore | None = None) -> EngineContainer:
    """Isolated engine pointing at tmp dirs (no leakage into the workspace)."""
    return EngineContainer(
        run_store=store or RunStore(str(tmp_path / "runs")),
        ledger=ExecutionLedger(str(tmp_path / "ledger")),
    )


def test_should_trigger_threshold() -> None:
    wr = WindowReset(_StubProvider([]), config=WindowResetConfig(threshold=0.6))
    assert wr.should_trigger(token_count=60, max_tokens=100) is True  # exactly at threshold
    assert wr.should_trigger(token_count=59, max_tokens=100) is False
    assert wr.should_trigger(token_count=100, max_tokens=0) is False  # max_tokens disabled


def test_build_resume_messages_structure() -> None:
    out = WindowReset.build_resume_messages(original_prompt="do X", summary="half done")
    assert [m.role for m in out] == [Role.SYSTEM, Role.USER, Role.SYSTEM]
    assert out[1].content == "do X"
    assert "half done" in out[0].content


async def test_reset_rebuilds_window_and_metadata() -> None:
    wr = WindowReset(_StubProvider([]), config=WindowResetConfig(threshold=0.6))
    rc = RunContext()
    messages = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="task"),
        Message(role=Role.ASSISTANT, content="working"),
        Message(role=Role.TOOL, content="r", tool_call_id="t1"),
    ]

    out = await wr.reset(run_context=rc, original_prompt="task", messages=messages)

    assert len(out) == 3
    assert [m.role for m in out] == [Role.SYSTEM, Role.USER, Role.SYSTEM]
    assert out[1].content == "task"
    # system messages are excluded from the summary payload but metadata records it
    assert rc.metadata["segment"] == 1
    assert rc.metadata["progress_summary"] == "SUMMARY"
    assert "[Progress summary]" in out[0].content


def test_window_reset_mutually_exclusive_with_compressor() -> None:
    provider = _StubProvider([])
    with pytest.raises(ValueError, match="mutually exclusive"):
        AgentLoop(provider, compressor=ContextCompressor(provider), window_reset=WindowResetConfig())


async def test_resume_completed_returns_cached_answer(tmp_path) -> None:
    store = RunStore(str(tmp_path / "runs"))
    rc = RunContext()
    rc.touch(status=RunStatus.COMPLETED)
    store.start(rc, prompt="hi", system=None)
    store.checkpoint(rc, prompt="hi", system=None, messages=[], final_answer="42")

    loop = AgentLoop(_StubProvider([]), engine=_engine(tmp_path, store=store))
    assert await loop.resume(rc.run_id) == "42"


async def test_resume_rebuilds_from_progress_summary(tmp_path) -> None:
    store = RunStore(str(tmp_path / "runs"))
    rc = RunContext()
    rc.metadata["progress_summary"] = "step1 done"
    rc.touch(iteration=3)
    store.start(rc, prompt="build app", system=None)
    store.checkpoint(
        rc,
        prompt="build app",
        system=None,
        messages=[Message(role=Role.USER, content="build app")],
    )

    provider = _StubProvider([_final("final-out")])
    loop = AgentLoop(provider, engine=_engine(tmp_path, store=store))

    out = await loop.resume(rc.run_id)
    assert out == "final-out"
    assert loop.last_run_context is not None
    assert loop.last_run_context.status == RunStatus.COMPLETED


async def test_resume_stream_completed_yields_done(tmp_path) -> None:
    """P5-5：COMPLETED 的 run 用 resume_stream 只产出一个携带缓存答案的 done 事件。"""
    store = RunStore(str(tmp_path / "runs"))
    rc = RunContext()
    rc.touch(status=RunStatus.COMPLETED)
    store.start(rc, prompt="hi", system=None)
    store.checkpoint(rc, prompt="hi", system=None, messages=[], final_answer="42")

    loop = AgentLoop(_StubProvider([]), engine=_engine(tmp_path, store=store))
    events = [e async for e in loop.resume_stream(rc.run_id)]
    assert [e.type for e in events] == ["done"]
    assert events[0].final_answer == "42"


async def test_resume_stream_rebuilds_and_continues(tmp_path) -> None:
    """P5-5：未完成 run 从 progress_summary 重建窗口并流式续跑到 done。"""
    store = RunStore(str(tmp_path / "runs"))
    rc = RunContext()
    rc.metadata["progress_summary"] = "step1 done"
    rc.touch(iteration=3)
    store.start(rc, prompt="build app", system=None)
    store.checkpoint(
        rc,
        prompt="build app",
        system=None,
        messages=[Message(role=Role.USER, content="build app")],
    )

    provider = _StubProvider([_final("final-out")])
    loop = AgentLoop(provider, engine=_engine(tmp_path, store=store))

    events = [e async for e in loop.resume_stream(rc.run_id)]
    assert events[-1].type == "done"
    assert events[-1].final_answer == "final-out"
    assert loop.last_run_context is not None
    assert loop.last_run_context.status == RunStatus.COMPLETED


def _bump_registry() -> tuple[ToolRegistry, dict[str, int]]:
    """Fresh registry with a counting ``bump`` tool; returns (registry, counter)."""
    counter: dict[str, int] = {"n": 0}

    async def bump() -> int:
        counter["n"] += 1
        return counter["n"]

    registry = ToolRegistry()
    registry.register(
        ToolSchema(name="bump", description="bump", parameters={"type": "object", "properties": {}}),
        bump,
    )
    return registry, counter


async def test_execute_one_ledger_caches_completed_result(tmp_path) -> None:
    registry, counter = _bump_registry()
    loop = AgentLoop(_StubProvider([]), registry=registry, engine=_engine(tmp_path))
    rc = RunContext()
    call = ToolCall(id="c1", name="bump", arguments={})

    first = await loop._execute_one(call, run_context=rc)
    second = await loop._execute_one(call, run_context=rc)

    assert first.content == "1"
    assert second.content == "1"  # served from ledger cache
    assert counter["n"] == 1  # handler ran exactly once


async def test_window_reset_then_ledger_dedupe(tmp_path) -> None:
    """High-usage tool round triggers reset; a re-sent tool_call.id is deduped."""
    registry, counter = _bump_registry()
    high_usage = TokenUsage(prompt_tokens=40000, completion_tokens=40000, total_tokens=80000)
    provider = _StubProvider(
        [
            # round 1: call bump with usage past the 0.6 threshold → reset fires
            ProviderResponse(
                content="",
                tool_calls=[ToolCall(id="b1", name="bump", arguments={})],
                usage=high_usage,
                model="stub",
                finish_reason="tool_calls",
            ),
            # round 2 (after reset): model re-sends the same tool_call.id
            ProviderResponse(
                content="",
                tool_calls=[ToolCall(id="b1", name="bump", arguments={})],
                usage=_usage(),
                model="stub",
                finish_reason="tool_calls",
            ),
            # round 3: final answer
            _final("DONE"),
        ]
    )
    loop = AgentLoop(
        provider,
        registry=registry,
        engine=_engine(tmp_path),
        window_reset=WindowResetConfig(),
    )

    out = await loop.run("do work")

    assert out == "DONE"
    assert loop.last_run_context is not None
    assert loop.last_run_context.metadata.get("segment") == 1  # reset triggered once
    assert counter["n"] == 1  # re-sent b1 short-circuited by ledger


async def test_window_reset_triggers_in_stream_mode(tmp_path) -> None:
    """流式 ``run_stream`` 下 window_reset 同样触发（为 loop.py 重构兜底）。

    与 ``test_window_reset_then_ledger_dedupe`` 同构，但走 ``run_stream`` 路径，
    覆盖 ``run_stream`` 的 window_reset 分支——该分支在重构前无测试护栏
    （``run_stream`` 的 except/finally 与 yield 交织，最易在重构中回归）。
    """
    registry, _ = _bump_registry()
    high_usage = TokenUsage(prompt_tokens=40000, completion_tokens=40000, total_tokens=80000)
    provider = _StubProvider(
        [
            # round 1：工具调用 + 高 usage → 工具执行后触发 reset
            ProviderResponse(
                content="",
                tool_calls=[ToolCall(id="b1", name="bump", arguments={})],
                usage=high_usage,
                model="stub",
                finish_reason="tool_calls",
            ),
            # round 2（reset 后）：最终回答
            _final("DONE-STREAM"),
        ]
    )
    loop = AgentLoop(
        provider,
        registry=registry,
        engine=_engine(tmp_path),
        window_reset=WindowResetConfig(),
    )

    events = [e async for e in loop.run_stream("do work")]

    assert events[-1].type == "done"
    assert events[-1].final_answer == "DONE-STREAM"
    assert loop.last_run_context is not None
    assert loop.last_run_context.metadata.get("segment") == 1  # reset 触发一次
    assert loop.last_iteration is not None and loop.last_iteration >= 2


async def test_lease_active_skips_reexecute(tmp_path) -> None:
    """B：lease-active（RUNNING 未过期）命中时不重复执行 handler，返回 is_error skip。

    对齐 cron/scheduler.py 的「acquired=False 即 skip」语义。COMPLETED 命中走缓存
    由 test_execute_one_ledger_caches_completed_result 覆盖；本测试覆盖 RUNNING 分支。
    """
    registry, counter = _bump_registry()
    loop = AgentLoop(_StubProvider([]), registry=registry, engine=_engine(tmp_path))
    rc = RunContext()
    call = ToolCall(id="b1", name="bump", arguments={})

    # 预占 lease：acquire 写入 RUNNING 记录但不 complete，模拟并发重入。
    cache_key = f"{rc.run_id}:{call.id}"
    loop.engine.ledger.acquire(cache_key, run_id=rc.run_id)

    # 相同 cache_key 再调：acquire 返回 lease-active（acquired=False），应 skip。
    result = await loop._execute_one(call, run_context=rc)

    assert result.is_error
    assert "in-flight" in result.content
    assert counter["n"] == 0  # handler 未执行


async def test_cached_result_respects_policy_tightening(tmp_path) -> None:
    """A：缓存命中后若 policy 收紧到 BLOCKED，不返回缓存，按 BLOCKED 处理。

    防止 policy 收紧（新加 blocklist）后，已 COMPLETED 的 tool_call.id 借缓存绕过。
    """
    registry, counter = _bump_registry()
    loop = AgentLoop(_StubProvider([]), registry=registry, engine=_engine(tmp_path))
    rc = RunContext()
    call = ToolCall(id="b1", name="bump", arguments={})

    first = await loop._execute_one(call, run_context=rc)
    assert first.content == "1"
    assert counter["n"] == 1

    # 收紧 policy：把 bump 加入黑名单 → 再次执行应判 BLOCKED，不返回缓存。
    loop.engine.policy.blocked_tools = {*loop.engine.policy.blocked_tools, "bump"}

    second = await loop._execute_one(call, run_context=rc)
    assert second.is_error is True
    assert second.content != "1"  # 缓存内容未被放行
    assert counter["n"] == 1  # handler 未再执行（BLOCKED 在 executor 拦截）
