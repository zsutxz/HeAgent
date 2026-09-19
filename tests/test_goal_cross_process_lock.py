"""Cross-process file lock coverage for /goal state (deferred-work 高严重度项).

双进程并发（CLI cron × 手动命令、CLI × GUI）此前仅由进程内 ``asyncio.Lock``
保护，会互相覆盖 require.md / current 指针丢进度；本文件锁定复合互斥
（``_goal_mutex``：进程内快速路径 + ``.heagent/goal.lock`` 文件锁）的对外语义：
抢占失败显性报错、无争用时行为不变、锁文件残留无害。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import heagent.cli_goal as cli_goal
from heagent.cli_goal import _goal_runner
from heagent.persist import file_lock

_WORKFLOW_MD = (
    "---\nname: test-development\nentrypoint: goal\non_create: persist_goal_identity\n"
    "step_executor: subagent\n---\n\nworkflow instructions\n\n"
    "## Step 01: plan\ninput: user intent, existing project context\n"
    "output: requirements brief\ncheckpoint: true\n\nplan the story\n\n"
    "## Step 02: build\ninput: requirements brief\noutput: implementation\ncheckpoint: true\n\nbuild the story\n"
)


@pytest.fixture()
def declarative_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    workflow_root = tmp_path / ".heagent" / "workflows"
    workflow_root.mkdir(parents=True)
    (workflow_root / "workflow.md").write_text(_WORKFLOW_MD, encoding="utf-8")
    (tmp_path / "_he-output" / "goals").mkdir(parents=True)
    # 缩短锁等待，测试不必真等 5s 超时。
    monkeypatch.setattr(cli_goal, "_GOAL_LOCK_TIMEOUT", 0.2)
    return tmp_path


@pytest.fixture()
def step_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(prompt)
        return SimpleNamespace(success=True, output=f"output-{len(calls)}")

    monkeypatch.setattr("heagent.cli_goal._goal_session", run_step)
    return calls


@pytest.mark.asyncio
async def test_held_lock_fails_loudly_without_running_step(
    declarative_cwd: Path,
    step_spy: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """另一进程持锁时：显性失败、不执行任何步骤、不落任何 goal 状态。"""
    async with file_lock(cli_goal._GOAL_LOCK_PATH):
        await _goal_runner(SimpleNamespace(), None, "new build a todo app")

    err = capsys.readouterr().err
    assert "另一进程正在推进同一 goal" in err
    assert step_spy == []
    # 整个 dispatch 都在锁内：连 current 指针都不应被创建。
    assert not (declarative_cwd / "_he-output" / "goals" / "current").exists()


@pytest.mark.asyncio
async def test_uncontended_goal_runs_and_lock_file_persists_harmlessly(
    declarative_cwd: Path,
    step_spy: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """无争用：行为与加锁前一致；锁文件刻意残留但不阻塞后续推进。"""
    await _goal_runner(SimpleNamespace(), None, "new build a todo app")
    err = capsys.readouterr().err
    assert "另一进程" not in err
    assert len(step_spy) == 1
    assert (declarative_cwd / ".heagent" / "goal.lock").exists()

    await _goal_runner(SimpleNamespace(), None, "resume confirmed scope")
    assert len(step_spy) == 2  # 残留的 0 字节锁文件不阻塞下一次推进
