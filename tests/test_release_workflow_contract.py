"""发布面契约：workflow 三要素（只读文本断言）+ 版本号单一真源（A51 缺口）。

**workflow 三要素**（G-10），任何一件被改掉都意味着「发版路径」变了：

1. **触发面**：`release` job 只由 `v*` tag 或 `workflow_dispatch` 触发；
2. **审批门**：`environment: release`（GitHub Environments 保护）；
3. **零 secret 发布**：`id-token: write`（PyPI Trusted Publisher OIDC）。

为什么是文本断言而不是解析 YAML：解析会给判据加一层依赖与「解析器版本差异」风险，而这里要钉的是
**仓库里那几行**。代价是措辞敏感——所以每条断言都先确认切块非空（`_release_block()` 找不到 job 时
直接失败，不会静默变成「空字符串里没有 pull_request」的假绿）。

**版本号单一真源**（A51 的第一半缺口）：版本号有两处真源——`src/heagent/__init__.py` 的
``__version__``（运行期 `heagent.__version__`、WS hello 帧的注入源）与 `pyproject.toml` 的
``project.version``（打包元数据、release job 提取 tag 失败时的回退源）。两处靠人手工同步时，
bump 漏改一处**不会有任何门禁报警**，而 PyPI 不允许重传同版本号 ⇒ 发出去就不可撤销。
本文件把它变成秒级判据，并在 HEAD 恰好带 `v*` tag 时顺带校验 tag 与版本一致。

Step 04 决策 Q2：**不启用 merge 自动发 PyPI**——`release` 只在 tag / 手动时跑，本条测试就是它的守卫。
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
INIT_MODULE = REPO_ROOT / "src" / "heagent" / "__init__.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"


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


# --------------------------------------------------- 版本号单一真源（A51 缺口）


def _module_version() -> str:
    """`src/heagent/__init__.py` 的 ``__version__``（AST 取值，不 import 整个包）。"""
    tree = ast.parse(INIT_MODULE.read_text(encoding="utf-8"), filename=str(INIT_MODULE))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    value = ast.literal_eval(node.value)
                    assert isinstance(value, str), f"__version__ is not a string literal: {value!r}"
                    return value
    raise AssertionError(f'{INIT_MODULE} has no module-level `__version__ = "..."`')


def _pyproject_version() -> str:
    """`pyproject.toml` 的 ``project.version``（`tomllib` 是 3.11+ 标准库，无新依赖）。"""
    import tomllib

    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_package_version_has_a_single_source() -> None:
    """两处真源必须相等：模块常量（运行期 / hello 帧）与打包元数据（release 回退源）。"""
    module_version = _module_version()
    packaged_version = _pyproject_version()
    assert module_version == packaged_version, (
        "版本号两处真源不一致（PyPI 不允许重传同版本号，发出去不可撤销）\n"
        f"  src/heagent/__init__.py: {module_version}\n"
        f"  pyproject.toml:          {packaged_version}"
    )


def test_version_is_plain_semver() -> None:
    """`X.Y.Z` 纯数字段：挡住 `0.9`、`v0.9.0`、日期式版本这类手误（tag 前缀另行处理）。"""
    version = _module_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"version is not plain X.Y.Z: {version!r}"
    assert not version.startswith("v"), f"version must not carry the tag prefix: {version!r}"


# ------------------------------------------------------- CHANGELOG 载体（A51）

CHANGELOG = REPO_ROOT / "CHANGELOG.md"

#: `## [Unreleased]` / `## [0.9.0] - 2026-11-11`
CHANGELOG_HEADING = re.compile(r"^## \[(?P<label>Unreleased|\d+\.\d+\.\d+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?$")


def _changelog_text() -> str:
    assert CHANGELOG.is_file(), f"missing {CHANGELOG.name}: 发布变更没有载体（A51 的残余缺口）"
    return CHANGELOG.read_text(encoding="utf-8")


def _changelog_headings() -> list[re.Match[str]]:
    return [match for line in _changelog_text().splitlines() if (match := CHANGELOG_HEADING.match(line))]


def test_changelog_has_unreleased_section() -> None:
    """`## [Unreleased]` 段必须常驻：没有它，下一个版本的改动就无处落笔。"""
    labels = [match.group("label") for match in _changelog_headings()]
    assert "Unreleased" in labels, f"CHANGELOG.md has no `## [Unreleased]` heading (found: {labels})"


def test_changelog_has_entry_for_current_version() -> None:
    """当前 `__version__` 必须有对应版本节 —— bump 版本却忘了写变更是最常见的漏项。"""
    version = _module_version()
    entries = {match.group("label"): match.group("date") for match in _changelog_headings()}
    assert version in entries, (
        f"CHANGELOG.md has no entry for the current version {version} (found: {sorted(entries)})\n"
        "bump 版本号时同步把 `## [Unreleased]` 的内容落成版本节"
    )
    assert entries[version], f"CHANGELOG.md entry for {version} has no `- YYYY-MM-DD` release date"


def test_changelog_headings_are_well_formed() -> None:
    """`## [` 开头的行必须全部是 `[X.Y.Z] - YYYY-MM-DD` 或裸 `[Unreleased]`。"""
    malformed = [
        line
        for line in _changelog_text().splitlines()
        if line.startswith("## [") and CHANGELOG_HEADING.match(line) is None
    ]
    assert not malformed, "CHANGELOG.md headings must be `## [X.Y.Z] - YYYY-MM-DD` or `## [Unreleased]`:\n" + "\n".join(
        f"  - {line}" for line in malformed
    )
    unreleased = [m for m in _changelog_headings() if m.group("label") == "Unreleased"]
    assert len(unreleased) == 1, f"CHANGELOG.md must have exactly one Unreleased heading, found {len(unreleased)}"
    assert unreleased[0].group("date") is None, "`## [Unreleased]` must not carry a release date"


def test_head_tag_matches_version_when_present() -> None:
    """HEAD 恰好带 `v*` tag 时，tag 必须与版本一致（发布那一刻的判据）。

    无 git / 仓库未 fetch tags / HEAD 无 tag ⇒ **跳过**：本仓的 tag 是在发布时手动打的，
    「没打 tag」是常态，不该算失败。CI 的 checkout 默认不取 tags，故此处在这条路径上会跳过。
    """
    if shutil.which("git") is None:
        import pytest

        pytest.skip("git not available")
    try:
        result = subprocess.run(  # noqa: S603 -- 固定 argv，无外部输入
            ["git", "-c", "safe.directory=*", "tag", "--points-at", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - 环境异常
        import pytest

        pytest.skip(f"git tag unavailable: {exc}")
    if result.returncode != 0:  # pragma: no cover - 环境异常
        import pytest

        pytest.skip(f"git tag failed: {result.stderr.strip()[:120]}")
    tags = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("v")]
    if not tags:
        import pytest

        pytest.skip("HEAD carries no v* tag (tags are created at release time)")
    version = _module_version()
    mismatched = [tag for tag in tags if tag.lstrip("v") != version]
    assert not mismatched, (
        f"HEAD tag(s) disagree with __version__ {version}: {mismatched}\n"
        "打 tag 前先 bump 版本号，否则 PyPI 会拒收同版本号"
    )
