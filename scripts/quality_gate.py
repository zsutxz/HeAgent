"""Run deterministic quality gates in fail-fast order.

门序按「越便宜越先跑」排列：契约快照（~0.3s）→ goal 冒烟 → 全量回归+覆盖率 → 静态检查。
契约快照门守 INV-1/INV-2/INV-3：公共导出面、传输路由表、异常类型集合的基线漂移。

可选门 ``--with-audit``（默认不跑）：依赖漏洞扫描 `pip-audit`。它与 CI 的 `lint` job 跑同一
参数面，但需要联网索引（PyPI / OSV），无网的本地环境必红——因此不进门序，只作显式 opt-in。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]
GATE_TIMEOUT_SECONDS = 900

COMMANDS = (
    # 第 0 门：契约快照（~0.3s）。按「六门前插一门」的架构要求插入，守住五份基线（public / routes /
    # exceptions / transport_errors / error_codes）的静默漂移；
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
    ("ruff lint", ["ruff", "check", "src", "tests", "scripts", "examples"]),
    ("ruff format", ["ruff", "format", "--check", "src", "tests", "scripts", "examples"]),
    ("mypy", ["mypy", "src"]),
    # CI 的 lint job 是 fail-fast 源头（bandit 失败会连带 test 矩阵全部跳过）；
    # 本地门不含这一条时，「本地全绿 / CI 全红」无从察觉（实测发生过一次）。
    ("bandit", [sys.executable, "-m", "bandit", "-r", "src/", "-ll"]),
)

# 可选门（`--with-audit`）：依赖漏洞扫描。参数面与 CI 的 `lint` job 逐字对齐——本地复现的必须是
# CI 的同一判定，否则「本地绿 / CI 红」仍无从察觉。审计输入是 `requirements.lock`（精确可复现；
# 当前环境的本项目是 editable 安装，`--strict` 会把它当 skip 判 fatal）。报告落 `pip-audit.json`。
AUDIT_GATE = (
    "dependency audit",
    [
        sys.executable,
        "-m",
        "pip_audit",
        "--strict",
        "-r",
        "requirements.lock",
        "--format",
        "json",
        "--output",
        "pip-audit.json",
    ],
)

# 需要联网索引才能成立的门：失败时给出「无网 vs 真有漏洞」的分诊提示。
_NETWORK_GATE_LABELS = frozenset({AUDIT_GATE[0]})


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="quality_gate.py",
        description="跑确定性质量门（fail-fast）。依赖漏洞扫描需显式 --with-audit。",
    )
    parser.add_argument(
        "--with-audit",
        action="store_true",
        help="追加依赖漏洞扫描门（pip-audit --strict，需联网索引；默认不跑，避免无网环境必红）",
    )
    return parser.parse_args(argv)


def main(*, with_audit: bool = False) -> int:
    """按门序跑到底；``with_audit`` 追加依赖漏洞扫描门（默认不跑，见模块 docstring）。

    刻意不收 ``argv``：``main()`` 是**无参可调用**的既有契约（测试与脚本内复用都按它调），
    参数解析只在 ``__main__`` 入口做一次。
    """
    gates = (*COMMANDS, AUDIT_GATE) if with_audit else COMMANDS
    for label, command in gates:
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
            if label in _NETWORK_GATE_LABELS:
                # 两种成因的判据：报告文件在 ⇒ 扫描跑通了但发现漏洞；不在 ⇒ 多半是索引不可达。
                report = ROOT / "pip-audit.json"
                if report.is_file():
                    print(
                        f"[quality-gate] hint: 扫描已完成，详情见 {report.name}（有漏洞即红，逐条升级或登记例外）",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    print(
                        "[quality-gate] hint: 未生成报告——pip-audit 需访问 PyPI/OSV 索引，"
                        "无网或代理不通时会在此失败（与「代码有漏洞」是两回事）",
                        file=sys.stderr,
                        flush=True,
                    )
            return result.returncode
    print("[quality-gate] all gates passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(with_audit=_parse_args(sys.argv[1:]).with_audit))
