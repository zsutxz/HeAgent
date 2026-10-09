"""Tests for the per-run write allowlist fence (Epic 52 AD-17, Story 52-1).

写集围栏原语：PolicyEngine 对 ``file_write`` / ``file_edit`` 的目标路径做
``context.metadata["write_allowlist"]`` 越集预检（预防层，走既有治理链零旁路）；
SubAgent 经显式参数注入该键（reserved，用户 / role metadata 不可伪造）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from heagent.agent import sub as sub_module
from heagent.agent.sub import SubAgent
from heagent.engine import EngineContainer, PolicyEngine, RunContext, ToolExecutionMode
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import ProviderResponse, StreamEvent, TokenUsage, ToolCall


def _policy(tmp_path: Path, **kwargs: Any) -> PolicyEngine:
    return PolicyEngine(workspace_root=str(tmp_path), **kwargs)


def _ctx(tmp_path: Path, metadata: dict[str, Any] | None = None) -> RunContext:
    return RunContext(workspace_root=str(tmp_path), metadata=metadata or {})


def _call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id="t1", name=name, arguments=arguments)


# ── policy 层：越集 BLOCKED / 命中放行 ────────────────────────────────────────


def test_write_outside_allowlist_is_blocked(tmp_path: Path) -> None:
    """界内但越集的 file_write → BLOCKED，source=write_allowlist，reason 点名路径。"""
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "docs/x.md", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": ["src"]}),
    )
    assert verdict.mode is ToolExecutionMode.BLOCKED
    assert verdict.source == "write_allowlist"
    assert "docs/x.md" in verdict.reason
    assert "write set" in verdict.reason


def test_file_edit_outside_allowlist_is_blocked(tmp_path: Path) -> None:
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_edit", {"path": "docs/x.md"}),
        context=_ctx(tmp_path, {"write_allowlist": ["src"]}),
    )
    assert verdict.mode is ToolExecutionMode.BLOCKED
    assert verdict.source == "write_allowlist"


def test_directory_entry_allows_subtree(tmp_path: Path) -> None:
    """目录条目放行其子树（is_relative_to）。"""
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "src/module/x.py", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": ["src"]}),
    )
    assert verdict.mode is ToolExecutionMode.DIRECT


def test_file_entry_exact_match(tmp_path: Path) -> None:
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "src/x.py", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": ["src/x.py"]}),
    )
    assert verdict.mode is ToolExecutionMode.DIRECT


def test_workspace_fence_takes_precedence(tmp_path: Path) -> None:
    """越出工作区的路径仍由围栏裁决（source=workspace_paths），allowlist 不抢。"""
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "../outside.md", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": ["src"]}),
    )
    assert verdict.mode is ToolExecutionMode.BLOCKED
    assert verdict.source == "workspace_paths"


# ── policy 层：缺省 = 现状放行（零回归面） ────────────────────────────────────


def test_no_allowlist_passthrough(tmp_path: Path) -> None:
    """未声明 allowlist → 行为与现状一致（界内写放行）。"""
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "docs/x.md", "content": "hi"}),
        context=_ctx(tmp_path),
    )
    assert verdict.mode is ToolExecutionMode.DIRECT


def test_empty_allowlist_passthrough(tmp_path: Path) -> None:
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "docs/x.md", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": []}),
    )
    assert verdict.mode is ToolExecutionMode.DIRECT


def test_non_list_allowlist_passthrough(tmp_path: Path) -> None:
    """非列表（如字符串）视为未启用——宿主契约是列表，畸形输入不启用围栏。"""
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "docs/x.md", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": "src"}),
    )
    assert verdict.mode is ToolExecutionMode.DIRECT


def test_read_tool_unaffected(tmp_path: Path) -> None:
    """读工具不接写集围栏（读不构成写集冲突）。"""
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_read", {"path": "docs/x.md"}),
        context=_ctx(tmp_path, {"write_allowlist": ["src"]}),
    )
    assert verdict.mode is ToolExecutionMode.DIRECT


def test_no_context_passthrough(tmp_path: Path) -> None:
    """无 run 上下文 → allowlist 不适用（它是 per-run 授权，随 context 注入）。"""
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "docs/x.md", "content": "hi"}),
        context=None,
    )
    assert verdict.mode is ToolExecutionMode.DIRECT


def test_entry_outside_root_is_dead_entry(tmp_path: Path) -> None:
    """越界条目按死条目处理（永不匹配）——只收紧、不放宽可写范围。"""
    verdict = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "src/x.py", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": ["../outside", "src"]}),
    )
    assert verdict.mode is ToolExecutionMode.DIRECT  # "src" 条目仍命中

    blocked = _policy(tmp_path).evaluate_tool_call(
        _call("file_write", {"path": "docs/x.md", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": ["../outside"]}),
    )
    assert blocked.mode is ToolExecutionMode.BLOCKED  # 死条目放行不了任何路径


def test_danger_full_access_skips_allowlist(tmp_path: Path) -> None:
    """danger-full-access 档跳过整族路径预检（与围栏 / deny 同一口径）。"""
    verdict = _policy(tmp_path, sandbox_mode="danger-full-access").evaluate_tool_call(
        _call("file_write", {"path": "docs/x.md", "content": "hi"}),
        context=_ctx(tmp_path, {"write_allowlist": ["src"]}),
    )
    assert verdict.mode is ToolExecutionMode.DIRECT


# ── SubAgent：参数注入 + reserved 防伪造 ──────────────────────────────────────


class _OkProvider:
    """Round 1 即返回最终文本的最小 provider。"""

    async def send(self, messages: list[Any], *, tools: Any = None) -> ProviderResponse:
        return ProviderResponse(
            content="ok",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Any], *, tools: Any = None):
        # 单 chunk 复用 send（usage 合法——TokenUsage 字段必填，哑化会在流式执行路径炸校验）。
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture()
def capture_loop(monkeypatch: pytest.MonkeyPatch) -> list[RunContext | None]:
    """把 SubAgent.run 内构造的 AgentLoop 换成捕获桩，收集传入的 RunContext。"""
    captured: list[RunContext | None] = []

    class _Loop:
        last_iteration = 0
        last_run_context = None

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.append(kwargs.get("run_context"))

        async def run(self, task: str, system: str | None = None) -> str:
            return "ok"

        async def run_stream(self, task: str, system: str | None = None):
            yield StreamEvent(type="done", final_answer="ok")

    monkeypatch.setattr(sub_module, "AgentLoop", _Loop)
    return captured


def _agent(tmp_path: Path, **kwargs: Any) -> SubAgent:
    return SubAgent(
        _OkProvider(),
        engine=EngineContainer.default(workspace_root=str(tmp_path)),
        max_iterations=2,
        **kwargs,
    )


async def test_write_allowlist_param_reaches_run_context(tmp_path: Path, capture_loop: list[RunContext | None]) -> None:
    agent = _agent(tmp_path, write_allowlist=["src"])
    result = await agent.run("do things")
    assert result.success
    assert capture_loop and capture_loop[0] is not None
    assert capture_loop[0].metadata["write_allowlist"] == ["src"]


async def test_metadata_forgery_cannot_inject_allowlist(tmp_path: Path, capture_loop: list[RunContext | None]) -> None:
    """用户 metadata 伪造 write_allowlist 被 reserved 过滤——键不出现。"""
    agent = _agent(tmp_path, metadata={"write_allowlist": ["evil"]})
    result = await agent.run("do things")
    assert result.success
    assert capture_loop and capture_loop[0] is not None
    assert "write_allowlist" not in capture_loop[0].metadata


async def test_param_wins_over_metadata_forgery(tmp_path: Path, capture_loop: list[RunContext | None]) -> None:
    agent = _agent(tmp_path, write_allowlist=["src"], metadata={"write_allowlist": ["evil"]})
    result = await agent.run("do things")
    assert result.success
    assert capture_loop and capture_loop[0] is not None
    assert capture_loop[0].metadata["write_allowlist"] == ["src"]
