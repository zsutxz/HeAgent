"""契约基线守卫：INV-1/INV-2/INV-3/INV-8 与 G-1 的 pytest 化。

INV-1/INV-2/INV-3 分别守公共导出面、传输路由表、异常类型集合三份基线不漂移；
INV-8 守「传输错误码集合只增不减」——`transport_errors.json` 里的每个
``(status, code)`` 对必须仍能在当前代码里找到（删码即红并点名），且信封键集不许改形状；
G-1 守「同一棵树连跑两次快照，输出逐字节相同」——即脚本不含时间戳、绝对路径、
行号、mtime 等易变字段。

快照走 subprocess 而非 import：`scripts/contract_snapshot.py` 是纯 stdlib 的
CLI（`--check` / `--write` / `--print` / `--only`），子进程是它唯一受支持的入口；
import 会绕过 `__main__` 的参数解析与退出码语义，也就测不到 CI 真正跑的那条路径。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/contract_snapshot.py"
BASELINE_DIR = REPO_ROOT / "tests" / "contract_baselines"
BASELINE_FILES = (
    "public_exports.json",
    "transport_routes.json",
    "exception_types.json",
    "transport_errors.json",
)

# 基线里不得出现的易变字段/环境泄漏（"path" 是路由路径，属合法字段，勿列入）。
FORBIDDEN_SUBSTRINGS = ("E:\\", "/workspace", "/home/")
FORBIDDEN_KEYS = ('"lineno"', '"generated_at"', '"mtime"')


def _run_check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv 是固定字面量 + 本仓脚本路径，无外部输入
        [sys.executable, SCRIPT, "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_snapshot_check_passes() -> None:
    """`--check` 必须 exit 0；否则四份基线已与实际代码漂移。"""
    result = _run_check()
    assert result.returncode == 0, (
        f"contract snapshot drift (exit={result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_snapshot_check_is_idempotent() -> None:
    """G-1：连跑两次，stdout 逐字相同（无时间戳/绝对路径/顺序抖动）。"""
    first = _run_check()
    second = _run_check()
    assert first.returncode == 0, f"first run failed\n{first.stdout}\n{first.stderr}"
    assert second.returncode == 0, f"second run failed\n{second.stdout}\n{second.stderr}"
    assert first.stdout == second.stdout, (
        f"snapshot output is not idempotent\n--- first ---\n{first.stdout}\n--- second ---\n{second.stdout}"
    )


def _run_dump(kind: str) -> dict[str, object]:
    """以 `--print --only <kind>` 取「当前代码算出的快照」（不落盘、不比对）。"""
    result = subprocess.run(  # noqa: S603 -- argv 是固定字面量 + 本仓脚本路径，无外部输入
        [sys.executable, SCRIPT, "--print", "--only", kind],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"--print {kind} failed\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


def test_transport_error_codes_are_additive_only() -> None:
    """INV-8：基线里的每个 `(status, code)` 对必须仍在当前代码里；删码即红并点名。"""
    baseline = json.loads((BASELINE_DIR / "transport_errors.json").read_text(encoding="utf-8"))
    current = _run_dump("transport_errors")
    frozen = {(entry["status"], entry["code"]) for entry in baseline["entries"]}
    present = {(entry["status"], entry["code"]) for entry in current["entries"]}
    missing = sorted(frozen - present, key=lambda pair: (str(pair[0]), pair[1]))
    assert not missing, "INV-8 violated: transport error codes disappeared from the code\n" + "\n".join(
        f"  - status={status!r} code={code!r}" for status, code in missing
    )


def test_error_envelope_keys_are_frozen() -> None:
    """信封键集是客户端解析契约：`{"error": {...}}` 的层级与内层字段都不许变。"""
    baseline = json.loads((BASELINE_DIR / "transport_errors.json").read_text(encoding="utf-8"))
    current = _run_dump("transport_errors")
    assert current["envelope"] == baseline["envelope"], (
        f"error envelope shape changed: {baseline['envelope']} -> {current['envelope']}"
    )
    for entry in current["entries"]:
        assert entry["keys"] == baseline["envelope"]["error"], (
            f"{entry['code']}: keys {entry['keys']} != envelope inner keys {baseline['envelope']['error']}"
        )


def test_baseline_has_no_absolute_path_or_timestamp() -> None:
    """基线文本不得含绝对路径、行号、生成时间、mtime（否则每次跑都漂移）。"""
    for name in BASELINE_FILES:
        path = BASELINE_DIR / name
        assert path.is_file(), f"missing baseline: {path}"
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN_SUBSTRINGS:
            assert needle not in text, f"{name} contains environment path {needle!r}"
        for key in FORBIDDEN_KEYS:
            assert key not in text, f"{name} contains volatile key {key}"
