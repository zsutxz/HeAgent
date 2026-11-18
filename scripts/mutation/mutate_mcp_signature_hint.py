"""全局 + 项目级 MCP 签名合并语义的负向变异验证（A36；2026-11-18 改判为「真的加载」）。

不变量（三条，缺一即红）：

1. 全局文件 ``~/.heagent/injection_signatures.json`` **参与加载**（项目级缺失也生效）；
2. 同名 ``pattern`` 由**项目级覆盖**全局，且不产生重复条目；
3. 坏条目在日志里**带来源**（global / project），两级并存时报错可归因。

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
        "全局文件不再参与加载（回到「只认项目级」）",
        [
            (
                '    for source, file_path in (("global", global_file), ("project", _project_signatures_file(path))):\n',
                '    for source, file_path in (("project", _project_signatures_file(path)),):\n',
            ),
        ],
    ),
    (
        "M2",
        "合并顺序反了：全局覆盖项目（项目级不再胜出）",
        [
            (
                '    for source, file_path in (("global", global_file), ("project", _project_signatures_file(path))):\n',
                '    for source, file_path in (("project", _project_signatures_file(path)), ("global", global_file)):\n',
            ),
        ],
    ),
    (
        "M3",
        "坏条目的日志丢来源（一律写成 project，全局问题无从归因）",
        [
            (
                '        logger.error("Skipping %s signature %d: invalid regex: %s", source, index, exc)\n',
                '        logger.error("Skipping project signature %d: invalid regex: %s", index, exc)\n',
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
