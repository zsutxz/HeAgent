"""变异体验证：MCP stdio 进容器（Story 53-5 / 期二 D53-1）不变量与判据强度。

用法（容器沙箱内，venv 解释器）：:

    .heagent/tmp/py311-venv-linux/bin/python scripts/mutation/mutate_mcp_stdio_sandbox.py

做法同 `mutate_approval_relax.py`：把 `src/heagent` 复制到 `.heagent/tmp/mut-mcp-sandbox/src/`
后逐条变异并跑 `tests/test_mcp_stdio_sandbox.py`，**绝不修改活树**。先跑基线，基线红即放弃。
每个变异体的锚点必须恰好命中 1 处（多点变异按列表逐条替换，任一锚点不唯一即断言失败）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".heagent/tmp/mut-mcp-sandbox"
SRC = WORK / "src"
TARGET = "src/heagent/tools/mcp/stdio_sandbox.py"

# 每个变异体 = (说明, [(old, new), ...])
MUTANTS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "M1 不降级（可用性判定恒真，宿主也当容器隔离）",
        [("    if not spec.available():\n", "    if False:\n")],
    ),
    (
        "M2 不传声明的 env 名（server 拿不到自己的 token）",
        [("    for key in sorted(cfg.env):\n", "    for key in []:\n")],
    ),
    (
        "M3 删掉 --cap-drop=ALL（硬化旗标失守）",
        [('        "--cap-drop=ALL",\n', "")],
    ),
    (
        "M4 删掉 -i（stdin 不挂 ⇒ 长命双向管道断掉）",
        [('        "-i",\n', "")],
    ),
    (
        "M5 限额旗标排到 IMAGE 之后（docker 静默失效）",
        [
            (
                '    if spec.memory_limit_mb > 0:\n        argv += ["--memory", f"{spec.memory_limit_mb}m"]\n'
                '    if spec.pids_limit > 0:\n        argv += ["--pids-limit", str(spec.pids_limit)]\n',
                "    limits: list[str] = []\n"
                '    if spec.memory_limit_mb > 0:\n        limits += ["--memory", f"{spec.memory_limit_mb}m"]\n'
                '    if spec.pids_limit > 0:\n        limits += ["--pids-limit", str(spec.pids_limit)]\n',
            ),
            (
                "    argv += [spec.image, cfg.command, *cfg.args]\n",
                "    argv += [spec.image, cfg.command, *cfg.args] + limits\n",
            ),
        ],
    ),
    (
        "M6 降级不告警（静默假装已隔离）",
        [
            (
                "        logger.warning(\n"
                "            \"MCP stdio server '%s' is NOT sandboxed (docker backend unavailable); \"\n"
                '            "running on host — explicit degradation",\n'
                "            cfg.command,\n"
                "        )\n",
                "",
            )
        ],
    ),
]


def _prepare() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "src").mkdir(parents=True)
    shutil.copytree(ROOT / "src/heagent", SRC / "heagent")


def _run_tests() -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_mcp_stdio_sandbox.py",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def main() -> int:
    original = (ROOT / TARGET).read_text(encoding="utf-8")
    _prepare()

    baseline = _run_tests()
    tail = [line for line in baseline.stdout.strip().splitlines() if line.strip()]
    print(f"[baseline] exit={baseline.returncode} {tail[-1] if tail else ''}")
    if baseline.returncode != 0:
        print("基线本身就红：先修基线，变异结论无意义。")
        return 1

    survivors: list[str] = []
    for label, replacements in MUTANTS:
        mutant = original
        for old, new in replacements:
            count = mutant.count(old)
            assert count == 1, f"变异锚点应为 1 处，实际 {count} 处：{label}"
            mutant = mutant.replace(old, new, 1)
        (SRC / "heagent/tools/mcp/stdio_sandbox.py").write_text(mutant, encoding="utf-8")
        result = _run_tests()
        tail = [line for line in result.stdout.strip().splitlines() if line.strip()]
        print(f"[{label}] exit={result.returncode} {tail[-1] if tail else ''}")
        if result.returncode == 0:
            survivors.append(label)

    (SRC / "heagent/tools/mcp/stdio_sandbox.py").write_text(original, encoding="utf-8")
    print(f"\n存活变异体 = {len(survivors)}/{len(MUTANTS)}" + (f" -> {survivors}" if survivors else " -> 全部精确变红"))
    return 0 if not survivors else 2


if __name__ == "__main__":
    sys.exit(main())
