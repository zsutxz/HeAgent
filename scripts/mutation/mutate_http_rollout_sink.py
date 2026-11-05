"""网页入口 **rollout 订阅**的负向变异验证（A35 前置缺口，2026-11-05）。

修复后的不变量（每条都要有判据压住）：

1. 网页 handler 的 engine 真的订阅事件接收器 —— 否则 ``EVENTS_ROLLOUT_ENABLED`` 在网页入口
   仍是死键（与 A44 闭合前的交互 REPL 同款问题）；
2. 落盘根是**项目根**而不是进程 cwd —— 多项目控制台里二者不等，按 cwd 落盘会把 A 项目事件
   写进 B 项目的 ``.heagent/runs``；
3. 开关关闭时**不落盘**（rollout 含工具原始输出，默认关闭是安全默认，不能被顺手破坏）。

本脚本把 ``src`` / ``tests`` 复制到 ``.heagent/tmp/mut-http-rollout/`` 后逐条回退上述不变量，
要求**每条变异都红**（否则判据不足以护住该不变量）。

用法（仓库根）：

    python scripts/mutation/mutate_http_rollout_sink.py

输出：每条变异一行 ``RED/GREEN`` + 失败用例数；任一条 GREEN ⇒ 退出码 1。

**入库**（而非 ``.heagent/tmp/``）：判据强度结论必须能独立复核；它不进测试套件（是元验证）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 本文件在 scripts/mutation/ 下
MUT_ROOT = ROOT / ".heagent" / "tmp" / "mut-http-rollout"  # 一次性产物（gitignore）
TEST_FILE = "tests/test_http_events_rollout.py"

# (id, 目标文件（相对仓库根）, 说明, [(原文, 替换), ...])；每条原文必须**恰好出现一次**。
MUTATIONS: list[tuple[str, str, str, list[tuple[str, str]]]] = [
    (
        "M1",
        "src/heagent/cli/http_console.py",
        "网页 handler 不再订阅事件接收器（开关回到死键）",
        [
            (
                "        sink = _build_event_sink(self.settings, json_output=False, root=paths.root)\n"
                "        if sink is not None:\n"
                "            self.engine.events.subscribe(sink)\n",
                "",
            )
        ],
    ),
    (
        "M2",
        "src/heagent/cli/http_console.py",
        "落盘根退回进程 cwd（多项目控制台下会写错项目）",
        [
            (
                "        sink = _build_event_sink(self.settings, json_output=False, root=paths.root)\n",
                "        sink = _build_event_sink(self.settings, json_output=False)\n",
            )
        ],
    ),
    (
        "M3",
        "src/heagent/cli/composition.py",
        "绕过 EVENTS_ROLLOUT_ENABLED（默认关闭被破坏，rollout 含工具原始输出）",
        [
            (
                "    rollout_dir = default_rollout_dir(root) if settings.events_rollout_enabled else None\n",
                "    rollout_dir = default_rollout_dir(root)\n",
            )
        ],
    ),
]


def _prepare() -> None:
    if MUT_ROOT.exists():
        shutil.rmtree(MUT_ROOT)
    shutil.copytree(ROOT / "src", MUT_ROOT / "src")
    shutil.copytree(ROOT / "tests", MUT_ROOT / "tests", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "ruff.toml", ".env.example"):
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, MUT_ROOT / name)


def _run_tests() -> tuple[int, int]:
    """跑被测用例集；返回 ``(退出码, 失败用例数)``。"""
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
    _prepare()
    pristine = {rel: (MUT_ROOT / rel).read_text(encoding="utf-8") for _id, rel, _d, _p in MUTATIONS}

    baseline_code, baseline_failed = _run_tests()
    print(f"[baseline] exit={baseline_code} failed={baseline_failed}")
    if baseline_code != 0:
        print("基线本身就红：先修基线，变异结论无意义。")
        return 2

    survived: list[str] = []
    for ident, rel, description, patches in MUTATIONS:
        target = MUT_ROOT / rel
        mutated = pristine[rel]
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
            target.write_text(pristine[rel], encoding="utf-8")
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
