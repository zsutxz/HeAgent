"""Story 51-7：脚本步骤在 /goal 推进链上的接线（CLI 宿主端，两阶段 A 语义）。

覆盖：`executor_mode: script` 步骤真的被 ScriptRuntime 执行；只读操作同步作答；动作请求
在脚本返回后由宿主按序**提交**（checkpoint / decision 落步骤证据、validate 走 51-4 求值器）；
不可兑现的声明（未知门、未声明步骤、请求变更步骤顺序）当场显性失败；产物照走结构化完成门。
合成包建在 tmp skills 根，不依赖本机 `.heagent/skills`。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from heagent.cli.goal import _goal_runner
from heagent.config import reset_settings
from heagent.goal.application import resolve_bound_workflow, restore_runner


def _make_script_package(
    cwd: Path,
    skill_id: str,
    script_body: str,
    *,
    steps: int = 1,
    step_metadata: str = "output: report",
) -> Path:
    """合成一个（默认单步）脚本执行器的 workflow 包。"""
    root = cwd / ".heagent" / "skills" / skill_id
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        f"---\ncanonical_id: {skill_id}\nname: {skill_id}\ndescription: synthetic script package\n---\n\n# pkg\n",
        encoding="utf-8",
    )
    (root / "scripts" / "script.py").write_text(script_body, encoding="utf-8")
    blocks: list[str] = []
    for index in range(1, steps + 1):
        metadata = ["input: user intent" if index == 1 else "input: report", step_metadata]
        if index == 1:
            metadata.append("executor_mode: script")
            metadata.append("script_resource: script.py")
        blocks.append("\n".join([f"## Step {index:02d}: phase-{index}", *metadata]) + f"\n\nDo phase {index}.\n")
    (root / "workflow.md").write_text(
        "---\n"
        f"name: {skill_id}-flow\n"
        "entrypoint: goal\n"
        "on_create: persist_goal_identity\n"
        "---\n\n"
        "# script workflow\n\n" + "\n".join(blocks),
        encoding="utf-8",
    )
    return root


def _goal_dir(cwd: Path) -> Path:
    goal_id = (cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    return cwd / "_he-output" / "goals" / goal_id


async def _failure_reason(cwd: Path, skill_id: str) -> str:
    """读回 Runner 状态，取步骤失败 / 阻断的理由（跨进程可见的持久化事实）。"""
    goal_dir = _goal_dir(cwd)
    workflow = resolve_bound_workflow(goal_dir, skill_id)
    runner = await restore_runner(workflow, goal_dir)
    return runner.state.reason


async def _acceptance_evidence(cwd: Path, skill_id: str) -> list[str]:
    goal_dir = _goal_dir(cwd)
    workflow = resolve_bound_workflow(goal_dir, skill_id)
    runner = await restore_runner(workflow, goal_dir)
    return list(runner.state.acceptance_evidence)


@pytest.fixture()
def goal_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "_he-output" / "goals").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _use(monkeypatch: pytest.MonkeyPatch, skill_id: str) -> None:
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", skill_id)
    reset_settings()


@pytest.mark.asyncio
async def test_script_step_runs_and_persists_declared_output(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        "async def build_workflow(goal):\n"
        "    intent = await goal.input('user intent')\n"
        "    return 'scripted:' + str(intent)\n",
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new run the scripted step")

    artifact = _goal_dir(goal_cwd) / "step-01-phase-1.md"
    assert artifact.is_file()
    assert artifact.read_text(encoding="utf-8").startswith("scripted:")
    assert "status=completed" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_script_checkpoint_and_decision_become_step_evidence(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        "async def build_workflow(goal):\n"
        "    await goal.checkpoint('before design')\n"
        "    await goal.decision('storage', value='sqlite', note='local only')\n"
        "    return 'done'\n",
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new declare a checkpoint and a decision")

    assert "status=completed" in capsys.readouterr().err
    # 提交阶段把声明落进步骤证据；Runner 收尾时随 checkpoint 持久化（AD-1）。
    evidence = await _acceptance_evidence(goal_cwd, "he-scripted")
    assert any(line == "script-checkpoint: before design" for line in evidence)
    assert any(line.startswith("script-decision: storage = sqlite") for line in evidence)


@pytest.mark.asyncio
async def test_script_cannot_reorder_declared_steps(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        "async def build_workflow(goal):\n    await goal.step('step-02-phase-2.md')\n    return 'unreachable'\n",
        steps=2,
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new try to jump a step")

    err = capsys.readouterr().err
    assert "status=failed" in err
    assert not (_goal_dir(goal_cwd) / "step-01-phase-1.md").exists()
    reason = await _failure_reason(goal_cwd, "he-scripted")
    assert "the Runner owns step order" in reason


@pytest.mark.asyncio
async def test_script_validate_rejects_an_unregistered_gate(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        "async def build_workflow(goal):\n    await goal.validate('not-a-real-gate')\n    return 'unreachable'\n",
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new request an unknown gate")

    assert "status=failed" in capsys.readouterr().err
    assert "unknown quality gate" in await _failure_reason(goal_cwd, "he-scripted")


@pytest.mark.asyncio
async def test_script_validate_runs_a_registered_gate(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        "async def build_workflow(goal):\n    await goal.validate('git-changes')\n    return 'done'\n",
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new validate git changes")

    # tmp 工作区不是 Git 仓库 ⇒ 无变更证据 ⇒ 门未过 ⇒ 步骤 BLOCKED（不是 Completed）。
    err = capsys.readouterr().err
    assert "status=blocked" in err
    reason = await _failure_reason(goal_cwd, "he-scripted")
    assert "git-changes" in reason


@pytest.mark.asyncio
async def test_script_step_cannot_bypass_a_declared_gate(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        "async def build_workflow(goal):\n    return 'no required section here'\n",
        step_metadata="output: report\nvalidation: section: 结论",
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new script output must satisfy the gate")

    err = capsys.readouterr().err
    assert "quality gate failed" in err
    assert "status=blocked" in err
