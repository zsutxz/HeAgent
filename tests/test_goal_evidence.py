"""Story 51-3：结构化执行证据——模型、追加式存储、受治理结果证据化与只读 Git 端口。

覆盖验收标准的可执行判据：成功 / 失败 / 超时 / 取消 / 策略阻断都有显式证据；命令证据含
cwd / 退出码 / 耗时 / 命令摘要 / digest / 失败分类；脱敏与大小上限；报告只能经证据 id
取回（原始 dict 无法伪装）；跨 Story / 跨 Goal 冒用被拒绝；Git 端口只读、从不 commit。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from heagent.engine.workflow_resource import StepValidationClauses
from heagent.engine.workflow_runner import required_sections
from heagent.goal.evidence import (
    _MAX_COMMAND_CHARS,
    _MAX_OUTPUT_SUMMARY_CHARS,
    _TIMEOUT_MARKING,
    EVIDENCE_SCHEMA_VERSION,
    CommandEvidence,
    CommandOutcome,
    EvidenceError,
    EvidenceRecord,
    EvidenceStore,
    UNFILTERED,
    build_command_evidence,
    classify_command_result,
    evidence_store,
    new_evidence_id,
)
from heagent.goal import git_port as git_port_module
from heagent.goal.git_port import (
    _FIXED_FLAGS,
    _MAX_QUERY_BYTES,
    _READONLY_SUBCOMMANDS,
    GitPortError,
    ReadOnlyGitPort,
    WorkspaceConflictState,
    _entry_path,
    _parse_branch_line,
)
from heagent.goal.workflow_loader import SkillWorkflowError, parse_validation_clauses, read_workflow
from heagent.memory.skill_packages import SkillPackage
from heagent.pub.types import ToolCall, ToolResult


def _call(command: str = "pytest tests/ -q", name: str = "shell", call_id: str = "call-1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={"command": command})


def _shell_result(content: str, *, is_error: bool = False, call_id: str = "call-1") -> ToolResult:
    return ToolResult(tool_call_id=call_id, content=content, is_error=is_error)


def _record(story_id: str | None = None, goal_id: str = "goal-1") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=new_evidence_id(),
        goal_id=goal_id,
        workflow_id="he-goal",
        revision="",
        step="step-07",
        story_id=story_id,
    )


# ── 受治理执行结果 → 命令证据 ────────────────────────────────────────────


def test_successful_command_forms_explicit_evidence() -> None:
    content = "exit_code=0\nstdout:\n3 passed in 1.2s\n"
    evidence = build_command_evidence(_call(), _shell_result(content), cwd="E:/proj", duration_ms=1200)

    assert evidence.outcome is CommandOutcome.SUCCEEDED
    assert evidence.exit_code == 0
    assert evidence.cwd == "E:/proj"
    assert evidence.duration_ms == 1200
    assert evidence.command == "pytest tests/ -q"
    assert evidence.output_digest == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert "3 passed" in evidence.output_summary
    assert evidence.output_truncated is False


def test_failed_command_records_nonzero_exit_code() -> None:
    evidence = build_command_evidence(
        _call(), _shell_result("exit_code=2\nstderr:\n1 failed\n"), cwd="E:/proj", duration_ms=30
    )

    assert evidence.outcome is CommandOutcome.FAILED
    assert evidence.exit_code == 2


def test_timeout_is_its_own_outcome_not_a_plain_failure() -> None:
    evidence = build_command_evidence(
        _call(), _shell_result("exit_code=-1\nstderr: Command timed out after 120s"), cwd="E:/proj"
    )

    assert evidence.outcome is CommandOutcome.TIMEOUT
    assert evidence.exit_code == -1


def test_success_short_circuits_before_the_timeout_wording() -> None:
    """退出码 0 先短路成功：输出里含 "Command timed out" 字样的成功命令不是超时（patch #1）。"""
    content = "exit_code=0\nstdout:\nretried once after Command timed out, then passed\n"
    evidence = build_command_evidence(_call(), _shell_result(content), cwd="E:/proj")

    assert evidence.outcome is CommandOutcome.SUCCEEDED
    assert evidence.exit_code == 0


def test_unparsable_exit_code_line_fails_loud() -> None:
    """``exit_code=`` 形状在但解析不出数字：显性报错，不静默落成 FAILED（patch #2）。"""
    with pytest.raises(EvidenceError, match="unparsable exit_code"):
        classify_command_result(_shell_result("exit_code=\nstdout:\nbody\n"))
    with pytest.raises(EvidenceError, match="unparsable exit_code"):
        classify_command_result(_shell_result("exit_code=abc\n"))


