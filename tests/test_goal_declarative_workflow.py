"""Declarative /goal routing and checkpoint recovery contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import heagent.cli as cli
import heagent.cli_goal as cli_goal
from heagent.cli_goal import (
    _goal_cron_advance,
    _goal_declarative_runner,
    _goal_declarative_workflow,
    _goal_project_id,
    _goal_runner,
)
from heagent.cron.jobs import JobStore
from heagent.config import reset_settings
from heagent.engine import (
    WorkflowGateError,
    WorkflowRunResult,
    WorkflowRunner,
    required_sections,
)
from heagent.engine.workflow import WorkflowCheckpointStore, WorkflowStatus
from heagent.memory.skill_packages import WorkflowResource, WorkflowStepResource


@pytest.fixture()
def declarative_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    workflow_root = tmp_path / ".heagent" / "workflows"
    workflow_root.mkdir(parents=True)
    (workflow_root / "workflow.md").write_text(
        "---\nname: test-development\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\nworkflow instructions\n\n"
        "## Questionnaire\n\nname: game-product-decisions\napplies_when: game\n\n"
        "### Q1 对手类型\nid: opponent_type\noptions: A 本地双人|B 人机|C 两者\n\n"
        "### Q2 平台\nid: platform\noptions: 桌面（操作系统）|浏览器|终端|其他\n\n"
        "### Q3 规则\nid: rules\noptions: 标准完整规则|简化 MVP\n\n"
        "### Q4 首版附加能力\nid: launch_features\noptions: 无|重新开始\n\n"
        "### Q5 基础单难度是否可接受\nid: ai_single_difficulty\nwhen: opponent_type=B 人机|C 两者\n\n"
        "### Q6 电脑每步最长思考时间（秒）\n"
        "id: ai_think_seconds\ntype: number\nminimum: 0\nwhen: opponent_type=B 人机|C 两者\n"
        "\n"
        "## Step 01: plan\ninput: user intent, existing project context\n"
        "output: requirements brief, story breakdown\ncheckpoint: true\n\nplan the story\n\n"
        "## Step 02: build\ninput: requirements brief\noutput: implementation\ncheckpoint: true\n\nbuild the story\n",
        encoding="utf-8",
    )
    (tmp_path / "_he-output" / "goals").mkdir(parents=True, exist_ok=True)
    (tmp_path / "QUESTIONNAIRE.md").write_text(
        "# Questionnaire\n\nname: game-product-decisions\napplies_when: game\n"
        "include_in_step: step-01-plan.md\n\n"
        "### Q1 对手类型\nid: opponent_type\noptions: A 本地双人|B 人机|C 两者\n\n"
        "### Q2 平台\nid: platform\noptions: 桌面（操作系统）|浏览器|终端|其他\n\n"
        "### Q3 规则\nid: rules\noptions: 标准完整规则|简化 MVP\n\n"
        "### Q4 首版附加能力\nid: launch_features\noptions: 无|重新开始\n\n"
        "### Q5 基础单难度是否可接受\nid: ai_single_difficulty\nwhen: opponent_type=B 人机|C 两者\n\n"
        "### Q6 电脑每步最长思考时间（秒）\n"
        "id: ai_think_seconds\ntype: number\nminimum: 0\nwhen: opponent_type=B 人机|C 两者\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def successful_step(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(prompt)
        return SimpleNamespace(success=True, output=f"output-{len(calls)}")

    monkeypatch.setattr("heagent.cli_goal._goal_session", run_step)
    return calls


@pytest.mark.asyncio
async def test_declarative_commands_checkpoint_and_no_duplicate_completion(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new ship   the workflow")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    goal_document = goal_dir / "require.md"
    assert goal_document.exists()
    goal_text = goal_document.read_text(encoding="utf-8")
    assert "## 原始需求（Original Request）" in goal_text
    assert "ship   the workflow" in goal_text
    assert "## 总结的需求（Derived Requirements）" in goal_text
    assert not (goal_dir / "GOAL.md").exists()
    assert not (goal_dir / "ORIGINAL_REQUEST.md").exists()
    assert not (goal_dir / "goal.txt").exists()
    assert (goal_dir / "step-01-plan.md").read_text(encoding="utf-8") == "output-1"
    assert cli_goal._goal_document_title(goal_text) == "ship the workflow"
    assert len(successful_step) == 1
    assert "## user intent\nship   the workflow" in successful_step[0]
    assert "## existing project context" in successful_step[0]
    assert f"Project output root: {declarative_cwd / '_he-output'}" in successful_step[0]
    checkpoints = await WorkflowCheckpointStore(str(goal_dir / "checkpoints")).list_checkpoints(goal_id=goal_id)
    assert len(checkpoints) == 1
    assert checkpoints[0].completed_steps == [0]
    assert checkpoints[0].active_skill == "test-development"

    await _goal_runner(SimpleNamespace(), None, "status")
    assert "declarative progress: 1/2" in capsys.readouterr().err

    await _goal_runner(SimpleNamespace(), None, "resume confirmed: use the requested scope")
    assert len(successful_step) == 2
    assert "## requirements brief\noutput-1" in successful_step[1]
    assert "## user responses" in successful_step[1]
    assert "confirmed: use the requested scope" in successful_step[1]
    persisted_goal = goal_document.read_text(encoding="utf-8")
    assert "## 用户补充（User Responses）" in persisted_goal
    assert "confirmed: use the requested scope" in persisted_goal
    persisted = await WorkflowCheckpointStore(str(goal_dir / "checkpoints")).list_checkpoints(goal_id=goal_id)
    assert len({checkpoint.checkpoint_id for checkpoint in persisted}) == len(persisted)

    await _goal_runner(SimpleNamespace(), None, "run")
    assert len(successful_step) == 2

    await _goal_runner(SimpleNamespace(), None, "audit")
    assert "audit unavailable without engine" in capsys.readouterr().err


def test_goal_project_id_uses_english_letters_without_numeric_suffix() -> None:
    assert _goal_project_id("继续开发 MCP 安全功能 2026") == "continue-development-mcp-security-feature"
    assert _goal_project_id("Build MCP security 2026") == "build-mcp-security"


@pytest.mark.asyncio
async def test_declarative_resume_advances_once_under_goal_lock(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new locked resume workflow")
    observed: list[bool] = []
    original = cli_goal._goal_declarative_advance

    async def observe_advance(provider, engine, workflow):
        observed.append(cli_goal._goal_auto_lock.locked())
        return await original(provider, engine, workflow)

    monkeypatch.setattr(cli_goal, "_goal_declarative_advance", observe_advance)
    await _goal_runner(SimpleNamespace(), None, "resume")

    assert len(successful_step) == 2
    assert observed == [True]


@pytest.mark.asyncio
async def test_declarative_auto_uses_same_completed_checkpoint(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new scheduled workflow")
    await _goal_runner(SimpleNamespace(), None, "pause")
    await _goal_runner(SimpleNamespace(), None, "resume")
    await _goal_runner(SimpleNamespace(), None, "next")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    store = JobStore(str(declarative_cwd / "jobs.json"))
    await _goal_runner(SimpleNamespace(), None, "auto", cron_store=store)

    await _goal_cron_advance(SimpleNamespace(), None, store, goal_id)
    assert len(successful_step) == 2
    assert store.list_jobs() == []


@pytest.mark.asyncio
async def test_declarative_goal_rejects_unknown_workflow_declarations(
    declarative_cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        "---\nname: invalid\nentrypoint: unsupported\n---\n\n## Step 01: plan\noutput: plan\n\nPlan the work.\n",
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new rejected")

    assert "unsupported goal workflow entrypoint" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_goal_requires_workflow_instead_of_falling_back_to_legacy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    await _goal_runner(SimpleNamespace(), None, "legacy goal")
    assert "workflow.md is required" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_declarative_resume_retries_a_blocked_step(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new blocked workflow")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    workflow = _goal_declarative_workflow()
    assert workflow is not None
    runner = await _goal_declarative_runner(workflow, goal_dir)
    runner.state = runner.state.model_copy(update={"status": WorkflowStatus.BLOCKED, "reason": "missing evidence"})
    await runner.persist_state()

    await _goal_runner(SimpleNamespace(), None, "resume")

    resumed = await _goal_declarative_runner(workflow, goal_dir)
    assert resumed.state.status is WorkflowStatus.COMPLETED
    assert resumed.state.completed_steps == [0, 1]


@pytest.mark.asyncio
async def test_declarative_next_rejects_waiting_checkpoint(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new checkpoint workflow")
    await _goal_runner(SimpleNamespace(), None, "next")
    assert len(successful_step) == 1
    assert "use /goal resume first" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_final_checkpoint_persists_completed_state(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        "---\nname: final-checkpoint\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\nworkflow instructions\n\n"
        "## Step 01: finish\ninput: user intent, existing project context\n"
        "output: implementation\ncheckpoint: true\n\nfinish the story\n",
        encoding="utf-8",
    )
    await _goal_runner(SimpleNamespace(), None, "new final workflow")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    runner = await _goal_declarative_runner(_goal_declarative_workflow(), goal_dir)  # type: ignore[arg-type]
    assert runner.done
    assert runner.state.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_checkpoint_auto_mode_advances_until_completion(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\ncheckpoint_mode: auto\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new auto workflow")

    assert len(successful_step) == 2
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    runner = await _goal_declarative_runner(  # type: ignore[arg-type]
        _goal_declarative_workflow(), declarative_cwd / "_he-output" / "goals" / goal_id
    )
    assert runner.done


@pytest.mark.asyncio
async def test_checkpoint_mode_env_applies_when_workflow_omits_declaration(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOAL_CHECKPOINT_MODE", "auto")
    reset_settings()

    await _goal_runner(SimpleNamespace(), None, "new env auto workflow")

    assert len(successful_step) == 2


@pytest.mark.asyncio
async def test_workflow_checkpoint_mode_overrides_environment(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOAL_CHECKPOINT_MODE", "auto")
    reset_settings()
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\ncheckpoint_mode: prompt\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new explicit prompt workflow")

    assert len(successful_step) == 1


@pytest.mark.asyncio
async def test_checkpoint_prompt_accepts_and_advances(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    confirmations: list[bool] = []

    def confirm(_message: str, *, default: bool = False) -> bool:
        confirmations.append(default)
        return True

    monkeypatch.setattr(cli.click, "confirm", confirm)

    await _goal_runner(SimpleNamespace(), None, "new prompt workflow")

    assert len(successful_step) == 2
    assert confirmations == [False]


@pytest.mark.asyncio
async def test_checkpoint_prompt_rejection_keeps_waiting_user(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli.click, "confirm", lambda _message, default=False: False)

    await _goal_runner(SimpleNamespace(), None, "new paused workflow")

    assert len(successful_step) == 1
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    runner = await _goal_declarative_runner(
        _goal_declarative_workflow(), declarative_cwd / "_he-output" / "goals" / goal_id
    )  # type: ignore[arg-type]
    assert runner.state.status is WorkflowStatus.WAITING_USER


@pytest.mark.asyncio
async def test_invalid_checkpoint_mode_fails_workflow_load(
    declarative_cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\ncheckpoint_mode: always\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new invalid mode")

    assert "invalid checkpoint_mode 'always'" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_empty_subagent_output_fails_without_persisting_empty_artifact(
    declarative_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty_goal_session(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        del provider, engine, prompt, kwargs
        return SimpleNamespace(success=True, output="  \n")

    monkeypatch.setattr(cli_goal, "_goal_session", empty_goal_session)

    await _goal_runner(SimpleNamespace(), None, "new empty output workflow")

    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    runner = await _goal_declarative_runner(_goal_declarative_workflow(), goal_dir)  # type: ignore[arg-type]
    assert runner.state.status is WorkflowStatus.FAILED
    assert "produced empty output" in runner.state.reason
    assert not (goal_dir / "step-01-plan.md").exists()


@pytest.mark.asyncio
async def test_non_interactive_game_goal_waits_for_questionnaire(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new make a space game")

    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    runner = await _goal_declarative_runner(_goal_declarative_workflow(), goal_dir)  # type: ignore[arg-type]
    assert runner.state.status is WorkflowStatus.WAITING_USER
    assert successful_step == []
    assert "Q1 对手类型" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_resume_game_questionnaire_persists_answers_and_runs_first_step(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new make a space game")

    await _goal_runner(
        SimpleNamespace(),
        None,
        "resume Q1 对手类型：A 本地双人\nQ2 平台：浏览器\nQ3 规则：简化 MVP\nQ4 首版附加能力：重新开始",
    )

    assert len(successful_step) == 1
    assert "## questionnaire\nQ1 对手类型：A 本地双人" in successful_step[0]
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    goal_text = (declarative_cwd / "_he-output" / "goals" / goal_id / "require.md").read_text(encoding="utf-8")
    assert "## Questionnaire: game-product-decisions" in goal_text
    assert "Q4 首版附加能力：重新开始" in goal_text


@pytest.mark.asyncio
async def test_invalid_game_questionnaire_stays_waiting_for_user(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new make a space game")
    await _goal_runner(SimpleNamespace(), None, "resume Q1 对手类型：B 人机\nQ2 平台：浏览器")

    assert successful_step == []
    assert "缺少 Q3" in capsys.readouterr().err
    await _goal_runner(
        SimpleNamespace(),
        None,
        "resume Q1 对手类型：A 本地双人\nQ2 平台：浏览器\nQ3 规则：简化 MVP\nQ4 首版附加能力：联网对战",
    )
    assert successful_step == []
    assert "Q4 必须是" in capsys.readouterr().err
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    runner = await _goal_declarative_runner(
        _goal_declarative_workflow(), declarative_cwd / "_he-output" / "goals" / goal_id
    )  # type: ignore[arg-type]
    assert runner.state.status is WorkflowStatus.WAITING_USER


@pytest.mark.asyncio
async def test_interactive_ai_game_questionnaire_collects_follow_up_answers(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    answers = iter(["B 人机", "浏览器", "简化 MVP", "重新开始", "可接受", 2.5])
    monkeypatch.setattr(cli.click, "prompt", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(cli.click, "confirm", lambda *_args, **_kwargs: False)

    await _goal_runner(SimpleNamespace(), None, "new make a space game")

    assert len(successful_step) == 1
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    goal_text = (declarative_cwd / "_he-output" / "goals" / goal_id / "require.md").read_text(encoding="utf-8")
    assert "Q5 基础单难度是否可接受：可接受" in goal_text
    assert "Q6 电脑每步最长思考时间（秒）：2.5" in goal_text


@pytest.mark.asyncio
async def test_completed_game_questionnaire_is_not_recorded_twice_on_resume(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new make a space game")
    await _goal_runner(
        SimpleNamespace(),
        None,
        "resume Q1 对手类型：A 本地双人\nQ2 平台：浏览器\nQ3 规则：简化 MVP\nQ4 首版附加能力：无",
    )
    await _goal_runner(SimpleNamespace(), None, "resume continue with the current scope")

    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    goal_text = (declarative_cwd / "_he-output" / "goals" / goal_id / "require.md").read_text(encoding="utf-8")
    assert goal_text.count("## Questionnaire: game-product-decisions") == 1
    assert len(successful_step) == 2


def _real_step_one() -> tuple[str, str]:
    """Return the shipped workflow's step-01 block and its validation declaration."""
    workflow_path = Path(__file__).resolve().parents[1] / ".heagent" / "workflows" / "workflow.md"
    text = workflow_path.read_text(encoding="utf-8")
    block = text.split("## Step 01:", 1)[1].split("## Step 02:", 1)[0]
    return block, next(line for line in block.splitlines() if line.startswith("validation:"))


