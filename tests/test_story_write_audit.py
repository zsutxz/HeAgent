"""Story 52-3 宿主写集审计测试：Git 增量判负、兄弟排除、untracked 警告、非 Git 跳过与门锁串行。"""

import asyncio
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from heagent.cli import goal as cli_goal
from tests.helpers_goal_audit import StubGitEngine, commit_all as _commit_all, git as _git, tracked as _tracked
from heagent.engine import (
    StepValidationClauses,
    StorySpec,
    WorkflowResource,
    WorkflowStatus,
    WorkflowStepResource,
)
from heagent.engine.checkpoint import WorkflowCheckpointStore
from heagent.engine.workflow_runner import WorkflowRunner, WorkflowStepResult
from heagent.goal import application
from heagent.goal.workflow_loader import parse_story_list
from heagent.pub.types import StoryExecutionContext


@pytest.fixture()
def git_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """带基线提交的 git 工作区：src/base.py 已 tracked。"""
    monkeypatch.chdir(tmp_path)
    _tracked(tmp_path, "src/base.py", "x = 1\n")
    _git("init", cwd=tmp_path)
    _commit_all(tmp_path, "base")
    return tmp_path


def _goal_dir(workspace: Path) -> Path:
    goal_dir = workspace / "_he-output" / "goals" / "demo"
    goal_dir.mkdir(parents=True, exist_ok=True)
    return goal_dir


def _execution() -> StoryExecutionContext:
    return StoryExecutionContext(
        story_id="s-1",
        parallel=True,
        write_allowlist=["src/a.py"],
        batch_members=["s-1", "s-2"],
        sibling_write_sets={"s-2": ["src/b.py"]},
    )


def _step() -> WorkflowStepResource:
    return WorkflowStepResource(index=7, name="step-07-implement-story.md", instructions="implement")


def _workflow() -> WorkflowResource:
    return WorkflowResource(name="demo", instructions="", steps=[], prompt_template="step prompt")


def _story() -> StorySpec:
    return StorySpec(id="s-1", epic="epic-a")


def _session_stub(monkeypatch: pytest.MonkeyPatch, *, writes: tuple[str, ...] = ()) -> list[dict]:
    """替身 _goal_session：记录 kwargs 并模拟越集/集内写（相对仓库根的 tracked 路径）。"""
    calls: list[dict] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(dict(kwargs))
        for rel in writes:
            _tracked(Path.cwd(), rel, f"touched {rel}\n")
        return SimpleNamespace(success=True, output="body")

    monkeypatch.setattr("heagent.cli.goal._goal_session", run_step)
    return calls


_StubEngine = StubGitEngine


async def _run_step(
    engine: object,
    goal_dir: Path,
    execution: StoryExecutionContext | None,
    *,
    step: WorkflowStepResource | None = None,
    story: object = None,
) -> object:
    return await cli_goal._goal_execute_step(
        SimpleNamespace(),
        engine,
        _workflow(),
        "demo goal",
        goal_dir,
        {"user intent": "ship it"},
        step or _step(),
        story if story is not None else (_story() if execution is not None else None),
        execution,
    )


def test_write_set_coverage_semantics() -> None:
    """判负覆盖语义与引擎批派生同源：目录条目覆盖子树、大小写不敏感；空/死条目不构成豁免。"""
    assert cli_goal._covered_by_write_set("src/x.py", ["src"])
    assert cli_goal._covered_by_write_set("SRC/X.PY", ["src"])
    assert not cli_goal._covered_by_write_set("docs/x.md", ["src"])
    assert cli_goal._covered_by_write_set("src/a.py", ["src/a.py"])
    assert not cli_goal._covered_by_write_set("anything/else", [""])  # 空条目免检是 fail-open，已修


