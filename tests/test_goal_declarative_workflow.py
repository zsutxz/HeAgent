"""Declarative /goal routing and checkpoint recovery contracts."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import heagent.cli.console as cli
import heagent.cli.goal as cli_goal
from heagent.cli.goal import (
    _goal_cron_advance,
    _goal_declarative_runner,
    _goal_declarative_workflow,
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
from heagent.engine.checkpoint import (
    GoalWorkflowState,
    WorkflowCheckpoint,
    WorkflowCheckpointError,
    WorkflowCheckpointStore,
    WorkflowPhase,
    WorkflowStatus,
)
from heagent.goal.application import checkpoint_store, restore_runner
from heagent.engine.workflow_resource import WorkflowResource, WorkflowStepResource
from heagent.goal.workflow_loader import read_workflow
from heagent.memory.skill_packages import SkillPackage
from heagent.types import Message, ProviderResponse, TokenUsage

# 随包发布的真实模板：测试消费包内真源，不在测试代码里留文案副本（防漂移）。
_SHIPPED_TEMPLATES = Path(__file__).resolve().parents[1] / ".heagent" / "skills" / "he-goal" / "templates"


def _shipped_gate_template() -> str:
    return (_SHIPPED_TEMPLATES / "gate-template.md").read_text(encoding="utf-8").strip()


def _shipped_prompt_template() -> str:
    return (_SHIPPED_TEMPLATES / "prompt-template.md").read_text(encoding="utf-8").strip()


@pytest.fixture()
def declarative_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_workflow_root: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    (goal_workflow_root / "workflow.md").write_text(
        "---\nname: test-development\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\nworkflow instructions\n\n"
        "## Step 01: plan\ninput: user intent, existing project context\n"
        "output: requirements brief, story breakdown\ncheckpoint: true\n\nplan the story\n\n"
        "## Step 02: build\ninput: requirements brief\noutput: implementation\ncheckpoint: true\n\nbuild the story\n",
        encoding="utf-8",
    )
    (tmp_path / "_he-output" / "goals").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def successful_step(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(prompt)
        return SimpleNamespace(success=True, output=f"output-{len(calls)}")

    monkeypatch.setattr("heagent.cli.goal._goal_session", run_step)
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
    goal_document = goal_dir / "brief.md"
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
    checkpoint_dir = declarative_cwd / ".heagent" / "checkpoints" / goal_id
    assert not (goal_dir / "checkpoints").exists()
    checkpoints = await WorkflowCheckpointStore(str(checkpoint_dir)).list_checkpoints(goal_id=goal_id)
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
    persisted = await WorkflowCheckpointStore(str(checkpoint_dir)).list_checkpoints(goal_id=goal_id)
    assert len({checkpoint.checkpoint_id for checkpoint in persisted}) == len(persisted)

    await _goal_runner(SimpleNamespace(), None, "run")
    assert len(successful_step) == 2


@pytest.mark.asyncio
async def test_removed_audit_subcommand_reports_usage_instead_of_creating_a_goal(
    declarative_cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A removed subcommand must fail loudly, not silently start a goal named after it."""
    await _goal_runner(SimpleNamespace(), None, "audit")

    assert "audit subcommand has been removed" in capsys.readouterr().err
    assert not (declarative_cwd / "_he-output" / "goals" / "current").exists()
    assert not (declarative_cwd / "_he-output" / "goals" / "audit").exists()


