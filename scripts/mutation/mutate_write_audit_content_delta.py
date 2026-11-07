"""宿主写集审计**内容级增量与补救语义**的负向变异验证（A40 / A41 / A42，2026-11-05）。

背景（2026-11-05 落地的三条收窄）：

- **A40**：Δ 由「after 路径集 \\ before 路径集」改为**内容指纹**比较。旧语义看不见「会话前
  已脏的集外 tracked 文件被本 Story 再改」——路径在两个集合里都出现，差额恒为空。
- **A41**：共享工作区里写者**无法归属**到某个 Story；消息与 `workflow_write_audit` 事件
  如实披露（`shared_workspace` + 「a sibling may be the author」），不默认让本 Story 背锅。
- **A42**：判负不再只置 FAILED + 闩——越集路径 + 基线 revision 进观测事件留档（闩后串行
  重跑的新基线已含旧违规，事件是唯一持久记录），reason 里给可执行的人工清理命令。

本脚本把 ``goal/write_audit.py`` 复制到 ``.heagent/tmp/mut-write-audit-delta/`` 下逐条回退这些
不变量，要求**每条变异都红**（否则判据不足以护住该不变量）。

用法（在仓库根）：

    python scripts/mutation/mutate_write_audit_content_delta.py

输出：每条变异一行 ``RED/GREEN`` + 失败用例数；任一条 GREEN ⇒ 退出码 1。

**入库**（而非 `.heagent/tmp/`）：判据强度结论必须能独立复核；它不进测试套件（是元验证）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 本文件在 scripts/mutation/ 下
MUT_ROOT = ROOT / ".heagent" / "tmp" / "mut-write-audit-delta"  # 一次性产物（gitignore）
TARGET_REL = "src/heagent/goal/write_audit.py"
TEST_FILE = "tests/test_story_write_audit.py"

# (id, 说明, [(原文, 替换), ...])；每条原文必须**恰好出现一次**，否则脚本报错退出。
MUTATIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "M1",
        "Δ 退回路径差集（既有脏文件被再改不可见，A40 回归）",
        [
            (
                "    changed_delta = [\n"
                "        path for path in after.changed_files if before.fingerprints.get(path) != after_fingerprints.get(path)\n"
                "    ]\n",
                "    before_paths = set(before.fingerprints)\n"
                "    changed_delta = [path for path in after.changed_files if path not in before_paths]\n",
            )
        ],
    ),
    (
        "M2",
        "判负事件不留档越集路径（A42 留档回归）",
        [
            ("        violations=violations,\n", ""),
        ],
    ),
    (
        "M3",
        "判负理由去掉人工清理指引（A42 指引回归）",
        [
            (
                '        f"parallel authorization for this goal is revoked; remediation: review with `git diff {base} -- <path>`, "\n'
                '        f"then discard with `git restore --source={base} -- <path>` (delete the path instead if it was newly created)"\n',
                '        "parallel authorization for this goal is revoked"\n',
            )
        ],
    ),
    (
        "M4",
        "归因披露恒关（共享工作区歧义被隐去，A41 回归）",
        [
            ("    shared_workspace = len(execution.batch_members) > 1\n", "    shared_workspace = False\n"),
        ],
    ),
]


def _prepare() -> Path:
    if MUT_ROOT.exists():
        shutil.rmtree(MUT_ROOT)
    shutil.copytree(ROOT / "src", MUT_ROOT / "src")
    shutil.copytree(ROOT / "tests", MUT_ROOT / "tests", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "ruff.toml", ".env.example"):
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, MUT_ROOT / name)
    return MUT_ROOT / TARGET_REL


def _run_tests() -> tuple[int, int]:
    """跑单测面；返回 ``(退出码, 失败用例数)``。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_FILE, "-q", "-p", "no:cacheprovider"],
        cwd=MUT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
        env={**os.environ, "PYTHONPATH": str(MUT_ROOT / "src")},
    )
    failed = sum(1 for line in result.stdout.splitlines() if line.strip().startswith(("FAILED ", "ERROR ")))
    return result.returncode, failed


def main() -> int:
    target = _prepare()
    pristine = target.read_text(encoding="utf-8")

    baseline_code, baseline_failed = _run_tests()
    print(f"[baseline] exit={baseline_code} failed={baseline_failed}")
    if baseline_code != 0:
        print("基线本身就红：先修基线，变异结论无意义。")
        return 2

    survived: list[str] = []
    for ident, description, patches in MUTATIONS:
        mutated = pristine
        for old, new in patches:
            count = mutated.count(old)
            if count != 1:
                print(f"[{ident}] 变异锚点出现 {count} 次（应为 1）：{description}")
                return 2
            mutated = mutated.replace(old, new)
        target.write_text(mutated, encoding="utf-8")
        try:
            code, failed = _run_tests()
        finally:
            target.write_text(pristine, encoding="utf-8")
        print(f"[{ident}] {'RED' if code != 0 else 'GREEN'} failed={failed}  {description}")
        if code == 0:
            survived.append(f"{ident} {description}")

    if survived:
        print(f"\n判据不足，以下变异未被捕获（{len(survived)}/{len(MUTATIONS)}）：")
        for item in survived:
            print(f"  - {item}")
        return 1
    print(f"\n全部 {len(MUTATIONS)} 条变异均被捕获（RED）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