@pytest.mark.asyncio
async def test_tracked_write_outside_set_fails_with_violation(
    git_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tracked 增量越集 → FAILED + write_violation + reason 列出越集路径；会话带 allowlist。"""
    _tracked(git_workspace, "src/rogue.py", "sneak = 0\n")
    _commit_all(git_workspace, "plant rogue")
    goal_dir = _goal_dir(git_workspace)
    calls = _session_stub(monkeypatch, writes=("src/rogue.py",))

    result = await _run_step(_StubEngine(), goal_dir, _execution())

    assert result.status is WorkflowStatus.FAILED
    assert result.write_violation is True
    assert "src/rogue.py" in result.reason
    assert calls[0]["write_allowlist"] == ["src/a.py"]


@pytest.mark.asyncio
async def test_own_and_sibling_declared_paths_not_flagged(git_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """双 Story 并发写各自声明路径：own + 兄弟写集内的 tracked 增量不误伤。"""
    _tracked(git_workspace, "src/a.py", "a = 0\n")
    _tracked(git_workspace, "src/b.py", "b = 0\n")
    _commit_all(git_workspace, "plant declared")
    goal_dir = _goal_dir(git_workspace)
    _session_stub(monkeypatch, writes=("src/a.py", "src/b.py"))

    result = await _run_step(_StubEngine(), goal_dir, _execution())

    assert result.status is WorkflowStatus.COMPLETED
    assert result.write_violation is False


@pytest.mark.asyncio
async def test_untracked_delta_emits_warning_event_only(git_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """untracked 增量（含 .heagent/tmp/ 验证夹具）只发 workflow_write_audit 警告，不判负。"""
    goal_dir = _goal_dir(git_workspace)
    engine = _StubEngine()
    _session_stub(monkeypatch, writes=("src/generated.py", ".heagent/tmp/probe/fixture.bin"))

    result = await _run_step(engine, goal_dir, _execution())

    assert result.status is WorkflowStatus.COMPLETED
    audits = [(kind, details) for kind, details in engine.published if kind == "workflow_write_audit"]
    assert len(audits) == 1
    untracked = audits[0][1]["untracked"]
    assert "src/generated.py" in untracked
    assert ".heagent/tmp/probe/fixture.bin" in untracked


@pytest.mark.asyncio
async def test_non_git_workspace_skips_audit_but_keeps_fence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非 Git 项目：审计跳过（发说明事件）、围栏参数仍传给会话、越集写不判负。"""
    monkeypatch.chdir(tmp_path)
    goal_dir = _goal_dir(tmp_path)
    engine = _StubEngine()
    calls = _session_stub(monkeypatch, writes=("src/rogue.py",))

    result = await _run_step(engine, goal_dir, _execution())

    assert result.status is WorkflowStatus.COMPLETED
    assert calls[0]["write_allowlist"] == ["src/a.py"]
    audits = [(kind, details) for kind, details in engine.published if kind == "workflow_write_audit"]
    assert audits and audits[0][1].get("skipped") == "git_unavailable"


@pytest.mark.asyncio
async def test_host_artifact_write_not_flagged(git_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """宿主自写产物（goal_step_artifact_path，且已 tracked）不计入违规。"""
    goal_dir = _goal_dir(git_workspace)
    artifact = cli_goal.goal_step_artifact_path(goal_dir, _step(), _story())
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("previous\n", encoding="utf-8")
    _commit_all(git_workspace, "plant artifact")
    _session_stub(monkeypatch)

    result = await _run_step(_StubEngine(), goal_dir, _execution())

    assert result.status is WorkflowStatus.COMPLETED
    assert artifact.read_text(encoding="utf-8") == "body"


@pytest.mark.asyncio
async def test_serial_step_without_execution_keeps_legacy_path(
    git_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """execution=None（串行步）：会话不带 allowlist、零 Git 查询、结果与既有路径逐字节一致。"""
    goal_dir = _goal_dir(git_workspace)
    engine = _StubEngine()
    calls = _session_stub(monkeypatch, writes=("src/rogue.py",))

    result = await _run_step(engine, goal_dir, None)

    assert result.status is WorkflowStatus.COMPLETED
    assert calls[0].get("write_allowlist") is None
    assert engine.published == []


@pytest.mark.asyncio
async def test_parallel_gates_run_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    """门锁探针：并发 _goal_structured_gate 的求值区间不重叠（LLM 会话并行、门命令串行）。"""
    spans: list[tuple[float, float]] = []

    async def fake_report(*args: object, **kwargs: object) -> SimpleNamespace:
        start = time.perf_counter()
        await asyncio.sleep(0.05)
        spans.append((start, time.perf_counter()))
        return SimpleNamespace(
            passed=True,
            failed=[],
            errors=[],
            render=list,
            failure_summary_parts=list,
            rerun_evidence=[],
            reused_commands=[],
        )

    monkeypatch.setattr("heagent.cli.goal._goal_verify_report", fake_report)
    step = WorkflowStepResource(
        index=1,
        name="s",
        instructions="",
        validation_clauses=StepValidationClauses(commands=["echo ok"]),
    )
    workflow = _workflow()
    await asyncio.gather(
        cli_goal._goal_structured_gate(None, workflow, step, None, Path(".")),
        cli_goal._goal_structured_gate(None, workflow, step, None, Path(".")),
    )
    assert len(spans) == 2
    first, second = sorted(spans)
    assert first[1] <= second[0] + 1e-6


def test_step_executor_protocol_bridge_shape() -> None:
    """四参宿主 → 执行上下文桥（Runner 授权并行）；三参老宿主 → 串行桥（fail-closed）。"""

    async def four_param(inputs: object, step: object, story: object = None, execution: object = None) -> object:
        return None

    async def three_param(inputs: object, step: object, story: object = None) -> object:
        return None

    assert application._executor_accepts_execution(four_param)
    assert not application._executor_accepts_execution(three_param)
    assert WorkflowRunner._accepts_execution(partial(application._run_step_with_inputs, {}, four_param))
    assert not WorkflowRunner._accepts_execution(partial(application._run_step_without_execution, {}, three_param))


@pytest.mark.asyncio
async def test_run_step_bridge_forwards_execution() -> None:
    """执行上下文经桥透传到宿主第四参。"""
    seen: dict[str, object] = {}
    context = _execution()

    async def host(inputs: object, step: object, story: object = None, execution: object = None) -> str:
        seen["execution"] = execution
        return "ok"

    result = await application._run_step_with_inputs({"u": 1}, host, "step", "story", context)
    assert result == "ok"
    assert seen["execution"] is context


_TWO_DISJOINT = """## E1
### S-1 First
- depends_on: []
- parallel_group: g
- write_set: [src/a.py]
### S-2 Second
- depends_on: []
- parallel_group: g
- write_set: [src/b.py]
"""


@pytest.mark.asyncio
async def test_runner_batch_wiring_through_application_bridge(tmp_path: Path) -> None:
    """52-2 授权 × 52-3 协议桥联动冒烟：授权批经应用桥派发、宿主按成员收各自上下文；
    三参老宿主经串行桥退化为串行且永不收上下文。"""
    store = WorkflowCheckpointStore(str(tmp_path / "cp"), workflow_path=str(tmp_path / "wf.json"))
    workflow = WorkflowResource(
        name="sample",
        instructions="",
        steps=[
            WorkflowStepResource(
                index=1,
                name="implement",
                instructions="run",
                story_loop="epics.md",
                max_parallel_stories=2,
            )
        ],
    )
    stories = parse_story_list(_TWO_DISJOINT)
    received: list[StoryExecutionContext | None] = []

    async def host(
        inputs: object, step: object, story: StorySpec, execution: StoryExecutionContext | None = None
    ) -> WorkflowStepResult:
        received.append(execution)
        return WorkflowStepResult(output=story.id)

    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)
    result = await runner.run_step(partial(application._run_step_with_inputs, {"u": 1}, host), stories=stories)

    assert result.status is WorkflowStatus.COMPLETED
    assert [context.story_id if context else "" for context in received] == ["S-1", "S-2"]
    assert all(context is not None and context.parallel for context in received)
    assert received[0] is not None and received[0].sibling_write_sets == {"S-2": ["src/b.py"]}
    assert received[1] is not None and received[1].sibling_write_sets == {"S-1": ["src/a.py"]}

    legacy: list[str] = []

    async def old_host(inputs: object, step: object, story: object = None) -> WorkflowStepResult:
        assert story is not None
        # S-1 最慢：若被并行授权，S-2 会先入列——断言声明序即断言串行。
        await asyncio.sleep(0.05 if story.id == "S-1" else 0.0)
        legacy.append(story.id)
        return WorkflowStepResult(output=story.id)

    runner_legacy = WorkflowRunner(workflow, goal_id="g2", run_id="run2", checkpoint_store=store)
    callback_legacy = partial(application._run_step_without_execution, {"u": 1}, old_host)
    # 串行语义一次推进一个 story；S-1 最慢，若批被误授权则两次执行会在同一调用内并发、
    # S-2 先入列——断言跨两次推进的声明序即断言串行。
    first = await runner_legacy.run_step(callback_legacy, stories=stories)
    second = await runner_legacy.run_step(callback_legacy, stories=stories)

    assert first.status is WorkflowStatus.PENDING
    assert second.status is WorkflowStatus.COMPLETED
    assert legacy == ["S-1", "S-2"]


@pytest.mark.asyncio
async def test_production_advance_wires_execution_to_host(tmp_path: Path) -> None:
    """生产推进路径（advance→桥选择→Runner 授权→宿主第四参）端到端（评审 P3）。

    此前所有并行集成样例都手拼四参 partial——桥选择发生在测试里；桥若回归恒串行，
    全量测试仍绿。本用例沿真实 application.advance 驱动，宿主闭包不手拼桥。
    """
    (tmp_path / "brief.md").write_text(
        "# 需求\n\n## 原始需求（Original Request）\n\n```\ndemo\n```\n", encoding="utf-8"
    )
    (tmp_path / "epics.md").write_text(_TWO_DISJOINT, encoding="utf-8")
    store = WorkflowCheckpointStore(str(tmp_path / "cp"), workflow_path=str(tmp_path / "wf.json"))
    workflow = WorkflowResource(
        name="demo",
        instructions="",
        steps=[
            WorkflowStepResource(
                index=1,
                name="implement",
                instructions="run",
                story_loop="epics.md",
                max_parallel_stories=2,
            )
        ],
        prompt_template="p",
    )
    seen: list[StoryExecutionContext | None] = []

    async def host(
        inputs: object, step: object, story: StorySpec, execution: StoryExecutionContext | None = None
    ) -> WorkflowStepResult:
        seen.append(execution)
        return WorkflowStepResult(output=story.id)

    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)
    context = application.GoalAdvanceContext(runner=runner, mode="auto", description="demo", goal_dir=tmp_path)
    outcome = await application.advance(
        context, host, confirm_checkpoint=lambda: True, load_project_context=lambda: None
    )

    assert outcome.status is application.GoalAdvanceStatus.DONE
    assert len(seen) == 2
    assert all(context is not None for context in seen)


@pytest.mark.asyncio
async def test_manual_batch_suspends_once_for_human_resume(tmp_path: Path) -> None:
    """批=单 checkpoint 单元的人工面（评审 P8）：manual 模式批完成后挂起一次等
    /goal resume；advance 不代批确认（confirm 零调用）——「每批一次确认」的准确语义。"""
    (tmp_path / "brief.md").write_text(
        "# 需求\n\n## 原始需求（Original Request）\n\n```\ndemo\n```\n", encoding="utf-8"
    )
    (tmp_path / "epics.md").write_text(_TWO_DISJOINT, encoding="utf-8")
    store = WorkflowCheckpointStore(str(tmp_path / "cp"), workflow_path=str(tmp_path / "wf.json"))
    three = (
        _TWO_DISJOINT
        + """### S-3 Third
- depends_on: []
- parallel_group: g
- write_set: [src/c.py]
"""
    )
    (tmp_path / "epics.md").write_text(three, encoding="utf-8")
    workflow = WorkflowResource(
        name="demo",
        instructions="",
        steps=[
            WorkflowStepResource(
                index=1,
                name="implement",
                instructions="run",
                story_loop="epics.md",
                max_parallel_stories=2,
                checkpoint="true",
            )
        ],
        prompt_template="p",
    )

    async def host(
        inputs: object, step: object, story: StorySpec, execution: StoryExecutionContext | None = None
    ) -> WorkflowStepResult:
        return WorkflowStepResult(output=story.id)

    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)
    context = application.GoalAdvanceContext(runner=runner, mode="manual", description="demo", goal_dir=tmp_path)
    confirm_calls: list[int] = []

    def confirm() -> bool:
        confirm_calls.append(1)
        return True

    outcome = await application.advance(context, host, confirm_checkpoint=confirm, load_project_context=lambda: None)

    assert outcome.status is application.GoalAdvanceStatus.WAITING
    assert confirm_calls == []  # 批确认只能由人 /goal resume，advance 不代批拍板
    assert runner.state.status is WorkflowStatus.WAITING_USER
