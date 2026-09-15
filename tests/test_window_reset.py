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

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from heagent.agent import tool_execution
from heagent.agent.loop import AgentLoop
from heagent.context.compressor import ContextCompressor, STRUCTURED_SUMMARY_PROMPT
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


@pytest.fixture(autouse=True)
def _pin_context_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定上下文窗口为 128k，隔离全局默认值波动。

    ``_maybe_window_reset`` 用 ``settings.max_context_tokens`` 作为分母；commit
    574c2d9 曾把默认值从 128000 改成 1_000_000，导致 80000 usage 不再越过 60%
    阈值、端到端 window_reset 用例失败。这里显式钉死窗口，测试不再依赖全局默认。
    """
    from heagent.config import reset_settings

    monkeypatch.setenv("MAX_CONTEXT_TOKENS", "128000")
    reset_settings()
    yield
    reset_settings()


def _usage(total: int = 15) -> TokenUsage:
    return TokenUsage(prompt_tokens=total // 2, completion_tokens=total - total // 2, total_tokens=total)


def _final(content: str) -> ProviderResponse:
    return ProviderResponse(content=content, usage=_usage(), model="stub", finish_reason="stop")


# 摘要请求的识别标记**从共享常量派生**：此前硬编码旧 prompt 的前缀，prompt 一改
# （P0-3 结构化四段）测试就静默走错分支，用「payload 耗尽 → 默认回复」冒充成功。
_SUMMARY_PREFIX = STRUCTURED_SUMMARY_PROMPT.split("\n", 1)[0]


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
        if last is not None and last.role == Role.USER and (last.content or "").startswith(_SUMMARY_PREFIX):
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
    assert [m.role for m in out] == [Role.SYSTEM, Role.USER, Role.USER]
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
    assert [m.role for m in out] == [Role.SYSTEM, Role.USER, Role.USER]
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
    await store.start(rc, prompt="hi", system=None)
    await store.checkpoint(rc, prompt="hi", system=None, messages=[], final_answer="42")

    loop = AgentLoop(_StubProvider([]), engine=_engine(tmp_path, store=store))
    assert await loop.resume(rc.run_id) == "42"


async def test_resume_rebuilds_from_progress_summary(tmp_path) -> None:
    store = RunStore(str(tmp_path / "runs"))
    rc = RunContext()
    rc.metadata["progress_summary"] = "step1 done"
    rc.touch(iteration=3)
    await store.start(rc, prompt="build app", system=None)
    await store.checkpoint(
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
    await store.start(rc, prompt="hi", system=None)
    await store.checkpoint(rc, prompt="hi", system=None, messages=[], final_answer="42")

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
    await store.start(rc, prompt="build app", system=None)
    await store.checkpoint(
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
    await loop.engine.ledger.acquire(cache_key, run_id=rc.run_id)

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


# ══════════════════════════════════════════════════════════════════════
# 长时工具调用：在途续租 + 回写容错
# （回归 2026-09-15：6 分半的 shell 跑超 120s 租约 → 记录被 prune 当孤儿删掉 →
#   complete 抛 Cannot complete non-existent key → 跑完的输出被换成一条记账报错）
# ══════════════════════════════════════════════════════════════════════

_TOOL_LOGGER = "heagent.agent.tool_execution"


def _slow_registry(delay: float) -> tuple[ToolRegistry, dict[str, int]]:
    """注册耗时 ``delay`` 秒的 ``slow`` 工具；返回 (registry, counter)。"""
    counter: dict[str, int] = {"n": 0}

    async def slow() -> int:
        counter["n"] += 1
        await asyncio.sleep(delay)
        return counter["n"]

    registry = ToolRegistry()
    registry.register(
        ToolSchema(name="slow", description="slow", parameters={"type": "object", "properties": {}}),
        slow,
    )
    return registry, counter


@pytest.fixture
def _short_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """把租约压到 1s、续期 0.2s，使「跑超租约」在测试里只要 1 秒（而非 2 分钟）。"""
    monkeypatch.setattr(tool_execution, "_LEDGER_LEASE_SECONDS", 1)
    monkeypatch.setattr(tool_execution, "_LEDGER_LEASE_RENEW_INTERVAL", 0.2)


@pytest.mark.usefixtures("_short_lease")
async def test_inflight_tool_call_keeps_its_lease_fresh(tmp_path) -> None:
    """在途续租：长时工具跑超租约时，其它进程的 prune 删不掉它的记录。

    时序复刻线上故障——1s 租约 + 1.6s 工具，在 1.25s（已超原始租约、但**仍未跑完**）
    执行 prune；若未续租，此时记录会被当作过期孤儿删掉。
    """
    registry, counter = _slow_registry(1.6)
    loop = AgentLoop(_StubProvider([]), registry=registry, engine=_engine(tmp_path))
    rc = RunContext()
    call = ToolCall(id="s1", name="slow", arguments={})

    task = asyncio.create_task(loop._execute_one(call, run_context=rc))
    await asyncio.sleep(1.25)
    # 前置断言：此刻记录确实还是 RUNNING（否则 prune 测试会因「已经终态」而假通过）。
    inflight = await loop.engine.ledger.get(f"{rc.run_id}:{call.id}")
    assert inflight is not None and inflight.status.value == "running"
    assert await loop.engine.ledger.prune(retention_days=7) == 0  # 续租保住了在途记录

    result = await task
    assert result.is_error is False
    assert result.content == "1"
    assert counter["n"] == 1

    record = await loop.engine.ledger.get(f"{rc.run_id}:{call.id}")
    assert record is not None and record.status.value == "completed"

    # 幂等缓存仍然可用：同一 tool_call.id 再发一次不再执行 handler。
    cached = await loop._execute_one(call, run_context=rc)
    assert cached.content == "1"
    assert counter["n"] == 1


@pytest.mark.usefixtures("_short_lease")
async def test_expired_orphan_is_prunable_but_result_survives(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """反例（禁用续租）：记录仍会被 prune 删掉，但工具结果不再被记账错误顶替。

    这条锁住故障的另一半——prune 语义本身不变（过期 RUNNING = 孤儿），变的是
    「缓存丢了不能连结果一起丢」。
    """

    async def _noop_renewal(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(tool_execution, "_renew_ledger_lease", _noop_renewal)
    registry, counter = _slow_registry(1.6)
    loop = AgentLoop(_StubProvider([]), registry=registry, engine=_engine(tmp_path))
    rc = RunContext()
    call = ToolCall(id="s2", name="slow", arguments={})

    with caplog.at_level(logging.WARNING, logger=_TOOL_LOGGER):
        task = asyncio.create_task(loop._execute_one(call, run_context=rc))
        await asyncio.sleep(1.25)
        inflight = await loop.engine.ledger.get(f"{rc.run_id}:{call.id}")
        assert inflight is not None and inflight.status.value == "running"
        # 租约在 1.0s 已过期、工具尚未跑完 → 判为孤儿并删除。
        assert await loop.engine.ledger.prune(retention_days=7) == 1
        result = await task

    assert result.is_error is False
    assert result.content == "1"  # ← 修复前这里是 "Tool error: Cannot complete non-existent key..."
    assert counter["n"] == 1
    assert any("Failed to record ledger outcome" in record.message for record in caplog.records)
    assert await loop.engine.ledger.get(f"{rc.run_id}:{call.id}") is None  # 缓存确已丢失


async def test_complete_failure_keeps_successful_result(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """回写成功态抛错（记录被清）→ 成功的工具结果原样返回，只记 warning。"""
    registry, counter = _bump_registry()
    loop = AgentLoop(_StubProvider([]), registry=registry, engine=_engine(tmp_path))
    rc = RunContext()
    call = ToolCall(id="c9", name="bump", arguments={})

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("Cannot complete non-existent key: 'x'")

    monkeypatch.setattr(loop.engine.ledger, "complete", _boom)

    with caplog.at_level(logging.WARNING, logger=_TOOL_LOGGER):
        result = await loop._execute_one(call, run_context=rc)

    assert result.is_error is False
    assert result.content == "1"
    assert counter["n"] == 1
    assert any("Failed to record ledger outcome" in record.message for record in caplog.records)


async def test_fail_writeback_failure_keeps_error_result(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """回写失败态抛错 → 仍返回 handler 的错误结果，不被记账错误顶替。"""

    async def boom_tool() -> str:
        raise RuntimeError("handler exploded")

    registry = ToolRegistry()
    registry.register(
        ToolSchema(name="boom", description="boom", parameters={"type": "object", "properties": {}}),
        boom_tool,
    )
    loop = AgentLoop(_StubProvider([]), registry=registry, engine=_engine(tmp_path))
    rc = RunContext()
    call = ToolCall(id="c10", name="boom", arguments={})

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("Cannot fail non-existent key: 'x'")

    monkeypatch.setattr(loop.engine.ledger, "fail", _boom)

    with caplog.at_level(logging.WARNING, logger=_TOOL_LOGGER):
        result = await loop._execute_one(call, run_context=rc)

    assert result.is_error is True
    assert "handler exploded" in result.content  # handler 的失败原因仍可见
    assert "non-existent key" not in result.content  # 记账错误未顶替
    assert any("Failed to record ledger outcome" in record.message for record in caplog.records)


async def test_renewal_stops_when_record_is_gone(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """记录已消失时续租任务自行退出（不空转），且不抛错。"""
    monkeypatch.setattr(tool_execution, "_LEDGER_LEASE_RENEW_INTERVAL", 0.01)
    ledger = ExecutionLedger(str(tmp_path / "ledger"))

    with caplog.at_level(logging.WARNING, logger=_TOOL_LOGGER):
        # wait_for 兜底：若实现退化成死循环，测试立刻失败而不是挂住。
        await asyncio.wait_for(tool_execution._renew_ledger_lease(ledger, "gone:key"), timeout=2)

    assert any("vanished" in record.message for record in caplog.records)


async def test_renewal_survives_heartbeat_io_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """续租自身 I/O 故障只告警并重试，绝不把异常抛进工具执行路径。"""
    monkeypatch.setattr(tool_execution, "_LEDGER_LEASE_RENEW_INTERVAL", 0.01)
    ledger = ExecutionLedger(str(tmp_path / "ledger"))
    await ledger.acquire("k:1", lease_seconds=30)
    calls: list[int] = []

    async def _flaky(key: str, *, lease_seconds: int = 120):  # noqa: ANN202 - 测试替身
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk hiccup")
        return None  # 第二次返回 None → 任务正常退出

    monkeypatch.setattr(ledger, "heartbeat", _flaky)

    with caplog.at_level(logging.WARNING, logger=_TOOL_LOGGER):
        await asyncio.wait_for(tool_execution._renew_ledger_lease(ledger, "k:1"), timeout=2)

    assert len(calls) >= 2  # 失败后仍重试（未因异常退出）
    assert any("renewal failed" in record.message for record in caplog.records)
