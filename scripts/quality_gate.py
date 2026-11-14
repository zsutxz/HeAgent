"""Run deterministic quality gates in fail-fast order.

门序按「越便宜越先跑」排列：契约快照（~0.3s）→ goal 冒烟 → 全量回归+覆盖率 → 静态检查。
契约快照门守 INV-1/INV-2/INV-3：公共导出面、传输路由表、异常类型集合的基线漂移。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_TIMEOUT_SECONDS = 900

COMMANDS = (
    # 第 0 门：契约快照（~0.3s）。要求「六门前插一门」，守住四份基线（public / routes /
    # exceptions / transport_errors）的静默漂移；
    # 若这里红了，先用 `python scripts/contract_snapshot.py --check` 看 diff，再判断是改代码还是重生基线。
    ("contract snapshot", [sys.executable, "scripts/contract_snapshot.py", "--check"]),
    ("goal workflow smoke", [sys.executable, "-m", "pytest", "tests/test_goal_workflow_smoke.py", "-q"]),
    (
        "default regression and coverage",
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "not integration and not benchmark",
            "--cov=heagent",
            "--cov-fail-under=87",
        ],
    ),
    ("ruff lint", ["ruff", "check", "src", "tests", "scripts"]),
    ("ruff format", ["ruff", "format", "--check", "src", "tests", "scripts"]),
    ("mypy", ["mypy", "src"]),
    # CI 的 lint job 是 fail-fast 源头（bandit 失败会连带 test 矩阵全部跳过）；
    # 本地门不含这一条时，「本地全绿 / CI 全红」无从察觉（实测发生过一次）。
    ("bandit", [sys.executable, "-m", "bandit", "-r", "src/", "-ll"]),
)


def main() -> int:
    for label, command in COMMANDS:
        print(f"[quality-gate] {label}: {' '.join(command)}", flush=True)
        try:
            result = subprocess.run(command, check=False, cwd=ROOT, timeout=GATE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            print(f"[quality-gate] failed: {label} (timed out)", file=sys.stderr, flush=True)
            return 124
        except OSError as exc:
            print(f"[quality-gate] failed: {label} ({exc})", file=sys.stderr, flush=True)
            return 1
        if result.returncode != 0:
            print(f"[quality-gate] failed: {label} (exit {result.returncode})", file=sys.stderr, flush=True)
            return result.returncode
    print("[quality-gate] all gates passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
