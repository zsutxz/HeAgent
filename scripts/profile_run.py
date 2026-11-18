"""性能分析脚本：用标准库 ``cProfile`` 给任意模块 / 脚本做一次剖面，落一份可读报告。

**为什么用 cProfile 而不是 py-spy**：``cProfile`` 是标准库，零新依赖、可在 CI 与容器里直接跑；
``py-spy`` 的价值在「attach 已在运行的进程」（本仓用例：``heagent http-server`` 挂着排障），
它是外部二进制、需要 root 或 ``ptrace`` 权限，因此不写进脚本依赖，只在下文给用法。

用法：

```bash
# 剖面一个模块（`--` 之后原样转给目标，例如 pytest 的参数）
python scripts/profile_run.py --module pytest -- tests/test_agent_loop.py -q
python scripts/profile_run.py --module heagent -- "快速排序"

# 剖面一个脚本文件
python scripts/profile_run.py --script scripts/collect_stats.py

# 报告落点与深度
python scripts/profile_run.py --module pytest --out .heagent/tmp/pytest.prof.txt --top 40 -- tests/test_cli.py
```

产出：``--out`` 指定的文本报告（默认 ``.heagent/tmp/profile-<时间戳>.txt``），内容 =
运行元信息 + 按 ``cumtime`` 排序的函数表 + 「热点函数」摘要（按 ``tottime`` 排序取前 10）。
stdout 同时打印热点摘要，便于不打开文件就定位。

「attach 正在运行的进程」的等价做法（需另装 py-spy）：

```bash
py-spy record -o .heagent/tmp/heagent.svg --pid <PID>      # 火焰图
py-spy top --pid <PID>                                     # 实时热点
```
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import runpy
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / ".heagent" / "tmp"
DEFAULT_TOP = 25
HOTTEST_COUNT = 10

#: 目标进程内的 ``sys.argv`` 首项（报告里也用它标注「这次剖面的是谁」）。
_TARGET_LABEL = "{kind} {name}"


def split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """把命令行切成「本脚本的参数」与「目标程序的参数」（分隔符是 ``--``）。"""
    if "--" not in argv:
        return argv, []
    index = argv.index("--")
    return argv[:index], argv[index + 1 :]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="profile_run",
        description="Profile a Python module or script with cProfile and write a readable report.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("-m", "--module", help="要剖面的模块名（按 runpy.run_module 执行）")
    target.add_argument("--script", help="要剖面的脚本路径（按 runpy.run_path 执行）")
    parser.add_argument("--out", default=None, help="报告落点（默认 .heagent/tmp/profile-<时间戳>.txt）")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help=f"函数表列出条数（默认 {DEFAULT_TOP}）")
    return parser.parse_args(argv)


def _run_target(profile: cProfile.Profile, module: str | None, script: str | None, target_argv: list[str]) -> int:
    """在进程内跑目标并采集剖面；目标的 ``SystemExit`` 转成返回码，其它异常也要留下报告。"""
    label = _TARGET_LABEL.format(kind="module" if module else "script", name=module or script)
    saved_argv = sys.argv
    sys.argv = [label, *target_argv]
    code = 0
    profile.enable()
    try:
        if module:
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        else:
            runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        # pytest / argparse 的正常退出通道：有整数码就用它，None 视为成功。
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException as exc:  # 目标崩了正是最需要报告的时刻
        profile.disable()
        print(f"[profile] target raised {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        code = 1
    finally:
        profile.disable()
        sys.argv = saved_argv
    return code


def hot_functions(profile: cProfile.Profile, limit: int = HOTTEST_COUNT) -> list[str]:
    """按 ``tottime``（自身耗时，不含子调用）取前 N 个热点函数，一行一个。

    ``tottime`` 才是「改这里能省时间」的信号；``cumtime`` 排出来的往往是 ``main`` / ``runpy``
    这类调度壳，对定位无用。
    """
    stats = pstats.Stats(profile)
    entries: list[tuple[float, float, int, str]] = []
    for (filename, lineno, funcname), (_cc, call_count, total_time, cumulative_time, _callers) in stats.stats.items():
        entries.append((total_time, cumulative_time, call_count, f"{filename}:{lineno}({funcname})"))
    entries.sort(key=lambda item: item[0], reverse=True)
    return [
        f"{total:8.3f}s tottime  {cumulative:8.3f}s cumtime  {calls:7d} calls  {name}"
        for total, cumulative, calls, name in entries[:limit]
    ]


def build_report(profile: cProfile.Profile, label: str, top: int) -> str:
    """拼出报告正文：元信息 + cumtime 函数表 + 热点摘要。"""
    buffer = io.StringIO()
    buffer.write(f"# cProfile report — {label}\n")
    buffer.write(f"# generated: {datetime.now().isoformat(timespec='seconds')}\n")
    buffer.write(f"# python: {sys.version.splitlines()[0]}\n\n")
    buffer.write("## Hottest functions (by tottime)\n")
    for line in hot_functions(profile):
        buffer.write(f"{line}\n")
    buffer.write("\n## Callers / callees (sorted by cumulative time)\n")
    pstats.Stats(profile, stream=buffer).sort_stats("cumulative").print_stats(top)
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    head, target_argv = split_argv(list(sys.argv[1:] if argv is None else argv))
    args = parse_args(head)
    out_path = (
        Path(args.out) if args.out else DEFAULT_OUT_DIR / f"profile-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    profile = cProfile.Profile()
    label = _TARGET_LABEL.format(kind="module" if args.module else "script", name=args.module or args.script)
    code = _run_target(profile, args.module, args.script, target_argv)

    report = build_report(profile, label, args.top)
    out_path.write_text(report, encoding="utf-8")

    print(f"[profile] {label} → exit {code}", flush=True)
    print("[profile] hottest functions (tottime):", flush=True)
    for line in hot_functions(profile):
        print(f"  {line}", flush=True)
    print(f"[profile] full report: {out_path}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
