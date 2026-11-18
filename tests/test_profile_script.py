"""性能分析脚本（`scripts/profile_run.py`）判据。

断言三件「脚本存在但用不了」的典型失效：

1. 能跑起来并落报告（模块目标 + 参数转发）；
2. 目标**崩了也要留报告**（那正是最需要剖面的时刻），且退出码如实反映失败；
3. 报告里真的有热点函数段（不是只有一句「success」）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_SCRIPT = REPO_ROOT / "scripts" / "profile_run.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("heagent_profile_run_under_test", PROFILE_SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot load {PROFILE_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def profile_script() -> ModuleType:
    return _load_script()


def _write_target(directory: Path, name: str, body: str) -> None:
    (directory / f"{name}.py").write_text(body, encoding="utf-8")


def test_split_argv_separates_target_arguments(profile_script: ModuleType) -> None:
    """`--` 之前是本脚本参数，之后原样转给目标。"""
    head, tail = profile_script.split_argv(["--module", "pytest", "--", "tests/test_cli.py", "-q"])
    assert head == ["--module", "pytest"]
    assert tail == ["tests/test_cli.py", "-q"]
    assert profile_script.split_argv(["--script", "x.py"]) == (["--script", "x.py"], [])


def test_profile_module_writes_report(
    profile_script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """模块目标：报告落盘、含热点段，且 `--` 之后的参数真的进了目标 `sys.argv`。"""
    _write_target(
        tmp_path,
        "prof_target_ok",
        "import sys\n"
        "def work(n):\n"
        "    return sum(i * i for i in range(n))\n"
        "if __name__ == '__main__':\n"
        "    print('argv:', sys.argv[1:])\n"
        "    work(2000)\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    out = tmp_path / "report.txt"

    code = profile_script.main(["--module", "prof_target_ok", "--out", str(out), "--", "alpha", "beta"])

    assert code == 0
    report = out.read_text(encoding="utf-8")
    assert "Hottest functions (by tottime)" in report
    assert "Callers / callees" in report
    assert "prof_target_ok" in report
    assert "['alpha', 'beta']" in capsys.readouterr().out


def test_target_failure_still_leaves_a_report(
    profile_script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """目标抛异常：退出码 1、stderr 点名异常类型、报告仍然落盘。"""
    _write_target(tmp_path, "prof_target_boom", "raise RuntimeError('kaboom')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    out = tmp_path / "boom.txt"

    code = profile_script.main(["--module", "prof_target_boom", "--out", str(out)])

    assert code == 1
    assert out.is_file()
    assert "RuntimeError: kaboom" in capsys.readouterr().err


def test_system_exit_codes_are_propagated(
    profile_script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """目标的 `SystemExit` 是真的退出码（pytest 失败即 1），不能被吞成 0。"""
    _write_target(tmp_path, "prof_target_exit", "raise SystemExit(3)\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    code = profile_script.main(["--module", "prof_target_exit", "--out", str(tmp_path / "exit.txt")])

    assert code == 3


def test_hot_functions_ranks_by_self_time(profile_script: ModuleType) -> None:
    """热点按 tottime 降序：重活函数必须排在轻函数之前（cumtime 排序会把它俩混在一起）。

    刻意在单元层构造剖面（而不是跑一次端到端）：全量回归里进程可能带着别的线程，
    `cProfile` 是进程级钩子，会把噪声算进来——「谁比谁热」这个关系在受控剖面里才稳。
    """

    def heavy() -> int:
        total = 0
        for i in range(300_000):
            total += i
        return total

    def light() -> int:
        return 1

    profile = profile_script.cProfile.Profile()
    profile.enable()
    try:
        heavy()
        light()
    finally:
        profile.disable()

    lines = profile_script.hot_functions(profile, limit=20)
    heavy_index = next(index for index, line in enumerate(lines) if "(heavy)" in line)
    light_index = next((index for index, line in enumerate(lines) if "(light)" in line), len(lines))
    assert heavy_index < light_index, lines
    # 排序口径本身：每行解析出的 tottime 必须单调不增。
    tottimes = [float(line.split("s tottime")[0]) for line in lines]
    assert tottimes == sorted(tottimes, reverse=True), tottimes
