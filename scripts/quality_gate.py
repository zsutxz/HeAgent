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
)


def main() -> int:
    for label, command in COMMANDS:
        print(f"[quality-gate] {label}: {' '.join(command)}", flush=True)
        try:
            result = subprocess.run(command, check=False, cwd=ROOT, timeout=GATE_TIMEOUT_SECONDS)  # noqa: S603
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
