"""运行产物落盘根（``RunContext.state_root``）与围栏根解耦的判据。

A41 物理隔离的后续切片：Story 在独立 git worktree 里跑时，围栏根
（``workspace_root``）钉 worktree —— 写集审计基线与沙箱会话目录都随之；但工具审计是
**进程级持久台账**，必须与 run 快照、ledger 同根（主工作区），否则随 worktree 移除
一并丢失。钉住四条：

1. 围栏根换到 worktree 时，审计落容器根；
2. 未隔离时二者同源（行为逐字不变）；
3. 显式 ``state_root`` 可覆盖（如库消费者自建落盘根）；
4. 鸭子契约的替身（只带 ``workspace_root`` / 只带 ``run_id``）不抛错。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from heagent.engine.container import EngineContainer
from heagent.engine.executor import ToolExecutor
from heagent.engine.policy import PolicyEngine
from heagent.pub.audit import AUDIT_DIRNAME, read_entries, resolve_audit_path
from heagent.pub.types import ToolCall


class _AllowAllGuard:
    """``SafetyGuard.check`` 的放行替身（本文件只关心审计落点，不测 guard 语义）。"""

    def check(self, call: ToolCall) -> None:
        return None


async def _handler(call: ToolCall) -> object:
    await asyncio.sleep(0)
    return "done"


async def _run_tool(run_context: object) -> None:
    call = ToolCall(id="1", name="shell", arguments={"command": "echo hi"})
    await ToolExecutor().execute(
        call=call,
        verdict=PolicyEngine().evaluate_tool_call(call),
        guard=_AllowAllGuard(),
        handler=_handler,
        run_context=run_context,  # type: ignore[arg-type]
    )


def _audit_entries(root: Path) -> list[dict[str, object]]:
    return read_entries(resolve_audit_path(root=root))


async def test_worktree_fence_keeps_audit_in_container_root(tmp_path: Path) -> None:
    """隔离场景：围栏在 worktree，审计仍落主工作区（worktree 里不留审计目录）。"""
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    worktree.mkdir()

    engine = EngineContainer(workspace_root=str(main))
    context = engine.create_run_context(workspace_root=str(worktree))

    assert context.workspace_root == str(worktree.resolve())
    assert context.state_root == str(main.resolve())

    await _run_tool(context)

    entries = _audit_entries(main)
    assert [entry["tool"] for entry in entries] == ["shell"]
    assert not (worktree / ".heagent" / AUDIT_DIRNAME).exists(), "worktree 内不得留审计台账（会随移除丢失）"


async def test_audit_root_matches_fence_when_not_isolated(tmp_path: Path) -> None:
    """未隔离：产物根与围栏根同源（既有行为逐字不变）。"""
    engine = EngineContainer(workspace_root=str(tmp_path))
    context = engine.create_run_context()

    assert context.state_root == context.workspace_root == str(tmp_path.resolve())

    await _run_tool(context)
    assert len(_audit_entries(tmp_path)) == 1


async def test_explicit_state_root_wins(tmp_path: Path) -> None:
    """显式 ``state_root`` 优先于容器根（自建落盘根的库消费者）。"""
    engine = EngineContainer(workspace_root=str(tmp_path / "main"))
    explicit = tmp_path / "ledger-root"

    context = engine.create_run_context(workspace_root=str(tmp_path / "fence"), state_root=str(explicit))

    assert context.state_root == str(explicit.resolve())
    await _run_tool(context)
    assert len(_audit_entries(explicit)) == 1


async def test_duck_typed_context_falls_back_without_state_root(tmp_path: Path) -> None:
    """鸭子契约：无 ``state_root`` 的替身回退 ``workspace_root``；只有 ``run_id`` 也不抛错。"""

    class _NoStateRoot:
        run_id = "r-1"
        session_id = "s-1"
        workspace_root = str(tmp_path)

    class _SoloRunId:
        run_id = "r-2"

    await _run_tool(_NoStateRoot())
    assert len(_audit_entries(tmp_path)) == 1

    await _run_tool(_SoloRunId())  # 落 cwd 口径，不断言位置，只钉「不抛错」
