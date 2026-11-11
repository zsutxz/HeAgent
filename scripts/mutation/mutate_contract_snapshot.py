"""契约快照判据的**强度验证**（变异体）。

为什么需要它：`scripts/contract_snapshot.py` 的判据只在真实数据上「绿」过，没证明「红了会点名」。
本脚本在**组件副本**上注入两类变异，逐一验证 `--check` 会变红并点出位置：
- M1：删 `__all__` 里一个符号（公共导出面漂移）
- M2：改基线里一个名字（基线被手改且未同步代码）

纪律：**绝不改活树**（2026-09 旧事故：`mutate_security_posture.py` 在 9p 上 `Errno 22` 把工作树
留在变异态）。全部操作在 `tmp_path` 副本里完成。

用法::

    python scripts/mutation/mutate_contract_snapshot.py

退出码：``0`` = 全部变异体都被检出（判据有强度）；``1`` = 有变异体未被检出（判据弱）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK_TIMEOUT_SECONDS = 120


def _copy_component(target: Path) -> None:
    """只复制判据依赖的最小面：脚本、基线、被测的两个模块。"""
    (target / "scripts").mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts" / "contract_snapshot.py", target / "scripts" / "contract_snapshot.py")
    shutil.copytree(
        ROOT / "tests" / "contract_baselines",
        target / "tests" / "contract_baselines",
    )
    src = target / "src" / "heagent"
    (src / "config").mkdir(parents=True)
    (src / "pub").mkdir(parents=True)
    (src / "network").mkdir(parents=True)
    for rel in (
        "src/heagent/__init__.py",
        "src/heagent/config/__init__.py",
        "src/heagent/config/catalog.py",
        "src/heagent/pub/types.py",
        "src/heagent/pub/exceptions.py",
        "src/heagent/network/http_protocol.py",
        "src/heagent/network/http_console_protocol.py",
        "src/heagent/network/http_server.py",
        "src/heagent/network/ws_host.py",
    ):
        source = ROOT / rel
        if source.is_file():
            shutil.copyfile(source, target / rel)


def _run_check(target: Path) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "scripts/contract_snapshot.py", "--check"],
        cwd=target,
        capture_output=True,
        text=True,
        timeout=CHECK_TIMEOUT_SECONDS,
    )
    return result.returncode, result.stdout + result.stderr


def _mutate_drop_export(target: Path) -> None:
    """M1：从 `config/catalog.py` 的 `__all__` 删掉一项。"""
    path = target / "src" / "heagent" / "config" / "catalog.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("__all__ = [")
    end = text.index("]", start)
    lines = text[start:end].split("\n")
    path.write_text(text[:start] + "\n".join([lines[0], *lines[2:]]) + text[end:], encoding="utf-8")


def _mutate_baseline_name(target: Path) -> None:
    """M2：直接把基线里的一个名字改掉（模拟「手改基线而不改代码」）。"""
    path = target / "tests" / "contract_baselines" / "public_exports.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = data["modules"]["heagent.config.catalog"]
    modules["defined"] = [*modules["defined"], "PHANTOM_SYMBOL_XYZ"]
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    mutants = (
        ("M1 删除 __all__ 一项", _mutate_drop_export, "public_exports.json"),
        ("M2 手改基线新增名字", _mutate_baseline_name, "public_exports.json"),
    )
    red = 0
    for label, mutate, expected_name in mutants:
        with tempfile.TemporaryDirectory(prefix="mut-contract-") as tmp:
            target = Path(tmp) / "component"
            _copy_component(target)
            mutate(target)
            code, output = _run_check(target)
        named = expected_name in output
        ok = code != 0 and named
        red += 1 if ok else 0
        print(f"[{label}] exit={code} named={named} -> {'RED (expected)' if ok else 'GREEN (MISSED!)'}")
        if not ok:
            print(output[:600])
    print(f"VERDICT: {'PASS' if red == len(mutants) else 'FAIL'} ({red}/{len(mutants)} 变异体被检出)")
    return 0 if red == len(mutants) else 1


if __name__ == "__main__":
    raise SystemExit(main())
