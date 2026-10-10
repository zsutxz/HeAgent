"""Cross-process file lock coverage for /goal state (deferred-work 高严重度项).

双进程并发（CLI cron × 手动命令、CLI × GUI）此前仅由进程内 ``asyncio.Lock``
保护，会互相覆盖 brief.md / current 指针丢进度；本文件锁定复合互斥
（:mod:`heagent.goal.mutex`：进程内快速路径 + ``.heagent/goal.lock`` 文件锁，
台账 A32② 起由变更内核自持）的对外语义：抢占失败显性报错、无争用时行为不变、
锁文件残留无害、同 task 重入不排队、并发临界区串行化。
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import heagent.cli.goal as cli_goal
from heagent.cli.goal import _goal_runner
from heagent.goal import mutex as goal_mutex
from heagent.pub.persist import file_lock

_WORKFLOW_MD = (
    "---\nname: test-development\nentrypoint: goal\non_create: persist_goal_identity\n"
    "step_executor: subagent\n"
    "prompt_template: templates/prompt.md\ngate_template: templates/gate.md\n---\n\nworkflow instructions\n\n"
    "## Step 01: plan\ninput: user intent, existing project context\n"
    "output: requirements brief\ncheckpoint: true\n\nplan the story\n\n"
    "## Step 02: build\ninput: requirements brief\noutput: implementation\ncheckpoint: true\n\nbuild the story\n"
)


@pytest.fixture()
def declarative_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_workflow_root: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    (goal_workflow_root / "workflow.md").write_text(_WORKFLOW_MD, encoding="utf-8")
    (tmp_path / "_he-output" / "goals").mkdir(parents=True)
    # 缩短锁等待，测试不必真等 5s 超时。
    monkeypatch.setattr(goal_mutex, "GOAL_LOCK_TIMEOUT", 0.2)
    return tmp_path


@pytest.fixture()
def step_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(prompt)
        return SimpleNamespace(success=True, output=f"output-{len(calls)}")

    monkeypatch.setattr("heagent.cli.goal._goal_session", run_step)
    return calls


@pytest.mark.asyncio
async def test_held_lock_fails_loudly_without_running_step(
    declarative_cwd: Path,
    step_spy: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """另一进程持锁时：显性失败、不执行任何步骤、不落任何 goal 状态。"""
    async with file_lock(goal_mutex.GOAL_LOCK_PATH):
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


# ---- 内核自锁语义（台账 A32②）：重入与串行化 ------------------------------------


@pytest.mark.asyncio
async def test_goal_mutex_is_reentrant_within_one_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同 task 重入：外层持锁再进只增计数，不排队文件锁、不死锁。

    这是「CLI 外层组合持锁 + 内核三写方法自锁」共存的前提。变异体：撤重入分支
    ⇒ 内层在 ``_auto_lock`` 上永久阻塞，2s 后本用例以显性信息失败（而非挂起测试进程）。
    """
    monkeypatch.chdir(tmp_path)
    observed: list[bool] = []

    async def scenario() -> None:
        # 嵌套两次获取即重入本体——写成单 with 双上下文语义逐字相同（同 task 顺序获取）。
        async with goal_mutex.goal_mutex(), goal_mutex.goal_mutex():
            observed.append(goal_mutex._auto_lock.locked())

    task = asyncio.create_task(scenario())
    done, _pending = await asyncio.wait({task}, timeout=2.0)
    assert done, "goal_mutex 同 task 重入死锁（变异体：撤重入分支即此状）"
    assert observed == [True]
    assert goal_mutex._auto_lock.locked() is False


@pytest.mark.asyncio
async def test_concurrent_critical_sections_serialize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """两 task 并发进临界区：严格串行（域锁是互斥，不是计数器）。"""
    monkeypatch.chdir(tmp_path)
    inside = 0
    max_inside = 0

    async def section() -> None:
        nonlocal inside, max_inside
        async with goal_mutex.goal_mutex():
            inside += 1
            max_inside = max(max_inside, inside)
            await asyncio.sleep(0.01)
            inside -= 1

    await asyncio.gather(section(), section())
    assert max_inside == 1
