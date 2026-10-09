"""Story 51-8 集成样例与旧资产恢复矩阵（52-5 扩展：并行全链 + 恢复新形态 + R4 并发冒烟）。

集成样例（引擎级）链起 fail-closed Story 调度全链：依赖闸门（未知依赖 BLOCKED 且零执行）
→ 串行执行（一次一条，逐 story 落 checkpoint 与 story_statuses）→ 步骤级审批门（末条 story
后 WAITING_USER）→ approve 放行合并输出 → 恢复不重复已完成 story。CLI 级各宿主环节
（doctor / 证据 Gate / workflow 冻结 / 脚本步骤 / verify）各有专属判据文件
（test_goal_doctor / test_goal_quality_gates / test_goal_decisions / test_goal_script_*），
本文件不重复。写集声明不授权并发由 test_story_batch_safety 的 fail-closed 判据锁定。
"""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from heagent.agent.sub import SubAgent
from heagent.cli import goal as cli_goal
from heagent.engine import EngineContainer
from heagent.engine.checkpoint import WorkflowCheckpoint, WorkflowCheckpointStore, WorkflowStatus
from heagent.engine.workflow_runner import (
    StorySpec,
    WorkflowRunner,
    WorkflowStepResult,
)
from heagent.engine.workflow_resource import StepApproval, WorkflowResource, WorkflowStepResource
from heagent.goal import application
from tests.helpers_goal_audit import StubGitEngine, git as _git
from heagent.goal.workflow_loader import parse_story_list
from heagent.pub.types import StoryExecutionContext


def _story_workflow(**step_kwargs: object) -> WorkflowResource:
    step = WorkflowStepResource(
        index=1,
        name="step-01.md",
        instructions="implement",
        story_loop="epics.md",
        **step_kwargs,
    )
    return WorkflowResource(name="demo", instructions="", steps=[step])


STORIES = [
    StorySpec(id="S-1", summary="First"),
    StorySpec(id="S-2", summary="Second", depends_on=["S-1"]),
]


def _story_callback(seen: list[str]):
    async def callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=f"impl {story.id}")

    return callback