def test_success_outcome_with_nonzero_exit_code_is_rejected() -> None:
    """矛盾证据不进 append-only：声称成功却带非零退出码 = 调用方 bug（patch #4）。"""
    with pytest.raises(EvidenceError, match="contradictory evidence"):
        build_command_evidence(
            _call(),
            _shell_result("exit_code=3\nstderr:\nboom\n"),
            cwd="E:/proj",
            outcome=CommandOutcome.SUCCEEDED,
        )


def test_timeout_marking_stays_in_sync_with_the_governed_runner() -> None:
    """超时识别与生产方文案同源钉死：文案漂移时这里先红（patch #12）。"""
    from heagent.tools.sandbox import _TIMEOUT_RESULT

    assert _TIMEOUT_MARKING in _TIMEOUT_RESULT.format(timeout=1)


def test_command_falls_back_to_the_tool_name_and_never_empty() -> None:
    """命令摘要三级回退（命令 → target 摘要 → 工具名），模型侧 min_length=1 兜底（patch #10）。"""
    call = ToolCall(id="call-3", name="my_custom_tool", arguments={"path": "docs/x.md"})
    evidence = build_command_evidence(call, _shell_result("exit_code=0\n"), cwd="E:/proj")

    assert evidence.command  # 非 shell 工具无 command 参数 → target 摘要，仍非空
    with pytest.raises(ValueError, match="at least 1 character"):
        CommandEvidence(command="", cwd="E:/proj", outcome=CommandOutcome.FAILED)


def test_cancelled_command_without_result_needs_explicit_outcome() -> None:
    evidence = build_command_evidence(_call(), None, cwd="E:/proj", outcome=CommandOutcome.CANCELLED)

    assert evidence.outcome is CommandOutcome.CANCELLED
    assert evidence.exit_code is None
    assert evidence.output_digest == ""
    assert evidence.output_summary == ""


def test_policy_blocked_command_is_recorded_with_reason_not_exit_code() -> None:
    blocked = _shell_result("policy blocked: destructive command requires approval", is_error=True)
    evidence = build_command_evidence(_call(), blocked, cwd="E:/proj", outcome=CommandOutcome.POLICY_BLOCKED)

    assert evidence.outcome is CommandOutcome.POLICY_BLOCKED
    assert evidence.exit_code is None
    assert "policy blocked" in evidence.output_summary


def test_unclassifiable_results_fail_loud_instead_of_guessing() -> None:
    with pytest.raises(EvidenceError, match="without a result"):
        build_command_evidence(_call(), None, cwd="E:/proj")
    with pytest.raises(EvidenceError, match="explicit outcome"):
        build_command_evidence(_call(), _shell_result("Tool error: handler exploded", is_error=True), cwd="E:/proj")
    with pytest.raises(EvidenceError, match="governed shell result"):
        build_command_evidence(_call("docs/a.md", name="file_read"), _shell_result("file body"), cwd="E:/proj")


def test_nonzero_exit_code_is_never_reported_as_success() -> None:
    """变异守卫：失败被读成成功时这里必须红（负向验证 A 的锚点）。"""
    evidence = build_command_evidence(_call(), _shell_result("exit_code=1\nstderr:\nboom\n"), cwd="E:/proj")

    assert evidence.outcome is not CommandOutcome.SUCCEEDED
    assert evidence.exit_code == 1


def test_classify_reuses_the_recorded_exit_code_shape() -> None:
    assert classify_command_result(_shell_result("exit_code=0\n")) is CommandOutcome.SUCCEEDED
    assert classify_command_result(_shell_result("exit_code=3\n")) is CommandOutcome.FAILED


def test_command_evidence_requires_a_cwd() -> None:
    """cwd 是证据的一部分：丢掉 cwd（落成空串）的变异必须红。"""
    expected = str(Path.cwd().resolve())
    evidence = build_command_evidence(_call(), _shell_result("exit_code=0\n"), cwd=expected)

    assert evidence.cwd == expected
    assert evidence.cwd != ""


# ── 脱敏与上限 ────────────────────────────────────────────────────────


