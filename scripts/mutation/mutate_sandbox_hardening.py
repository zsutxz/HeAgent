"""Epic 53 retro A53-3：容器硬化旗标的**负向变异验证**（删旗标必须变红）。

背景：53-3 的审查修复批只证了「当前 argv 里有这些旗标」，没证「删掉之后判据会红」。本脚本把
``tools/sandbox/docker.py`` 复制到 ``.heagent/tmp/mut/`` 下逐条变异，每次跑
``tests/test_sandbox_docker.py``（不需要 docker daemon 的单测面），要求**每条变异都红**。

用法（在仓库根；不需要 docker daemon）：

    python scripts/mutate_sandbox_hardening.py

输出：每条变异一行 ``RED/GREEN`` + 失败用例数；任一条 GREEN ⇒ 退出码 1（判据不足以保护该旗标）。

**入库**（而不是放 ``.heagent/tmp/``）：epic-54 retro 的教训是「变异体脚本在 gitignore 目录 ⇒
结论无法独立复核」。它不进测试套件（是「判据强度」的元验证，不是被测行为），但必须留在仓里可复跑。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 本文件在 scripts/mutation/ 下
MUT_ROOT = ROOT / ".heagent" / "tmp" / "mut"  # 一次性产物（gitignore）
TARGET_REL = "src/heagent/tools/sandbox/docker.py"
TEST_FILE = "tests/test_sandbox_docker.py"

# (id, 说明, [(原文, 替换), ...])；每条原文必须**恰好出现一次**，否则脚本报错退出（防止变异打在错位置）。
# 多点变异（如 M9「旗标挪到镜像之后」需要**同时**删原位与追加）用多对替换表达。
MUTATIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("M1", "删 --cap-drop=ALL", [('        "--cap-drop=ALL",\n', "")]),
    ("M2", "删 --security-opt no-new-privileges", [('        "--security-opt",\n        "no-new-privileges",\n', "")]),
    ("M3", "非 root 用户退化为 root", [('        "--user",\n        user,', '        "--user",\n        "root",')]),
    (
        "M4",
        "网络隔离旗标被强制成 bridge",
        [('        "--network",\n        network,', '        "--network",\n        "bridge",')],
    ),
    ("M5", "删 --rm（容器残留）", [('        "--rm",\n', "")]),
    ("M6", "删 --pull=never（隐式拉取）", [('        "--pull=never",\n', "")]),
    (
        "M7",
        "删 --memory（限额静默失效）",
        [('    if memory_limit_mb > 0:\n        argv += ["--memory", f"{memory_limit_mb}m"]\n', "")],
    ),
    (
        "M8",
        "删 --pids-limit（进程数限额静默失效）",
        [('    if nproc_limit > 0:\n        argv += ["--pids-limit", str(nproc_limit)]\n', "")],
    ),
    (
        "M9",
        "限额旗标移到镜像名之后（docker 不解析 ⇒ 静默失效）",
        [
            (
                '    if memory_limit_mb > 0:\n        argv += ["--memory", f"{memory_limit_mb}m"]\n'
                '    if nproc_limit > 0:\n        argv += ["--pids-limit", str(nproc_limit)]\n',
                "",
            ),
            (
                '    argv += [image, "sh", "-c", command]',
                '    argv += [image]\n    if memory_limit_mb > 0:\n        argv += ["--memory", f"{memory_limit_mb}m"]\n'
                '    if nproc_limit > 0:\n        argv += ["--pids-limit", str(nproc_limit)]\n'
                '    argv += ["sh", "-c", command]',
            ),
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
        timeout=900,
        env={"PYTHONPATH": str(MUT_ROOT / "src")},
    )
    failed = 0
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(("FAILED ", "ERROR ")):
            failed += 1
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
        status = "RED" if code != 0 else "GREEN"
        print(f"[{ident}] {status} failed={failed}  {description}")
        if code == 0:
            survived.append(f"{ident} {description}")

    print("----")
    if survived:
        print(f"存活变异 {len(survived)}/{len(MUTATIONS)}（判据不足）：")
        for item in survived:
            print(f"  - {item}")
        return 1
    print(f"全部变红：{len(MUTATIONS)}/{len(MUTATIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
