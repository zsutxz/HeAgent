"""G-10：发布面契约的只读文本断言（不引入 `pyyaml`）。

守三件事，任何一件被改掉都意味着「发版路径」变了：

1. **触发面**：`release` job 只由 `v*` tag 或 `workflow_dispatch` 触发；
2. **审批门**：`environment: release`（GitHub Environments 保护）；
3. **零 secret 发布**：`id-token: write`（PyPI Trusted Publisher OIDC）。

为什么是文本断言而不是解析 YAML：解析会给判据加一层依赖与「解析器版本差异」风险，而这里要钉的是
**仓库里那几行**。代价是措辞敏感——所以每条断言都先确认切块非空（`_release_block()` 找不到 job 时
直接失败，不会静默变成「空字符串里没有 pull_request」的假绿）。

Step 04 决策 Q2：**不启用 merge 自动发 PyPI**——`release` 只在 tag / 手动时跑，本条测试就是它的守卫。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _release_block() -> str:
    """取 `release:` job 的文本块（到下一个同级 job 标题为止）。"""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next((index for index, line in enumerate(lines) if re.match(r"^  release:$", line)), None)
    assert start is not None, "ci.yml has no top-level `release:` job"
    end = next(
        (index for index in range(start + 1, len(lines)) if re.match(r"^  [a-z][a-z0-9-]*:$", lines[index])),
        len(lines),
    )
    block = "\n".join(lines[start:end])
    assert "runs-on:" in block, f"release block looks truncated (no runs-on):\n{block[:200]}"
    return block


def test_release_job_triggers_only_on_tags_or_manual_dispatch() -> None:
    """触发条件必须是 tag 或手动 —— 不得混入 push 分支 / pull_request 自动发版。"""
    block = _release_block()
    condition = next((line.strip() for line in block.splitlines() if line.strip().startswith("if:")), None)
    assert condition is not None, "release job has no `if:` guard"
    assert "refs/tags/v" in condition, f"release is not gated on v* tags: {condition}"
    assert "workflow_dispatch" in condition, f"release does not allow manual dispatch: {condition}"
    assert "pull_request" not in condition, f"release must not run on pull_request: {condition}"


def test_release_job_uses_the_release_environment() -> None:
    """`environment: release` = GitHub Environments 的审批保护门，缺了等于无人复核就能发版。"""
    assert re.search(r"^    environment: release\b", _release_block(), flags=re.MULTILINE), (
        "release job must declare `environment: release`"
    )


def test_release_job_has_oidc_publish_permission() -> None:
    """`id-token: write`：PyPI Trusted Publisher 的前提；缺了发布只能退回长期 token。"""
    assert re.search(r"^\s+id-token:\s*write\b", _release_block(), flags=re.MULTILINE), (
        "release job must request `id-token: write` for OIDC publishing"
    )


def test_ci_job_count_is_pinned() -> None:
    """INV-9：改动只许在既有 job 里加 step，不许新建 job（job 数恒为 8）。"""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    jobs_header = next((index for index, line in enumerate(lines) if line == "jobs:"), None)
    assert jobs_header is not None, "ci.yml has no top-level `jobs:` key"
    # 只扫 `jobs:` 之后：`on:` 段里的 `push:` / `pull_request:` 也是 2 空格缩进，不能算 job。
    jobs = re.findall(r"^  ([a-z][a-z0-9-]*):$", "\n".join(lines[jobs_header:]), flags=re.MULTILINE)
    expected = {"lint", "test", "goal-smoke", "coverage", "benchmark", "dependency-review", "integration", "release"}
    assert set(jobs) == expected, f"ci.yml jobs changed: got {sorted(set(jobs))}, expected {sorted(expected)}"
