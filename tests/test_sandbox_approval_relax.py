"""期二 D53-2：审批降级（容器档生效）接入 ``PolicyEngine`` 的判据（Story 53-4）。

冻结决策见 `_bmad-output/epics/epic-53-容器沙箱档周期/stories/53-4-approval-relaxation-container.md`：
只对真正进沙箱的路径放松（D-53-4-1）、后端必须可用（D-53-4-2）、未知即不放松（D-53-4-3）、
不绕过沙箱授权（D-53-4-4）、显性留痕（D-53-4-5）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from heagent.engine.container import EngineContainer
from heagent.engine.context import RunContext
from heagent.engine.policy import PolicyEngine, ToolExecutionMode
from heagent.pub.types import ToolAnnotations, ToolCall, ToolSchema
from heagent.tools.sandbox.contracts import SandboxTier


class _Runner:
    """最小 runner 替身：只需 ``tier`` 与 ``available`` 两个读取面。"""

    def __init__(self, tier: SandboxTier, *, available: bool = True) -> None:
        self.tier = tier
        self.available = available


def _shell_call() -> ToolCall:
    return ToolCall(id="tc-shell", name="shell", arguments={"command": "echo hi"})


def _context(tmp_path: Path, *, sandboxed: bool = True, approved: bool = False) -> RunContext:
    metadata: dict[str, object] = {}
    if sandboxed:
        metadata["sandboxed_tools"] = ["shell"]
    if approved:
        metadata["approved_tools"] = ["shell"]
    return RunContext(workspace_root=str(tmp_path), metadata=metadata)


def _policy(
    tmp_path: Path,
    *,
    tier: SandboxTier | None = SandboxTier.CONTAINER,
    available: bool = True,
    with_provider: bool = True,
    provider: object | None = None,
    approval_tools: list[str] | None = None,
    sandbox_tools: list[str] | None = None,
    **kwargs: object,
) -> PolicyEngine:
    init: dict[str, object] = {
        "workspace_root": str(tmp_path),
        "approval_tools": approval_tools if approval_tools is not None else ["shell"],
        "sandbox_tools": sandbox_tools if sandbox_tools is not None else ["shell"],
        **kwargs,
    }
    if with_provider:
        runner = provider if provider is not None else _Runner(tier or SandboxTier.CONTAINER, available=available)
        init["sandbox_runner_provider"] = lambda: runner
    return PolicyEngine(**init)  # type: ignore[arg-type]


class TestRelaxationHappyPath:
    def test_container_tier_relaxes_approval(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """判据 1：容器档 + 后端可用 + shell 进沙箱 ⇒ 免审批，但打 WARNING 留痕。"""
        policy = _policy(tmp_path)
        with caplog.at_level(logging.WARNING, logger="heagent.engine.policy"):
            verdict = policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path))

        assert verdict.mode is not ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.mode is ToolExecutionMode.SANDBOX_REQUIRED
        assert verdict.approval_relaxed is True
        assert "approval relaxed by container sandbox" in verdict.reason
        assert any("relaxed approval for 'shell'" in rec.message for rec in caplog.records)

    def test_relaxed_still_requires_sandbox_grant(self, tmp_path: Path) -> None:
        """判据 1b / D-53-4-4：放松审批不等于放松沙箱授权。"""
        policy = _policy(tmp_path)
        verdict = policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path, sandboxed=False))

        assert verdict.mode is ToolExecutionMode.SANDBOX_REQUIRED
        assert verdict.approval_relaxed is True
        assert "requires sandbox" in verdict.reason


class TestNoRelaxation:
    @pytest.mark.parametrize("tier", [SandboxTier.PASSTHROUGH, SandboxTier.JOB, SandboxTier.FIREJAIL])
    def test_weak_tiers_keep_approval(self, tmp_path: Path, tier: SandboxTier) -> None:
        """判据 2 / NFR-2：弱后端一律维持原审批要求。"""
        policy = _policy(tmp_path, tier=tier)
        verdict = policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path))

        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.approval_relaxed is False

    def test_degraded_container_keeps_approval(self, tmp_path: Path) -> None:
        """判据 3 / D-53-4-2：容器档不可用会 fallback 宿主执行，不得放松。"""
        policy = _policy(tmp_path, tier=SandboxTier.CONTAINER, available=False)
        verdict = policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path))

        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.approval_relaxed is False

    def test_without_provider_keeps_approval(self, tmp_path: Path) -> None:
        """判据 4：未接线 provider（既有直接构造）行为逐字节不变。"""
        policy = _policy(tmp_path, with_provider=False)
        verdict = policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path))

        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.approval_relaxed is False

    def test_provider_failure_keeps_approval(self, tmp_path: Path) -> None:
        """判据 5 / D-53-4-3：读后端状态失败 ⇒ fail-closed 维持审批。"""

        def _boom() -> _Runner:
            raise RuntimeError("runner state unavailable")

        policy = _policy(tmp_path, provider=_boom)
        verdict = policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path))

        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.approval_relaxed is False

    def test_host_side_tool_keeps_approval(self, tmp_path: Path) -> None:
        """判据 6 / D-53-4-1：宿主执行面（file_write）与容器无关，永不放松。"""
        policy = _policy(tmp_path, approval_tools=["file_write"], sandbox_tools=["shell"])
        call = ToolCall(id="tc-write", name="file_write", arguments={"path": "notes.txt", "content": "x"})
        verdict = policy.evaluate_tool_call(call, context=_context(tmp_path))

        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.approval_relaxed is False

    def test_mcp_tool_keeps_approval(self, tmp_path: Path) -> None:
        """判据 7 / D-53-4-1：MCP stdio 尚未进容器（D53-1），不得放松。"""
        policy = _policy(
            tmp_path,
            approval_tools=[],
            sandbox_tools=["srv__do"],
            approval_mcp_tools=True,
            sandbox_mcp_tools=True,
        )
        call = ToolCall(id="tc-mcp", name="srv__do", arguments={})
        schema = ToolSchema(name="srv__do", description="mcp", parameters={}, annotations=ToolAnnotations())
        verdict = policy.evaluate_tool_call(call, context=_context(tmp_path), schema=schema)

        assert verdict.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert verdict.approval_relaxed is False


class TestAlreadyGrantedUnaffected:
    def test_granted_approval_is_not_marked_relaxed(self, tmp_path: Path) -> None:
        """判据 8：审批已授权时走既有路径，不冒充「放松」。"""
        policy = _policy(tmp_path)
        verdict = policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path, approved=True))

        assert verdict.mode is ToolExecutionMode.SANDBOX_REQUIRED
        assert verdict.approval_relaxed is False


class TestEngineWiring:
    def test_engine_container_wires_provider_lazily(self, tmp_path: Path) -> None:
        """判据 9：装配层把 provider 接到 executor.sandbox_runner（惰性读，可感知替换）。"""
        container = EngineContainer(workspace_root=str(tmp_path), command_runner=_Runner(SandboxTier.CONTAINER))
        container.policy.approval_tools = {"shell"}
        container.policy.sandbox_tools = {"shell"}

        assert container.policy.sandbox_runner_provider is not None
        assert container.policy.sandbox_runner_provider() is container.executor.sandbox_runner

        relaxed = container.policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path))
        assert relaxed.approval_relaxed is True

        # 运行期换成弱后端 ⇒ 立刻不再放松（证明是惰性读而非构造期快照）
        container.executor.sandbox_runner = _Runner(SandboxTier.PASSTHROUGH)
        weak = container.policy.evaluate_tool_call(_shell_call(), context=_context(tmp_path))
        assert weak.mode is ToolExecutionMode.APPROVAL_REQUIRED
        assert weak.approval_relaxed is False