def test_plaintext_credentials_never_enter_evidence() -> None:
    content = "exit_code=0\nstdout:\nusing API_KEY=sk-verysecret123\nBearer abcdefghijk\n"
    evidence = build_command_evidence(
        _call("pytest tests/ -q --token supersecretvalue"), _shell_result(content), cwd="E:/proj"
    )

    assert "supersecretvalue" not in evidence.command
    assert "verysecret123" not in evidence.output_summary
    assert "abcdefghijk" not in evidence.output_summary
    # digest 始终对受治理原文计算（可复算完整性），不受脱敏影响。
    assert evidence.output_digest == hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_output_summary_is_bounded() -> None:
    content = "exit_code=0\nstdout:\n" + ("x" * 100_000) + "\n"
    evidence = build_command_evidence(_call(), _shell_result(content), cwd="E:/proj")

    assert evidence.output_truncated is True
    assert len(evidence.output_summary) <= _MAX_OUTPUT_SUMMARY_CHARS
    assert evidence.output_summary.endswith("…[truncated]")


def test_long_command_is_bounded() -> None:
    evidence = build_command_evidence(_call("echo " + ("y" * 5000)), _shell_result("exit_code=0\n"), cwd="E:/proj")

    assert len(evidence.command) <= _MAX_COMMAND_CHARS


def test_command_summary_falls_back_to_tool_target() -> None:
    call = ToolCall(id="call-2", name="git_status", arguments={})
    evidence = build_command_evidence(call, _shell_result("exit_code=0\n"), cwd="E:/proj")

    assert evidence.tool_name == "git_status"
    assert evidence.tool_call_id == "call-2"


# ── 追加式存储：定位、防覆盖、绑定校验 ────────────────────────────────────


