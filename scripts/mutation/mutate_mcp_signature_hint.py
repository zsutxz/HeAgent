"""全局 MCP 签名「显式忽略」告警的负向变异验证（A36，2026-11-05）。

不变量：项目级签名缺失时，若 ``~/.heagent/injection_signatures.json`` 存在，必须**显式告警**
说明它不会被加载。全局入口刻意不存在（零使用 ⇒ YAGNI，活动台账 A36），但静默忽略会让用户
以为围栏已生效——那才是真正的缺陷面。

本脚本把 ``src`` / ``tests`` 复制到 ``.heagent/tmp/mut-mcp-signature/`` 后逐条回退该不变量，
要求**每条变异都红**。

用法（仓库根）：

    python scripts/mutation/mutate_mcp_signature_hint.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 本文件在 scripts/mutation/ 下
MUT_ROOT = ROOT / ".heagent" / "tmp" / "mut-mcp-signature"  # 一次性产物（gitignore）
TARGET_REL = "src/heagent/tools/mcp/mapping.py"
TEST_FILE = "tests/test_mcp_mapping.py"

# (id, 说明, [(原文, 替换), ...])；每条原文必须**恰好出现一次**。
MUTATIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "M1",
        "项目级缺失时不再探测全局文件（回到静默忽略）",
        [
            (
                "    except FileNotFoundError:\n        _warn_ignored_global_signatures(global_path)\n",
                "    except FileNotFoundError:\n",
            )
        ],
    ),
    (
        "M2",
        "忽略注入的 global_path（恒探真实 home ⇒ 告警不可测、不可控）",
        [
            (
                "        probe = global_path if global_path is not None else Path.home() / _GLOBAL_SIGNATURES_HINT\n",
                "        probe = Path.home() / _GLOBAL_SIGNATURES_HINT\n",
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
    env = {
        "PYTHONPATH": str(MUT_ROOT / "src"),
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin"]),
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_FILE, "-q", "-p", "no:cacheprovider"],
        cwd=MUT_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        env=env,
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
