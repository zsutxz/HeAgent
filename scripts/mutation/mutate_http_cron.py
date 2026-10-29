"""红化自检：证明「网页入口拥有完整 cron 工具面」的接线判据能打红。

两条变异（都在隔离副本里做，永不碰工作树）：
- N1：``new_loop`` 退回 ``enable_cron=False``（网页侧重新拿不到 cron 工具）
- N2：``new_loop`` 见到 ``CronScheduler`` 即 raise（旧 A11② 形态，前提是它不启停调度器）

任一条不变红 ⇒ 对应用例失效，脚本退出码 1。

用法：
    .heagent/tmp/py311-venv-linux/bin/python scripts/mutate_http_cron.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".heagent" / "tmp" / "heagent-http-cron"
TIMEOUT_SECONDS = 600

# 只复制跑单条判据所需的东西：整仓 500M+（含 logs / _he-output / news）会把这个脚本拖成分钟级。
_COPY_ENTRIES = ("src", "tests", "pyproject.toml", "ruff.toml")
_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}

_JUDGE = "tests/test_cli_http.py::test_new_loop_binds_the_full_cron_surface"


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
        target="src/heagent/cli/http_console.py",
        old="            enable_cron=True,\n",
        new="            enable_cron=False,\n",
        why="退回 enable_cron=False ⇒ 网页侧重新拿不到 cron 工具（cron_store 为 None）",
    ),
    Mutation(
        code="N2",
        target="src/heagent/cli/http_console.py",
        old="        return loop\n\n    async def __call__(",
        new=(
            "        if _scheduler is not None:\n"
            '            raise RuntimeError("HTTP runtime must not own a CronScheduler")\n'
            "        return loop\n\n    async def __call__("
        ),
        why="见到 CronScheduler 即 raise ⇒ 完整 cron 面在 handler 里不可实现",
    ),
)


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _SKIP_DIRS or name.endswith(".pyc")}


def _prepare(code: str) -> Path:
    dest = WORK / code
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in _COPY_ENTRIES:
        source = ROOT / name
        target = dest / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=_ignore)
        else:
            shutil.copy2(source, target)
    return dest


def _run_judge(workdir: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "PYTHONPATH": str(workdir / "src"),
        "PATH": f"{ROOT / '.heagent/tmp/py311-venv-linux/bin'}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(Path.home()),
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", _JUDGE, "-q", "-p", "no:cacheprovider"],
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
    base = _run_judge(baseline)
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
        result = _run_judge(workdir)
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
    print(f"OK: {len(MUTATIONS)} 条变异全部精确变红（网页 cron 面判据有效）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
