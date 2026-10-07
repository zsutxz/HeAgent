"""Story 51-6：多 workflow 选择、创建时冻结与恢复按绑定解析（AD-8）。

覆盖验收判据：创建时把选定的 workflow 包 id 与 revision 冻结进需求文档 frontmatter；
``--workflow`` 选择生效；恢复/推进一律按冻结绑定解析（改配置不换流程）；包漂移 fail-loud
（文案含两个 revision 与 goal id）；存量 goal 缺键 → 兼容绑定注入的默认包 id，且**只读路径
不改写原件**；绑定缺失包显性报错；「新增包 = src/ 遍改前零改动」以第 5 个合成包全链路演示；
frozen revision 流入 ``verify_step``（51-4 递延接线的收口）。合成包建在 tmp skills 根，
不依赖本机 ``.heagent/skills``。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import heagent.cli.goal as cli_goal
from heagent.cli.goal import _goal_runner
from heagent.config import reset_settings
from heagent.engine.workflow_resource import WorkflowResource
from heagent.goal.application import read_workflow_binding, resolve_bound_workflow, resolve_skill_package
from heagent.goal.doctor import diagnose_workflow
from heagent.goal.workflow_loader import read_workflow, workflow_revision
from heagent.memory.skill_packages import SkillCatalog
from heagent.pub.frontmatter import parse_strict_pairs, split_frontmatter

_PROMPT_TEMPLATE = (
    "{workflow_instructions}\n\n"
    "# Declarative workflow step\n"
    "Goal: {goal}\n"
    "Goal directory: {goal_dir}\n"
    "Step: {step}\n"
    "{story_context}Role instructions:\n"
    "{role}\n"
    "Open question policy:\n"
    "{open_question_policy}\n"
    "Declared inputs:\n"
    "{inputs}\n"
    "{gate}Execute only this declared step."
)

_GATE_TEMPLATE = "Gate requirements (hard, enforced on your final response):\n{sections}{acceptance}{rules}\n"


def _workflow_md(*, steps: int, name: str, revision: str = "", validation: str = "", phase: str = "phase") -> str:
    """合成一份内联步骤的 workflow.md（可选 ``revision`` 声明、首步 ``validation:`` 子句与步骤名前缀）。"""
    blocks: list[str] = []
    for index in range(1, steps + 1):
        metadata = ["input: user intent, existing project context" if index == 1 else "input: plan", "output: plan"]
        if index == steps:
            metadata.append("checkpoint: true")
        if validation and index == 1:
            metadata.append(f"validation: {validation}")
        blocks.append("\n".join([f"## Step {index:02d}: {phase}-{index}", *metadata]) + f"\n\nDo {phase} {index}.\n")
    frontmatter = (
        "---\n"
        f"name: {name}\n"
        "entrypoint: goal\n"
        "on_create: persist_goal_identity\n"
        "step_executor: subagent\n"
        + (f'revision: "{revision}"\n' if revision else "")
        + "required_resources: prompt-template.md, gate-template.md\n"
        "---\n\n"
        f"# {name} workflow\n\n"
        "Shared instructions injected into every step prompt.\n\n"
    )
    return frontmatter + "\n".join(blocks)


def _make_package(
    cwd: Path, skill_id: str, *, steps: int = 2, revision: str = "", validation: str = "", phase: str = "phase"
) -> Path:
    """在 cwd 的 skills 根下自建一个合成 workflow 包（SKILL.md + workflow.md + 两个模板）。"""
    root = cwd / ".heagent" / "skills" / skill_id
    root.mkdir(parents=True)
    alias = skill_id.removeprefix("he-")
    (root / "SKILL.md").write_text(
        "---\n"
        f"canonical_id: {skill_id}\n"
        f"name: {skill_id}\n"
        "description: synthetic workflow package\n"
        f"aliases: [{alias}]\n"
        "---\n\n# synthetic package\n",
        encoding="utf-8",
    )
    templates = root / "templates"
    templates.mkdir()
    (templates / "prompt-template.md").write_text(_PROMPT_TEMPLATE, encoding="utf-8")
    (templates / "gate-template.md").write_text(_GATE_TEMPLATE, encoding="utf-8")
    (root / "workflow.md").write_text(
        _workflow_md(steps=steps, name=f"{skill_id}-flow", revision=revision, validation=validation, phase=phase),
        encoding="utf-8",
    )
    return root


def _make_external_step_package(cwd: Path, skill_id: str) -> Path:
    """合成一个**外挂步骤文件**形态的 workflow 包（``steps:`` 声明 step-NN-*.md，51-6 审查 M1）。"""
    root = cwd / ".heagent" / "skills" / skill_id
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\n"
        f"canonical_id: {skill_id}\n"
        f"name: {skill_id}\n"
        "description: synthetic external-step workflow package\n"
        "---\n\n# synthetic external-step package\n",
        encoding="utf-8",
    )
    templates = root / "templates"
    templates.mkdir()
    (templates / "prompt-template.md").write_text(_PROMPT_TEMPLATE, encoding="utf-8")
    (templates / "gate-template.md").write_text(_GATE_TEMPLATE, encoding="utf-8")
    (root / "workflow.md").write_text(
        "---\n"
        f"name: {skill_id}-flow\n"
        "entrypoint: goal\n"
        "on_create: persist_goal_identity\n"
        "step_executor: subagent\n"
        "steps: [step-01-first.md, step-02-second.md]\n"
        "required_resources: prompt-template.md, gate-template.md\n"
        "---\n\n# external step files workflow\n\n",
        encoding="utf-8",
    )
    (root / "step-01-first.md").write_text(
        "---\ninput: user intent, existing project context\noutput: plan\n---\n\nDo the first phase.\n",
        encoding="utf-8",
    )
    (root / "step-02-second.md").write_text(
        "---\ninput: plan\noutput: done\ncheckpoint: true\n---\n\nDo the second phase.\n",
        encoding="utf-8",
    )
    return root


def _brief_frontmatter(goal_dir: Path) -> dict[str, str]:
    """brief.md frontmatter 的严档解析视图（测试专用；严档返回原始值，此处统一剥空白）。"""
    text = (goal_dir / "brief.md").read_text(encoding="utf-8")
    split = split_frontmatter(text)
    assert split is not None, "brief.md 必须带 frontmatter"
    return {key: value.strip() for key, value in parse_strict_pairs(split[0]).items()}


def _goal_dir(cwd: Path) -> Path:
    goal_id = (cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    return cwd / "_he-output" / "goals" / goal_id


def _make_legacy_goal(cwd: Path, goal_id: str) -> Path:
    """建一个**没有** workflow 绑定键的存量 goal（走 `goal_document` 旧口径）。"""
    goals = cwd / "_he-output" / "goals"
    goal_dir = goals / goal_id
    goal_dir.mkdir(parents=True)
    (goal_dir / "brief.md").write_text(cli_goal.goal_document("legacy goal", goal_id), encoding="utf-8")
    (goals / "current").write_text(goal_id, encoding="utf-8")
    return goal_dir


@pytest.fixture()
def goal_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """cwd 为 tmp 工作区；预建 goals 根。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "_he-output" / "goals").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def successful_step(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """步骤执行缝的替身：成功输出，记录每次 prompt。"""
    calls: list[str] = []

    async def run_step(provider: object, engine: object, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append(prompt)
        return SimpleNamespace(success=True, output=f"output-{len(calls)}")

    monkeypatch.setattr("heagent.cli.goal._goal_session", run_step)
    return calls


# ── ① 创建时冻结 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_goal_new_freezes_workflow_id_and_revision(
    goal_cwd: Path, successful_step: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_package(goal_cwd, "he-alpha")
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-alpha")
    reset_settings()
    package = resolve_skill_package("he-alpha")
    assert package is not None
    workflow = read_workflow(package, "workflow.md")
    expected = workflow_revision(package, workflow)

    await _goal_runner(SimpleNamespace(), None, "new freeze the workflow")

    goal_dir = _goal_dir(goal_cwd)
    values = _brief_frontmatter(goal_dir)
    assert values["workflow"] == "he-alpha"
    assert values["workflow_revision"] == expected
    assert successful_step  # 创建后照常推进第一步


@pytest.mark.asyncio
async def test_goal_new_declared_revision_is_frozen_verbatim(
    goal_cwd: Path, successful_step: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_package(goal_cwd, "he-fixed", revision="7")
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-fixed")
    reset_settings()
    package = resolve_skill_package("he-fixed")
    assert package is not None
    workflow = read_workflow(package, "workflow.md")

    await _goal_runner(SimpleNamespace(), None, "new declared revision")

    values = _brief_frontmatter(_goal_dir(goal_cwd))
    assert values["workflow"] == "he-fixed"
    # 声明路径：frontmatter 的 revision 原样冻结（改包内容不改变它，由声明方推进版本）。
    assert values["workflow_revision"] == "7"
    assert values["workflow_revision"] == workflow_revision(package, workflow)


# ── ② --workflow 选择生效 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_goal_new_honors_the_workflow_option(goal_cwd: Path, successful_step: list[str]) -> None:
    _make_package(goal_cwd, "he-alpha")
    _make_package(goal_cwd, "he-beta", steps=3)

    await _goal_runner(SimpleNamespace(), None, "new pick the beta flow --workflow he-beta")

    values = _brief_frontmatter(_goal_dir(goal_cwd))
    assert values["workflow"] == "he-beta"
    assert successful_step  # 选择的包正常执行第一步


@pytest.mark.asyncio
async def test_goal_new_with_an_unknown_package_fails_loudly(
    goal_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_package(goal_cwd, "he-alpha")

    await _goal_runner(SimpleNamespace(), None, "new ghost flow --workflow he-ghost")

    err = capsys.readouterr().err
    assert "he-ghost" in err
    assert "unavailable" in err
    assert not (goal_cwd / "_he-output" / "goals" / "current").exists()


@pytest.mark.asyncio
async def test_goal_new_rejects_a_workflow_option_without_a_value(
    goal_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_package(goal_cwd, "he-alpha")

    await _goal_runner(SimpleNamespace(), None, "new missing value --workflow")

    assert "--workflow requires a package id" in capsys.readouterr().err
    assert not (goal_cwd / "_he-output" / "goals" / "current").exists()


@pytest.mark.asyncio
async def test_goal_new_honors_the_equals_form_of_the_workflow_option(
    goal_cwd: Path, successful_step: list[str]
) -> None:
    """``--workflow=<包id>`` 与空格形态同义（51-6 审查 L1：等号形态不再被吞进描述）。"""
    _make_package(goal_cwd, "he-beta", steps=3)

    await _goal_runner(SimpleNamespace(), None, "new equals form --workflow=he-beta")

    values = _brief_frontmatter(_goal_dir(goal_cwd))
    assert values["workflow"] == "he-beta"
    assert successful_step  # 选择的包正常执行第一步


@pytest.mark.asyncio
async def test_goal_new_rejects_a_repeated_workflow_option(goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """重复 ``--workflow`` 显性报错（51-6 审查 L1：不再静默取第一个、把第二个留在描述里）。"""
    _make_package(goal_cwd, "he-alpha")
    _make_package(goal_cwd, "he-beta")

    await _goal_runner(SimpleNamespace(), None, "new twice --workflow he-alpha --workflow he-beta")

    assert "--workflow may be given at most once" in capsys.readouterr().err
    assert not (goal_cwd / "_he-output" / "goals" / "current").exists()


# ── ③ 恢复按绑定解析（改配置不换流程）─────────────────────────────────


@pytest.mark.asyncio
async def test_status_resolves_the_frozen_binding_not_the_current_setting(
    goal_cwd: Path, successful_step: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_package(goal_cwd, "he-alpha", steps=2)
    _make_package(goal_cwd, "he-beta", steps=3)
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-alpha")
    reset_settings()

    await _goal_runner(SimpleNamespace(), None, "new alpha flow")
    assert successful_step  # 第一步已完成
    capsys.readouterr()

    # 改配置指向另一个包：恢复必须仍按冻结绑定走 alpha（2 步），而不是 beta（3 步）。
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-beta")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, "status")

    err = capsys.readouterr().err
    assert "declarative progress: 1/2" in err
    assert "1/3" not in err


# ── ③b dispatch 逐臂：settings ≠ 绑定时按冻结绑定解析（51-6 审查 H1）──────────


class _RecordingCronStore:
    """``/goal auto`` 注册路径的最小 JobStore 替身（记录注册的 job）。"""

    def __init__(self) -> None:
        self.jobs: list[SimpleNamespace] = []

    def create_job(self, prompt: str, schedule: str) -> SimpleNamespace:
        return SimpleNamespace(id=f"job-{len(self.jobs) + 1}", prompt=prompt, schedule=schedule)

    def add(self, job: SimpleNamespace) -> None:
        self.jobs.append(job)

    def list_jobs(self) -> list[SimpleNamespace]:
        return list(self.jobs)

    def remove(self, job_id: str) -> bool:
        for index, job in enumerate(self.jobs):
            if job.id == job_id:
                del self.jobs[index]
                return True
        return False


# 逐臂核对 ``_goal_declarative_dispatch`` 分支表后列出的**绑定臂**：作用于既有 goal 的每条
# 命令都必须按冻结绑定解析（51-6 审查 H1：此前仅 status/next/cron 三臂有负向覆盖）。
# 其余各臂不解析 workflow、不进本表：``new`` 与裸描述是创建臂（按当前配置/选项选择，
# 见下方专属测试）；``reset`` 只清 current 指针；``audit`` 是已移除提示；拼错提示与
# 「命令带多余参数报用法表」两臂只回显用法。
_BOUND_ARMS = [
    ("", "declarative progress: 1/2"),
    ("status", "declarative progress: 1/2"),
    ("next", "step=2"),
    ("run", "step=2"),
    ("verify", "no structured clauses declared"),
    ("pause", "declarative workflow paused"),
    ("resume", "resume is not required"),
    ("approve", "no step is awaiting a decision"),
    ("reject 请修改", "no step is awaiting a decision"),
    ("amend 请补充", "no step is awaiting a decision"),
    ("decisions", "decisions: none recorded yet"),
    ("auto", "workflow=he-alpha-flow"),
    ("doctor", "doctor:"),
]


@pytest.mark.parametrize(("command", "expected"), _BOUND_ARMS)
@pytest.mark.asyncio
async def test_every_bound_dispatch_arm_resolves_the_frozen_binding(
    goal_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    expected: str,
) -> None:
    """goal 绑定包 A（2 步、phase 步名），配置指向不存在的包：每条绑定臂按 A 解析或显性失败。

    断言四层：臂完成自身语义（``expected`` 标记）、包可用性 / 绑定漂移错误从不出现、
    执行的步骤 prompt 全部来自 A。任一臂回潮成 settings 直连
    （``_goal_declarative_workflow()``）都会因配置包缺失而显性报「unavailable」——即红。
    """
    _make_package(goal_cwd, "he-alpha", steps=2)
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-alpha")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, "new bound arm probe", cron_store=_RecordingCronStore())
    assert len(successful_step) == 1  # 创建已完成 alpha 第 1 步
    successful_step.clear()

    # 配置翻到一个不存在的包（预校验放行、绑定解析仍必须按冻结的 he-alpha）。
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-ghost")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, command, cron_store=_RecordingCronStore())

    err = capsys.readouterr().err
    assert expected in err
    assert "unavailable" not in err
    assert "workflow binding failed" not in err
    assert all("he-ghost" not in prompt for prompt in successful_step)
    if command in {"next", "run"}:
        # 推进执行的是 alpha 的第 2 步（冻结绑定），不是配置或别的包的步骤。
        assert any("Step: step-02-phase-2.md" in prompt for prompt in successful_step)


@pytest.mark.asyncio
async def test_new_resolves_the_current_setting_not_the_previous_binding(
    goal_cwd: Path, successful_step: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """创建臂（``new`` / 裸描述）按当前配置选择包，不沿用上一个 goal 的冻结绑定。

    这是 dispatch 分支表里与绑定臂相对的**创建臂**语义：选择只发生在创建时（AD-8）。
    """
    _make_package(goal_cwd, "he-alpha", steps=2)
    _make_package(goal_cwd, "he-beta", steps=3, phase="stage")
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-alpha")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, "new first goal")
    assert _brief_frontmatter(_goal_dir(goal_cwd))["workflow"] == "he-alpha"

    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-beta")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, "new second goal")
    # 第二个 goal 按当前配置绑定 beta（3 步、stage 步名），第一个 goal 的绑定不被沿用。
    values = _brief_frontmatter(_goal_dir(goal_cwd))
    assert values["workflow"] == "he-beta"
    assert successful_step  # 第二个 goal 的第一步已按 beta 执行


# ── ④ revision 漂移 fail-loud ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_package_drift_after_creation_fails_the_restore(
    goal_cwd: Path, successful_step: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_package(goal_cwd, "he-alpha")
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-alpha")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, "new drift probe")
    goal_dir = _goal_dir(goal_cwd)
    frozen = _brief_frontmatter(goal_dir)["workflow_revision"]
    successful_step.clear()
    capsys.readouterr()

    # 包内容漂移（workflow.md 正文改动 → 派生 revision 变化）：推进必须显性阻断。
    workflow_path = goal_cwd / ".heagent" / "skills" / "he-alpha" / "workflow.md"
    workflow_path.write_text(workflow_path.read_text(encoding="utf-8") + "\nDrifted instructions.\n", encoding="utf-8")
    package = resolve_skill_package("he-alpha")
    assert package is not None
    current = workflow_revision(package, read_workflow(package, "workflow.md"))
    assert current != frozen

    await _goal_runner(SimpleNamespace(), None, "next")

    err = capsys.readouterr().err
    assert "workflow binding failed" in err
    assert frozen in err
    assert current in err
    assert goal_dir.name in err
    assert successful_step == []  # 漂移阻断在步骤执行之前


@pytest.mark.asyncio
async def test_external_step_file_drift_fails_the_restore(
    goal_cwd: Path, successful_step: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """外挂步骤文件形态（``steps:`` 声明 step-NN-*.md）：改 step 文件 → 指纹变 → 恢复显性阻断。

    51-6 审查 M1 的端到端收口：派生 revision 此前只哈希 workflow.md + 模板，外挂步骤文件
    的正文 / validation 漂移漏报。
    """
    _make_external_step_package(goal_cwd, "he-ext")
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-ext")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, "new ext probe")
    goal_dir = _goal_dir(goal_cwd)
    frozen = _brief_frontmatter(goal_dir)["workflow_revision"]
    assert len(successful_step) == 1
    successful_step.clear()
    capsys.readouterr()

    step_path = goal_cwd / ".heagent" / "skills" / "he-ext" / "step-01-first.md"
    step_path.write_text(step_path.read_text(encoding="utf-8") + "\nDrifted.\n", encoding="utf-8")
    package = resolve_skill_package("he-ext")
    assert package is not None
    current = workflow_revision(package, read_workflow(package, "workflow.md"))
    assert current != frozen

    await _goal_runner(SimpleNamespace(), None, "next")

    err = capsys.readouterr().err
    assert "workflow binding failed" in err
    assert frozen in err
    assert current in err
    assert goal_dir.name in err
    assert successful_step == []  # 漂移阻断在步骤执行之前


@pytest.mark.asyncio
async def test_package_drift_fails_the_cron_path_too(
    goal_cwd: Path, successful_step: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_package(goal_cwd, "he-alpha")
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-alpha")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, "new cron drift probe")
    goal_id = (goal_cwd / "_he-output" / "goals" / "current").read_text(encoding="utf-8").strip()
    successful_step.clear()
    workflow_path = goal_cwd / ".heagent" / "skills" / "he-alpha" / "workflow.md"
    workflow_path.write_text(workflow_path.read_text(encoding="utf-8") + "\nMore.\n", encoding="utf-8")
    capsys.readouterr()

    await cli_goal._goal_cron_advance(SimpleNamespace(), None, _FakeStore(), goal_id)  # type: ignore[arg-type]

    assert "auto stopped" in capsys.readouterr().err
    assert successful_step == []


class _FakeStore:
    """``/goal auto`` 注销路径的最小 JobStore 替身。"""

    def list_jobs(self) -> list[object]:
        return []

    def remove(self, job_id: str) -> bool:
        return False


# ── ⑤ 老 Goal 无键 → 兼容绑定注入的默认；⑦ 只读路径不改写原件 ────────


@pytest.mark.asyncio
async def test_legacy_goal_without_binding_keys_binds_the_injected_default(
    goal_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _make_package(goal_cwd, "he-beta", steps=3)
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-beta")
    reset_settings()
    goal_dir = _make_legacy_goal(goal_cwd, "legacy")
    before = (goal_dir / "brief.md").read_bytes()

    await _goal_runner(SimpleNamespace(), None, "status")

    err = capsys.readouterr().err
    # 兼容绑定注入的默认包（he-beta，3 步）驱动投影——不是 alpha，也不报「缺绑定」。
    assert "declarative progress: 0/3" in err
    # 只读路径不改写原件（AD-8）：绑定键不被回写。
    assert (goal_dir / "brief.md").read_bytes() == before


@pytest.mark.asyncio
async def test_legacy_goal_document_without_frontmatter_binds_the_default(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_package(goal_cwd, "he-plain", steps=1)
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-plain")
    reset_settings()
    goals = goal_cwd / "_he-output" / "goals"
    goal_dir = goals / "ancient"
    goal_dir.mkdir()
    (goal_dir / "brief.md").write_text("# old goal\n\nno frontmatter at all\n", encoding="utf-8")
    (goals / "current").write_text("ancient", encoding="utf-8")

    await _goal_runner(SimpleNamespace(), None, "status")

    assert "declarative progress: 0/1" in capsys.readouterr().err


# ── ⑥ 绑定缺失包显性报错 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_goal_bound_to_a_missing_package_fails_loudly(
    goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_package(goal_cwd, "he-alpha")
    goal_dir = _make_legacy_goal(goal_cwd, "orphan")
    text = (goal_dir / "brief.md").read_text(encoding="utf-8")
    (goal_dir / "brief.md").write_text(
        text.replace("---\n\n", "workflow: he-ghost\nworkflow_revision: deadbeef\n---\n\n"), encoding="utf-8"
    )

    await _goal_runner(SimpleNamespace(), None, "status")

    err = capsys.readouterr().err
    assert "he-ghost" in err
    assert "unavailable" in err


# ── 绑定模型的只读语义（不写回）───────────────────────────────────────


def test_read_workflow_binding_returns_frozen_values(tmp_path: Path) -> None:
    goal_dir = tmp_path / "goal"
    goal_dir.mkdir()
    (goal_dir / "brief.md").write_text(
        "---\nid: goal-x\ntype: requirement\nworkflow: he-alpha\nworkflow_revision: abc123\n---\n\nbody\n",
        encoding="utf-8",
    )
    binding = read_workflow_binding(goal_dir, "he-default")
    assert binding.workflow_id == "he-alpha"
    assert binding.revision == "abc123"

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "brief.md").write_text(cli_goal.goal_document("legacy", "legacy"), encoding="utf-8")
    compat = read_workflow_binding(legacy, "he-default")
    assert compat.workflow_id == "he-default"
    assert compat.revision == ""

    half = tmp_path / "half"
    half.mkdir()
    (half / "brief.md").write_text(
        "---\nid: goal-y\ntype: requirement\nworkflow: he-solo\n---\n\nbody\n", encoding="utf-8"
    )
    half_binding = read_workflow_binding(half, "he-default")
    assert half_binding.workflow_id == "he-solo"
    assert half_binding.revision == ""


def test_read_workflow_binding_rejects_a_revision_without_a_workflow_key(tmp_path: Path) -> None:
    """反向半键（有 ``workflow_revision`` 无 ``workflow``）显性抛错（51-6 审查 L3）。

    外来 revision 配到当前配置包上几乎必然误报漂移，指纹撞车则静默换包——拒绝猜测。
    """
    goal_dir = tmp_path / "reversed"
    goal_dir.mkdir()
    (goal_dir / "brief.md").write_text(
        "---\nid: goal-z\ntype: requirement\nworkflow_revision: deadbeef\n---\n\nbody\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="without the 'workflow' key"):
        read_workflow_binding(goal_dir, "he-default")


def test_resolve_bound_workflow_returns_the_bound_package(goal_cwd: Path) -> None:
    _make_package(goal_cwd, "he-alpha", steps=4)
    goal_dir = _make_legacy_goal(goal_cwd, "bound")
    text = (goal_dir / "brief.md").read_text(encoding="utf-8")
    package = resolve_skill_package("he-alpha")
    assert package is not None
    revision = workflow_revision(package, read_workflow(package, "workflow.md"))
    (goal_dir / "brief.md").write_text(
        text.replace("---\n\n", f"workflow: he-alpha\nworkflow_revision: {revision}\n---\n\n"), encoding="utf-8"
    )

    workflow = resolve_bound_workflow(goal_dir, "he-elsewhere")

    assert isinstance(workflow, WorkflowResource)
    assert len(workflow.steps) == 4  # 绑定的 alpha（4 步），不是注入的默认


# ── ⑧ 零 src 改动演示：第 5 个合成包全链路（catalog→doctor→冻结→恢复）──


@pytest.mark.asyncio
async def test_a_fifth_synthetic_package_needs_no_src_change(
    goal_cwd: Path,
    successful_step: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _make_package(goal_cwd, "he-gamma", steps=3)

    # ① catalog 发现（canonical id + 短别名两条路都可解析）。
    entries = SkillCatalog([str(goal_cwd / ".heagent" / "skills")]).scan()
    assert any(entry.canonical_id == "he-gamma" for entry in entries)
    assert resolve_skill_package("gamma") is not None
    # ② doctor 预检（无活动 goal 时 --workflow 任选包）。
    await _goal_runner(SimpleNamespace(), None, "doctor --workflow he-gamma")
    assert "workflow packages OK" in capsys.readouterr().err
    # ③ read_workflow → 冻结创建。
    await _goal_runner(SimpleNamespace(), None, "new gamma goal --workflow he-gamma")
    values = _brief_frontmatter(_goal_dir(goal_cwd))
    assert values["workflow"] == "he-gamma"
    package = resolve_skill_package("he-gamma")
    assert package is not None
    assert values["workflow_revision"] == workflow_revision(package, read_workflow(package, "workflow.md"))
    # ④ 恢复按绑定推进（默认配置指向不存在的包也不换流程）。
    successful_step.clear()
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-missing-default")
    reset_settings()
    await _goal_runner(SimpleNamespace(), None, "status")
    assert "declarative progress: 1/3" in capsys.readouterr().err
    # 声明本身可被 doctor 全绿预检（checkpoint 目录未解析时只查包与模板）。
    report = diagnose_workflow(read_workflow(package, "workflow.md"), package, resolve_skill_package)
    assert report.ok and not report.problems


# ── ⑨ frozen revision 流入 verify_step（51-4 递延接线收口）────────────


@pytest.mark.asyncio
async def test_frozen_revision_flows_into_verify_step(
    goal_cwd: Path, successful_step: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_package(goal_cwd, "he-gated", validation="artifact: reports/first.md")
    monkeypatch.setenv("GOAL_WORKFLOW_SKILL", "he-gated")
    reset_settings()
    captured: dict[str, object] = {}
    real_verify = cli_goal.verify_step

    async def spy(step: object, **kwargs: object) -> object:
        captured["revision"] = kwargs.get("revision")
        captured["workflow_id"] = kwargs.get("workflow_id")
        return await real_verify(step, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli_goal, "verify_step", spy)

    await _goal_runner(SimpleNamespace(), None, "new gated goal")

    package = resolve_skill_package("he-gated")
    assert package is not None
    expected = workflow_revision(package, read_workflow(package, "workflow.md"))
    assert captured["revision"] == expected
    assert captured["workflow_id"] == "he-gated-flow"  # workflow.name（声明值），与 revision 同一次求值携带


# ── 随包发布的 4 个模板包：catalog → loader → doctor 全绿（声明面主体）──

_SHIPPED_SKILLS = Path(__file__).resolve().parents[1] / ".heagent" / "skills"

_SHIPPED_WORKFLOW_PACKAGES = ("he-product", "he-engineering", "he-migration", "he-security")


@pytest.mark.parametrize("skill_id", _SHIPPED_WORKFLOW_PACKAGES)
def test_shipped_template_packages_pass_catalog_loader_and_doctor(skill_id: str) -> None:
    """每个随包模板包：可发现（含短别名）、可装载、doctor 预检零问题、两个模板非空。"""
    catalog = SkillCatalog([str(_SHIPPED_SKILLS)])
    entry = next(item for item in catalog.scan() if item.canonical_id == skill_id)
    assert entry.available and entry.package is not None
    package = entry.package

    from heagent.goal.application import validate_goal_workflow

    workflow = read_workflow(package, "workflow.md")
    validate_goal_workflow(workflow)  # entrypoint / on_create / step_executor 全部合规
    assert 3 <= len(workflow.steps) <= 4
    assert workflow.steps[-1].checkpoint  # final step 带 checkpoint
    assert all(not step.role for step in workflow.steps)  # 步骤不依赖本机角色包（CI 可跑）
    assert workflow.prompt_template.strip() and workflow.gate_template.strip()

    report = diagnose_workflow(workflow, package, resolve_skill_package)
    assert report.ok and not report.problems


def test_shipped_packages_cover_both_revision_paths() -> None:
    """he-engineering 演示声明 revision，其余三包演示派生路径（16 位十六进制摘要）。"""
    import re

    for skill_id in _SHIPPED_WORKFLOW_PACKAGES:
        package = resolve_skill_package(skill_id)
        assert package is not None
        workflow = read_workflow(package, "workflow.md")
        revision = workflow_revision(package, workflow)
        if skill_id == "he-engineering":
            assert workflow.revision == "1" and revision == "1"
        else:
            assert workflow.revision == ""
            assert re.fullmatch(r"[0-9a-f]{16}", revision), revision