def test_step_one_gate_requires_the_derived_requirements_summary() -> None:
    """Step 01 is the initial analysis: it must write and return the summarized requirements."""
    block, validation = _real_step_one()
    assert required_sections(validation) == ["需求总结"]
    assert "require.md" in block
    assert "## 总结的需求（Derived Requirements）" in block
    step = WorkflowStepResource(
        index=1, name="step-01-market-research.md", instructions="", validation_rules=validation
    )
    WorkflowRunner.validate_output(step, "## 需求总结\n\n能验证的需求陈述")
    with pytest.raises(WorkflowGateError):
        WorkflowRunner.validate_output(step, "## 市场综述\n\n只有调研结论")


def test_legacy_goal_document_is_read_and_written_in_place(tmp_path: Path) -> None:
    """A goal created before the rename keeps GOAL.md as its single document."""
    goal_dir = tmp_path / "legacy-goal"
    goal_dir.mkdir()
    goal_dir.joinpath("GOAL.md").write_text(
        "---\nid: goal-legacy\ntype: goal\nstatus: planning\ntitle: 旧目标\n---\n\n"
        "# 旧目标\n\n## 原始需求（Original Request）\n\n```\n旧目标描述\n```\n\n"
        "## Epics\n\n- E1: 旧 Epic\n",
        encoding="utf-8",
    )

    assert cli_goal._goal_description(goal_dir) == "旧目标描述"
    cli_goal._goal_record_user_response(goal_dir, "继续推进")

    assert "继续推进" in cli_goal._goal_user_responses(goal_dir)
    assert not (goal_dir / "require.md").exists()


