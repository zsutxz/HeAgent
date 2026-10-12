"""Story 51-7：脚本步骤在 /goal 推进链上的接线（CLI 宿主 + Runner 的 A1/A2 端口）。

覆盖：`executor_mode: script` 步骤真的被 ScriptRuntime 执行；只读操作同步作答；动作请求在
脚本返回后由宿主按序**提交**（checkpoint / decision 落步骤证据、validate 走 51-4 求值器、
step / parallel 交给 Runner 执行后续**声明**步骤）；不可兑现的声明（未知门、未声明步骤名、
自指）当场显性失败；已完成的声明步骤幂等跳过；产物照走结构化完成门。
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
    *,
    scripts: dict[int, str],
    steps: int = 1,
    step_metadata: str = "output: report",
) -> Path:
    """合成 workflow 包；``scripts`` 给出**哪些步骤**用脚本执行器及其脚本正文。

    未出现在 ``scripts`` 里的步骤保持声明式 ``subagent``（本文件不使用——它们需要 provider）。
    """
    root = cwd / ".heagent" / "skills" / skill_id
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: synthetic script package\n---\n\n# pkg\n",
        encoding="utf-8",
    )
    (root / "meta.yaml").write_text(f"canonical_id: {skill_id}\n", encoding="utf-8")
    blocks: list[str] = []
    for index in range(1, steps + 1):
        metadata = ["input: user intent" if index == 1 else "input: report", step_metadata]
        if index in scripts:
            resource = f"step-{index}.py"
            (root / "scripts" / resource).write_text(scripts[index], encoding="utf-8")
            metadata.append("executor_mode: script")
            metadata.append(f"script_resource: {resource}")
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


async def _runner_state(cwd: Path, skill_id: str):
    goal_dir = _goal_dir(cwd)
    workflow = resolve_bound_workflow(goal_dir, skill_id)
    return (await restore_runner(workflow, goal_dir)).state


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
        scripts={
            1: "async def build_workflow(goal):\n"
            "    intent = await goal.input('user intent')\n"
            "    return 'scripted:' + str(intent)\n"
        },
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
        scripts={
            1: "async def build_workflow(goal):\n"
            "    await goal.checkpoint('before design')\n"
            "    await goal.decision('storage', value='sqlite', note='local only')\n"
            "    return 'done'\n"
        },
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new declare a checkpoint and a decision")

    assert "status=completed" in capsys.readouterr().err
    # 提交阶段把声明落进步骤证据；Runner 收尾时随 checkpoint 持久化（AD-1）。
    state = await _runner_state(goal_cwd, "he-scripted")
    assert "script-checkpoint: before design" in state.acceptance_evidence
    assert any(line.startswith("script-decision: storage = sqlite") for line in state.acceptance_evidence)


@pytest.mark.asyncio
async def test_script_declares_a_follow_up_step_that_runs(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A1 + A2：脚本声明的后续**声明**步骤由 Runner 执行——**且真的选择了它**。

    场景刻意让声明目标**不是**正常推进的下一步（3 步里声明第 3 步、跳过第 2 步）：
    否则「按声明顺序跑下一步」也能让用例变绿，A1/A2 的存在就测不出来。
    """
    _make_script_package(
        goal_cwd,
        "he-scripted",
        steps=3,
        scripts={
            1: "async def build_workflow(goal):\n    await goal.step('step-03-phase-3.md')\n    return 'one'\n",
            3: "async def build_workflow(goal):\n    return 'three'\n",
        },
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new declare a later step")

    goal_dir = _goal_dir(goal_cwd)
    assert (goal_dir / "step-01-phase-1.md").read_text(encoding="utf-8") == "one"
    assert (goal_dir / "step-03-phase-3.md").read_text(encoding="utf-8") == "three"
    assert not (goal_dir / "step-02-phase-2.md").exists()
    state = await _runner_state(goal_cwd, "he-scripted")
    assert state.completed_steps == [0, 2]
    assert "script-step: step-03-phase-3.md" in "".join(state.acceptance_evidence)


@pytest.mark.asyncio
async def test_script_declared_step_is_idempotently_skipped(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """重复声明已完成的声明步骤：不重跑（证据只有一份），并显性回显跳过。"""
    _make_script_package(
        goal_cwd,
        "he-scripted",
        steps=3,
        scripts={
            1: "async def build_workflow(goal):\n"
            "    await goal.step('step-02-phase-2.md')\n"
            "    await goal.step('step-02-phase-2.md')\n"
            "    return 'one'\n",
            2: "async def build_workflow(goal):\n    await goal.decision('ran', value=1)\n    return 'two'\n",
        },
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new declare the same step twice")

    err = capsys.readouterr().err
    assert "skipped (idempotent)" in err
    state = await _runner_state(goal_cwd, "he-scripted")
    assert state.completed_steps == [0, 1]
    assert sum(line.startswith("script-decision: ran") for line in state.acceptance_evidence) == 1


@pytest.mark.asyncio
async def test_script_cannot_request_its_own_step(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        steps=2,
        scripts={1: "async def build_workflow(goal):\n    await goal.step('step-01-phase-1.md')\n    return 'x'\n"},
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new request itself")

    assert "status=failed" in capsys.readouterr().err
    state = await _runner_state(goal_cwd, "he-scripted")
    assert "cannot request itself" in state.reason


@pytest.mark.asyncio
async def test_script_declares_an_unknown_step(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        steps=2,
        scripts={1: "async def build_workflow(goal):\n    await goal.step('step-99-ghost.md')\n    return 'x'\n"},
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new request a ghost step")

    assert "status=failed" in capsys.readouterr().err
    assert "not a declared workflow step" in (await _runner_state(goal_cwd, "he-scripted")).reason


@pytest.mark.asyncio
async def test_script_validate_rejects_an_unregistered_gate(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        scripts={1: "async def build_workflow(goal):\n    await goal.validate('not-a-real-gate')\n    return 'x'\n"},
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new request an unknown gate")

    assert "status=failed" in capsys.readouterr().err
    assert "unknown quality gate" in (await _runner_state(goal_cwd, "he-scripted")).reason


@pytest.mark.asyncio
async def test_script_validate_runs_a_registered_gate(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        scripts={1: "async def build_workflow(goal):\n    await goal.validate('git-changes')\n    return 'done'\n"},
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new validate git changes")

    # tmp 工作区不是 Git 仓库 ⇒ 无变更证据 ⇒ 门未过 ⇒ 步骤 BLOCKED（不是 Completed）。
    assert "status=blocked" in capsys.readouterr().err
    assert "git-changes" in (await _runner_state(goal_cwd, "he-scripted")).reason


@pytest.mark.asyncio
async def test_script_step_cannot_bypass_a_declared_gate(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_script_package(
        goal_cwd,
        "he-scripted",
        scripts={1: "async def build_workflow(goal):\n    return 'no required section here'\n"},
        step_metadata="output: report\nvalidation: section: 结论",
    )
    _use(monkeypatch, "he-scripted")

    await _goal_runner(SimpleNamespace(), None, "new script output must satisfy the gate")

    err = capsys.readouterr().err
    assert "quality gate failed" in err
    assert "status=blocked" in err
