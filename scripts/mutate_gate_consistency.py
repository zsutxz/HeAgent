"""E2 / S-5 红化自检：证明「本地门 ↔ CI lint job 一致」判据能双向打红。

三条变异（都在隔离副本里做，永不碰工作树）：
- N1：`ci.yml` 的 `ruff check` 少扫 `scripts`（CI 少一门）
- N2：`scripts/quality_gate.py` 的 `ruff check` 少扫 `scripts`（本地少一门）
- N3：`ci.yml` 整行删掉 `mypy` 的 `run`（CI 缺一门）

任一条不变红 ⇒ 一致性判据失效，脚本退出码 1。

用法：
    .heagent/tmp/py311-venv-linux/bin/python scripts/mutate_gate_consistency.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".heagent" / "tmp" / "heagent-next-cycle" / "s-5"
TIMEOUT_SECONDS = 900
JUDGE = "tests/test_quality_gate.py::test_local_and_ci_static_commands_are_identical"

_SKIP_DIRS = {
    ".git",
    ".venv",
    ".heagent",
    "_he-output",
    "projects",
    "_bmad",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".benchmarks",
    ".test-workdirs",
    ".pytest_tmp_local",
    "logs",
}


@dataclass(frozen=True)
class Mutation:
    code: str
    target: str
    old: str
    new: str
    why: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        code="N1",
        target=".github/workflows/ci.yml",
        old="        run: ruff check src tests scripts\n",
        new="        run: ruff check src tests\n",
        why="CI 少扫 scripts ⇒ 判据须点名差异",
    ),
    Mutation(
        code="N2",
        target="scripts/quality_gate.py",
        old='("ruff lint", ["ruff", "check", "src", "tests", "scripts"]),',
        new='("ruff lint", ["ruff", "check", "src", "tests"]),',
        why="本地门少扫 scripts ⇒ 判据须点名差异",
    ),
    Mutation(
        code="N3",
        target=".github/workflows/ci.yml",
        old="      - name: Mypy (strict)\n        run: mypy src\n",
        new="",
        why="CI 整门缺失 ⇒ 判据须报「恰好 1 条」失败",
    ),
)


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _SKIP_DIRS or name.endswith(".pyc")}


def _prepare(code: str) -> Path:
    dest = WORK / code
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for entry in ROOT.iterdir():
        if entry.name in _SKIP_DIRS:
            continue
        target = dest / entry.name
        try:
            if entry.is_dir():
                shutil.copytree(entry, target, ignore=_ignore)
            else:
                shutil.copy2(entry, target)
        except (PermissionError, OSError) as exc:  # 个别本地目录不可读：跳过
            print(f"[copy] 跳过 {entry.name}：{exc}")
    return dest


def _run_jadge(workdir: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "PYTHONPATH": str(workdir / "src"),
        "PATH": f"{ROOT / '.heagent/tmp/py311-venv-linux/bin'}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(Path.home()),
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", JUDGE, "-q", "-p", "no:cacheprovider"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    baseline = _prepare("baseline")
    base = _run_jadge(baseline)
    if base.returncode != 0:
        print("[baseline] FAILED — 未变异副本本应为绿")
        print(base.stdout[-2000:])
        return 2
    print("[baseline] 绿（未变异副本可作为对照）")

    for mutation in MUTATIONS:
        workdir = _prepare(mutation.code)
        target = workdir / mutation.target
        text = target.read_text(encoding="utf-8")
        hits = text.count(mutation.old)
        if hits != 1:
            failures.append(f"{mutation.code}: 变异点命中 {hits} 次（应为 1）")
            print(f"[{mutation.code}] SKIP — 变异点不唯一")
            continue
        target.write_text(text.replace(mutation.old, mutation.new), encoding="utf-8")
        result = _run_jadge(workdir)
        red = result.returncode != 0
        print(f"[{mutation.code}] {'红（预期）' if red else '**绿了（判据失效）**'} — {mutation.why}")
        if red:
            first = next(
                (line.strip() for line in result.stdout.splitlines() if line.strip().startswith("E ")),
                "",
            )
            if first:
                print(f"        断言摘要：{first[:160]}")
        else:
            failures.append(f"{mutation.code}: 期望变红但仍是绿 —— {mutation.why}")

    print()
    if failures:
        print("FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"OK: {len(MUTATIONS)} 条变异全部精确变红（双向一致判据有效）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
