"""CI 与本地质量门禁的一致性契约（R12）。

三个关注点，各自对应一条「静默漂移」风险：

1. **本地门 ≡ CI 覆盖面**：`scripts/quality_gate.py` 是提交前唯一全门入口，CI 的
   ``lint`` / ``coverage`` / ``goal-smoke`` 是远端闸门。两者由人手工维护时，「本地加了
   一门、CI 没加」或反向都没有任何报警——代码注释里记载过一次实测事故（本地门缺 bandit，
   本地全绿而 CI 全红）。因此这里把「每一门由哪个 job 的哪条命令承接」写成显式映射，并
   断言**映射覆盖 `quality_gate.COMMANDS` 的全部条目**：新增一门而不接线，本测试直接红。
2. **PR 触发面**：票面要求「PR 触发全量测试」。实际口径是 unit / coverage / benchmark /
   goal-smoke 都在 PR 上跑，integration **刻意只在 workflow_dispatch**（需要真实 API 密钥，
   fork PR 拿不到 secret）。刻意项在这里被钉住，免得日后被当成遗漏顺手加上。
3. **发布失败可见**：`release` job 走 ``environment: release`` 审批门 + OIDC 发布，一旦
   中途失败，PyPI 上是否有半成品版本是最要紧的判读信息。失败摘要必须落 `GITHUB_STEP_SUMMARY`。

断言是对 ci.yml 的**文本**切块，不解析 YAML：这里要钉的是「仓库里那几行」，解析会引入
解析器版本差异这层额外风险（与 `test_release_workflow_contract.py` 同一立场）。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
QUALITY_GATE = REPO_ROOT / "scripts" / "quality_gate.py"

# 本地门 → (承接它的 CI job, 该 job 里必须出现的一条命令片段)。
# 片段取「工具 + 参数面」而非整行：CI 与本地的调用形态可能不同（`ruff` vs `python -m ruff`），
# 但**参数面**是对齐的关键——把 `src tests scripts examples` 收窄成 `src` 就不会被发现，所以
# 片段里带路径面。
LOCAL_GATE_TO_CI: dict[str, tuple[str, str]] = {
    "contract snapshot": ("lint", "python scripts/contract_snapshot.py --check"),
    "goal workflow smoke": ("goal-smoke", "tests/test_goal_workflow_smoke.py"),
    "default regression and coverage": ("coverage", "--cov-fail-under=87"),
    "ruff lint": ("lint", "ruff check src tests scripts examples"),
    "ruff format": ("lint", "ruff format --check src tests scripts examples"),
    "mypy": ("lint", "mypy src"),
    "bandit": ("lint", "bandit -r src/ -ll"),
}

# CI 比本地多出来的两门：本地默认不跑（依赖漏洞扫描需联网索引、docs 构建要装 mkdocs）。
# pip-audit 的片段取完整参数面：`--strict`（依赖收集失败也判红）与 `--format json --output`
# （报告落盘供 artifact 归档）是这条门的契约，收窄成裸 `pip-audit` 就等于退回「只打屏不落证据」。
CI_ONLY_CHECKS: dict[str, tuple[str, str]] = {
    "pip-audit": ("lint", "pip-audit --strict -r requirements.lock --format json --output pip-audit.json"),
    "docs build": ("lint", "mkdocs build --strict"),
}

# 在 PR 上必须跑的分支 job（不得带 `if:` 事件过滤）。
PR_RUNNING_JOBS = ("test", "coverage", "benchmark", "goal-smoke")


def _ci_lines() -> list[str]:
    return CI_WORKFLOW.read_text(encoding="utf-8").splitlines()


def _job_block(job: str) -> str:
    """取 `jobs:` 下某个 job 的文本块（到下一个同级 job 标题为止）。"""
    lines = _ci_lines()
    start = next((index for index, line in enumerate(lines) if line == f"  {job}:"), None)
    assert start is not None, f"ci.yml has no `{job}:` job"
    end = next(
        (index for index in range(start + 1, len(lines)) if re.match(r"^  [a-z][a-z0-9-]*:$", lines[index])),
        len(lines),
    )
    block = "\n".join(lines[start:end])
    assert "runs-on:" in block, f"`{job}` block looks truncated (no runs-on):\n{block[:200]}"
    return block


def _triggers_block() -> str:
    """取 `on:` 段（到 `jobs:` 为止）——只用来判 PR 触发面。"""
    lines = _ci_lines()
    start = next((index for index, line in enumerate(lines) if line == "on:"), None)
    assert start is not None, "ci.yml has no top-level `on:` key"
    end = next((index for index in range(start + 1, len(lines)) if lines[index] == "jobs:"), len(lines))
    return "\n".join(lines[start:end])


def _quality_gate_module() -> ModuleType:
    """按文件路径加载 `scripts/quality_gate.py`（`scripts/` 不是包，不走 import 路径）。"""
    spec = importlib.util.spec_from_file_location("heagent_quality_gate_under_test", QUALITY_GATE)
    assert spec is not None and spec.loader is not None, f"cannot load {QUALITY_GATE}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runs_command(block: str, snippet: str) -> bool:
    """片段是否作为**完整命令片段**出现：右侧必须是空白或行尾。

    不做右侧边界就会退化成纯子串匹配——把 ``mypy src`` 收窄成 ``mypy src/heagent``
    仍会被判为「还在」，而这正是要拦的漂移。
    """
    return re.search(re.escape(snippet) + r"(?=\s|$)", block, flags=re.MULTILINE) is not None


def test_every_local_gate_has_a_ci_counterpart() -> None:
    """本地门集合与映射表必须一一对应：加了门不接线（或删了门留死条目）都红。"""
    labels = [label for label, _command in _quality_gate_module().COMMANDS]
    assert set(labels) == set(LOCAL_GATE_TO_CI), (
        "local quality gates and CI mapping drifted:\n"
        f"  only in quality_gate.py: {sorted(set(labels) - set(LOCAL_GATE_TO_CI))}\n"
        f"  only in mapping:        {sorted(set(LOCAL_GATE_TO_CI) - set(labels))}"
    )


def test_mapped_ci_commands_really_run() -> None:
    """每条映射的命令片段必须真的出现在声明的 job 里（改 job 名或改参数面都会红）。"""
    missing = [
        f"{label}: `{snippet}` not found in job `{job}`"
        for label, (job, snippet) in LOCAL_GATE_TO_CI.items()
        if not _runs_command(_job_block(job), snippet)
    ]
    assert not missing, "CI lost coverage for local gates:\n  " + "\n  ".join(missing)


def test_ci_only_checks_stay_in_place() -> None:
    """CI 独有的两门（依赖漏洞 / 文档构建）不得静默消失——本地跑不了的缺口只能由 CI 守。"""
    missing = [
        f"{check}: `{snippet}` not found in job `{job}`"
        for check, (job, snippet) in CI_ONLY_CHECKS.items()
        if not _runs_command(_job_block(job), snippet)
    ]
    assert not missing, "CI-only checks disappeared:\n  " + "\n  ".join(missing)


def test_pip_audit_report_is_archived_as_artifact() -> None:
    """扫描报告必须作为 artifact 上传：红了时「哪条依赖哪个 CVE」只能靠落盘 JSON 复盘。"""
    block = _job_block("lint")
    upload_step = next((step for step in block.split("- name:") if "actions/upload-artifact@v4" in step), "")
    assert upload_step, "lint job no longer uploads artifacts (pip-audit report has no archive)"
    assert "pip-audit.json" in upload_step, (
        "pip-audit report is not uploaded — a failing run would leave no machine-readable evidence"
    )
    assert re.search(r"^\s+if: always\(\)$", upload_step, flags=re.MULTILINE), (
        "the upload step must run `if: always()`, otherwise a failing audit uploads nothing"
    )


def test_local_audit_gate_is_opt_in_and_matches_ci() -> None:
    """`--with-audit` 是显式 opt-in（默认门序不含它），且参数面与 CI 逐字同源。"""
    module = _quality_gate_module()
    audit_label, audit_command = module.AUDIT_GATE
    assert audit_label not in [label for label, _command in module.COMMANDS], (
        "the audit gate must stay out of the default gate order (needs network index)"
    )
    joined = " ".join(str(part) for part in audit_command)
    for flag in ("--strict", "-r requirements.lock", "--format json", "--output"):
        assert flag in joined, f"local audit gate lost `{flag}`: {joined}"
    assert audit_label in module._NETWORK_GATE_LABELS, (
        "audit gate must be registered as a network-dependent gate (offline failures need triage hints)"
    )


def test_pull_request_runs_the_test_surface() -> None:
    """PR 触发面：所有 PR 都跑（不得加分支过滤），测试类 job 不得带事件过滤。"""
    triggers = _triggers_block()
    assert re.search(r"^  pull_request:$", triggers, flags=re.MULTILINE), "ci.yml no longer triggers on pull_request"
    pr_index = triggers.splitlines().index("  pull_request:")
    following = [line for line in triggers.splitlines()[pr_index + 1 :] if line.strip()][:1]
    assert not (following and following[0].strip().startswith("branches:")), (
        "pull_request gained a branch filter — PRs to other branches would skip the gate"
    )
    filtered = [job for job in PR_RUNNING_JOBS if re.search(r"^    if:", _job_block(job), flags=re.MULTILINE)]
    assert not filtered, f"these jobs must run on every PR but gained an `if:` filter: {filtered}"


def test_integration_tests_stay_manual_only() -> None:
    """integration 需真实 API 密钥：只允许 workflow_dispatch 触发，别顺手加进 PR。"""
    block = _job_block("integration")
    condition = next((line.strip() for line in block.splitlines() if line.strip().startswith("if:")), None)
    assert condition is not None, "integration job lost its `if:` guard — it would run on PRs without secrets"
    assert "workflow_dispatch" in condition, f"integration must stay manual: {condition}"
    assert "pull_request" not in condition, f"integration must not run on pull_request: {condition}"


def test_release_failure_is_surfaced() -> None:
    """发布失败必须留下可读摘要：PyPI 是否已吃下半成品版本，回滚决策全靠它。"""
    block = _job_block("release")
    assert re.search(r"^\s+if: failure\(\)$", block, flags=re.MULTILINE), (
        "release job has no `if: failure()` step — a failed publish would leave no summary"
    )
    failure_step = block.split("if: failure()", 1)[1]
    assert "GITHUB_STEP_SUMMARY" in failure_step.split("- name:", 1)[0], (
        "release failure step must write to $GITHUB_STEP_SUMMARY"
    )