def test_cli_reexports_goal_runner_but_not_monkeypatch_seams() -> None:
    """cli.py keeps only the three self-used goal symbols; patch seams live in cli_goal."""
    assert cli._goal_runner is cli_goal._goal_runner
    assert not hasattr(cli, "_goal_session")


@pytest.mark.asyncio
async def test_declarative_auto_keeps_job_when_paused_at_checkpoint(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prompt-mode checkpoint pauses are waiting, not terminal: cron auto must survive them."""
    await _goal_runner(SimpleNamespace(), None, "new scheduled pause workflow")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    store = JobStore(str(declarative_cwd / "jobs.json"))
    await _goal_runner(SimpleNamespace(), None, "auto", cron_store=store)

    await _goal_cron_advance(SimpleNamespace(), None, store, goal_id)

    assert len(successful_step) == 1
    assert len(store.list_jobs()) == 1
    assert "paused; use /goal resume first" in capsys.readouterr().err


def test_interactive_questionnaire_skips_inactive_gap_without_reask(
    declarative_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid answer must be accepted even when the next question is inactive and a later one is active."""
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    (declarative_cwd / "QUESTIONNAIRE.md").write_text(
        "# Questionnaire\n\nname: gap-test\napplies_when: test\n\n"
        "### Q1 模式\nid: mode\noptions: A 独行|B 组队\n\n"
        "### Q2 队友\nid: teammate\nwhen: mode=B 组队\n\n"
        "### Q3 备注\nid: note\n",
        encoding="utf-8",
    )
    spec = cli_goal._goal_questionnaire_spec(declarative_cwd)
    assert spec is not None
    answers = iter(["A 独行", "ok"])
    calls: list[str] = []

    def fake_prompt(message: object, **kwargs: object) -> str:
        calls.append(str(message))
        return next(answers)

    monkeypatch.setattr(cli.click, "prompt", fake_prompt)

    questionnaire = cli_goal._goal_collect_questionnaire(spec)

    assert questionnaire is not None
    assert questionnaire.answers == {"mode": "A 独行", "note": "ok"}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_declarative_new_reports_invalid_questionnaire_configuration(
    declarative_cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed questionnaire declaration must fail loudly at /goal new, not escape."""
    (declarative_cwd / "QUESTIONNAIRE.md").write_text(
        "# Questionnaire\n\nname: broken\napplies_when: ([unclosed\n\n### Q1 模式\nid: mode\n",
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new broken questionnaire game")

    assert "declarative questionnaire configuration is invalid" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_open_question_mode_default_injects_proceed_with_default(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\nopen_question_mode: default\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new default open question workflow")

    assert len(successful_step) == 1
    assert "Open question policy:" in successful_step[0]
    assert "proceed with the recommended" in successful_step[0]
    assert "do not stop with waiting_user" in successful_step[0]


@pytest.mark.asyncio
async def test_open_question_mode_block_injects_stop_instruction(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    await _goal_runner(SimpleNamespace(), None, "new block open question workflow")

    assert len(successful_step) == 1
    assert "Open question policy:" in successful_step[0]
    assert "Stop with waiting_user" in successful_step[0]


@pytest.mark.asyncio
async def test_invalid_open_question_mode_fails_workflow_load(
    declarative_cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\nopen_question_mode: always\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new invalid open question mode")

    assert "invalid open_question_mode 'always'" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_open_question_mode_env_applies_when_workflow_omits_declaration(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOAL_OPEN_QUESTION_MODE", "default")
    reset_settings()

    await _goal_runner(SimpleNamespace(), None, "new env open question workflow")

    assert len(successful_step) == 1
    assert "do not stop with waiting_user" in successful_step[0]


@pytest.mark.asyncio
async def test_workflow_open_question_mode_overrides_environment(
    declarative_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOAL_OPEN_QUESTION_MODE", "default")
    reset_settings()
    workflow = declarative_cwd / ".heagent" / "workflows" / "workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n", "step_executor: subagent\nopen_question_mode: block\n"
        ),
        encoding="utf-8",
    )

    await _goal_runner(SimpleNamespace(), None, "new explicit block open question workflow")

    assert len(successful_step) == 1
    assert "Stop with waiting_user" in successful_step[0]


def test_step_prompt_feeds_gate_headings_to_executor(tmp_path: Path) -> None:
    """The executor must be told the exact headings the post-step gate requires."""
    validation_rules = "section: 实现摘要; section: 测试证据; section: 验证结论; 记录确切命令与结果"
    workflow = WorkflowResource(name="demo", instructions="workflow instructions", steps=[])
    prompt = cli_goal._goal_declarative_prompt(
        workflow,
        "step-07-implement-story.md",
        "demo goal",
        tmp_path,
        {"澄清的实现范围": "scope"},
        validation_rules=validation_rules,
    )
    assert "Gate requirements (hard, enforced on your final response):" in prompt
    assert required_sections(validation_rules) == ["实现摘要", "测试证据", "验证结论"]
    for section in required_sections(validation_rules):
        assert f"  - ## {section}\n" in prompt
    assert "the workflow will not advance" in prompt
    assert validation_rules in prompt


def test_step_prompt_gate_headings_satisfy_the_runner_gate(tmp_path: Path) -> None:
    """The advertised headings must be sufficient for the real (post-step) gate."""
    step = WorkflowStepResource(
        index=1,
        name="step-01-plan.md",
        instructions="",
        validation_rules="section: 实现摘要; section: 测试证据",
    )
    workflow = WorkflowResource(name="demo", instructions="workflow instructions", steps=[step])
    prompt = cli_goal._goal_declarative_prompt(
        workflow, step.name, "demo goal", tmp_path, {"user intent": "ship it"}, validation_rules=step.validation_rules
    )
    sections = required_sections(step.validation_rules)
    assert [item for item in sections if f"  - ## {item}\n" in prompt] == sections
    body = "\n\n".join(f"## {section}\n\ncontent" for section in sections)
    WorkflowRunner.validate_output(step, body)
    with pytest.raises(WorkflowGateError):
        WorkflowRunner.validate_output(step, body.replace("## 测试证据", "测试证据"))
    # The prompt itself must not satisfy the gate: the advertised headings are list items
    # there, so telling the executor about the gate never pre-approves the step output.
    with pytest.raises(WorkflowGateError):
        WorkflowRunner.validate_output(step, prompt)


def test_step_prompt_without_gate_rules_has_no_gate_block(tmp_path: Path) -> None:
    """Steps without ``section:`` rules keep the previous prompt shape."""
    workflow = WorkflowResource(name="demo", instructions="workflow instructions", steps=[])
    prompt = cli_goal._goal_declarative_prompt(
        workflow, "step-01-plan.md", "demo goal", tmp_path, {"user intent": "ship it"}
    )
    assert "Gate requirements" not in prompt
    assert "Declared validation rules (verbatim)" not in prompt


@pytest.mark.asyncio
async def test_step_iteration_budget_overrides_the_global_default(
    declarative_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step declaring `max_iterations:` must reach the SubAgent session; 0 inherits."""
    seen: list[object] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        seen.append(kwargs.get("max_iterations"))
        return SimpleNamespace(success=True, output="body")

    monkeypatch.setattr("heagent.cli_goal._goal_session", run_step)
    workflow = WorkflowResource(name="demo", instructions="", steps=[])
    goal_dir = declarative_cwd / "_he-output" / "goals" / "demo"
    goal_dir.mkdir(parents=True, exist_ok=True)
    for declared in (40, 0):
        step = WorkflowStepResource(index=1, name="step-01-plan.md", instructions="", max_iterations=declared)
        await cli_goal._goal_execute_step(
            SimpleNamespace(),
            None,
            workflow,
            "demo goal",
            goal_dir,
            {"user intent": "ship it"},
            step,
            None,
            None,
        )
    assert seen == [40, None]


def test_step_prompt_renders_duplicate_artifact_text_once(tmp_path: Path) -> None:
    """Each artifact is stored under two keys; the prompt must not carry it twice."""
    artifact = "# 市场调研报告\n\n" + "证据" * 400
    workflow = WorkflowResource(name="demo", instructions="workflow instructions", steps=[])
    prompt = cli_goal._goal_declarative_prompt(
        workflow,
        "step-07-implement-story.md",
        "demo goal",
        tmp_path,
        {"user intent": "demo", "step-01-market-research.md": artifact, "市场综述": artifact},
    )
    assert prompt.count(artifact) == 1
    assert "## step-01-market-research.md" in prompt
    assert "## 市场综述" not in prompt


@pytest.mark.asyncio
async def test_blocked_step_reports_the_way_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """BLOCKED used to be a dead end: the CLI must print how to leave it."""
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    (goal_dir / "require.md").write_text(cli_goal._goal_document("demo goal", "demo"), encoding="utf-8")
    step = WorkflowStepResource(index=1, name="step-01.md", instructions="")
    workflow = WorkflowResource(name="demo", instructions="", steps=[step])

    class StubRunner:
        def __init__(self) -> None:
            self.workflow = workflow
            self.state = SimpleNamespace(outputs={}, active_step=0, reason="gate rejected the output")

        async def run_step(self, callback: object, *, inputs: object, stories: object = None) -> WorkflowRunResult:
            return WorkflowRunResult(
                status=WorkflowStatus.BLOCKED,
                step_index=0,
                reason="step 'step-01.md' output is missing section: 实现摘要",
            )

    context = cli_goal._GoalAdvanceContext(
        runner=StubRunner(),  # type: ignore[arg-type]
        mode="auto",
        description="demo goal",
        questionnaire=None,
        questionnaire_spec=None,
        goal_dir=goal_dir,
    )

    async def prepare(prepared_workflow: object) -> tuple[None, object]:
        return None, context

    monkeypatch.setattr(cli_goal, "_goal_declarative_prepare", prepare)
    outcome = await cli_goal._goal_declarative_advance(SimpleNamespace(), None, workflow)
    err = capsys.readouterr().err
    assert "[goal] step blocked: step 'step-01.md' output is missing section: 实现摘要" in err
    assert "/goal resume" in err
    assert outcome == cli_goal._GOAL_FAILED


@pytest.mark.asyncio
async def test_typo_subcommand_prints_usage_instead_of_creating_a_goal(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``/goal resume\\`` used to silently allocate a new goal and burn its first step."""
    await _goal_runner(SimpleNamespace(), None, "resume\\")
    err = capsys.readouterr().err
    assert "did you mean `/goal resume`" in err
    assert successful_step == []
    assert not (declarative_cwd / "_he-output" / "goals" / "current").exists()