@pytest.mark.asyncio
async def test_fail_closed_story_chain_with_approval_and_recovery(tmp_path) -> None:
    """集成样例：依赖闸门 → 串行（逐 story checkpoint + 状态）→ 审批门 → 放行 → 恢复不重跑。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(
        _story_workflow(approval=StepApproval(required=True)),
        goal_id="goal",
        run_id="run",
        checkpoint_store=store,
    )
    seen: list[str] = []

    # 第 1 条 story：依赖已满足，执行后 PENDING，逐 story 落 checkpoint 与状态
    first = await runner.run_step(_story_callback(seen), stories=STORIES)
    assert first.status is WorkflowStatus.PENDING
    assert seen == ["S-1"]
    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert checkpoints[-1].completed_stories == ["S-1"]
    assert checkpoints[-1].story_statuses == {"S-1": "completed"}

    # 恢复（跨进程语义）：从 checkpoint 重建 runner，不重复 S-1
    checkpoint = checkpoints[-1]
    restored = WorkflowRunner.from_checkpoint(
        _story_workflow(approval=StepApproval(required=True)), checkpoint, checkpoint_store=store
    )
    second = await restored.run_step(_story_callback(seen), stories=STORIES)
    assert second.status is WorkflowStatus.WAITING_USER  # 末条 story 后挂审批门
    assert seen == ["S-1", "S-2"]

    # approve 放行：合并输出落 outputs，簿记延后到决策落定（51-5）
    approved = restored.approve()
    assert approved.status is WorkflowStatus.COMPLETED
    assert approved.outputs["step-01.md"] == "impl S-1\n\n---\n\nimpl S-2"
    assert restored.done


@pytest.mark.asyncio
async def test_unknown_dependency_blocks_the_whole_chain_without_running(tmp_path) -> None:
    """依赖闸门在集成链上同样 fail-closed：未知依赖 BLOCKED 且零执行、零 checkpoint 写入。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_story_workflow(), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = [
        StorySpec(id="S-1", summary="First", depends_on=["S-99"]),
        StorySpec(id="S-2", summary="Second", depends_on=["S-1"]),
    ]
    seen: list[str] = []

    result = await runner.run_step(_story_callback(seen), stories=stories)

    assert result.status is WorkflowStatus.BLOCKED
    assert seen == []
    checkpoints = await store.list_checkpoints(goal_id="goal")
    assert len(checkpoints) == 1  # 显性失败也落盘（BLOCKED 可恢复诊断）
    assert checkpoints[0].status is WorkflowStatus.BLOCKED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "label"),
    [
        (lambda data: data, "as-is"),
        (lambda data: {**data, "story_batches": {"S-1": ["S-1", "S-2"]}}, "removed story_batches field"),
        (
            lambda data: {key: value for key, value in data.items() if key not in {"active_stories", "story_statuses"}},
            "legacy minimal shape",
        ),
        # A26 / A33①：镜像字段（active_stories / artifact_refs）已从模型删除；旧盘文件携带
        # 陈旧镜像值恢复时必须被容忍读忽略——恢复一律派生自 active_story / outputs。
        (
            lambda data: {**data, "active_stories": ["S-STALE"], "artifact_refs": ["stale-ref"]},
            "stale derived mirrors are ignored",
        ),
        # 52-5：Epic 52 新形态——撤销闩随 checkpoint 持久化且可回读；闩强制串行的语义由
        # test_story_parallel_scheduling::test_violation_latch_keeps_execution_on_serial_rerun 钉住。
        (lambda data: {**data, "story_parallel_revoked": True}, "revoked latch checkpoint"),
    ],
)
async def test_legacy_checkpoint_recovery_matrix(tmp_path, mutation, label: str) -> None:
    """旧 checkpoint 形态恢复矩阵：四种历史形态都能恢复并串行续跑，不重复已完成 story。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_story_workflow(), goal_id="goal", run_id="run", checkpoint_store=store)
    seen: list[str] = []
    await runner.run_step(_story_callback(seen), stories=STORIES)
    checkpoint = (await store.list_checkpoints(goal_id="goal"))[-1]

    legacy = WorkflowCheckpoint.model_validate(mutation(checkpoint.model_dump()))
    restored = WorkflowRunner.from_checkpoint(_story_workflow(), legacy, checkpoint_store=store)
    await restored.run_step(_story_callback(seen), stories=STORIES)

    assert seen == ["S-1", "S-2"]  # 恢复不重复已完成 S-1
    assert restored.done


# ── Epic 52（Story 52-5）：并行全链样例 / 恢复矩阵新形态 / R4 并发冒烟 ─────────


_DISJOINT_THREE = """## E1
### S-1 First
- depends_on: []
- parallel_group: g
- write_set: [src/a.py]
### S-2 Second
- depends_on: []
- parallel_group: g
- write_set: [src/b.py]
### S-3 Third
- depends_on: []
- parallel_group: g
- write_set: [src/c.py]
"""


def _parallel_workflow() -> WorkflowResource:
    return WorkflowResource(
        name="demo",
        instructions="",
        steps=[
            WorkflowStepResource(
                index=1,
                name="step-01.md",
                instructions="implement",
                story_loop="epics.md",
                max_parallel_stories=2,
            )
        ],
        prompt_template="step prompt",
    )


_AuditEngineStub = StubGitEngine


@pytest.mark.asyncio
async def test_parallel_full_chain_host_wiring_with_git_audit(tmp_path, monkeypatch) -> None:
    """并行全链样例：依赖闸门 → 批调度事件 → 桥透传执行上下文 → 宿主会话（围栏参数）+
    产物落盘 + Git 审计 → RUNNING 中间快照 → 声明序合并 → 恢复不重跑。"""
    monkeypatch.chdir(tmp_path)
    for rel in ("src/a.py", "src/b.py", "src/c.py"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{rel}\n", encoding="utf-8")
    _git("init", cwd=tmp_path)
    _git("add", "-A", cwd=tmp_path)
    _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-m", "base", cwd=tmp_path)
    goal_dir = tmp_path / "_he-output" / "goals" / "demo"
    goal_dir.mkdir(parents=True)
    story_of = {"S-1": "src/a.py", "S-2": "src/b.py", "S-3": "src/c.py"}

    engine_stub = _AuditEngineStub()
    sessions: list[str] = []

    async def fake_session(provider, engine, prompt, **kwargs):
        story_id = kwargs["metadata"]["workflow_story"]
        sessions.append(story_id)
        allowlist = kwargs.get("write_allowlist")
        assert allowlist == [story_of[story_id]]  # 围栏输入逐成员生效（52-1 联动）
        (tmp_path / story_of[story_id]).write_text(f"impl {story_id}\n", encoding="utf-8")
        return SimpleNamespace(success=True, output=f"impl {story_id}")

    monkeypatch.setattr("heagent.cli.goal._goal_session", fake_session)

    async def host(inputs, step, story=None, execution=None):
        return await cli_goal._goal_execute_step(
            SimpleNamespace(), engine_stub, workflow, "demo goal", goal_dir, inputs, step, story, execution
        )

    workflow = _parallel_workflow()
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(workflow, goal_id="goal", run_id="run", checkpoint_store=store)
    stories = parse_story_list(_DISJOINT_THREE)
    events: list[tuple[str, dict]] = []

    def emit(kind: str, details: dict | None = None) -> None:
        events.append((kind, details or {}))

    # 第一波：批 [S-1, S-2] 并发（围栏 + 审计 + 逐成员 RUNNING 快照），步骤落 PENDING。
    callback = partial(application._run_step_with_inputs, {"user intent": "ship it"}, host)
    first = await runner.run_step(callback, stories=stories, emit=emit)
    assert first.status is WorkflowStatus.PENDING
    assert sorted(sessions) == ["S-1", "S-2"]
    scheduled = [details for kind, details in events if kind == "workflow_story_batch_scheduled"]
    assert scheduled and scheduled[0]["members"] == ["S-1", "S-2"]
    # step 事件形状（评审 D1 钉形）：批路径 = started 一条（story=批首成员）+ 收口一条
    # （story 空）；审计事件只报真实信号（宿主产物噪声已被豁免集排除，此处信号 =
    # checkpoint 快照文件）。
    step_events = [(kind, details.get("story", "")) for kind, details in events if kind.startswith("workflow_step_")]
    assert step_events == [("workflow_step_started", "S-1"), ("workflow_step_completed", "")]
    audits = [details for kind, details in engine_stub.published if kind == "workflow_write_audit"]
    assert len(audits) == 2  # 每条 Story 一次 Git 审计
    assert all(details.get("untracked") for details in audits)  # 真实 untracked 信号（非产物）
    snapshots = await store.list_checkpoints(goal_id="goal")
    # 快照链：S-1 记账（RUNNING）→ S-2 记账（RUNNING）→ 批终态（PENDING），批 = 单 checkpoint 单元。
    assert [checkpoint.completed_stories for checkpoint in snapshots] == [["S-1"], ["S-1", "S-2"], ["S-1", "S-2"]]

    # 恢复（跨进程语义）：不重跑 S-1/S-2，串行收尾 S-3 并完成步骤。
    restored = WorkflowRunner.from_checkpoint(workflow, snapshots[-1], checkpoint_store=store)
    restored.resume()
    second = await restored.run_step(callback, stories=stories, emit=emit)
    assert second.status is WorkflowStatus.COMPLETED
    assert restored.done
    assert sessions.count("S-3") == 1 and sessions.count("S-1") == 1
    # 串行收尾的 result.output 是单 story 输出（51-8 语义）；声明序合并落在步骤 outputs。
    assert restored.state.outputs["step-01.md"] == "impl S-1\n\n---\n\nimpl S-2\n\n---\n\nimpl S-3"
    # 串行波的 step 事件形状：started 与 completed 都带该 story 归因（与批路径单组形状不同）。
    wave2 = [(kind, details.get("story", "")) for kind, details in events if kind.startswith("workflow_step_")][2:]
    assert wave2 == [("workflow_step_started", "S-3"), ("workflow_step_completed", "S-3")]


@pytest.mark.asyncio
async def test_mid_batch_running_snapshot_is_restorable(tmp_path) -> None:
    """批中间 RUNNING 快照恢复：进程死在批结算中段时，恢复必须能重新驱动（不卡死在 RUNNING）。"""
    store = WorkflowCheckpointStore(str(tmp_path / "checkpoints"), workflow_path=str(tmp_path / "workflow.json"))
    runner = WorkflowRunner(_parallel_workflow(), goal_id="goal", run_id="run", checkpoint_store=store)
    stories = parse_story_list(_DISJOINT_THREE)
    await runner.run_step(_story_callback([]), stories=stories)  # 批 [S-1, S-2] → PENDING
    mid_running = WorkflowCheckpoint.model_validate(
        {**(await store.list_checkpoints(goal_id="goal"))[-1].model_dump(), "status": "running"}
    )
    restored = WorkflowRunner.from_checkpoint(_parallel_workflow(), mid_running, checkpoint_store=store)
    seen: list[str] = []

    async def tracked_callback(step, story):
        seen.append(story.id)
        return WorkflowStepResult(output=f"impl {story.id}")

    # 串行推进语义一次一个 story：归一化后从首个未完成（S-2）续跑，直到步骤收口。
    result = None
    while not restored.done:
        result = await restored.run_step(tracked_callback, stories=stories)
    assert result is not None and result.status is WorkflowStatus.COMPLETED
    assert seen == ["S-2", "S-3"]  # 已完成的 S-1 不重跑
    assert restored.done


@pytest.mark.asyncio
async def test_parallel_subagents_share_provider_and_engine_bus() -> None:
    """R4 冒烟：3+ SubAgent 并发复用同一 provider 与 engine 容器——全部成功、互不串扰、真实并发重叠。"""
    in_flight = 0
    peak = 0
    prompts: list[str] = []

    class CountingProvider:
        async def send(self, messages, *, tools=None):  # noqa: ANN001, ANN202
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            prompts.append(messages[-1].content)
            await asyncio.sleep(0.01)
            in_flight -= 1
            from heagent.pub.types import ProviderResponse, TokenUsage

            return ProviderResponse(
                content=f"answer-{len(prompts)}",
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model="stub",
                finish_reason="stop",
            )

        async def stream(self, messages, *, tools=None):  # noqa: ANN001, ANN202
            yield await self.send(messages, tools=tools)

        def get_metadata(self):
            from heagent.providers.base import ProviderMetadata

            return ProviderMetadata(name="stub", model="stub")

    provider = CountingProvider()
    engine = EngineContainer.default(workspace_root=None)
    contexts = [
        StoryExecutionContext(
            story_id=f"s-{index}",
            parallel=True,
            write_allowlist=[f"src/{index}.py"],
            batch_members=[f"s-{index}"],
        )
        for index in range(1, 4)
    ]
    results = await asyncio.gather(
        *(
            SubAgent(
                provider,
                engine=engine,
                metadata={"goal_id": "demo", "workflow_story": context.story_id},
                max_iterations=5,
                write_allowlist=context.write_allowlist,
            ).run(f"task {context.story_id}")
            for context in contexts
        )
    )

    assert all(result.success for result in results)
    assert sorted(prompts) == [f"task s-{index}" for index in range(1, 4)]
    assert peak >= 2  # 三个会话真实并发重叠，而非退化为顺序执行
