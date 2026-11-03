"""变异体验证：审批降级（Story 53-4 / 期二 D53-2）五条不变量的判据强度。

用法（容器沙箱内，venv 解释器）：:

    .heagent/tmp/py311-venv-linux/bin/python scripts/mutation/mutate_approval_relax.py

做法沿用 ``mutate_sandbox_hardening.py``：把 ``src/heagent`` 复制到 ``.heagent/tmp/mut-relax/src/``
后逐条变异并跑 ``tests/test_sandbox_approval_relax.py``，**绝不修改活树**。先跑一次基线，
基线红即放弃（此时变异结论无意义）。每条变异锚点必须恰好命中 1 处，否则断言失败。

判据强度口径：每个变异体都应变红（`exit != 0`）；存活体 > 0 说明对应不变量没有被测试钉住。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".heagent/tmp/mut-relax"
SRC = WORK / "src"
TARGET = "src/heagent/engine/policy.py"

MUTANTS: list[tuple[str, str, str]] = [
    (
        "M1 完全不放松（回到接入前）",
        "        if self.sandbox_runner_provider is None:\n            return False\n",
        "        return False\n        if self.sandbox_runner_provider is None:\n            return False\n",
    ),
    (
        "M2 不看后端可用性（降级 Passthrough 也放松）",
        '        return bool(getattr(runner, "available", False))',
        "        return True",
    ),
    (
        "M3 不排除 MCP 工具",
        "        if call.name not in self.sandbox_tools or self._is_mcp_tool(call):\n            return False\n",
        "        if call.name not in self.sandbox_tools:\n            return False\n",
    ),
    (
        "M4 不要求工具进沙箱（宿主工具也放松）",
        "        if call.name not in self.sandbox_tools or self._is_mcp_tool(call):\n            return False\n",
        "        if self._is_mcp_tool(call):\n            return False\n",
    ),
    (
        "M5 不看档位（弱后端也放松，破坏 NFR-2）",
        "        if not tier.can_relax_approval:\n            return False\n",
        "",
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
            "tests/test_sandbox_approval_relax.py",
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
    for label, old, new in MUTANTS:
        count = original.count(old)
        assert count == 1, f"变异锚点应为 1 处，实际 {count} 处：{label}"
        mutant = original.replace(old, new, 1)
        (SRC / "heagent/engine/policy.py").write_text(mutant, encoding="utf-8")
        result = _run_tests()
        tail = [line for line in result.stdout.strip().splitlines() if line.strip()]
        print(f"[{label}] exit={result.returncode} {tail[-1] if tail else ''}")
        if result.returncode == 0:
            survivors.append(label)

    (SRC / "heagent/engine/policy.py").write_text(original, encoding="utf-8")
    print(f"\n存活变异体 = {len(survivors)}/{len(MUTANTS)}" + (f" -> {survivors}" if survivors else " -> 全部精确变红"))
    return 0 if not survivors else 2


if __name__ == "__main__":
    sys.exit(main())
