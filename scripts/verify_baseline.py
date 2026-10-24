"""在**干净的 HEAD 副本**上复跑同一批测试，判定「红」是不是本次改动引入的。

用法::

    python scripts/verify_baseline.py tests/test_cli_http_lifecycle.py -q
    python scripts/verify_baseline.py tests/network -q -x

为什么需要它（`docs/testing.md` 二）：本仓可能被多个会话并发编辑，`git stash` 会动工作区、影响别人；
`git worktree add --detach` 只读 HEAD、用完即删，是唯一不打扰并发编辑的取证方式。此前三个周期都把
「`test_cli_http_lifecycle` 三条端口探针红」当环境噪声——事后查明是**判据缺陷**（`bind` 撞 TIME_WAIT），
说明「凭记忆归因」不可靠，必须每次真的复跑。

退出码：``0`` = 判读完成（两边同红，或两边全绿）；``1`` = **回归**（基线绿、工作区红）；
``2`` = 脚本自身失败（含「基线跑不起来」——绝不被当成「基线绿」）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_TIMEOUT_SECONDS = 1800
_SUMMARY_FIELDS = ("passed", "failed", "error", "errors", "skipped", "deselected")


def _pytest_command(args: list[str]) -> list[str]:
    """固定 `-p no:cacheprovider`：基线副本不该在工作区留下缓存副作用。"""
    return [sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider"]


def _run(cwd: Path, args: list[str]) -> tuple[int, str]:
    """在 ``cwd`` 里跑一遍 pytest，返回 ``(exit_code, combined_output)``。"""
    env = dict(os.environ)
    src = str(cwd / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src}{os.pathsep}{existing}" if existing else src
    try:
        completed = subprocess.run(
            _pytest_command(args),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=BASELINE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"pytest timed out after {BASELINE_TIMEOUT_SECONDS}s"
    except OSError as exc:  # pragma: no cover - 环境不可用（解释器/权限）
        return 127, f"could not run pytest: {exc}"
    return completed.returncode, completed.stdout + completed.stderr


def _counts(output: str) -> dict[str, int]:
    """从 pytest 汇总行抽计数（``3 failed, 7 passed in 19.83s``）。

    逐字段取**最后一次**匹配：pytest 会在警告摘要里重复出现 ``N passed`` 之类的短语，取最后
    一次才对应真正的 summary 行。
    """
    counts: dict[str, int] = {}
    for field in _SUMMARY_FIELDS:
        matches = re.findall(rf"(\d+) {field}\b", output)
        if matches:
            counts[field] = int(matches[-1])
    return counts


def _describe(code: int, counts: dict[str, int]) -> str:
    if not counts:
        return f"exit {code}（没有解析到汇总行）"
    parts = [f"{value} {name}" for name, value in counts.items()]
    return f"exit {code}（{', '.join(parts)}）"


def _add_worktree(target: Path) -> None:
    """在 ``target`` 建一个只读 HEAD 的 worktree（``safe.directory`` 兼容容器挂载的 uid 差异）。"""
    subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "worktree", "add", "--detach", str(target), "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _remove_worktree(target: Path) -> None:
    subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "worktree", "remove", "--force", str(target)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _head_sha() -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() or "unknown"


def main(argv: list[str]) -> int:
    args = [item for item in argv if item]
    if not args:
        print(
            "usage: python scripts/verify_baseline.py <pytest args…>\n"
            "   e.g. python scripts/verify_baseline.py tests/test_cli_http_lifecycle.py -q",
            file=sys.stderr,
        )
        return 2

    baseline = ROOT / ".heagent" / "tmp" / f"baseline-{uuid.uuid4().hex[:8]}"
    print(f"[baseline] repo: {ROOT}", flush=True)
    print(f"[baseline] HEAD: {_head_sha()}", flush=True)
    try:
        _add_worktree(baseline)
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"[baseline] could not create the HEAD copy: {detail.strip()}", file=sys.stderr, flush=True)
        return 2

    try:
        work_code, work_output = _run(ROOT, args)
        base_code, base_output = _run(baseline, args)
    finally:
        _remove_worktree(baseline)

    work_counts, base_counts = _counts(work_output), _counts(base_output)
    print(f"[baseline] working tree: {_describe(work_code, work_counts)}", flush=True)
    print(f"[baseline] HEAD copy:    {_describe(base_code, base_counts)}", flush=True)

    if (work_code == 124) or (base_code in {124, 127}):
        print("[baseline] VERDICT: inconclusive（有一侧没跑起来，不能当成基线绿）", file=sys.stderr, flush=True)
        return 2
    if base_code != 0:
        print(
            "[baseline] VERDICT: environmental（基线同样红 ⇒ 与本次改动无关；汇报里写明两边数字）",
            flush=True,
        )
        return 0
    if work_code != 0:
        print(
            "[baseline] VERDICT: REGRESSION（基线绿、工作区红 ⇒ 本次改动引入，必须修）",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print("[baseline] VERDICT: clean（两边全绿）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
