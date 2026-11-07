"""宿主写集审计**参照系换算**的负向变异验证（A43，2026-11-05）。

背景（实测矩阵，git 2.x + Python 3.11 … 3.13）：

- ``git -C <repo/sub> diff --name-only`` 报**仓库根**相对路径（``sub/inner.py``、``top.py``）；
- ``git -C <repo/sub> ls-files --others`` 报 **cwd**（= 工作区）相对路径（``inner_new.py``）；
- ``_host_artifact_relpath`` 报**工作区**相对路径。

三者只在「工作区恰为仓库根」时同形。工作区仅是仓库子目录时，宿主自写产物（已 tracked 的
``report.md`` 被重写）会以 ``sub/_he-output/...`` 出现在 `git diff` 差额里、而豁免集里只有
``_he-output/...`` ⇒ 被判越集写 ⇒ FAILED + 撤销并行授权（红测实测复现，2026-11-05）。

修复后的不变量（每条都要有判据压住）：① 产物在 tracked 差额里按仓库根相对豁免（换算生效）；
② 参照根不可知时退回旧语义（多判负、不漏判）；③ ``ls-files`` 那一支维持 cwd 相对，不能被
换算弄坏；④ 换算方向必须从工作区指向仓库根。

本脚本把 ``goal/write_audit.py`` 复制到 ``.heagent/tmp/mut-write-audit/`` 下逐条回退这些不变量，
要求**每条变异都红**（否则判据不足以护住该不变量）。

用法（在仓库根；不需要 git 仓库以外的任何依赖）：

    python scripts/mutation/mutate_write_audit_reference.py

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
MUT_ROOT = ROOT / ".heagent" / "tmp" / "mut-write-audit"  # 一次性产物（gitignore）
TARGET_REL = "src/heagent/goal/write_audit.py"
TEST_FILE = "tests/test_story_write_audit.py"

# (id, 说明, [(原文, 替换), ...])；每条原文必须**恰好出现一次**，否则脚本报错退出。
MUTATIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "M1",
        "去掉仓库根换算式（产物只按工作区相对进豁免集）",
        [
            (
                "    allowed.extend(_repo_relpath(path, workspace, toplevel) for path in artifact_paths)\n",
                "",
            )
        ],
    ),
    (
        "M2",
        "参照根恒不可知（换算永不生效，退回旧语义）",
        [
            (
                "    toplevel = _git_toplevel(workspace)\n",
                "    toplevel = None\n",
            )
        ],
    ),
    (
        "M3",
        "untracked 侧也改用仓库根相对（弄坏 cwd 相对那一支）",
        [
            (
                "        signal = [path for path in untracked_delta if path not in artifacts]\n",
                "        rooted = {_repo_relpath(p, workspace, toplevel) for p in artifacts if p}\n"
                "        signal = [path for path in untracked_delta if path not in rooted]\n",
            )
        ],
    ),
    (
        "M4",
        "换算方向反转（仓库根 → 工作区，永远 ValueError 退回恒等）",
        [
            (
                "        prefix = workspace.relative_to(toplevel).as_posix()\n",
                "        prefix = toplevel.relative_to(workspace).as_posix()\n",
            )
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
