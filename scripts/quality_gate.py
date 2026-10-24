"""Run deterministic quality gates in fail-fast order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_TIMEOUT_SECONDS = 900

COMMANDS = (
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
    # 本地门不含这一条时，「本地全绿 / CI 全红」无从察觉（2026-10-23 实测过一次）。
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