class _NamingProvider:
    """LLM 命名路径的最小 provider：仅实现 send，按构造参数返回内容或抛错。"""

    def __init__(self, *, content: str = "", error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.prompts: list[str] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.prompts.append(messages[-1].content)
        if self._error is not None:
            raise self._error
        return ProviderResponse(
            content=self._content,
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="stub",
            finish_reason="stop",
        )


@pytest.fixture()
def advance_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """命名测试只关心 goal 身份落盘：推进阶段置空，不跑 step。"""

    async def noop_advance(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("heagent.cli.goal._goal_declarative_advance", noop_advance)


@pytest.mark.asyncio
async def test_goal_new_names_project_via_llm(
    declarative_cwd: Path,
    advance_noop: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = _NamingProvider(content="  Stock-Picker \n")

    await _goal_runner(provider, None, "new 做一个选股工具")

    current = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    assert current == "stock-picker"
    assert (declarative_cwd / "_he-output" / "goals" / "stock-picker" / "brief.md").exists()
    assert "做一个选股工具" in provider.prompts[0]
    assert "using default id" not in capsys.readouterr().err


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    ["做一个好项目", "tool-2026", "a " * 40],
)
async def test_goal_new_falls_back_to_project_id_when_llm_output_unusable(
    declarative_cwd: Path,
    advance_noop: None,
    capsys: pytest.CaptureFixture[str],
    content: str,
) -> None:
    provider = _NamingProvider(content=content)

    await _goal_runner(provider, None, "new whatever the goal is")

    current = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    assert current == "project"
    assert "using default id 'project'" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_goal_new_falls_back_to_project_id_when_provider_fails(
    declarative_cwd: Path,
    advance_noop: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = _NamingProvider(error=RuntimeError("network down"))

    await _goal_runner(provider, None, "new whatever the goal is")

    current = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    assert current == "project"
    assert "using default id 'project'" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_goal_new_appends_suffix_when_llm_name_collides(
    declarative_cwd: Path,
    advance_noop: None,
) -> None:
    provider = _NamingProvider(content="stock-picker")

    await _goal_runner(provider, None, "new first goal")
    await _goal_runner(provider, None, "new second goal")

    goals = declarative_cwd / "_he-output" / "goals"
    assert (goals / "stock-picker" / "brief.md").exists()
    assert (goals / "stock-picker-a" / "brief.md").exists()
    assert (goals / "current").read_text(encoding="utf-8") == "stock-picker-a"


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
    workflow = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
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
async def test_stale_active_step_is_reported_as_checkpoint_failure(
    declarative_cwd: Path,
    successful_step: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """回归（2026-09-22）：活动步骤越界时必须像 ``/goal status`` 一样呈报 checkpoint 失败。

    ``WorkflowRunner._validate_state`` 对 ``active_step > len(steps)`` 抛的是**裸
    ``ValueError``**（``WorkflowCheckpointError`` 是它的子类，反向不成立），而推进路径
    （``_goal_declarative_prepare``）此前只兜 ``WorkflowCheckpointError``——于是存量 goal
    在「工作流收缩」（12→10→9→8 步）后执行 ``/goal next`` 会抛裸异常栈，而不是
    ``[goal] declarative checkpoint failed: ...``。
    """
    await _goal_runner(SimpleNamespace(), None, "stale state workflow")
    goal_id = (declarative_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8")
    goal_dir = declarative_cwd / "_he-output" / "goals" / goal_id
    capsys.readouterr()

    # 落在步骤数（2）之外的活动步骤：等价于工作流收缩后留下的历史状态。
    store = checkpoint_store(goal_dir)
    await store.save(
        WorkflowCheckpoint(
            checkpoint_id="stale-1",
            goal_id=goal_id,
            phase=WorkflowPhase.IMPLEMENTATION,
            status=WorkflowStatus.RUNNING,
            run_id="run-stale",
            active_step=99,
            active_skill="test-development",
        )
    )

    await _goal_runner(SimpleNamespace(), None, "next")

    err = capsys.readouterr().err
    assert "declarative checkpoint failed" in err
    assert "active step is out of range" in err


@pytest.mark.asyncio
async def test_restore_runner_fails_loud_when_configuration_does_not_match_persisted_state(tmp_path: Path) -> None:
    """恢复语义契约（Phase 3）：聚合状态与快照不匹配时显性失败，不静默重建。

    恢复顺序（goal/application.restore_runner）：有 workflow.json 时按
    ``active_step + active_skill + status`` 匹配快照；匹配落空且存在快照 →
    ``WorkflowCheckpointError``。落盘其他形式（快照损坏 / workflow.json 损坏）由
    ``test_engine_checkpoint.py`` 钉住。
    """
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    store = checkpoint_store(goal_dir)
    await store.save(
        WorkflowCheckpoint(
            checkpoint_id="cp-1",
            goal_id="goal",
            phase=WorkflowPhase.IMPLEMENTATION,
            status=WorkflowStatus.RUNNING,
            run_id="run-1",
            active_step=0,
            active_skill="he-goal",
        )
    )
    # 聚合状态指向另一条快照（手改 / 异版本写入）：与唯一快照不匹配。
    mismatched = GoalWorkflowState(
        goal_id="goal",
        phase=WorkflowPhase.IMPLEMENTATION,
        status=WorkflowStatus.RUNNING,
        active_step=3,
        active_skill="he-goal",
    )
    (goal_dir / "workflow.json").write_text(mismatched.model_dump_json(), encoding="utf-8")

    workflow = WorkflowResource(name="demo", instructions="", steps=[])
    with pytest.raises(WorkflowCheckpointError, match="does not match"):
        await restore_runner(workflow, goal_dir)


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
    workflow = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
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
    workflow = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
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
    workflow = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
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
    workflow = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
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


def _real_step_one() -> WorkflowStepResource:
    """Parse the shipped workflow with the production loader and return its step 01."""
    package = SkillPackage(
        skill_id="he-goal",
        root=Path(__file__).resolve().parents[1] / ".heagent" / "skills" / "he-goal",
    )
    return read_workflow(package, "workflow.md").steps[0]


def test_step_one_gate_requires_the_derived_requirements_summary() -> None:
    """Step 01 is the initial analysis: it must write and return the summarized requirements."""
    step = _real_step_one()
    assert required_sections(step.validation_rules) == ["需求总结"]
    # 需求文档文件名不得写进散文：代码按 goal 解析后经 prompt 的 `Goal document` 行注入。
    assert "`Goal document`" in step.instructions
    assert "brief.md" not in step.instructions
    assert "require.md" not in step.instructions
    assert "## 总结的需求（Derived Requirements）" in step.instructions
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
    assert not (goal_dir / "brief.md").exists()


def test_prior_generation_goal_document_is_read_and_written_in_place(tmp_path: Path) -> None:
    """The earlier rename (require.md -> brief.md) must not split existing goals either."""
    goal_dir = tmp_path / "prior-goal"
    goal_dir.mkdir()
    goal_dir.joinpath("require.md").write_text(cli_goal._goal_document("旧一代目标", "prior"), encoding="utf-8")

    assert cli_goal._goal_description(goal_dir) == "旧一代目标"
    cli_goal._goal_record_user_response(goal_dir, "继续推进")

    assert "继续推进" in cli_goal._goal_user_responses(goal_dir)
    assert not (goal_dir / "brief.md").exists()


@pytest.mark.parametrize(
    ("existing", "expected"),
    [(None, "brief.md"), ("brief.md", "brief.md"), ("require.md", "require.md"), ("GOAL.md", "GOAL.md")],
)
def test_step_prompt_names_the_goal_document_resolved_in_code(
    tmp_path: Path,
    existing: str | None,
    expected: str,
) -> None:
    """The filename comes from code, not from the prose: renaming it is a one-file change."""
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    if existing is not None:
        (goal_dir / existing).write_text(cli_goal._goal_document("demo goal", "demo"), encoding="utf-8")
    workflow = WorkflowResource(
        name="demo", instructions="workflow instructions", steps=[], prompt_template=_shipped_prompt_template()
    )

    prompt = cli_goal._goal_declarative_prompt(workflow, "step-01-market-research.md", "demo goal", goal_dir, {})

    assert f"Goal document: {expected}\n" in prompt
    assert "{goal_document}" not in prompt


def test_console_reexports_goal_runner_but_not_monkeypatch_seams() -> None:
    """cli/console.py 只持有自己用到的 goal 符号；patch 缝留在 cli/goal.py。"""
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


@pytest.mark.asyncio
async def test_open_question_mode_default_injects_proceed_with_default(
    declarative_cwd: Path,
    successful_step: list[str],
) -> None:
    workflow = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
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
    workflow = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
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
    workflow = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
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
    workflow = WorkflowResource(
        name="demo",
        instructions="workflow instructions",
        steps=[],
        prompt_template="{inputs}\n{gate}",
        gate_template=_shipped_gate_template(),
    )
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
    workflow = WorkflowResource(
        name="demo",
        instructions="workflow instructions",
        steps=[step],
        prompt_template="{inputs}\n{gate}",
        gate_template=_shipped_gate_template(),
    )
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
    workflow = WorkflowResource(
        name="demo",
        instructions="workflow instructions",
        steps=[],
        prompt_template="{inputs}\n{gate}",
        gate_template=_shipped_gate_template(),
    )
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

    monkeypatch.setattr("heagent.cli.goal._goal_session", run_step)
    workflow = WorkflowResource(name="demo", instructions="", steps=[], prompt_template="step prompt")
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
        )
    assert seen == [40, None]


def test_step_prompt_renders_duplicate_artifact_text_once(tmp_path: Path) -> None:
    """Each artifact is stored under two keys; the prompt must not carry it twice."""
    artifact = "# 市场调研报告\n\n" + "证据" * 400
    workflow = WorkflowResource(
        name="demo", instructions="workflow instructions", steps=[], prompt_template="{inputs}\n{gate}"
    )
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
    (goal_dir / "brief.md").write_text(cli_goal._goal_document("demo goal", "demo"), encoding="utf-8")
    step = WorkflowStepResource(index=1, name="step-01.md", instructions="")
    workflow = WorkflowResource(name="demo", instructions="", steps=[step])

    class StubRunner:
        def __init__(self) -> None:
            self.workflow = workflow
            self.state = SimpleNamespace(outputs={}, active_step=0, reason="gate rejected the output")

        async def run_step(
            self, callback: object, *, inputs: object, stories: object = None, emit: object = None
        ) -> WorkflowRunResult:
            return WorkflowRunResult(
                status=WorkflowStatus.BLOCKED,
                step_index=0,
                reason="step 'step-01.md' output is missing section: 实现摘要",
            )

    context = cli_goal._GoalAdvanceContext(
        runner=StubRunner(),  # type: ignore[arg-type]
        mode="auto",
        description="demo goal",
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


def test_bundled_workflow_ships_the_required_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Templates are the package's alone: the bundled ones must carry the placeholder contract."""
    monkeypatch.chdir(Path(__file__).resolve().parents[1])

    workflow = _goal_declarative_workflow()

    assert workflow is not None
    assert workflow.max_rounds >= 1
    # 声明行是生效开关：frontmatter 不声明 required_resources 就没有加载期强制，钉死防漂移。
    declared = str(workflow.frontmatter.get("required_resources", ""))
    assert "prompt-template.md" in declared
    assert "gate-template.md" in declared
    # 维护者文档只能住在 SKILL.md：混进 workflow.md 正文会被注入每步提示词。
    assert "模板契约" not in workflow.instructions
    for placeholder in ("{workflow_instructions}", "{goal}", "{goal_document}", "{step}", "{gate}"):
        assert placeholder in workflow.prompt_template
    for placeholder in ("{sections}", "{acceptance}", "{rules}"):
        assert placeholder in workflow.gate_template


def test_declared_run_rounds_and_auto_schedule_override_cli_defaults(declarative_cwd: Path) -> None:
    """``max_rounds`` / ``auto_schedule`` come from the workflow declaration, not from code."""
    workflow_path = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
    workflow_path.write_text(
        workflow_path.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n",
            'step_executor: subagent\nmax_rounds: 3\nauto_schedule: "0 3 * * *"\n',
        ),
        encoding="utf-8",
    )

    workflow = _goal_declarative_workflow()

    assert workflow is not None
    assert workflow.max_rounds == 3
    assert workflow.auto_schedule == "0 3 * * *"


def test_workflow_package_resolves_by_id_and_serves_its_own_templates(declarative_cwd: Path) -> None:
    """A package entry makes the workflow addressable by id and lets it ship prompt/gate templates."""
    root = declarative_cwd / ".heagent" / "skills" / "he-goal"
    templates = root / "templates"
    templates.mkdir(exist_ok=True)
    (templates / "prompt-template.md").write_text("CUSTOM {goal} :: {step}\n{gate}", encoding="utf-8")
    (templates / "gate-template.md").write_text("CUSTOM-GATE {rules}\n", encoding="utf-8")

    package = cli_goal._goal_workflow_package()
    assert package is not None
    workflow = _goal_declarative_workflow()

    assert package.skill_id == "he-goal"
    assert workflow is not None

    prompt = cli_goal._goal_declarative_prompt(
        workflow,
        "step-01-plan.md",
        "demo goal",
        declarative_cwd / "goals" / "demo",
        {"user intent": "ship it"},
        validation_rules="section: Gate Title",
        declared_inputs="user intent",
    )

    assert prompt.startswith("CUSTOM demo goal :: step-01-plan.md")
    assert "CUSTOM-GATE" in prompt
    assert "- Declared validation rules (verbatim): section: Gate Title" in prompt


def test_missing_declared_required_templates_fail_explicitly(declarative_cwd: Path) -> None:
    """``required_resources`` 声明驱动：声明了却缺失 → 加载即显性失败，不再有内置兜底。"""
    workflow_md = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
    workflow_md.write_text(
        workflow_md.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n",
            "step_executor: subagent\nrequired_resources: prompt-template.md, gate-template.md\n",
        ),
        encoding="utf-8",
    )
    shutil.rmtree(declarative_cwd / ".heagent" / "skills" / "he-goal" / "templates")

    with pytest.raises(ValueError, match="gate-template|prompt-template"):
        _goal_declarative_workflow()


def test_bulleted_inline_step_metadata_fails_loudly(declarative_cwd: Path) -> None:
    """列表式元数据（``- input: x``）是常见笔误：显性拒绝，不静默收成 ``- input`` 键丢掉真实契约。"""
    workflow_md = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
    workflow_md.write_text(
        "---\nname: test-development\nentrypoint: goal\non_create: persist_goal_identity\n"
        "step_executor: subagent\n---\n\nworkflow instructions\n\n"
        "## Step 01: plan\n- input: user intent\n- output: brief\n\nplan the story\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="markdown bullets"):
        _goal_declarative_workflow()


def test_undeclared_missing_templates_fail_loudly_at_render_time(tmp_path: Path) -> None:
    """未声明 required 的包缺模板 → 渲染期显性失败，不以空提示词/空门禁静默跑步骤。"""
    workflow = WorkflowResource(name="demo", instructions="", steps=[])
    with pytest.raises(ValueError, match="prompt-template"):
        cli_goal._goal_declarative_prompt(workflow, "step-01-plan.md", "demo goal", tmp_path, {})
    workflow = workflow.model_copy(update={"prompt_template": "{gate}"})
    with pytest.raises(ValueError, match="gate-template"):
        cli_goal._goal_declarative_prompt(
            workflow, "step-01-plan.md", "demo goal", tmp_path, {}, validation_rules="section: 实现摘要"
        )
    # 无门禁规则的步骤不消费门禁模板：缺了也不拦（该步渲染不出门禁块本就是正确形态）。
    assert cli_goal._goal_declarative_prompt(workflow, "step-01-plan.md", "demo goal", tmp_path, {}) == ""


def test_required_resources_normalizes_prefix_and_rejects_typos(declarative_cwd: Path) -> None:
    """声明带 ``templates/`` 前缀同样生效；拼错或未知的条目在加载期显性失败，不做静默忽略。"""
    workflow_md = declarative_cwd / ".heagent" / "skills" / "he-goal" / "workflow.md"
    workflow_md.write_text(
        workflow_md.read_text(encoding="utf-8").replace(
            "step_executor: subagent\n",
            "step_executor: subagent\nrequired_resources: templates/prompt-template.md, templates/gate-template.md\n",
        ),
        encoding="utf-8",
    )

    workflow = _goal_declarative_workflow()

    assert workflow is not None
    assert workflow.prompt_template  # 前缀归一化后命中真实模板
    workflow_md.write_text(
        workflow_md.read_text(encoding="utf-8").replace(
            "required_resources: templates/prompt-template.md, templates/gate-template.md",
            "required_resources: prompt-templates.md",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="prompt-templates"):
        _goal_declarative_workflow()