async def test_store_roundtrips_a_record_at_a_deterministic_location(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    command = CommandEvidence(command="pytest tests/ -q", cwd="E:/proj", outcome=CommandOutcome.SUCCEEDED, exit_code=0)
    record = _record().model_copy(update={"commands": [command]})

    path = await store.append(record)

    assert path == tmp_path / "evidence" / f"{record.evidence_id}.json"
    loaded = await store.load(record.evidence_id)
    assert loaded is not None
    assert loaded.schema_version == EVIDENCE_SCHEMA_VERSION
    assert loaded.commands[0].outcome is CommandOutcome.SUCCEEDED


async def test_store_is_append_only_and_never_overwrites(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    record = _record()
    await store.append(record)

    with pytest.raises(EvidenceError, match="append-only"):
        await store.append(record.model_copy(update={"step": "step-08"}))


async def test_store_reports_corrupted_records_loudly(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    record = _record()
    await store.append(record)
    (tmp_path / f"{record.evidence_id}.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(EvidenceError, match="corrupted"):
        await store.load(record.evidence_id)
    with pytest.raises(EvidenceError, match="corrupted"):
        await store.list_records()


async def test_store_lists_by_goal_and_story(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    # created_at 显式给值：断言顺序不依赖墙钟微秒（同微秒并写由 evidence_id 定序）。
    step_level = _record().model_copy(update={"created_at": "2026-09-29T00:00:01.000000+00:00"})
    story_one = _record(story_id="S-1").model_copy(update={"created_at": "2026-09-29T00:00:02.000000+00:00"})
    other_goal = _record(goal_id="goal-2").model_copy(update={"created_at": "2026-09-29T00:00:03.000000+00:00"})
    for record in (story_one, other_goal, step_level):  # 追加顺序刻意与 created_at 顺序不同
        await store.append(record)

    all_records = await store.list_records()
    assert [record.evidence_id for record in all_records] == [
        step_level.evidence_id,
        story_one.evidence_id,
        other_goal.evidence_id,
    ]
    assert [record.evidence_id for record in await store.list_records(goal_id="goal-1")] == [
        step_level.evidence_id,
        story_one.evidence_id,
    ]
    assert [record.evidence_id for record in await store.list_records(goal_id="goal-1", story_id="S-1")] == [
        story_one.evidence_id
    ]


async def test_list_records_sentinel_keeps_none_filters_explicit(tmp_path: Path) -> None:
    """缺省 = 不过滤；显式 story_id=None 只取步骤级记录（patch #9 的显性 sentinel 语义）。"""
    store = EvidenceStore(tmp_path)
    step_level = _record(story_id=None)
    story_one = _record(story_id="S-1")
    for record in (step_level, story_one):
        await store.append(record)

    assert len(await store.list_records()) == 2
    assert [record.evidence_id for record in await store.list_records(story_id=None)] == [step_level.evidence_id]
    assert [record.evidence_id for record in await store.list_records(story_id="S-1")] == [story_one.evidence_id]
    assert UNFILTERED is not None  # sentinel 存在且不等于任何字面量


@pytest.mark.parametrize("evidence_id", ["", "..", "a/b", "a\\b", "con", "NUL", "com1", "a.json", "id with space"])
async def test_evidence_id_whitelist_rejects_unsafe_names(tmp_path: Path, evidence_id: str) -> None:
    """id 白名单：charset 之外 / Windows 保留设备名一律显性报错（patch #6）。"""
    store = EvidenceStore(tmp_path)

    with pytest.raises(EvidenceError, match=r"evidence id must match"):
        await store.load(evidence_id)


async def test_store_rejects_foreign_schema_versions(tmp_path: Path) -> None:
    """schema_version 不为当前版本：读取 / 列举 / 写入全部拒绝（patch #3，「版本化」有门）。"""
    store = EvidenceStore(tmp_path)
    foreign = _record().model_copy(update={"schema_version": "999"})
    with pytest.raises(EvidenceError, match="schema version"):
        await store.append(foreign)
    (tmp_path / f"{foreign.evidence_id}.json").write_text(
        json.dumps(foreign.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(EvidenceError, match="schema version"):
        await store.load(foreign.evidence_id)
    with pytest.raises(EvidenceError, match="schema version"):
        await store.list_records()
    with pytest.raises(EvidenceError, match="schema version"):
        await store.resolve([foreign.evidence_id], goal_id="goal-1", story_id=None)


async def test_created_at_is_utc_ordered(tmp_path: Path) -> None:
    """created_at 是 UTC（+00:00 后缀），字典序即时间序（patch #7）。"""
    record = _record()
    assert record.created_at.endswith("+00:00")
    await EvidenceStore(tmp_path).append(record)
    loaded = await EvidenceStore(tmp_path).load(record.evidence_id)
    assert loaded is not None and loaded.created_at == record.created_at


async def test_resolve_returns_records_in_report_order(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    first, second = _record(story_id="S-1"), _record(story_id="S-1")
    for record in (first, second):
        await store.append(record)

    resolved = await store.resolve(
        [first.evidence_id, second.evidence_id], goal_id="goal-1", story_id="S-1", workflow_id="he-goal"
    )

    assert [record.evidence_id for record in resolved] == [first.evidence_id, second.evidence_id]


async def test_reports_cannot_masquerade_raw_dicts_as_evidence(tmp_path: Path) -> None:
    """报告只能引用证据 id：拼一段等价原始 dict 文本不是合法 id，取不到记录即显性报错。"""
    store = EvidenceStore(tmp_path)
    raw_dict_text = '{"command": "pytest", "exit_code": 0, "outcome": "succeeded"}'

    with pytest.raises(EvidenceError, match="evidence id must match"):
        await store.resolve([raw_dict_text], goal_id="goal-1", story_id=None)
    # 形状合法但未存储的 id 同样拒绝（不存在的引用 = 伪装失败）。
    with pytest.raises(EvidenceError, match="does not exist"):
        await store.resolve(["0" * 32], goal_id="goal-1", story_id=None)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"goal_id": "goal-2", "story_id": None}, "belongs to goal"),
        ({"goal_id": "goal-1", "story_id": "S-9"}, "belongs to story"),
        ({"goal_id": "goal-1", "story_id": None}, "belongs to story"),
        ({"goal_id": "goal-1", "story_id": "S-1", "workflow_id": "other-flow"}, "workflow_id"),
        ({"goal_id": "goal-1", "story_id": "S-1", "revision": "r41"}, "revision"),
    ],
)
async def test_resolve_rejects_mismatched_bindings(tmp_path: Path, kwargs: dict, match: str) -> None:
    store = EvidenceStore(tmp_path)
    story_record = _record(story_id="S-1").model_copy(update={"workflow_id": "he-goal", "revision": "r40"})
    await store.append(story_record)

    with pytest.raises(EvidenceError, match=match):
        await store.resolve([story_record.evidence_id], **kwargs)


async def test_step_level_evidence_is_usable_without_a_story(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    record = _record(story_id=None)
    await store.append(record)

    resolved = await store.resolve([record.evidence_id], goal_id="goal-1", story_id=None)

    assert [item.evidence_id for item in resolved] == [record.evidence_id]


async def test_undeclared_binding_side_stays_usable(tmp_path: Path) -> None:
    """workflow_id / revision 任一侧未声明（空串）= 该侧未绑定，不误伤（51-6 之前无 revision）。"""
    store = EvidenceStore(tmp_path)
    record = _record()
    await store.append(record)

    resolved = await store.resolve([record.evidence_id], goal_id="goal-1", story_id=None, revision="r41")

    assert resolved[0].revision == ""


def test_evidence_location_is_a_single_resolution_point(tmp_path: Path) -> None:
    store = evidence_store(tmp_path / "goals" / "demo")

    assert store.root == tmp_path / "goals" / "demo" / "evidence"


# ── 只读 Git 端口 ─────────────────────────────────────────────────────

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - 测试夹具：受信 git、字面子命令
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_GIT_ENV, **os.environ},
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small real repository: one base commit, a worktree edit, untracked + ignored files."""
    root = tmp_path / "ws"
    (root / "pkg").mkdir(parents=True)
    _git(root, "init", "-q")
    (root / "pkg" / "app.py").write_text("print('v1')\n", encoding="utf-8")
    (root / "pkg" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    (root / ".gitignore").write_text("scratch.py\n", encoding="utf-8")
    (root / "pkg" / "lib.py").write_text("x = 2\n", encoding="utf-8")
    (root / "pkg" / "scratch.py").write_text("todo\n", encoding="utf-8")
    return root


async def test_git_evidence_covers_tracked_changes_and_untracked_files(repo: Path) -> None:
    evidence = await ReadOnlyGitPort(repo).evidence()

    assert evidence.base == "HEAD"
    assert evidence.head == _git(repo, "rev-parse", "HEAD")
    assert evidence.changed_files == ["pkg/lib.py"]
    # .gitignore 生效：被忽略的 pkg/scratch.py 不进未跟踪清单；.gitignore 自身未跟踪。
    assert evidence.untracked_files == [".gitignore"]


async def test_git_evidence_from_an_explicit_base_includes_committed_changes(repo: Path) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "second")
    base = _git(repo, "rev-parse", "HEAD~1")
    (repo / "pkg" / "lib.py").write_text("x = 3\n", encoding="utf-8")

    evidence = await ReadOnlyGitPort(repo).evidence(base)

    assert evidence.base == base
    assert evidence.head != base
    # base → 工作树：含第二次提交新增的 .gitignore 与 lib.py 的前后两次变更。
    assert evidence.changed_files == [".gitignore", "pkg/lib.py"]


async def test_git_port_never_changes_the_repository(repo: Path) -> None:
    """AD-11：端口只查询——前后 commit 历史与工作区状态逐字一致，从未 commit。"""
    port = ReadOnlyGitPort(repo)
    before_log = _git(repo, "log", "--oneline")
    before_status = _git(repo, "status", "--porcelain=v1", "-b")

    await port.head()
    await port.evidence()
    await port.evidence(await port.head())
    await port.conflict_state()

    assert _git(repo, "log", "--oneline") == before_log
    assert _git(repo, "status", "--porcelain=v1", "-b") == before_status


async def test_conflict_state_flags_a_merge_conflict_as_dangerous(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "pkg" / "lib.py").write_text("x = feature\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "feature change")
    _git(repo, "checkout", "-q", "master")
    (repo / "pkg" / "lib.py").write_text("x = master\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "master change")
    merge = subprocess.run(  # noqa: S603 - 测试夹具：受信 git、字面子命令
        ["git", "-C", str(repo), "merge", "feature"],
        capture_output=True,
        text=True,
        env={**_GIT_ENV, **os.environ},
    )
    assert merge.returncode != 0  # 前置：制造冲突成功

    state = await ReadOnlyGitPort(repo).conflict_state()

    assert state.conflicting_files == ["pkg/lib.py"]
    assert state.merge_in_progress is True
    assert state.has_unresolved_conflicts is True


async def test_conflict_state_reports_the_working_tree(repo: Path) -> None:
    state = await ReadOnlyGitPort(repo).conflict_state()

    assert state.branch in {"master", "main"}
    assert state.uncommitted_files == ["pkg/lib.py"]
    # 与 GitEvidence.untracked_files 同口径：未跟踪是**路径列表**（patch #24）。
    assert state.untracked_files == [".gitignore"]
    assert state.conflicting_files == []
    assert state.merge_in_progress is False
    assert state.has_unresolved_conflicts is False


def test_branch_line_parses_ahead_behind_gone_and_special_heads() -> None:
    assert _parse_branch_line("## master...origin/master [ahead 2, behind 3]") == (
        "master",
        "origin/master",
        2,
        3,
        False,
    )
    assert _parse_branch_line("## feature") == ("feature", "", 0, 0, False)
    assert _parse_branch_line("## master...origin/main [ahead 1]") == ("master", "origin/main", 1, 0, False)
    # [gone] 是显性信号，不得伪装成 ahead=0 / behind=0 的「同步」（patch #23）。
    assert _parse_branch_line("## master...origin/master [gone]") == ("master", "origin/master", 0, 0, True)
    assert _parse_branch_line("## topic...origin/topic [ahead 1, gone]") == ("topic", "origin/topic", 1, 0, True)
    # detached 与尚无提交（patch #23）。
    assert _parse_branch_line("## HEAD (no branch)") == ("HEAD", "", 0, 0, False)
    assert _parse_branch_line("## No commits yet on master") == ("master", "", 0, 0, False)


def test_status_entries_take_the_rename_target_quote_aware() -> None:
    """rename 取箭头右侧且引号感知；非 rename 条目里文件名含 `` -> `` 不被误拆（patch #23）。"""
    assert _entry_path('"old -> a.txt" -> "new -> b.txt"', rename=True) == "new -> b.txt"
    assert _entry_path("old.txt -> new.txt", rename=True) == "new.txt"
    assert _entry_path("pkg/a -> b.txt", rename=False) == "pkg/a -> b.txt"
    assert _entry_path('"quoted path.txt"', rename=False) == "quoted path.txt"


async def test_conflict_state_flags_a_gone_upstream_instead_of_pretending_sync(repo: Path) -> None:
    """upstream 已消失（``[gone]``）是显性信号，不伪装成 ahead=0/behind=0 的同步态（patch #23）。"""
    _git(repo, "remote", "add", "origin", "https://example.com/x.git")
    _git(repo, "config", "branch.master.remote", "origin")
    _git(repo, "config", "branch.master.merge", "refs/heads/master")

    state = await ReadOnlyGitPort(repo).conflict_state()

    assert state.upstream == "origin/master"
    assert state.upstream_gone is True
    assert state.ahead == 0 and state.behind == 0
    assert state.has_unresolved_conflicts is False


async def test_query_output_is_never_truncated(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """查询输出超预算显性报错，绝不静默截断（patch #21）。"""
    monkeypatch.setattr(git_port_module, "_MAX_QUERY_BYTES", 8)

    with pytest.raises(GitPortError, match="query budget"):
        await ReadOnlyGitPort(repo).evidence()


async def test_diff_query_pinned_to_no_external_driver(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """diff 查询实际携带 ``--no-textconv --no-ext-diff``（外部 diff 驱动被关死，patch #22）。"""
    port = ReadOnlyGitPort(repo)
    captured: list[tuple[str, tuple[str, ...]]] = []

    async def _record(subcommand: str, *args: str) -> str:
        captured.append((subcommand, args))
        return ""

    monkeypatch.setattr(port, "_run", _record)

    await port.evidence()

    diff_query = next(args for subcommand, args in captured if subcommand == "diff")
    assert "--no-textconv" in diff_query
    assert "--no-ext-diff" in diff_query


async def test_missing_git_executable_fails_loud(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """git 可执行缺失：FileNotFoundError 包成 GitPortError 上抛（patch #20）。"""

    async def _raise(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_port_module.asyncio, "create_subprocess_exec", _raise)

    with pytest.raises(GitPortError, match="not available"):
        await ReadOnlyGitPort(repo).head()


async def test_flags_outside_the_fixed_template_are_rejected(repo: Path) -> None:
    """只读纵深：旗标必须逐字来自固定模板，操作数位置不得走私旗标（patch #22）。"""
    port = ReadOnlyGitPort(repo)

    with pytest.raises(GitPortError, match="fixed query template"):
        await port._run("status", "--porcelain=v2")  # noqa: SLF001 - 判据钉的就是这个入口
    with pytest.raises(GitPortError, match="fixed query template"):
        await port._run("diff", "--output=/tmp/evil")  # noqa: SLF001
    with pytest.raises(GitPortError, match="fixed query template"):
        await port._run("rev-parse", "--verify", "--quiet", "-q")  # noqa: SLF001

    from heagent.goal.git_port import _REVISION_PATTERN

    assert _REVISION_PATTERN.match("-HEAD") is None
    assert _REVISION_PATTERN.match("-") is None
    assert _REVISION_PATTERN.match("HEAD~1") is not None
    assert set(_FIXED_FLAGS) <= _READONLY_SUBCOMMANDS


async def test_git_port_allowlist_blocks_every_write_shape(repo: Path) -> None:
    port = ReadOnlyGitPort(repo)
    mutating = ("commit", "push", "reset", "merge", "rebase", "checkout", "clean", "add")
    for subcommand in mutating:
        with pytest.raises(GitPortError, match="read-only allowlist"):
            await port._run(subcommand)  # noqa: SLF001 - 判据本身就是钉这个入口

    assert {"status", "diff", "rev-parse", "ls-files", "log", "show", "merge-base"} >= _READONLY_SUBCOMMANDS
    assert not _READONLY_SUBCOMMANDS & set(mutating)


async def test_git_port_rejects_flag_injection_through_revisions(repo: Path) -> None:
    with pytest.raises(GitPortError, match="invalid git revision"):
        await ReadOnlyGitPort(repo).evidence("--exec=evil")
    with pytest.raises(GitPortError, match="invalid git revision"):
        await ReadOnlyGitPort(repo).evidence("HEAD; rm -rf /")


async def test_git_port_fails_loud_outside_a_repository(tmp_path: Path) -> None:
    with pytest.raises(GitPortError):
        await ReadOnlyGitPort(tmp_path).head()


def test_workspace_conflict_state_defaults_are_honest() -> None:
    assert WorkspaceConflictState().has_unresolved_conflicts is False


# ── 声明面：validation: 证据子句的解析契约 ────────────────────────────────


@pytest.mark.parametrize(
    "validation_rules",
    [
        "section: 需求总结",
        "section: Story 拆分; section: Sprint 计划; 范围被拆成从 S-1 起连续编号",
        "command: pytest tests/ -q, artifact: reports/verify.md, git: src/x.py, gate: tests-pass",
        # 内嵌形态（段中 ``section:``）与引号值：两个解析器必须同结果（patch #13）。
        "must include section: X",
        'section: "A"',
        "记录验证命令, must contain section: 测试证据; command: pytest -q",
        "has plan",
        "Given a plan, when tests run, then done",
        "",
    ],
)
def test_clause_sections_agree_with_the_existing_section_parser(validation_rules: str) -> None:
    """单一解析真源：子句模型的 sections 必须与既有 ``required_sections`` 逐字一致。"""
    clauses = parse_validation_clauses(
        SkillPackage(skill_id="demo", root=Path(".")), "step-01-demo.md", validation_rules
    )

    assert clauses.sections == required_sections(validation_rules)


def test_quoted_separator_stays_one_clause_value() -> None:
    """引号保护分隔符：``command: pytest -k "a,b"`` 是一条命令，不被拆成两段（patch #15）。"""
    clauses = parse_validation_clauses(
        SkillPackage(skill_id="demo", root=Path(".")), "step-01-demo.md", 'command: pytest -k "a,b", gate: x'
    )

    assert clauses.commands == ['pytest -k "a,b"']
    assert clauses.gates == ["x"]


def test_quoted_clause_value_strips_one_outer_pair() -> None:
    clauses = parse_validation_clauses(
        SkillPackage(skill_id="demo", root=Path(".")), "step-01-demo.md", 'command: "pytest -q"'
    )

    assert clauses.commands == ["pytest -q"]


@pytest.mark.parametrize("line_feed", ["\n", "\r"])
def test_clause_value_with_a_line_feed_fails_loud(line_feed: str) -> None:
    """换行会把第二条命令走私进同一条声明：显性报错（patch #14）。"""
    with pytest.raises(SkillWorkflowError, match="single line"):
        parse_validation_clauses(
            SkillPackage(skill_id="demo", root=Path(".")), "step-01-demo.md", f"command: a{line_feed}command: b"
        )


def test_unbalanced_quote_fails_loud(tmp_path: Path) -> None:
    """引号不平衡显性报错，不静默截断半条声明（patch #15）。"""
    with pytest.raises(SkillWorkflowError, match="unbalanced quote"):
        parse_validation_clauses(
            SkillPackage(skill_id="demo", root=tmp_path), "step-01-demo.md", 'command: pytest -k "a,b gate: x'
        )


def test_clauses_parse_into_the_step_model(tmp_path: Path) -> None:
    (tmp_path / "workflow.md").write_text("---\nname: demo\nsteps: [step-01-a.md]\n---\n\n# D\n", encoding="utf-8")
    (tmp_path / "step-01-a.md").write_text(
        "---\nvalidation: section: 测试证据; command: pytest -q, artifact: reports/verify.md; "
        "git: src/heagent/goal/evidence.py, gate: tests-pass; plain text gate\n---\nBody",
        encoding="utf-8",
    )

    step = read_workflow(SkillPackage(skill_id="demo", root=tmp_path)).steps[0]
    clauses = step.validation_clauses

    assert clauses.sections == ["测试证据"]
    assert clauses.commands == ["pytest -q"]
    assert clauses.artifacts == ["reports/verify.md"]
    assert clauses.git_paths == ["src/heagent/goal/evidence.py"]
    assert clauses.gates == ["tests-pass"]
    assert clauses.declared is True
    # 原始声明串保持原样：既有文本门禁照旧读它。
    assert "plain text gate" in step.validation_rules


@pytest.mark.parametrize(
    "validation_rules",
    ["has plan", "focused tests pass", "Given a plan, when tests run, then done", "至少三条实质性不同的方向"],
)
def test_plain_validation_text_requires_no_evidence(tmp_path: Path, validation_rules: str) -> None:
    """老包语义不变：不声明证据子句 = 不要求证据。"""
    (tmp_path / "workflow.md").write_text("---\nname: demo\nsteps: [step-01-a.md]\n---\n\n# D\n", encoding="utf-8")
    (tmp_path / "step-01-a.md").write_text(f"---\nvalidation: {validation_rules}\n---\nBody", encoding="utf-8")

    step = read_workflow(SkillPackage(skill_id="demo", root=tmp_path)).steps[0]

    assert step.validation_clauses.declared is False
    assert step.validation_clauses.model_dump() == {
        "sections": [],
        "commands": [],
        "artifacts": [],
        "git_paths": [],
        "gates": [],
    }


def test_unknown_validation_clause_fails_loud_at_load(tmp_path: Path) -> None:
    (tmp_path / "workflow.md").write_text("---\nname: demo\nsteps: [step-01-a.md]\n---\n\n# D\n", encoding="utf-8")
    (tmp_path / "step-01-a.md").write_text(
        "---\nvalidation: section: A, commandz: pytest -q\n---\nBody", encoding="utf-8"
    )

    with pytest.raises(SkillWorkflowError, match="unknown validation clause 'commandz:'"):
        read_workflow(SkillPackage(skill_id="demo", root=tmp_path))


@pytest.mark.parametrize("value", ["", "   "])
def test_clause_without_a_value_fails_loud(tmp_path: Path, value: str) -> None:
    with pytest.raises(SkillWorkflowError, match="requires a value"):
        parse_validation_clauses(
            SkillPackage(skill_id="demo", root=tmp_path), "step-01-a.md", f"section: A; command:{value}"
        )


@pytest.mark.parametrize("clause", ["artifact", "git"])
@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../outside.py", "a/../../b.md", "C:/Windows/system32", "C:relative.py"]
)
def test_path_clauses_must_stay_inside_the_workspace(tmp_path: Path, clause: str, path: str) -> None:
    """含 Windows 盘符**相对**路径（``C:foo``，patch #16）：绝对 / 逃逸一律报错。"""
    with pytest.raises(SkillWorkflowError, match="workspace-relative"):
        parse_validation_clauses(SkillPackage(skill_id="demo", root=tmp_path), "step-01-a.md", f"{clause}: {path}")


def test_clause_model_rejects_unsafe_paths_even_when_built_directly() -> None:
    """绕过 loader 直接构造模型同样受路径守卫约束（patch #17）。"""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="workspace-relative"):
        StepValidationClauses(artifacts=["../escape.md"])
    with pytest.raises(pydantic.ValidationError, match="workspace-relative"):
        StepValidationClauses(git_paths=["C:relative.py"])
    assert StepValidationClauses(artifacts=["reports/ok.md"]).artifacts == ["reports/ok.md"]


def test_real_workflow_package_parses_its_declared_sections() -> None:
    """真实包（存在时）的声明经生产加载器解析后与既有解析器一致（防两处解析漂移）。"""
    root = Path(__file__).resolve().parents[1] / ".heagent" / "skills" / "he-goal"
    if not root.is_dir():
        pytest.skip("he-goal package is not installed in this checkout")
    steps = read_workflow(SkillPackage(skill_id="he-goal", root=root), "workflow.md").steps

    declared = [step for step in steps if step.validation_clauses.declared]
    assert declared, "he-goal 声明了 section 子句；解析后应非空"
    for step in steps:
        assert step.validation_clauses.sections == required_sections(step.validation_rules)
